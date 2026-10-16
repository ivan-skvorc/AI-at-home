"""Verify imported ChatGPT plan grants and discover their public model catalog."""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from deerflow.config.model_config import ModelConfig
from deerflow.config.runtime_paths import runtime_home
from deerflow.models import chatgpt_subscription_login as login


class ChatGPTKeyDiscoveryError(ValueError):
    """Temporary signing-key lookup failure, separate from an invalid grant."""


def _fetch_jwks() -> dict:
    try:
        return login.request_json(login.JWKS_ENDPOINT)
    except (ValueError, OSError):
        raise ChatGPTKeyDiscoveryError("Could not load ChatGPT signing keys; retry the connection shortly.") from None


def validate_chatgpt_token_response(response: dict, *, client_id: str, subject: str | None = None, nonce: str | None = None, require_id_token: bool = True, jwks: dict | None = None) -> dict:
    return login.validate_token_response(response, client_id=client_id, jwks=_fetch_jwks() if jwks is None else jwks, subject=subject, nonce=nonce, require_id_token=require_id_token)


def import_chatgpt_connection(record: dict) -> dict:
    if not isinstance(record, dict):
        raise ValueError("Upload a valid ChatGPT connection file.")
    validated = validate_chatgpt_token_response(record, client_id=record.get("client_id"))
    if not validated.get("refresh_token"):
        raise ValueError("The ChatGPT connection needs renewable access; sign in again.")
    # The import transfers a session, never the browser computer's host identity.
    validated["ext_agent_host_id"] = login.get_or_create_host_id(runtime_home() / "subscriptions")
    return validated


def discover_chatgpt_models(access_token: str) -> list[dict]:
    try:
        response = httpx.get(login.RESOURCE + "/models", headers={"Authorization": f"Bearer {access_token}", "User-Agent": "DeerFlow/subscription-models"}, timeout=20, follow_redirects=False)
        response.raise_for_status()
        if len(response.content) > 2 * 1024 * 1024:
            raise ValueError
        items = response.json().get("models")
        if not isinstance(items, list) or len(items) > 1000:
            raise ValueError
    except (httpx.HTTPError, ValueError, AttributeError):
        raise ValueError("Could not load the ChatGPT account's model catalog; check access and retry.") from None
    profiles, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or item.get("visibility") != "list":
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,149}", slug) or slug in seen:
            continue
        seen.add(slug)
        display = item.get("display_name")
        profile = {
            "name": "subscription-chatgpt-" + slug,
            "display_name": f"{display if isinstance(display, str) and display else slug} (ChatGPT subscription)",
            "model": slug,
            "use": "deerflow.models.subscription_providers:ChatGPTSubscriptionChatModel",
            "subscription_provider": "chatgpt",
            "supports_vision": False,
        }
        efforts = item.get("supported_reasoning_levels")
        values = [level.get("effort") for level in efforts if isinstance(level, dict)] if isinstance(efforts, list) else []
        values = [value for value in values if value in {"none", "low", "medium", "high", "xhigh"}]
        profile["allow_reasoning_none"] = "none" in values
        if values:
            profile["reasoning"] = {
                "thinking": "optional" if "none" in values else "required",
                "effort": {"path": "reasoning_effort", "values": values, "default": item.get("default_reasoning_level") if item.get("default_reasoning_level") in values else values[0]},
            }
        profiles.append(ModelConfig.model_validate(profile).model_dump(exclude_none=True))
    return profiles


def helper_source() -> str:
    return Path(login.__file__).read_text(encoding="utf-8")
