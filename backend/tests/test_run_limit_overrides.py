"""Settings → Run limits: UI overrides of config.yaml's run-ending limits (FORK.md §46).

Pins three properties that are silent when broken:

* an override reaches every place a run reads the limit — the lead chain, the
  subagent chain, spend admission/status and the Gateway's step default — so a
  saved change is what the next run enforces;
* a section is a complete replacement: YAML per-tool loop limits and separate
  input/output token budgets cannot keep stopping a run the page shows as
  allowed;
* writes are admin-only, and a stored section that no longer validates falls
  back to config.yaml instead of breaking every run.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.gateway import spend_budget as sb
from app.gateway.routers.settings import get_run_limits_setting, update_run_limits_setting
from deerflow.agents.lead_agent.agent import build_middlewares
from deerflow.agents.middlewares.loop_detection_middleware import LoopDetectionMiddleware
from deerflow.agents.middlewares.token_budget_middleware import TokenBudgetMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
from deerflow.config import run_limit_overrides as rlo
from deerflow.config import runtime_settings
from deerflow.config.app_config import AppConfig
from deerflow.config.loop_detection_config import LoopDetectionConfig, ToolFreqOverride
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.spend_budget_config import SpendBudgetConfig
from deerflow.config.token_budget_config import TokenBudgetConfig

ADMIN = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
MEMBER = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="user")))

TOOL_LIMITS = {"enabled": True, "warn_threshold": 4, "hard_limit": 8, "tool_freq_warn": 400, "tool_freq_hard_limit": 500}


@pytest.fixture(autouse=True)
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "runtime_settings.json"
    monkeypatch.setattr(runtime_settings, "_settings_path", lambda: path)
    # conftest isolates every other test from saved overrides; these re-bind the real reader.
    monkeypatch.setattr(rlo, "get_runtime_setting", runtime_settings.get_runtime_setting)
    runtime_settings.reset_cache_for_tests()
    yield path
    runtime_settings.reset_cache_for_tests()


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _save(**sections) -> None:
    rlo.set_run_limit_overrides(rlo.RunLimitOverrides.model_validate(sections))


def _config(**fields) -> AppConfig:
    return AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"), **fields)


class TestEffectiveLimits:
    def test_without_overrides_config_yaml_applies_unchanged(self):
        base = LoopDetectionConfig(tool_freq_warn=7, tool_freq_hard_limit=9)
        assert rlo.effective_loop_detection(base) is base
        assert rlo.effective_recursion_limit(250) == 250

    def test_spend_override_replaces_switch_and_every_window(self):
        _save(spend_budget={"enabled": True, "weekly_limit": 20.0})
        effective = rlo.effective_spend_budget(SpendBudgetConfig(enabled=False, daily_limit=5.0, window="calendar"))
        assert effective.enabled is True
        # The daily cap the page does not show is cleared, not kept.
        assert effective.limits() == (("weekly", 20.0),)
        assert effective.window == "calendar"

    def test_turning_the_spend_cap_off_disables_a_yaml_cap(self):
        _save(spend_budget={"enabled": False})
        assert rlo.effective_spend_budget(SpendBudgetConfig(enabled=True, daily_limit=5.0)).enabled is False

    def test_spend_cap_on_without_an_amount_is_rejected(self):
        with pytest.raises(ValidationError):
            rlo.RunLimitOverrides.model_validate({"spend_budget": {"enabled": True}})

    def test_tool_limits_apply_to_every_tool_while_set(self):
        _save(loop_detection=TOOL_LIMITS)
        base = LoopDetectionConfig(tool_freq_overrides={"bash": ToolFreqOverride(warn=30, hard_limit=50)})
        effective = rlo.effective_loop_detection(base)
        assert (effective.tool_freq_warn, effective.tool_freq_hard_limit) == (400, 500)
        assert effective.tool_freq_overrides == {}

    def test_token_override_drops_the_separate_input_and_output_budgets(self):
        _save(token_budget={"enabled": True, "max_tokens": 5_000_000})
        effective = rlo.effective_token_budget(TokenBudgetConfig(enabled=False, max_tokens=200_000, max_input_tokens=100_000, max_output_tokens=10_000))
        assert (effective.enabled, effective.max_tokens, effective.max_input_tokens, effective.max_output_tokens) == (True, 5_000_000, None, None)

    @pytest.mark.parametrize("bad", [{"enabled": "yes", "max_tokens": 5000}, {"enabled": True, "max_tokens": True}, {"enabled": True, "max_tokens": 10}])
    def test_token_override_rejects_non_strict_values(self, bad):
        with pytest.raises(ValidationError):
            rlo.RunLimitOverrides.model_validate({"token_budget": bad})

    def test_an_invalid_stored_section_is_ignored_and_the_rest_kept(self, settings_file):
        settings_file.write_text(json.dumps({"run_limits": {"loop_detection": {"enabled": "maybe"}, "recursion_limit": 600}}), encoding="utf-8")
        runtime_settings.reset_cache_for_tests()
        overrides = rlo.get_run_limit_overrides()
        assert overrides.loop_detection is None
        assert overrides.recursion_limit == 600

    def test_saving_keeps_other_runtime_settings(self, settings_file):
        runtime_settings.set_multi_user_mode(False)
        _save(recursion_limit=600)
        _save()
        assert runtime_settings.is_multi_user_mode_enabled() is False
        assert "run_limits" not in json.loads(settings_file.read_text(encoding="utf-8"))


class TestRunsReadTheOverride:
    def test_lead_chain_drops_loop_detection_when_turned_off(self):
        app_config = _config()
        assemble = lambda: build_middlewares({"configurable": {}}, model_name=None, app_config=app_config, memory_enabled=False, available_skills=set())  # noqa: E731
        assert any(isinstance(m, LoopDetectionMiddleware) for m in assemble())
        _save(loop_detection={**TOOL_LIMITS, "enabled": False})
        assert not any(isinstance(m, LoopDetectionMiddleware) for m in assemble())

    def test_lead_chain_uses_the_saved_tool_limits_and_token_budget(self):
        _save(loop_detection=TOOL_LIMITS, token_budget={"enabled": True, "max_tokens": 3_000_000})
        chain = build_middlewares({"configurable": {}}, model_name=None, app_config=_config(), memory_enabled=False, available_skills=set())
        loop = next(m for m in chain if isinstance(m, LoopDetectionMiddleware))
        assert (loop.tool_freq_warn, loop.tool_freq_hard_limit, loop.hard_limit) == (400, 500, 8)
        budget = next(m for m in chain if isinstance(m, TokenBudgetMiddleware))
        assert budget._config.max_tokens == 3_000_000

    def test_subagent_chain_uses_the_saved_limits(self):
        app_config = _config()
        assert any(isinstance(m, TokenBudgetMiddleware) for m in build_subagent_runtime_middlewares(app_config=app_config))
        _save(loop_detection=TOOL_LIMITS, subagent_token_budget={"enabled": False, "max_tokens": 1_000_000})
        chain = build_subagent_runtime_middlewares(app_config=app_config)
        assert not any(isinstance(m, TokenBudgetMiddleware) for m in chain)
        assert next(m for m in chain if isinstance(m, LoopDetectionMiddleware)).tool_freq_hard_limit == 500

    def test_spend_admission_honours_the_off_switch(self, monkeypatch):
        monkeypatch.setattr(sb, "get_session_factory", lambda: None)
        priced = SimpleNamespace(name="p", model="p-1", display_name="P", pricing={"currency": "USD", "input_per_million": 1.0, "output_per_million": 1.0})
        app_config = SimpleNamespace(models=[priced], spend_budget=SpendBudgetConfig(enabled=True, daily_limit=1.0))
        before = asyncio.run(sb.resolve_spend_budget_status(app_config=app_config, user_id=None))
        assert before.disabled_reason == sb.DISABLED_NO_DATABASE  # YAML cap is on; only history is missing
        _save(spend_budget={"enabled": False})
        after = asyncio.run(sb.resolve_spend_budget_status(app_config=app_config, user_id=None))
        assert after.disabled_reason == sb.DISABLED_NOT_CONFIGURED

    def test_gateway_step_default_follows_the_override_and_stays_clamped(self, monkeypatch):
        from app.gateway import services

        monkeypatch.setattr(services, "get_app_config", lambda: _config(recursion_limit=250, max_recursion_limit=1000))
        _save(recursion_limit=800)
        assert services.build_run_config("t1", None, None)["recursion_limit"] == 800
        _save(recursion_limit=5000)
        assert services.build_run_config("t1", None, None)["recursion_limit"] == 1000


class TestSettingsRoute:
    @pytest.fixture(autouse=True)
    def yaml_config(self, monkeypatch):
        import deerflow.config

        monkeypatch.setattr(deerflow.config, "get_app_config", lambda: _config())

    @pytest.mark.anyio
    async def test_admin_save_round_trips_and_null_restores_config_yaml(self):
        saved = await update_run_limits_setting(rlo.RunLimitOverrides.model_validate({"loop_detection": TOOL_LIMITS, "recursion_limit": 700}), ADMIN)
        assert saved.overrides.loop_detection is not None
        assert saved.effective.loop_detection.tool_freq_hard_limit == 500
        assert saved.effective.recursion_limit == min(700, saved.effective.max_recursion_limit)

        cleared = await update_run_limits_setting(rlo.RunLimitOverrides(), ADMIN)
        assert cleared.overrides == rlo.RunLimitOverrides()
        assert (await get_run_limits_setting()).effective.loop_detection.tool_freq_hard_limit != 500

    @pytest.mark.anyio
    async def test_non_admin_cannot_change_limits(self):
        with pytest.raises(HTTPException) as exc_info:
            await update_run_limits_setting(rlo.RunLimitOverrides.model_validate({"recursion_limit": 700}), MEMBER)
        assert exc_info.value.status_code == 403
        assert rlo.get_run_limit_overrides().recursion_limit is None
