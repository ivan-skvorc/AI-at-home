"""Push a notification when a run finishes (fork feature).

The fork's use case is "start a run from my phone over Tailscale, pocket it, get
pinged when it's done". That needs the notification to arrive with the browser
closed, which the plain `Notification` API cannot do — hence Web Push and a
service worker.

Two judgement calls live here rather than in the transport layer:

**Only runs worth interrupting for.** A notification for a two-second question
is noise, and noise is how a user turns notifications off for good. Only runs
past :data:`MIN_RUN_SECONDS` are announced — by then the user has almost
certainly switched away, which is exactly when a push is useful.

**Never fail a run.** This hook runs on the completion path; a push service
outage, a missing dependency, or a malformed subscription must leave the run
exactly as successful as it was.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Below this, the user was almost certainly still watching. Chosen to be longer
# than an ordinary chat turn and shorter than anything that involves a sandbox.
MIN_RUN_SECONDS = 30.0

# A notification is a nudge; the answer is in the app.
MAX_TITLE_CHARS = 80
MAX_BODY_CHARS = 200


def _elapsed_seconds(record: Any) -> float | None:
    started, finished = getattr(record, "created_at", None), getattr(record, "updated_at", None)
    if started is None or finished is None:
        return None
    try:
        return max(0.0, (finished - started).total_seconds())
    except (TypeError, AttributeError):
        return None


def build_run_notification(record: Any, *, min_seconds: float = MIN_RUN_SECONDS) -> dict[str, Any] | None:
    """The payload for a finished run, or ``None`` when it is not worth sending.

    Returns ``None`` for short runs and for runs whose elapsed time cannot be
    determined — an unknown duration is treated as "probably short", because a
    missed notification costs less than a stream of unwanted ones.
    """
    elapsed = _elapsed_seconds(record)
    if elapsed is None or elapsed < min_seconds:
        return None

    status = getattr(getattr(record, "status", None), "value", None) or str(getattr(record, "status", "") or "")
    thread_id = getattr(record, "thread_id", None)
    title = "Run finished" if status == "success" else f"Run {status or 'ended'}"

    minutes = int(elapsed // 60)
    duration = f"{minutes} min" if minutes else f"{int(elapsed)}s"
    body = f"Your conversation finished after {duration}."
    if status and status != "success":
        body = f"Your conversation ended with status '{status}' after {duration}."

    return {
        "title": title[:MAX_TITLE_CHARS],
        "body": body[:MAX_BODY_CHARS],
        # Deep-link straight to the conversation: a notification that only opens
        # the app makes the user hunt for what it was about.
        "url": f"/chat/{thread_id}" if thread_id else "/",
        # One notification per thread — a re-run replaces rather than stacks.
        "tag": f"deerflow-run-{thread_id}" if thread_id else "deerflow-run",
    }


def notify_run_completed(record: Any) -> int:
    """Deliver the finished-run notification. Never raises."""
    try:
        payload = build_run_notification(record)
        if payload is None:
            return 0
        user_id = getattr(record, "user_id", None)
        if not user_id:
            return 0
        from app.gateway.web_push import notify_user

        return notify_user(user_id, payload)
    except Exception:
        logger.warning("run notification failed (non-fatal)", exc_info=True)
        return 0
