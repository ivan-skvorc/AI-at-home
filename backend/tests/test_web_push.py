"""Tests for Web Push delivery and subscription storage (roadmap item 7).

The fork's premise is "start a run from my phone over Tailscale, pocket it, get
pinged when it's done". That needs a notification with the browser closed, which
is why this exists at all.

The behaviors worth pinning are the ones that are silent when wrong: VAPID keys
that get regenerated (invalidating every subscription), a private key that lands
world-readable, a dead subscription that is never pruned, and a notification
failure that takes a successful run down with it.
"""

from __future__ import annotations

import json
import stat
from datetime import datetime, timedelta

import pytest

from app.gateway import web_push
from app.gateway.run_notifications import MIN_RUN_SECONDS, build_run_notification, notify_run_completed
from deerflow.config import user_ui_state


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    from deerflow.config import paths

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    paths.get_paths.cache_clear() if hasattr(paths.get_paths, "cache_clear") else None
    user_ui_state.reset_cache_for_tests()
    yield
    user_ui_state.reset_cache_for_tests()


SUBSCRIPTION = {
    "endpoint": "https://push.example.com/abc",
    "keys": {"p256dh": "BPublicKey", "auth": "AuthSecret"},
}


# ---------------------------------------------------------------------------
# VAPID keys
# ---------------------------------------------------------------------------


