#!/usr/bin/env python3
"""Effective network exposure of this DeerFlow instance (fork feature).

Passwordless auth, multi-user mode off, and a non-loopback ``BIND_HOST`` are
simultaneously this fork's happy path and its worst-case posture. Each setting
is individually documented and defensible; the *combination* is what matters,
and nothing computed it — the operator was left to reason about three
independent settings in three different files.

This module computes it, and only that. It changes no default, reads no
secrets, and never fails a launch: it is diagnosis, printed where it is
actually read (``make doctor``, and the closing summary of ``make up`` /
``make dev``).

Two entry surfaces exist and they do not share a bind address:

* ``docker`` — ``make up`` publishes the nginx entry port at
  ``${BIND_HOST:-127.0.0.1}:${PORT:-2026}``, so ``BIND_HOST`` is the whole
  external surface.
* ``local`` — ``make dev`` / ``make start`` run nginx from
  ``docker/nginx/nginx.local.conf``, whose ``listen 2026;`` has no address.
  ``BIND_HOST`` does not apply; the local stack is on every interface.

Usage:
    python3 scripts/exposure.py --surface docker
    python3 scripts/exposure.py --surface local --format json
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Reach = Literal["loopback", "tailscale", "private", "public", "wildcard", "unknown"]
Tier = Literal["local-only", "trusted-network", "open-network"]
Surface = Literal["docker", "local"]
Status = Literal["ok", "warn"]

# Mirrors app/gateway/auth_disabled.py — kept as literals rather than an import
# because this script runs from the repo root with no backend on sys.path.
AUTH_DISABLED_ENV_VAR = "DEER_FLOW_AUTH_DISABLED"
PRODUCTION_ENV_VARS: tuple[str, ...] = ("DEER_FLOW_ENV", "ENVIRONMENT")
PRODUCTION_ENV_VALUES = frozenset({"prod", "production"})

# docker/docker-compose.yaml publishes "${BIND_HOST:-127.0.0.1}:${PORT:-2026}:2026".
DEFAULT_DOCKER_BIND_HOST = "127.0.0.1"
LOCAL_BIND_SOURCE = "nginx.local.conf"

# Tailscale addresses come from the CGNAT range plus its own IPv6 ULA prefix.
# Python reports 100.64.0.0/10 as "private", so this has to be checked first —
# a tailnet is a device-authenticated overlay, not the same risk as a LAN.
_TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")
_TAILSCALE_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")

_LOOPBACK_NAMES = frozenset({"localhost", "localhost4", "localhost6", "ip6-localhost"})
_WILDCARD_NAMES = frozenset({"0.0.0.0", "::", "*"})


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def classify_bind_host(value: str | None) -> Reach:
    """Classify a bind address by who can reach it.

    An unparseable value (a hostname) is ``unknown`` rather than a guess:
    resolving it here would be a DNS call in a diagnostic, and guessing
    "probably local" is the one direction this must never fail in.
    """
    host = (value or "").strip()
    if not host or host in _WILDCARD_NAMES:
        return "wildcard"
    if host.lower() in _LOOPBACK_NAMES:
        return "loopback"
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return "unknown"
    if addr.is_unspecified:
        return "wildcard"
    if addr.is_loopback:
        return "loopback"
    if addr in _TAILSCALE_V4 or addr in _TAILSCALE_V6:
        return "tailscale"
    if addr.is_private or addr.is_link_local:
        return "private"
    return "public"


def _read_dotenv(path: Path) -> dict[str, str]:
    """Parse the handful of plain ``KEY=value`` lines we care about."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def _resolve(name: str, env: Mapping[str, str], dotenv: Mapping[str, str]) -> tuple[str | None, str]:
    """Process environment first, then ``.env`` — the precedence both launch scripts use."""
    value = env.get(name)
    if value is not None and value.strip():
        return value.strip(), "environment"
    value = dotenv.get(name)
    if value is not None and value.strip():
        return value.strip(), ".env"
    return None, "default"


def _runtime_home_candidates(project_root: Path, env: Mapping[str, str]) -> list[Path]:
    home = env.get("DEER_FLOW_HOME")
    if home:
        return [Path(home)]
    # The Gateway runs from backend/, so its DeerFlow home is backend/.deer-flow;
    # a repo-root .deer-flow is the embedded-client / TUI layout.
    return [project_root / "backend" / ".deer-flow", project_root / ".deer-flow"]


def read_multi_user_mode(project_root: Path, env: Mapping[str, str]) -> bool:
    """Read the runtime-toggleable multi-user flag (default ON = isolated)."""
    for base in _runtime_home_candidates(project_root, env):
        path = base / "runtime_settings.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("multi_user_mode"), bool):
            return data["multi_user_mode"]
    return True


