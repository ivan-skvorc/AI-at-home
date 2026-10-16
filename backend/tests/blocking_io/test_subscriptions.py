"""Subscription credential/catalog mutations must not block the Gateway loop."""

from types import SimpleNamespace

import pytest

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
