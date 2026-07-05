#!/usr/bin/env python3
"""Decide how the stack should provide SearXNG for the `web_search` tool.

Called by scripts/deploy.sh (Docker prod), scripts/docker.sh (Docker dev), and
scripts/serve.sh (host-run) before starting services. Prints exactly one
resolution line on stdout:

    skip              config.yaml does not use the SearXNG web_search provider
    bundled           no usable existing instance found — start the bundled
                      docker service and use the in-network / loopback default
    external <url>    a reachable SearXNG instance already exists — do not
                      start the bundled service; point the gateway at <url>

Human-readable diagnostics go to stderr. Callers should treat any non-zero
exit or unparseable output as `bundled` (the safe default that always works).

Detection rules:
  1. If DEER_FLOW_SEARXNG_BASE_URL is set (env or --env-file) to something
     other than the in-network default, that explicit choice wins. Loopback
     URLs are verified and, for --context docker, translated to
     host.docker.internal (falling back to `bundled` when the instance is
     dead or unreachable from containers). Non-loopback URLs are respected
     even when they cannot be verified from this machine (they may only
     resolve inside the compose network).
  2. Otherwise the well-known local ports are probed (8088 — this repo's
     convention, then 8080 — the SearXNG default). A candidate counts only
     if it answers `GET /search?format=json` like a real SearXNG with the
     JSON API enabled, which is exactly what the web_search tool needs.
  3. An instance served by our own `deer-flow-searxng` container resolves to
     `bundled` (compose `up` on it is idempotent).
  4. For --context docker, a host-local instance is only used if containers
     can actually reach it: it must answer on the docker bridge gateway IP,
     or the daemon must be Docker Desktop (whose host.docker.internal
     proxies host loopback). Loopback-only binds on Linux fall back to
     `bundled` with a hint instead of silently breaking web_search.

Usage:
    python3 scripts/detect_searxng.py --context docker|host \
        [--config PATH] [--env-file PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ENV_VAR = "DEER_FLOW_SEARXNG_BASE_URL"
IN_NETWORK_URL = "http://searxng:8080"
BUNDLED_CONTAINER = "deer-flow-searxng"
# 8088 is this repo's published host port; 8080 is the upstream SearXNG default.
CANDIDATE_PORTS = (8088, 8080)
PROVIDER_MARKER = "deerflow.community.searxng"
PROBE_TIMEOUT = 5.0
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}


def log(message: str) -> None:
    print(f"[detect_searxng] {message}", file=sys.stderr)


def config_uses_searxng(config_text: str) -> bool:
    """True when an active (uncommented) config line references the provider."""
    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if PROVIDER_MARKER in stripped:
            return True
    return False


def parse_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser for .env files (comments, `export `, quotes)."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


# Probes target loopback / docker-bridge addresses; a configured HTTP(S)
# proxy must not intercept them, so the opener carries an empty proxy map.
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe_searxng(base_url: str, timeout: float = PROBE_TIMEOUT) -> bool:
    """True when base_url answers like a SearXNG with the JSON API enabled.

    This mirrors what the web_search tool does at runtime: instances without
    `json` in `search.formats` return 403 here and are correctly rejected.
    """
    url = base_url.rstrip("/") + "/search?q=deerflow+connectivity+check&format=json"
    request = urllib.request.Request(url, headers={"User-Agent": "deer-flow-searxng-detect/1.0"})
    try:
        with _DIRECT_OPENER.open(request, timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError, ValueError, OSError):
        return False
    return isinstance(payload, dict) and "results" in payload


def run_docker(args: list[str], timeout: float = 5.0) -> str | None:
    """Run a docker CLI command, returning stdout or None on any failure."""
    try:
        completed = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def bundled_container_publishes(port: int, docker: Callable[[list[str]], str | None]) -> bool:
    """True when our own bundled container is running and publishes `port`."""
    out = docker(["ps", "--filter", f"name={BUNDLED_CONTAINER}", "--filter", f"publish={port}", "--format", "{{.Names}}"])
    if not out:
        return False
    return BUNDLED_CONTAINER in out.split()


def bridge_gateway_ip(docker: Callable[[list[str]], str | None]) -> str | None:
    """Host IP as seen from containers on the default bridge (Linux)."""
    out = docker(["network", "inspect", "bridge", "--format", "{{(index .IPAM.Config 0).Gateway}}"])
    if out and out.strip():
        return out.strip()
    return None


def is_docker_desktop(docker: Callable[[list[str]], str | None]) -> bool:
    out = docker(["info", "--format", "{{.OperatingSystem}}"])
    return bool(out and "docker desktop" in out.lower())


def is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in LOOPBACK_HOSTS


def url_port(url: str) -> int:
    parsed = urlparse(url)
    if parsed.port:
        return parsed.port
    return 443 if parsed.scheme == "https" else 80


def translate_for_docker(url: str) -> str:
    """Rewrite loopback hosts to host.docker.internal for in-container use."""
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
    """Best-effort check that containers can reach a host-local port.

    On Linux, host.docker.internal maps to the bridge gateway IP, so a
    service must answer there (loopback-only binds do not). Docker Desktop
    proxies host.docker.internal to the host loopback, so it always passes.
    """
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
        probe = probe_searxng
    if docker is None:
        docker = run_docker
    if config_text is not None and not config_uses_searxng(config_text):
        log("config does not use the SearXNG web_search provider")
        return ("skip", None)

    explicit = env.get(ENV_VAR, "").strip()
    if explicit and explicit != IN_NETWORK_URL:
        if is_loopback_url(explicit):
            if not probe(explicit):
                log(f"{ENV_VAR}={explicit} did not answer as a SearXNG JSON API; falling back to the bundled instance")
                return ("bundled", None)
            if context == "host":
                return ("external", explicit)
            if container_can_reach_host_port(url_port(explicit), probe, docker):
                return ("external", translate_for_docker(explicit))
            log(f"{ENV_VAR}={explicit} answers on the host but is not reachable from containers (loopback-only bind?); falling back to the bundled instance")
            return ("bundled", None)
        # Non-loopback URLs (LAN hosts, compose-network names) are respected
        # as-is: they may be resolvable only from inside the network.
        if not probe(explicit):
            log(f"could not verify {ENV_VAR}={explicit} from this machine; using it anyway")
        return ("external", explicit)

    for port in CANDIDATE_PORTS:
        local_url = f"http://127.0.0.1:{port}"
        if not probe(local_url):
            continue
        if context == "host":
            log(f"found existing SearXNG at {local_url}")
            return ("external", local_url)
        if bundled_container_publishes(port, docker):
            log(f"the instance at {local_url} is our own {BUNDLED_CONTAINER} container")
            return ("bundled", None)
        if container_can_reach_host_port(port, probe, docker):
            log(f"found existing SearXNG at {local_url}; containers will use host.docker.internal:{port}")
            return ("external", f"http://host.docker.internal:{port}")
        log(f"found SearXNG at {local_url}, but containers cannot reach it (loopback-only bind?); set {ENV_VAR} to a container-reachable URL to use it")

    return ("bundled", None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--context", choices=("docker", "host"), required=True, help="docker: the gateway runs in a container; host: the gateway runs on this machine")
    parser.add_argument("--config", type=Path, default=None, help="path to config.yaml (used to skip when the SearXNG provider is not active)")
    parser.add_argument("--env-file", type=Path, default=None, help="path to a .env file consulted for DEER_FLOW_SEARXNG_BASE_URL (process env wins)")
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
            config_text = None  # unreadable config → don't skip, assume searxng

    mode, url = resolve(context=args.context, env=env, config_text=config_text)
    print(f"{mode} {url}" if url else mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
