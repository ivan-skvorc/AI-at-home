"""One review before the lead agent's final answer, and the skill ledger after it.

Two coding habits a mature agent has and a model forgets mid-task, checked
from facts the run already holds rather than from the model's own account:

1. **Verify before finishing** (``harness_guard.verify_before_finish``). The
   run edited code (``write_file``/``str_replace`` on a source file) and ran no
   ``bash`` command after its last edit, so nothing it changed was executed.
2. **Learn before finishing** (``skill_evolution.enabled`` and
   ``skill_evolution.nudge_after_tool_calls``). The run took many tool calls
   and never called ``skill_manage``, or it loaded a custom skill: the moment
   to save the procedure it worked out, or patch the skill that fell short, is
   now, while the conversation still holds the evidence.

When either applies, the model's first clean final answer is held back once
per run and the next model request carries one hidden reminder naming what
applies. The model then does it or answers; there is never a second reminder,
so the gate costs at most one extra model call and cannot loop.

It mirrors ``TodoMiddleware``'s completion reminder and honors the same stops:
a loop, token or spend cap, a safety or length-capped response, an error
fallback, or tool-call intent all mean "do not resume". Outstanding to-dos
belong to ``TodoMiddleware`` (registered after this one, so its reverse-order
``after_model`` runs first); this gate stands aside while any are open.

After the agent finishes (``after_agent``), and only while skill evolution is
on, the skills loaded in this turn are counted in the per-user skill ledger and
the curator runs at most daily (``deerflow.skills.learning``). That half is
telemetry: every failure is logged and swallowed.
"""

from __future__ import annotations

import asyncio
import logging
import posixpath
import threading
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse, hook_config
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares._bounded_dict import BoundedDict
from deerflow.agents.middlewares.skill_usage import SKILL_USAGE_KEY
from deerflow.agents.middlewares.todo_middleware import (
    _COMPLETION_REMINDER_RESPONSE_STOP_MARKERS,
    _COMPLETION_REMINDER_RUN_STOP_REASONS,
    _has_tool_call_intent_or_error,
)

logger = logging.getLogger(__name__)

COMPLETION_REVIEW_MESSAGE_NAME = "completion_review_reminder"
_MAX_TRACKED_RUNS = 4096
_MAX_PATHS_SHOWN = 5
_EDIT_TOOLS = frozenset({"write_file", "str_replace"})
# Source files whose edit is worth running something for. Docs, data and
# config are left out on purpose: "run the tests" after editing a README is
# noise, and noise is what teaches a model to ignore the reminder.
CODE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".scala",
        ".rb",
        ".php",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".swift",
        ".m",
        ".sh",
        ".bash",
        ".zsh",
        ".lua",
        ".dart",
        ".ex",
        ".exs",
        ".erl",
        ".clj",
        ".hs",
        ".ml",
        ".r",
        ".jl",
        ".vue",
        ".svelte",
        ".sql",
    }
)


def _is_code_path(path: Any) -> bool:
    if not isinstance(path, str) or not path:
        return False
    return posixpath.splitext(path.replace("\\", "/"))[1].lower() in CODE_SUFFIXES


def _is_user_turn(message: BaseMessage) -> bool:
    """A human message the user sent, not a framework reminder persisted as one."""
    if not isinstance(message, HumanMessage):
        return False
    if (message.additional_kwargs or {}).get("hide_from_ui"):
        return False
    name = message.name or ""
    return not name.endswith("reminder")


def current_turn(messages: list[BaseMessage]) -> list[BaseMessage]:
    """The messages after the last user message (the whole list when there is none)."""
    for index in range(len(messages) - 1, -1, -1):
        if _is_user_turn(messages[index]):
            return messages[index + 1 :]
    return list(messages)


def _tool_succeeded(result: ToolMessage | None) -> bool:
    if result is None:
        return False
    if getattr(result, "status", None) == "error":
        return False
    content = result.content if isinstance(result.content, str) else ""
    return not content.lstrip().startswith("Error")


def skills_used(messages: Iterable[BaseMessage], *, category: str | None = None) -> list[str]:
    """Names of skills whose content was loaded (stamped by the read/slash paths)."""
    names: list[str] = []
    for message in messages:
        usage = (getattr(message, "additional_kwargs", None) or {}).get(SKILL_USAGE_KEY)
        if not isinstance(usage, dict):
            continue
        name = usage.get("name")
        if not isinstance(name, str) or not name:
            continue
        if category is not None and usage.get("category") != category:
            continue
        if name not in names:
            names.append(name)
    return names


