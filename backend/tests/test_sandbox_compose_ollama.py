"""Regression coverage: the external AIO sandbox container can reach a host-run Ollama.

docker/docker-compose.sandbox.yml must map ``host.docker.internal`` to the host
gateway (Linux daemons do not provide the alias automatically the way Docker
Desktop does) and advertise ``OLLAMA_HOST`` inside the container so agent-run
Ollama clients target the host daemon instead of the container's own loopback.
The per-conversation (provider-created) containers get the same treatment in
``local_backend.py`` — covered by ``test_aio_sandbox_local_backend.py``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker" / "docker-compose.sandbox.yml"


def _sandbox_service() -> dict:
    data = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    return data["services"]["sandbox"]


def test_sandbox_compose_maps_host_gateway_alias():
    service = _sandbox_service()
    assert "host.docker.internal:host-gateway" in service.get("extra_hosts", [])


def test_sandbox_compose_advertises_host_ollama():
    environment = _sandbox_service()["environment"]
    assert environment["OLLAMA_HOST"] == "${DEER_FLOW_SANDBOX_OLLAMA_HOST:-http://host.docker.internal:11434}"


def test_sandbox_compose_stays_loopback_only():
    """The alias must not come with a broader port binding — the sandbox API stays loopback-only."""
    ports = _sandbox_service()["ports"]
    assert ports == ["127.0.0.1:8091:8080"]