class TestVapidKeys:
    def test_generated_keys_are_base64url_without_padding(self):
        keys = web_push.generate_vapid_keys()
        assert "=" not in keys.public_key and "=" not in keys.private_key
        assert "+" not in keys.public_key and "/" not in keys.public_key

    def test_keys_are_reused_across_calls(self, tmp_path):
        # Regenerating silently invalidates every subscription a user has made.
        path = tmp_path / "vapid.json"
        first = web_push.load_or_create_vapid_keys(path=path)
        second = web_push.load_or_create_vapid_keys(path=path)
        assert first.public_key == second.public_key
        assert first.private_key == second.private_key

    def test_an_existing_file_wins_over_the_requested_subject(self, tmp_path):
        path = tmp_path / "vapid.json"
        first = web_push.load_or_create_vapid_keys("mailto:a@example.com", path=path)
        second = web_push.load_or_create_vapid_keys("mailto:b@example.com", path=path)
        assert second.public_key == first.public_key
        assert second.subject == "mailto:a@example.com"

    def test_the_private_key_file_is_owner_only(self, tmp_path):
        path = tmp_path / "vapid.json"
        web_push.load_or_create_vapid_keys(path=path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_a_corrupt_key_file_is_replaced_rather_than_fatal(self, tmp_path):
        path = tmp_path / "vapid.json"
        path.write_text("{not json", encoding="utf-8")
        keys = web_push.load_or_create_vapid_keys(path=path)
        assert keys.public_key
        assert json.loads(path.read_text(encoding="utf-8"))["public_key"] == keys.public_key


# ---------------------------------------------------------------------------
# Subscription storage
# ---------------------------------------------------------------------------


class TestSubscriptionStore:
    def test_round_trip(self):
        user_ui_state.add_push_subscription("default", SUBSCRIPTION)
        stored = user_ui_state.get_push_subscriptions("default")
        assert len(stored) == 1
        assert stored[0]["endpoint"] == SUBSCRIPTION["endpoint"]

    def test_resubscribing_the_same_endpoint_replaces_rather_than_duplicates(self):
        user_ui_state.add_push_subscription("default", SUBSCRIPTION)
        user_ui_state.add_push_subscription("default", {**SUBSCRIPTION, "label": "Chrome on Linux"})
        stored = user_ui_state.get_push_subscriptions("default")
        assert len(stored) == 1
        assert stored[0]["label"] == "Chrome on Linux"

    def test_several_devices_coexist(self):
        user_ui_state.add_push_subscription("default", SUBSCRIPTION)
        user_ui_state.add_push_subscription("default", {**SUBSCRIPTION, "endpoint": "https://push.example.com/phone"})
        assert len(user_ui_state.get_push_subscriptions("default")) == 2

    def test_the_newest_device_is_never_the_one_evicted_at_the_cap(self):
        for index in range(user_ui_state.MAX_PUSH_SUBSCRIPTIONS + 3):
            user_ui_state.add_push_subscription("default", {**SUBSCRIPTION, "endpoint": f"https://push.example.com/{index}"})
        stored = user_ui_state.get_push_subscriptions("default")
        assert len(stored) == user_ui_state.MAX_PUSH_SUBSCRIPTIONS
        # The device the user just opted in from is the one they are looking at.
        assert stored[-1]["endpoint"].endswith(f"/{user_ui_state.MAX_PUSH_SUBSCRIPTIONS + 2}")

    def test_a_non_https_endpoint_is_dropped(self):
        user_ui_state.add_push_subscription("default", {**SUBSCRIPTION, "endpoint": "http://push.example.com/abc"})
        assert user_ui_state.get_push_subscriptions("default") == []

    def test_a_subscription_without_keys_is_dropped(self):
        user_ui_state.add_push_subscription("default", {"endpoint": "https://push.example.com/x"})
        assert user_ui_state.get_push_subscriptions("default") == []

    def test_removing_by_endpoint(self):
        user_ui_state.add_push_subscription("default", SUBSCRIPTION)
        user_ui_state.remove_push_subscription("default", SUBSCRIPTION["endpoint"])
        assert user_ui_state.get_push_subscriptions("default") == []

    def test_push_state_and_chat_tabs_share_the_file_without_clobbering(self):
        # Both live in one JSON bag; a writer that knows only one must not
        # delete the other.
        user_ui_state.set_chat_tabs("default", [{"key": "k", "threadId": "t"}])
        user_ui_state.add_push_subscription("default", SUBSCRIPTION)
        assert len(user_ui_state.get_chat_tabs("default")) == 1
        assert len(user_ui_state.get_push_subscriptions("default")) == 1


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


class TestNotifyUser:
    def test_no_subscriptions_is_a_no_op(self):
        assert web_push.notify_user("default", {"title": "x"}) == 0

    def test_delivers_to_every_registered_device(self, monkeypatch):
        user_ui_state.add_push_subscription("default", SUBSCRIPTION)
        user_ui_state.add_push_subscription("default", {**SUBSCRIPTION, "endpoint": "https://push.example.com/phone"})
        monkeypatch.setattr(web_push, "send_push", lambda *a, **k: (True, False))
        assert web_push.notify_user("default", {"title": "x"}) == 2

    def test_a_dead_subscription_is_pruned(self, monkeypatch):
        user_ui_state.add_push_subscription("default", SUBSCRIPTION)
        # A push service 410s a subscription the browser discarded; nothing else
        # ever cleans those up.
        monkeypatch.setattr(web_push, "send_push", lambda *a, **k: (False, True))
        assert web_push.notify_user("default", {"title": "x"}) == 0
        assert user_ui_state.get_push_subscriptions("default") == []

    def test_a_transient_failure_keeps_the_subscription(self, monkeypatch):
        user_ui_state.add_push_subscription("default", SUBSCRIPTION)
        monkeypatch.setattr(web_push, "send_push", lambda *a, **k: (False, False))
        assert web_push.notify_user("default", {"title": "x"}) == 0
        assert len(user_ui_state.get_push_subscriptions("default")) == 1

    def test_a_missing_dependency_stops_cleanly_rather_than_raising(self, monkeypatch):
        user_ui_state.add_push_subscription("default", SUBSCRIPTION)

        def unavailable(*args, **kwargs):
            raise web_push.WebPushUnavailable("pywebpush is not installed")

        monkeypatch.setattr(web_push, "send_push", unavailable)
        assert web_push.notify_user("default", {"title": "x"}) == 0

    def test_an_unexpected_error_never_escapes(self, monkeypatch):
        user_ui_state.add_push_subscription("default", SUBSCRIPTION)
        monkeypatch.setattr(web_push, "send_push", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert web_push.notify_user("default", {"title": "x"}) == 0

    def test_availability_reports_the_install_hint_when_the_extra_is_missing(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "pywebpush":
                raise ImportError("no module")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        available, reason = web_push.push_availability()
        assert available is False
        assert "uv sync --extra webpush" in reason


# ---------------------------------------------------------------------------
# Run-completion notification
# ---------------------------------------------------------------------------


class _Record:
    def __init__(self, seconds: float, status: str = "success", thread_id: str = "t1", user_id: str = "default"):
        self.created_at = datetime(2026, 1, 1, 12, 0, 0)
        self.updated_at = self.created_at + timedelta(seconds=seconds)
        self.status = type("S", (), {"value": status})()
        self.thread_id = thread_id
        self.user_id = user_id


class TestRunNotification:
    def test_a_short_run_is_not_worth_interrupting_for(self):
        assert build_run_notification(_Record(2)) is None

    def test_a_long_run_produces_a_payload(self):
        payload = build_run_notification(_Record(MIN_RUN_SECONDS + 90))
        assert payload is not None
        assert payload["title"] == "Run finished"
        assert "min" in payload["body"]

    def test_the_payload_deep_links_to_the_conversation(self):
        payload = build_run_notification(_Record(120, thread_id="abc"))
        assert payload["url"] == "/chat/abc"
        # One notification per thread — a re-run replaces rather than stacks.
        assert payload["tag"] == "deerflow-run-abc"

    def test_a_failed_run_says_so(self):
        payload = build_run_notification(_Record(120, status="error"))
        assert "error" in payload["body"]
        assert payload["title"] != "Run finished"

    def test_an_unknown_duration_is_treated_as_short(self):
        # A missed notification costs less than a stream of unwanted ones.
        record = _Record(120)
        record.updated_at = None
        assert build_run_notification(record) is None

    def test_delivery_never_raises_out_of_the_completion_path(self, monkeypatch):
        def explode(*args, **kwargs):
            raise RuntimeError("push service down")

        monkeypatch.setattr(web_push, "notify_user", explode)
        assert notify_run_completed(_Record(120)) == 0

    def test_a_run_with_no_owner_is_skipped(self):
        record = _Record(120)
        record.user_id = None
        assert notify_run_completed(record) == 0