def build_completion_reminder(
    turn: list[BaseMessage],
    *,
    tool_names: frozenset[str],
    verify_code_edits: bool,
    skill_learning: bool,
    nudge_after_tool_calls: int,
) -> str | None:
    """Return the reminder text for this turn, or ``None`` when nothing applies."""
    results: dict[str, ToolMessage] = {}
    for message in turn:
        if isinstance(message, ToolMessage) and message.tool_call_id:
            results[message.tool_call_id] = message

    calls: list[tuple[str, dict[str, Any], str]] = []
    for message in turn:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                calls.append((str(call.get("name") or ""), call.get("args") or {}, str(call.get("id") or "")))

    lines: list[str] = []

    if verify_code_edits and "bash" in tool_names:
        last_edit = -1
        edited: list[str] = []
        for position, (name, args, call_id) in enumerate(calls):
            path = args.get("path") if isinstance(args, dict) else None
            if name in _EDIT_TOOLS and _is_code_path(path) and _tool_succeeded(results.get(call_id)):
                last_edit = position
                base = posixpath.basename(str(path).replace("\\", "/"))
                if base not in edited:
                    edited.append(base)
        ran_after = any(name == "bash" for name, _args, _id in calls[last_edit + 1 :])
        if last_edit >= 0 and not ran_after:
            shown = ", ".join(edited[:_MAX_PATHS_SHOWN]) + (", ..." if len(edited) > _MAX_PATHS_SHOWN else "")
            lines.append(f"- You edited code ({shown}) and ran no command after the last edit. Run the relevant tests, linter or the program now, or say in your answer why you could not.")

    if skill_learning and "skill_manage" in tool_names and not any(name == "skill_manage" for name, _args, _id in calls):
        custom = skills_used(turn, category="custom")
        if custom:
            lines.append(f"- You followed your custom skill(s) {', '.join(custom)}. If one was wrong, incomplete or out of date for this task, patch it now with `skill_manage` so the next run starts from the fix.")
        if nudge_after_tool_calls > 0 and len(calls) >= nudge_after_tool_calls:
            lines.append(
                f"- This task took {len(calls)} tool calls. If it produced a reusable procedure (a sequence of steps that worked, the fix for a non-obvious error, "
                "or an approach the user corrected), save it with `skill_manage`: patch an existing skill rather than adding a near-duplicate, ask the user "
                "before creating a new one, and skip this for one-off work."
            )

    if not lines:
        return None
    return "<system_reminder>\nBefore your final answer:\n" + "\n".join(lines) + "\nIf none of this applies, give your final answer now.\n</system_reminder>"


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        name = tool.get("name") or (tool.get("function") or {}).get("name")
        return name if isinstance(name, str) else None
    name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None


