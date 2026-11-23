"""Design runs only: keep the drafting tool, add the brief, record the finalize build.

The host binds every enabled plugin tool on every request, so this lead-scoped
middleware at ``Placement.MODEL_LOGICAL`` (outside the context guard, which then
measures what is really sent) removes ``scad_draft`` from every model call that
is not a design run: ordinary conversations pay 0 tokens for this extension.
Delegated subagents get ``NoDrafting``, which removes it from every call.

A design run is one whose ``plugin_options["cad-design"]`` names a live design
whose conversation is the run's own thread. The options are client input, so
the thread binding is what makes them trustworthy: the host admitted the run
on a thread the caller owns, and the store maps that thread to one design.
On such a run the brief and a bounded version note ride the system message
(the workflows extension's ultracode.py pattern, so a custom SYSTEM_PROMPT.md
still receives them). In the finalize phase the drafting tool is removed too,
and each ``cad_build`` result is recorded into the finalized version.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from deerflow_extension_api import AgentScope, MiddlewarePlacement, Placement, plugin_run_options
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from .constants import CAD_BUILD_TOOL, ID, NAMESPACE, SCAD_DRAFT_TOOL
from .notes import DRAFT_BRIEF, FINALIZE_BRIEF, version_note
from .store import Store

#: Per axis, the finalized part may differ from the draft's rendered size by this much.
TOLERANCE_MM = 0.5
TOLERANCE_RATIO = 0.02
MAX_CHECKS = 12


def tool_name(tool: Any) -> str | None:
    if isinstance(tool, Mapping):
        function = tool.get("function")
        return function.get("name") if isinstance(function, Mapping) else tool.get("name")
    return getattr(tool, "name", None)


def _context(runtime: Any) -> Mapping[str, Any]:
    context = getattr(runtime, "context", None)
    return context if isinstance(context, Mapping) else {}


def _triple(value: Any) -> list[float] | None:
    if isinstance(value, list) and len(value) == 3 and all(isinstance(item, int | float) and not isinstance(item, bool) and math.isfinite(item) for item in value):
        return [float(item) for item in value]
    return None


#: The part files cad_build writes only when every check passes; a failed build
#: leaves <stem>.failed.glb and .failed.png, which are not the part.
DELIVERABLE_SUFFIXES = (".step", ".glb", ".stl", ".3mf")


def deliverable(name: str) -> bool:
    lower = name.lower()
    return lower.endswith(DELIVERABLE_SUFFIXES) and ".failed." not in lower


def bbox_check(measured: list[float], draft: list[float]) -> tuple[bool, list[float]]:
    tolerance = [max(TOLERANCE_MM, TOLERANCE_RATIO * abs(size)) for size in draft]
    return all(abs(m - d) <= t for m, d, t in zip(measured, draft, tolerance, strict=True)), tolerance


def final_from_answer(answer: Mapping[str, Any], previous: Mapping[str, Any] | None, draft_bbox: Any) -> dict[str, Any]:
    """The version's ``final`` record from one ``cad_build`` answer."""
    final: dict[str, Any] = {key: previous[key] for key in ("run_id",) if previous and key in previous}
    files = [PurePosixPath(path).name for path in answer.get("files") or [] if isinstance(path, str)]
    checks = [{key: check.get(key) for key in ("check", "expected", "measured", "passed") if key in check} for check in (answer.get("checks") or [])[:MAX_CHECKS] if isinstance(check, Mapping)]
    report: dict[str, Any] = {"passed": answer.get("passed") is True, "checks": checks}
    for key in ("attempt", "error"):
        if key in answer:
            report[key] = answer[key]
    final.update(files=files, report=report)
    draft = _triple(draft_bbox)
    if draft is not None:
        final["draft_bbox_mm"] = draft
    measured = next((_triple(check.get("measured")) for check in checks if check.get("check") == "bounding box"), None)
    if measured is not None:
        final["bbox_mm"] = measured
    # cad_build judges the box at 0.1 %, but the draft's box is a faceted mesh's: a true
    # cylinder or sphere differs from it by more than that. The page judges the box
    # itself (max(0.5 mm, 2 %)), so a failed box check alone is not a wrong size. But
    # cad_build exports the part (STEP, GLB, STL) only when every check passes, so such
    # a build is "built" only once a rebuild against the measured size has exported it.
    failed = [str(check.get("check")) for check in checks if check.get("passed") is False]
    box_only = answer.get("error") is None and failed == ["bounding box"] and measured is not None and draft is not None
    if answer.get("passed") is not True and not box_only:
        error = answer.get("error")
        message = error.get("message") if isinstance(error, Mapping) else None
        final.update(status="failed", message=str(message or ("Failed checks: " + ", ".join(failed) if failed else "The build failed."))[:1000])
        return final
    if measured is not None and draft is not None:
        within, tolerance = bbox_check(measured, draft)
        final["tolerance_mm"] = tolerance
        if not within:
            final.update(status="mismatch", message="Port the draft's dimensions exactly; the CadQuery part has a different size.")
            return final
    if not any(deliverable(name) for name in files):
        size = "[" + ", ".join(f"{value:.3f}".rstrip("0").rstrip(".") for value in measured) + "]" if measured is not None else "the measured size"
        final.update(status="failed", message=f"The part matches the draft, but cad_build exported nothing because its strict bounding box check failed. Build it again passing bbox_xyz_mm = {size}.")
        return final
    final["status"] = "built"
    return final


