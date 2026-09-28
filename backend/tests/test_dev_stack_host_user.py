"""The dev stack must not leave root-owned files in the checkout.

docker/docker-compose-dev.yaml bind-mounts the checkout read-write into
containers that start as root. Everything the Gateway created there — thread
data under backend/.deer-flow, logs/, skills/custom, __pycache__ — landed on the
host owned by root, and the next `git pull` / `git clean` as the normal user
failed until a `sudo chown -R`.

Pinned here:
- scripts/docker.sh passes the invoking user's ids (Linux only) and creates
  logs/ itself, so Docker does not create it as root;
- docker/dev-entrypoint.sh drops to those ids with setpriv, joining the DooD
  socket's group when that socket is mounted, and leaves root alone when no ids
  (or 0) are given;
- the Gateway writes no bytecode into the source tree, and the frontend's
  source mounts are read-only.

The ownership hand-over itself (find -user 0 | chown) needs root and a real
container; it is exercised manually, see FORK.md "Dev stack file ownership".
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_COMPOSE = REPO_ROOT / "docker" / "docker-compose-dev.yaml"
ENTRYPOINT = REPO_ROOT / "docker" / "dev-entrypoint.sh"
DOCKER_SH = REPO_ROOT / "scripts" / "docker.sh"
BASH = shutil.which("bash")

posix_only = pytest.mark.skipif(BASH is None or os.name == "nt", reason="exercises POSIX shell scripts")


def _service(name: str) -> dict:
    return yaml.safe_load(DEV_COMPOSE.read_text(encoding="utf-8"))["services"][name]


def _environment(name: str) -> list[str]:
    return [str(entry) for entry in _service(name).get("environment", [])]


class TestComposeShape:
    def test_gateway_receives_the_host_ids_without_a_default(self) -> None:
        env = _environment("gateway")
        # Empty, not 1000, when unset: a guessed uid would hand the user's
        # files to someone else. Empty keeps the old run-as-root behavior.
        assert "DEER_FLOW_UID=${DEER_FLOW_UID:-}" in env
        assert "DEER_FLOW_GID=${DEER_FLOW_GID:-}" in env

    def test_gateway_writes_no_bytecode_into_the_source_tree(self) -> None:
        assert "PYTHONDONTWRITEBYTECODE=1" in _environment("gateway")

    def test_gateway_starts_as_root_so_the_entrypoint_can_hand_over_volumes(self) -> None:
        # A compose `user:` would start it unprivileged: the named volumes
        # (.venv, uv cache) stay root-owned and `uv sync` fails.
        assert "user" not in _service("gateway")

    @pytest.mark.parametrize("target", ["/app/frontend/src", "/app/frontend/public"])
    def test_frontend_source_mounts_are_read_only(self, target: str) -> None:
        mounts = [str(v) for v in _service("frontend")["volumes"] if str(v).split(":")[1:2] == [target]]
        assert len(mounts) == 1, mounts
        assert mounts[0].split(":")[2:] == ["ro"]


def _extract_function(script: Path, name: str) -> str:
    lines = script.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{name}() {{")
    end = lines.index("}", start)
    return "\n".join(lines[start : end + 1])


@posix_only
class TestDockerShPassesHostIds:
    def _ids(self, kernel: str, preset: dict[str, str] | None = None) -> str:
        snippet = f"""
            uname() {{ echo {kernel}; }}
            id() {{ case "$1" in -u) echo 1234 ;; -g) echo 5678 ;; esac; }}
            source /dev/stdin <<'FUNCS'
{_extract_function(DOCKER_SH, "ensure_host_user_ids")}
FUNCS
            ensure_host_user_ids
            echo "${{DEER_FLOW_UID-unset}}:${{DEER_FLOW_GID-unset}}"
        """
        env = {k: v for k, v in os.environ.items() if k not in ("DEER_FLOW_UID", "DEER_FLOW_GID")}
        env.update(preset or {})
        result = subprocess.run([BASH, "-c", snippet], capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def test_linux_exports_the_invoking_users_ids(self) -> None:
        assert self._ids("Linux") == "1234:5678"

    @pytest.mark.parametrize("kernel", ["Darwin", "MINGW64_NT-10.0"])
    def test_docker_desktop_hosts_are_left_alone(self, kernel: str) -> None:
        # Docker Desktop maps bind-mount ownership to the host user already.
        assert self._ids(kernel) == "unset:unset"

    def test_an_operator_override_wins(self) -> None:
        # DEER_FLOW_UID=0 is the documented way back to run-as-root.
        assert self._ids("Linux", {"DEER_FLOW_UID": "0", "DEER_FLOW_GID": "0"}) == "0:0"

    def test_start_creates_logs_before_compose_can(self) -> None:
        text = DOCKER_SH.read_text(encoding="utf-8")
        start = text.index("start() {")
        body = text[start : text.index("\n}\n", start)]
        mkdir = body.index('mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/backend/.venv"')
        assert mkdir < body.index("up --build")


@posix_only
class TestEntrypointDropsToTheHostUser:
    def _run_as(self, tmp_path: Path, *, container_uid: str = "0", env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        shim = tmp_path / "bin"
        shim.mkdir(exist_ok=True)
        fake_id = shim / "id"
        fake_id.write_text(f'#!/bin/sh\n[ "$1" = -u ] && echo {container_uid} && exit 0\nexec /usr/bin/env -i id "$@"\n', encoding="utf-8")
        fake_id.chmod(0o755)
        full_env = {k: v for k, v in os.environ.items() if k not in ("DEER_FLOW_UID", "DEER_FLOW_GID")}
        full_env.update({"PATH": f"{shim}{os.pathsep}{os.environ.get('PATH', '')}", "DEER_FLOW_RUN_AS_DOCKER_SOCKET": str(tmp_path / "no.sock")})
        full_env.update(env or {})
        return subprocess.run(["sh", str(ENTRYPOINT), "--print-run-as"], capture_output=True, text=True, env=full_env, timeout=30)

    def test_drops_to_the_given_ids_with_no_inherited_groups(self, tmp_path: Path) -> None:
        result = self._run_as(tmp_path, env={"DEER_FLOW_UID": "1234", "DEER_FLOW_GID": "5678"})
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "setpriv --reuid=1234 --regid=5678 --clear-groups"

    def test_gid_defaults_to_the_uid(self, tmp_path: Path) -> None:
        assert self._run_as(tmp_path, env={"DEER_FLOW_UID": "1234"}).stdout.strip() == "setpriv --reuid=1234 --regid=1234 --clear-groups"

    @pytest.mark.parametrize("uid", ["", "0"])
    def test_no_ids_or_root_keeps_running_as_root(self, tmp_path: Path, uid: str) -> None:
        assert self._run_as(tmp_path, env={"DEER_FLOW_UID": uid}).stdout.strip() == "as-is"

    def test_an_unprivileged_container_cannot_drop_and_does_not_try(self, tmp_path: Path) -> None:
        assert self._run_as(tmp_path, container_uid="1000", env={"DEER_FLOW_UID": "1234"}).stdout.strip() == "as-is"

    @pytest.mark.parametrize("uid", ["12a", "-1", "1234 --reuid=0"])
    def test_a_non_numeric_id_aborts(self, tmp_path: Path, uid: str) -> None:
        result = self._run_as(tmp_path, env={"DEER_FLOW_UID": uid})
        assert result.returncode != 0
        assert "numeric" in result.stderr

    def test_a_mounted_docker_socket_adds_its_group(self, tmp_path: Path) -> None:
        if subprocess.run(["stat", "-c", "%g", "/"], capture_output=True).returncode != 0:
            pytest.skip("needs GNU stat, as in the gateway image")
        sock_path = tmp_path / "docker.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        try:
            result = self._run_as(tmp_path, env={"DEER_FLOW_UID": "1234", "DEER_FLOW_RUN_AS_DOCKER_SOCKET": str(sock_path)})
        finally:
            server.close()
        assert result.stdout.strip() == f"setpriv --reuid=1234 --regid=1234 --groups={sock_path.stat().st_gid}"
