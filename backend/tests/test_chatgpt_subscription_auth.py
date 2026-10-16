"""Offline checks for the subscription credential and local OAuth boundaries."""

import json
import os
import socket
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from deerflow.models import chatgpt_subscription_auth as auth
from deerflow.models import chatgpt_subscription_login as login


@pytest.fixture
def credentials(monkeypatch, tmp_path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update(kid="test-key", use="sig", alg="RS256")
    monkeypatch.setattr(auth, "_fetch_jwks", lambda: {"keys": [public_jwk]})
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "runtime"))
    now = int(time.time())
    identity = {"iss": login.ISSUER, "sub": "verified-account", "aud": "oaiapp_deerflow", "iat": now, "exp": now + 3600, "nonce": "attempt-nonce", "email": "person@example.com"}
    access = {**identity, "aud": login.RESOURCE, "client_id": "oaiapp_deerflow", "scope": login.SCOPES}
    access.pop("nonce")

    def make_record(*, identity_updates=None, access_updates=None, signing_key=None):
        key = signing_key or private_key
        return {
            "client_id": "oaiapp_deerflow",
            "id_token": jwt.encode({**identity, **(identity_updates or {})}, key, algorithm="RS256", headers={"kid": "test-key"}),
            "access_token": jwt.encode({**access, **(access_updates or {})}, key, algorithm="RS256", headers={"kid": "test-key"}),
            "refresh_token": "secret-refresh-token",
            "token_type": "Bearer",
            "scopes": login.SCOPES.split(),
            "ext_agent_host_id": "urn:uuid:copied-laptop-id",
            "subject": "untrusted-metadata",
            "email": "spoofed@example.com",
        }

    return make_record


def test_import_verifies_identity_and_preserves_runtime_host(credentials):
    first = auth.import_chatgpt_connection(credentials())
    second = auth.import_chatgpt_connection(credentials())
    assert first["subject"] == "verified-account"
    assert first["email"] == "person@example.com"
    assert first["ext_agent_host_id"] == second["ext_agent_host_id"]
    assert first["ext_agent_host_id"] != "urn:uuid:copied-laptop-id"
    assert first["expires_at"] > time.time()
    assert "chatgpt.tokens.use.direct" in first["scopes"]


def test_browser_handoff_verifies_nonce_and_keeps_provider_errors_in_settings(credentials, monkeypatch):
    from types import SimpleNamespace
    from urllib.parse import urlencode

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.gateway.routers import subscriptions as router
    from deerflow.models import subscriptions as service

    app = FastAPI()

    @app.middleware("http")
    async def administrator(request, call_next):
        request.state.user = SimpleNamespace(id="admin", system_role="admin")
        return await call_next(request)

    app.include_router(router.router)
    monkeypatch.setattr(service, "_catalog", lambda *args: [])
    with TestClient(app) as client:
        for valid_nonce in (False, True):
            start = client.post("/api/subscriptions/chatgpt/start", json={})
            assert start.status_code == 200
            assert start.headers["cache-control"] == "no-store"
            flow = start.json()
            parameters = parse_qs(urlsplit(flow["authorization_url"]).query)
            token_response = credentials(identity_updates={"nonce": parameters["nonce"][0] if valid_nonce else "another-attempt"})
            monkeypatch.setattr(service, "_request_json", lambda *args, **kwargs: token_response)
            callback = flow["redirect_uri"] + "?" + urlencode({"state": parameters["state"][0], "code": "private-code", "client_id": "oaiapp_deerflow"})
            response = client.post("/api/subscriptions/chatgpt/complete", json={"flow_id": flow["flow_id"], "callback_url": callback})
            # A provider rejection must not use 401: the browser fetcher would
            # mistake that for an expired DeerFlow session and leave settings.
            assert response.status_code == (200 if valid_nonce else 400)
            assert "private-code" not in response.text
            assert token_response["access_token"] not in response.text
            assert token_response["refresh_token"] not in response.text
            status = client.get("/api/subscriptions").json()
            assert next(item for item in status["providers"] if item["provider"] == "chatgpt")["connected"] is valid_nonce


