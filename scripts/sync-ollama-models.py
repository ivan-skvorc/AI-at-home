#!/usr/bin/env python3
"""Sync Ollama-installed models into config.yaml's models: section.

Idempotent and bounded: this script owns only the content between its
BEGIN/END markers. Hand-edited entries (cloud models, custom Ollama configs)
outside the markers are never touched.

If Ollama is not running, the script exits cleanly with no changes.

Usage:
    python3 scripts/sync-ollama-models.py [--config PATH] [--dry-run] [--verbose]
                                          [--base-url URL] [--container]
                                          [--num-ctx-cap N]

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
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
    """Return list of model names from /api/tags, or None if Ollama is unreachable."""
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
        return None
    return [m.get("name") for m in data.get("models", []) if m.get("name")]


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


def resolve_num_ctx(native: int | None, cap: int = DEFAULT_NUM_CTX_CAP) -> int | None:
    """Resolve the ``num_ctx`` to write from a model's native context length.

    Returns the native length clamped to ``cap`` (``cap <= 0`` disables the
    clamp), or None when the native length is unknown — in which case no
    ``num_ctx`` is written and Ollama keeps its own default.
    """
    if not native or native <= 0:
        return None
    if cap and cap > 0:
        return min(native, cap)
    return native


def render_entry(name: str, caps: list, base_url: str = DEFAULT_HOST, num_ctx: int | None = None) -> str:
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
            # Entries are (name, caps) or (name, caps, num_ctx); num_ctx is
            # optional so pre-existing 2-tuple callers keep working.
            name, caps = entry[0], entry[1]
            num_ctx = entry[2] if len(entry) > 2 else None
            new_section.append(render_entry(name, caps, base_url, num_ctx=num_ctx))
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
    ap.add_argument("--num-ctx-cap", type=int, default=DEFAULT_NUM_CTX_CAP, help=f"Clamp the written num_ctx to this many tokens (default: {DEFAULT_NUM_CTX_CAP}; 0 = use each model's full native context length)")
    ap.add_argument("--dry-run", action="store_true", help="Print result to stdout, do not write")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    host = normalize_host(os.environ.get("OLLAMA_HOST") or args.host)
    base_url = resolve_base_url(host, args.base_url, args.container)
    if args.verbose:
        print(f"[ollama-sync] querying {host}; writing base_url {base_url}", file=sys.stderr)

    names = fetch_tags(host)
    if names is None:
        if args.verbose:
            print(f"[ollama-sync] {host} unreachable; skipping (no changes)", file=sys.stderr)
        return 0

    models = []
    for name in names:
        show = fetch_show(host, name)
        caps = parse_capabilities(show)
        num_ctx = resolve_num_ctx(parse_context_length(show), cap=args.num_ctx_cap)
        models.append((name, caps, num_ctx))
        if args.verbose:
            ctx_note = num_ctx if num_ctx is not None else "unknown (Ollama default)"
            print(f"  - {name}  caps={caps}  num_ctx={ctx_note}", file=sys.stderr)

    # Tool-capable first, then alphabetical (matches dropdown order in UI)
    models.sort(key=lambda m: (0 if "tools" in m[1] else 1, m[0]))

    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"ERROR: config not found at {config_path}")
    original = config_path.read_text()
    check_duplicate_top_level_keys(original, config_path)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
