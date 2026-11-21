"""The two boundaries a run crosses: the running Gateway, and the process that measures a STEP.

Everything goes through public HTTP routes, as ``drift_eval``'s agent mode does,
so a result is a statement about the deployed system: the request goes in as a
user message, the transcript comes back from the run's event store, and the
delivered STEP is downloaded through the artifact route like any user's file.
The STEP is measured by the CAD module's own ``measure_cli`` in a child process,
because the Gateway's Python never loads the kernel and neither does this one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .score import measured_from

DEFAULT_BASE_URL = "http://localhost:8001"
#: A local model on a 32K window can take many minutes for a part it repairs several times.
DEFAULT_TIMEOUT_SECONDS = 1_800
MEASURE_TIMEOUT_SECONDS = 300
#: The CAD module's namespace and tool, as /api/plugins lists them.
CAD_NAMESPACE = "cad"
CAD_TOOL = "cad_build"
#: Page size for the run's messages; the route's own maximum.
MESSAGE_PAGE = 200


class StartRefused(Exception):
    """The eval cannot give a meaningful result on this Gateway, so it does not start."""


class SpendCapReached(Exception):
    """The Gateway refused a run at admission (HTTP 402): the operator's spend cap is spent."""


@dataclass
class GatewayFacts:
    model: str
    provider_model: str | None = None
    context_window: int | None = None


@dataclass
class RunRecord:
    thread_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def headers() -> dict[str, str]:
    """Bearer token from the environment, never from a flag: a flag lands in shell history and the run record."""
    token = os.environ.get("DEER_FLOW_API_TOKEN") or os.environ.get("DEER_FLOW_CAD_EVAL_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def check_gateway(client: httpx.AsyncClient, model: str, *, module_on: bool = True) -> GatewayFacts:
    """Refuse to start unless the Gateway has the CAD module in the state asked for and knows the model."""
    try:
        plugins = (await client.get("/api/plugins")).raise_for_status().json()
    except httpx.HTTPError as exc:
        raise StartRefused(f"the Gateway at {client.base_url} did not answer /api/plugins ({type(exc).__name__}: {exc}). Start the stack with `make dev`, or pass --base-url.") from None
    cad = next((entry for entry in plugins if isinstance(entry, dict) and entry.get("namespace") == CAD_NAMESPACE and CAD_TOOL in (entry.get("model_tools") or [])), None)
    enabled = cad is not None and (cad.get("settings") or {}).get("enabled", True) is True
    if module_on and not enabled:
        raise StartRefused("the CAD module is not installed or not enabled on this Gateway: /api/plugins has no 'cad' namespace with cad_build. Install it (`make install`) or run `make extension-enable NAME=cad`, restart, and run again.")
    if not module_on and enabled:
        raise StartRefused("--no-module needs the CAD module turned off: run `make extension-disable NAME=cad`, restart, and run again.")
    try:
        listed = (await client.get("/api/models")).raise_for_status().json().get("models") or []
    except httpx.HTTPError as exc:
        raise StartRefused(f"the Gateway did not answer /api/models ({type(exc).__name__}: {exc}).") from None
    entry = next((item for item in listed if isinstance(item, dict) and item.get("name") == model), None)
    if entry is None:
        # The Gateway falls back to its default model for an unknown name; a row under the wrong name is worse than none.
        names = ", ".join(sorted(str(item.get("name")) for item in listed if isinstance(item, dict))) or "none"
        raise StartRefused(f"model {model!r} is not configured on this Gateway (configured: {names}). Use a name from config.yaml.")
    return GatewayFacts(model=model, provider_model=entry.get("model"), context_window=entry.get("context_window"))


async def run_request(client: httpx.AsyncClient, *, prompt: str, model: str, thread_id: str, timeout: float) -> RunRecord:
    """Send *prompt* as a user message in a new thread, wait for the run, and read back everything it did."""
    body = {
        "assistant_id": "lead_agent",
        "input": {"messages": [{"role": "user", "content": prompt}]},
        "config": {"configurable": {"thread_id": thread_id}},
        # An explicit selection: the run fails instead of falling back to another model.
        "context": {"model_name": model, "model_selection_requested": model},
    }
    try:
        response = await client.post("/api/runs/wait", json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        return RunRecord(thread_id, error=f"run failed: {type(exc).__name__}: {exc}")
    if response.status_code == 402:
        raise SpendCapReached(response.text[:300])
    if response.is_error:
        return RunRecord(thread_id, error=f"run failed: HTTP {response.status_code}: {response.text[:300]}")
    state = response.json()
    error = None
    if not isinstance(state, dict) or "messages" not in state:
        error = f"run ended without a state: {json.dumps(state)[:300]}"
    messages = await _run_messages(client, thread_id)
    if not messages and isinstance(state, dict):
        messages = [message for message in state.get("messages") or [] if isinstance(message, dict)]
    return RunRecord(thread_id, messages=messages, error=error)


async def _run_messages(client: httpx.AsyncClient, thread_id: str) -> list[dict[str, Any]]:
    """Every message the run produced, from its event store.

    The thread state is what is left after compaction, which drops older tool
    results; the event store keeps each one, so refusals and builds are counted in full.
    """
    try:
        runs = (await client.get(f"/api/threads/{thread_id}/runs")).raise_for_status().json()
        if not runs:
            return []
        run_id = runs[0]["run_id"]
        messages: list[dict[str, Any]] = []
        after = 0
        while True:
            page = (await client.get(f"/api/threads/{thread_id}/runs/{run_id}/messages", params={"limit": MESSAGE_PAGE, "after_seq": after})).raise_for_status().json()
            rows = page.get("data") or []
            # A middleware's own model call (a title, a summary) is logged in the run too; it is not the model at work.
            messages.extend(row["content"] for row in rows if isinstance(row.get("content"), dict) and not str((row.get("metadata") or {}).get("caller", "")).startswith("middleware:"))
            if not page.get("has_more") or not rows:
                return messages
            after = max(int(row.get("seq") or after) for row in rows)
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return []


async def token_usage(client: httpx.AsyncClient, thread_id: str) -> dict[str, Any]:
    try:
        return (await client.get(f"/api/threads/{thread_id}/token-usage")).raise_for_status().json()
    except (httpx.HTTPError, ValueError):
        return {}


async def download(client: httpx.AsyncClient, thread_id: str, virtual_path: str, directory: Path) -> Path:
    """Fetch one file the run wrote, through the same artifact route a user's download takes."""
    response = await client.get(f"/api/threads/{thread_id}/artifacts/{virtual_path.lstrip('/')}", params={"download": "true"})
    response.raise_for_status()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / Path(virtual_path).name
    target.write_bytes(response.content)
    return target


class MeasureCli:
    """``python -I -m deerflow_extension_cad.measure_cli <step>``, in an environment that has the CAD module."""

    def __init__(self, python: str = sys.executable):
        self.python = python

    def problem(self) -> str | None:
        probe = "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('deerflow_extension_cad.measure_cli') else 3)"
        try:
            done = subprocess.run([self.python, "-I", "-c", probe], capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"{self.python} could not be started ({exc})"
        if done.returncode != 0:
            return f"the CAD module's measure_cli is not installed for {self.python}: the eval measures each STEP with it. Install the CAD module there, or pass --measure-python."
        return None

    def measure(self, step: Path) -> dict[str, Any]:
        done = subprocess.run([self.python, "-I", "-m", "deerflow_extension_cad.measure_cli", str(step)], capture_output=True, text=True, timeout=MEASURE_TIMEOUT_SECONDS, check=True)
        return measured_from(json.loads(done.stdout))
