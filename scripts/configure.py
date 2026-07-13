#!/usr/bin/env python3
"""Cross-platform config bootstrap script for DeerFlow."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def copy_if_missing(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    if not src.exists():
        raise FileNotFoundError(f"Missing template file: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def _prompt_yes_no(question: str, *, default: bool = False) -> bool:
    """Ask a yes/no question on a TTY. Non-interactive → the caller's default.

    A non-interactive run cannot answer, so it takes the default the caller
    passed. Callers wanting the old always-safe behavior simply keep
    ``default=False`` (e.g. the web_fetch prompt); the sandbox prompt passes
    ``default`` = "a container runtime is available", so a scripted first
    install still lands on the container sandbox when Docker is present.
    """
    if not sys.stdin.isatty():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{question} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if not answer:
        return default
    return answer in {"y", "yes"}


def _container_runtime_available() -> bool:
    """Return True when Docker or Apple Container is on PATH."""
    return bool(shutil.which("docker") or shutil.which("container"))


def _offer_sandbox_choice(project_root: Path) -> None:
    """Offer to switch the fresh config to the containerized AIO sandbox.

    Writes the per-thread container mode (no base_url) — DeerFlow manages one
    container per thread with that thread's user-data mounted, so uploads,
    outputs, and present_files work without a separate `make sandbox-up`. This
    matches what the richer `make setup` wizard writes.

    Defaults to yes when a container runtime is installed: the container
    sandbox is the only mode where the bash tool (and therefore git/clone) is
    active out of the box — with the local sandbox, host bash stays disabled.
    Because the prompt's default is "a runtime is available", a non-interactive
    first install also lands on the container sandbox whenever Docker/Apple
    Container is present, and falls back to the local sandbox otherwise.
    """
    if not _prompt_yes_no("Enable the containerized AIO sandbox (requires Docker)?", default=_container_runtime_available()):
        print("  Keeping the local sandbox: the bash tool (git, program runs) stays disabled by default.")
        print("  Enable later with 'make sandbox-enable MODE=container'.")
        return
    script = project_root / "scripts" / "sandbox_toggle.py"
    result = subprocess.run([sys.executable, str(script), "enable", "--mode", "container"], cwd=str(project_root))
    if result.returncode == 0:
        print("  Containers start automatically on first use (a Docker daemon must be running).")
    else:
        print("  Could not update the sandbox section automatically; edit config.yaml by hand.")


def _offer_web_fetch_choice(project_root: Path) -> None:
    """Offer to switch web_fetch from the default local Camoufox browser to the Jina cloud API."""
    if not _prompt_yes_no("Use the Jina cloud reader API for web_fetch instead of the default local Camoufox browser?"):
        return
    config_path = project_root / "config.yaml"
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return
    # Flip only the web_fetch dispatcher's `backend: camoufox` to `backend: jina`.
    updated = text.replace("    backend: camoufox\n", "    backend: jina\n", 1)
    if updated != text:
        config_path.write_text(updated, encoding="utf-8")
        print("  web_fetch backend set to jina (cloud reader API, no browser download needed).")
    else:
        print("  Could not update the web_fetch backend automatically; edit config.yaml by hand.")


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent

    existing_config = [
        project_root / "config.yaml",
        project_root / "config.yml",
        project_root / "configure.yml",
    ]

    if any(path.exists() for path in existing_config):
        print("Error: configuration file already exists (config.yaml/config.yml/configure.yml). Aborting.")
        return 1

    try:
        copy_if_missing(project_root / "config.example.yaml", project_root / "config.yaml")
        copy_if_missing(project_root / ".env.example", project_root / ".env")
        copy_if_missing(
            project_root / "frontend" / ".env.example",
            project_root / "frontend" / ".env",
        )
    except (FileNotFoundError, OSError) as exc:
        print("Error while generating configuration files:")
        print(f"  {exc}")
        if isinstance(exc, PermissionError):
            print("Hint: Check file permissions and ensure the files are not read-only or locked by another process.")
        return 1

    print("✓ Configuration files generated")

    # Optional interactive choices (TTY only; non-interactive runs skip these).
    _offer_sandbox_choice(project_root)
    _offer_web_fetch_choice(project_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
