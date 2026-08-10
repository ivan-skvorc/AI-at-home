"""Web Push delivery for finished runs (fork feature).

The fork's premise is "start a sandbox run from my phone over Tailscale, pocket
it, get pinged when it's done". Until now there was a notification settings page
built on the plain browser `Notification` API — no service worker, no manifest —
so a notification only fired while the tab was open, and iOS Safari would not
deliver at all without an installed PWA. The use case the fork is built around
did not work on the device it is designed for.

**VAPID keys are generated once and kept.** They are the server's identity to
the push service; regenerating them invalidates every existing subscription, so
the private key is written `0600` under the DeerFlow home directory and reused.

**`pywebpush` is an optional dependency.** Push encryption (AES128GCM + ECDH) is
not something to hand-roll, and most installs never turn this on, so the feature
reports itself unavailable with an install hint rather than making everyone
carry the dependency — the same pattern as the Camoufox browser backend.

**A dead subscription deletes itself.** A push service answers 404/410 for a
subscription the browser has discarded, and nothing else ever cleans those up;
delivery prunes them so a user who reinstalls their browser does not accumulate
undeliverable endpoints forever.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VAPID_FILENAME = "vapid.json"
# Contact address included in the VAPID claim. Push services want a way to reach
# the sender; a mailto that resolves nowhere is the convention for self-hosted
# senders and is accepted by FCM/Mozilla/Apple.
DEFAULT_VAPID_SUBJECT = "mailto:deerflow@localhost"
# Push services reject oversized payloads (4 KB after encryption is the common
# limit); a notification is a nudge, not a transcript.
MAX_PAYLOAD_BYTES = 3000


class WebPushUnavailable(RuntimeError):
    """Raised when push is configured but cannot run in this install."""


@dataclass(frozen=True)
class VapidKeys:
    public_key: str
    private_key: str
    subject: str


def _vapid_path() -> Path:
    from deerflow.config.paths import get_paths

    return get_paths().base_dir / VAPID_FILENAME


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def generate_vapid_keys(subject: str = DEFAULT_VAPID_SUBJECT) -> VapidKeys:
    """Mint a fresh VAPID keypair (P-256, the only curve Web Push defines)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.generate_private_key(ec.SECP256R1())
    public_numbers = private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    private_value = private.private_numbers().private_value.to_bytes(32, "big")
    return VapidKeys(public_key=_b64url(public_numbers), private_key=_b64url(private_value), subject=subject)


def load_or_create_vapid_keys(subject: str = DEFAULT_VAPID_SUBJECT, path: Path | None = None) -> VapidKeys:
    """Read the instance's VAPID keys, minting them on first use.

    Regenerating the keypair silently invalidates every subscription a user has
    already made, so an existing file is always preferred — including one whose
    subject differs from the argument.
    """
    path = path or _vapid_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("public_key") and data.get("private_key"):
            return VapidKeys(public_key=data["public_key"], private_key=data["private_key"], subject=data.get("subject") or subject)
    except (OSError, json.JSONDecodeError):
        pass

    keys = generate_vapid_keys(subject)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Opened 0600 rather than chmod'ed afterwards: the private key must never
    # exist world-readable, not even briefly.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"public_key": keys.public_key, "private_key": keys.private_key, "subject": keys.subject}, handle, indent=2)
    logger.info("web push: generated a new VAPID keypair at %s", path)
    return keys


def push_availability() -> tuple[bool, str]:
    """Whether this install can send a push, and why not when it cannot."""
    try:
        import pywebpush  # noqa: F401
    except ImportError:
        return False, "The `pywebpush` package is not installed. Run `cd backend && uv sync --extra webpush` to enable push notifications."
    return True, ""


def _truncate_payload(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    if len(body.encode("utf-8")) <= MAX_PAYLOAD_BYTES:
        return body
    trimmed = dict(payload)
    text = str(trimmed.get("body") or "")
    # Cut the body, never the title or the URL: a notification with no body is
    # still actionable, one with no title or link is not.
    trimmed["body"] = text[: max(0, MAX_PAYLOAD_BYTES // 2)] + "…"
    return json.dumps(trimmed, ensure_ascii=False)


def send_push(subscription: dict[str, Any], payload: dict[str, Any], keys: VapidKeys, *, timeout: float = 10.0) -> tuple[bool, bool]:
    """Deliver one notification.

    Returns ``(delivered, subscription_is_gone)``. The second flag is the useful
    one: a 404/410 means the browser discarded this subscription and it should
    be forgotten, while any other failure is transient and the subscription is
    kept.
    """
    available, reason = push_availability()
    if not available:
        raise WebPushUnavailable(reason)

    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=subscription,
            data=_truncate_payload(payload),
            vapid_private_key=keys.private_key,
            vapid_claims={"sub": keys.subject},
            timeout=timeout,
        )
        return True, False
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            logger.info("web push: subscription is gone (%s); dropping it", status)
            return False, True
        logger.warning("web push: delivery failed (%s)", exc)
        return False, False
    except Exception as exc:  # a broken subscription must never fail a run
        logger.warning("web push: unexpected delivery error (%s)", exc)
        return False, False


def notify_user(user_id: str, payload: dict[str, Any]) -> int:
    """Push *payload* to every device the user opted in from.

    Returns the number of successful deliveries. Never raises: this is called
    from the run-completion path, where a failed notification must not turn a
    successful run into a failed one.
    """
    from deerflow.config.user_ui_state import get_push_subscriptions, remove_push_subscription

    try:
        subscriptions = get_push_subscriptions(user_id)
    except Exception:
        logger.warning("web push: could not read subscriptions for %r", user_id, exc_info=True)
        return 0
    if not subscriptions:
        return 0

    try:
        keys = load_or_create_vapid_keys()
    except Exception:
        logger.warning("web push: no usable VAPID keys", exc_info=True)
        return 0

    delivered = 0
    for subscription in subscriptions:
        try:
            ok, gone = send_push(subscription, payload, keys)
        except WebPushUnavailable as exc:
            logger.info("web push: %s", exc)
            return delivered
        except Exception:
            logger.warning("web push: delivery raised", exc_info=True)
            continue
        if ok:
            delivered += 1
        elif gone:
            try:
                remove_push_subscription(user_id, subscription["endpoint"])
            except Exception:
                logger.warning("web push: could not prune a dead subscription", exc_info=True)
    return delivered
