"""HTTP client for a ComfyUI service.

ComfyUI's job API is four calls: submit a graph (``POST /prompt``), poll for it
(``GET /history/{prompt_id}``), fetch the produced bytes (``GET /view``), and
ask the running build what it can do (``GET /object_info``). Two more exist for
the GPU arbiter: ``GET /system_stats`` (what is resident) and ``POST /free``
(give the VRAM back).

Everything here is transport. Graph construction lives in :mod:`.templates`,
residency policy in :mod:`.arbiter`, and the agent-facing contract in
:mod:`.tools`, so this module can be exercised against a fake transport without
any of them.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8188"
# Deployment-level override, mirroring DEER_FLOW_SEARXNG_BASE_URL: the same
# config.yaml then works host-run and inside the Docker stack. Deliberately
# free of KEY/TOKEN/SECRET so `env_policy.build_sandbox_env` does not scrub it
# from skill subprocesses.
BASE_URL_ENV_VAR = "DEER_FLOW_COMFYUI_BASE_URL"


class ComfyUIError(RuntimeError):
    """A ComfyUI call failed in a way the agent should be told about."""


class ComfyUIUnavailableError(ComfyUIError):
    """The service could not be reached at all."""


class ComfyUIPromptRejected(ComfyUIError):
    """ComfyUI refused the submitted graph (node validation)."""


class ComfyUITimeout(ComfyUIError):
    """The prompt did not finish inside the caller's wall-clock budget."""


@dataclass(frozen=True)
class OutputFile:
    """One file ComfyUI produced, addressed the way ``/view`` wants it."""

    filename: str
    subfolder: str
    type: str
    node_id: str
    kind: str  # "image" | "animation"

    @property
    def view_params(self) -> dict[str, str]:
        return {"filename": self.filename, "subfolder": self.subfolder, "type": self.type}


@dataclass
class PromptResult:
    """Everything a finished prompt produced, in submission order per node."""

    prompt_id: str
    outputs: list[OutputFile] = field(default_factory=list)
    duration_seconds: float = 0.0

    def images(self) -> list[OutputFile]:
        return [output for output in self.outputs if output.kind == "image"]

    def animations(self) -> list[OutputFile]:
        return [output for output in self.outputs if output.kind == "animation"]