def _read_sandbox(config_path: Path) -> tuple[bool, bool, bool]:
    """Return ``(config_present, sandbox_isolated, host_bash)`` from config.yaml."""
    if not config_path.exists():
        return False, False, False
    try:
        import yaml

        with config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except Exception:
        return False, False, False
    sandbox = data.get("sandbox") if isinstance(data, dict) else None
    if not isinstance(sandbox, dict):
        return True, False, False
    use = str(sandbox.get("use") or "")
    isolated = "LocalSandboxProvider" not in use and bool(use)
    host_bash = not isolated and bool(sandbox.get("allow_host_bash", False))
    return True, isolated, host_bash


@dataclass(frozen=True)
class DeploymentFacts:
    """The settings that together decide who can reach this instance, and as whom."""

    surface: Surface
    bind_host: str
    bind_source: str
    reach: Reach
    auth_disabled_requested: bool
    auth_disabled_effective: bool
    production_env: bool
    multi_user_mode: bool
    sandbox_isolated: bool
    host_bash: bool
    config_present: bool


def resolve_facts(
    project_root: Path,
    *,
    surface: Surface = "docker",
    env: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> DeploymentFacts:
    env = os.environ if env is None else env
    dotenv = _read_dotenv(project_root / ".env")

    if surface == "local":
        # nginx.local.conf listens without an address; BIND_HOST is not consulted.
        bind_host, bind_source, reach = "0.0.0.0", LOCAL_BIND_SOURCE, "wildcard"
    else:
        raw, source = _resolve("BIND_HOST", env, dotenv)
        bind_host = raw or DEFAULT_DOCKER_BIND_HOST
        bind_source = source
        reach = classify_bind_host(bind_host)

    auth_raw, _ = _resolve(AUTH_DISABLED_ENV_VAR, env, dotenv)
    # Both serve.sh and deploy.sh default this to 1 when nothing sets it.
    auth_requested = (auth_raw if auth_raw is not None else "1") == "1"
    production = any((env.get(name) or dotenv.get(name) or "").strip().lower() in PRODUCTION_ENV_VALUES for name in PRODUCTION_ENV_VARS)

    config_present, sandbox_isolated, host_bash = _read_sandbox(config_path or (project_root / "config.yaml"))

    return DeploymentFacts(
        surface=surface,
        bind_host=bind_host,
        bind_source=bind_source,
        reach=reach,
        auth_disabled_requested=auth_requested,
        auth_disabled_effective=auth_requested and not production,
        production_env=production,
        multi_user_mode=read_multi_user_mode(project_root, env),
        sandbox_isolated=sandbox_isolated,
        host_bash=host_bash,
        config_present=config_present,
    )


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExposureFactor:
    name: str
    detail: str
    contributes: bool
    fix: str | None = None


@dataclass(frozen=True)
class Exposure:
    tier: Tier
    status: Status
    headline: str
    factors: tuple[ExposureFactor, ...]
    facts: DeploymentFacts

    def summary_line(self) -> str:
        return f"Exposure: {self.tier} — {self.headline}"

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "status": self.status,
            "headline": self.headline,
            "surface": self.facts.surface,
            "factors": [asdict(f) for f in self.factors],
            "facts": asdict(self.facts),
        }


_REACH_PHRASE: dict[Reach, str] = {
    "loopback": "this machine only",
    "tailscale": "every device on your tailnet",
    "private": "every device on the local network",
    "public": "the public internet",
    "wildcard": "every interface on this host, including any public one",
    "unknown": "an address this check could not classify",
}

_ENTRY_LABEL: dict[Surface, str] = {"docker": "make up", "local": "make dev"}


