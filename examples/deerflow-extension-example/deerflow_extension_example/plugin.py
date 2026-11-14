"""The example's six deliberately small contribution implementations."""

from __future__ import annotations

import re
from asyncio import CancelledError
from collections.abc import Awaitable, Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic_ns
from typing import Any

from deerflow_extension_api import (
    AgentBuildContext,
    AgentScope,
    ExtensionData,
    ExtensionRuntimeDeps,
    HostCapabilityError,
    MiddlewarePlacement,
    ModelTool,
    Placement,
    PluginContribution,
    SystemModelRequest,
    SystemModelResult,
    SystemOperationKind,
    TaskInfo,
    TaskOutcome,
    ToolContext,
    task_store_from_runtime,
)
from fastapi import APIRouter, Depends, HTTPException
from langchain.agents.middleware import AgentMiddleware
from langgraph.prebuilt.tool_node import ToolCallRequest


@dataclass
class ExampleStats:
    """Small extension-owned value used in both app and task stores."""

    tool_calls: int = 0
    tool_outcomes: dict[str, int] = field(default_factory=lambda: {"returned": 0, "raised": 0, "cancelled": 0})
    tool_duration_samples: int = 0
    tool_duration_total_ns: int = 0
    tasks: dict[str, int] = field(default_factory=dict)
    system_model_calls: dict[str, dict[str, int]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    def note_tool_call(self) -> None:
        with self._lock:
            self.tool_calls += 1

    def note_tool_outcome(self, outcome: str, duration_ns: int) -> None:
        with self._lock:
            self.tool_outcomes[outcome] += 1
            self.tool_duration_samples += 1
            self.tool_duration_total_ns += duration_ns

    def absorb_task(self, task_stats: ExampleStats, outcome: TaskOutcome) -> None:
        # Copy the task under its lock, then merge under the app lock.
        with task_stats._lock:
            tool_calls = task_stats.tool_calls
            outcomes = dict(task_stats.tool_outcomes)
            samples = task_stats.tool_duration_samples
            duration_ns = task_stats.tool_duration_total_ns
        with self._lock:
            self.tool_calls += tool_calls
            for name, count in outcomes.items():
                self.tool_outcomes[name] += count
            self.tool_duration_samples += samples
            self.tool_duration_total_ns += duration_ns
            key = outcome.value
            self.tasks[key] = self.tasks.get(key, 0) + 1

    def note_system_call(self, kind: SystemOperationKind, *, failed: bool) -> None:
        with self._lock:
            entry = self.system_model_calls.setdefault(
                kind.value,
                {"calls": 0, "errors": 0},
            )
            entry["calls"] += 1
            if failed:
                entry["errors"] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tasks": dict(self.tasks),
                "tool_calls": self.tool_calls,
                "tool_outcomes": dict(self.tool_outcomes),
                "tool_duration_samples": self.tool_duration_samples,
                "tool_duration_total_ms": self.tool_duration_total_ns / 1_000_000,
                "system_model_calls": {kind: dict(counts) for kind, counts in self.system_model_calls.items()},
            }


def _stats(store: ExtensionData) -> ExampleStats:
    return store.get_or_init(ExampleStats, ExampleStats)


class ExampleMiddleware(AgentMiddleware):
    @contextmanager
    def _observe(self, request: ToolCallRequest) -> Generator[None, None, None]:
        task_store = task_store_from_runtime(getattr(request, "runtime", None))
        task_stats = task_store.get(ExampleStats) if task_store is not None else None
        if task_stats is None:
            yield
            return
        task_stats.note_tool_call()
        started = monotonic_ns()
        outcome = "returned"
        try:
            yield
        except CancelledError:
            outcome = "cancelled"
            raise
        except BaseException:
            # Includes graph interrupts; observation must not consume control flow.
            outcome = "raised"
            raise
        finally:
            task_stats.note_tool_outcome(outcome, monotonic_ns() - started)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        with self._observe(request):
            return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        with self._observe(request):
            return await handler(request)


