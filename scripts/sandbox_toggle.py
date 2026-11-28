#!/usr/bin/env python3
"""Enable or disable the containerized AIO sandbox in config.yaml.

Rewrites ONLY the top-level ``sandbox:`` section, by text surgery (find the
section start and the next top-level key), so the rest of config.yaml —
comments, other sections, ollama-sync markers — is left byte-for-byte intact.
The existing ``environment:`` block is preserved across both directions.

Usage:
    python3 scripts/sandbox_toggle.py enable                    # → AIO external mode (localhost:8091)
    python3 scripts/sandbox_toggle.py enable --mode container   # → AIO local container mode (per-thread containers)
    python3 scripts/sandbox_toggle.py enable --mode container --image cad  # → the same, on the CAD image
    python3 scripts/sandbox_toggle.py disable                   # → LocalSandboxProvider default

Modes for ``enable``:
- ``external`` (default): one externally-managed container (`make sandbox-up`);
  DeerFlow never creates or destroys it. `sandbox.mounts` is ignored, so files
  written in the sandbox are not host-backed (present_files can't surface them).
- ``container``: DeerFlow spawns one container per thread and mounts that
  thread's user-data directories, so /mnt/user-data is host-backed — uploads,
  outputs, and present_files all work. Best mode for clone-and-debug workflows.

Images for container mode: the stock pinned tag, or ``--image cad`` for the CAD
image that ``make sandbox-cad-image`` builds from it (docker/sandbox-cad). An
image means nothing to external mode, whose container `make sandbox-up` starts,
so ``--image`` is refused there. When the config is already in container mode,
only the ``image:`` line changes, so ``devices:``, ``expose_ports:`` and the
other keys an operator set survive the switch; without ``--image`` that line
goes back to the stock tag.

Guarantees:
- config.yaml is backed up to config.yaml.bak before any write.
- Idempotent: enabling the mode and image already set / disabling when
  already-local prints a notice and does not rewrite (no new backup).
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

# Working AIO sandbox image, kept in lockstep with the external-mode container in
# docker/docker-compose.sandbox.yml. Container mode spawns its own container from
# this image, so it must be pinned: the provider's fallback DEFAULT_IMAGE is a
# `:latest` mirror tag frozen on a pre-1.9.3 digest that lacks the /v1/bash/*
# routes, which would leave the agent's env-bearing bash broken out of the box.
AIO_SANDBOX_IMAGE = "ghcr.io/agent-infra/sandbox:1.11.0"

# Images ``--image`` can name. The CAD image is built locally FROM the tag above
# (docker/sandbox-cad, `make sandbox-cad-image`); there is no registry to pull
# it from, so the Gateway's first container fails until it is built.
CAD_SANDBOX_IMAGE = "deerflow-sandbox-cad:local"
NAMED_IMAGES = {"cad": CAD_SANDBOX_IMAGE}

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


def build_enabled_container_section(environment: list[str] | None, image: str = AIO_SANDBOX_IMAGE) -> list[str]:
    """Build the AIO local-container-mode sandbox section (per-thread containers)."""
    lines = [
        "sandbox:",
        f"  use: {AIO_PROVIDER}",
        "  # Local container mode: DeerFlow spawns one sandbox container per thread",
        "  # and mounts that thread's user-data directories, so /mnt/user-data is",
        "  # host-backed (uploads, outputs, and present_files all work). Requires a",
        "  # local Docker daemon; no `make sandbox-up` needed.",
        "  # Pinned image (matches docker/docker-compose.sandbox.yml), or the CAD image",
        f"  # ({CAD_SANDBOX_IMAGE}) that `make sandbox-cad-image` builds FROM it. Do NOT",
        "  # drop to :latest — that mirror tag lacks the /v1/bash/* routes the agent needs.",
        f"  image: {image}",
        "  # Wall-clock deadline for one bash command in the sandbox; raise it for",
        "  # long installs/builds. Each command carries its own request budget, so",
        "  # request_timeout only covers session creation and the file/list calls.",
        "  bash_command_timeout: 1800",
        "  request_timeout: 1800.0",
        "  # Keep debug sessions warm for an hour before idle reclaim.",
        "  idle_timeout: 3600",
        "  # Publish extra ports 1:1 to localhost so a program under debug is",
        "  # reachable from the host browser (one container at a time per port):",
        "  # expose_ports: [8000, 3000]",
        "  # Grant extra capabilities, e.g. so gdb/strace can attach:",
        "  # extra_capabilities: [SYS_PTRACE]",
        "  # Hardware-accelerated VMs: forward the host's /dev/kvm (the host must",
        "  # have it; read the `devices:` note in config.example.yaml first):",
        "  # devices: [/dev/kvm]",
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


def find_image_line(section_lines: list[str]) -> tuple[int | None, str | None, int]:
    """Locate the section's own ``image:`` key.

    Returns (index, value, indent): the index into ``section_lines`` and the
    value of the ``image:`` line at the same indent as ``use:`` (None, None when
    absent), and that indent, so a nested ``image:`` of a sub-mapping is never
    taken for the sandbox's own.
    """
    indent = 2
    for line in section_lines:
        m = re.match(r"^(\s*)use:", line)
        if m:
            indent = len(m.group(1))
            break
    for i, line in enumerate(section_lines):
        m = re.match(r"^(\s*)image:(.*)$", line)
        if m and len(m.group(1)) == indent:
            return i, m.group(2).split("#", 1)[0].strip().strip("'\"") or None, indent
    return None, None, indent


def switch_image(config_path: Path, lines: list[str], start: int, end: int, image: str) -> int:
    """Point an AIO container-mode section at ``image`` by changing one line."""
    section_lines = lines[start + 1 : end]
    index, current, indent = find_image_line(section_lines)
    if current == image:
        print(f"OK sandbox is already set to AIO container mode with image {image} — no change.")
        return 0
    new_line = f"{' ' * indent}image: {image}"
    if index is None:
        # No image: the provider would fall back to its broken :latest default,
        # so pin one right after `use:`.
        use_index = next((i for i, ln in enumerate(section_lines) if re.match(r"^\s*use:", ln)), -1)
        section_lines.insert(use_index + 1, new_line)
    else:
        section_lines[index] = new_line
    print(f"Switching the AIO container-mode image: {current or '(none)'} -> {image}")
    write_section(config_path, [lines[start], *section_lines], start, end, lines)
    print("OK sandbox image updated; the rest of the sandbox section is unchanged.")
    print_image_hint(image)
    return 0


def print_image_hint(image: str, *, containers_may_run: bool = True) -> None:
    """Say what the operator does next after the container image changed."""
    if image == CAD_SANDBOX_IMAGE:
        print(f"  {CAD_SANDBOX_IMAGE} is built locally, never pulled: run `make sandbox-cad-image` first.")
    if not containers_may_run:
        return
    # A restarted Gateway adopts a labelled sandbox container whatever its image
    # (LocalContainerBackend compares the image only for unlabelled ones).
    print("  Remove the running sandbox containers, then restart the Gateway: a restarted Gateway keeps")
    print("  using a running container whatever its image. `make stop` and `make docker-stop` remove")
    print("  them; otherwise run `bash scripts/cleanup-containers.sh`.")


def current_aio_mode(section_lines: list[str]) -> str:
    """Return "external" when the section pins a base_url, else "container"."""
    for line in section_lines:
        stripped = line.split("#", 1)[0].strip()
        if stripped.startswith("base_url:") and stripped.split(":", 1)[1].strip():
            return "external"
    return "container"


def toggle(action: str, config_path: Path, mode: str = "external", image: str | None = None) -> int:
    """Rewrite the sandbox section; ``image`` is a key of NAMED_IMAGES, container mode only."""
    if image is not None and (action != "enable" or mode != "container"):
        print("✗ --image applies only to `enable --mode container`: external mode connects to the one")
        print("  container `make sandbox-up` starts, which never uses the configured image.")
        return 2
    target_image = NAMED_IMAGES[image] if image is not None else AIO_SANDBOX_IMAGE
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
        if action == "disable":
            print("OK sandbox is already set to LocalSandboxProvider — no change.")
            return 0
        if current_aio_mode(section_lines) == mode:
            if mode == "container":
                return switch_image(config_path, lines, start, end, target_image)
            print(f"OK sandbox is already set to AIO {mode} mode — no change.")
            return 0

    if action == "enable" and mode == "container":
        new_section = build_enabled_container_section(environment, target_image)
        print("Enabling AIO sandbox in local container mode (one container per thread).")
        print("  Requires a running Docker daemon; containers start on first use.")
    elif action == "enable":
        new_section = build_enabled_section(environment)
        print("Enabling containerized AIO sandbox (base_url: http://localhost:8091).")
        print("  Start it with: make sandbox-up")
    else:
        new_section = build_disabled_section(environment)
        print("Disabling containerized sandbox — reverting to LocalSandboxProvider.")

    write_section(config_path, new_section, start, end, lines)
    print("OK sandbox section updated.")
    if action == "enable" and mode == "container":
        # Coming from the local or the external sandbox, no per-thread container runs yet.
        print_image_hint(target_image, containers_may_run=False)
    return 0


def main(argv: list[str]) -> int:
    usage = f"usage: sandbox_toggle.py {{enable [--mode {{external|container}}] [--image {{{'|'.join(NAMED_IMAGES)}}}]|disable}}"
    args = argv[1:]
    if not args or args[0] not in ("enable", "disable"):
        print(usage, file=sys.stderr)
        return 2
    action = args[0]
    options = {"--mode": ("external", "container"), "--image": tuple(NAMED_IMAGES)}
    chosen: dict[str, str] = {}
    rest = args[1:]
    if rest and action != "enable":
        print(usage, file=sys.stderr)
        return 2
    while rest:
        if len(rest) < 2 or rest[0] not in options or rest[0] in chosen or rest[1] not in options[rest[0]]:
            print(usage, file=sys.stderr)
            return 2
        chosen[rest[0]] = rest[1]
        rest = rest[2:]
    mode = chosen.get("--mode", "external")
    image = chosen.get("--image")
    if image is not None and mode != "container":
        print(f"✗ --image {image} needs --mode container (make sandbox-enable MODE=container IMAGE={image}):", file=sys.stderr)
        print("  external mode connects to the one container `make sandbox-up` starts, which never uses the configured image.", file=sys.stderr)
        return 2
    config_path = resolve_config_path()
    if config_path is None:
        print("✗ No config.yaml found.")
        print("  Run `make config` (or `make setup`) to create it first.")
        return 1
    return toggle(action, config_path, mode, image)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