def assess(facts: DeploymentFacts) -> Exposure:
    """Combine the settings into one tier, naming each contributing one.

    The rule that keeps this honest rather than noisy: a setting only
    *contributes* once something outside this machine can reach the instance.
    Multi-user mode off on a loopback-only box is the documented personal-server
    default, not a finding.
    """
    reachable = facts.reach != "loopback"
    factors: list[ExposureFactor] = []

    # ── bind ────────────────────────────────────────────────────────────────
    if facts.surface == "local":
        bind_detail = f"{_ENTRY_LABEL['local']} serves nginx on every interface ({LOCAL_BIND_SOURCE} listens without an address; BIND_HOST does not apply)"
        bind_fix = "Use `make up` with BIND_HOST=127.0.0.1 in .env for a loopback-only stack, or keep the host off untrusted networks"
    else:
        bind_detail = f"published on {facts.bind_host} (from {facts.bind_source}) — reachable by {_REACH_PHRASE[facts.reach]}"
        bind_fix = "Set BIND_HOST=127.0.0.1 in .env, or to your Tailscale IP, then `make up-start`"
    factors.append(ExposureFactor("bind", bind_detail, contributes=reachable, fix=bind_fix if reachable else None))

    # ── auth ────────────────────────────────────────────────────────────────
    if facts.auth_disabled_effective:
        auth_detail = f"{AUTH_DISABLED_ENV_VAR}=1 — every request runs as the built-in 'default' admin, with no login"
        auth_fix = f"Set {AUTH_DISABLED_ENV_VAR}=0 in .env to require email/password login"
        auth_contributes = reachable
    elif facts.auth_disabled_requested and facts.production_env:
        auth_detail = f"{AUTH_DISABLED_ENV_VAR}=1 is set but ignored — DEER_FLOW_ENV/ENVIRONMENT is production, so login is required"
        auth_fix = None
        auth_contributes = False
    else:
        auth_detail = "login required"
        auth_fix = None
        auth_contributes = False
    factors.append(ExposureFactor("auth", auth_detail, contributes=auth_contributes, fix=auth_fix))

    # ── multi-user mode ─────────────────────────────────────────────────────
    escalates = reachable and facts.auth_disabled_effective
    if facts.multi_user_mode:
        mu_detail = "multi-user mode on — each login only sees its own conversations"
    else:
        mu_detail = "multi-user mode off — every conversation is visible to anyone who reaches the server"
    factors.append(
        ExposureFactor(
            "multi-user",
            mu_detail,
            contributes=escalates and not facts.multi_user_mode,
            fix="Settings → Account → turn multi-user mode back on" if escalates and not facts.multi_user_mode else None,
        )
    )

    # ── sandbox ─────────────────────────────────────────────────────────────
    if not facts.config_present:
        sandbox_detail = "no config.yaml yet — sandbox isolation unknown"
        sandbox_contributes = False
        sandbox_fix = None
    elif facts.sandbox_isolated:
        sandbox_detail = "container sandbox — agent commands run isolated from the host"
        sandbox_contributes = False
        sandbox_fix = None
    elif facts.host_bash:
        sandbox_detail = "local sandbox with allow_host_bash: true — agent commands run directly on this host"
        sandbox_contributes = escalates
        sandbox_fix = "Run `make sandbox-enable MODE=container` so shell commands are isolated" if escalates else None
    else:
        sandbox_detail = "local sandbox, host bash off — file tools touch the host, shell does not"
        sandbox_contributes = False
        sandbox_fix = None
    factors.append(ExposureFactor("sandbox", sandbox_detail, contributes=sandbox_contributes, fix=sandbox_fix))

    # ── tier ────────────────────────────────────────────────────────────────
    if not reachable:
        tier: Tier = "local-only"
        status: Status = "ok"
        headline = f"reachable from this machine only ({facts.bind_host})"
    elif facts.auth_disabled_effective and facts.reach in {"wildcard", "public", "unknown"}:
        tier = "open-network"
        status = "warn"
        headline = f"no login wall, reachable by {_REACH_PHRASE[facts.reach]}"
    elif facts.auth_disabled_effective:
        tier = "trusted-network"
        status = "warn"
        headline = f"no login wall, reachable by {_REACH_PHRASE[facts.reach]}"
    else:
        tier = "trusted-network"
        status = "warn"
        headline = f"login required, reachable by {_REACH_PHRASE[facts.reach]}"

    return Exposure(tier=tier, status=status, headline=headline, factors=tuple(factors), facts=facts)


def report_lines(result: Exposure) -> list[str]:
    """Render the assessment: one line when fine, the contributing settings when not."""
    lines = [result.summary_line()]
    for factor in result.factors:
        if not factor.contributes:
            continue
        lines.append(f"  • {factor.detail}")
        if factor.fix:
            lines.append(f"    → {factor.fix}")
    return lines


def assess_project(
    project_root: Path,
    *,
    surface: Surface = "docker",
    env: Mapping[str, str] | None = None,
) -> Exposure:
    return assess(resolve_facts(project_root, surface=surface, env=env))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report this instance's effective network exposure.")
    parser.add_argument("--surface", choices=["docker", "local"], default="docker")
    parser.add_argument("--format", choices=["text", "json", "line"], default="text")
    parser.add_argument("--project-root", default=None)
    args = parser.parse_args(argv)

    root = Path(args.project_root) if args.project_root else Path(__file__).resolve().parents[1]
    try:
        result = assess_project(root, surface=args.surface)
    except Exception as exc:  # diagnosis must never break a launch
        print(f"Exposure: unavailable ({exc})", file=sys.stderr)
        return 0

    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2))
    elif args.format == "line":
        print(result.summary_line())
    else:
        print("\n".join(report_lines(result)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
