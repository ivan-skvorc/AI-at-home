#!/usr/bin/env python3
"""Sync Ollama-installed models into config.yaml's models: section.

Idempotent and bounded: this script owns only the content between its
BEGIN/END markers. Hand-edited entries (cloud models, custom Ollama configs)
outside the markers are never touched.

If Ollama is not running, the script exits cleanly with no changes.

Usage:
    python3 scripts/sync-ollama-models.py [--config PATH] [--dry-run] [--verbose]
                                          [--base-url URL] [--container]
                                          [--num-ctx-cap N] [--vram-gb G]
                                          [--kv-cache-type f16|q8_0|q4_0]

Environment:
    OLLAMA_HOST: override Ollama endpoint (default: http://localhost:11434)

The endpoint the script *queries* (``--host`` / ``OLLAMA_HOST``) and the
``base_url`` it *writes* into each model entry are decoupled: a containerized
runtime (Docker paths) queries the host's Ollama over loopback but must record a
``base_url`` the container can reach. ``--container`` rewrites a loopback query
host to ``host.docker.internal`` for the written entries; ``--base-url`` sets it
explicitly (wins over ``--container``).

Context window: Ollama defaults ``num_ctx`` to 2048 tokens regardless of what a
model actually supports, which silently truncates the agent's context (system
prompt + tools + skills + memory + conversation) and is smaller than the 8192
``num_predict`` output budget the entries request. Each entry is therefore
written with an explicit ``num_ctx`` read from the model's native context length
(``/api/show`` -> ``model_info``), clamped to ``--num-ctx-cap`` (default 32768)
so a 128K-native model does not allocate an OOM-sized KV cache on a typical local
GPU. Pass ``--num-ctx-cap 0`` to use each model's full native length uncapped.

VRAM-aware sizing: when a GPU memory budget is known (``ollama.vram_gb`` in
config.yaml — written by ``make setup`` — or ``--vram-gb``), the flat cap is
replaced by a per-model estimate: the largest window whose KV cache fits next to
the model's weights within that budget, derived from the model's attention
geometry (``/api/show`` -> ``model_info``) and its on-disk size (``/api/tags``).
``ollama.kv_cache_type`` / ``--kv-cache-type`` tells the sizing which KV-cache
quantization the daemon runs (``OLLAMA_KV_CACHE_TYPE``): ``q8_0`` roughly halves
the per-token cost versus the default ``f16``, roughly doubling the affordable
window. An explicit ``--num-ctx-cap`` still applies as a hard ceiling; models
whose geometry can't be read fall back to the flat-cap behavior.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_HOST = "http://localhost:11434"
# Loopback host names that mean "this machine" — inside a container these resolve
# to the container itself, not the Docker host where a host-run Ollama listens.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
# host-gateway alias mapped into the gateway container via `extra_hosts` in the
# docker-compose files, so a container can reach a host-run Ollama.
DOCKER_HOST_ALIAS = "host.docker.internal"
BEGIN_MARKER = "# === BEGIN ollama-sync (auto-generated; regenerated on each run) ==="
END_MARKER = "# === END ollama-sync ==="
INDENT = "  "  # entries inside models: are at 2-space indent
# Output-token budget requested per entry (Ollama option: num_predict).
DEFAULT_NUM_PREDICT = 8192
# Ceiling for the auto-written context window (Ollama option: num_ctx). A model
# may advertise 128K+ natively, but allocating that much KV cache can OOM a
# typical local GPU, so the auto-populated value is clamped here; users can raise
# it by hand (or pass --num-ctx-cap 0 for uncapped) on big-memory rigs.
DEFAULT_NUM_CTX_CAP = 32768

# ── VRAM-aware context sizing ─────────────────────────────────────────────────
# When `ollama.vram_gb` is configured (config.yaml, written by `make setup`, or
# --vram-gb), the flat cap above is replaced by a per-model estimate: the largest
# window whose KV cache fits next to the model weights in that budget.
#
# Bytes per KV-cache element by Ollama's OLLAMA_KV_CACHE_TYPE. q8_0/q4_0 are
# block-quantized (32 elements + a 2-byte scale per block), hence the fractions.
KV_CACHE_BYTES_PER_ELEMENT = {"f16": 2.0, "q8_0": 34 / 32, "q4_0": 18 / 32}
DEFAULT_KV_CACHE_TYPE = "f16"
# VRAM reserved for everything that is neither weights nor KV cache: compute
# graph buffers, CUDA/ROCm/Metal context, display, fragmentation. Deliberately
# conservative — and the estimate assumes OLLAMA_NUM_PARALLEL=1 (the modern
# Ollama default; each extra parallel slot multiplies the KV allocation). If the
# estimate is still too optimistic, Ollama degrades by offloading layers to CPU
# (slow, not fatal).
VRAM_OVERHEAD_BYTES = int(1.5 * 1024**3)
# Floor/step for the computed window: below 4096 the agent's system prompt alone
# doesn't fit, and odd sizes buy nothing.
MIN_VRAM_NUM_CTX = 4096
NUM_CTX_STEP = 2048


def normalize_host(host: str) -> str:
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host.rstrip("/")


def containerize_base_url(url: str) -> str:
    """Rewrite a loopback Ollama URL to the Docker host-gateway alias.

    Inside a container ``localhost`` is the container itself, not the host where
    a host-run Ollama listens, so a loopback ``base_url`` written for the
    containerized runtime would be unreachable. ``host.docker.internal`` (mapped
    to the host gateway via ``extra_hosts`` in the compose files) reaches it. A
    non-loopback host (a genuinely remote Ollama) is already reachable from a
    container and is returned unchanged.
    """
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname
    if host is None or host.lower() not in _LOOPBACK_HOSTS:
        return url
    netloc = DOCKER_HOST_ALIAS + (f":{parsed.port}" if parsed.port else "")
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def resolve_base_url(query_host: str, explicit_base_url: str | None, container: bool) -> str:
    """Resolve the ``base_url`` to write into entries (see module docstring).

    Precedence: explicit ``--base-url`` > ``--container`` loopback rewrite >
    the query host itself (so a remote ``OLLAMA_HOST`` is recorded verbatim).
    """
    if explicit_base_url:
        return normalize_host(explicit_base_url)
    if container:
        return containerize_base_url(query_host)
    return query_host


def fetch_tags(host: str, timeout: float = 2.0):
    """Return installed models from /api/tags as [{"name", "size"}, ...].

    ``size`` is the on-disk model size in bytes (≈ VRAM the weights need when
    fully offloaded), used for VRAM-aware context sizing. Returns None if
    Ollama is unreachable.
    """
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
        return None
    return [{"name": m.get("name"), "size": m.get("size")} for m in data.get("models", []) if m.get("name")]


def fetch_show(host: str, name: str, timeout: float = 5.0) -> dict:
    """Return the parsed /api/show payload for a model; {} on error."""
    try:
        req = urllib.request.Request(
            f"{host}/api/show",
            data=json.dumps({"name": name}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _run_docker(args: list, timeout: float = 5.0):
    """Run a docker CLI command, returning stdout or None on any failure."""
    try:
        completed = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _ollama_probe(host: str) -> bool:
    return fetch_tags(host, timeout=2.0) is not None


def container_ollama_warning(base_url: str, *, docker=_run_docker, probe=_ollama_probe):
    """Return a warning when a host.docker.internal base_url looks container-unreachable.

    The ``--container`` rewrite records ``host.docker.internal``, which resolves
    to the Docker bridge gateway on Linux. A host Ollama bound to loopback only —
    its default — answers on localhost but refuses bridge-gateway connections,
    so the gateway container would get "connection refused" for every model
    call. Best-effort: returns None whenever reachability cannot be determined,
    and on Docker Desktop (which proxies host loopback for the alias).
    """
    parsed = urllib.parse.urlsplit(base_url)
    if (parsed.hostname or "").lower() != DOCKER_HOST_ALIAS:
        return None
    operating_system = docker(["info", "--format", "{{.OperatingSystem}}"]) or ""
    if "docker desktop" in operating_system.lower():
        return None
    gateway_ip = (docker(["network", "inspect", "bridge", "--format", "{{(index .IPAM.Config 0).Gateway}}"]) or "").strip()
    if not gateway_ip:
        return None
    port = parsed.port or 11434
    if probe(f"http://{gateway_ip}:{port}"):
        return None
    return (
        f"WARNING: wrote base_url {base_url}, but the host's Ollama does not answer on the Docker bridge gateway ({gateway_ip}:{port}) — "
        "it is likely bound to loopback only, so containers will get 'connection refused' on every model call. "
        'Make Ollama listen on all interfaces and restart it (systemd: sudo systemctl edit ollama, add [Service] Environment="OLLAMA_HOST=0.0.0.0"; '
        "manual: OLLAMA_HOST=0.0.0.0 ollama serve)."
    )


def parse_capabilities(show: dict) -> list:
    """Return the list of capability strings from an /api/show payload."""
    return show.get("capabilities") or []


def parse_context_length(show: dict) -> int | None:
    """Return the model's native context length from an /api/show payload.

    Ollama reports it under ``model_info`` as ``<architecture>.context_length``
    (e.g. ``qwen3.context_length``). Falls back to any ``*.context_length`` key,
    and returns None when the payload does not expose it.
    """
    info = show.get("model_info")
    if not isinstance(info, dict):
        return None
    arch = info.get("general.architecture")
    if isinstance(arch, str):
        value = info.get(f"{arch}.context_length")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return int(value)
    for key, value in info.items():
        if key.endswith(".context_length") and isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return int(value)
    return None


def _positive_number(info: dict, key: str) -> float | None:
    value = info.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


def parse_kv_bytes_per_token(show: dict, kv_cache_type: str = DEFAULT_KV_CACHE_TYPE) -> float | None:
    """Estimate KV-cache bytes per context token from an /api/show payload.

    KV cache per token = layers × kv_heads × (key_dim + value_dim) × bytes/element.
    Head dims come from ``attention.key_length``/``value_length`` when present,
    falling back to ``embedding_length / head_count``. Some hybrid architectures
    report ``head_count_kv`` as a per-layer list; its mean is used. Returns None
    when the payload doesn't expose the needed geometry; an unknown
    ``kv_cache_type`` is costed as f16 (the conservative choice).
    """
    info = show.get("model_info")
    if not isinstance(info, dict):
        return None
    arch = info.get("general.architecture")
    if not isinstance(arch, str):
        return None
    block_count = _positive_number(info, f"{arch}.block_count")
    kv_heads = _positive_number(info, f"{arch}.attention.head_count_kv")
    if kv_heads is None:
        raw = info.get(f"{arch}.attention.head_count_kv")
        if isinstance(raw, list) and raw and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in raw):
            kv_heads = sum(raw) / len(raw)
    key_dim = _positive_number(info, f"{arch}.attention.key_length")
    value_dim = _positive_number(info, f"{arch}.attention.value_length")
    if key_dim is None or value_dim is None:
        head_count = _positive_number(info, f"{arch}.attention.head_count")
        embedding = _positive_number(info, f"{arch}.embedding_length")
        if head_count and embedding:
            head_dim = embedding / head_count
            key_dim = key_dim or head_dim
            value_dim = value_dim or head_dim
    if not (block_count and kv_heads and key_dim and value_dim):
        return None
    bytes_per_element = KV_CACHE_BYTES_PER_ELEMENT.get(kv_cache_type, KV_CACHE_BYTES_PER_ELEMENT[DEFAULT_KV_CACHE_TYPE])
    return block_count * kv_heads * (key_dim + value_dim) * bytes_per_element


def vram_num_ctx_limit(show: dict, weights_bytes, vram_bytes, kv_cache_type: str = DEFAULT_KV_CACHE_TYPE) -> int | None:
    """Largest context window whose KV cache fits VRAM next to the weights.

    ``(vram - weights - VRAM_OVERHEAD_BYTES) / kv_bytes_per_token``, floored to
    ``NUM_CTX_STEP`` and never below ``MIN_VRAM_NUM_CTX`` (a model that doesn't
    fit at all still gets a usable window — Ollama offloads layers to CPU rather
    than failing). Returns None when the geometry or weights size is unknown, so
    callers can fall back to the flat cap.
    """
    per_token = parse_kv_bytes_per_token(show, kv_cache_type)
    if per_token is None or not weights_bytes or weights_bytes <= 0 or not vram_bytes or vram_bytes <= 0:
        return None
    available = vram_bytes - weights_bytes - VRAM_OVERHEAD_BYTES
    if available <= 0:
        return MIN_VRAM_NUM_CTX
    tokens = int(available // per_token)
    return max(MIN_VRAM_NUM_CTX, (tokens // NUM_CTX_STEP) * NUM_CTX_STEP)


def parse_ollama_settings(text: str) -> dict:
    """Parse the top-level ``ollama:`` section of config.yaml.

    Recognized keys: ``vram_gb`` (positive number), ``kv_cache_type`` (one of
    KV_CACHE_BYTES_PER_ELEMENT), ``keep_alive`` (opaque Ollama duration string),
    ``preload`` (bool), and the nested ``keep_alive_overrides`` map of
    model name -> duration. Malformed values are dropped. Pure-text scan on
    purpose — this script runs under plain python3 with no PyYAML.
    """
    top_key = re.compile(r"^[A-Za-z_][\w-]*:")
    entry = re.compile(r"^(\s+)([A-Za-z_][\w.:-]*):\s*([^#]*)")
    raw: dict[str, str] = {}
    overrides: dict[str, str] = {}
    in_section = False
    # Indent of the `keep_alive_overrides:` key, so its children are attributed
    # to the map rather than read as further ollama.* settings.
    overrides_indent: int | None = None

    for line in text.splitlines():
        if not in_section:
            if re.match(r"^ollama:\s*(#.*)?$", line):
                in_section = True
            continue
        if line and not line[0].isspace():
            if top_key.match(line):
                break
            continue
        match = entry.match(line)
        if not match:
            continue
        indent, key, value = len(match.group(1)), match.group(2), match.group(3).strip().strip("\"'")

        if overrides_indent is not None:
            if indent > overrides_indent:
                if value:
                    overrides[key] = value
                continue
            overrides_indent = None  # dedented back out of the map

        if key == "keep_alive_overrides":
            overrides_indent = indent
            continue
        raw[key] = value

    settings: dict = {}
    try:
        vram_gb = float(raw["vram_gb"])
        if vram_gb > 0:
            settings["vram_gb"] = vram_gb
    except (KeyError, ValueError):
        pass
    if raw.get("kv_cache_type") in KV_CACHE_BYTES_PER_ELEMENT:
        settings["kv_cache_type"] = raw["kv_cache_type"]
    # keep_alive is passed through to Ollama verbatim ("30m", "1h", "-1", "600"),
    # so it is deliberately not validated here beyond being non-empty.
    if raw.get("keep_alive"):
        settings["keep_alive"] = raw["keep_alive"]
    if raw.get("preload", "").lower() in {"true", "yes", "1"}:
        settings["preload"] = True
    if overrides:
        settings["keep_alive_overrides"] = overrides
    return settings


def resolve_keep_alive(name: str, settings: dict, cli_keep_alive: str | None = None) -> str | None:
    """Resolve a model's ``keep_alive``: CLI > per-model override > global > none.

    Returning None means "write nothing", which leaves the daemon on its own
    5-minute default. That is the pre-existing behavior and stays the default:
    pinning weights in VRAM is a decision about the whole machine, not something
    a config sync should assume.
    """
    if cli_keep_alive:
        return cli_keep_alive
    override = (settings.get("keep_alive_overrides") or {}).get(name)
    if override:
        return override
    return settings.get("keep_alive") or None


def resolve_sizing_settings(cli_vram_gb, cli_kv_cache_type, config_text: str):
    """Resolve (vram_bytes, kv_cache_type) with CLI > config > default precedence."""
    settings = parse_ollama_settings(config_text)
    vram_gb = cli_vram_gb if cli_vram_gb is not None else settings.get("vram_gb")
    kv_cache_type = cli_kv_cache_type or settings.get("kv_cache_type") or DEFAULT_KV_CACHE_TYPE
    vram_bytes = int(vram_gb * 1024**3) if vram_gb and vram_gb > 0 else None
    return vram_bytes, kv_cache_type


def effective_num_ctx_cap(explicit_cap: int | None, vram_limit: int | None) -> int:
    """Cap precedence: explicit ``--num-ctx-cap`` > VRAM sizing (cap off) > flat default.

    The flat DEFAULT_NUM_CTX_CAP exists to protect a GPU of *unknown* size from a
    128K-native model; once a per-model VRAM estimate exists it subsumes that
    job, so the flat cap is disabled rather than fighting the better number.
    """
    if explicit_cap is not None:
        return explicit_cap
    if vram_limit is not None:
        return 0
    return DEFAULT_NUM_CTX_CAP


def resolve_num_ctx(native: int | None, cap: int = DEFAULT_NUM_CTX_CAP, vram_limit: int | None = None) -> int | None:
    """Resolve the ``num_ctx`` to write from a model's native context length.

    Returns the native length clamped to ``vram_limit`` (when known) and to
    ``cap`` (``cap <= 0`` disables the clamp), or None when the native length is
    unknown — in which case no ``num_ctx`` is written and Ollama keeps its own
    default.
    """
    if not native or native <= 0:
        return None
    resolved = native
    if vram_limit and vram_limit > 0:
        resolved = min(resolved, vram_limit)
    if cap and cap > 0:
        resolved = min(resolved, cap)
    return resolved


def vram_contention_warning(loaded: list, vram_bytes: int | None, kv_cache_type: str = DEFAULT_KV_CACHE_TYPE) -> str | None:
    """Warn when the two largest local models cannot be resident at once.

    This is the Ultra-mode shape: a local lead plus a local subagent means two
    sets of weights in VRAM simultaneously. Ollama does not fail in that case —
    it evicts one model to load the other, so every delegation pays a full
    reload and the run silently crawls. The sizing math is the same one that
    already computes each model's context window; this just applies it to a pair.

    Returns None when there is nothing to say (no budget configured, fewer than
    two local models, or the pair fits). Never reassigns a model choice — the
    user's picks are theirs, and a warning with real numbers is the useful thing.
    """
    if not vram_bytes or vram_bytes <= 0 or len(loaded) < 2:
        return None

    def _cost(show: dict, weights: int) -> tuple[int, int]:
        """(weights, kv bytes for a modest shared window) for one resident model."""
        per_token = parse_kv_bytes_per_token(show, kv_cache_type)
        # Geometry may be unreadable; weights alone still prove non-coexistence.
        kv = int(per_token * MIN_VRAM_NUM_CTX) if per_token else 0
        return weights or 0, kv

    ranked = sorted(loaded, key=lambda item: item[2] or 0, reverse=True)[:2]
    (name_a, show_a, weights_a), (name_b, show_b, weights_b) = ranked
    wa, ka = _cost(show_a, weights_a)
    wb, kb = _cost(show_b, weights_b)
    needed = wa + ka + wb + kb + VRAM_OVERHEAD_BYTES
    if needed <= vram_bytes:
        return None

    gib = 1024**3
    return (
        f"VRAM contention: {name_a} ({wa / gib:.1f} GiB) + {name_b} ({wb / gib:.1f} GiB) "
        f"need ~{needed / gib:.1f} GiB resident together (weights + a {MIN_VRAM_NUM_CTX}-token KV cache each "
        f"+ {VRAM_OVERHEAD_BYTES / gib:.1f} GiB overhead), but the configured budget is {vram_bytes / gib:g} GiB. "
        f"Running both at once (a local lead with a local subagent) makes Ollama evict and reload between calls. "
        f"Pair a local lead with a smaller local subagent, raise ollama.vram_gb if it understates your GPU, or use q8_0 KV cache."
    )


def default_local_model(text: str) -> str | None:
    """Return the Ollama model id of ``models[0]``, or None if it is not local.

    ``models/factory.py`` resolves an unspecified model to ``config.models[0]``,
    so that entry — and only that entry — is the one worth preloading. Warming a
    different local model would heat the wrong weights and evict the right ones.
    """
    lines = text.splitlines()
    try:
        start, end = find_models_section(lines)
    except SystemExit:
        return None
    except Exception:
        return None

    entry_re = re.compile(r"^\s*-\s+(.*)$")
    first: dict[str, str] = {}
    seen_entry = False
    for line in lines[start + 1 : end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = entry_re.match(line)
        if match:
            if seen_entry:
                break  # only models[0] matters
            seen_entry = True
            stripped = match.group(1).strip()
        elif not seen_entry:
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            first.setdefault(key.strip(), value.strip().strip("\"'"))

    if "ollama" not in first.get("use", "").lower():
        return None
    return first.get("model") or first.get("name") or None


def _post_json(url: str, payload: dict, timeout: float) -> bool:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed loopback/daemon URL
            response.read()
        return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def preload_model(host: str, name: str, keep_alive: str | None = None, timeout: float = 300.0, post=_post_json) -> bool:
    """Load a model's weights into VRAM without generating a token.

    Ollama's ``/api/generate`` with an empty prompt is the documented load-only
    request. Best-effort: a daemon that is down, slow, or busy returns False and
    the caller carries on — a warm cache is an optimization, never a precondition.
    """
    payload: dict = {"model": name, "prompt": ""}
    if keep_alive:
        payload["keep_alive"] = keep_alive
    return post(f"{normalize_host(host)}/api/generate", payload, timeout)


def render_entry(name: str, caps: list, base_url: str = DEFAULT_HOST, num_ctx: int | None = None, keep_alive: str | None = None) -> str:
    """Render a single Ollama model entry as YAML at 2-space indent.

    When ``num_ctx`` is known, the entry pins the context window and keeps the
    ``num_predict`` output budget below it (reserving at least half the window
    for the prompt) so the two options stay consistent.
    """
    num_predict = DEFAULT_NUM_PREDICT
    if num_ctx is not None:
        num_predict = max(1, min(DEFAULT_NUM_PREDICT, num_ctx // 2))
    lines = [
        f"{INDENT}- name: {name}",
        f"{INDENT}  display_name: {name} (Ollama)",
        f"{INDENT}  use: langchain_ollama:ChatOllama",
        f"{INDENT}  model: {name}",
        f"{INDENT}  base_url: {base_url}",
    ]
    if num_ctx is not None:
        lines.append(f"{INDENT}  num_ctx: {num_ctx}")
    if keep_alive:
        # ChatOllama forwards keep_alive to the daemon, so the model stays
        # resident between turns instead of paying a cold start per subagent call.
        lines.append(f"{INDENT}  keep_alive: {keep_alive}")
    lines += [
        f"{INDENT}  num_predict: {num_predict}",
        f"{INDENT}  temperature: 0.7",
    ]
    if "thinking" in caps:
        # Native Ollama API toggles reasoning via reasoning:true (think:true downstream)
        lines.append(f"{INDENT}  reasoning: true")
        lines.append(f"{INDENT}  supports_thinking: true")
    if "vision" in caps:
        lines.append(f"{INDENT}  supports_vision: true")
    if "tools" not in caps:
        # Explicit false signals the UI to grey out the entry for subagent selection.
        lines.append(f"{INDENT}  supports_tools: false")
    return "\n".join(lines)


def check_duplicate_top_level_keys(text: str, path) -> None:
    """Abort when a top-level YAML key appears twice.

    YAML last-key-wins would make this script edit a `models:` section the
    application never sees (and would silently mask a corrupted config, e.g.
    two `sandbox:` blocks). Pure-text scan on purpose — this script runs under
    plain python3 with no PyYAML; the message format matches the shared loader
    in backend/packages/harness/deerflow/config/yaml_guard.py.
    """
    top_key = re.compile(r"^([A-Za-z_][\w-]*):")
    seen: dict[str, int] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = top_key.match(line)
        if not match:
            continue
        key = match.group(1)
        if key in seen:
            raise SystemExit(f"ERROR: duplicate top-level key '{key}' in {path}: first defined at line {seen[key]}, duplicated at line {lineno}\nRemove one of the duplicate sections from config.yaml, then retry.")
        seen[key] = lineno


def find_models_section(lines):
    """Return (start, end) indices of the models: block.

    `start` is the line index of `models:`; `end` is the first line after the
    block (i.e., the next top-level YAML key, or len(lines)).
    """
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == "models:":
            start = i
            break
    if start is None:
        raise SystemExit("ERROR: 'models:' section not found in config.yaml")

    top_key = re.compile(r"^[A-Za-z_][\w-]*:")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if not line:
            continue
        if line[0].isspace():
            continue
        if line.lstrip().startswith("#"):
            continue
        if top_key.match(line):
            end = i
            break
    return start, end


def sync(text: str, models: list, base_url: str = DEFAULT_HOST) -> str:
    """Return updated config text with the managed block regenerated."""
    lines = text.splitlines()
    start, end = find_models_section(lines)

    # Strip any existing managed block inside [start+1, end)
    section = lines[start + 1 : end]
    new_section = []
    in_managed = False
    for line in section:
        s = line.strip()
        if s == BEGIN_MARKER:
            in_managed = True
            continue
        if in_managed:
            if s == END_MARKER:
                in_managed = False
            continue
        new_section.append(line)

    # Trim trailing blank lines from the section
    while new_section and not new_section[-1].strip():
        new_section.pop()

    # Append the fresh managed block (only if there are models to write)
    if models:
        new_section.append("")
        new_section.append(f"{INDENT}{BEGIN_MARKER}")
        for entry in models:
            # Entries are (name, caps), (name, caps, num_ctx), or
            # (name, caps, num_ctx, keep_alive); the tail fields are optional so
            # pre-existing shorter-tuple callers keep working.
            name, caps = entry[0], entry[1]
            num_ctx = entry[2] if len(entry) > 2 else None
            keep_alive = entry[3] if len(entry) > 3 else None
            new_section.append(render_entry(name, caps, base_url, num_ctx=num_ctx, keep_alive=keep_alive))
        new_section.append(f"{INDENT}{END_MARKER}")

    new_section.append("")  # blank separator before next top-level key

    final = lines[: start + 1] + new_section + lines[end:]
    out = "\n".join(final)
    if text.endswith("\n") and not out.endswith("\n"):
        out += "\n"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    repo_root = Path(__file__).resolve().parent.parent
    ap.add_argument("--config", default=str(repo_root / "config.yaml"))
    ap.add_argument("--host", default=DEFAULT_HOST, help=f"Ollama endpoint to query (default: {DEFAULT_HOST}; OLLAMA_HOST env wins)")
    ap.add_argument("--base-url", default=None, help="base_url written into each entry (default: the query host). Wins over --container.")
    ap.add_argument("--container", action="store_true", help=f"Rewrite a loopback query host to {DOCKER_HOST_ALIAS} for the written base_url (Docker launch paths)")
    ap.add_argument("--num-ctx-cap", type=int, default=None, help=f"Hard cap for the written num_ctx (default: {DEFAULT_NUM_CTX_CAP}, or the VRAM-based estimate when a VRAM budget is configured; 0 = uncapped)")
    ap.add_argument("--vram-gb", type=float, default=None, help="GPU memory budget in GiB for per-model context sizing (default: `ollama.vram_gb` in config.yaml; unset = flat cap only)")
    ap.add_argument(
        "--kv-cache-type",
        choices=sorted(KV_CACHE_BYTES_PER_ELEMENT),
        default=None,
        help="KV-cache quantization assumed by the sizing (default: `ollama.kv_cache_type` in config.yaml, else f16). Must match the daemon's OLLAMA_KV_CACHE_TYPE to be accurate.",
    )
    ap.add_argument("--keep-alive", default=None, help="How long the daemon keeps each model resident (e.g. 30m, 1h, -1 for never unload). Default: `ollama.keep_alive` in config.yaml; unset leaves Ollama's own 5-minute default.")
    ap.add_argument(
        "--preload-only",
        action="store_true",
        help="Skip the config sync; just load the default local model (models[0]) into VRAM so the first turn is not a cold start. No-op unless `ollama.preload: true` or --preload is set.",
    )
    ap.add_argument("--preload", action="store_true", help="Preload the default local model after syncing (overrides `ollama.preload`)")
    ap.add_argument("--dry-run", action="store_true", help="Print result to stdout, do not write")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"ERROR: config not found at {config_path}")
    original = config_path.read_text()
    check_duplicate_top_level_keys(original, config_path)
    vram_bytes, kv_cache_type = resolve_sizing_settings(args.vram_gb, args.kv_cache_type, original)
    settings = parse_ollama_settings(original)

    host = normalize_host(os.environ.get("OLLAMA_HOST") or args.host)

    # ── Preload-only: warm the default local model, touch nothing else ───────
    # Split out so a launch script can background it: loading weights can take
    # tens of seconds, which must not sit in front of the stack starting.
    if args.preload_only:
        if not (args.preload or settings.get("preload")):
            return 0
        name = default_local_model(original)
        if not name:
            if args.verbose:
                print("[ollama-sync] default model is not an Ollama entry; nothing to preload", file=sys.stderr)
            return 0
        keep_alive = resolve_keep_alive(name, settings, args.keep_alive)
        if preload_model(host, name, keep_alive):
            print(f"[ollama-sync] preloaded {name}" + (f" (keep_alive={keep_alive})" if keep_alive else ""), file=sys.stderr)
        elif args.verbose:
            print(f"[ollama-sync] could not preload {name} (daemon unreachable or busy); continuing", file=sys.stderr)
        return 0

    base_url = resolve_base_url(host, args.base_url, args.container)
    if args.verbose:
        print(f"[ollama-sync] querying {host}; writing base_url {base_url}", file=sys.stderr)
        if vram_bytes:
            print(f"[ollama-sync] sizing num_ctx for {vram_bytes / 1024**3:g} GiB VRAM (kv_cache_type={kv_cache_type})", file=sys.stderr)

    installed = fetch_tags(host)
    if installed is None:
        if args.verbose:
            print(f"[ollama-sync] {host} unreachable; skipping (no changes)", file=sys.stderr)
        return 0

    # The daemon is up, so entries will be written — check they will actually
    # be reachable from the containers that read them (best-effort, warn only).
    if args.container:
        warning = container_ollama_warning(base_url)
        if warning:
            print(f"[ollama-sync] {warning}", file=sys.stderr)

    models = []
    resident = []
    for installed_model in installed:
        name = installed_model["name"]
        show = fetch_show(host, name)
        caps = parse_capabilities(show)
        vram_limit = vram_num_ctx_limit(show, installed_model.get("size"), vram_bytes, kv_cache_type) if vram_bytes else None
        num_ctx = resolve_num_ctx(parse_context_length(show), cap=effective_num_ctx_cap(args.num_ctx_cap, vram_limit), vram_limit=vram_limit)
        keep_alive = resolve_keep_alive(name, settings, args.keep_alive)
        models.append((name, caps, num_ctx, keep_alive))
        resident.append((name, show, installed_model.get("size")))
        if args.verbose:
            ctx_note = num_ctx if num_ctx is not None else "unknown (Ollama default)"
            vram_note = f"  vram_limit={vram_limit}" if vram_limit is not None else ""
            keep_note = f"  keep_alive={keep_alive}" if keep_alive else ""
            print(f"  - {name}  caps={caps}  num_ctx={ctx_note}{vram_note}{keep_note}", file=sys.stderr)

    # A local lead with a local subagent means two sets of weights resident at
    # once. Warn with the numbers rather than silently reassigning a model.
    contention = vram_contention_warning(resident, vram_bytes, kv_cache_type)
    if contention:
        print(f"[ollama-sync] {contention}", file=sys.stderr)

    # Tool-capable first, then alphabetical (matches dropdown order in UI)
    models.sort(key=lambda m: (0 if "tools" in m[1] else 1, m[0]))

    updated = sync(original, models, base_url=base_url)

    if args.dry_run:
        sys.stdout.write(updated)
        return 0

    if updated == original:
        if args.verbose:
            print("[ollama-sync] no changes", file=sys.stderr)
        return 0

    config_path.write_text(updated)
    print(f"[ollama-sync] updated {config_path} with {len(models)} Ollama model(s)", file=sys.stderr)

    if args.preload or settings.get("preload"):
        name = default_local_model(updated)
        if name and preload_model(host, name, resolve_keep_alive(name, settings, args.keep_alive)):
            print(f"[ollama-sync] preloaded {name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