def _collect_outputs(history_entry: dict[str, Any]) -> list[OutputFile]:
    """Flatten a history entry's per-node outputs into addressable files.

    ComfyUI reports still images under ``images`` and assembled clips under
    ``gifs`` (the key predates mp4 support and is what VideoHelperSuite still
    writes). Both carry the same filename/subfolder/type triple.
    """
    collected: list[OutputFile] = []
    outputs = history_entry.get("outputs")
    if not isinstance(outputs, dict):
        return collected
    # Node ids are numeric strings, so sort them numerically: a lexicographic
    # sort puts node 12 before node 9 and silently reorders a clip's outputs.
    for node_id, node_output in sorted(outputs.items(), key=_node_sort_key):
        if not isinstance(node_output, dict):
            continue
        for key, kind in (("images", "image"), ("gifs", "animation")):
            entries = node_output.get(key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or not entry.get("filename"):
                    continue
                # ComfyUI writes previews into type="temp"; only saved outputs
                # are stable enough to hand back as an artifact.
                if entry.get("type") not in (None, "output"):
                    continue
                collected.append(
                    OutputFile(
                        filename=str(entry["filename"]),
                        subfolder=str(entry.get("subfolder") or ""),
                        type=str(entry.get("type") or "output"),
                        node_id=str(node_id),
                        kind=kind,
                    )
                )
    return collected


def _node_sort_key(item: tuple[str, Any]) -> tuple[int, float, str]:
    node_id = item[0]
    try:
        return (0, float(node_id), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(node_id))


def _status_error(history_entry: dict[str, Any]) -> str | None:
    """Return a human-readable failure from a history entry, or None."""
    status = history_entry.get("status")
    if not isinstance(status, dict):
        return None
    if status.get("status_str") not in {"error", "failed"}:
        return None
    for message in status.get("messages") or []:
        if isinstance(message, list | tuple) and len(message) >= 2 and message[0] == "execution_error":
            detail = message[1]
            if isinstance(detail, dict):
                node = detail.get("node_type") or detail.get("node_id")
                return f"ComfyUI execution failed at node {node}: {detail.get('exception_message') or detail.get('exception_type')}"
    return "ComfyUI reported an execution error"


class ComfyUIClient:
    """Thin async wrapper over the ComfyUI HTTP API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        request_timeout: float = 30.0,
        poll_interval: float = 1.5,
        client_factory: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout
        self.poll_interval = poll_interval
        # Injectable so tests drive a fake transport instead of a live service.
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=self.request_timeout))

    # ── low-level ────────────────────────────────────────────────────────

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            async with self._client_factory() as client:
                response = await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise ComfyUIUnavailableError(f"ComfyUI at {self.base_url} is unreachable: {exc}") from exc
        return response

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._request(method, path, **kwargs)
        if response.status_code >= 400:
            raise ComfyUIError(f"ComfyUI {method} {path} failed with HTTP {response.status_code}: {response.text[:500]}")
        try:
            return response.json()
        except ValueError as exc:
            raise ComfyUIError(f"ComfyUI {method} {path} returned a non-JSON body") from exc

    # ── API surface ──────────────────────────────────────────────────────

    async def object_info(self) -> dict[str, Any]:
        """The running build's node catalogue — the source of truth for templates."""
        data = await self._json("GET", "/object_info")
        if not isinstance(data, dict):
            raise ComfyUIError("ComfyUI /object_info did not return an object")
        return data

    async def system_stats(self) -> dict[str, Any]:
        data = await self._json("GET", "/system_stats")
        return data if isinstance(data, dict) else {}

    async def free(self, *, unload_models: bool = True, free_memory: bool = True) -> bool:
        """Ask ComfyUI to give the card back. Best-effort by design."""
        try:
            response = await self._request("POST", "/free", json={"unload_models": unload_models, "free_memory": free_memory})
        except ComfyUIUnavailableError:
            # A ComfyUI that is not running holds no VRAM — that is the
            # post-condition the caller wanted.
            return True
        return response.status_code < 400

    async def submit(self, graph: dict[str, Any], *, client_id: str | None = None) -> str:
        payload = {"prompt": graph, "client_id": client_id or uuid.uuid4().hex}
        response = await self._request("POST", "/prompt", json=payload)
        if response.status_code >= 400:
            raise ComfyUIPromptRejected(_describe_rejection(response))
        try:
            data = response.json()
        except ValueError as exc:
            raise ComfyUIError("ComfyUI /prompt returned a non-JSON body") from exc
        prompt_id = data.get("prompt_id") if isinstance(data, dict) else None
        if not prompt_id:
            raise ComfyUIPromptRejected(f"ComfyUI accepted no prompt id: {str(data)[:500]}")
        return str(prompt_id)

    async def history(self, prompt_id: str) -> dict[str, Any] | None:
        data = await self._json("GET", f"/history/{prompt_id}")
        if not isinstance(data, dict):
            return None
        entry = data.get(prompt_id)
        return entry if isinstance(entry, dict) else None

    async def download(self, output: OutputFile) -> bytes:
        response = await self._request("GET", "/view", params=output.view_params)
        if response.status_code >= 400:
            raise ComfyUIError(f"ComfyUI /view failed for {output.filename} with HTTP {response.status_code}")
        return response.content

    async def run(self, graph: dict[str, Any], *, timeout: float, sleep: Any = asyncio.sleep, now: Any = time.monotonic) -> PromptResult:
        """Submit a graph and wait for its outputs.

        ``timeout`` is the caller's own budget — image and video pass different
        values, because a shared one would either abandon working clips or let
        a wedged image run hold the GPU for half an hour.
        """
        started = now()
        prompt_id = await self.submit(graph)
        while True:
            entry = await self.history(prompt_id)
            if entry:
                error = _status_error(entry)
                if error:
                    raise ComfyUIError(error)
                outputs = _collect_outputs(entry)
                if outputs:
                    return PromptResult(prompt_id=prompt_id, outputs=outputs, duration_seconds=now() - started)
                status = entry.get("status")
                if isinstance(status, dict) and status.get("completed"):
                    raise ComfyUIError(f"ComfyUI finished prompt {prompt_id} without saving any output; check that the template's save node is enabled")
            elapsed = now() - started
            if elapsed >= timeout:
                raise ComfyUITimeout(f"ComfyUI prompt {prompt_id} did not finish within {timeout:.0f}s (elapsed {elapsed:.0f}s)")
            await sleep(self.poll_interval)


def _describe_rejection(response: httpx.Response) -> str:
    """Turn ComfyUI's validation dump into one sentence naming the node.

    The native error is a nested ``node_errors`` map; handing that to a model
    verbatim is how a stale template turns into an unreadable wall of JSON.
    """
    try:
        data = response.json()
    except ValueError:
        return f"ComfyUI rejected the workflow (HTTP {response.status_code}): {response.text[:500]}"
    if not isinstance(data, dict):
        return f"ComfyUI rejected the workflow (HTTP {response.status_code})"
    node_errors = data.get("node_errors")
    if isinstance(node_errors, dict) and node_errors:
        parts: list[str] = []
        for node_id, detail in sorted(node_errors.items()):
            messages: list[str] = []
            if isinstance(detail, dict):
                for err in detail.get("errors") or []:
                    if isinstance(err, dict):
                        messages.append(str(err.get("message") or err.get("type")))
                class_type = detail.get("class_type")
            else:
                class_type = None
            label = f"node {node_id}" + (f" ({class_type})" if class_type else "")
            parts.append(f"{label}: {'; '.join(messages) or 'invalid'}")
        return "ComfyUI rejected the workflow — " + " | ".join(parts)
    error = data.get("error")
    if isinstance(error, dict):
        return f"ComfyUI rejected the workflow: {error.get('message') or error.get('type')}"
    return f"ComfyUI rejected the workflow (HTTP {response.status_code})"


def checkpoints_from_object_info(object_info: dict[str, Any]) -> list[str]:
    """Installed checkpoints, read from the loader node's own enum.

    ``CheckpointLoaderSimple.ckpt_name``'s enum *is* the list of checkpoints the
    running build can load. That is the primitive that lets one sentence pick a
    model, and it is the main reason this fork drives ComfyUI rather than a
    simpler HTTP image wrapper.
    """
    return enum_values(object_info, "CheckpointLoaderSimple", "ckpt_name")


def enum_values(object_info: dict[str, Any], class_type: str, input_name: str) -> list[str]:
    """Return the allowed values for one node input, or [] when not an enum."""
    node = object_info.get(class_type)
    if not isinstance(node, dict):
        return []
    inputs = node.get("input")
    if not isinstance(inputs, dict):
        return []
    for group in ("required", "optional"):
        spec = inputs.get(group)
        if not isinstance(spec, dict) or input_name not in spec:
            continue
        entry = spec[input_name]
        if isinstance(entry, list) and entry and isinstance(entry[0], list):
            return [str(value) for value in entry[0]]
        return []
    return []


def declared_inputs(object_info: dict[str, Any], class_type: str) -> set[str]:
    """Every input name a node class declares (required + optional)."""
    node = object_info.get(class_type)
    if not isinstance(node, dict):
        return set()
    inputs = node.get("input")
    if not isinstance(inputs, dict):
        return set()
    names: set[str] = set()
    for group in ("required", "optional"):
        spec = inputs.get(group)
        if isinstance(spec, dict):
            names.update(str(name) for name in spec)
    return names
