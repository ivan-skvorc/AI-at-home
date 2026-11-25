"""Design runs only: append the design brief to the system message.

A lead-scoped middleware at ``Placement.MODEL_LOGICAL``, outside the context
guard, which then measures what is really sent. The host forwards only removed
tools and appended system text from this placement, and this middleware only
appends: on a design run the brief (notes.py), plus a line telling the model
to stop when the run has no bash tool and so no container to render in. Every
other model call, a delegated subagent's included, passes unchanged, so
ordinary conversations pay 0 tokens for this extension.

A design run is one whose ``plugin_options["cad-design"]`` names a live design
whose conversation is the run's own thread. The options are client input, so
the thread binding is what makes them trustworthy: the host admitted the run
on a thread the caller owns, and the store maps that thread to one design.
The brief rides the system message (the workflows extension's ultracode.py
pattern), so a custom SYSTEM_PROMPT.md still receives it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import AgentScope, MiddlewarePlacement, Placement, plugin_run_options
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from .constants import BASH_TOOL, ID, NAMESPACE
from .notes import DESIGN_BRIEF, NO_CONTAINER
from .store import Store


def tool_name(tool: Any) -> str | None:
    if isinstance(tool, Mapping):
        function = tool.get("function")
        return function.get("name") if isinstance(function, Mapping) else tool.get("name")
    return getattr(tool, "name", None)


def _context(runtime: Any) -> Mapping[str, Any]:
    context = getattr(runtime, "context", None)
    return context if isinstance(context, Mapping) else {}


class DesignMode(AgentMiddleware):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store

    def design_run(self, runtime: Any) -> dict[str, Any] | None:
        """The design on a design run, else None. Touches the store only when flagged."""
        context = _context(runtime)
        design_id = plugin_run_options(context, NAMESPACE).get("design_id")
        thread_id = context.get("thread_id")
        if not isinstance(design_id, str) or not ID.fullmatch(design_id) or not isinstance(thread_id, str) or not thread_id:
            return None
        return self.store.design_for_thread(design_id, thread_id)

    def notes(self, request: Any) -> list[str]:
        if self.design_run(request.runtime) is None:
            return []
        if any(tool_name(tool) == BASH_TOOL for tool in request.tools):
            return [DESIGN_BRIEF]
        return [DESIGN_BRIEF, NO_CONTAINER]

    @staticmethod
    def apply(request: Any, notes: list[str]) -> Any:
        if not notes:
            return request
        current = request.system_message
        content = current.content if current is not None else ""
        text = content if isinstance(content, str) else "\n".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        return request.override(
            system_message=SystemMessage(
                content="\n\n".join([text, *notes]) if text else "\n\n".join(notes),
                id=getattr(current, "id", None),
                additional_kwargs=dict(getattr(current, "additional_kwargs", None) or {}),
            )
        )

    def wrap_model_call(self, request, handler):
        return handler(self.apply(request, self.notes(request)))

    async def awrap_model_call(self, request, handler):
        notes = await asyncio.to_thread(self.notes, request) if self._flagged(request.runtime) else []
        return await handler(self.apply(request, notes))

    @staticmethod
    def _flagged(runtime: Any) -> bool:
        return bool(plugin_run_options(_context(runtime), NAMESPACE).get("design_id"))


class Contributor:
    def __init__(self, store: Store):
        self.store = store

    def contribute_middlewares(self, app_store, context):
        if context.scope != AgentScope.LEAD:
            return ()
        return (MiddlewarePlacement(DesignMode(self.store), Placement.MODEL_LOGICAL, AgentScope.LEAD),)
