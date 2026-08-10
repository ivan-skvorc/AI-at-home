"""Web Push subscription management (fork feature).

The browser subscribes with the server's VAPID public key and hands back an
endpoint plus two keys; the server stores that per user (beside the pinned chat
tabs, in the same per-user `ui_state.json` bag) and uses it to deliver a
notification when a long-running turn finishes.

Every route is caller-scoped and carries no admin gate — a push subscription is
personal UI state, like the chat tab strip, not a server-wide setting.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.gateway.web_push import load_or_create_vapid_keys, notify_user, push_availability
from deerflow.config.user_ui_state import add_push_subscription, get_push_subscriptions, remove_push_subscription
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/push", tags=["push"])


class PushConfigResponse(BaseModel):
    """What the browser needs to decide whether (and how) to subscribe."""

    available: bool = Field(description="Whether this install can actually send a push.")
    reason: str = Field(default="", description="Why it cannot, when `available` is false — shown verbatim in settings.")
    public_key: str | None = Field(default=None, description="VAPID public key (base64url) for PushManager.subscribe.")
    subscriptions: int = Field(default=0, description="How many devices the caller has registered.")


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionBody(BaseModel):
    """The browser's `PushSubscription.toJSON()` shape, plus a display label."""

    endpoint: str
    keys: PushKeys
    label: str | None = None


class PushUnsubscribeBody(BaseModel):
    endpoint: str


class PushResultResponse(BaseModel):
    subscriptions: int
    delivered: int = 0


@router.get("/config", response_model=PushConfigResponse)
async def get_push_config() -> PushConfigResponse:
    """Report push availability and the VAPID public key.

    The key is minted on first read rather than at startup: an install that
    never enables push should never generate or store a keypair.
    """
    available, reason = push_availability()
    user_id = get_effective_user_id()
    subscriptions = await asyncio.to_thread(get_push_subscriptions, user_id)
    if not available:
        return PushConfigResponse(available=False, reason=reason, subscriptions=len(subscriptions))
    try:
        keys = await asyncio.to_thread(load_or_create_vapid_keys)
    except Exception as exc:
        logger.warning("push: could not load VAPID keys", exc_info=True)
        return PushConfigResponse(available=False, reason=f"Could not load or create VAPID keys: {exc}", subscriptions=len(subscriptions))
    return PushConfigResponse(available=True, public_key=keys.public_key, subscriptions=len(subscriptions))


@router.post("/subscribe", response_model=PushResultResponse)
async def subscribe(body: PushSubscriptionBody) -> PushResultResponse:
    """Register the calling browser for push. Re-subscribing replaces, never duplicates."""
    stored = await asyncio.to_thread(add_push_subscription, get_effective_user_id(), body.model_dump(exclude_none=True))
    return PushResultResponse(subscriptions=len(stored))


@router.post("/unsubscribe", response_model=PushResultResponse)
async def unsubscribe(body: PushUnsubscribeBody) -> PushResultResponse:
    """Forget one device's subscription."""
    stored = await asyncio.to_thread(remove_push_subscription, get_effective_user_id(), body.endpoint)
    return PushResultResponse(subscriptions=len(stored))


@router.post("/test", response_model=PushResultResponse)
async def send_test_push() -> PushResultResponse:
    """Deliver a test notification to every registered device.

    The only way to find out whether the whole chain works — service worker,
    subscription, VAPID keys, push service reachability — without waiting for a
    long run to finish.
    """
    user_id = get_effective_user_id()
    payload = {
        "title": "DeerFlow",
        "body": "Push notifications are working. You will get one of these when a long run finishes.",
        "url": "/",
        "tag": "deerflow-test",
    }
    delivered = await asyncio.to_thread(notify_user, user_id, payload)
    stored = await asyncio.to_thread(get_push_subscriptions, user_id)
    return PushResultResponse(subscriptions=len(stored), delivered=delivered)
