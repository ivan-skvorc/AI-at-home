"""The page's backend actions. Every one re-reads the design under the caller's user id.

Runs go through the host's AgentRuns handle, so the host checks thread
ownership again and stamps the input messages as this plugin's. A design run
carries ``plugin_options["cad-design"] = {design_id}``; that flag is what turns
the design brief on (middleware.py).

Nothing here reads or writes the design's files: the model renders them in the
run's container, and the page lists and reads them through the host's thread
file routes. ``container`` tells the page whether this host runs those
containers at all (``HostPolicySnapshot.sandbox_container``, API 0.2.15).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import AgentRunError

from .constants import FOLDER, ID, NAMESPACE, RUN_ID
from .notes import VIEWING_SUFFIX
from .store import Conflict, NotFound, Store, clean_title, new_id

ACTIVE = frozenset({"pending", "running"})
STREAM_MODE = ["values", "messages-tuple"]
MAX_PROMPT_CHARS = 8000
MAX_MESSAGES = 200
MAX_MESSAGE_CHARS = 20000
#: A tool result is output the user skims (a cadkit summary, a file read): the page shows its start.
MAX_TOOL_CHARS = 4000
#: A tool call is shown as its name and one line of its arguments.
MAX_SUMMARY_CHARS = 200
#: The argument that says best what a call does, in order: a bash command, a file, the files presented.
SUMMARY_KEYS = ("command", "path", "image_path", "filepaths", "description")
MAX_VERSION = 100_000
MODEL_NAME = re.compile(r"[A-Za-z0-9._:/@+-]{1,128}")


class HostSandbox:
    """The host's sandbox mode, as the Gateway projects it at start (an ExtensionService).

    ``sandbox`` is startup-only configuration, so the value read once at start
    holds until the Gateway restarts. Before start, and on a host older than
    API 0.2.15, it reads False.
    """

    def __init__(self) -> None:
        self.container = False

    async def start(self, deps: Any) -> None:
        self.container = getattr(getattr(deps, "policy", None), "sandbox_container", False) is True

    async def stop(self) -> None:
        return None


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


def _version(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= MAX_VERSION:
        raise ValueError(f"{key} must be a version number")
    return value


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, Mapping) and part.get("type", "text") == "text" else part if isinstance(part, str) else "" for part in content)
    return ""


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _line(value: Any) -> str:
    if isinstance(value, str):
        lines = value.strip().splitlines()
        return lines[0].strip() if lines else ""
    if isinstance(value, list):
        names = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return ", ".join(names[:5]) + (f" (+{len(names) - 5} more)" if len(names) > 5 else "")
    return ""


def summarize_args(args: Any) -> str:
    """One bounded line for a tool call: a bash command's first line, a path, else the first text argument."""
    if not isinstance(args, Mapping):
        return ""
    for key in SUMMARY_KEYS:
        line = _line(args.get(key))
        if line:
            return _cut(line, MAX_SUMMARY_CHARS)
    for value in args.values():
        line = _line(value)
        if line:
            return _cut(line, MAX_SUMMARY_CHARS)
    return ""


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
        entry: dict[str, Any] = {"id": str(message.get("id") or ""), "role": role, "text": _cut(text, MAX_TOOL_CHARS) if role == "tool" else text[:MAX_MESSAGE_CHARS]}
        if role == "assistant" and message.get("tool_calls"):
            entry["tool_calls"] = [{"name": str(call.get("name") or ""), "summary": summarize_args(call.get("args"))} for call in message["tool_calls"] if isinstance(call, Mapping)]
        if role == "tool":
            entry["tool_name"] = str(message.get("name") or "")
        shown.append(entry)
    return shown[-MAX_MESSAGES:]


class Designs:
    def __init__(self, store: Store, sandbox: HostSandbox):
        self.store = store
        self.sandbox = sandbox

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

    # -- designs ---------------------------------------------------------------

    async def list_designs(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        trash = payload.get("trash", False)
        if type(trash) is not bool:
            raise ValueError("trash must be boolean")
        designs = await self._call(self.store.list_designs, self._owner(context), trash=trash)
        return {"designs": [{key: d[key] for key in ("id", "title", "updated_at", "deleted_at")} for d in designs], "container": self.sandbox.container}

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
        design = await self._call(self.store.get_design, self._owner(context), _id(payload, "design_id"))
        return {"design": design, "folder": FOLDER, "container": self.sandbox.container}

    async def rename_design(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        if not isinstance(payload.get("title"), str):
            raise ValueError("title must be text")
        return {"design": await self._call(self.store.rename, self._owner(context), _id(payload, "design_id"), clean_title(payload["title"]))}

    async def delete_design(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        return {"design": await self._call(self.store.delete, self._owner(context), _id(payload, "design_id"))}

    async def restore_design(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        return {"design": await self._call(self.store.restore, self._owner(context), _id(payload, "design_id"))}

    async def purge_design(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        """Delete for good: the row and the design's thread, which holds every prompt and version folder.

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

    # -- runs ------------------------------------------------------------------

    async def prompt(self, payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        """Start a design run with the user's message.

        ``viewing`` is the version the page shows and ``newest`` the newest it
        listed, both optional. When the user looks at an older version (or the
        page sends ``viewing`` alone), the message names it, so "make this one
        taller" reaches the model with the version it means.
        """
        owner = self._owner(context)
        design_id = _id(payload, "design_id")
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_PROMPT_CHARS:
            raise ValueError(f"text must be 1 to {MAX_PROMPT_CHARS} characters")
        viewing, newest = _version(payload, "viewing"), _version(payload, "newest")
        if viewing is not None and newest is not None and viewing > newest:
            raise ValueError("viewing must not be newer than newest")
        if viewing is not None and (newest is None or viewing < newest):
            text += VIEWING_SUFFIX.format(seq=viewing, folder=FOLDER)
        run_context: dict[str, Any] = {"plugin_options": {NAMESPACE: {"design_id": design_id}}}
        model_name = payload.get("model_name")
        if model_name is not None:
            if not isinstance(model_name, str) or not MODEL_NAME.fullmatch(model_name):
                raise ValueError("invalid model_name")
            run_context["model_name"] = model_name
        mode = payload.get("mode", "flash")
        if mode not in ("flash", "thinking"):
            raise ValueError("mode must be flash or thinking")
        run_context["thinking_enabled"] = mode == "thinking"
        design = await self._call(self.store.get_design, owner, design_id)
        run = await self._runs(context).start(
            thread_id=design["thread_id"],
            input={"messages": [{"role": "user", "content": text}]},
            context=run_context,
            stream_mode=list(STREAM_MODE),
        )
        await self._call(self.store.set_run, owner, design_id, run.run_id)
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
        if run.status not in ACTIVE and design.get("run_id") == run_id:
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
    "rename_design",
    "delete_design",
    "restore_design",
    "purge_design",
    "prompt",
    "messages",
    "run_status",
    "cancel",
)