@pytest.mark.parametrize(
    "changes",
    [
        {"identity_updates": {"iss": "https://attacker.invalid"}},
        {"identity_updates": {"aud": "another-client"}},
        {"identity_updates": {"exp": 1}},
        {"access_updates": {"scope": "openid resource.invoke"}},
        {"access_updates": {"aud": "another-resource"}},
        {"access_updates": {"client_id": "another-client"}},
        {"access_updates": {"sub": "another-account"}},
        {"signing_key": rsa.generate_private_key(public_exponent=65537, key_size=2048)},
    ],
)
def test_import_rejects_invalid_or_unrelated_grants_without_exposing_tokens(credentials, changes):
    record = credentials(**changes)
    with pytest.raises(ValueError) as error:
        auth.import_chatgpt_connection(record)
    assert record["access_token"] not in str(error.value)
    assert record["refresh_token"] not in str(error.value)


def test_refresh_validates_the_signed_grant_and_selected_registration(credentials):
    record = credentials()
    record.pop("id_token")
    result = auth.validate_chatgpt_token_response(record, client_id="oaiapp_deerflow", subject="verified-account", require_id_token=False)
    assert result["subject"] == "verified-account"
    with pytest.raises(ValueError, match="identity"):
        auth.validate_chatgpt_token_response(record, client_id="oaiapp_deerflow", subject="other-account", require_id_token=False)
    with pytest.raises(ValueError, match="nonce"):
        auth.validate_chatgpt_token_response(credentials(), client_id="oaiapp_deerflow", nonce="wrong-nonce")


def test_prefetched_signing_keys_validate_without_another_network_request(credentials, monkeypatch):
    keys = auth._fetch_jwks()

    def unavailable():
        raise AssertionError("Rotating a token must not require another signing-key request")

    monkeypatch.setattr(auth, "_fetch_jwks", unavailable)
    result = auth.validate_chatgpt_token_response(credentials(), client_id="oaiapp_deerflow", jwks=keys)
    assert result["subject"] == "verified-account"


