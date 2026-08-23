"""Tests for the /api/system-prompt routes (fork feature).

The lead-agent system prompt is readable and editable from Settings. Writing it
rewrites the instructions every run starts from, so the write routes sit behind
the same admin gate as skill and MCP management; reading is admin-gated too,
because the prompt is framework-internal context the agent is told not to
disclose.
"""

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import system_prompt as system_prompt_router
from deerflow.agents.lead_agent import system_prompt_store as store
from deerflow.agents.lead_agent.prompt import SYSTEM_PROMPT_TEMPLATE
from deerflow.config.paths import Paths


def _make_admin_user() -> User:
    return User(email="admin-test@example.com", password_hash="x", system_role="admin", id=uuid4())


def _make_plain_user() -> User:
    return User(email="user-test@example.com", password_hash="x", system_role="user", id=uuid4())


def _make_app(*, admin: bool = True) -> FastAPI:
    app = make_authed_test_app(user_factory=_make_admin_user if admin else _make_plain_user)
    app.include_router(system_prompt_router.router)
    return app


@pytest.fixture
def client(tmp_path: Path):
    with patch.object(store, "get_paths", return_value=Paths(base_dir=tmp_path)):
        yield TestClient(_make_app())


@pytest.fixture
def plain_user_client(tmp_path: Path):
    with patch.object(store, "get_paths", return_value=Paths(base_dir=tmp_path)):
        yield TestClient(_make_app(admin=False))


class TestRead:
    def test_returns_the_builtin_template_by_default(self, client):
        response = client.get("/api/system-prompt")
        assert response.status_code == 200
        body = response.json()
        assert body["content"] == SYSTEM_PROMPT_TEMPLATE
        assert body["default_content"] == SYSTEM_PROMPT_TEMPLATE
        assert body["is_custom"] is False

    def test_lists_the_available_placeholders(self, client):
        body = client.get("/api/system-prompt").json()
        assert "agent_name" in body["placeholders"]
        assert "skills_section" in body["placeholders"]
        # Sorted, so the editor can render a stable list.
        assert body["placeholders"] == sorted(body["placeholders"])

    def test_reports_no_missing_placeholders_for_the_default(self, client):
        assert client.get("/api/system-prompt").json()["missing_placeholders"] == []

    def test_returns_the_override_once_saved(self, client):
        client.put("/api/system-prompt", json={"content": "You are {agent_name}."})
        body = client.get("/api/system-prompt").json()
        assert body["content"] == "You are {agent_name}."
        assert body["default_content"] == SYSTEM_PROMPT_TEMPLATE
        assert body["is_custom"] is True

    def test_reports_placeholders_the_override_dropped(self, client):
        client.put("/api/system-prompt", json={"content": "You are {agent_name}."})
        missing = client.get("/api/system-prompt").json()["missing_placeholders"]
        assert "skills_section" in missing
        assert "agent_name" not in missing


class TestWrite:
    def test_saves_a_valid_override(self, client):
        response = client.put("/api/system-prompt", json={"content": "You are {agent_name}."})
        assert response.status_code == 200
        assert response.json()["is_custom"] is True
        assert store.load_custom_system_prompt() == "You are {agent_name}."

    def test_rejects_an_unknown_placeholder(self, client):
        response = client.put("/api/system-prompt", json={"content": "Hello {not_a_field}"})
        assert response.status_code == 422
        assert "not_a_field" in response.json()["detail"]
        assert store.load_custom_system_prompt() is None

    def test_rejects_an_empty_override(self, client):
        response = client.put("/api/system-prompt", json={"content": "   "})
        assert response.status_code == 422
        assert store.load_custom_system_prompt() is None

    def test_rejects_malformed_braces(self, client):
        response = client.put("/api/system-prompt", json={"content": "unbalanced {agent_name"})
        assert response.status_code == 422

    def test_saving_the_default_verbatim_is_accepted(self, client):
        response = client.put("/api/system-prompt", json={"content": SYSTEM_PROMPT_TEMPLATE})
        assert response.status_code == 200
        assert response.json()["is_custom"] is True


class TestReset:
    def test_delete_reverts_to_the_builtin(self, client):
        client.put("/api/system-prompt", json={"content": "You are {agent_name}."})
        response = client.delete("/api/system-prompt")
        assert response.status_code == 200
        assert response.json()["is_custom"] is False
        assert response.json()["content"] == SYSTEM_PROMPT_TEMPLATE

    def test_delete_without_an_override_is_a_no_op(self, client):
        response = client.delete("/api/system-prompt")
        assert response.status_code == 200
        assert response.json()["is_custom"] is False


class TestPreview:
    def test_renders_the_prompt_the_agent_receives(self, client):
        response = client.get("/api/system-prompt/preview")
        assert response.status_code == 200
        rendered = response.json()["rendered"]
        # Placeholders are substituted, not echoed.
        assert "{agent_name}" not in rendered
        assert "<role>" in rendered

    def test_subagent_section_follows_the_query_flag(self, client):
        # The confidentiality paragraph names <subagent_system> in prose either
        # way, so key off the roster the section itself renders.
        with_subagents = client.get("/api/system-prompt/preview", params={"subagent_enabled": "true"}).json()["rendered"]
        without = client.get("/api/system-prompt/preview", params={"subagent_enabled": "false"}).json()["rendered"]
        assert "**general-purpose**" in with_subagents
        assert "**general-purpose**" not in without
        assert len(without) < len(with_subagents)

    def test_preview_reflects_a_saved_override(self, client):
        client.put("/api/system-prompt", json={"content": "CUSTOM for {agent_name}"})
        rendered = client.get("/api/system-prompt/preview").json()["rendered"]
        assert rendered == "CUSTOM for DeerFlow 2.0"


class TestAuthorization:
    def test_read_requires_admin(self, plain_user_client):
        assert plain_user_client.get("/api/system-prompt").status_code == 403

    def test_preview_requires_admin(self, plain_user_client):
        assert plain_user_client.get("/api/system-prompt/preview").status_code == 403

    def test_write_requires_admin(self, plain_user_client):
        response = plain_user_client.put("/api/system-prompt", json={"content": "You are {agent_name}."})
        assert response.status_code == 403
        assert store.load_custom_system_prompt() is None

    def test_reset_requires_admin(self, plain_user_client):
        assert plain_user_client.delete("/api/system-prompt").status_code == 403
