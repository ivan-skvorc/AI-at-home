"""Gateway routes for the durable keep-alive chat tab strip (fork feature).

``GET``/``PUT /api/settings/chat-tabs`` back the tab strip with per-user
server-side storage so a pinned set survives a machine restart, a browser data
clear, and an origin change — none of which ``localStorage`` alone survives.
Unlike the sibling multi-user-mode routes these are per-user UI state, so they
are scoped to the caller and carry no admin gate.
"""

from __future__ import annotations

import pytest

from app.gateway.routers.settings import (
    ChatTab,
    ChatTabsUpdate,
    get_chat_tabs_setting,
    update_chat_tabs_setting,
)
from deerflow.config import paths as paths_module
from deerflow.config import user_ui_state
from deerflow.runtime import user_context


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_module, "_paths", None)
    user_ui_state.reset_cache_for_tests()
    yield
    monkeypatch.setattr(paths_module, "_paths", None)
    user_ui_state.reset_cache_for_tests()


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _User:
    def __init__(self, user_id: str) -> None:
        self.id = user_id


@pytest.mark.anyio
async def test_get_defaults_to_empty():
    assert (await get_chat_tabs_setting()).chat_tabs == []


@pytest.mark.anyio
async def test_put_then_get_round_trips():
    await update_chat_tabs_setting(
        ChatTabsUpdate(chat_tabs=[ChatTab(key="k1", threadId="t1", title="Alpha"), ChatTab(key="k2", threadId="t2")]),
    )

    # Cold cache: this is the "reopened after a restart" read.
    user_ui_state.reset_cache_for_tests()
    tabs = (await get_chat_tabs_setting()).chat_tabs
    assert [(t.key, t.threadId, t.title) for t in tabs] == [("k1", "t1", "Alpha"), ("k2", "t2", None)]


@pytest.mark.anyio
async def test_put_returns_the_normalized_persisted_value():
    """The response is authoritative: the client adopts what actually stored."""
    resp = await update_chat_tabs_setting(
        ChatTabsUpdate(
            chat_tabs=[
                ChatTab(key="k1", threadId="t1"),
                ChatTab(key="k1", threadId="t9"),  # duplicate key collapses
                ChatTab(key="k2", threadId="t1"),  # duplicate thread collapses
                ChatTab(key="k3", threadId="t3"),
            ],
        ),
    )
    assert [(t.key, t.threadId) for t in resp.chat_tabs] == [("k1", "t1"), ("k3", "t3")]


@pytest.mark.anyio
async def test_put_caps_an_oversized_list():
    resp = await update_chat_tabs_setting(
        ChatTabsUpdate(chat_tabs=[ChatTab(key=f"k{i}", threadId=f"t{i}") for i in range(50)]),
    )
    assert len(resp.chat_tabs) == user_ui_state.MAX_CHAT_TABS


@pytest.mark.anyio
async def test_empty_put_clears_the_stored_set():
    await update_chat_tabs_setting(ChatTabsUpdate(chat_tabs=[ChatTab(key="k1", threadId="t1")]))
    assert (await update_chat_tabs_setting(ChatTabsUpdate(chat_tabs=[]))).chat_tabs == []
    user_ui_state.reset_cache_for_tests()
    assert (await get_chat_tabs_setting()).chat_tabs == []


@pytest.mark.anyio
async def test_tabs_are_scoped_to_the_calling_user():
    token = user_context._current_user.set(_User("alice"))
    try:
        await update_chat_tabs_setting(ChatTabsUpdate(chat_tabs=[ChatTab(key="ka", threadId="ta")]))
    finally:
        user_context._current_user.reset(token)

    token = user_context._current_user.set(_User("bob"))
    try:
        assert (await get_chat_tabs_setting()).chat_tabs == []
        await update_chat_tabs_setting(ChatTabsUpdate(chat_tabs=[ChatTab(key="kb", threadId="tb")]))
    finally:
        user_context._current_user.reset(token)

    token = user_context._current_user.set(_User("alice"))
    try:
        tabs = (await get_chat_tabs_setting()).chat_tabs
        assert [t.threadId for t in tabs] == ["ta"]
    finally:
        user_context._current_user.reset(token)


@pytest.mark.anyio
async def test_identity_outside_the_directory_charset_is_accepted():
    """An email-shaped identity must not blow up per-user path resolution."""
    token = user_context._current_user.set(_User("someone@example.com"))
    try:
        await update_chat_tabs_setting(ChatTabsUpdate(chat_tabs=[ChatTab(key="k1", threadId="t1")]))
        assert [t.threadId for t in (await get_chat_tabs_setting()).chat_tabs] == ["t1"]
    finally:
        user_context._current_user.reset(token)
