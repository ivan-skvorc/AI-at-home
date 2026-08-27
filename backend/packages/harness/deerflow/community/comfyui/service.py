"""Resolution layer: config + service state → a submittable, validated job.

Everything the agent-facing tools need before they can submit a graph lives
here — reaching the service safely, checking the template against the build
that will run it, picking a model the build actually has, and writing the
results into the thread's outputs directory.

Two decisions are worth keeping:

* **The URL guard is not bypassed.** A loopback ComfyUI is the textbook
  intentional-internal-target case, so it is handled by the documented
  ``allow_private_addresses`` opt-out (default true for this tool), exactly as
  ``browser_automation`` does — not by skipping
  :func:`validate_public_http_url`. Flipping the opt-out to false is then a
  working setting rather than a dead one.
* **The submitted graph is saved beside its output.** ``<name>.workflow.json``
  is the whole of "inspect how the nodes are set up": it opens in ComfyUI's own
  editor and reproduces the result by hand, which makes every failure
  debuggable without the Gateway in the loop.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deerflow.community.url_safety import validate_public_http_url
from deerflow.config import get_app_config
from deerflow.config.media_config import MediaConfig
from deerflow.config.paths import VIRTUAL_PATH_PREFIX

from .client import BASE_URL_ENV_VAR, ComfyUIClient, checkpoints_from_object_info, enum_values
from .templates import TemplateError, WorkflowTemplate, load_template_cached, validate_template, validate_value_against_enum

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
OUTPUTS_VIRTUAL_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs"


class MediaToolError(RuntimeError):
    """A generation could not proceed, with a message meant for the agent."""


def media_config() -> MediaConfig:
    return get_app_config().media


def resolve_base_url(config: MediaConfig | None = None) -> str:
    """Config base_url unless the deployment env var overrides it."""
    override = os.getenv(BASE_URL_ENV_VAR, "").strip()
    if override:
        return override
    return (config or media_config()).comfyui.base_url


def build_client(config: MediaConfig | None = None) -> ComfyUIClient:
    """Screen the endpoint, then build a client for it."""
    cfg = config or media_config()
    base_url = resolve_base_url(cfg)
    guard = validate_public_http_url(
        base_url,
        allow_private_addresses=cfg.comfyui.allow_private_addresses,
        action="reach",
    )
    if guard:
        raise MediaToolError(f"{guard} (media.comfyui.base_url={base_url}). Set media.comfyui.allow_private_addresses: true if this really is your own machine.")
    return ComfyUIClient(
        base_url,
        request_timeout=cfg.comfyui.request_timeout,
        poll_interval=cfg.comfyui.poll_interval,
    )


# Validation is per (base_url, template) and cached for the process: the
# catalogue only changes when ComfyUI restarts, and re-fetching /object_info
# before every generation would add a second round trip to a call that already
# holds the GPU.
_validated: set[tuple[str, str]] = set()


def reset_validation_cache() -> None:
    _validated.clear()


async def validated_template(client: ComfyUIClient, name: str, object_info: dict[str, Any]) -> WorkflowTemplate:
    """Load a template and check it against the running build.

    A stale template fails here, naming the node that moved — the alternative
    is ComfyUI's own validation dump, which is a wall of JSON rather than a
    sentence.
    """
    try:
        template = load_template_cached(name)
    except TemplateError as exc:
        raise MediaToolError(str(exc)) from exc
    key = (client.base_url, name)
    if key in _validated:
        return template
    problems = validate_template(template, object_info)
    if problems:
        raise MediaToolError(f"Workflow template '{name}' no longer matches this ComfyUI build — " + " | ".join(problems))
    _validated.add(key)
    return template


def resolve_enum_choice(
    template: WorkflowTemplate,
    object_info: dict[str, Any],
    *,
    param: str,
    requested: str | None,
    configured: str | None,
    label: str,
) -> str:
    """Pick a model file for one bound parameter: request → config → what is installed.

    The last step is the point of driving ComfyUI: the enum on the loader node
    *is* the list of installed files, so a fresh install with one checkpoint
    generates without anyone naming it.
    """
    binding = template.bindings.get(param)
    if binding is None:
        raise MediaToolError(f"Workflow template '{template.name}' does not expose a '{param}' parameter")
    class_type = template.node_class(binding.node) or ""
    installed = enum_values(object_info, class_type, binding.input)
    for candidate in (requested, configured):
        if not candidate:
            continue
        problem = validate_value_against_enum(template, object_info, param, candidate)
        if problem:
            raise MediaToolError(problem)
        return candidate
    if not installed:
        raise MediaToolError(f"This ComfyUI has no {label} installed (node {binding.node}, {class_type}.{binding.input} is empty). Put one in ComfyUI's models directory and try again.")
    return installed[0]


def available_models(object_info: dict[str, Any]) -> dict[str, list[str]]:
    """Everything a caller might need to name, read from the build itself."""
    models = {
        "checkpoints": checkpoints_from_object_info(object_info),
        "unets": enum_values(object_info, "UNETLoader", "unet_name"),
        "gguf_unets": enum_values(object_info, "UnetLoaderGGUF", "unet_name"),
        "clips": enum_values(object_info, "CLIPLoader", "clip_name"),
        "vaes": enum_values(object_info, "VAELoader", "vae_name"),
        "loras": enum_values(object_info, "LoraLoader", "lora_name"),
        "samplers": enum_values(object_info, "KSampler", "sampler_name"),
        "schedulers": enum_values(object_info, "KSampler", "scheduler"),
    }
    return {key: value for key, value in models.items() if value}


# ── output naming and writing ────────────────────────────────────────────


def slugify(text: str, *, fallback: str = "generated", max_length: int = 40) -> str:
    cleaned = _SAFE_NAME_RE.sub("-", (text or "").strip().lower()).strip("-._")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return (cleaned[:max_length].strip("-._") or fallback).lower()


def timestamped_stem(label: str, *, fallback: str = "generated") -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{slugify(label, fallback=fallback)}-{stamp}"


@dataclass(frozen=True)
class WrittenOutput:
    """One file written into the thread's outputs directory."""

    path: Path
    virtual_path: str


def write_output(outputs_dir: Path, name: str, content: bytes, *, subdir: str | None = None) -> WrittenOutput:
    """Write bytes under the thread's outputs directory and return both paths."""
    safe_name = _SAFE_NAME_RE.sub("-", name).strip("-") or "output"
    directory = Path(outputs_dir) if subdir is None else Path(outputs_dir) / _SAFE_NAME_RE.sub("-", subdir).strip("-")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / safe_name
    path.write_bytes(content)
    relative = path.relative_to(Path(outputs_dir)).as_posix()
    return WrittenOutput(path=path, virtual_path=f"{OUTPUTS_VIRTUAL_PREFIX}/{relative}")
