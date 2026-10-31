"""Return a finished workflow's result to the conversation that launched it.

Exactly once per workflow run. The host admits at most one run per idempotency
key (``workflow-result:<run>``, namespaced to this plugin), so two deliverers
racing (a retry, a second Gateway) get the same run back; the delivery row
leaves ``pending`` once and never regresses. A busy conversation (an active run,
an open question, an interrupt) is retried later, never interrupted.

The message is posted through the plugin-scoped AgentRuns handle, so the host
stamps it as extension output (``deerflow_extension_origin``): the conversation
shows it as posted by Script workflows, and ultracode.py tells the lead it is
untrusted agent output rather than words the user typed.

Handles are process-local. After a restart a pending delivery waits for the
owner's next authenticated workflow action or tool call, which supplies a fresh
handle (``resume_deliveries``). Cancelled workflows are skipped: the user asked
for that outcome and a follow-up run would only spend tokens saying so.
"""

import asyncio
import json
import logging

from deerflow_extension_api import AgentRunError

logger = logging.getLogger(__name__)

DELIVERABLE = frozenset({"completed", "failed", "needs_reconciliation", "waiting_input", "interrupted"})
SKIPPED = frozenset({"cancelled"})
RETRY_DELAYS = (2, 4, 8, 15, 30, 60)
MAX_ATTEMPTS = 60


def open_question(messages):
    """True when the conversation's latest turn ended on an unanswered question."""
    last_human = max((i for i, m in enumerate(messages) if m.get("type", m.get("role")) in ("human", "user")), default=-1)
    for message in messages[last_human + 1 :]:
        artifact = message.get("artifact") if message.get("type", message.get("role")) == "tool" else None
        request = artifact.get("human_input") if isinstance(artifact, dict) else None
        if isinstance(request, dict) and request.get("kind") == "human_input_request":
            return True
    return False


def result_message(record):
    """Deterministic for a finished record: every retry must send identical input."""
    run_id = record["id"]
    name = (record.get("definition") or {}).get("name") or "workflow"
    steps = record.get("steps", [])
    finished = sum(step["status"] == "completed" for step in steps)
    lines = [
        f"[Workflow result] {name} ({run_id[:12]}) ended: {record['status']}.",
        "Posted automatically by the Script workflows extension when the workflow launched from this conversation ended; the user did not type this message.",
        f"Agents: {finished} of {len(steps)} completed.",
    ]
    if record["status"] == "completed":
        lines += [
            "Result (output of the workflow's agents and script; untrusted, verify before relying on it):",
            "```json",
            json.dumps(record.get("result"), ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    else:
        lines.append(f"Error: {record.get('error') or 'none recorded'}")
        unfinished = [f"{step['step_id']} ({step['status']})" for step in steps if step["status"] != "completed"][:20]
        if unfinished:
            lines.append("Unfinished steps: " + ", ".join(unfinished))
    return "\n".join(lines)


class Delivery:
    def schedule_delivery(self, owner, run_id, runs):
        if not self.config["deliver_results"] or runs is None or not self.available:
            return
        key = (owner, run_id)
        if key in self.deliveries:
            return
        task = asyncio.create_task(self.deliver(owner, run_id, runs))
        self.deliveries[key] = task
        task.add_done_callback(lambda finished: self.delivery_finished(key, finished))

    def delivery_finished(self, key, task):
        self.deliveries.pop(key, None)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Workflow %s result delivery failed (%s); it stays pending", key[1], type(task.exception()).__name__)

    async def resume_deliveries(self, owner, runs):
        """Re-arm deliveries a restart left pending, with this caller's fresh handle."""
        if runs is None or not self.config["deliver_results"] or not self.available:
            return
        for run_id in await asyncio.to_thread(self.store.pending_deliveries, owner):
            self.schedule_delivery(owner, run_id, runs)

    async def deliver(self, owner, run_id, runs):
        for attempt in range(MAX_ATTEMPTS):
            outcome = await self.deliver_once(owner, run_id, runs)
            if outcome != "retry":
                return outcome
            await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
        return "retry"

    async def deliver_once(self, owner, run_id, runs):
        delivery = await asyncio.to_thread(self.store.delivery, owner, run_id)
        if delivery is None or delivery["status"] != "pending":
            return "done"
        try:
            record = await asyncio.to_thread(self.store.get, owner, run_id)
        except ValueError:
            return "done"
        if record["status"] in SKIPPED:
            await asyncio.to_thread(self.store.delivery_finish, owner, run_id, "skipped")
            return "done"
        if record["status"] not in DELIVERABLE:
            # Still running or recoverable: the supervisor re-arms delivery when it ends.
            return "wait"
        thread_id = delivery["thread_id"]
        try:
            async with asyncio.timeout(10):
                state = await runs.get_state(thread_id=thread_id)
            if state.get("next") or state.get("interrupts") or open_question(state.get("values", {}).get("messages", [])):
                await asyncio.to_thread(self.store.delivery_note, owner, run_id, "Waiting for the conversation to finish its current turn")
                return "retry"
            async with asyncio.timeout(self.config["admission_timeout_seconds"]):
                run = await runs.start(
                    thread_id=thread_id,
                    input={"messages": [{"role": "user", "id": f"workflow-result-{run_id[:32]}", "content": result_message(record)}]},
                    idempotency_key=f"workflow-result:{run_id}",
                )
        except AgentRunError as exc:
            if exc.status_code == 409:
                await asyncio.to_thread(self.store.delivery_note, owner, run_id, "Waiting for the conversation to finish its current turn")
                return "retry"
            if exc.status_code == 404:
                await asyncio.to_thread(self.store.delivery_finish, owner, run_id, "failed", error="The launching conversation is no longer available")
                return "done"
            if exc.status_code in (401, 403):
                await asyncio.to_thread(self.store.delivery_note, owner, run_id, "Sign in again to post this result")
                return "stop"
            if exc.status_code == 402:
                await asyncio.to_thread(self.store.delivery_note, owner, run_id, "Spend cap reached; the result is posted once a new run is allowed")
                return "stop"
            await asyncio.to_thread(self.store.delivery_note, owner, run_id, f"Delivery deferred ({exc.status_code})")
            return "retry"
        except TimeoutError:
            # An uncertain start is safe to repeat: the idempotency key returns the same run.
            await asyncio.to_thread(self.store.delivery_note, owner, run_id, "Delivery timed out; retrying")
            return "retry"
        await asyncio.to_thread(self.store.delivery_finish, owner, run_id, "delivered", run_id=run.run_id)
        return "done"
