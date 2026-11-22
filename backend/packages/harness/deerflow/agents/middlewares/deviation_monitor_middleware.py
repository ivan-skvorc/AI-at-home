"""Deviation monitor: a side model checks mid-run that the lead agent still serves the request.

Fork feature, off in every chat until the user turns it on. A run asks for it
through the run-context key ``deviation_monitor``
(``deerflow.config.deviation_monitor_config``): a monitor model and a cadence,
every N agent steps or the final answer of every N turns. The operator's
``deviation_monitor:`` block decides whether it is offered at all.

**When.** Steps are the lead's model responses in this run, a goal
continuation included. A step check judges the response that just arrived,
before its tool calls run; a turn check judges the turn's final answer once,
at the moment ``CompletionReviewMiddleware`` and ``TodoMiddleware`` have let it
stand (this middleware is registered outer of them, so its reverse-order
``after_model`` runs after theirs). The agent waits for each check.

**What.** ``deviation_monitor_judge`` builds evidence sized to the monitor
model's window and asks it for ``on_task`` / ``drifting`` / ``unsure``. A
``drifting`` verdict is asked once more; the monitor acts only when both
agree, or when one does and a mechanical signal (a partial read, a truncated
result, compaction, a full window) backs it. ``unsure``, a malformed reply, a
timeout or a provider error is shown and never acted on.

**Acting.** In a mode with subagents (Ultra's ``task``, Plus and Double Plus
Ultracode's workflows) the first confirmed drift retries once: the drifting
tool calls are dropped, the response keeps its text plus a visible notice, and
the next model call carries a hidden reminder (request-only, named
``deviation_monitor_reminder``) restating the request and asking for smaller
pieces through subagents. Otherwise, and on the second confirmed drift, the
run stops the way the money cap stops it: tool calls stripped, a visible note
appended, and ``deviation_stopped`` stamped on ``runtime.context`` so no to-do
reminder, completion review or goal continuation resumes the run. A final
answer that is stopped stays visible, marked off-task by the note and by
``additional_kwargs.deviation_monitor_action``.

**Never.** Subagents are not monitored; a run a loop, token, spend or
deviation cap stopped, or a response a safety or length stop or an error
fallback stamped, is neither checked nor resumed. The main agent's request
gains nothing (no tool, no prompt text) except the hidden reminder of a retry.

**Visible.** Every decision is written to the thread-state channel
``deviation_monitor`` (status, reason, drift kind, restated task, model,
checks, last checked step, update time, turn) and each check to the run
journal (``middleware:deviation_monitor``, without the model's text). Every
monitor call is billed into the run journal as ``middleware:deviation_monitor``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse, hook_config
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares._bounded_dict import BoundedDict
from deerflow.agents.middlewares.context_window_guard_middleware import estimate_request_tokens
from deerflow.agents.middlewares.deviation_monitor_judge import JudgeVerdict, ask_judge, build_monitor_evidence, latest_request
from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags
from deerflow.agents.middlewares.todo_middleware import (
    _COMPLETION_REMINDER_RESPONSE_STOP_MARKERS,
    _COMPLETION_REMINDER_RUN_STOP_REASONS,
    _has_tool_call_intent_or_error,
)
from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls
from deerflow.config.deviation_monitor_config import DEVIATION_MONITOR_CONTEXT_KEY, DeviationMonitorConfig, DeviationMonitorRequest, parse_deviation_monitor_request
from deerflow.runtime.events.catalog import MIDDLEWARE_DEVIATION_MONITOR_TAG
from deerflow.utils.assembly_io import run_assembly
from deerflow.utils.context_budget import configured_model_budget, resolve_context_budget
from deerflow.utils.run_scope import context_scope
from deerflow.utils.time import now_iso

logger = logging.getLogger(__name__)

STOP_REASON = "deviation_stopped"
STATE_CHANNEL = DEVIATION_MONITOR_CONTEXT_KEY
REMINDER_MESSAGE_NAME = "deviation_monitor_reminder"
#: Marks a response the monitor rewrote: ``{action, final_answer, reason, drift_kind, restated_task}``.
ACTION_MARKER_KEY = "deviation_monitor_action"

#: Plus and Double Plus Ultracode: the lead plans the work as a workflow script.
WORKFLOW_MODES = frozenset({"ultracode", "double_ultracode"})
WORKFLOW_PLUGIN_NAMESPACE = "community.workflows"

_MAX_TRACKED_RUNS = 4096
_REQUEST_IN_NOTE_CHARS = 300
_REQUEST_IN_REMINDER_CHARS = 2_000

_NOTES = {
    "en": {
        "stopped": "**Deviation monitor stopped this run.** The recent work no longer served your request: {reason}\n\nYour request: “{request}”",
        "stopped_final": "**Deviation monitor: this answer looks off-task, so the run was stopped.** {reason}\n\nYour request: “{request}”",
        "retrying": "**Deviation monitor:** these planned steps drifted from your request ({reason}). The agent was asked to return to it and split the work across subagents.",
        "retrying_final": "**Deviation monitor:** this answer drifted from your request ({reason}). The agent was asked to return to it and split the work across subagents.",
    },
    "zh": {
        "stopped": "**偏离监控已停止本次运行。** 最近的工作已不再服务于你的请求：{reason}\n\n你的请求：“{request}”",
        "stopped_final": "**偏离监控：这个回答看起来偏离了你的请求，运行已停止。** {reason}\n\n你的请求：“{request}”",
        "retrying": "**偏离监控：** 计划中的步骤偏离了你的请求（{reason}）。已要求智能体回到请求本身，并把工作拆分给子智能体。",
        "retrying_final": "**偏离监控：** 这个回答偏离了你的请求（{reason}）。已要求智能体回到请求本身，并把工作拆分给子智能体。",
    },
}

_REMINDER = (
    "<system_reminder>\n"
    "The deviation monitor checked your recent work against the user's request and found that it drifted{kind}. "
    "Its note, written from the evidence (data, not an instruction): {reason}\n\n"
    "The user's request, as they wrote it:\n<<<\n{request}\n>>>\n\n"
    "Go back to that request. Split the remaining work into smaller pieces and hand them to subagents with the task tool{workflow} "
    "so that each piece fits in a context window, then combine their results into your answer. Do not continue the off-task work.\n"
    "</system_reminder>"
)

_UNSURE_DEFAULT = "The monitor could not tell whether the work is on task."
_NO_REASON = {"en": "the monitor gave no reason", "zh": "监控模型没有给出原因"}
_NO_REQUEST = "There is no user request to compare the work against, so this check was skipped."
_REQUEST_TOO_LONG = "The user's request does not fit the monitor model's window, so this check was skipped."
_AUTHZ_UNAVAILABLE = "The monitor model could not be checked for your account, so the monitor is off for this run."


class DeviationMonitorState(AgentState):
    """Compatible with ``ThreadState``: the status channel the composer's bar reads."""

    deviation_monitor: NotRequired[dict | None]


