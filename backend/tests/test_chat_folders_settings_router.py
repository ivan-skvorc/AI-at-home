"""Gateway routes for the sidebar's chat-folder registry (fork feature).

``GET``/``PUT /api/settings/chat-folders`` store the folder list — id, name,
display order — per user, beside the keep-alive tab strip in the same
``ui_state.json`` bag. Membership is *not* here: a conversation records its
folder in its own ``deerflow_folder`` thread metadata, so a rename stays one
write. Like the sibling chat-tabs routes these are per-user UI state and carry
no admin gate.
"""

from __future__ import annotations

import pytest

from app.gateway.routers.settings import (
    ChatFolder,
    ChatFoldersUpdate,
    get_chat_folders_setting,
    update_chat_folders_setting,
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
    assert (await get_chat_folders_setting()).chat_folders == []


@pytest.mark.anyio
async def test_put_then_get_round_trips_in_display_order():
    await update_chat_folders_setting(
        ChatFoldersUpdate(chat_folders=[ChatFolder(id="f1", name="Work"), ChatFolder(id="f2", name="Personal")]),
    )

    # Cold cache: this is the "reopened after a restart" read.
    user_ui_state.reset_cache_for_tests()
    folders = (await get_chat_folders_setting()).chat_folders
    assert [(f.id, f.name) for f in folders] == [("f1", "Work"), ("f2", "Personal")]


@pytest.mark.anyio
async def test_put_returns_the_normalized_persisted_value():
    """The response is authoritative: the client adopts what actually stored."""
    resp = await update_chat_folders_setting(
        ChatFoldersUpdate(
            chat_folders=[
                ChatFolder(id="f1", name="  Work  "),
                ChatFolder(id="f1", name="Duplicate id"),  # collapses, first wins
                ChatFolder(id="f2", name="   "),  # blank name is unusable
                ChatFolder(id="f3", name="Archive"),
            ],
        ),
    )
    assert [(f.id, f.name) for f in resp.chat_folders] == [("f1", "Work"), ("f3", "Archive")]


@pytest.mark.anyio
async def test_put_caps_an_oversized_list():
    resp = await update_chat_folders_setting(
        ChatFoldersUpdate(chat_folders=[ChatFolder(id=f"f{i}", name=f"Folder {i}") for i in range(400)]),
    )
    assert len(resp.chat_folders) == user_ui_state.MAX_CHAT_FOLDERS


@pytest.mark.anyio
async def test_empty_put_clears_the_stored_list():
    await update_chat_folders_setting(ChatFoldersUpdate(chat_folders=[ChatFolder(id="f1", name="Work")]))
    assert (await update_chat_folders_setting(ChatFoldersUpdate(chat_folders=[]))).chat_folders == []
    user_ui_state.reset_cache_for_tests()
    assert (await get_chat_folders_setting()).chat_folders == []


@pytest.mark.anyio
async def test_folders_are_scoped_to_the_calling_user():
    token = user_context._current_user.set(_User("alice"))
    try:
        await update_chat_folders_setting(ChatFoldersUpdate(chat_folders=[ChatFolder(id="fa", name="Alice")]))
    finally:
        user_context._current_user.reset(token)

    token = user_context._current_user.set(_User("bob"))
    try:
        assert (await get_chat_folders_setting()).chat_folders == []
        await update_chat_folders_setting(ChatFoldersUpdate(chat_folders=[ChatFolder(id="fb", name="Bob")]))
    finally:
        user_context._current_user.reset(token)

    token = user_context._current_user.set(_User("alice"))
    try:
        assert [f.name for f in (await get_chat_folders_setting()).chat_folders] == ["Alice"]
    finally:
        user_context._current_user.reset(token)


@pytest.mark.anyio
async def test_identity_outside_the_directory_charset_is_accepted():
    """An email-shaped identity must not blow up per-user path resolution."""
    token = user_context._current_user.set(_User("someone@example.com"))
    try:
        await update_chat_folders_setting(ChatFoldersUpdate(chat_folders=[ChatFolder(id="f1", name="Work")]))
        assert [f.id for f in (await get_chat_folders_setting()).chat_folders] == ["f1"]
    finally:
        user_context._current_user.reset(token)


@pytest.mark.anyio
async def test_folders_and_tabs_share_one_file_without_clobbering_each_other():
    """Both live in ``ui_state.json``; a writer that knows one must keep the other."""
    from app.gateway.routers.settings import ChatTab, ChatTabsUpdate, get_chat_tabs_setting, update_chat_tabs_setting

    await update_chat_tabs_setting(ChatTabsUpdate(chat_tabs=[ChatTab(key="k1", threadId="t1")]))
    await update_chat_folders_setting(ChatFoldersUpdate(chat_folders=[ChatFolder(id="f1", name="Work")]))

    user_ui_state.reset_cache_for_tests()
    assert [t.threadId for t in (await get_chat_tabs_setting()).chat_tabs] == ["t1"]
    assert [f.id for f in (await get_chat_folders_setting()).chat_folders] == ["f1"]
