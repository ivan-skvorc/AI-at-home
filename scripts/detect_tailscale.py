#!/usr/bin/env python3
"""Detect the host's tailnet identity so the stack can publish itself on it.

Called by scripts/docker.sh (Docker dev), scripts/deploy.sh (Docker prod), and
scripts/serve.sh (host-run) before starting services. It answers one question:
*if this machine is on a tailnet, what addresses do other tailnet devices use to
reach it?* Everything the launch scripts do with Tailscale — publishing the
nginx port on the CGNAT address, merging origins into the CORS / trusted-origin
allowlists, printing the banner — is driven from this one answer.

Prints shell-evaluable ``KEY=value`` lines on stdout (``--format env``, the
default), or a JSON object (``--format json``). Human-readable diagnostics go to
stderr. **Absence of Tailscale is not an error**: the script prints nothing and
exits 0, so every caller can run it unconditionally and simply get no new
publish and no new origins. Any unexpected failure degrades the same way — a
launch path must never break because a detector could not make up its mind.

Emitted keys (only when Tailscale is up and has an IPv4):

    DEER_FLOW_TAILSCALE_IPV4       100.x.y.z — the CGNAT address peers dial
    DEER_FLOW_TAILSCALE_HOSTNAME   MagicDNS name, trailing dot stripped (may be
                                   absent when MagicDNS is off for the tailnet)
    DEER_FLOW_TAILSCALE_ORIGINS    comma-separated browser origins to allowlist

Why the origins matter as much as the port: a browser on another tailnet device
sends ``Origin: http://100.x.y.z:2026`` (or ``https://<magicdns>`` through
Tailscale Serve). Publishing the port without adding those origins to the
allowlists gets you a shell that loads and an API that 403s — the half-fixed
state that makes this look like a Tailscale problem rather than a config one.

Usage:
    python3 scripts/detect_tailscale.py [--format env|json] [--port PORT]
                                        [--status-json PATH] [--serve]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess  # noqa: S404 - invoking the local `tailscale` CLI is the point
import sys
from dataclasses import dataclass, field
from ipaddress import AddressValueError, IPv4Address

# `tailscale status --json` is a local, unauthenticated read of the daemon's own
# view. Two seconds is generous for that and keeps a wedged daemon from stalling
# every `make docker-start`.
STATUS_TIMEOUT_SECONDS = 5.0

# Only a daemon in this state has usable addresses. "Stopped", "NeedsLogin", and
# "NoState" all mean the machine is not on the tailnet right now, which is
# indistinguishable from not having Tailscale at all as far as publishing goes.
RUNNING_BACKEND_STATE = "Running"

ENV_IPV4 = "DEER_FLOW_TAILSCALE_IPV4"
ENV_HOSTNAME = "DEER_FLOW_TAILSCALE_HOSTNAME"
ENV_ORIGINS = "DEER_FLOW_TAILSCALE_ORIGINS"

# Opt-out switch. Publishing only ever happens when Tailscale is actually up, so
# the default is "use the tailnet you already have"; this is the escape hatch for
# a host that is on a tailnet but deliberately should not serve DeerFlow to it.
ENV_PUBLISH_TOGGLE = "DEER_FLOW_TAILSCALE_PUBLISH"

_FALSEY = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class TailnetIdentity:
    """The addresses other tailnet devices use to reach this machine."""

    ipv4: str
    magic_dns: str | None = None
    ipv6: str | None = None


@dataclass
class Detection:
    """Result of a detection pass; ``identity`` is None when Tailscale is absent."""

    identity: TailnetIdentity | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def present(self) -> bool:
        return self.identity is not None


def publish_enabled(env: dict[str, str] | None = None) -> bool:
    """Whether the tailnet publish is wanted at all.

    Default on — but note this only ever *does* anything when detection finds a
    live tailnet, so a host without Tailscale is unaffected either way.
    """
    raw = (env if env is not None else os.environ).get(ENV_PUBLISH_TOGGLE, "").strip().lower()
    return raw not in _FALSEY


def _is_ipv4(value: str) -> bool:
    try:
        IPv4Address(value)
    except (AddressValueError, ValueError):
        return False
    return True


def parse_status(payload: object) -> TailnetIdentity | None:
    """Reduce ``tailscale status --json`` output to this machine's addresses.

    Returns None for every shape that does not describe a machine currently on a
    tailnet — wrong type, backend not Running, no ``Self``, no IPv4. The IPv4 is
    required because it is what a phone's existing bookmark dials; a tailnet with
    only IPv6 addresses cannot serve the compatibility URL this whole feature
    exists to keep working.
    """
    if not isinstance(payload, dict):
        return None

    # Older/other builds may omit BackendState entirely; only an explicitly
    # non-Running state disqualifies the host.
    state = payload.get("BackendState")
    if isinstance(state, str) and state != RUNNING_BACKEND_STATE:
        return None

    self_node = payload.get("Self")
    if not isinstance(self_node, dict):
        return None

    addresses = self_node.get("TailscaleIPs")
    if not isinstance(addresses, list):
        return None

    ipv4 = next((a for a in addresses if isinstance(a, str) and _is_ipv4(a)), None)
    if ipv4 is None:
        return None
    ipv6 = next((a for a in addresses if isinstance(a, str) and not _is_ipv4(a)), None)

    magic_dns = self_node.get("DNSName")
    if isinstance(magic_dns, str):
        # The daemon reports a fully-qualified name with the root dot
        # ("box.tailnet.ts.net."). A URL must not carry it.
        magic_dns = magic_dns.strip().rstrip(".") or None
    else:
        magic_dns = None

    return TailnetIdentity(ipv4=ipv4, magic_dns=magic_dns, ipv6=ipv6)


def read_status(status_json: str | None = None, *, runner=subprocess.run) -> Detection:
    """Detect the tailnet identity, degrading to "absent" on every failure.

    ``status_json`` short-circuits the CLI (used by tests and by callers that
    already hold a status payload).
    """
    if status_json is not None:
        try:
            return Detection(identity=parse_status(json.loads(status_json)))
        except (ValueError, TypeError):
            return Detection(notes=["tailscale status payload was not valid JSON"])

    binary = shutil.which("tailscale")
    if binary is None:
        return Detection(notes=["no `tailscale` binary on PATH"])

    try:
        completed = runner(
            [binary, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=STATUS_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return Detection(notes=[f"could not run `tailscale status`: {exc}"])

    if completed.returncode != 0:
        return Detection(notes=["`tailscale status` exited non-zero (daemon down or not logged in)"])

    try:
        payload = json.loads(completed.stdout or "")
    except ValueError:
        return Detection(notes=["`tailscale status --json` did not return JSON"])

    identity = parse_status(payload)
    if identity is None:
        return Detection(notes=["Tailscale is installed but this machine has no tailnet IPv4 right now"])
    return Detection(identity=identity)


def tailnet_origins(identity: TailnetIdentity, port: int, *, include_serve: bool = True) -> list[str]:
    """Browser origins a tailnet device can load the app from.

    Two shapes, both required:

    * ``http://100.x.y.z:<port>`` — the compatibility URL. Bookmarks and phones
      already use it, and it is what the extra published port answers on.
    * ``https://<magicdns>`` — the Tailscale Serve URL. Serve terminates TLS on
      443 and forwards to loopback, so it carries **no port** and is always
      https. Adding it costs nothing when Serve is not configured (an origin
      that never arrives is never matched) and avoids a second reconfigure step
      the moment the user does run `tailscale serve`.

    Deliberately **not** emitted: ``https://100.x.y.z``. Serve's certificate is
    issued for the MagicDNS name, so an https URL on the bare IP is a
    certificate error every time — offering it as an origin would only help
    someone reach a page that cannot load.
    """
    origins = [f"http://{identity.ipv4}:{port}"]
    if include_serve and identity.magic_dns:
        origins.append(f"https://{identity.magic_dns}")
        # Serve can also be pointed at a non-443 port, in which case the origin
        # carries it. Cheap to allow, and it is the documented alternative when
        # 443 is already taken on the host.
        if port != 443:
            origins.append(f"https://{identity.magic_dns}:{port}")
    return origins


def merge_origins(existing: str | None, additions: list[str]) -> str:
    """Add origins to a comma-separated allowlist without dropping user entries.

    Order is "what the user set, then what we detected", and duplicates are
    removed on normalized comparison, so re-running a launch script is
    idempotent rather than growing the list on every start. A user entry is
    never rewritten — only compared — because an operator may have deliberately
    written an origin in a form we would not generate.
    """
    merged: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        candidate = value.strip()
        if not candidate:
            return
        key = candidate.rstrip("/").lower()
        if key in seen:
            return
        seen.add(key)
        merged.append(candidate)

    for entry in (existing or "").split(","):
        _add(entry)
    for entry in additions:
        _add(entry)
    return ",".join(merged)


def _emit_env(identity: TailnetIdentity, origins: list[str]) -> str:
    lines = [f"{ENV_IPV4}={identity.ipv4}"]
    if identity.magic_dns:
        lines.append(f"{ENV_HOSTNAME}={identity.magic_dns}")
    lines.append(f"{ENV_ORIGINS}={','.join(origins)}")
    return "\n".join(lines)


def _read_status_file(path: str) -> str | None:
    """Read a status payload, treating an unreadable file as "no tailnet"."""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        print(f"detect_tailscale: cannot read {path}: {exc}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect this host's tailnet identity for DeerFlow's launch scripts.")
    parser.add_argument("--format", choices=("env", "json"), default="env")
    parser.add_argument("--port", type=int, default=2026, help="published entry port, used to build the compatibility origin")
    parser.add_argument("--status-json", help="read a `tailscale status --json` payload from this file instead of running the CLI")
    parser.add_argument("--no-serve-origin", action="store_true", help="omit the https MagicDNS origin")
    parser.add_argument(
        "--merge-into",
        metavar="EXISTING",
        help="print EXISTING (a comma-separated allowlist) with the detected tailnet origins merged in, then exit. Prints EXISTING unchanged when there is no tailnet, so a caller can assign the result unconditionally.",
    )
    args = parser.parse_args(argv)

    if args.merge_into is not None:
        # Shell-facing helper: keeps the merge rules (dedupe, user-entries-first,
        # idempotence) in one tested place instead of in two shell scripts.
        detection = read_status(_read_status_file(args.status_json) if args.status_json else None)
        if detection.identity is None or not publish_enabled():
            print(args.merge_into)
            return 0
        print(merge_origins(args.merge_into, tailnet_origins(detection.identity, args.port, include_serve=not args.no_serve_origin)))
        return 0

    status_json = _read_status_file(args.status_json) if args.status_json else None
    detection = read_status(status_json)
    if not publish_enabled():
        print(f"detect_tailscale: {ENV_PUBLISH_TOGGLE} is off; not publishing on the tailnet", file=sys.stderr)
        if args.format == "json":
            print(json.dumps({"present": False, "reason": "disabled"}))
        return 0

    if detection.identity is None:
        for note in detection.notes:
            print(f"detect_tailscale: {note}", file=sys.stderr)
        if args.format == "json":
            print(json.dumps({"present": False, "notes": detection.notes}))
        return 0

    identity = detection.identity
    origins = tailnet_origins(identity, args.port, include_serve=not args.no_serve_origin)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "present": True,
                    "ipv4": identity.ipv4,
                    "ipv6": identity.ipv6,
                    "magic_dns": identity.magic_dns,
                    "origins": origins,
                }
            )
        )
    else:
        print(_emit_env(identity, origins))
    return 0


if __name__ == "__main__":
    sys.exit(main())
