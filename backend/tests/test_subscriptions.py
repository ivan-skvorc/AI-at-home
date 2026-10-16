"""Subscription connections: encrypted snapshots, OAuth fencing, and admin-only writes."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from deerflow.models import subscriptions as service


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    return service.SubscriptionStore()


def test_encrypted_connections_and_disconnected_catalog(store):
    record = {"provider": "kimi", "api_key": "private-key", "connected": True, "models": [{"name": "subscription-kimi-test", "model": "test", "use": "test"}]}
    store.save("kimi", record)
    assert b"private-key" not in store.path.read_bytes()
    assert store.get("kimi")["api_key"] == "private-key"
    assert service.get_subscription_models()[0].name == "subscription-kimi-test"
    assert "private-key" not in json.dumps(service.subscription_status())
    store.save("kimi", {**record, "connected": False})
    assert service.get_subscription_models() == []
    store.key_path.unlink()
    with pytest.raises(service.SubscriptionError, match="storage"):
        store.get("kimi")
    assert not store.key_path.exists()


def test_refresh_rotates_atomically_and_revocation_hides_models(store, monkeypatch):
    store.save("grok", {"access_token": "old", "refresh_token": "refresh", "client_id": "issued-id", "expires_at": 0, "connected": True, "models": []})
    calls = []

    def request(method, url, **kwargs):
        calls.append(kwargs["data"])
        return {"access_token": "new", "refresh_token": "rotated", "expires_in": 3600}

    monkeypatch.setattr(service, "_request_json", request)
    assert service.get_access_token("grok") == "new"
    assert service.get_access_token("grok") == "new"
    assert len(calls) == 1
    assert calls[0]["client_id"] == "issued-id"
    assert store.get("grok")["refresh_token"] == "rotated"
    record = store.get("grok")
    store.save("grok", {**record, "expires_at": 0})

    def revoked(*args, **kwargs):
        raise service.SubscriptionError("Reconnect subscription", code="invalid_grant", status_code=401)

    monkeypatch.setattr(service, "_request_json", revoked)
    with pytest.raises(service.SubscriptionError):
        service.get_access_token("grok")
    assert store.get("grok")["needs_reauth"] is True
    assert service.get_subscription_models() == []


def test_device_flow_owner_poll_spacing_and_catalog(store, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(service.time, "monotonic", lambda: clock[0])
    calls = []
    attempts = []

    def request(method, url, **kwargs):
        calls.append(url)
        if url.endswith("device/code"):
            return {"device_code": "server-secret", "user_code": "CODE", "verification_uri": "https://accounts.x.ai/device", "expires_in": 600, "interval": 5}
        if url.endswith("oauth2/token"):
            attempts.append(url)
            if len(attempts) == 1:
                raise service.SubscriptionError("Please slow down", code="slow_down")
            return {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}
        return {"data": [{"id": "grok-test", "context_window": 10000}, {"id": "locked", "available": False}]}

    monkeypatch.setattr(service, "_request_json", request)
    flow = service.begin_grok_connection("owner")
    assert "server-secret" not in json.dumps(flow)
    with pytest.raises(service.SubscriptionError) as exc:
        service.poll_grok_connection("other-owner", flow["flow_id"])
    assert exc.value.status_code == 404
    assert service.poll_grok_connection("owner", flow["flow_id"])["status"] == "pending"
    assert len(calls) == 1
    clock[0] += 5
    assert service.poll_grok_connection("owner", flow["flow_id"]) == {"status": "pending", "interval": 10}
    clock[0] += 5
    assert service.poll_grok_connection("owner", flow["flow_id"])["status"] == "pending"
    assert len(attempts) == 1
    clock[0] += 5
    result = service.poll_grok_connection("owner", flow["flow_id"])
    assert result["status"] == "connected"
    models = service.get_subscription_models()
    assert [m.model for m in models] == ["grok-test"]
    assert models[0].supports_vision is False
    assert models[0].price is None
    with pytest.raises(service.SubscriptionError):
        service.poll_grok_connection("owner", flow["flow_id"])


@pytest.mark.asyncio
async def test_admin_gate_precedes_storage_and_key_connect_is_offloop(store, monkeypatch):
    from app.gateway.routers import subscriptions as router

    member = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="member", system_role="user")))
    admin = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="admin", system_role="admin")))
    with pytest.raises(HTTPException) as exc:
        await router.list_subscriptions(member)
    assert exc.value.status_code == 403

    def request(*args, **kwargs):
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        assert kwargs["headers"]["Authorization"] == "Bearer private-key"
        return {"data": [{"id": "kimi-test", "supports_reasoning": True, "context_length": 1024}]}

    monkeypatch.setattr(service, "_request_json", request)
    result = await router.connect_subscription("kimi", admin, router.ConnectRequest(api_key="private-key"))
    assert result["model_count"] == 1
    assert service.get_subscription_models()[0].subscription_provider == "kimi"
    public = await router.list_subscriptions(admin)
    assert "private-key" not in json.dumps(public)
    await router.disconnect_subscription("kimi", admin)
    assert service.get_subscription_models() == []


def test_effective_snapshot_preserves_manual_profiles_and_changes_on_disconnect(store, monkeypatch):
    from deerflow.config.app_config import AppConfig, get_app_config, reset_app_config

    path = store.path.parent.parent / "config.yaml"
    path.write_text("sandbox:\n  use: test\nmodels:\n  - name: manual\n    model: same\n    use: test\n", encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(path))
    monkeypatch.setattr(AppConfig, "resolve_config_path", staticmethod(lambda *args, **kwargs: path))
    store.save("kimi", {"connected": True, "models": [{"name": "manual", "model": "conflict", "use": "test"}, {"name": "subscription-kimi-same", "model": "same", "use": "test"}]})
    reset_app_config()
    try:
        first = get_app_config()
        assert [model.name for model in first.models] == ["manual", "subscription-kimi-same"]
        assert first.get_model_config("manual").model == "same"
        assert first is get_app_config()
        store.delete("kimi")
        second = get_app_config()
        assert second.get_model_config("subscription-kimi-same") is None
        assert first.get_model_config("subscription-kimi-same") is not None
        explicit = AppConfig.from_file(str(path))
        assert [model.name for model in explicit.models] == ["manual"]
    finally:
        reset_app_config()


def test_concurrent_refresh_uses_one_rotating_grant(store, monkeypatch):
    store.save("grok", {"connected": True, "access_token": "old", "refresh_token": "old-refresh", "client_id": "client", "expires_at": 0})
    calls = []

    def refresh(*args, **kwargs):
        calls.append(kwargs["data"]["refresh_token"])
        return {"access_token": "fresh", "refresh_token": "new-refresh", "expires_in": 3600}

    monkeypatch.setattr(service, "_request_json", refresh)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _: service.get_access_token("grok"), range(4))) == ["fresh"] * 4
    assert calls == ["old-refresh"]
    assert store.get("grok")["refresh_token"] == "new-refresh"


def test_disconnect_clears_local_access_when_remote_revocation_fails(store, monkeypatch):
    import httpx

    store.save("grok", {"connected": True, "refresh_token": "private-refresh", "client_id": "client"})

    def revoke(client, url, **kwargs):
        assert url == "https://auth.x.ai/oauth2/revoke"
        assert kwargs["data"]["token"] == "private-refresh"
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.Client, "post", revoke)
    assert service.disconnect_subscription("grok")["revocation_confirmed"] is False
    assert store.get("grok") is None


def test_invalid_http_payloads_never_echo_subscription_secrets(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.gateway.routers import subscriptions as router

    app = FastAPI()
    app.include_router(router.router)
    with TestClient(app) as client:
        response = client.post("/api/subscriptions/chatgpt/connect", json={"connection": "private-imported-secret"})
    assert response.status_code == 422
    assert "private-imported-secret" not in response.text


def test_grok_catalog_uses_inference_identity_and_only_supported_visible_entries(monkeypatch):
    catalog = [
        {"id": "picker-slug", "model": "inference-model", "contextWindow": 32000, "supports_reasoning": True},
        {"modelId": "camel-model", "_meta": {"contextWindow": 64000}},
        {"_meta": {"model": "meta-model", "totalContextTokens": 128000}},
        {"id": "session-only", "supportedInApi": False, "api_backend": "chat_completions"},
        {"model": "hidden", "hidden": True},
        {"id": "meta-hidden", "_meta": {"hidden": True}},
        {"id": "responses-only", "apiBackend": "responses"},
        {"id": "messages-only", "api_backend": "messages"},
    ]
    monkeypatch.setattr(service, "_request_json", lambda *args, **kwargs: {"data": catalog})
    models = service._catalog("grok", "token")
    assert [model["model"] for model in models] == ["inference-model", "camel-model", "meta-model", "session-only"]
    assert [model.get("context_window") for model in models] == [32000, 64000, 128000, None]
    assert models[0]["default_headers"]["x-grok-model-override"] == "inference-model"
    assert models[0]["reasoning"]["dialect"] == "none"
    assert "when_thinking_enabled" not in models[0]


def test_kimi_reasoning_uses_documented_thinking_switch_without_clear_thinking(monkeypatch):
    from deerflow.config.model_config import ModelConfig
    from deerflow.models.factory import _apply_contract_thinking_settings
    from deerflow.models.reasoning import resolve_reasoning_contract

    monkeypatch.setattr(service, "_request_json", lambda *args, **kwargs: {"data": [{"id": "kimi-test", "supports_reasoning": True}]})
    profile = ModelConfig.model_validate(service._catalog("kimi", "key")[0])
    for enabled in (True, False):
        settings = {}
        _apply_contract_thinking_settings(
            settings,
            resolve_reasoning_contract(profile),
            profile,
            thinking_enabled=enabled,
            effective_wte=profile.when_thinking_enabled or {},
            requested_reasoning_effort=None,
            codex_handles_generic_effort=False,
        )
        assert settings == {"extra_body": {"thinking": {"type": "enabled" if enabled else "disabled"}}}


@pytest.mark.parametrize("provider", ["kimi", "chatgpt"])
def test_connection_discovery_stays_inside_write_transaction(store, monkeypatch, provider):
    from deerflow.models import chatgpt_subscription_auth as auth

    started, release = threading.Event(), threading.Event()

    def catalog(*args):
        started.set()
        assert release.wait(5)
        return []

    monkeypatch.setattr(service, "_catalog", catalog)
    monkeypatch.setattr(auth, "import_chatgpt_connection", lambda record: {"access_token": "token"})
    connect = service.connect_kimi if provider == "kimi" else service.connect_chatgpt
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(connect, "key" if provider == "kimi" else {})
        try:
            assert started.wait(5)
            # A competing disconnect must not enter its write transaction until
            # discovery and connection publication complete.
            acquired = service._LOCK.acquire(blocking=False)
            if acquired:
                service._LOCK.release()
            assert not acquired
        finally:
            release.set()
            future.result(5)
    service.disconnect_subscription(provider)
    assert store.get(provider) is None


def test_chatgpt_jwks_outage_preserves_grant_without_rotating(store, monkeypatch):
    from deerflow.models import chatgpt_subscription_auth as auth

    original = {"connected": True, "access_token": "old", "refresh_token": "renewable", "client_id": "client", "expires_at": 0, "models": []}
    store.save("chatgpt", original)
    calls = []

    def unavailable():
        raise auth.ChatGPTKeyDiscoveryError("Temporary key discovery outage")

    monkeypatch.setattr(auth, "_fetch_jwks", unavailable)
    monkeypatch.setattr(service, "_request_json", lambda *args, **kwargs: calls.append(args) or {"access_token": "new", "refresh_token": "replacement"})
    with pytest.raises(service.SubscriptionError) as exc:
        service.get_access_token("chatgpt")
    assert exc.value.status_code == 503
    assert calls == []
    assert store.get("chatgpt") == {**original, "provider": "chatgpt"}


@pytest.mark.parametrize("code", ["invalid_grant", "refresh_token_reused", "invalid_scope"])
def test_terminal_refresh_codes_survive_http_parsing_and_disconnect(store, monkeypatch, code):
    import httpx

    original_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(400, json={"error": code, "error_description": "private-refresh must never be exposed"}))
    monkeypatch.setattr(service.httpx, "Client", lambda **kwargs: original_client(transport=transport, **kwargs))
    store.save("grok", {"connected": True, "refresh_token": "private-refresh", "client_id": "issued-client", "expires_at": 0, "models": []})
    with pytest.raises(service.SubscriptionError) as exc:
        service.get_access_token("grok")
    assert exc.value.code == code
    assert "private-refresh" not in str(exc.value)
    assert store.get("grok")["needs_reauth"] is True


def test_config_snapshots_remain_readable_while_subscription_provider_is_waiting(store, monkeypatch):
    from deerflow.config.app_config import AppConfig

    store.save("kimi", {"connected": True, "models": [{"name": "subscription-kimi-existing", "model": "existing", "use": "test"}]})
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})
    snapshot = service.merge_subscription_models(config)
    started, release = threading.Event(), threading.Event()

    def waiting_catalog(*args):
        started.set()
        assert release.wait(10)
        return []

    def read_snapshots():
        assert service.merge_subscription_models(config) is snapshot
        uncached = service.merge_subscription_models(config.model_copy())
        return [model.model for model in uncached.models]

    monkeypatch.setattr(service, "_catalog", waiting_catalog)
    with ThreadPoolExecutor(max_workers=2) as pool:
        connecting = pool.submit(service.connect_kimi, "new-key")
        try:
            assert started.wait(5)
            # A pending provider request retains the write lock, but both cached
            # and newly assembled application snapshots must read prior state.
            reading = pool.submit(read_snapshots)
            assert reading.result(timeout=5) == ["existing"]
        finally:
            release.set()
            connecting.result(timeout=5)
