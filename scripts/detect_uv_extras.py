#!/usr/bin/env python3
"""Resolve uv extras for local `uv sync` based on environment + config.yaml.

Order of resolution:
1. `UV_EXTRAS` env var. Comma- or whitespace-separated names so multiple
   extras can be layered (e.g. ``UV_EXTRAS=postgres,ollama``). The same
   parsing semantics apply in the Docker dev container via
   ``docker/dev-entrypoint.sh`` and in the production Docker image build via
   ``backend/Dockerfile``.
2. Auto-detection from config.yaml (plus backend env overrides) — currently maps:
   - database.backend == postgres        -> postgres
   - checkpointer.type == postgres       -> postgres
   - stream_bridge.type == redis         -> redis
   - channels.discord.enabled == true    -> discord
   - tools[].name == browser_navigate    -> browser
   - sandbox.ownership.type == redis     -> redis
   - web_fetch resolving to camoufox     -> camoufox (explicit ``backend:`` /
     ``fallback:`` / ``use:`` selection, or a dispatcher entry that omits
     ``backend:`` — camoufox is the code-level default)
3. Runtime environment toggles that enable optional backends:
   - DEER_FLOW_STREAM_BRIDGE_REDIS_URL   -> redis
   - DEER_FLOW_SANDBOX_OWNERSHIP_REDIS_URL -> redis
   - DEER_FLOW_WEB_FETCH_BACKEND=camoufox -> camoufox (the env var overrides
     config at dispatch time, so the extra must install even over a jina config)

Each extra name is validated against ``^[A-Za-z][A-Za-z0-9_-]*$`` (the same
shape uv enforces for `[project.optional-dependencies]` keys). Anything else
is dropped with a stderr warning so a stray shell metacharacter in `.env`
cannot reach the `uv sync` invocation downstream.

Output: space-separated `--extra <name>` flags ready for splat into
`uv sync`, e.g. `--extra postgres`. Empty output means "no extras".

Intentionally implemented with the standard library only: this script must run
*before* `uv sync` has populated the venv, so it cannot depend on PyYAML.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Mirrors uv's accepted shape for extra names — keeps the eventual
# `uv sync --extra <name>` invocation free of shell metacharacters even when
# `UV_EXTRAS` comes from `.env` or another semi-trusted source.
_EXTRA_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _validate_extras(names: list[str]) -> list[str]:
    valid: list[str] = []
    for name in names:
        if _EXTRA_NAME_RE.match(name):
            valid.append(name)
        else:
            print(
                f"detect_uv_extras: ignoring invalid UV_EXTRAS entry {name!r} (must match [A-Za-z][A-Za-z0-9_-]*)",
                file=sys.stderr,
            )
    return valid


def parse_env_extras(value: str) -> list[str]:
    """Split UV_EXTRAS into a list, accepting comma or whitespace separators."""
    parts = re.split(r"[\s,]+", value.strip())
    return _validate_extras([p for p in parts if p])


def find_config_file() -> Path | None:
    """Locate config.yaml using the same precedence as serve.sh."""
    explicit = os.environ.get("DEER_FLOW_CONFIG_PATH")
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return candidate
    for path in (Path("config.yaml"), Path("backend/config.yaml")):
        if path.is_file():
            return path
    return None


_SECTION_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*$")
_INDENTED_SECTION_RE = re.compile(r"^\s+([A-Za-z_][\w-]*)\s*:\s*$")
_KEY_RE = re.compile(r"^\s+([A-Za-z_][\w-]*)\s*:\s*(\S.*?)\s*$")
_LIST_ITEM_NAME_RE = re.compile(r"^\s*-\s+name\s*:\s*(\S.*?)\s*$")


def _strip_comment(line: str) -> str:
    """Drop trailing `#` comments while preserving `#` inside quoted strings."""
    in_quote: str | None = None
    out: list[str] = []
    for ch in line:
        if in_quote is not None:
            out.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def section_value(lines: list[str], section: str, key: str) -> str | None:
    """Return the value of `section.key` from a flat-ish YAML, or None.

    Only handles the shallow shape DeerFlow uses for these settings:
        database:
          backend: postgres
    Nested mappings deeper than the immediate child level are ignored on
    purpose — that keeps this parser predictable without a full YAML stack.
    """
    inside = False
    child_indent: int | None = None
    for raw in lines:
        line = _strip_comment(raw)
        if not line.strip():
            continue
        sect_match = _SECTION_RE.match(line)
        if sect_match:
            inside = sect_match.group(1) == section
            child_indent = None
            continue
        if not inside:
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent == 0:
            inside = False
            continue
        if child_indent is None:
            child_indent = indent
        if indent < child_indent:
            inside = False
            continue
        if indent != child_indent:
            continue
        key_match = _KEY_RE.match(line)
        if key_match and key_match.group(1) == key:
            return _unquote(key_match.group(2).strip())
    return None


def nested_section_value(lines: list[str], section_path: str, key: str) -> str | None:
    """Return the value of a nested YAML key like ``channels.discord.enabled``.

    Handles two levels of nesting:
        channels:
          discord:
            enabled: true
    """
    parts = section_path.split(".")
    if len(parts) != 2:
        return None
    parent_section, child_section = parts

    inside_parent = False
    inside_child = False
    parent_indent: int | None = None
    child_indent: int | None = None

    for raw in lines:
        line = _strip_comment(raw)
        if not line.strip():
            continue

        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # Top-level section match
        sect_match = _SECTION_RE.match(line)
        if sect_match:
            if indent == 0:
                inside_parent = sect_match.group(1) == parent_section
            inside_child = False
            parent_indent = None
            child_indent = None
            continue

        if not inside_parent:
            continue

        # Track parent indent from first child
        if parent_indent is None and indent > 0:
            parent_indent = indent

        # If indent goes back to 0, we left the parent section
        if indent == 0:
            inside_parent = False
            inside_child = False
            continue

        # Check if we're at the parent's child level (subsection)
        if parent_indent is not None and indent == parent_indent:
            # This could be a subsection or a direct key of parent
            sub_match = _INDENTED_SECTION_RE.match(line)
            if sub_match and sub_match.group(1) == child_section:
                inside_child = True
                child_indent = None
                continue
            else:
                inside_child = False
                continue

        if not inside_child:
            continue

        # We're inside the subsection — track child indent
        if child_indent is None and indent > (parent_indent or 0):
            child_indent = indent

        if child_indent is not None and indent != child_indent:
            continue

        key_match = _KEY_RE.match(line)
        if key_match and key_match.group(1) == key:
            return _unquote(key_match.group(2).strip())

    return None


def tools_include_name(lines: list[str], tool_name: str) -> bool:
    """Return True when the top-level tools list has an active item name."""
    inside = False
    for raw in lines:
        line = _strip_comment(raw)
        if not line.strip():
            continue
        sect_match = _SECTION_RE.match(line)
        if sect_match:
            inside = sect_match.group(1) == "tools"
            continue
        if not inside:
            continue
        name_match = _LIST_ITEM_NAME_RE.match(line)
        if name_match:
            if _unquote(name_match.group(1).strip()) == tool_name:
                return True
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent == 0:
            inside = False
            continue
    return False


def detect_from_config(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    extras: set[str] = set()
    if (section_value(lines, "database", "backend") or "").lower() == "postgres":
        extras.add("postgres")
    if (section_value(lines, "checkpointer", "type") or "").lower() == "postgres":
        extras.add("postgres")
    if (section_value(lines, "stream_bridge", "type") or "").lower() == "redis":
        extras.add("redis")
    if (nested_section_value(lines, "sandbox.ownership", "type") or "").lower() == "redis":
        extras.add("redis")
    if (nested_section_value(lines, "channels.discord", "enabled") or "").lower() == "true":
        extras.add("discord")
    if tools_include_name(lines, "browser_navigate"):
        extras.add("browser")
    if _uses_camoufox_web_fetch(text):
        extras.add("camoufox")
    return sorted(extras)


_DISPATCHER_USE = "web_fetch.tools:web_fetch_tool"


def _uses_camoufox_web_fetch(text: str) -> bool:
    """True when config.yaml resolves web_fetch to the Camoufox backend.

    Matched on any of: the dispatcher entry with ``backend: camoufox``, a
    ``fallback: camoufox`` chain, a ``use:`` pointing into the camoufox
    module, or a dispatcher entry that omits ``backend:`` entirely — camoufox
    is the dispatcher's code-level default. Line-oriented on purpose — this
    parser runs before uv sync, so it cannot depend on PyYAML; the tools:
    section is a list, not the flat shape section_value handles.
    """
    for raw in text.splitlines():
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("use:") and "camoufox_fetch" in line:
            return True
        if line.startswith("backend:") and _unquote(line.split(":", 1)[1].strip()) == "camoufox":
            return True
        if line.startswith("fallback:") and _unquote(line.split(":", 1)[1].strip()) == "camoufox":
            return True
    return _dispatcher_entry_omits_backend(text)


def _dispatcher_entry_omits_backend(text: str) -> bool:
    """True when a tools list entry uses the web_fetch dispatcher without a ``backend:`` key.

    Such an entry gets the dispatcher's code-level default (camoufox), so the
    extra must install even though "camoufox" never appears in the file. Scans
    list entries by indentation: an entry starts at a ``- `` line and ends at
    the next ``- `` line or a dedent to (or past) the dash's indent, so keys
    from later sections (e.g. ``database.backend``) are never attributed to it.
    """
    in_entry = False
    entry_indent = 0
    has_dispatcher_use = False
    has_backend = False

    for raw in text.splitlines():
        line = _strip_comment(raw)
        stripped = line.lstrip()
        if not stripped:
            continue
        indent = len(line) - len(stripped)
        if stripped.startswith("- "):
            if in_entry and has_dispatcher_use and not has_backend:
                return True
            in_entry = True
            entry_indent = indent
            has_dispatcher_use = False
            has_backend = False
            stripped = stripped[2:].lstrip()
        elif in_entry and indent <= entry_indent:
            if has_dispatcher_use and not has_backend:
                return True
            in_entry = False
        if not in_entry:
            continue
        if stripped.startswith("use:") and _DISPATCHER_USE in stripped:
            has_dispatcher_use = True
        elif stripped.startswith("backend:"):
            has_backend = True
    return in_entry and has_dispatcher_use and not has_backend


def detect_from_runtime_env() -> list[str]:
    extras: set[str] = set()
    if os.environ.get("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", "").strip():
        extras.add("redis")
    if os.environ.get("DEER_FLOW_SANDBOX_OWNERSHIP_REDIS_URL", "").strip():
        extras.add("redis")
    if os.environ.get("DEER_FLOW_WEB_FETCH_BACKEND", "").strip().lower() == "camoufox":
        extras.add("camoufox")
    return sorted(extras)


def merge_extras(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for extra in group:
            if extra in seen:
                continue
            seen.add(extra)
            merged.append(extra)
    return merged


def resolve_extras() -> list[str]:
    runtime_env_extras = detect_from_runtime_env()
    env = os.environ.get("UV_EXTRAS", "")
    if env.strip():
        return merge_extras(parse_env_extras(env), runtime_env_extras)
    config = find_config_file()
    if config is None:
        return runtime_env_extras
    return merge_extras(detect_from_config(config), runtime_env_extras)


def format_flags(extras: list[str]) -> str:
    return " ".join(f"--extra {e}" for e in extras)


def main() -> int:
    extras = resolve_extras()
    if extras:
        sys.stdout.write(format_flags(extras))
    return 0


if __name__ == "__main__":
    sys.exit(main())
