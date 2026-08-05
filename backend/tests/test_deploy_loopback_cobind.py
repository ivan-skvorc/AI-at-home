"""Regression coverage for the loopback co-bind on the Docker prod path.

``BIND_HOST`` publishes exactly ONE interface (it is a bind address, not an
allowlist). Setting it to a Tailscale IP (e.g. ``100.x.y.z``) to reach the app
from a phone binds ONLY that interface, so the host's own
``http://localhost:2026`` is refused — the "works over Tailscale on my phone,
connection refused on localhost on the PC" footgun.

``scripts/deploy.sh::should_cobind_loopback`` decides when to append
``docker/docker-compose.loopback.yaml`` (which also publishes the entry port on
``127.0.0.1``) so localhost keeps working on the host without widening the
external surface. These tests pin both the decision (only a single, non-loopback,
non-wildcard interface co-binds) and the overlay's shape, so an upstream merge or
a refactor cannot quietly reintroduce the localhost-refused regression — or,
conversely, add a duplicate ``127.0.0.1`` mapping on top of a wildcard bind and
collide on the port.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "scripts" / "deploy.sh"
OVERLAY_PATH = REPO_ROOT / "docker" / "docker-compose.loopback.yaml"


def _extract_shell_function(name: str) -> str:
    text = DEPLOY_SH.read_text(encoding="utf-8")
    marker = f"{name}() {{"
    start = text.index(marker)
    depth = 0
    chunks: list[str] = []

    for line in text[start:].splitlines(keepends=True):
        chunks.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0:
            return "".join(chunks)

    raise AssertionError(f"Could not extract shell function {name}")


def _run_should_cobind(tmp_path: Path, *, bind_host: str | None) -> str:
    """Return the decision of ``should_cobind_loopback`` for a given BIND_HOST.

    ``bind_host`` is written into a temp ``.env`` (``None`` = no entry).
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to exercise deploy.sh helpers")

    env_file = tmp_path / ".env"
    env_file.write_text("" if bind_host is None else f"BIND_HOST={bind_host}\n", encoding="utf-8")

    read_fn = _extract_shell_function("read_dotenv_value")
    decide_fn = _extract_shell_function("should_cobind_loopback")

    script = f"""
set -e
ENV_FILE="{env_file}"
{read_fn}
{decide_fn}

should_cobind_loopback
"""
    result = subprocess.run([bash, "-c", script], check=True, capture_output=True, text=True)
    return result.stdout.strip()


class TestShouldCobindDecision:
    @pytest.mark.parametrize("bind_host", [None, "127.0.0.1", "::1", "localhost", "0.0.0.0", "::"])
    def test_no_cobind_for_loopback_and_wildcards(self, tmp_path: Path, bind_host):
        # Loopback already serves localhost; wildcards already cover it (and a
        # second 127.0.0.1 mapping would collide on the port).
        assert _run_should_cobind(tmp_path, bind_host=bind_host) == "no"

    @pytest.mark.parametrize("bind_host", ["100.101.102.103", "192.168.1.50", "10.0.0.9"])
    def test_cobind_for_single_specific_interface(self, tmp_path: Path, bind_host):
        # A single non-loopback interface (e.g. a Tailscale IP) must co-bind
        # loopback so the host's own localhost keeps working.
        assert _run_should_cobind(tmp_path, bind_host=bind_host) == "yes"


class TestLoopbackOverlay:
    def test_overlay_publishes_loopback_entry_port(self):
        compose = yaml.safe_load(OVERLAY_PATH.read_text(encoding="utf-8"))
        ports = compose["services"]["nginx"]["ports"]
        assert ports == ["127.0.0.1:${PORT:-2026}:2026"]

    def test_overlay_only_touches_nginx_ports(self):
        # The overlay must be a minimal additive layer — not redefine the whole
        # nginx service or touch other services — so compose concatenates the
        # port onto the base mapping instead of replacing it.
        compose = yaml.safe_load(OVERLAY_PATH.read_text(encoding="utf-8"))
        assert set(compose["services"].keys()) == {"nginx"}
        assert set(compose["services"]["nginx"].keys()) == {"ports"}
