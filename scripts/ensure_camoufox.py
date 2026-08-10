#!/usr/bin/env python3
"""Ensure the Camoufox browser binaries are present when the camoufox extra is installed.

Run *inside the backend virtualenv* so the ``camoufox`` import resolves, e.g.::

    cd backend && uv run python ../scripts/ensure_camoufox.py

Idempotent and best-effort — it never blocks startup:

- If the ``camoufox`` package is not importable, the camoufox ``web_fetch``
  backend was not selected (``scripts/detect_uv_extras.py`` only adds the
  ``camoufox`` uv extra when ``config.yaml`` points ``web_fetch`` at it), so
  there is nothing to do.
- If the browser binaries are already downloaded (camoufox writes a
  ``version.json`` into its install dir on ``camoufox fetch``), do nothing.
- Otherwise download them via ``python -m camoufox fetch``. A failure (e.g. no
  network) is logged, not raised, so the tool can still surface its actionable
  install hint at call time instead of crashing the launcher.

This mirrors the browser-presence probe in
``deerflow.community.camoufox_fetch.browser._camoufox_browser_present`` so the
launch-time check and the runtime check agree.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def browser_install_dir() -> Path | None:
    """Return camoufox's browser install dir, or None if it can't be resolved."""
    from camoufox import pkgman

    install_dir = getattr(pkgman, "INSTALL_DIR", None)
    if install_dir is None:
        return None
    return Path(str(install_dir))


def browser_present(install_dir: Path | None) -> bool:
    """Whether the camoufox browser binaries have been fetched into ``install_dir``."""
    if install_dir is None:
        return False
    return (install_dir / "version.json").exists()


def main() -> int:
    try:
        import camoufox  # noqa: F401
    except ImportError:
        # camoufox extra not installed -> backend not selected. Nothing to do.
        return 0

    try:
        install_dir = browser_install_dir()
    except Exception as exc:  # noqa: BLE001 - never let the probe block startup
        print(f"[camoufox] could not resolve install dir: {exc}", file=sys.stderr)
        install_dir = None

    if browser_present(install_dir):
        print("[camoufox] browser binaries already present")
        return 0

    print("[camoufox] downloading browser binaries (first run; large download)...", file=sys.stderr)
    try:
        rc = subprocess.call([sys.executable, "-m", "camoufox", "fetch"])
    except Exception as exc:  # noqa: BLE001 - best-effort; do not block startup
        print(f"[camoufox] fetch failed to launch: {exc}", file=sys.stderr)
        return 0
    if rc != 0:
        print(
            "[camoufox] fetch failed; the camoufox web_fetch backend will error until 'make fetch-browser' succeeds",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
