#!/usr/bin/env python3
"""Decide how the stack should provide ComfyUI for the local media tools.

Called by the launch scripts before starting services, exactly like
``scripts/detect_searxng.py``. Prints one resolution line on stdout:

    skip              config.yaml does not use the ComfyUI media tools
    bundled           no usable existing instance found — start the bundled
                      docker service and use the loopback / in-network default
    external <url>    a reachable ComfyUI already exists — do not start a
                      second one; point the gateway at <url>

Human-readable diagnostics go to stderr. Callers should treat any non-zero exit
or unparseable output as `bundled`.

Why reuse matters more here than for SearXNG: a second ComfyUI is not a second
lightweight web service, it is a second process that will try to put model
weights on the same GPU. Starting one next to an instance you already run is
how a card ends up thrashing.

Detection rules:
  1. DEER_FLOW_COMFYUI_BASE_URL (env or --env-file) wins when set to anything
     other than the in-network default. Loopback URLs are verified and, for
     --context docker, translated to host.docker.internal. Non-loopback URLs
     are respected even when unverifiable from this machine.
  2. Otherwise the well-known port is probed (8188, ComfyUI's default). A
     candidate counts only when it answers `GET /system_stats` like ComfyUI.
  3. An instance served by our own `deer-flow-comfyui` container resolves to
     `bundled` (compose `up` on it is idempotent).
  4. For --context docker, a host-local instance is only used when containers
     can actually reach it (docker bridge gateway IP, or Docker Desktop).

Usage:
    python3 scripts/detect_comfyui.py --context docker|host \
        [--config PATH] [--env-file PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlparse, urlunparse

# Reuse the SearXNG detector's helpers rather than growing a second copy of the
# same .env parsing and docker probing. They are pure functions with no SearXNG
# specifics in them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from detect_searxng import (  # noqa: E402 - path bootstrap above
    LOOPBACK_HOSTS,
    bridge_gateway_ip,
    is_docker_desktop,
    parse_env_file,
    run_docker,
)

ENV_VAR = "DEER_FLOW_COMFYUI_BASE_URL"
IN_NETWORK_URL = "http://comfyui:8188"
BUNDLED_CONTAINER = "deer-flow-comfyui"
CANDIDATE_PORTS = (8188,)
# Any active line naming the tool package means the media tools are enabled.
PROVIDER_MARKER = "deerflow.community.comfyui"
PROBE_TIMEOUT = 5.0

_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def log(message: str) -> None:
    print(f"[detect_comfyui] {message}", file=sys.stderr)


def config_uses_comfyui(config_text: str) -> bool:
    """True when an active (uncommented) config line references the tools."""
    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if PROVIDER_MARKER in stripped:
            return True
    return False


def probe_comfyui(base_url: str, timeout: float = PROBE_TIMEOUT) -> bool:
    """True when base_url answers /system_stats like a ComfyUI would.

    /system_stats is the same endpoint the GPU arbiter reads for residency, so
    an instance that passes here is one the tools can actually drive.
    """
    url = base_url.rstrip("/") + "/system_stats"
    request = urllib.request.Request(url, headers={"User-Agent": "deer-flow-comfyui-detect/1.0"})
    try:
        with _DIRECT_OPENER.open(request, timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, ValueError, OSError):
        return False
    return isinstance(payload, dict) and ("system" in payload or "devices" in payload)


def bundled_container_publishes(port: int, docker: Callable[[list[str]], str | None]) -> bool:
    out = docker(["ps", "--filter", f"name={BUNDLED_CONTAINER}", "--filter", f"publish={port}", "--format", "{{.Names}}"])
    if not out:
        return False
    return BUNDLED_CONTAINER in out.split()


def is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in LOOPBACK_HOSTS


def url_port(url: str) -> int:
    parsed = urlparse(url)
    if parsed.port:
        return parsed.port
    return 443 if parsed.scheme == "https" else 80


def translate_for_docker(url: str) -> str:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in LOOPBACK_HOSTS:
        return url
    host = "host.docker.internal"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=host))


def container_can_reach_host_port(
    port: int,
    probe: Callable[[str], bool],
    docker: Callable[[list[str]], str | None],
) -> bool:
    ip = bridge_gateway_ip(docker)
    if ip and probe(f"http://{ip}:{port}"):
        return True
    return is_docker_desktop(docker)


def resolve(
    *,
    context: str,
    env: Mapping[str, str],
    config_text: str | None,
    probe: Callable[[str], bool] | None = None,
    docker: Callable[[list[str]], str | None] | None = None,
) -> tuple[str, str | None]:
    """Return (mode, url) where mode is "skip" | "bundled" | "external"."""
    if probe is None:
        probe = probe_comfyui
    if docker is None:
        docker = run_docker
    if config_text is not None and not config_uses_comfyui(config_text):
        log("config does not use the ComfyUI media tools")
        return ("skip", None)

    explicit = env.get(ENV_VAR, "").strip()
    if explicit and explicit != IN_NETWORK_URL:
        if is_loopback_url(explicit):
            if not probe(explicit):
                log(f"{ENV_VAR}={explicit} did not answer as a ComfyUI; falling back to the bundled instance")
                return ("bundled", None)
            if context == "host":
                return ("external", explicit)
            if container_can_reach_host_port(url_port(explicit), probe, docker):
                return ("external", translate_for_docker(explicit))
            log(f"{ENV_VAR}={explicit} answers on the host but is not reachable from containers (loopback-only bind?); falling back to the bundled instance")
            return ("bundled", None)
        if not probe(explicit):
            log(f"could not verify {ENV_VAR}={explicit} from this machine; using it anyway")
        return ("external", explicit)

    for port in CANDIDATE_PORTS:
        local_url = f"http://127.0.0.1:{port}"
        if not probe(local_url):
            continue
        if context == "host":
            log(f"found existing ComfyUI at {local_url}")
            return ("external", local_url)
        if bundled_container_publishes(port, docker):
            log(f"the instance at {local_url} is our own {BUNDLED_CONTAINER} container")
            return ("bundled", None)
        if container_can_reach_host_port(port, probe, docker):
            log(f"found existing ComfyUI at {local_url}; containers will use host.docker.internal:{port}")
            return ("external", f"http://host.docker.internal:{port}")
        log(f"found ComfyUI at {local_url}, but containers cannot reach it (loopback-only bind?); set {ENV_VAR} to a container-reachable URL to use it")

    return ("bundled", None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--context", choices=("docker", "host"), required=True, help="docker: the gateway runs in a container; host: the gateway runs on this machine")
    parser.add_argument("--config", type=Path, default=None, help="path to config.yaml (used to skip when the media tools are not active)")
    parser.add_argument("--env-file", type=Path, default=None, help=f"path to a .env file consulted for {ENV_VAR} (process env wins)")
    args = parser.parse_args(argv)

    env: dict[str, str] = {}
    if args.env_file is not None:
        env.update(parse_env_file(args.env_file))
    if os.environ.get(ENV_VAR, "").strip():
        env[ENV_VAR] = os.environ[ENV_VAR]

    config_text: str | None = None
    if args.config is not None:
        try:
            config_text = args.config.read_text(encoding="utf-8")
        except OSError:
            config_text = None

    mode, url = resolve(context=args.context, env=env, config_text=config_text)
    print(f"{mode} {url}" if url else mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