class CompletionReviewMiddleware(AgentMiddleware):
    """Hold back the first final answer once per run when a check applies."""

    def __init__(
        self,
        *,
        verify_code_edits: bool = True,
        skill_learning: bool = False,
        nudge_after_tool_calls: int = 8,
        archive_unused_after_days: int = 0,
    ) -> None:
        super().__init__()
        self.verify_code_edits = verify_code_edits
        self.skill_learning = skill_learning
        self.nudge_after_tool_calls = max(0, int(nudge_after_tool_calls))
        self.archive_unused_after_days = max(0, int(archive_unused_after_days))
        self._lock = threading.Lock()
        self._reminded: BoundedDict[tuple[str, str], bool] = BoundedDict(maxsize=_MAX_TRACKED_RUNS)
        self._pending: BoundedDict[tuple[str, str], str] = BoundedDict(maxsize=_MAX_TRACKED_RUNS)
        self._tool_names: BoundedDict[tuple[str, str], frozenset[str]] = BoundedDict(maxsize=_MAX_TRACKED_RUNS)

    @classmethod
    def from_app_config(cls, app_config: Any) -> CompletionReviewMiddleware | None:
        """Build from ``harness_guard`` and ``skill_evolution``; ``None`` when neither check is on."""
        harness_guard = getattr(app_config, "harness_guard", None)
        skill_evolution = getattr(app_config, "skill_evolution", None)
        verify = bool(getattr(harness_guard, "enabled", False) and getattr(harness_guard, "verify_before_finish", False))
        learning = bool(getattr(skill_evolution, "enabled", False))
        if not verify and not learning:
            return None
        return cls(
            verify_code_edits=verify,
            skill_learning=learning,
            nudge_after_tool_calls=getattr(skill_evolution, "nudge_after_tool_calls", 0) if learning else 0,
            archive_unused_after_days=getattr(skill_evolution, "archive_unused_after_days", 0) if learning else 0,
        )

    # -- run identity ------------------------------------------------------------

    @staticmethod
    def _key(runtime: Any) -> tuple[str, str]:
        context = getattr(runtime, "context", None)
        context = context if isinstance(context, dict) else {}
        return str(context.get("thread_id") or "default"), str(context.get("run_id") or "default")

    # -- the gate ------------------------------------------------------------------

    @hook_config(can_jump_to=["model"])
    @override
    def after_model(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        context = getattr(runtime, "context", None)
        context = context if isinstance(context, dict) else {}
        if context.get("is_subagent") or context.get("stop_reason") in _COMPLETION_REMINDER_RUN_STOP_REASONS:
            return None
        messages = state.get("messages") or []
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if last_ai is None or _has_tool_call_intent_or_error(last_ai):
            return None
        metadata = last_ai.additional_kwargs or {}
        if metadata.get("deerflow_error_fallback") or any(metadata.get(marker) for marker in _COMPLETION_REMINDER_RESPONSE_STOP_MARKERS.values()):
            return None
        todos = state.get("todos") or []
        if any(isinstance(todo, dict) and todo.get("status") != "completed" for todo in todos):
            return None

        key = self._key(runtime)
        with self._lock:
            if self._reminded.get(key):
                return None
            tool_names = self._tool_names.get(key) or frozenset()
        reminder = build_completion_reminder(
            current_turn(messages),
            tool_names=tool_names,
            verify_code_edits=self.verify_code_edits,
            skill_learning=self.skill_learning,
            nudge_after_tool_calls=self.nudge_after_tool_calls,
        )
        if reminder is None:
            return None
        with self._lock:
            if self._reminded.get(key):
                return None
            self._reminded[key] = True
            self._pending[key] = reminder
        return {"jump_to": "model"}

    @hook_config(can_jump_to=["model"])
    @override
    async def aafter_model(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        return self.after_model(state, runtime)

    def _prepare(self, request: ModelRequest) -> tuple[ModelRequest, tuple[str, str], str | None]:
        key = self._key(request.runtime)
        names = frozenset(name for name in (_tool_name(tool) for tool in (request.tools or [])) if name)
        with self._lock:
            self._tool_names[key] = names
            reminder = self._pending.pop(key, None)
        if reminder is None:
            return request, key, None
        message = HumanMessage(content=reminder, name=COMPLETION_REVIEW_MESSAGE_NAME, additional_kwargs={"hide_from_ui": True})
        return request.override(messages=[*request.messages, message]), key, reminder

    def _restore(self, key: tuple[str, str], reminder: str | None) -> None:
        # LLMErrorHandlingMiddleware retries a failed call through this wrapper
        # again, so the retry must still carry the reminder.
        if reminder is not None:
            with self._lock:
                self._pending.setdefault(key, reminder)

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

    # -- the ledger ------------------------------------------------------------------

    def _record_and_curate(self, user_id: str, names: list[str]) -> list[str]:
        from deerflow.skills.learning import SkillLedger
        from deerflow.skills.storage import get_or_new_user_skill_storage

        storage = get_or_new_user_skill_storage(user_id)
        root_getter = getattr(storage, "get_user_custom_root", None)
        if not callable(root_getter):
            return []
        ledger = SkillLedger(root_getter())
        if names:
            ledger.record_use(names)
        if self.archive_unused_after_days > 0 and ledger.curation_due():
            result = ledger.curate(storage, archive_after_days=self.archive_unused_after_days)
            if result.archived:
                logger.info("Skill curator switched off %d unused agent-written skill(s) for user %s: %s", len(result.archived), user_id, ", ".join(result.archived))
            return result.archived
        return []

    def _ledger_inputs(self, state: Any, runtime: Runtime) -> tuple[str, list[str]] | None:
        if not self.skill_learning:
            return None
        context = getattr(runtime, "context", None)
        if isinstance(context, dict) and context.get("is_subagent"):
            return None
        from deerflow.runtime.user_context import resolve_runtime_user_id

        user_id = resolve_runtime_user_id(runtime)
        return user_id, skills_used(current_turn(state.get("messages") or []))

    @override
    def after_agent(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        try:
            inputs = self._ledger_inputs(state, runtime)
            if inputs is None:
                return None
            user_id, names = inputs
            if self._record_and_curate(user_id, names):
                from deerflow.agents.lead_agent.prompt import invalidate_user_skill_cache, publish_skills_cache_reset

                invalidate_user_skill_cache(user_id)
                publish_skills_cache_reset(user_id=user_id)
        except Exception:
            logger.warning("Skill ledger update failed; the run is unaffected", exc_info=True)
        return None

    @override
    async def aafter_agent(self, state: Any, runtime: Runtime) -> dict[str, Any] | None:
        try:
            inputs = self._ledger_inputs(state, runtime)
            if inputs is None:
                return None
            user_id, names = inputs
            archived = await asyncio.to_thread(self._record_and_curate, user_id, names)
            if archived:
                from deerflow.agents.lead_agent.prompt import publish_skills_cache_reset, refresh_user_skills_system_prompt_cache_async

                await refresh_user_skills_system_prompt_cache_async(user_id)
                await asyncio.to_thread(publish_skills_cache_reset, user_id=user_id)
        except Exception:
            logger.warning("Skill ledger update failed; the run is unaffected", exc_info=True)
        return None
