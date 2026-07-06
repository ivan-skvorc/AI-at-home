#!/usr/bin/env python3
"""Enable or disable the containerized AIO sandbox in config.yaml.

Rewrites ONLY the top-level ``sandbox:`` section, by text surgery (find the
section start and the next top-level key), so the rest of config.yaml —
comments, other sections, ollama-sync markers — is left byte-for-byte intact.
The existing ``environment:`` block is preserved across both directions.

Usage:
    python3 scripts/sandbox_toggle.py enable    # → AIO external mode (localhost:8091)
    python3 scripts/sandbox_toggle.py disable   # → LocalSandboxProvider default

Guarantees:
- config.yaml is backed up to config.yaml.bak before any write.
- Idempotent: enabling when already-AIO / disabling when already-local prints a
  notice and does not rewrite (no new backup).
- Hard-aborts (exit 1) if config.yaml has duplicate top-level ``sandbox:`` keys,
  naming the key and both line numbers.
- Aborts (exit 1) with a pointer to ``make config`` if config.yaml is missing.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

AIO_PROVIDER = "deerflow.community.aio_sandbox:AioSandboxProvider"
LOCAL_PROVIDER = "deerflow.sandbox.local:LocalSandboxProvider"

DEFAULT_ENVIRONMENT = ["  environment:", "    GITHUB_TOKEN: $GITHUB_TOKEN"]

_TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*):")


def _load_yaml_guard():
    """Load the shared duplicate-key detector (prefer installed package)."""
    try:
        from deerflow.config.yaml_guard import DuplicateKeyError, safe_load_guarded

        return safe_load_guarded, DuplicateKeyError
    except ImportError:
        guard_path = REPO_ROOT / "backend" / "packages" / "harness" / "deerflow" / "config" / "yaml_guard.py"
        spec = importlib.util.spec_from_file_location("_deerflow_yaml_guard", guard_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.safe_load_guarded, module.DuplicateKeyError


def resolve_config_path() -> Path | None:
    """Resolve config.yaml: $DEER_FLOW_CONFIG_PATH > backend/ > repo root."""
    import os

    env_path = os.environ.get("DEER_FLOW_CONFIG_PATH")
    if env_path and Path(env_path).is_file():
        return Path(env_path)
    for candidate in (REPO_ROOT / "backend" / "config.yaml", REPO_ROOT / "config.yaml"):
        if candidate.is_file():
            return candidate
    return None


def find_section_bounds(lines: list[str], key: str) -> tuple[int, int] | None:
    """Return (start, end) line indices for a top-level ``key:`` block.

    ``start`` is the index of the ``key:`` line; ``end`` is the index of the
    next top-level key (or len(lines)). Returns None if not found.
    """
    start = None
    for i, line in enumerate(lines):
        m = _TOP_KEY.match(line)
        if m and m.group(1) == key:
            start = i
            break
    if start is None:
        return None

    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if not line or line[0].isspace() or line.lstrip().startswith("#"):
            continue
        if _TOP_KEY.match(line):
            end = i
            break
    return start, end


def extract_environment_block(section_lines: list[str]) -> list[str] | None:
    """Extract the ``environment:`` sub-block from a sandbox section body.

    Returns the block lines (the ``environment:`` key line plus its more-indented
    children, comments and blanks within the block included), or None if there
    is no environment mapping with entries.
    """
    env_start = None
    env_indent = 0
    for i, line in enumerate(section_lines):
        stripped = line.lstrip()
        if stripped.startswith("#") or not stripped:
            continue
        if re.match(r"^environment:\s*$", stripped) or re.match(r"^environment:\s*\S", stripped):
            env_start = i
            env_indent = len(line) - len(stripped)
            break
    if env_start is None:
        return None

    block = [section_lines[env_start]]
    for line in section_lines[env_start + 1 :]:
        if not line.strip():
            block.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent > env_indent:
            block.append(line)
        else:
            break

    # Trim trailing blank lines inside the captured block.
    while len(block) > 1 and not block[-1].strip():
        block.pop()

    # Only meaningful if it actually has at least one child entry.
    has_entry = any(len(ln) - len(ln.lstrip()) > env_indent and ln.strip() and not ln.lstrip().startswith("#") for ln in block[1:])
    return block if has_entry else None


def current_provider(section_lines: list[str]) -> str | None:
    """Return the value of ``use:`` inside the sandbox section, if present."""
    for line in section_lines:
        m = re.match(r"^\s*use:\s*(\S+)", line)
        if m:
            return m.group(1)
    return None


def build_enabled_section(environment: list[str] | None) -> list[str]:
    """Build the AIO external-mode sandbox section."""
    lines = [
        "sandbox:",
        f"  use: {AIO_PROVIDER}",
        "  # Containerized AIO sandbox managed via `make sandbox-up`",
        "  # (docker/docker-compose.sandbox.yml). DeerFlow connects to it but",
        "  # never creates or destroys it.",
        "  base_url: http://localhost:8091",
        "  request_timeout: 120.0",
    ]
    lines.extend(environment if environment is not None else DEFAULT_ENVIRONMENT)
    return lines


def build_disabled_section(environment: list[str] | None) -> list[str]:
    """Build the LocalSandboxProvider default sandbox section."""
    lines = [
        "sandbox:",
        f"  use: {LOCAL_PROVIDER}",
        "  # Host bash execution is disabled by default because LocalSandboxProvider is",
        "  # not a secure isolation boundary for shell access. Enable only for fully",
        "  # trusted, single-user local workflows.",
        "  allow_host_bash: false",
    ]
    if environment is not None:
        lines.extend(environment)
    return lines


def write_section(config_path: Path, new_section: list[str], start: int, end: int, lines: list[str]) -> None:
    backup = config_path.with_suffix(".yaml.bak")
    shutil.copy2(config_path, backup)
    print(f"Backed up to {backup.name}")
    new_lines = lines[:start] + new_section + lines[end:]
    text = "\n".join(new_lines)
    if config_path.read_text(encoding="utf-8").endswith("\n") and not text.endswith("\n"):
        text += "\n"
    config_path.write_text(text, encoding="utf-8")


def toggle(action: str, config_path: Path) -> int:
    safe_load_guarded, duplicate_key_error = _load_yaml_guard()
    raw = config_path.read_text(encoding="utf-8")
    try:
        safe_load_guarded(raw, source=str(config_path))
    except duplicate_key_error as exc:
        print(f"✗ {exc}")
        print("  Remove one of the duplicate sections from config.yaml, then retry.")
        return 1

    lines = raw.splitlines()
    bounds = find_section_bounds(lines, "sandbox")
    if bounds is None:
        print("✗ No top-level `sandbox:` section found in config.yaml.")
        print("  Run `make config` to regenerate it from config.example.yaml.")
        return 1
    start, end = bounds
    section_lines = lines[start + 1 : end]
    provider = current_provider(section_lines)
    environment = extract_environment_block(section_lines)

    target = AIO_PROVIDER if action == "enable" else LOCAL_PROVIDER
    if provider == target:
        state = "AIO container sandbox" if action == "enable" else "LocalSandboxProvider"
        print(f"OK sandbox is already set to {state} — no change.")
        return 0

    if action == "enable":
        new_section = build_enabled_section(environment)
        print("Enabling containerized AIO sandbox (base_url: http://localhost:8091).")
        print("  Start it with: make sandbox-up")
    else:
        new_section = build_disabled_section(environment)
        print("Disabling containerized sandbox — reverting to LocalSandboxProvider.")

    write_section(config_path, new_section, start, end, lines)
    print("OK sandbox section updated.")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("enable", "disable"):
        print("usage: sandbox_toggle.py {enable|disable}", file=sys.stderr)
        return 2
    config_path = resolve_config_path()
    if config_path is None:
        print("✗ No config.yaml found.")
        print("  Run `make config` (or `make setup`) to create it first.")
        return 1
    return toggle(argv[1], config_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