class ExampleMiddlewareContributor:
    def contribute_middlewares(
        self,
        app_store: ExtensionData,
        ctx: AgentBuildContext,
    ) -> Sequence[MiddlewarePlacement]:
        return (
            MiddlewarePlacement(
                ExampleMiddleware(),
                Placement.TOOL_VISIBLE,
                AgentScope.BOTH,
            ),
        )


class ExampleTaskLifecycle:
    async def on_task_start(
        self,
        app_store: ExtensionData,
        task_store: ExtensionData,
        info: TaskInfo,
    ) -> None:
        task_store.set(ExampleStats())

    async def on_task_stop(
        self,
        app_store: ExtensionData,
        task_store: ExtensionData,
        info: TaskInfo,
        outcome: TaskOutcome,
    ) -> None:
        task_stats = task_store.remove(ExampleStats)
        if task_stats is not None:
            _stats(app_store).absorb_task(task_stats, outcome)


class ExampleSystemObserver:
    async def on_system_model_call(
        self,
        app_store: ExtensionData,
        task_store: ExtensionData,
        kind: SystemOperationKind,
        request: SystemModelRequest,
        result: SystemModelResult,
    ) -> None:
        _stats(app_store).note_system_call(kind, failed=result.error is not None)


class ExampleService:
    def __init__(self) -> None:
        self._deps: ExtensionRuntimeDeps | None = None

    async def start(self, deps: ExtensionRuntimeDeps) -> None:
        self._deps = deps

    async def stop(self) -> None:
        self._deps = None

    async def require_deps(self) -> ExtensionRuntimeDeps:
        deps = self._deps
        if deps is None or deps.app_store is None:
            raise HTTPException(
                status_code=503,
                detail="extension-example is not running",
            )
        return deps


def build_router(service: ExampleService) -> APIRouter:
    """Build paths during registration, before runtime dependencies exist."""
    router = APIRouter(prefix="/api/extension-example", tags=["extension-example"])

    @router.get("/stats")
    async def read_stats(
        deps: ExtensionRuntimeDeps = Depends(service.require_deps),
    ) -> dict[str, Any]:
        assert deps.app_store is not None
        return {
            "scope_id": deps.app_store.scope_id,
            "session_factory_available": deps.session_factory is not None,
            "host_policy": {
                "max_subagents_per_run": deps.policy.max_subagents_per_run,
            },
            **_stats(deps.app_store).snapshot(),
        }

    return router


async def save_note(payload: Mapping[str, Any], context: ToolContext) -> dict[str, str]:
    """Write the note as a Markdown file into the calling conversation's outputs.

    The tool names a file and hands over bytes. The host decides where the
    conversation's outputs are, checks the name and the operator's size caps,
    and returns the path it used, which differs when the name was taken.
    """
    title = " ".join(str(payload["title"]).split())
    name = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "note"
    content = f"# {title}\n\n{str(payload['text']).rstrip()}\n".encode()
    try:
        return {"saved": await context.write_output(f"{name}.md", content)}
    except HostCapabilityError as exc:
        # The codes are stable: UNSUPPORTED, INVALID_NAME, LIMIT_EXCEEDED, ...
        return {"error": f"The note was not saved ({exc.code})."}


def build_notes_plugin() -> PluginContribution:
    """One model tool, on by default once the operator installed the package."""
    return PluginContribution(
        namespace="example.notes",
        title="Example notes",
        description="Saves a short note as a Markdown file in the conversation's outputs.",
        enabled=True,
        tools=(
            ModelTool(
                "save_note",
                "Save a short note as a Markdown file in this conversation's outputs. Returns the file's path.",
                {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 80, "description": "Title of the note; also names the file."},
                        "text": {"type": "string", "maxLength": 20000, "description": "Body of the note, as Markdown."},
                    },
                    "required": ["title", "text"],
                    "additionalProperties": False,
                },
                save_note,
            ),
        ),
    )
