"""Operator-shared subscription credentials and discovered model snapshots.

No network calls occur while assembling application configuration. Connection,
refresh, and disconnect transactions share one thread/process lock; credentials
are encrypted with a runtime-local key and never projected into model profiles.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from deerflow.config.extensions_config import extensions_config_file_lock
from deerflow.config.file_signature import get_config_signature
from deerflow.config.managed_models import ManagedModelStore
from deerflow.config.model_config import ModelConfig
from deerflow.config.runtime_paths import runtime_home

PROVIDERS = ("chatgpt", "grok", "kimi")
GROK_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
GROK_AUTH = "https://auth.x.ai/oauth2"
GROK_BASE = "https://cli-chat-proxy.grok.com/v1"
KIMI_BASE = "https://api.kimi.ai/coding/v1"
USER_AGENT = "DeerFlow/2 subscription-connect"
_LOCK = threading.RLock()
_HELD = threading.local()
_MODEL_CACHE_LOCK = threading.Lock()
_MODEL_CACHE: tuple | None = None
_TERMINAL_REFRESH_ERRORS = frozenset({"invalid_grant", "invalid_token", "access_denied", "invalid_scope", "invalid_refresh_token", "token_expired", "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"})


class SubscriptionError(ValueError):
    """A sanitized domain error safe to return to the settings UI."""

    def __init__(self, message: str, *, code: str = "subscription_error", status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise SubscriptionError("Unknown subscription provider", status_code=404)


def subscription_model_name(provider: str, model: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]", "-", model)
    if slug != model:
        slug += "-" + hashlib.sha256(model.encode("utf-8")).hexdigest()[:8]
    return f"subscription-{provider}-{slug}"


class SubscriptionStore(ManagedModelStore):
    """The managed-model encryption/atomic-write primitive, with a separate key."""

    def __init__(self):
        self.path = runtime_home() / "subscriptions" / "connections.enc"
        self.key_path = self.path.with_name("key")

    @contextmanager
    def locked(self) -> Iterator[None]:
        # Nested save/get calls must retain the outer advisory lock. Opening the
        # same flock twice on different descriptors can deadlock even in one thread.
        key = str(self.path)
        with _LOCK:
            held = getattr(_HELD, "paths", set())
            if key in held:
                yield
                return
            with extensions_config_file_lock(self.path):
                _HELD.paths = held | {key}
                try:
                    yield
                finally:
                    _HELD.paths = held

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            records = json.loads(self._cipher().decrypt(self.path.read_bytes()))
            if not isinstance(records, dict) or any(key not in PROVIDERS or not isinstance(value, dict) for key, value in records.items()):
                raise ValueError
            return records
        except Exception:
            raise SubscriptionError("Subscription storage is unavailable; check the catalog and encryption key", status_code=503) from None

    def get(self, provider: str) -> dict | None:
        _provider(provider)
        return copy.deepcopy(self._read().get(provider))

    def save(self, provider: str, record: dict) -> None:
        _provider(provider)
        with self.locked():
            records = self._read()
            records[provider] = {**record, "provider": provider}
            self._publish(records)

    def delete(self, provider: str) -> None:
        _provider(provider)
        with self.locked():
            records = self._read()
            records.pop(provider, None)
            self._publish(records)

    def _publish(self, records: dict) -> None:
        try:
            cipher = self._cipher(create=True)
            self._write(self.path, cipher.encrypt(json.dumps(records, allow_nan=False).encode("utf-8")))
        except SubscriptionError:
            raise
        except Exception:
            raise SubscriptionError("Subscription storage is unavailable; check the catalog and encryption key", status_code=503) from None


def _request_json(method: str, url: str, **kwargs) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **kwargs.pop("headers", {})}
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            with client.stream(method, url, headers=headers, **kwargs) as response:
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 2 * 1024 * 1024:
                        raise SubscriptionError("The subscription provider returned an oversized response")
                payload = json.loads(content)
    except (httpx.HTTPError, ValueError):
        raise SubscriptionError("The subscription provider could not be reached; try again") from None
    if not isinstance(payload, dict):
        raise SubscriptionError("The subscription provider returned an invalid response")
    if not response.is_success:
        raw_error = payload.get("error")
        code = raw_error if isinstance(raw_error, str) else "provider_error"
        # Return only known protocol codes. Error text and response bodies can
        # contain credentials, account information, or client-supplied content.
        safe_codes = _TERMINAL_REFRESH_ERRORS | {"authorization_pending", "slow_down", "expired_token", "invalid_client"}
        raise SubscriptionError("The subscription provider rejected the request; check access or reconnect", code=code if code in safe_codes else "provider_error", status_code=401 if response.status_code == 401 else 502)
    return payload


def _token_update(record: dict, tokens: dict) -> dict:
    token = tokens.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise SubscriptionError("The subscription provider did not issue an access token")
    expires_in = tokens.get("expires_in", 3600)
    if isinstance(expires_in, bool) or not isinstance(expires_in, (float, int)) or not math.isfinite(expires_in) or expires_in <= 0:
        raise SubscriptionError("The subscription provider returned an invalid token expiry")
    updated = {**record, "access_token": token, "expires_at": time.time() + expires_in, "connected": True, "needs_reauth": False}
    refresh = tokens.get("refresh_token")
    if isinstance(refresh, str) and refresh:
        updated["refresh_token"] = refresh
    if "scope" in tokens:
        if not isinstance(tokens["scope"], str):
            raise SubscriptionError("The subscription provider returned invalid token scopes")
        updated["scope"] = tokens["scope"]
    return updated


def _access_token_locked(store: SubscriptionStore, provider: str) -> str:
    record = store.get(provider)
    if not record or not record.get("connected") or record.get("needs_reauth"):
        raise SubscriptionError("Connect this subscription in Settings before using it", status_code=401)
    if provider == "kimi":
        key = record.get("api_key")
        if not isinstance(key, str) or not key:
            raise SubscriptionError("Reconnect this subscription", status_code=401)
        return key
    if record.get("access_token") and record.get("expires_at", 0) > time.time() + 60:
        return record["access_token"]
    if not record.get("refresh_token") or not record.get("client_id"):
        raise SubscriptionError("Reconnect this subscription to refresh access", status_code=401)
    endpoint = f"{GROK_AUTH}/token" if provider == "grok" else "https://auth.openai.com/api/accounts/oauth/token"
    form = {"grant_type": "refresh_token", "client_id": record["client_id"], "refresh_token": record["refresh_token"]}
    if provider == "chatgpt":
        from deerflow.models.chatgpt_subscription_auth import ChatGPTKeyDiscoveryError, _fetch_jwks, validate_chatgpt_token_response

        form["resource"] = "https://api.openai.com/v1"
        # Fetch verification keys before consuming the rotating grant. A JWKS
        # outage must leave the stored refresh token valid for a later attempt.
        try:
            jwks = _fetch_jwks()
        except ChatGPTKeyDiscoveryError:
            raise SubscriptionError("ChatGPT verification keys are temporarily unavailable; try again", status_code=503) from None
    try:
        tokens = _request_json("POST", endpoint, data=form)
        if provider == "chatgpt":
            try:
                validated = validate_chatgpt_token_response(tokens, client_id=record["client_id"], subject=record.get("subject"), require_id_token=False, jwks=jwks)
            except ValueError:
                raise SubscriptionError("ChatGPT authorization changed; reconnect the subscription", code="invalid_token", status_code=401) from None
            updated = {**record, **validated, "connected": True, "needs_reauth": False}
        else:
            updated = _token_update(record, tokens)
    except SubscriptionError as exc:
        if exc.code in _TERMINAL_REFRESH_ERRORS:
            store.save(provider, {**record, "connected": False, "needs_reauth": True, "models": []})
        raise
    store.save(provider, updated)
    return updated["access_token"]


def get_access_token(provider: str) -> str:
    """Resolve the current credential; refresh once under the shared lock."""
    _provider(provider)
    store = SubscriptionStore()
    with store.locked():
        return _access_token_locked(store, provider)


def get_subscription_models() -> list[ModelConfig]:
    """Read discovered snapshots only; disconnected subscriptions expose nothing."""
    records = SubscriptionStore()._read()
    models = []
    for provider in PROVIDERS:
        record = records.get(provider, {})
        if record.get("connected") and record.get("enabled", True) and not record.get("needs_reauth"):
            try:
                models.extend(ModelConfig.model_validate(item) for item in record.get("models", []))
            except (ValueError, TypeError):
                raise SubscriptionError("Subscription model storage is invalid; refresh the connection", status_code=503) from None
    return models


def merge_subscription_models(config):
    """Append discovered models to file-backed snapshots without mutating a run."""
    global _MODEL_CACHE
    store = SubscriptionStore()
    signature = (str(store.path), get_config_signature(store.path), get_config_signature(store.key_path))
    if signature[1] is None:
        return config
    # Writers retain _LOCK while waiting on providers. Configuration readers
    # use only the independently published atomic file snapshot, so neither
    # cache hits nor cache rebuilds wait for a network transaction to finish.
    with _MODEL_CACHE_LOCK:
        if _MODEL_CACHE is not None and _MODEL_CACHE[0] is config and _MODEL_CACHE[1] == signature:
            return _MODEL_CACHE[2]
        existing_names = {item.name for item in config.models}
        models = [item for item in get_subscription_models() if item.name not in existing_names]
        result = config.model_copy(update={"models": [*config.models, *models]})
        result._models_by_name = {**config._models_by_name, **{item.name: item for item in models}}
        result._subscription_model_names = {item.name for item in models}
        _MODEL_CACHE = (config, signature, result)
        return result


def subscription_status() -> dict:
    records = SubscriptionStore()._read()
    providers = []
    for provider in PROVIDERS:
        record = records.get(provider, {})
        connected = bool(record.get("connected") and not record.get("needs_reauth"))
        models = record.get("models", []) if connected else []
        providers.append(
            {
                "provider": provider,
                "connected": connected,
                "needs_reauth": bool(record.get("needs_reauth")),
                "model_count": len(models),
                "models": [{key: model.get(key) for key in ("name", "display_name", "model")} for model in models],
                "auth_type": "api_key" if provider == "kimi" else "oauth",
                "interactive_only": provider == "kimi",
                "updated_at": record.get("updated_at"),
                "account_label": record.get("email") if provider == "chatgpt" else None,
            }
        )
    return {"providers": providers}


def _catalog(provider: str, token: str) -> list[dict]:
    if provider == "chatgpt":
        from deerflow.models.chatgpt_subscription_auth import discover_chatgpt_models

        return discover_chatgpt_models(token)
    base = GROK_BASE if provider == "grok" else KIMI_BASE
    headers = {"Authorization": f"Bearer {token}"}
    if provider == "grok":
        headers["X-XAI-Token-Auth"] = "xai-grok-cli"
    data = _request_json("GET", f"{base}/models", headers=headers).get("data")
    if not isinstance(data, list) or len(data) > 1000:
        raise SubscriptionError("The subscription provider returned an invalid model catalog")
    models, seen = [], set()
    for item in data:
        if not isinstance(item, dict) or item.get("available") is False or item.get("enabled") is False:
            continue
        meta = item.get("_meta") if isinstance(item.get("_meta"), dict) else {}
        if provider == "grok":
            if item.get("hidden", meta.get("hidden")) is True or (item.get("apiBackend") or item.get("api_backend")) in {"responses", "messages"}:
                continue
            # Grok's picker slug (`id`) may differ from the inference route.
            # Match its official client precedence, without trusting a remote
            # base URL or other credential-bearing constructor settings.
            model_id = next((value for value in (item.get("model"), item.get("modelId"), item.get("id"), meta.get("model"), meta.get("modelId")) if isinstance(value, str) and value.strip()), None)
        else:
            model_id = item.get("id") or item.get("model")
        if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 200 or model_id in seen:
            continue
        seen.add(model_id)
        name = subscription_model_name(provider, model_id)
        profile = {
            "name": name,
            "display_name": f"{item.get('display_name') or model_id} ({'Grok' if provider == 'grok' else 'Kimi Code'} subscription)",
            "model": model_id,
            "use": f"deerflow.models.subscription_providers:{'Grok' if provider == 'grok' else 'Kimi'}SubscriptionChatModel",
            "subscription_provider": provider,
            "base_url": base,
            "streaming": True,
        }
        context = next((value for value in (item.get("contextWindow"), item.get("context_window"), item.get("context_length"), meta.get("contextWindow"), meta.get("totalContextTokens")) if type(value) is int and value > 0), None)
        if type(context) is int and context > 0:
            profile["context_window"] = context
        if item.get("supports_image_in") is True or item.get("supports_vision") is True:
            profile["supports_vision"] = True
        if item.get("supports_reasoning") is True:
            # Reasoning history must survive tool follow-ups, but that does not
            # imply support for DeepSeek's clear_thinking wire parameter.
            profile["reasoning"] = {"thinking": "optional" if provider == "kimi" else "required", "history": "preserve", "dialect": "none"}
            if provider == "kimi":
                profile["when_thinking_enabled"] = {"extra_body": {"thinking": {"type": "enabled"}}}
                profile["when_thinking_disabled"] = {"extra_body": {"thinking": {"type": "disabled"}}}
        # The per-model routing header is required even if the JSON model field
        # is present. An empty catalog stays empty: never invent entitlements.
        if provider == "grok":
            profile["default_headers"] = {"X-XAI-Token-Auth": "xai-grok-cli", "x-grok-model-override": model_id, "User-Agent": USER_AGENT}
        else:
            profile["default_headers"] = {"User-Agent": USER_AGENT}
        models.append(ModelConfig.model_validate(profile).model_dump(exclude_none=True))
    return models


def _connected(provider: str, record: dict) -> dict:
    return {"status": "connected", "provider": provider, "model_count": len(record.get("models", []))}


def connect_kimi(api_key: str) -> dict:
    if not api_key.strip():
        raise SubscriptionError("Enter a Kimi Code subscription API key", status_code=422)
    store = SubscriptionStore()
    with store.locked():
        models = _catalog("kimi", api_key.strip())
        record = {"connected": True, "api_key": api_key.strip(), "models": models, "updated_at": time.time()}
        store.save("kimi", record)
        return _connected("kimi", record)


def connect_chatgpt(connection: dict) -> dict:
    from deerflow.models.chatgpt_subscription_auth import import_chatgpt_connection

    store = SubscriptionStore()
    with store.locked():
        record = import_chatgpt_connection(connection)
        record = {**record, "connected": True, "models": _catalog("chatgpt", record["access_token"]), "updated_at": time.time()}
        store.save("chatgpt", record)
        return _connected("chatgpt", record)


def begin_grok_connection(owner: str) -> dict:
    store = SubscriptionStore()
    with store.locked():
        auth = _request_json("POST", f"{GROK_AUTH}/device/code", data={"client_id": GROK_CLIENT_ID, "scope": "openid profile email offline_access grok-cli:access api:access", "referrer": "deerflow"}, headers={"x-grok-client-surface": "ui"})
        uri = auth.get("verification_uri")
        complete = auth.get("verification_uri_complete")
        if any(not isinstance(value, str) or urlsplit(value).scheme != "https" or urlsplit(value).hostname not in {"accounts.x.ai", "auth.x.ai"} for value in (uri, complete) if value is not None):
            raise SubscriptionError("The subscription provider returned an invalid verification URL")
        if not uri or not isinstance(auth.get("device_code"), str) or not isinstance(auth.get("user_code"), str) or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", auth["user_code"]):
            raise SubscriptionError("The subscription provider returned an invalid device code")
        interval = auth.get("interval", 5)
        expiry = auth.get("expires_in", 600)
        if type(interval) is not int or type(expiry) is not int or not 1 <= interval <= 300 or not 1 <= expiry <= 3600:
            raise SubscriptionError("The subscription provider returned invalid device timing")
        flow = {"flow_id": uuid4().hex, "owner": owner, "device_code": auth["device_code"], "interval": interval, "expires_at": time.time() + expiry, "deadline": time.monotonic() + expiry, "next_poll_at": time.monotonic() + interval}
        previous = store.get("grok") or {}
        store.save("grok", {**previous, "pending_flow": flow})
        return {"status": "pending", "flow_id": flow["flow_id"], "user_code": auth["user_code"], "verification_uri": uri, "verification_uri_complete": complete, "interval": interval, "expires_in": expiry}


def poll_grok_connection(owner: str, flow_id: str) -> dict:
    store = SubscriptionStore()
    with store.locked():
        record = store.get("grok") or {}
        flow = record.get("pending_flow", {})
        if flow.get("owner") != owner or flow.get("flow_id") != flow_id:
            raise SubscriptionError("This sign-in flow was not found; start again", status_code=404)
        now = time.monotonic()
        if now >= flow["deadline"] or time.time() >= flow["expires_at"]:
            store.save("grok", {key: value for key, value in record.items() if key != "pending_flow"})
            raise SubscriptionError("This sign-in code expired; start again", status_code=410)
        if now < flow["next_poll_at"]:
            return {"status": "pending", "interval": flow["interval"]}
        flow["next_poll_at"] = now + flow["interval"]
        try:
            tokens = _request_json("POST", f"{GROK_AUTH}/token", data={"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "device_code": flow["device_code"], "client_id": GROK_CLIENT_ID})
        except SubscriptionError as exc:
            if exc.code in {"authorization_pending", "slow_down"}:
                if exc.code == "slow_down":
                    flow["interval"] += 5
                    flow["next_poll_at"] = now + flow["interval"]
                store.save("grok", {**record, "pending_flow": flow})
                return {"status": "pending", "interval": flow["interval"]}
            if exc.code in {"access_denied", "expired_token", "invalid_grant"}:
                record.pop("pending_flow", None)
            else:
                record["pending_flow"] = flow
            store.save("grok", record)
            raise
        connected = _token_update({"client_id": GROK_CLIENT_ID}, tokens)
        # Keep a successful OAuth grant even if model discovery temporarily fails.
        store.save("grok", {**connected, "models": []})
        connected.update(models=_catalog("grok", connected["access_token"]), updated_at=time.time())
        store.save("grok", connected)
        return _connected("grok", connected)


def refresh_subscription(provider: str) -> dict:
    _provider(provider)
    store = SubscriptionStore()
    with store.locked():
        token = _access_token_locked(store, provider)
        record = store.get(provider)
        record.update(models=_catalog(provider, token), updated_at=time.time())
        store.save(provider, record)
        return _connected(provider, record)


def disconnect_subscription(provider: str) -> dict:
    """Stop locally even if the remote renewable session cannot be revoked."""
    _provider(provider)
    store = SubscriptionStore()
    confirmed = provider == "kimi"
    with store.locked():
        record = store.get(provider) or {}
        refresh_token = record.get("refresh_token")
        if provider != "kimi" and refresh_token:
            endpoint = f"{GROK_AUTH}/revoke" if provider == "grok" else "https://auth.openai.com/api/accounts/oauth/revoke"
            try:
                with httpx.Client(timeout=10, follow_redirects=False) as client:
                    response = client.post(endpoint, data={"token": refresh_token, "token_type_hint": "refresh_token", "client_id": record["client_id"]}, headers={"User-Agent": USER_AGENT})
                    confirmed = response.status_code == 200
            except (httpx.HTTPError, KeyError):
                pass
        elif provider != "kimi":
            confirmed = not record.get("access_token")
        store.delete(provider)
    return {"status": "disconnected", "provider": provider, "revocation_confirmed": confirmed}
