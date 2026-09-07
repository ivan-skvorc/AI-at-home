"""Force a refresh of the two components this repo installs for itself.

Neither self-updates: ``camoufox fetch`` only re-downloads when the installed
browser differs from the one the package expects, and Docker only pulls
``searxng:latest`` when the image is missing locally — so a long-running stack
keeps whatever it started with. ``scripts/update_camoufox_searxng.py`` closes
that gap on a daily timer and on launch (throttled). This module is the
*on-demand* path behind the Settings button, for the case the throttle exists to
prevent you from hitting: something is broken now and you want the newer build
now, without dropping to a shell on the host.

Three properties this has to hold, and each is a way it could be worse than not
existing at all:

* **Single-flight.** Two concurrent ``docker compose pull``/``camoufox fetch``
  runs fight over the same files. A second request while one is in flight is
  told so rather than started.
* **Off the event loop.** Both halves are blocking subprocess work measured in
  minutes; they run in a worker thread, and the HTTP request that starts them
  returns immediately. The caller polls for the outcome.
* **No caller input.** The work is a fixed pair of actions with no parameters —
  nothing from the request reaches a command line. The endpoint is admin-gated
  on top of that, because this runs commands on the host.
"""

from __future__ import annotations

import importlib.util
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# backend/app/gateway/dependency_update.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
UPDATER_PATH = REPO_ROOT / "scripts" / "update_camoufox_searxng.py"

# Both halves shell out; a hung `docker pull` (unreachable registry, dead
# daemon) must not pin the worker thread forever. The updater itself has no
# timeout, so this is the only bound there is.
COMPONENT_TIMEOUT_SECONDS = 900


@dataclass
class DependencyUpdateStatus:
    """What the last (or current) refresh is doing, in one JSON-able shape."""

    running: bool = False
    #: Epoch seconds when the last completed run finished; ``None`` until then.
    finished_at: float | None = None
    started_at: float | None = None
    #: Per component: one of the updater's own outcome strings, e.g. ``"ok"``,
    #: ``"skipped"``, ``"skipped-no-docker"``, ``"failed"``, ``"timeout"``.
    results: dict[str, str] = field(default_factory=dict)
    #: Set when the run could not be attempted at all (updater missing, etc).
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DependencyUpdater:
    """Single-flight runner for the on-demand dependency refresh."""

    def __init__(self, *, updater_path: Path = UPDATER_PATH, timeout: int = COMPONENT_TIMEOUT_SECONDS) -> None:
        self._updater_path = updater_path
        self._timeout = timeout
        self._lock = threading.Lock()
        self._status = DependencyUpdateStatus()

    def status(self) -> DependencyUpdateStatus:
        with self._lock:
            return DependencyUpdateStatus(
                running=self._status.running,
                finished_at=self._status.finished_at,
                started_at=self._status.started_at,
                results=dict(self._status.results),
                error=self._status.error,
            )

    def begin(self) -> bool:
        """Claim the single-flight slot. False when a run is already in flight."""
        with self._lock:
            if self._status.running:
                return False
            self._status = DependencyUpdateStatus(running=True, started_at=time.time())
            return True

    def run(self) -> DependencyUpdateStatus:
        """Do the work. Call only after :meth:`begin` returned True."""
        results: dict[str, str] = {}
        error: str | None = None
        try:
            updater = self._load_updater()
            results["camoufox"] = self._run_component(lambda: updater.update_camoufox(verbose=True))
            results["searxng"] = self._run_component(
                lambda: updater.update_searxng(
                    config_text=self._config_text(updater),
                    env=self._env(),
                    verbose=True,
                )
            )
        except Exception as exc:  # noqa: BLE001 - reported to the caller, never raised
            logger.warning("dependency update could not run", exc_info=True)
            error = str(exc)
        finally:
            with self._lock:
                self._status = DependencyUpdateStatus(
                    running=False,
                    started_at=self._status.started_at,
                    finished_at=time.time(),
                    results=results,
                    error=error,
                )
        return self.status()

    def _run_component(self, work: Any) -> str:
        """Run one component's update, bounding it and never raising.

        A component that fails is reported as ``"failed"`` and the other one
        still runs: a machine with no Docker should still get its browser
        refreshed.
        """
        outcome: list[str] = []

        def target() -> None:
            try:
                outcome.append(str(work()))
            except Exception:  # noqa: BLE001 - one component must not sink the other
                logger.warning("dependency update component failed", exc_info=True)
                outcome.append("failed")

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(self._timeout)
        if thread.is_alive():
            # The worker is abandoned rather than killed — there is no safe way
            # to interrupt a subprocess mid-pull — but the caller is told, and
            # the single-flight slot is released so a retry is possible.
            return "timeout"
        return outcome[0] if outcome else "failed"

    def _load_updater(self) -> Any:
        """Import ``scripts/update_camoufox_searxng.py`` by path.

        The updater is a repo script rather than a package module, and it is
        already the single implementation the Makefile target and the launch
        hook both use. Importing it keeps this endpoint from becoming a second,
        drifting copy of the same logic.
        """
        if not self._updater_path.is_file():
            raise FileNotFoundError(f"updater script not found at {self._updater_path}")
        spec = importlib.util.spec_from_file_location("deerflow_dependency_updater", self._updater_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"could not load the updater at {self._updater_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _config_text(updater: Any) -> str | None:
        path = updater._resolve_config_path(None)
        return updater._read_config_text(path)

    @staticmethod
    def _env() -> dict[str, str]:
        import os

        return dict(os.environ)


#: Process-wide runner. Single-flight is per Gateway process, which is the same
#: scope as the host it would be updating.
_updater = DependencyUpdater()


def get_dependency_updater() -> DependencyUpdater:
    return _updater
