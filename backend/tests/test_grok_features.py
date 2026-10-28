"""Grok API features on the connected subscription: reach probe, switches, tool gate (FORK.md §43).

The properties pinned here are the silent ones: a new grant starts with every
feature off, only a 401/403 locks a feature, an outage keeps the last answer,
the run's tool list and the per-call token check agree with the switches, and
no token reaches a status response.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from deerflow.models import subscriptions as service

LISTING = {
    "data": [
        {"id": "grok-imagine-image-2.0", "output_modalities": ["image"]},
        {"id": "grok-imagine-video", "output_modalities": ["video"]},
        {"id": "grok-4.3", "output_modalities": ["text"]},
        {"id": "grok-imagine-image"},
    ]
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    return service.SubscriptionStore()


def _connected(store, **extra):
    store.save("grok", {"connected": True, "access_token": "private-access", "refresh_token": "private-refresh", "client_id": "client", "expires_at": 10**12, "models": [], **extra})


def _xai(responses: dict):
    """A `_request_json` double keyed by URL suffix; values are payloads or HTTP statuses."""
    calls = []

    def request(method, url, **kwargs):
        calls.append(url)
        for suffix, value in responses.items():
            if url.endswith(suffix):
                if isinstance(value, int):
                    raise service.SubscriptionError("rejected", http_status=value) if value else service.SubscriptionError("unreachable")
                return value
        raise AssertionError(f"unexpected request {url}")

    return request, calls


def test_probe_classifies_the_listing_and_only_refusals_lock_a_feature(store, monkeypatch):
    request, calls = _xai({"api.x.ai/v1/models": LISTING, "/tts/voices": {"voices": [{"voice_id": "eve"}]}})
    monkeypatch.setattr(service, "_request_json", request)
    probe = service._probe_grok("token")
    assert probe["api"] == "available" and probe["voice"] == "available"
    assert probe["models"] == {"image": ["grok-imagine-image-2.0", "grok-imagine-image"], "video": ["grok-imagine-video"], "text": ["grok-4.3"]}
    assert calls == [f"{service.XAI_API}/models", f"{service.XAI_API}/tts/voices"]

    refused, _ = _xai({"/models": 403, "/tts/voices": 401})
    monkeypatch.setattr(service, "_request_json", refused)
    locked = service._probe_grok("token", probe)
    assert locked["api"] == "not_on_plan" and locked["voice"] == "not_on_plan"
    assert set(service._feature_availability(locked).values()) == {"not_on_plan"}

    # An outage is not a verdict: the previous answer survives it.
    outage, _ = _xai({"/models": 0, "/tts/voices": 502})
    monkeypatch.setattr(service, "_request_json", outage)
    kept = service._probe_grok("token", probe)
    assert kept["api"] == "available" and kept["voice"] == "available" and kept["models"] == probe["models"]
    assert service._feature_availability(service._probe_grok("token"))["image"] == "unknown"


def test_a_listing_that_omits_a_family_leaves_it_switchable():
    probe = {"api": "available", "models": {"image": ["grok-imagine-image"], "video": [], "text": []}, "voice": "available"}
    assert service._feature_availability(probe) == {"image": "available", "video": "unknown", "x_search": "unknown", "voice": "available"}


def test_new_grant_starts_switched_off_and_lists_responses_models_only_when_api_reaches(store, monkeypatch):
    catalog = {"data": [{"id": "grok-chat"}, {"id": "grok-agentic", "apiBackend": "responses"}]}
    request, _ = _xai({"oauth2/token": {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}, "grok.com/v1/models": catalog, "api.x.ai/v1/models": LISTING, "/tts/voices": {}})
    monkeypatch.setattr(service, "_request_json", request)
    store.save("grok", {"pending_flow": {"flow_id": "flow", "owner": "owner", "device_code": "code", "interval": 5, "expires_at": 10**12, "deadline": 10**12, "next_poll_at": 0}})
    assert service.poll_grok_connection("owner", "flow")["status"] == "connected"
    record = store.get("grok")
    assert record.get("features") is None
    models = {model["model"]: model for model in record["models"]}
    assert models["grok-agentic"]["use"].endswith(":GrokResponsesSubscriptionChatModel")
    assert models["grok-agentic"]["base_url"] == service.XAI_API
    assert "x-grok-model-override" not in models["grok-agentic"]["default_headers"]
    assert "x-grok-model-override" in models["grok-chat"]["default_headers"]
    status = next(item for item in service.subscription_status()["providers"] if item["provider"] == "grok")
    assert status["features"] == [{"name": name, "enabled": False, "availability": "available"} for name in service.GROK_FEATURES]
    assert "private" not in json.dumps(status) and "access" not in json.dumps(status["features"])

    # A grant the API refuses keeps chat but hides the Responses-only models.
    refused, _ = _xai({"grok.com/v1/models": catalog, "api.x.ai/v1/models": 403, "/tts/voices": 403})
    monkeypatch.setattr(service, "_request_json", refused)
    service.refresh_subscription("grok")
    assert [model["model"] for model in store.get("grok")["models"]] == ["grok-chat"]


def test_switches_refuse_a_plan_refusal_and_reach_the_run_snapshot(store):
    from deerflow.config.app_config import AppConfig

    _connected(store, api_probe={"api": "available", "models": {"image": ["grok-imagine-image"]}, "voice": "not_on_plan"})
    with pytest.raises(service.SubscriptionError) as refused:
        service.set_grok_features({"voice": True})
    assert refused.value.status_code == 409
    with pytest.raises(service.SubscriptionError):
        service.set_grok_features({"teleport": True})

    result = service.set_grok_features({"image": True, "x_search": True})
    assert {item["name"]: item["enabled"] for item in result["features"]} == {"image": True, "video": False, "x_search": True, "voice": False}
    config = service.merge_subscription_models(AppConfig.model_validate({"sandbox": {"use": "test"}}))
    assert config._subscription_features == frozenset({"image", "x_search"})

    service.set_grok_features({"image": False})
    config = service.merge_subscription_models(AppConfig.model_validate({"sandbox": {"use": "test"}}))
    assert config._subscription_features == frozenset({"x_search"})
    assert service.grok_feature_ready("x_search") and not service.grok_feature_ready("image")

    service.disconnect_subscription("grok")
    assert service.grok_feature_ready("x_search") is False


def test_per_call_access_rechecks_the_switch_and_returns_listed_models(store):
    _connected(store, api_probe={"api": "available", "models": {"image": ["grok-imagine-image-2.0"], "text": ["grok-4.3"]}}, features={"image": True})
    token, listed = service.grok_api_access("image")
    assert token == "private-access" and listed == ["grok-imagine-image-2.0"]
    with pytest.raises(service.SubscriptionError, match="switched off"):
        service.grok_api_access("x_search")
    service.set_grok_features({"image": False})
    with pytest.raises(service.SubscriptionError, match="switched off"):
        service.grok_api_access("image")


def test_tools_appear_only_for_ready_features(store, monkeypatch):
    from deerflow.config.app_config import AppConfig
    from deerflow.tools import tools as tools_module

    entries = [
        {"name": "grok_generate_image", "group": "cloud_media", "use": "deerflow.community.xai.tools:grok_generate_image_tool"},
        {"name": "grok_generate_video", "group": "cloud_media", "use": "deerflow.community.xai.tools:grok_generate_video_tool"},
        {"name": "x_search", "group": "web", "use": "deerflow.community.xai.tools:x_search_tool"},
    ]
    base = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "tools": entries})
    monkeypatch.setattr(tools_module, "is_host_bash_allowed", lambda config: True)

    def names(config, **kwargs):
        return {tool.name for tool in tools_module.get_available_tools(include_mcp=False, app_config=config, **kwargs)}

    assert not names(base) & {"grok_generate_image", "grok_generate_video", "x_search"}
    _connected(store, api_probe={"api": "available", "models": {"image": ["grok-imagine-image"]}}, features={"image": True, "x_search": True, "video": False})
    ready = service.merge_subscription_models(base)
    assert {"grok_generate_image", "x_search"} <= names(ready)
    assert "grok_generate_video" not in names(ready)
    # Both are internet-reaching: the conversation's internet switch drops them.
    assert not names(ready, internet_enabled=False) & {"grok_generate_image", "x_search"}


@pytest.mark.asyncio
async def test_feature_route_is_admin_only_and_never_echoes_secrets(store, monkeypatch):
    from app.gateway.routers import subscriptions as router

    _connected(store, api_probe={"api": "available", "models": {"video": ["grok-imagine-video"]}})
    member = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="member", system_role="user")))
    admin = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="admin", system_role="admin")))
    body = router.GrokFeaturesRequest(features={"video": True})
    with pytest.raises(HTTPException) as denied:
        await router.update_grok_features(member, body)
    assert denied.value.status_code == 403
    assert store.get("grok").get("features") is None
    result = await router.update_grok_features(admin, body)
    assert "private" not in json.dumps(result)
    assert store.get("grok")["features"] == {"video": True}
