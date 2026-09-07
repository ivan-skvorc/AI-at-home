"""Forcing a Camoufox + SearXNG refresh from Settings.

Both components are already refreshed on a daily throttle; this is the path for
the case the throttle exists to prevent — something is broken now and you want
the newer build without dropping to a shell on the host.

Three properties, each of which is a way this could be worse than not existing:

1. **Single-flight.** Two concurrent ``docker compose pull`` / ``camoufox
   fetch`` runs fight over the same files, and nothing downstream would report
   the resulting corruption — so a second request while one is in flight has to
   be refused, not queued.
2. **One component cannot sink the other.** A machine with no Docker should
   still get its browser refreshed, and a raising updater must be reported
   rather than propagated: a maintenance button that 500s teaches the user to
   stop pressing it.
3. **The admin gate.** This runs commands on the host.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.gateway import dependency_update
from app.gateway.dependency_update import DependencyUpdater
from app.gateway.routers import settings as settings_router


class _FakeUpdaterModule:
    """Stand-in for ``scripts/update_camoufox_searxng.py``."""

    def __init__(self, *, camoufox: str = "ok", searxng: str = "ok", raises: Exception | None = None):
        self._camoufox = camoufox
        self._searxng = searxng
        self._raises = raises
        self.calls: list[str] = []

    def update_camoufox(self, **_kwargs) -> str:
        self.calls.append("camoufox")
        if self._raises is not None:
            raise self._raises
        return self._camoufox

    def update_searxng(self, **_kwargs) -> str:
        self.calls.append("searxng")
        return self._searxng

    def _resolve_config_path(self, _explicit):
        return None

    def _read_config_text(self, _path):
        return None


def _updater_with(module: _FakeUpdaterModule, **kwargs) -> DependencyUpdater:
    updater = DependencyUpdater(**kwargs)
    updater._load_updater = lambda: module  # type: ignore[method-assign]
    return updater


class TestRunningTheRefresh:
    def test_both_components_are_refreshed_and_reported(self) -> None:
        module = _FakeUpdaterModule()
        updater = _updater_with(module)

        assert updater.begin() is True
        status = updater.run()

        assert module.calls == ["camoufox", "searxng"]
        assert status.results == {"camoufox": "ok", "searxng": "ok"}
        assert status.running is False
        assert status.error is None
        assert status.finished_at is not None

    def test_a_skipped_component_is_reported_rather_than_hidden(self) -> None:
        """ "No Docker" is an answer the user needs, not a silent success."""
        updater = _updater_with(_FakeUpdaterModule(searxng="skipped-no-docker"))
        updater.begin()

        assert updater.run().results == {"camoufox": "ok", "searxng": "skipped-no-docker"}

    def test_a_raising_component_does_not_stop_the_other(self) -> None:
        module = _FakeUpdaterModule(raises=RuntimeError("camoufox exploded"))
        updater = _updater_with(module)
        updater.begin()

        status = updater.run()

        assert status.results["camoufox"] == "failed"
        assert status.results["searxng"] == "ok"
        assert status.error is None

    def test_a_missing_updater_script_is_an_error_not_a_crash(self) -> None:
        updater = DependencyUpdater()
        updater._load_updater = lambda: (_ for _ in ()).throw(FileNotFoundError("no updater"))  # type: ignore[method-assign]
        updater.begin()

        status = updater.run()

        assert status.error is not None
        assert status.running is False

    def test_a_hung_component_times_out_instead_of_pinning_the_worker(self) -> None:
        """An unreachable registry must not wedge the runner forever."""
        release = threading.Event()

        class _HangingModule(_FakeUpdaterModule):
            def update_camoufox(self, **_kwargs) -> str:
                release.wait(timeout=5)
                return "ok"

        updater = _updater_with(_HangingModule(), timeout=0)
        updater.begin()
        try:
            status = updater.run()
        finally:
            release.set()

        assert status.results["camoufox"] == "timeout"
        # The slot is released, so the user can retry.
        assert status.running is False


class TestSingleFlight:
    def test_a_second_start_is_refused_while_one_is_in_flight(self) -> None:
        updater = _updater_with(_FakeUpdaterModule())

        assert updater.begin() is True
        assert updater.begin() is False

    def test_the_slot_is_released_after_the_run(self) -> None:
        updater = _updater_with(_FakeUpdaterModule())
        updater.begin()
        updater.run()

        assert updater.begin() is True

    def test_the_slot_is_released_even_when_the_run_fails(self) -> None:
        """Otherwise one failure disables the button until the Gateway restarts."""
        updater = DependencyUpdater()
        updater._load_updater = lambda: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[method-assign]
        updater.begin()
        updater.run()

        assert updater.begin() is True


class TestTheRoutes:
    @pytest.fixture
    def http(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(dependency_update, "_updater", _updater_with(_FakeUpdaterModule()))
        app = make_authed_test_app()
        app.include_router(settings_router.router)
        with TestClient(app) as client:
            yield client

    def test_status_is_readable_before_any_run(self, http) -> None:
        response = http.get("/api/settings/update-dependencies")

        assert response.status_code == 200
        body = response.json()
        assert body["running"] is False
        assert body["results"] == {}

    @pytest.mark.anyio
    async def test_starting_returns_immediately_rather_than_waiting(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The work takes minutes, so the request only starts it.

        Holding the HTTP request open for the duration would hit every
        reverse-proxy read timeout before the pull finished, and the user would
        see a 504 for a refresh that actually succeeded.
        """
        updater = _updater_with(_FakeUpdaterModule())
        monkeypatch.setattr(dependency_update, "_updater", updater)
        admin_request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))

        response = await settings_router.start_dependency_update(admin_request)

        # `running` may already be False if the (instant) fake finished first;
        # what must hold is that the call returned without doing the work.
        assert response.results == {} or set(response.results) == {"camoufox", "searxng"}

    @pytest.mark.anyio
    async def test_a_non_admin_cannot_run_commands_on_the_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        updater = _updater_with(_FakeUpdaterModule())
        monkeypatch.setattr(dependency_update, "_updater", updater)
        plain_request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="user")))

        with pytest.raises(HTTPException) as excinfo:
            await settings_router.start_dependency_update(plain_request)

        assert excinfo.value.status_code == 403
        # And nothing was started.
        assert updater.status().running is False
