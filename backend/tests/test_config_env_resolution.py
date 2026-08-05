"""Regression coverage for env-placeholder resolution in ``AppConfig``.

The forensic story behind these tests: after a git pull + ``make up`` (Docker
prod, AiO sandbox), ``http://localhost:2026`` returned a bare nginx **502**. The
gateway had hard-crashed on config load because ``resolve_env_variables`` raised
on an unset ``$SLACK_BOT_TOKEN`` — even though the ``channels.slack`` block that
referenced it was ``enabled: false``. A leftover placeholder for a feature the
operator never turned on should not take down the whole stack.

The fix keeps the strict, fail-loud behavior for *active* config (a missing API
key for an enabled model still raises), while a missing ``$VAR`` inside an
``enabled: false`` section resolves to an empty string with a warning. These
tests pin both halves so an upstream merge cannot silently re-introduce the
crash or, conversely, start swallowing genuinely-required missing vars.
"""

from __future__ import annotations

import pytest

from deerflow.config.app_config import AppConfig


class TestStrictResolution:
    """Active config keeps failing loudly on a missing env var."""

    def test_missing_var_in_ungated_section_raises(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        config = {"models": [{"name": "gpt", "api_key": "$OPENAI_API_KEY"}]}
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            AppConfig.resolve_env_variables(config)

    def test_missing_var_in_enabled_true_section_raises(self, monkeypatch):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        config = {"channels": {"slack": {"enabled": True, "bot_token": "$SLACK_BOT_TOKEN"}}}
        with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
            AppConfig.resolve_env_variables(config)

    def test_present_var_resolves(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-real")
        config = {"channels": {"slack": {"enabled": True, "bot_token": "$SLACK_BOT_TOKEN"}}}
        resolved = AppConfig.resolve_env_variables(config)
        assert resolved["channels"]["slack"]["bot_token"] == "xoxb-real"


class TestLenientDisabledSections:
    """A disabled (``enabled: false``) section no longer crashes on a missing var."""

    def test_missing_var_in_disabled_channel_resolves_to_empty(self, monkeypatch):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        config = {"channels": {"slack": {"enabled": False, "bot_token": "$SLACK_BOT_TOKEN"}}}
        resolved = AppConfig.resolve_env_variables(config)
        assert resolved["channels"]["slack"]["bot_token"] == ""

    def test_leniency_propagates_to_nested_dicts_and_lists(self, monkeypatch):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
        config = {
            "channels": {
                "slack": {
                    "enabled": False,
                    "bot_token": "$SLACK_BOT_TOKEN",
                    "session": {"context": {"app_token": "$SLACK_APP_TOKEN"}},
                    "allowed_users": ["$SLACK_BOT_TOKEN"],
                }
            }
        }
        resolved = AppConfig.resolve_env_variables(config)
        slack = resolved["channels"]["slack"]
        assert slack["bot_token"] == ""
        assert slack["session"]["context"]["app_token"] == ""
        assert slack["allowed_users"] == [""]

    def test_present_var_still_wins_in_disabled_section(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-real")
        config = {"channels": {"slack": {"enabled": False, "bot_token": "$SLACK_BOT_TOKEN"}}}
        resolved = AppConfig.resolve_env_variables(config)
        assert resolved["channels"]["slack"]["bot_token"] == "xoxb-real"

    def test_sibling_enabled_section_stays_strict(self, monkeypatch):
        """One disabled block does not relax a sibling enabled block."""
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        config = {
            "channels": {
                "slack": {"enabled": False, "bot_token": "$SLACK_BOT_TOKEN"},
                "telegram": {"enabled": True, "bot_token": "$TELEGRAM_BOT_TOKEN"},
            }
        }
        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
            AppConfig.resolve_env_variables(config)

    @pytest.mark.parametrize("disabled_value", [False, "false", "False", "no", "off", "0"])
    def test_string_and_bool_disabled_spellings(self, monkeypatch, disabled_value):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        config = {"channels": {"slack": {"enabled": disabled_value, "bot_token": "$SLACK_BOT_TOKEN"}}}
        resolved = AppConfig.resolve_env_variables(config)
        assert resolved["channels"]["slack"]["bot_token"] == ""


class TestSectionDisabledHelper:
    def test_explicit_true_is_not_disabled(self):
        assert AppConfig._is_section_disabled({"enabled": True}) is False

    def test_absent_enabled_is_not_disabled(self):
        assert AppConfig._is_section_disabled({"bot_token": "$X"}) is False

    def test_explicit_false_is_disabled(self):
        assert AppConfig._is_section_disabled({"enabled": False}) is True

    def test_non_bool_non_string_enabled_is_not_disabled(self):
        # A weird value (e.g. a dict) is treated as "not a clean disable" and
        # stays strict rather than silently swallowing missing vars.
        assert AppConfig._is_section_disabled({"enabled": {"weird": 1}}) is False
