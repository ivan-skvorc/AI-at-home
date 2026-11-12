"""Return a finished workflow's result to the conversation that launched it.

Exactly once per workflow run. The host admits at most one run per idempotency
key (``workflow-result:<run>``, namespaced to this plugin), so two deliverers
racing (a retry, a second Gateway) get the same run back; the delivery row
leaves ``pending`` once and never regresses. A busy conversation (an active run,
an open question, an interrupt) is retried later, never interrupted; a start the
spend cap refuses (402) is waited out the same way.

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

from deerflow_extension_api import PLUGIN_OPTIONS_CONTEXT_KEY, AgentRunError

from .constants import NAMESPACE
from .ultracode import MODE, MODE_DOUBLE, MODES, RESULT_MESSAGE_PREFIX

logger = logging.getLogger(__name__)

DELIVERABLE = frozenset({"completed", "failed", "needs_reconciliation", "waiting_input", "interrupted"})
SKIPPED = frozenset({"cancelled"})
RETRY_DELAYS = (2, 4, 8, 15, 30, 60)
#: Failed attempts (timeouts, unexpected statuses) before delivery waits for the
#: owner's next workflow action instead.
MAX_ATTEMPTS = 60
#: How long a result waits out a busy conversation (a run in progress, an open
#: question, an interrupt). A long task in the launching chat must not make the
#: result give up, so these waits do not count as failed attempts.
BUSY_WAIT_SECONDS = 24 * 3600
BUSY = "Waiting for the conversation to finish its current turn"
SPEND_CAP = "Spend cap reached; the result is posted once a new run is allowed"


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
        # The whole ID: it is what inspect_workflow_step takes.
        f"[Workflow result] {name} ({run_id}) ended: {record['status']}.",
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
        unfinished = [step for step in steps if step["status"] != "completed"]
        if unfinished:
            shown = [f"{step['step_id']} ({step['status']})" + (f": {str(step['error'])[:160]}" if step.get("error") else "") for step in unfinished[:20]]
            lines.append("Unfinished steps: " + "; ".join(shown) + (f" (+{len(unfinished) - 20} more)" if len(unfinished) > 20 else ""))
    return "\n".join(lines)


def result_context(record):
    """Run context of the result turn. Derived from the record: every retry sends the same start.

    The turn gets the launching run's options back (the limits as the record
    clamped them), so a follow-up workflow the lead launches from it keeps the
    mode, the user's limits, the model and the internet switch; and it runs on
    the conversation's model with the conversation's internet switch itself.
    """
    context, options = {}, {}
    mode = record.get("mode")
    if mode in MODES:
        limits = record["limits"]
        options.update(mode=mode, max_agents=limits["max_calls"], max_parallel=limits["concurrency"])
        # Double Plus has no wall clock to pass on.
        if mode == MODE:
            options["max_minutes"] = max(1, limits["timeout_seconds"] // 60)
    if record.get("model"):
        context["model_name"] = options["model"] = record["model"]
    if record.get("internet_enabled") is False:
        context["internet_enabled"] = options["internet_enabled"] = False
    # The host lifts its automatic limits only for a run whose context says so.
    if mode == MODE_DOUBLE:
        context["mode"] = MODE_DOUBLE
    if options:
        context[PLUGIN_OPTIONS_CONTEXT_KEY] = {NAMESPACE: options}
    return context or None


class Delivery:
    def schedule_delivery(self, owner, run_id, runs):
        if not self.config["deliver_results"] or runs is None or not self.available:
            return
        key = (owner, run_id)
        if key in self.deliveries:
            # A task that already saw the workflow running may be about to end
            # with "wait": run once more after it, so the end is never missed.
            self.delivery_rearm[key] = runs
            return
        task = asyncio.create_task(self.deliver(owner, run_id, runs))
        self.deliveries[key] = task
        task.add_done_callback(lambda finished: self.delivery_finished(key, finished))

    def delivery_finished(self, key, task):
        self.deliveries.pop(key, None)
        rearm = self.delivery_rearm.pop(key, None)
        if task.cancelled():
            return
        if task.exception() is not None:
            logger.error("Workflow %s result delivery failed (%s); it stays pending", key[1], type(task.exception()).__name__)
        elif rearm is not None:
            self.schedule_delivery(key[0], key[1], rearm)

    async def resume_deliveries(self, owner, runs):
        """Re-arm deliveries a restart left pending, with this caller's fresh handle."""
        if runs is None or not self.config["deliver_results"] or not self.available:
            return
        for run_id in await asyncio.to_thread(self.store.pending_deliveries, owner):
            self.schedule_delivery(owner, run_id, runs)

    async def deliver(self, owner, run_id, runs):
        failures = busy = 0
        waited = 0.0
        while failures < MAX_ATTEMPTS and waited < BUSY_WAIT_SECONDS:
            outcome = await self.deliver_once(owner, run_id, runs)
            if outcome == "busy":
                delay = RETRY_DELAYS[min(busy, len(RETRY_DELAYS) - 1)]
                busy += 1
                waited += delay
            elif outcome == "retry":
                delay = RETRY_DELAYS[min(failures, len(RETRY_DELAYS) - 1)]
                failures += 1
            else:
                return outcome
            await asyncio.sleep(delay)
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
                await asyncio.to_thread(self.store.delivery_note, owner, run_id, BUSY)
                return "busy"
            while True:
                try:
                    async with asyncio.timeout(self.config["admission_timeout_seconds"]):
                        run = await runs.start(
                            thread_id=thread_id,
                            input={"messages": [{"role": "user", "id": f"{RESULT_MESSAGE_PREFIX}{run_id[:32]}", "content": result_message(record)}]},
                            context=result_context(record),
                            idempotency_key=f"workflow-result:{run_id}",
                        )
                    break
                except AgentRunError as exc:
                    if exc.status_code not in (400, 422) or not record.get("model"):
                        raise
                    # The conversation's model is a default: when the host refuses it
                    # (removed or renamed since launch) the result is posted on the
                    # server's. Stored first so every retry sends the same start; a
                    # clustered store retired the ended record's lease, so there the
                    # drop is repeated per attempt and the idempotency key keeps one run.
                    record["model"] = None
                    if not self.clustered:
                        await self.save(owner, record)
        except AgentRunError as exc:
            if exc.status_code == 409:
                await asyncio.to_thread(self.store.delivery_note, owner, run_id, BUSY)
                return "busy"
            if exc.status_code == 404:
                await asyncio.to_thread(self.store.delivery_finish, owner, run_id, "failed", error="The launching conversation is no longer available")
                return "done"
            if exc.status_code in (401, 403):
                await asyncio.to_thread(self.store.delivery_note, owner, run_id, "Sign in again to post this result")
                return "stop"
            if exc.status_code == 402:
                # The cap's window reopens without any owner action, so this is
                # waited out like a busy conversation rather than abandoned.
                await asyncio.to_thread(self.store.delivery_note, owner, run_id, SPEND_CAP)
                return "busy"
            await asyncio.to_thread(self.store.delivery_note, owner, run_id, f"Delivery deferred ({exc.status_code})")
            return "retry"
        except TimeoutError:
            # An uncertain start is safe to repeat: the idempotency key returns the same run.
            await asyncio.to_thread(self.store.delivery_note, owner, run_id, "Delivery timed out; retrying")
            return "retry"
        await asyncio.to_thread(self.store.delivery_finish, owner, run_id, "delivered", run_id=run.run_id)
        return "done"
