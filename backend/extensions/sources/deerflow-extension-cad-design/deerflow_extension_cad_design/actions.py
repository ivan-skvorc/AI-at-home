"""The page's backend actions. Every one re-reads the design under the caller's user id.

Runs go through the host's AgentRuns handle, so the host checks thread
ownership again and stamps the input messages as this plugin's. A design run
carries ``plugin_options["cad-design"] = {design_id, head, phase}``; that flag
is what turns the drafting tool and the design brief on (middleware.py).
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import AgentRunError

from .constants import CAD_BUILD_TOOL, ID, NAMESPACE, RUN_ID, SCAD_DRAFT_TOOL
from .notes import MODEL_SOURCES, hand_edits
from .store import Conflict, NotFound, Store, clean_title, new_id

ACTIVE = frozenset({"pending", "running"})
STREAM_MODE = ["values", "messages-tuple"]
MAX_PROMPT_CHARS = 8000
MAX_MESSAGES = 200
MAX_MESSAGE_CHARS = 20000
MAX_ARG_CHARS = 4000
#: get_design returns sources newest first up to this many bytes; older ones come from get_version.
DESIGN_SOURCE_BYTES = 2 * 1024 * 1024
MODEL_NAME = re.compile(r"[A-Za-z0-9._:/@+-]{1,128}")
PARAM_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
MAX_PARAMS = 100
REPAIR_MESSAGE = "The last render of draft v{seq} failed; the version note says where. Fix the file and save the whole corrected file with scad_draft once."
FINALIZE_MESSAGE = "Finalize draft v{seq}: port this OpenSCAD file to CadQuery and build it with cad_build.\n\n```openscad\n{scad}\n```"
WRITTEN_SUFFIX = "\n\nThe current file, written by the user; build on it:\n\n```openscad\n{scad}\n```"
EDITED_SUFFIX = "\n\nThe current file, edited by hand since your last version:\n\n```openscad\n{scad}\n```"
TOOL_NAMES = {SCAD_DRAFT_TOOL: "scad_draft", CAD_BUILD_TOOL: "cad_build"}


def _id(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError(f"invalid {key}")
    return value


def _run_id(payload: Mapping[str, Any]) -> str:
    value = payload.get("run_id")
    if not isinstance(value, str) or not RUN_ID.fullmatch(value):
        raise ValueError("invalid run_id")
    return value


def _finite(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _triple(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 3 or not all(_finite(item) for item in value):
        raise ValueError("expected three numbers")
    return [float(item) for item in value]


def clean_render(render: Any) -> dict[str, Any]:
    """A final render result from the page; partial (live) renders are never stored."""
    if not isinstance(render, Mapping) or type(render.get("ok")) is not bool:
        raise ValueError("render needs ok")
    allowed = {"ok", "partial", "error", "error_lines", "bbox_mm", "bbox_min_mm", "bbox_max_mm", "volume_mm3", "manifold", "triangles", "ms"}
    if set(render) - allowed or render.get("partial", False) is not False:
        raise ValueError("unknown or partial render")
    clean: dict[str, Any] = {"ok": render["ok"], "partial": False}
    if "error" in render:
        if not isinstance(render["error"], str):
            raise ValueError("error must be text")
        clean["error"] = render["error"][:4000]
    if "error_lines" in render:
        lines = render["error_lines"]
        if not isinstance(lines, list) or not all(type(line) is int and line >= 0 for line in lines):
            raise ValueError("error_lines must be line numbers")
        clean["error_lines"] = lines[:50]
    for key in ("bbox_mm", "bbox_min_mm", "bbox_max_mm"):
        if key in render:
            clean[key] = _triple(render[key])
    if "volume_mm3" in render:
        if not _finite(render["volume_mm3"]):
            raise ValueError("volume must be a number")
        clean["volume_mm3"] = float(render["volume_mm3"])
    if "manifold" in render:
        if type(render["manifold"]) is not bool:
            raise ValueError("manifold must be boolean")
        clean["manifold"] = render["manifold"]
    for key in ("triangles", "ms"):
        if key in render:
            if type(render[key]) is not int or render[key] < 0:
                raise ValueError(f"{key} must be a count")
            clean[key] = render[key]
    return clean


def clean_params(params: Any) -> dict[str, Any]:
    if not isinstance(params, Mapping) or len(params) > MAX_PARAMS:
        raise ValueError("params must be an object of at most 100 values")
    for name, value in params.items():
        if not isinstance(name, str) or not PARAM_NAME.fullmatch(name) or not (type(value) is bool or _finite(value)):
            raise ValueError("params map names to numbers or booleans")
    return dict(params)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, Mapping) and part.get("type", "text") == "text" else part if isinstance(part, str) else "" for part in content)
    return ""


def _bounded(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= MAX_ARG_CHARS else value[:MAX_ARG_CHARS] + "..."
    if isinstance(value, Mapping):
        return {str(key): _bounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_bounded(item) for item in value[:50]]
    return value


def simplify_messages(messages: Any) -> list[dict[str, Any]]:
    """The conversation as the page shows it: user, assistant and tool turns, bounded."""
    roles = {"human": "user", "user": "user", "ai": "assistant", "assistant": "assistant", "tool": "tool"}
    shown = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, Mapping):
            continue
        role = roles.get(message.get("type", message.get("role")))
        extra = message.get("additional_kwargs") or {}
        if role is None or (isinstance(extra, Mapping) and extra.get("hide_from_ui")):
            continue
        text = _text(message.get("content"))
        entry: dict[str, Any] = {"id": str(message.get("id") or ""), "role": role, "text": text[:MAX_MESSAGE_CHARS]}
        if role == "assistant" and message.get("tool_calls"):
            entry["tool_calls"] = [{"name": TOOL_NAMES.get(call.get("name"), call.get("name")), "args": _bounded(call.get("args") or {})} for call in message["tool_calls"] if isinstance(call, Mapping)]
        if role == "tool":
            entry["tool_name"] = TOOL_NAMES.get(message.get("name"), message.get("name"))
        shown.append(entry)
    return shown[-MAX_MESSAGES:]


class Designs:
    def __init__(self, store: Store, max_source_bytes: int):
        self.store = store
        self.max_source_bytes = max_source_bytes

    # -- helpers ---------------------------------------------------------------

    async def _call(self, method, *args, **kwargs):
        try:
            return await asyncio.to_thread(method, *args, **kwargs)
        except NotFound as exc:
            raise AgentRunError(404, str(exc)) from None
        except Conflict as exc:
            raise AgentRunError(409, str(exc)) from None

    @staticmethod
    def _owner(context: Any) -> str:
        owner = getattr(context.principal, "user_id", None)
        if not isinstance(owner, str) or not owner:
            raise AgentRunError(403, "No signed-in user")
        return owner

    @staticmethod
    def _runs(context: Any):
        if context.agent_runs is None:
            raise AgentRunError(503, "Design runs need a signed-in browser session")
        return context.agent_runs

    def _source(self, value: Any) -> str:
        if not isinstance(value, str) or len(value.encode("utf-8")) > self.max_source_bytes:
            raise ValueError("scad must be text within max_source_bytes")
        return value

    async def _idle(self, context: Any, design: Mapping[str, Any]) -> None:
        """Refuse while the design's last run is still going (its tool would race the edit)."""
        if not design.get("run_id") or context.agent_runs is None:
            return
        try:
            run = await context.agent_runs.get(thread_id=design["thread_id"], run_id=design["run_id"])
        except AgentRunError as exc:
            if exc.status_code == 404:
                return
            raise
        if run.status in ACTIVE:
            raise AgentRunError(409, "A run is active on this design; wait for it or stop it")

    async def _start(self, context: Any, owner: str, design: Mapping[str, Any], text: str, phase: str, head: str | None, payload: Mapping[str, Any]):
        runs = self._runs(context)
        run_context: dict[str, Any] = {"plugin_options": {NAMESPACE: {"design_id": design["id"], "head": head, "phase": phase}}}
        model_name = payload.get("model_name")
        if model_name is not None:
            if not isinstance(model_name, str) or not MODEL_NAME.fullmatch(model_name):
                raise ValueError("invalid model_name")
            run_context["model_name"] = model_name
        mode = payload.get("mode", "flash")
        if mode not in ("flash", "thinking"):
            raise ValueError("mode must be flash or thinking")
        run_context["thinking_enabled"] = mode == "thinking"
        run = await runs.start(
            thread_id=design["thread_id"],
            input={"messages": [{"role": "user", "content": text}]},
            context=run_context,
            stream_mode=list(STREAM_MODE),
        )
        await self._call(self.store.set_run, owner, design["id"], run.run_id)
        return run

    # -- designs ---------------------------------------------------------------

    async def list_designs(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        trash = payload.get("trash", False)
        if type(trash) is not bool:
            raise ValueError("trash must be boolean")
        designs = await self._call(self.store.list_designs, self._owner(context), trash=trash)
        return {"designs": [{"id": d["id"], "title": d["title"], "updated_at": d["updated_at"], "versions": d["versions"], "thumbnail": None, "deleted_at": d["deleted_at"]} for d in designs]}

    async def create_design(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        owner = self._owner(context)
        title = clean_title(payload.get("title"))
        runs = self._runs(context)
        design_id = new_id()
        # Hidden from the chat lists (deerflow_listed); still reachable by URL.
        thread_id = await runs.create_thread(metadata={"cad_design_id": design_id, "deerflow_listed": False})
        try:
            design = await self._call(self.store.create_design, owner, design_id, title, thread_id)
        except BaseException:
            # A refused row (the per-owner cap) would orphan the thread: it is unlisted
            # and only purge_design, which needs the row, ever deletes it.
            try:
                await runs.delete_thread(thread_id=thread_id)
            except AgentRunError:
                pass
            raise
        return {"design": design}

    async def get_design(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        owner = self._owner(context)
        design_id = _id(payload, "design_id")
        design = await self._call(self.store.get_design, owner, design_id)
        versions = await self._call(self.store.versions, owner, design_id)
        budget = DESIGN_SOURCE_BYTES
        for version in reversed(versions):
            size = len(version["scad"].encode("utf-8"))
            if size > budget and version["id"] != design["head_version_id"]:
                version["scad"] = None
                version["scad_omitted"] = True
            else:
                budget -= size
        return {"design": design, "versions": versions}

    async def get_version(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        return {"version": await self._call(self.store.get_version, self._owner(context), _id(payload, "design_id"), _id(payload, "version_id"))}

    async def rename_design(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        if not isinstance(payload.get("title"), str):
            raise ValueError("title must be text")
        return {"design": await self._call(self.store.rename, self._owner(context), _id(payload, "design_id"), clean_title(payload["title"]))}

    async def delete_design(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        return {"design": await self._call(self.store.delete, self._owner(context), _id(payload, "design_id"))}

    async def restore_design(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        return {"design": await self._call(self.store.restore, self._owner(context), _id(payload, "design_id"))}

    async def purge_design(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        """Delete for good: the rows and the design's thread, which holds every prompt, draft and build file.

        The thread is unlisted, so the user has no other place to delete it. It goes
        first: a refusal (work in flight) leaves the design in the Trash to try again.
        """
        owner = self._owner(context)
        design_id = _id(payload, "design_id")
        design = await self._call(self.store.get_design, owner, design_id, deleted=True)
        try:
            await self._runs(context).delete_thread(thread_id=design["thread_id"])
        except AgentRunError as exc:
            if exc.status_code != 404:
                raise
        await self._call(self.store.purge, owner, design_id)
        return {"purged": True}

    # -- versions --------------------------------------------------------------

    async def save_version(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        owner = self._owner(context)
        design_id = _id(payload, "design_id")
        parent_id = _id(payload, "parent_id") if payload.get("parent_id") is not None else None
        source = payload.get("source")
        if source not in ("hand", "slider"):
            raise ValueError("source must be hand or slider")
        scad = self._source(payload.get("scad"))
        params = clean_params(payload.get("params", {}))
        design = await self._call(self.store.get_design, owner, design_id)
        await self._idle(context, design)
        version = await self._call(self.store.add_version, owner, design_id, parent_id=parent_id, source=source, scad=scad, params=params)
        return {"version": version}

    async def report_render(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        render = clean_render(payload.get("render"))
        return {"version": await self._call(self.store.set_render, self._owner(context), _id(payload, "design_id"), _id(payload, "version_id"), render)}

    async def set_head(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        return {"design": await self._call(self.store.set_head, self._owner(context), _id(payload, "design_id"), _id(payload, "version_id"))}

    # -- runs ------------------------------------------------------------------

    async def prompt(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        owner = self._owner(context)
        design_id = _id(payload, "design_id")
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_PROMPT_CHARS:
            raise ValueError(f"text must be 1 to {MAX_PROMPT_CHARS} characters")
        design = await self._call(self.store.get_design, owner, design_id)
        versions = await self._call(self.store.versions, owner, design_id)
        base, _, whole = hand_edits(versions, design["head_version_id"])
        head = next((version for version in versions if version["id"] == design["head_version_id"]), None)
        if head is not None and head["source"] not in MODEL_SOURCES:
            if base is None:
                # The user wrote this file without a model version to diff against:
                # the note can only name it, so the message carries it.
                text += WRITTEN_SUFFIX.format(scad=head["scad"])
            elif not whole:
                # The note's diff is cut; the model still needs the file it builds on.
                text += EDITED_SUFFIX.format(scad=head["scad"])
        run = await self._start(context, owner, design, text, "draft", design["head_version_id"], payload)
        return {"run_id": run.run_id, "thread_id": design["thread_id"]}

    async def repair(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        owner = self._owner(context)
        design_id = _id(payload, "design_id")
        version = await self._call(self.store.get_version, owner, design_id, _id(payload, "version_id"))
        render = version.get("render") or {}
        if version["source"] != "model" or version["repair_requested"] or render.get("ok") is not False:
            raise AgentRunError(409, "Only a failed model draft gets one automatic repair")
        design = await self._call(self.store.get_design, owner, design_id)
        if design["head_version_id"] != version["id"]:
            await self._call(self.store.set_head, owner, design_id, version["id"])
        run = await self._start(context, owner, design, REPAIR_MESSAGE.format(seq=version["seq"]), "repair", version["id"], payload)
        await self._call(self.store.mark_repair, owner, design_id, version["id"])
        return {"run_id": run.run_id, "thread_id": design["thread_id"]}

    async def finalize(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        owner = self._owner(context)
        design_id = _id(payload, "design_id")
        version = await self._call(self.store.get_version, owner, design_id, _id(payload, "version_id"))
        render = version.get("render") or {}
        if render.get("ok") is not True or not isinstance(render.get("bbox_mm"), list):
            raise AgentRunError(409, "Finalize a draft that rendered without errors")
        design = await self._call(self.store.get_design, owner, design_id)
        await self._call(self.store.set_head, owner, design_id, version["id"])
        previous = version.get("final")
        await self._call(self.store.set_final, owner, design_id, version["id"], {"status": "running", "files": [], "draft_bbox_mm": render["bbox_mm"]})
        try:
            run = await self._start(context, owner, design, FINALIZE_MESSAGE.format(seq=version["seq"], scad=version["scad"]), "finalize", version["id"], payload)
        except BaseException:
            if previous is not None:
                await self._call(self.store.set_final, owner, design_id, version["id"], previous)
            else:
                await self._call(self.store.set_final, owner, design_id, version["id"], {"status": "failed", "files": [], "message": "The finalize run did not start."})
            raise
        current = await self._call(self.store.get_version, owner, design_id, version["id"])
        final = current.get("final") or {}
        if final.get("status") == "running" and not final.get("run_id"):
            await self._call(self.store.set_final, owner, design_id, version["id"], {**final, "run_id": run.run_id})
        return {"run_id": run.run_id, "thread_id": design["thread_id"]}

    async def messages(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        design = await self._call(self.store.get_design, self._owner(context), _id(payload, "design_id"))
        state = await self._runs(context).get_state(thread_id=design["thread_id"])
        values = state.get("values") if isinstance(state, Mapping) else None
        return {"messages": simplify_messages(values.get("messages") if isinstance(values, Mapping) else None)}

    async def run_status(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        owner = self._owner(context)
        design_id = _id(payload, "design_id")
        run_id = _run_id(payload)
        design = await self._call(self.store.get_design, owner, design_id)
        run = await self._runs(context).get(thread_id=design["thread_id"], run_id=run_id)
        if run.status not in ACTIVE:
            # A finalize run that ended without a build would otherwise read "running" forever.
            for version in await self._call(self.store.versions, owner, design_id):
                final = version.get("final") or {}
                if final.get("status") == "running" and final.get("run_id") == run_id:
                    await self._call(self.store.set_final, owner, design_id, version["id"], {**final, "status": "failed", "message": "The run ended without building the part."})
            if design.get("run_id") == run_id:
                await self._call(self.store.set_run, owner, design_id, None)
        return {"status": run.status}

    async def cancel(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        design = await self._call(self.store.get_design, self._owner(context), _id(payload, "design_id"))
        await self._runs(context).cancel(thread_id=design["thread_id"], run_id=_run_id(payload))
        return {"cancelled": True}


ACTIONS = (
    "list_designs",
    "create_design",
    "get_design",
    "get_version",
    "rename_design",
    "delete_design",
    "restore_design",
    "purge_design",
    "save_version",
    "report_render",
    "set_head",
    "prompt",
    "repair",
    "finalize",
    "messages",
    "run_status",
    "cancel",
)
