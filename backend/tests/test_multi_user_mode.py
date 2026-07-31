"""Multi-user mode (fork feature): per-user thread isolation, toggleable off.

Default ON = each login sees only its own conversations (upstream behavior).
OFF = one shared workspace: thread listing and per-thread access ignore the
owner filter, so every conversation is visible regardless of which login
created it. Writes still stamp the real owner so turning it back ON restores
isolation cleanly.
"""

from __future__ import annotations

import pytest

from deerflow.config import runtime_settings
from deerflow.runtime.user_context import AUTO, reset_current_user, set_current_user


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Point the runtime-settings store at a temp file and clear its cache."""
    path = tmp_path / "runtime_settings.json"
    monkeypatch.setattr(runtime_settings, "_settings_path", lambda: path)
    runtime_settings.reset_cache_for_tests()
    yield path
    runtime_settings.reset_cache_for_tests()


class _FakeUser:
    def __init__(self, user_id: str) -> None:
        self.id = user_id


class TestRuntimeSettings:
    def test_defaults_to_multi_user_mode_on(self, settings_file):
        # No file yet -> per-user isolation is the default.
        assert not settings_file.exists()
        assert runtime_settings.is_multi_user_mode_enabled() is True

    def test_set_and_get_roundtrip(self, settings_file):
        runtime_settings.set_multi_user_mode(False)
        assert runtime_settings.is_multi_user_mode_enabled() is False
        runtime_settings.set_multi_user_mode(True)
        assert runtime_settings.is_multi_user_mode_enabled() is True

    def test_resolve_owner_scope_on_uses_real_user(self, settings_file):
        # ON: explicit id passes through; AUTO resolves the request user.
        assert runtime_settings.resolve_owner_scope("user-1") == "user-1"
        token = set_current_user(_FakeUser("ctx-user"))
        try:
            assert runtime_settings.resolve_owner_scope(AUTO) == "ctx-user"
        finally:
            reset_current_user(token)

    def test_resolve_owner_scope_off_bypasses(self, settings_file):
        # OFF: always None (no owner filter), even without any user context.
        runtime_settings.set_multi_user_mode(False)
        assert runtime_settings.resolve_owner_scope("user-1") is None
        assert runtime_settings.resolve_owner_scope(AUTO) is None


@pytest.fixture
async def repo(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.thread_meta import ThreadMetaRepository

    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    yield ThreadMetaRepository(get_session_factory())
    await close_engine()


class TestThreadMetaMultiUserMode:
    @pytest.mark.anyio
    async def test_on_isolates_by_owner(self, repo, settings_file):
        # Two conversations under different logins (the phone/PC split shape).
        await repo.create("t-alice", user_id="alice", display_name="Alice chat")
        await repo.create("t-bob", user_id="bob", display_name="Bob chat")

        alice_threads = await repo.search(user_id="alice")
        assert {t["thread_id"] for t in alice_threads} == {"t-alice"}

        # Cross-owner reads/access are denied while multi-user mode is ON.
        assert await repo.get("t-bob", user_id="alice") is None
        assert await repo.check_access("t-bob", "alice") is False

    @pytest.mark.anyio
    async def test_off_shows_all_regardless_of_login(self, repo, settings_file):
        await repo.create("t-alice", user_id="alice", display_name="Alice chat")
        await repo.create("t-bob", user_id="bob", display_name="Bob chat")

        runtime_settings.set_multi_user_mode(False)

        # The list shows every conversation regardless of who asks.
        seen = {t["thread_id"] for t in await repo.search(user_id="alice")}
        assert seen == {"t-alice", "t-bob"}

        # And any thread can be opened/accessed by anyone.
        assert (await repo.get("t-bob", user_id="alice"))["thread_id"] == "t-bob"
        assert await repo.check_access("t-bob", "alice") is True
        # require_existing safety still holds: a missing thread is not accessible.
        assert await repo.check_access("does-not-exist", "alice", require_existing=True) is False

    @pytest.mark.anyio
    async def test_off_still_stamps_real_owner_on_create(self, repo, settings_file):
        # Writes keep the real owner so re-enabling isolation restores cleanly.
        runtime_settings.set_multi_user_mode(False)
        record = await repo.create("t-new", user_id="carol", display_name="Carol chat")
        assert record["user_id"] == "carol"

        runtime_settings.set_multi_user_mode(True)
        assert {t["thread_id"] for t in await repo.search(user_id="carol")} == {"t-new"}
        assert await repo.search(user_id="dave") == []


class TestSettingsRouter:
    @pytest.mark.anyio
    async def test_get_returns_current_value(self, settings_file):
        from app.gateway.routers.settings import get_multi_user_mode_setting

        assert (await get_multi_user_mode_setting()).multi_user_mode is True
        runtime_settings.set_multi_user_mode(False)
        assert (await get_multi_user_mode_setting()).multi_user_mode is False

    @pytest.mark.anyio
    async def test_admin_can_toggle(self, settings_file):
        from types import SimpleNamespace

        from app.gateway.routers.settings import MultiUserModeUpdate, update_multi_user_mode_setting

        admin_request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
        resp = await update_multi_user_mode_setting(MultiUserModeUpdate(enabled=False), admin_request)
        assert resp.multi_user_mode is False
        assert runtime_settings.is_multi_user_mode_enabled() is False

    @pytest.mark.anyio
    async def test_non_admin_cannot_toggle(self, settings_file):
        from types import SimpleNamespace

        from fastapi import HTTPException

        from app.gateway.routers.settings import MultiUserModeUpdate, update_multi_user_mode_setting

        user_request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="user")))
        with pytest.raises(HTTPException) as exc_info:
            await update_multi_user_mode_setting(MultiUserModeUpdate(enabled=False), user_request)
        assert exc_info.value.status_code == 403
        # The rejected write must not have changed the setting.
        assert runtime_settings.is_multi_user_mode_enabled() is True
