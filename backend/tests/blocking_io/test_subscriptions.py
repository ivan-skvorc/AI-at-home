"""Subscription credential/catalog mutations must not block the Gateway loop."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi import HTTPException, Response

from app.gateway.routers import subscriptions as router
from deerflow.models import subscriptions as service


@pytest.mark.asyncio
async def test_subscription_settings_round_trip_offloads_encryption_and_files(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(service, "_request_json", lambda *args, **kwargs: {"data": [{"id": "kimi-test"}]})
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="admin", system_role="admin")))
    result = await router.connect_subscription("kimi", request, router.ConnectRequest(api_key="private-key"))
    assert result["model_count"] == 1
    status = await router.list_subscriptions(request)
    assert next(item for item in status["providers"] if item["provider"] == "kimi")["connected"]
    assert "private-key" not in str(status)
    await router.refresh_subscription("kimi", request)
    await router.disconnect_subscription("kimi", request)
    status = await router.list_subscriptions(request)
    assert not next(item for item in status["providers"] if item["provider"] == "kimi")["connected"]


@pytest.mark.asyncio
async def test_chatgpt_browser_handoff_offloads_storage_and_rejects_nonadmins(tmp_path, monkeypatch):
    from deerflow.models import chatgpt_subscription_auth as auth

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    admin = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="admin", system_role="admin")))
    member = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id="member", system_role="user")))
    body = router.ChatGPTCallbackRequest(flow_id="untrusted", callback_url="http://127.0.0.1:12345/auth/callback?code=private-code")
    for action in (router.start_chatgpt(member, Response(), router.ChatGPTStartRequest()), router.complete_chatgpt(member, body)):
        with pytest.raises(HTTPException) as error:
            await action
        assert error.value.status_code == 403

    response = Response()
    flow = await router.start_chatgpt(admin, response, router.ChatGPTStartRequest())
    assert response.headers["Cache-Control"] == "no-store"
    params = parse_qs(urlsplit(flow["authorization_url"]).query)
    callback = flow["redirect_uri"] + "?" + urlencode({"state": params["state"][0], "code": "private-code", "client_id": "oaiapp_browser"})
    monkeypatch.setattr(auth, "_fetch_jwks", lambda: {"keys": []})
    monkeypatch.setattr(service, "_request_json", lambda *args, **kwargs: {"access_token": "private-access", "refresh_token": "private-refresh"})
    monkeypatch.setattr(auth, "validate_chatgpt_token_response", lambda tokens, **kwargs: {**tokens, "client_id": "oaiapp_browser", "subject": "verified", "expires_at": 9999999999})
    monkeypatch.setattr(service, "_catalog", lambda *args: [])
    result = await router.complete_chatgpt(admin, router.ChatGPTCallbackRequest(flow_id=flow["flow_id"], callback_url=callback))
    assert result["status"] == "connected"
    status = await router.list_subscriptions(admin)
    assert next(item for item in status["providers"] if item["provider"] == "chatgpt")["connected"]
    assert "private-" not in str(status)
