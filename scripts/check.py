#!/usr/bin/env python3
"""Cross-platform dependency checker for DeerFlow."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PNPM_SCRIPT_PATH = Path(__file__).resolve().with_name("pnpm.py")
FRONTEND_DIR = PNPM_SCRIPT_PATH.parent.parent / "frontend"
COREPACK_NOTICE = "Using pnpm via Corepack."


def configure_stdio() -> None:
    """Prefer UTF-8 output so Unicode status markers render on Windows."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                continue


def run_command(command: list[str]) -> str | None:
    """Run a command and return trimmed stdout, or None on failure."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, shell=False)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or result.stderr.strip()


def run_pnpm_version() -> tuple[str | None, bool, str | None]:
    """Return the pnpm version, resolution source, and failure message."""
    try:
        result = subprocess.run(
            [sys.executable, str(PNPM_SCRIPT_PATH), "-v"],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            cwd=FRONTEND_DIR,
        )
    except OSError as exc:
        return None, False, f"Unable to launch the pnpm runner: {exc}"

    stdout = result.stdout.strip()
    stderr_lines = result.stderr.splitlines()
    via_corepack = COREPACK_NOTICE in stderr_lines
    stderr = "\n".join(line for line in stderr_lines if line != COREPACK_NOTICE).strip()
    if result.returncode == 0 and (stdout or stderr):
        return stdout or stderr, via_corepack, None

    diagnostics = "\n".join(part for part in (stderr, stdout) if part)
    if diagnostics:
        return None, via_corepack, diagnostics
    return (
        None,
        via_corepack,
        f"The pnpm runner exited with status {result.returncode} without output.",
    )


def parse_node_major(version_text: str) -> int | None:
    version = version_text.strip()
    if version.startswith("v"):
        version = version[1:]
    major_str = version.split(".", 1)[0]
    if not major_str.isdigit():
        return None
    return int(major_str)


def in_docker_group() -> bool | None:
    """Whether the current user can use Docker without sudo.

    Returns True for root or a member of the `docker` group, False when not a
    member, or None when membership can't be determined (e.g. non-POSIX).
    """
    try:
        import os

        if hasattr(os, "geteuid") and os.geteuid() == 0:
            return True
        import grp

        try:
            docker_gid = grp.getgrnam("docker").gr_gid
        except KeyError:
            return False
        if docker_gid in os.getgroups():
            return True
        return False
    except Exception:
        return None


def probe_port_8091() -> str:
    """Classify localhost:8091: 'sandbox', 'occupied', or 'free'."""
    import socket
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen("http://localhost:8091/v1/sandbox", timeout=2) as resp:
            if resp.status == 200:
                return "sandbox"
    except urllib.error.HTTPError:
        return "occupied"  # something answers HTTP but isn't the sandbox API
    except (urllib.error.URLError, TimeoutError, OSError):
        pass

    # No HTTP response — is anything listening on the port at all?
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        connected = sock.connect_ex(("127.0.0.1", 8091)) == 0
    finally:
        sock.close()
    return "occupied" if connected else "free"


def print_docker_remediation() -> None:
    """Print fish-compatible Docker setup commands (Arch + Debian). Never runs them."""
    print("    Install & start Docker + compose (run these yourself; commands are fish-compatible):")
    print("      # Arch:")
    print("      sudo pacman -S docker docker-compose")
    print("      # Debian/Ubuntu:")
    print("      sudo apt install docker.io docker-compose-v2")
    print("      # Then enable the daemon and allow your user to use it:")
    print("      sudo systemctl enable --now docker.service")
    print("      sudo usermod -aG docker $USER")
    print("      # Log out and back in for the docker group to take effect.")


def check_docker_optional() -> None:
    """Advisory Docker diagnostics for the containerized AIO sandbox.

    Never fails `make check` — Docker is optional (default LocalSandboxProvider
    needs none of it). Reports daemon reachability, docker-group membership,
    compose availability, and whether port 8091 is free / already serving the
    sandbox / occupied by something else.
    """
    print()
    print("Checking Docker (optional — only for the containerized AIO sandbox)...")
    docker_path = shutil.which("docker")
    if not docker_path:
        print("  INFO Docker not found (optional)")
        print("    Required only for the containerized AIO sandbox (isolated agent execution,")
        print("    private GitHub repo cloning) and the Docker deploy modes (make up / make docker-start).")
        print("    The default LocalSandboxProvider works without it.")
        print_docker_remediation()
        return

    docker_version = run_command(["docker", "--version"]) or "Docker (version unknown)"
    daemon_ok = run_command(["docker", "info", "--format", "{{.ServerVersion}}"]) is not None
    if daemon_ok:
        print(f"  OK {docker_version} — daemon reachable")
    else:
        print(f"  INFO {docker_version} — installed, but the daemon is not reachable")
        print("    Start it before using `make sandbox-up` / the AIO sandbox:")
        print("      sudo systemctl enable --now docker.service")

    group_state = in_docker_group()
    if group_state is True:
        print("  OK current user can use Docker without sudo")
    elif group_state is False:
        print("  INFO current user is not in the `docker` group (docker commands will need sudo)")
        print("      sudo usermod -aG docker $USER")
        print("      # Log out and back in for it to take effect.")

    # docker compose (v2 plugin) or legacy docker-compose
    compose_ok = run_command(["docker", "compose", "version"]) is not None or shutil.which("docker-compose") is not None
    if compose_ok:
        print("  OK docker compose available")
    else:
        print("  INFO docker compose not available (needed for `make sandbox-up`)")
        print("      # Arch: sudo pacman -S docker-compose")
        print("      # Debian/Ubuntu: sudo apt install docker-compose-v2")

    port_state = probe_port_8091()
    if port_state == "free":
        print("  OK port 8091 is free (`make sandbox-up` will use it)")
    elif port_state == "sandbox":
        print("  OK an AIO sandbox is already serving on port 8091")
    else:
        print("  WARN port 8091 is occupied by something other than the AIO sandbox")
        print("    Stop that process or change sandbox.base_url before `make sandbox-up`.")


def main() -> int:
    configure_stdio()
    print("==========================================")
    print("  Checking Required Dependencies")
    print("==========================================")
    print()

    failed = False

    print("Checking Node.js...")
    node_path = shutil.which("node")
    if node_path:
        node_version = run_command(["node", "-v"])
        if node_version:
            major = parse_node_major(node_version)
            if major is not None and major >= 22:
                print(f"  OK Node.js {node_version.lstrip('v')} (>= 22 required)")
            else:
                print(f"  FAIL Node.js {node_version.lstrip('v')} found, but version 22+ is required")
                print("    Install from: https://nodejs.org/")
                failed = True
        else:
            print("  INFO Unable to determine Node.js version")
            print("    Install from: https://nodejs.org/")
            failed = True
    else:
        print("  FAIL Node.js not found (version 22+ required)")
        print("    Install from: https://nodejs.org/")
        failed = True

    print()
    print("Checking pnpm...")
    pnpm_version, pnpm_via_corepack, pnpm_error = run_pnpm_version()
    if pnpm_version:
        resolution_hint = " (via Corepack)" if pnpm_via_corepack else ""
        print(f"  OK pnpm {pnpm_version}{resolution_hint}")
    else:
        print("  FAIL pnpm is unavailable or failed to run")
        if pnpm_error:
            for line in pnpm_error.splitlines():
                print(f"    {line}")
        failed = True

    print()
    print("Checking uv...")
    if shutil.which("uv"):
        uv_version_text = run_command(["uv", "--version"])
        if uv_version_text:
            uv_version_parts = uv_version_text.split()
            uv_version = uv_version_parts[1] if len(uv_version_parts) > 1 else uv_version_text
            print(f"  OK uv {uv_version}")
        else:
            print("  INFO Unable to determine uv version")
            failed = True
    else:
        print("  FAIL uv not found")
        print("    Visit the official installation guide for your platform:")
        print("    https://docs.astral.sh/uv/getting-started/installation/")
        failed = True

    print()
    print("Checking nginx...")
    if shutil.which("nginx"):
        nginx_version_text = run_command(["nginx", "-v"])
        if nginx_version_text and "/" in nginx_version_text:
            nginx_version = nginx_version_text.split("/", 1)[1]
            print(f"  OK nginx {nginx_version}")
        else:
            print("  INFO nginx (version unknown)")
    else:
        print("  FAIL nginx not found")
        print("    macOS:   brew install nginx")
        print("    Ubuntu:  sudo apt install nginx")
        print("    Windows: use WSL for local mode or use Docker mode")
        print("    Or visit: https://nginx.org/en/download.html")
        failed = True

    check_docker_optional()

    print()
    if not failed:
        print("==========================================")
        print("  OK All dependencies are installed!")
        print("==========================================")
        print()
        print("You can now run:")
        print("  make install  - Install project dependencies")
        print("  make setup    - Create a minimal working config (recommended)")
        print("  make config   - Copy the full config template (manual setup)")
        print("  make doctor   - Verify config and dependency health")
        print("  make dev      - Start development server")
        print("  make start    - Start production server")
        return 0

    print("==========================================")
    print("  FAIL Some dependencies are missing")
    print("==========================================")
    print()
    print("Please install the missing tools and run 'make check' again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