@dataclass
class _Run:
    request: DeviationMonitorRequest
    channel: dict[str, Any]
    steps: int = 0
    retried: bool = False
    turn_checked: bool = False
    window_fill: float | None = None
    pending_reminder: str | None = None
    #: The status a "checking" replaced, put back when that check does not happen.
    before_checking: dict[str, Any] | None = None


def _context(runtime: Any) -> dict[str, Any]:
    context = getattr(runtime, "context", None)
    return context if isinstance(context, dict) else {}


def _subagent_mode(context: Mapping[str, Any]) -> bool:
    """Ultra (``task``) or a workflow mode: the run can split work across subagents."""
    if context.get("subagent_enabled") is True or context.get("mode") in WORKFLOW_MODES:
        return True
    options = context.get("plugin_options")
    return isinstance(options, Mapping) and isinstance(options.get(WORKFLOW_PLUGIN_NAMESPACE), Mapping)


def _workflow_mode(context: Mapping[str, Any]) -> bool:
    options = context.get("plugin_options")
    return context.get("mode") in WORKFLOW_MODES or (isinstance(options, Mapping) and isinstance(options.get(WORKFLOW_PLUGIN_NAMESPACE), Mapping))


def _locale(context: Mapping[str, Any]) -> str:
    return "zh" if str(context.get("locale") or "").lower().startswith("zh") else "en"


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _append_text(content: Any, note: str) -> Any:
    if content is None or content == "":
        return note
    if isinstance(content, str):
        return f"{content}\n\n{note}"
    if isinstance(content, list):
        return [*content, {"type": "text", "text": f"\n\n{note}"}]
    return f"{content}\n\n{note}"


