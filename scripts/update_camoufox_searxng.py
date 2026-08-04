#!/usr/bin/env python3
"""Daily auto-update loop for the two components this repo installs itself:
the Camoufox browser binaries and the bundled SearXNG Docker image.

Neither self-updates otherwise, which is the gap this script closes:

- ``scripts/ensure_camoufox.py`` only *fetches when absent* (it short-circuits
  as soon as camoufox's ``version.json`` exists), so a newer browser build — for
  an updated ``camoufox`` package, or a re-published build for the pinned one —
  is never pulled after the first download. ``camoufox fetch`` is itself
  version-aware: it compares the installed browser against the expected version
  and re-downloads only when they differ, so running it unconditionally *is* the
  update (a no-op when already current).

- the bundled SearXNG runs ``docker.io/searxng/searxng:latest``, but Docker only
  pulls ``:latest`` when the image is missing locally — a long-running stack
  keeps whatever image it started with indefinitely. ``docker compose pull``
  fetches the newest published image and ``up -d`` recreates the container only
  when the image actually changed.

Meant to run daily (systemd timer / cron — see ``make auto-update-install``) and
also invoked, throttled, from the local launch path. Idempotent and best-effort:
an already-current component is a no-op, and any failure is logged rather than
raised, so a scheduled or launch-time run never wedges.

Run it inside the backend virtualenv so the ``camoufox`` import resolves, e.g.::

    cd backend && uv run python ../scripts/update_camoufox_searxng.py --verbose
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SEARXNG_SH = REPO_ROOT / "scripts" / "searxng.sh"
DEFAULT_STAMP = REPO_ROOT / ".deer-flow" / "auto-update.stamp"


def log(message: str) -> None:
    print(f"[auto-update] {message}", file=sys.stderr)


# --- detect_searxng reuse ---------------------------------------------------
# The SearXNG "do we own this instance?" logic already lives in
# scripts/detect_searxng.py; import it by path so the two scripts cannot drift
# on the config-marker check, the in-network URL, and the loopback host set.


def _load_detect_searxng():
    path = REPO_ROOT / "scripts" / "detect_searxng.py"
    spec = importlib.util.spec_from_file_location("detect_searxng", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_detect = _load_detect_searxng()


# --- Camoufox ---------------------------------------------------------------


def camoufox_installed() -> bool:
    """Whether the optional ``camoufox`` package is importable (extra selected)."""
    return importlib.util.find_spec("camoufox") is not None


def update_camoufox(
    *,
    installed: Callable[[], bool] = camoufox_installed,
    run: Callable[[list[str]], int] = subprocess.call,
    dry_run: bool = False,
    verbose: bool = False,
) -> str:
    """Refresh the Camoufox browser binaries to the version the package expects.

    Returns one of: ``"skipped"`` (camoufox extra not installed — the backend
    was not selected, nothing to update), ``"would-update"`` (dry run),
    ``"ok"`` (``camoufox fetch`` succeeded — a no-op when already current), or
    ``"failed"`` (fetch launched but returned non-zero).
    """
    if not installed():
        if verbose:
            log("camoufox not installed; skipping (web_fetch backend not selected)")
        return "skipped"
    if dry_run:
        log("would run 'python -m camoufox fetch' to refresh the browser binaries")
        return "would-update"
    log("refreshing Camoufox browser binaries (camoufox fetch)...")
    try:
        rc = run([sys.executable, "-m", "camoufox", "fetch"])
    except Exception as exc:  # noqa: BLE001 - best-effort; never raise
        log(f"camoufox fetch failed to launch: {exc}")
        return "failed"
    if rc != 0:
        log("camoufox fetch returned non-zero; browser binaries left unchanged")
        return "failed"
    log("Camoufox browser binaries are up to date")
    return "ok"


# --- SearXNG ----------------------------------------------------------------


def should_update_searxng(config_text: str | None, env: Mapping[str, str]) -> bool:
    """Whether the bundled SearXNG image is ours to keep current.

    True when config uses the SearXNG ``web_search`` provider and the operator
    has NOT pointed ``DEER_FLOW_SEARXNG_BASE_URL`` at a foreign instance they run
    themselves. This is deliberately narrower than ``detect_searxng.resolve()``
    (which answers "where should the gateway point", and treats even our own
    running container as ``external`` on the host path): here we only ever touch
    the repo's own ``deer-flow-searxng`` container, so we skip only when the
    provider is unused or the user manages their own remote instance.
    """
    if config_text is not None and not _detect.config_uses_searxng(config_text):
        return False
    explicit = env.get(_detect.ENV_VAR, "").strip()
    if explicit and explicit != _detect.IN_NETWORK_URL and not _detect.is_loopback_url(explicit):
        # A non-loopback, non-in-network URL is the operator's own instance.
        return False
    return True


def update_searxng(
    *,
    config_text: str | None,
    env: Mapping[str, str],
    run_searxng_sh: Callable[[str], int] | None = None,
    docker_available: Callable[[], bool] = lambda: shutil.which("docker") is not None,
    dry_run: bool = False,
    verbose: bool = False,
) -> str:
    """Pull the latest bundled SearXNG image and recreate it if it is running.

    Returns one of: ``"skipped"`` (provider unused or a foreign instance is
    configured), ``"skipped-no-docker"`` (Docker CLI absent), ``"would-update"``
    (dry run), ``"ok"``, or ``"failed"``.
    """
    if not should_update_searxng(config_text, env):
        if verbose:
            log("SearXNG provider not used (or a foreign instance is configured); skipping")
        return "skipped"
    if not docker_available():
        log("Docker CLI not found; cannot refresh the bundled SearXNG image (skipping)")
        return "skipped-no-docker"
    if dry_run:
        log("would run 'scripts/searxng.sh update' (docker compose pull + recreate-if-running)")
        return "would-update"
    if run_searxng_sh is None:
        run_searxng_sh = _default_searxng_runner
    log("refreshing the bundled SearXNG image (docker compose pull)...")
    try:
        rc = run_searxng_sh("update")
    except Exception as exc:  # noqa: BLE001 - best-effort; never raise
        log(f"SearXNG update failed to launch: {exc}")
        return "failed"
    if rc != 0:
        log("SearXNG update returned non-zero (Docker daemon down?); image left unchanged")
        return "failed"
    log("Bundled SearXNG image is up to date")
    return "ok"


def _default_searxng_runner(command: str) -> int:
    return subprocess.call([str(SEARXNG_SH), command])


# --- Throttle (for the launch-time hook) ------------------------------------


def is_stale(stamp: Path, max_age_hours: float, *, now: float | None = None) -> bool:
    """True when ``stamp`` is missing or older than ``max_age_hours``."""
    if now is None:
        now = time.time()
    try:
        mtime = stamp.stat().st_mtime
    except OSError:
        return True
    return (now - mtime) >= max_age_hours * 3600.0


def touch_stamp(stamp: Path, *, now: float | None = None) -> None:
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text("", encoding="utf-8")
        if now is not None:
            os.utime(stamp, (now, now))
    except OSError as exc:  # noqa: BLE001 - never let a stamp write block startup
        log(f"could not write throttle stamp {stamp}: {exc}")


# --- CLI --------------------------------------------------------------------


def _read_config_text(config_path: Path | None) -> str | None:
    if config_path is None:
        return None
    try:
        return config_path.read_text(encoding="utf-8")
    except OSError:
        return None  # unreadable config → don't skip on the marker check


def _resolve_config_path(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit
    env_path = os.environ.get("DEER_FLOW_CONFIG_PATH", "").strip()
    if env_path and Path(env_path).is_file():
        return Path(env_path)
    for candidate in (REPO_ROOT / "backend" / "config.yaml", REPO_ROOT / "config.yaml"):
        if candidate.is_file():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camoufox-only", action="store_true", help="only refresh the Camoufox browser")
    parser.add_argument("--searxng-only", action="store_true", help="only refresh the bundled SearXNG image")
    parser.add_argument("--dry-run", action="store_true", help="print what would happen without changing anything")
    parser.add_argument("--verbose", action="store_true", help="log skipped components too")
    parser.add_argument("--config", type=Path, default=None, help="path to config.yaml (defaults to the repo/backend copy)")
    parser.add_argument(
        "--if-stale",
        type=float,
        default=None,
        metavar="HOURS",
        help="only run when the throttle stamp is missing or older than HOURS (used by the launch hook)",
    )
    parser.add_argument("--stamp", type=Path, default=DEFAULT_STAMP, help="throttle stamp file for --if-stale")
    args = parser.parse_args(argv)

    if args.if_stale is not None and not is_stale(args.stamp, args.if_stale):
        if args.verbose:
            log(f"last run was under {args.if_stale}h ago; skipping (throttled)")
        return 0

    do_camoufox = not args.searxng_only
    do_searxng = not args.camoufox_only

    if do_camoufox:
        update_camoufox(dry_run=args.dry_run, verbose=args.verbose)

    if do_searxng:
        config_text = _read_config_text(_resolve_config_path(args.config))
        update_searxng(config_text=config_text, env=os.environ, dry_run=args.dry_run, verbose=args.verbose)

    # Stamp on every real (non-dry-run) run so the launch throttle advances even
    # when both components were no-ops or skipped — the intent is "checked today".
    if not args.dry_run:
        touch_stamp(args.stamp)

    return 0


if __name__ == "__main__":
    sys.exit(main())
