#!/usr/bin/env python3
"""Sync Ollama-installed models into config.yaml's models: section.

Idempotent and bounded: this script owns only the content between its
BEGIN/END markers. Hand-edited entries (cloud models, custom Ollama configs)
outside the markers are never touched.

If Ollama is not running, the script exits cleanly with no changes.

Usage:
    python3 scripts/sync-ollama-models.py [--config PATH] [--dry-run] [--verbose]
                                          [--base-url URL] [--container]

Environment:
    OLLAMA_HOST: override Ollama endpoint (default: http://localhost:11434)

The endpoint the script *queries* (``--host`` / ``OLLAMA_HOST``) and the
``base_url`` it *writes* into each model entry are decoupled: a containerized
runtime (Docker paths) queries the host's Ollama over loopback but must record a
``base_url`` the container can reach. ``--container`` rewrites a loopback query
host to ``host.docker.internal`` for the written entries; ``--base-url`` sets it
explicitly (wins over ``--container``).
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


def fetch_capabilities(host: str, name: str, timeout: float = 5.0):
    """Return list of capability strings from /api/show; [] on error."""
    try:
        req = urllib.request.Request(
            f"{host}/api/show",
            data=json.dumps({"name": name}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
        return []
    return data.get("capabilities") or []


def render_entry(name: str, caps: list, base_url: str = DEFAULT_HOST) -> str:
    """Render a single Ollama model entry as YAML at 2-space indent."""
    lines = [
        f"{INDENT}- name: {name}",
        f"{INDENT}  display_name: {name} (Ollama)",
        f"{INDENT}  use: langchain_ollama:ChatOllama",
        f"{INDENT}  model: {name}",
        f"{INDENT}  base_url: {base_url}",
        f"{INDENT}  num_predict: 8192",
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
        for name, caps in models:
            new_section.append(render_entry(name, caps, base_url))
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
        caps = fetch_capabilities(host, name)
        models.append((name, caps))
        if args.verbose:
            print(f"  - {name}  caps={caps}", file=sys.stderr)

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