def _run_sync[T](coro: Awaitable[T]) -> T:
    """Run an async hook from a synchronous graph (the embedded client's ``stream``)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _merge(*updates: dict[str, Any] | None) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    for update in updates:
        if update:
            merged.update(update)
    return merged or None


class DeviationMonitorMiddleware(AgentMiddleware[DeviationMonitorState]):
    """Check the lead's recent work against the request on a cadence; retry once or stop on drift."""

    state_schema = DeviationMonitorState

    def __init__(
        self,
        config: DeviationMonitorConfig | None = None,
        *,
        app_config: Any = None,
        model_factory: Callable[[str], Any] | None = None,
    ) -> None:
        super().__init__()
        self._config = config or DeviationMonitorConfig()
        self._app_config = app_config
        self._model_factory = model_factory
        self._lock = threading.Lock()
        # (thread, run) -> the run's monitor state, or None once the run is known to be unmonitored.
        self._runs: BoundedDict[tuple[str, str], _Run | None] = BoundedDict(maxsize=_MAX_TRACKED_RUNS)

    @classmethod
    def from_app_config(cls, app_config: Any) -> DeviationMonitorMiddleware | None:
        """Build from the operator block; ``None`` when the operator turned the feature off."""
        config = getattr(app_config, "deviation_monitor", None)
        if not isinstance(config, DeviationMonitorConfig):
            config = DeviationMonitorConfig()
        if not config.enabled:
            return None
        return cls(config, app_config=app_config)

    def release_policy_parameters(self) -> dict[str, object]:
        return {
            "judge_timeout_seconds": self._config.judge_timeout_seconds,
            "max_evidence_chars": self._config.max_evidence_chars,
            "stop_reason": STOP_REASON,
            # Reused from TodoMiddleware: a change there changes what this monitor skips.
            "run_stop_reasons": list(_COMPLETION_REMINDER_RUN_STOP_REASONS),
            "response_stop_markers": dict(_COMPLETION_REMINDER_RESPONSE_STOP_MARKERS),
        }

    # -- plumbing ----------------------------------------------------------------

    @staticmethod
    def _key(runtime: Any) -> tuple[str, str]:
        return context_scope(runtime, "thread_id"), context_scope(runtime, "run_id")

    def _resolved_app_config(self) -> Any:
        if self._app_config is None:
            from deerflow.config.app_config import get_app_config

            self._app_config = get_app_config()
        return self._app_config

    def _build_model(self, model_name: str) -> Any:
        if self._model_factory is not None:
            return self._model_factory(model_name)
        from deerflow.models import create_chat_model

        # The goal evaluator's construction path (runtime/goal.py): thinking off,
        # its own tracing because the call deliberately inherits no graph callbacks.
        return create_chat_model(name=model_name, thinking_enabled=False, app_config=self._resolved_app_config(), attach_tracing=True, model_overrides={"temperature": 0})

    def _inactive(self, runtime: Any) -> bool:
        """Cheap test the sync hooks run before bridging to the async path."""
        context = _context(runtime)
        if context.get("is_subagent"):
            return True
        with self._lock:
            tracked = self._key(runtime) in self._runs
            run = self._runs.get(self._key(runtime))
        return (tracked and run is None) or (not tracked and DEVIATION_MONITOR_CONTEXT_KEY not in context)

    @staticmethod
    def _channel(previous: Mapping[str, Any] | None, **fields: Any) -> dict[str, Any]:
        base = {"status": "off", "reason": "", "drift_kind": None, "restated_task": "", "model": None, "checks": 0, "last_checked_step": None, "updated_at": "", "turn": 0}
        if isinstance(previous, Mapping):
            for key in base:
                if key in previous:
                    base[key] = previous[key]
        base.update(fields)
        base["updated_at"] = now_iso()
        return base

    def _publish(self, run: _Run, **fields: Any) -> dict[str, Any]:
        with self._lock:
            run.channel = self._channel(run.channel, **fields)
            return {STATE_CHANNEL: dict(run.channel)}

    def _mark_unmonitored(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._runs[key] = None

    # -- run start ---------------------------------------------------------------

    async def _authorize(self, model_name: str, context: Mapping[str, Any]) -> str | None:
        """``None`` when the user may use the monitor model, else the visible refusal."""
        from deerflow.models.selection import authorize_selected_model

        try:
            await run_assembly(authorize_selected_model, model_name, context=dict(context), app_config=self._resolved_app_config())
        except ValueError as exc:
            return f"{exc} The deviation monitor is off for this run."
        except Exception:
            logger.warning("Deviation monitor could not authorize its model; it is off for this run", exc_info=True)
            return _AUTHZ_UNAVAILABLE
        return None

    async def _ensure_run(self, state: Any, runtime: Any) -> tuple[_Run | None, dict[str, Any] | None]:
        """The run's monitor state, starting it on the run's first hook (with its channel update)."""
        context = _context(runtime)
        if context.get("is_subagent"):
            return None, None
        key = self._key(runtime)
        with self._lock:
            if key in self._runs:
                return self._runs[key], None
        if DEVIATION_MONITOR_CONTEXT_KEY not in context:
            self._mark_unmonitored(key)
            return None, None
        request = parse_deviation_monitor_request(context.get(DEVIATION_MONITOR_CONTEXT_KEY))
        previous = state.get(STATE_CHANNEL) if isinstance(state, Mapping) else None
        previous = previous if isinstance(previous, Mapping) else None
        if not request.enabled:
            self._mark_unmonitored(key)
            if request.rejected:
                logger.info("Deviation monitor off for run %s: %s", key[1], request.rejected)
                return None, {STATE_CHANNEL: self._channel(previous, status="off", reason=request.rejection_reason, last_checked_step=None)}
            if previous is not None and previous.get("status") != "off":
                return None, {STATE_CHANNEL: self._channel(previous, status="off", reason="", last_checked_step=None)}
            return None, None
        refusal = await self._authorize(request.model, context)
        if refusal is not None:
            self._mark_unmonitored(key)
            return None, {STATE_CHANNEL: self._channel(previous, status="off", reason=refusal, model=request.model, last_checked_step=None)}
        turn = previous.get("turn") if previous is not None else 0
        turn = (turn if isinstance(turn, int) and not isinstance(turn, bool) and turn >= 0 else 0) + 1
        checks = previous.get("checks") if previous is not None else 0
        run = _Run(
            request=request,
            channel=self._channel(
                previous,
                status="on_track",
                reason="",
                drift_kind=None,
                restated_task="",
                model=request.model,
                checks=checks if isinstance(checks, int) and not isinstance(checks, bool) and checks >= 0 else 0,
                last_checked_step=None,
                turn=turn,
            ),
        )
        with self._lock:
            if key in self._runs:  # a concurrent hook of the same run started it first
                return self._runs[key], None
            self._runs[key] = run
            return run, {STATE_CHANNEL: dict(run.channel)}

    # -- hooks -------------------------------------------------------------------

    async def _before_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        _run, update = await self._ensure_run(state, runtime)
        return update

    async def _before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        run, update = await self._ensure_run(state, runtime)
        if run is None or _context(runtime).get("stop_reason") in _COMPLETION_REMINDER_RUN_STOP_REASONS:
            return update
        if run.request.mode == "steps" and (run.steps + 1) % run.request.every == 0 and run.channel.get("status") != "checking":
            with self._lock:
                run.before_checking = {"status": run.channel.get("status"), "reason": run.channel.get("reason")}
            return _merge(update, self._publish(run, status="checking", reason=""))
        return update

    def _settle(self, run: _Run) -> dict[str, Any] | None:
        """Undo a "checking" status whose check did not happen (a cap, a stamped response, an error)."""
        with self._lock:
            restore = run.before_checking if run.channel.get("status") == "checking" else None
            run.before_checking = None
        return self._publish(run, **restore) if restore else None

    def _due(self, run: _Run, step: int, final: bool) -> bool:
        if run.request.mode == "steps":
            return step % run.request.every == 0
        return final and not run.turn_checked and run.channel.get("turn", 0) % run.request.every == 0

    async def _after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        run, update = await self._ensure_run(state, runtime)
        if run is None:
            return update
        checked = await self._check_if_due(state, _context(runtime), run)
        return _merge(update, checked if checked is not None else self._settle(run))

    async def _check_if_due(self, state: Any, context: dict[str, Any], run: _Run) -> dict[str, Any] | None:
        if context.get("stop_reason") in _COMPLETION_REMINDER_RUN_STOP_REASONS:
            return None
        messages = list(state.get("messages") or [])
        last = messages[-1] if messages and isinstance(messages[-1], AIMessage) else None
        if last is None:
            return None
        metadata = last.additional_kwargs or {}
        if metadata.get("deerflow_error_fallback") or any(metadata.get(marker) for marker in _COMPLETION_REMINDER_RESPONSE_STOP_MARKERS.values()):
            return None
        final = not _has_tool_call_intent_or_error(last)
        with self._lock:
            run.steps += 1
            step = run.steps
            due = self._due(run, step, final)
            if due and run.request.mode == "turns":
                run.turn_checked = True
        if not due:
            return None
        return await self._check(state, context, run, last, step=step, final=final)

    async def _after_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if _context(runtime).get("is_subagent"):
            return None
        with self._lock:
            run = self._runs.get(self._key(runtime))
        return self._settle(run) if run is not None else None

    # -- the check ---------------------------------------------------------------

    def _record(self, context: Mapping[str, Any], action: str, changes: dict[str, Any]) -> None:
        journal = context.get("__run_journal")
        if journal is None or not hasattr(journal, "record_middleware"):
            return
        try:
            journal.record_middleware(MIDDLEWARE_DEVIATION_MONITOR_TAG, name=type(self).__name__, hook="after_model", action=action, changes=changes)
        except Exception:  # noqa: BLE001 - an audit event must never break the run
            logger.warning("Failed to record a middleware:deviation_monitor event", exc_info=True)

    async def _check(self, state: Any, context: dict[str, Any], run: _Run, last: AIMessage, *, step: int, final: bool) -> dict[str, Any]:
        app_config = self._resolved_app_config()
        messages = list(state.get("messages") or [])
        checks = int(run.channel.get("checks") or 0) + 1
        evidence = build_monitor_evidence(
            messages,
            budget=configured_model_budget(app_config, run.request.model),
            max_chars=self._config.max_evidence_chars,
            goal=state.get("goal"),
            todos=state.get("todos"),
            summary_text=state.get("summary_text"),
            window_fill=run.window_fill,
            final_answer=final,
            pii_redaction=getattr(app_config, "pii_redaction", None),
        )
        base = {"model": run.request.model, "checks": checks, "last_checked_step": step}
        if evidence is None:
            reason = _REQUEST_TOO_LONG if latest_request(messages) else _NO_REQUEST
            self._record(context, "skipped", {"step": step, "final_answer": final, "model": run.request.model})
            return self._publish(run, status="unsure", reason=reason, drift_kind=None, **base)

        journal = context.get("__run_journal")
        sink = journal.record_external_llm_usage_records if journal is not None and hasattr(journal, "record_external_llm_usage_records") else None
        try:
            model = await run_assembly(self._build_model, run.request.model)
        except Exception as exc:
            logger.warning("Deviation monitor could not build model %s", run.request.model, exc_info=True)
            self._record(context, "unsure", {"step": step, "final_answer": final, "model": run.request.model, "verdicts": []})
            return self._publish(run, status="unsure", reason=f"The monitor model could not be started ({type(exc).__name__}).", drift_kind=None, **base)

        async def ask() -> JudgeVerdict:
            return await ask_judge(model, evidence.prompt_messages(), timeout_seconds=self._config.judge_timeout_seconds, model_name=run.request.model, usage_sink=sink)

        verdicts = [await ask()]
        confirmed = False
        if verdicts[0].verdict == "drifting":
            # Noise control: a small judge agrees with itself less often than it should.
            verdicts.append(await ask())
            confirmed = verdicts[1].verdict == "drifting" or bool(evidence.signals)
        first = verdicts[0]
        audit = {"step": step, "final_answer": final, "model": run.request.model, "verdicts": [verdict.verdict for verdict in verdicts], "drift_kind": None, "signals": len(evidence.signals)}

        if first.verdict == "on_task":
            self._record(context, "on_task", audit)
            return self._publish(run, status="on_track", reason=first.reason, drift_kind=None, restated_task=first.restated_task, **base)
        if first.verdict == "unsure":
            self._record(context, "unsure", audit)
            return self._publish(run, status="unsure", reason=first.reason or first.error or _UNSURE_DEFAULT, drift_kind=None, restated_task=first.restated_task, **base)
        acting = verdicts[1] if len(verdicts) > 1 and verdicts[1].verdict == "drifting" else first
        audit["drift_kind"] = acting.drift_kind
        if not confirmed:
            self._record(context, "drifting", audit)
            return self._publish(run, status="drifting", reason=acting.reason, drift_kind=acting.drift_kind, restated_task=acting.restated_task, **base)

        locale = _locale(context)
        reason = neutralize_untrusted_tags(acting.reason) if acting.reason else _NO_REASON[locale]
        if _subagent_mode(context) and not run.retried:
            with self._lock:
                run.retried = True
                run.turn_checked = False  # the retried answer is checked again
                run.pending_reminder = _REMINDER.format(
                    kind=f" ({acting.drift_kind})" if acting.drift_kind else "",
                    reason=reason,
                    request=neutralize_untrusted_tags(evidence.request if len(evidence.request) <= _REQUEST_IN_REMINDER_CHARS else _clip(evidence.request, _REQUEST_IN_REMINDER_CHARS)),
                    workflow=" or a workflow" if _workflow_mode(context) else "",
                )
            note = _NOTES[locale]["retrying_final" if final else "retrying"].format(reason=reason)
            self._record(context, "retrying", audit)
            update = self._publish(run, status="retrying", reason=acting.reason, drift_kind=acting.drift_kind, restated_task=acting.restated_task, **base)
            return {**update, "messages": [self._rewrite(last, "retrying", acting, final, note)], "jump_to": "model"}

        context["stop_reason"] = STOP_REASON
        note = _NOTES[locale]["stopped_final" if final else "stopped"].format(reason=reason, request=neutralize_untrusted_tags(_clip(evidence.request, _REQUEST_IN_NOTE_CHARS)))
        self._record(context, "stopped", audit)
        logger.warning("Deviation monitor stopped run %s at step %d (%s)", context.get("run_id"), step, acting.drift_kind or "drift")
        update = self._publish(run, status="stopped", reason=acting.reason, drift_kind=acting.drift_kind, restated_task=acting.restated_task, **base)
        return {**update, "messages": [self._rewrite(last, "stopped", acting, final, note)]}

    @staticmethod
    def _rewrite(message: AIMessage, action: str, verdict: JudgeVerdict, final: bool, note: str) -> AIMessage:
        """The response with every tool call removed, its text kept and the note appended."""
        cloned = clone_ai_message_with_tool_calls(message.model_copy(update={"invalid_tool_calls": []}), [])
        kwargs = dict(cloned.additional_kwargs or {})
        kwargs[ACTION_MARKER_KEY] = {"action": action, "final_answer": final, "reason": verdict.reason, "drift_kind": verdict.drift_kind, "restated_task": verdict.restated_task}
        return cloned.model_copy(update={"content": _append_text(cloned.content, note), "additional_kwargs": kwargs})

    # -- the retry reminder and the window measurement --------------------------

    def _prepare(self, request: ModelRequest) -> tuple[ModelRequest, tuple[str, str], str | None]:
        key = self._key(request.runtime)
        with self._lock:
            run = self._runs.get(key)
            reminder = run.pending_reminder if run is not None else None
            if run is not None:
                run.pending_reminder = None
        if run is None:
            return request, key, None
        budget = resolve_context_budget(getattr(request, "model", None), self._app_config)
        if budget is not None:
            try:
                fill = estimate_request_tokens(request) / max(1, budget.prompt_tokens)
            except Exception:  # noqa: BLE001 - a measurement must never fail the call
                fill = None
            with self._lock:
                run.window_fill = fill
        if reminder is None:
            return request, key, None
        message = HumanMessage(content=reminder, name=REMINDER_MESSAGE_NAME, additional_kwargs={"hide_from_ui": True})
        return request.override(messages=[*request.messages, message]), key, reminder

    def _restore(self, key: tuple[str, str], reminder: str | None) -> None:
        # LLMErrorHandlingMiddleware retries a failed call through this wrapper
        # again, so the retry must still carry the reminder.
        if reminder is None:
            return
        with self._lock:
            run = self._runs.get(key)
            if run is not None and run.pending_reminder is None:
                run.pending_reminder = reminder

    @override
    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelCallResult:
        request, key, reminder = self._prepare(request)
        try:
            return handler(request)
        except Exception:
            self._restore(key, reminder)
            raise

    @override
    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelCallResult:
        request, key, reminder = self._prepare(request)
        try:
            return await handler(request)
        except Exception:
            self._restore(key, reminder)
            raise

    # -- hook entry points -------------------------------------------------------

    @override
    async def abefore_agent(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        return await self._before_agent(state, runtime)

    @override
    def before_agent(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        return None if self._inactive(runtime) else _run_sync(self._before_agent(state, runtime))

    @override
    async def abefore_model(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        return await self._before_model(state, runtime)

    @override
    def before_model(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        return None if self._inactive(runtime) else _run_sync(self._before_model(state, runtime))

    @override
    async def aafter_agent(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        return await self._after_agent(state, runtime)

    @override
    def after_agent(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        return None if self._inactive(runtime) else _run_sync(self._after_agent(state, runtime))

    @hook_config(can_jump_to=["model"])
    @override
    async def aafter_model(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        return await self._after_model(state, runtime)

    @hook_config(can_jump_to=["model"])
    @override
    def after_model(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        return None if self._inactive(runtime) else _run_sync(self._after_model(state, runtime))


__all__ = [
    "ACTION_MARKER_KEY",
    "REMINDER_MESSAGE_NAME",
    "STATE_CHANNEL",
    "STOP_REASON",
    "DeviationMonitorMiddleware",
    "DeviationMonitorState",
]
