"""Gateway routes for the per-user automatic-rename preference (FORK.md §33).

``GET``/``PUT /api/settings/auto-title`` store Settings -> Conversation titles
per user, in the shared ``ui_state.json`` bag next to the chat folders. Run
admission reads the stored value for every run the user owns
(``test_auto_title_preference.py``), so the switch no longer depends on which
browser, origin or IM channel starts the run.

The wire keeps three model states apart: ``model_name`` **absent** follows
``config.yaml -> title.model_name``, ``""`` renames without a model call, and a
name picks that model. Per-user UI state, so no admin gate, like chat folders.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import settings as settings_router
from app.gateway.routers.settings import AutoTitlePreference, get_auto_title_setting, update_auto_title_setting
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


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(settings_router.router)
    with TestClient(app) as test_client:
        yield test_client


class _User:
    def __init__(self, user_id: str) -> None:
        self.id = user_id


def test_get_defaults_to_on_with_no_model_key(client):
    """The absent key is the "follow config.yaml" state; ``null`` on the wire
    would read as a different value to a client that checks ``in``."""
    response = client.get("/api/settings/auto-title")
    assert response.status_code == 200
    assert response.json() == {"enabled": True, "stored": False}


def test_get_tells_a_never_set_account_from_an_explicit_on(client):
    """``{"enabled": true}`` is both the default and a saved "on". A browser
    that still holds an opt-out from before the preference moved to the
    account uploads it only into a never-set account; without ``stored`` it
    would overwrite an "on" another device saved."""
    assert client.get("/api/settings/auto-title").json()["stored"] is False

    client.put("/api/settings/auto-title", json={"enabled": True})
    user_ui_state.reset_cache_for_tests()

    assert client.get("/api/settings/auto-title").json() == {"enabled": True, "stored": True}


def test_put_does_not_echo_the_get_only_stored_flag(client):
    response = client.put("/api/settings/auto-title", json={"enabled": False, "stored": False})
    assert response.json() == {"enabled": False}


@pytest.mark.parametrize(
    "preference",
    [
        {"enabled": False},
        {"enabled": True, "model_name": ""},
        {"enabled": True, "model_name": "cheap-model"},
        {"enabled": False, "model_name": "cheap-model"},
    ],
    ids=["off", "no-model-call", "named-model", "off-keeps-model"],
)
def test_put_then_get_round_trips_each_state(client, preference):
    put = client.put("/api/settings/auto-title", json=preference)
    assert put.status_code == 200
    assert put.json() == preference

    # Cold cache: the "reopened on another device" read.
    user_ui_state.reset_cache_for_tests()
    assert client.get("/api/settings/auto-title").json() == {**preference, "stored": True}


def test_a_null_model_name_means_follow_the_operator(client):
    client.put("/api/settings/auto-title", json={"enabled": True, "model_name": "cheap-model"})

    response = client.put("/api/settings/auto-title", json={"enabled": True, "model_name": None})

    assert response.json() == {"enabled": True}
    assert client.get("/api/settings/auto-title").json() == {"enabled": True, "stored": True}


def test_put_is_a_replace_not_a_patch(client):
    """Leaving ``model_name`` out is how the user returns to the server default."""
    client.put("/api/settings/auto-title", json={"enabled": True, "model_name": "cheap-model"})

    response = client.put("/api/settings/auto-title", json={"enabled": True})

    assert response.json() == {"enabled": True}


def test_put_returns_the_normalized_stored_value(client):
    """The response is authoritative: a blank name is unusable, so the store
    keeps "follow the operator" rather than "no model call"."""
    response = client.put("/api/settings/auto-title", json={"enabled": True, "model_name": "   "})
    assert response.json() == {"enabled": True}

    response = client.put("/api/settings/auto-title", json={"enabled": True, "model_name": "  cheap-model "})
    assert response.json() == {"enabled": True, "model_name": "cheap-model"}


def test_an_over_long_model_name_is_rejected_not_truncated(client):
    """A truncated name is a different model; refuse it instead."""
    too_long = "m" * (user_ui_state.MAX_AUTO_TITLE_MODEL_CHARS + 1)

    response = client.put("/api/settings/auto-title", json={"enabled": True, "model_name": too_long})

    assert response.status_code == 422
    assert client.get("/api/settings/auto-title").json() == {"enabled": True, "stored": False}


def test_the_write_leaves_the_chat_folders_alone(client):
    user_ui_state.set_chat_folders("default", [{"id": "f1", "name": "Work"}])

    client.put("/api/settings/auto-title", json={"enabled": False})

    user_ui_state.reset_cache_for_tests()
    assert user_ui_state.get_chat_folders("default") == [{"id": "f1", "name": "Work"}]


@pytest.mark.anyio
async def test_the_preference_is_scoped_to_the_calling_user():
    token = user_context._current_user.set(_User("alice"))
    try:
        await update_auto_title_setting(AutoTitlePreference(enabled=False, model_name=""))
    finally:
        user_context._current_user.reset(token)

    token = user_context._current_user.set(_User("bob"))
    try:
        assert (await get_auto_title_setting()).model_dump(exclude_none=True) == {"enabled": True, "stored": False}
    finally:
        user_context._current_user.reset(token)

    token = user_context._current_user.set(_User("alice"))
    try:
        assert (await get_auto_title_setting()).model_dump(exclude_none=True) == {"enabled": False, "model_name": "", "stored": True}
    finally:
        user_context._current_user.reset(token)
    assert user_ui_state.get_auto_title_preference("alice") == {"enabled": False, "model_name": ""}
