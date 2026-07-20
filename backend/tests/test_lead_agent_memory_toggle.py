"""Tests for the per-user memory opt-out in the lead-agent factory.

The Web UI sends a per-run ``memory_enabled`` flag (Settings → Memory, off by
default on a fresh install). ``_apply_memory_preference`` turns that flag into a
per-run AppConfig with memory fully disabled, from a single chokepoint, so
injection / extraction / memory tools all skip memory for the run. The operator
master switch (``memory.enabled`` in config.yaml) still wins — the flag can only
opt out, never force memory on.
"""

from __future__ import annotations

from deerflow.agents.lead_agent.agent import _apply_memory_preference
from deerflow.config.app_config import AppConfig
from deerflow.config.memory_config import MemoryConfig, should_use_memory_tools
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig


def _make_app_config(memory: MemoryConfig) -> AppConfig:
    return AppConfig(
        models=[
            ModelConfig(
                name="m",
                display_name="m",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="m",
                supports_thinking=False,
                supports_vision=False,
            )
        ],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        memory=memory,
    )


def test_override_false_disables_injection_and_extraction():
    cfg = _make_app_config(MemoryConfig(enabled=True, injection_enabled=True))
    out = _apply_memory_preference(cfg, False)
    assert out.memory.enabled is False
    assert out.memory.injection_enabled is False
    # Original config is untouched (per-run copy, not mutation).
    assert cfg.memory.enabled is True
    assert cfg.memory.injection_enabled is True


def test_override_false_disables_memory_tools():
    cfg = _make_app_config(MemoryConfig(enabled=True, mode="tool", injection_enabled=True))
    assert should_use_memory_tools(cfg.memory) is True
    out = _apply_memory_preference(cfg, False)
    assert should_use_memory_tools(out.memory) is False


def test_override_absent_keeps_operator_config():
    cfg = _make_app_config(MemoryConfig(enabled=True, injection_enabled=True))
    # None / missing flag → non-web callers keep legacy behavior (unchanged object).
    assert _apply_memory_preference(cfg, None) is cfg


def test_override_true_keeps_operator_config():
    cfg = _make_app_config(MemoryConfig(enabled=True, injection_enabled=True))
    # Truthy opt-in does not rebuild the config; operator config already governs.
    assert _apply_memory_preference(cfg, True) is cfg


def test_override_true_cannot_force_memory_on_when_operator_disabled():
    # Operator master switch off; a per-user opt-in must not turn memory on.
    cfg = _make_app_config(MemoryConfig(enabled=False, injection_enabled=False))
    out = _apply_memory_preference(cfg, True)
    assert out.memory.enabled is False


def test_non_boolean_override_is_treated_as_no_optout():
    # Only an explicit boolean False opts out; other truthy/None values keep config.
    cfg = _make_app_config(MemoryConfig(enabled=True, injection_enabled=True))
    assert _apply_memory_preference(cfg, "false") is cfg
    assert _apply_memory_preference(cfg, 0) is cfg