def test_signing_key_outage_is_distinct_from_an_invalid_grant(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ValueError("Provider response might contain private details")

    monkeypatch.setattr(login, "request_json", unavailable)
    with pytest.raises(auth.ChatGPTKeyDiscoveryError) as error:
        auth._fetch_jwks()
    assert "private details" not in str(error.value)


def test_discovery_only_admits_public_catalog_models(monkeypatch):
    payload = {
        "models": [
            {"slug": "gpt-6.1-sol", "visibility": "list", "display_name": "GPT"},
            {"slug": "gpt-6.1-sol", "visibility": "list"},
            {"slug": "../../other-model", "visibility": "list"},
            {"slug": "gpt-6.1-sol\nsecret", "visibility": "list"},
            {"slug": "hidden-model", "visibility": "hide"},
        ]
    }
    captured = []

    def fake_get(url, **kwargs):
        import httpx

        captured.append((url, kwargs))
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(auth.httpx, "get", fake_get)
    models = auth.discover_chatgpt_models("secret-access-token")
    assert [model["model"] for model in models] == ["gpt-6.1-sol"]
    assert all("secret-access-token" not in json.dumps(model) for model in models)
    assert captured[0][0] == login.RESOURCE + "/models"
    assert captured[0][1]["headers"]["Authorization"] == "Bearer secret-access-token"


def test_catalog_only_allows_no_reasoning_when_the_server_declares_it(monkeypatch):
    import httpx

    models = [
        {"slug": "optional-model", "visibility": "list", "supported_reasoning_levels": [{"effort": "none"}, {"effort": "medium"}]},
        {"slug": "required-model", "visibility": "list", "supported_reasoning_levels": [{"effort": "medium"}]},
        {"slug": "unknown-model", "visibility": "list"},
    ]
    monkeypatch.setattr(auth.httpx, "get", lambda url, **kwargs: httpx.Response(200, json={"models": models}, request=httpx.Request("GET", url)))
    profiles = auth.discover_chatgpt_models("test-token")
    assert [item["allow_reasoning_none"] for item in profiles] == [True, False, False]
    assert profiles[0]["reasoning"]["thinking"] == "optional"
    assert profiles[1]["reasoning"]["thinking"] == "required"


def test_local_helper_reuses_registration_and_validates_callback():
    url = login.build_authorization_url(client_id="oaiapp_saved", host_id="urn:uuid:same-host", redirect_uri="http://127.0.0.1:54321/auth/callback", state="state", nonce="nonce", verifier="verifier", id_token_hint="private-id-token")
    params = parse_qs(urlsplit(url).query)
    assert params["client_id"] == ["oaiapp_saved"]
    assert params["ext_agent_host_id"] == ["urn:uuid:same-host"]
    assert "agent_name_hint" not in params
    assert params["id_token_hint"] == ["private-id-token"]
    assert login.parse_callback("/auth/callback?state=state&code=code", state="state", client_id="oaiapp_saved") == ("code", "oaiapp_saved")
    for callback in ("/auth/callback?state=wrong&code=code", "/callback?state=state&code=code", "/auth/callback?state=state&code=code&client_id=oaiapp_other", "/auth/callback?state=state&state=state&code=code"):
        with pytest.raises(ValueError):
            login.parse_callback(callback, state="state", client_id="oaiapp_saved")
    assert login.parse_callback("/auth/callback?state=state&code=code&client_id=oaiapp_new", state="state", client_id=login.DYNAMIC_CLIENT) == ("code", "oaiapp_new")


def test_local_helper_atomic_protected_output(tmp_path):
    path = tmp_path / "connection.json"
    login.write_private_json(path, {"refresh_token": "old"})
    login.write_private_json(path, {"refresh_token": "new"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"refresh_token": "new"}
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [path]


def test_local_helper_serves_callback_while_an_idle_preconnect_expires(tmp_path, monkeypatch):
    """A browser's spare connection cannot block the actual OAuth callback."""
    monkeypatch.setattr(login, "_CALLBACK_SOCKET_TIMEOUT", 0.05, raising=False)
    monkeypatch.setattr(login, "request_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(login, "validate_token_response", lambda *args, **kwargs: {"client_id": "oaiapp_test", "refresh_token": "test-refresh"})
    futures = []

    with ThreadPoolExecutor(max_workers=1) as pool:

        def open_browser(url):
            parameters = parse_qs(urlsplit(url).query)
            redirect = parameters["redirect_uri"][0]
            parsed = urlsplit(redirect)
            idle = socket.create_connection((parsed.hostname, parsed.port), timeout=2)
            callback = redirect + "?state=" + parameters["state"][0] + "&code=test-code&client_id=oaiapp_test"

            def finish_callback():
                try:
                    # The second connection carries the real browser redirect.
                    with urllib.request.urlopen(callback, timeout=1) as response:
                        assert response.status == 200
                    # The spare connection must also close in bounded time.
                    assert idle.recv(1) == b""
                finally:
                    idle.close()

            futures.append(pool.submit(finish_callback))
            return True

        monkeypatch.setattr(login.webbrowser, "open", open_browser)
        result = login.sign_in(profile_path=tmp_path / "profile.json", host_id="urn:uuid:test-host")
        futures[0].result(timeout=3)
    assert result["client_id"] == "oaiapp_test"


def test_local_helper_rejects_a_profile_that_would_replace_host_identity(tmp_path, monkeypatch):
    def forbidden_sign_in(**kwargs):
        raise AssertionError("Invalid profile must be rejected before browser sign-in")

    monkeypatch.setattr(sys, "argv", ["deerflow-chatgpt-login.py", "--profile", "chatgpt-host-id", "--state-dir", str(tmp_path)])
    monkeypatch.setattr(login, "sign_in", forbidden_sign_in)
    with pytest.raises(SystemExit) as error:
        login.main()
    assert error.value.code == 2
    assert not list(tmp_path.iterdir())
