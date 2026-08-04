#!/usr/bin/env python3
"""Install (or remove) a daily systemd **user** timer that runs the Camoufox +
SearXNG auto-update loop (``scripts/update_camoufox_searxng.py``).

This is the "daily automatically ran update loop": a ``systemd --user`` timer
that fires once a day (with a randomized delay and ``Persistent=true`` so a
missed run catches up after downtime) and runs the updater inside the backend
virtualenv via ``uv run``. systemd is the idiomatic scheduler on this fork's
target (Arch / CachyOS), and a *user* timer needs no root.

    make auto-update-install     # install + enable + start the timer
    make auto-update-uninstall   # stop + disable + remove the units
    systemctl --user list-timers deer-flow-auto-update.timer

On a machine without ``systemd --user`` (macOS, non-systemd Linux, containers),
installation prints an equivalent ``cron`` line instead of failing.

The unit *content* is produced by the pure ``service_unit`` / ``timer_unit``
helpers so it can be unit-tested without touching the real systemd tree.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UNIT_NAME = "deer-flow-auto-update"
SERVICE_FILE = f"{UNIT_NAME}.service"
TIMER_FILE = f"{UNIT_NAME}.timer"


def user_unit_dir() -> Path:
    """~/.config/systemd/user, honoring XDG_CONFIG_HOME."""
    base = os.environ.get("XDG_CONFIG_HOME", "").strip() or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def _uv_path() -> str:
    return shutil.which("uv") or "uv"


def service_unit(repo_root: Path, uv: str) -> str:
    """systemd .service content — a oneshot that runs the updater via uv."""
    backend = repo_root / "backend"
    updater = repo_root / "scripts" / "update_camoufox_searxng.py"
    return f"""\
[Unit]
Description=DeerFlow: update Camoufox browser + bundled SearXNG image
Documentation=file://{repo_root / "FORK.md"}
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={backend}
ExecStart={uv} run python {updater} --verbose
# Best-effort: a failed update must never mark the unit as failed and spam the
# journal — the updater already logs and swallows its own errors.
SuccessExitStatus=0 1
"""


def timer_unit() -> str:
    """systemd .timer content — daily, jittered, catches up missed runs."""
    return f"""\
[Unit]
Description=DeerFlow: daily Camoufox + SearXNG auto-update
Documentation=file://{REPO_ROOT / "FORK.md"}

[Timer]
OnCalendar=daily
# Spread the run out so a fleet of machines does not hammer the registries at
# midnight, and run a missed timer after the machine was off.
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
"""


def cron_line() -> str:
    updater = REPO_ROOT / "scripts" / "update_camoufox_searxng.py"
    backend = REPO_ROOT / "backend"
    uv = _uv_path()
    # A daily cron entry, quiet on success. Randomized minute keeps it off :00.
    return f"17 4 * * *  cd {backend} && {uv} run python {updater} >/dev/null 2>&1"


def _systemctl_user_available() -> bool:
    if shutil.which("systemctl") is None:
        return False
    try:
        # `systemctl --user` needs a running user manager (a session bus).
        result = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _systemctl(*args: str) -> int:
    return subprocess.call(["systemctl", "--user", *args])


def install() -> int:
    if not _systemctl_user_available():
        print("systemd --user is not available on this machine.", file=sys.stderr)
        print("Add this line to your crontab instead (`crontab -e`) for a daily run:", file=sys.stderr)
        print(f"\n    {cron_line()}\n", file=sys.stderr)
        return 1

    unit_dir = user_unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / SERVICE_FILE).write_text(service_unit(REPO_ROOT, _uv_path()), encoding="utf-8")
    (unit_dir / TIMER_FILE).write_text(timer_unit(), encoding="utf-8")
    print(f"✓ Wrote {unit_dir / SERVICE_FILE}")
    print(f"✓ Wrote {unit_dir / TIMER_FILE}")

    _systemctl("daemon-reload")
    rc = _systemctl("enable", "--now", TIMER_FILE)
    if rc != 0:
        print("✗ Could not enable the timer; see the output above.", file=sys.stderr)
        return rc

    print("✓ Enabled and started the daily auto-update timer.")
    print("  Check it with:  systemctl --user list-timers deer-flow-auto-update.timer")
    print("  Run it now:     systemctl --user start deer-flow-auto-update.service")
    print("  Tip: `loginctl enable-linger` keeps the timer running when you are logged out.")
    return 0


def uninstall() -> int:
    if _systemctl_user_available():
        _systemctl("disable", "--now", TIMER_FILE)
        _systemctl("daemon-reload")

    unit_dir = user_unit_dir()
    removed = False
    for name in (TIMER_FILE, SERVICE_FILE):
        path = unit_dir / name
        try:
            path.unlink()
            print(f"✓ Removed {path}")
            removed = True
        except FileNotFoundError:
            pass
        except OSError as exc:  # noqa: BLE001
            print(f"✗ Could not remove {path}: {exc}", file=sys.stderr)
    if not removed:
        print("Nothing to remove (units were not installed).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uninstall", action="store_true", help="stop, disable, and remove the timer units")
    parser.add_argument("--print", dest="print_units", action="store_true", help="print the unit files and exit (no changes)")
    args = parser.parse_args(argv)

    if args.print_units:
        print(f"# {SERVICE_FILE}\n{service_unit(REPO_ROOT, _uv_path())}")
        print(f"# {TIMER_FILE}\n{timer_unit()}")
        return 0
    if args.uninstall:
        return uninstall()
    return install()


if __name__ == "__main__":
    sys.exit(main())