def answer_of(result: Any) -> Mapping[str, Any] | None:
    """The JSON answer inside a tool result (a ToolMessage, or a Command that registers files)."""
    message = result
    update = getattr(result, "update", None)
    if isinstance(update, Mapping):
        message = next(iter(update.get("messages") or []), None)
    content = getattr(message, "content", None)
    if not isinstance(content, str):
        return None
    try:
        answer = json.loads(content)
    except ValueError:
        return None
    return answer if isinstance(answer, Mapping) else None


class DesignMode(AgentMiddleware):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store

    # -- which run is this -----------------------------------------------------

    def design_run(self, runtime: Any) -> tuple[Mapping[str, Any], dict[str, Any]] | None:
        """(options, design) on a design run, else None. Touches the store only when flagged."""
        context = _context(runtime)
        options = plugin_run_options(context, NAMESPACE)
        design_id = options.get("design_id")
        thread_id = context.get("thread_id")
        if not isinstance(design_id, str) or not ID.fullmatch(design_id) or not isinstance(thread_id, str) or not thread_id:
            return None
        design = self.store.design_for_thread(design_id, thread_id)
        return (options, design) if design is not None else None

    # -- model calls -----------------------------------------------------------

    def notes(self, request: Any) -> tuple[list[str], bool]:
        """(system notes, whether this is a drafting call) for one model call.

        A drafting call keeps ``scad_draft`` and loses ``cad_build``: only Finalize builds
        CadQuery. With both offered, a model followed the cad-modeling skill, built the
        part in one go and never drafted, so the page's preview stayed empty."""
        found = self.design_run(request.runtime)
        if found is None:
            return [], False
        options, design = found
        versions = self.store.thread_versions(design["id"], design["thread_id"])
        if options.get("phase") == "finalize":
            head = next((version for version in versions if version["id"] == options.get("head")), None)
            bbox = (head or {}).get("render") or {}
            size = _triple(bbox.get("bbox_mm"))
            return [FINALIZE_BRIEF.format(seq=head["seq"] if head else "?", bbox=json.dumps([round(value, 3) for value in size]) if size else "the draft's size")], False
        return [DRAFT_BRIEF, version_note(versions, design["head_version_id"])], True

    def apply(self, request: Any, notes: list[str], keep: bool) -> Any:
        changes: dict[str, Any] = {}
        dropped = CAD_BUILD_TOOL if keep else SCAD_DRAFT_TOOL
        tools = [tool for tool in request.tools if tool_name(tool) != dropped]
        if len(tools) != len(request.tools):
            changes["tools"] = tools
        if notes:
            current = request.system_message
            content = current.content if current is not None else ""
            text = content if isinstance(content, str) else "\n".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
            changes["system_message"] = SystemMessage(
                content="\n\n".join([text, *notes]) if text else "\n\n".join(notes),
                id=getattr(current, "id", None),
                additional_kwargs=dict(getattr(current, "additional_kwargs", None) or {}),
            )
        return request.override(**changes) if changes else request

    def wrap_model_call(self, request, handler):
        return handler(self.apply(request, *self.notes(request)))

    async def awrap_model_call(self, request, handler):
        notes, keep = await asyncio.to_thread(self.notes, request) if self._flagged(request.runtime) else ([], False)
        return await handler(self.apply(request, notes, keep))

    @staticmethod
    def _flagged(runtime: Any) -> bool:
        return bool(plugin_run_options(_context(runtime), NAMESPACE).get("design_id"))

    # -- the finalize build ----------------------------------------------------

    def record(self, runtime: Any, result: Any) -> None:
        found = self.design_run(runtime)
        if found is None:
            return
        options, design = found
        head = options.get("head")
        if options.get("phase") != "finalize" or not isinstance(head, str):
            return
        answer = answer_of(result)
        version = next((v for v in self.store.thread_versions(design["id"], design["thread_id"]) if v["id"] == head), None)
        if answer is None or version is None:
            return
        draft = (version.get("render") or {}).get("bbox_mm")
        final = final_from_answer(answer, version.get("final"), (version.get("final") or {}).get("draft_bbox_mm") or draft)
        self.store.record_final_for_thread(design["id"], design["thread_id"], head, final)

    def wrap_tool_call(self, request, handler):
        result = handler(request)
        if request.tool_call.get("name") == CAD_BUILD_TOOL:
            self.record(request.runtime, result)
        return result

    async def awrap_tool_call(self, request, handler):
        result = await handler(request)
        if request.tool_call.get("name") == CAD_BUILD_TOOL and self._flagged(request.runtime):
            await asyncio.to_thread(self.record, request.runtime, result)
        return result


class NoDrafting(AgentMiddleware):
    """Delegated subagents: the host binds plugin tools into them too, and they never draft."""

    @staticmethod
    def apply(request: Any) -> Any:
        tools = [tool for tool in request.tools if tool_name(tool) != SCAD_DRAFT_TOOL]
        return request.override(tools=tools) if len(tools) != len(request.tools) else request

    def wrap_model_call(self, request, handler):
        return handler(self.apply(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self.apply(request))


class Contributor:
    def __init__(self, store: Store):
        self.store = store

    def contribute_middlewares(self, app_store, context):
        if context.scope == AgentScope.SUBAGENT:
            return (MiddlewarePlacement(NoDrafting(), Placement.MODEL_LOGICAL, AgentScope.SUBAGENT),)
        if context.scope != AgentScope.LEAD:
            return ()
        return (MiddlewarePlacement(DesignMode(self.store), Placement.MODEL_LOGICAL, AgentScope.LEAD),)
