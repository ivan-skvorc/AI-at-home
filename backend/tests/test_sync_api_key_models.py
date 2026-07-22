"""Tests for scripts/sync-api-key-models.py.

The script is a text-surgery editor that *uncomments* the Anthropic / OpenRouter
model blocks in config.yaml (between BEGIN/END auto-model-config markers) when
the matching API key is present in .env. These tests pin:
- key detection ignores placeholders / unresolved "$VAR" / empty values;
- uncommenting produces valid YAML matching the block, and only for present keys;
- it is idempotent, never re-comments, skips already-active blocks, and no-ops
  when the markers are absent;
- the real config.example.yaml block round-trips to valid, correct YAML;
- it refuses to edit a config with duplicate top-level keys.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sync-api-key-models.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("sync_api_key_models", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync_api = _load_script()

# A miniature config carrying both marker blocks in the same commented shape the
# real config.example.yaml uses.
SAMPLE_CONFIG = """config_version: 1
models:
  # QUICK START prose that must never be uncommented.
  # === BEGIN auto-model-config: anthropic (uncommented at startup when ANTHROPIC_API_KEY is set) ===
  # - name: claude-opus-4-8
  #   display_name: Claude Opus 4.8
  #   use: langchain_anthropic:ChatAnthropic
  #   model: claude-opus-4-8
  #   api_key: $ANTHROPIC_API_KEY
  #   max_tokens: 32000
  #   supports_vision: true
  # === END auto-model-config: anthropic ===

  # === BEGIN auto-model-config: openrouter (uncommented at startup when OPENROUTER_API_KEY is set) ===
  # - name: openrouter-fable-5
  #   display_name: Claude Fable 5 (OpenRouter)
  #   use: langchain_openai:ChatOpenAI
  #   model: anthropic/claude-fable-5
  #   api_key: $OPENROUTER_API_KEY
  #   base_url: https://openrouter.ai/api/v1
  #   max_tokens: 32000
  #   supports_vision: true
  # === END auto-model-config: openrouter ===
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
"""


def _model_names(config_text: str) -> list[str]:
    data = yaml.safe_load(config_text)
    return [m["name"] for m in (data.get("models") or [])]


class TestKeyDetection:
    @pytest.mark.parametrize("value", ["sk-ant-realkey123", "or-1234567890", "abc"])
    def test_real_keys_detected(self, value):
        assert sync_api.looks_like_real_key(value) is True

    @pytest.mark.parametrize(
        "value",
        [None, "", "   ", "your-anthropic-api-key", "your_openrouter_key", "$ANTHROPIC_API_KEY", "<paste-key-here>"],
    )
    def test_placeholders_rejected(self, value):
        assert sync_api.looks_like_real_key(value) is False

    def test_env_file_parsing(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text('ANTHROPIC_API_KEY=sk-ant-xyz\nexport OPENROUTER_API_KEY="or-abc"\n# comment\nSERPER_API_KEY=your-serper-api-key\n')
        values = sync_api.parse_env_file(env)
        assert values["ANTHROPIC_API_KEY"] == "sk-ant-xyz"
        assert values["OPENROUTER_API_KEY"] == "or-abc"
        assert values["SERPER_API_KEY"] == "your-serper-api-key"

    def test_missing_env_file_is_empty(self, tmp_path):
        assert sync_api.parse_env_file(tmp_path / "nope.env") == {}


class TestUncomment:
    def test_anthropic_only(self):
        out = sync_api.sync(SAMPLE_CONFIG, {"anthropic"})
        assert _model_names(out) == ["claude-opus-4-8"]
        # OpenRouter block stayed commented.
        assert "  # - name: openrouter-fable-5" in out
        # Markers themselves stay commented.
        assert "# === BEGIN auto-model-config: anthropic" in out

    def test_openrouter_only(self):
        out = sync_api.sync(SAMPLE_CONFIG, {"openrouter"})
        assert _model_names(out) == ["openrouter-fable-5"]
        assert "  # - name: claude-opus-4-8" in out

    def test_both_keys(self):
        out = sync_api.sync(SAMPLE_CONFIG, {"anthropic", "openrouter"})
        assert _model_names(out) == ["claude-opus-4-8", "openrouter-fable-5"]

    def test_no_keys_is_noop(self):
        out = sync_api.sync(SAMPLE_CONFIG, set())
        assert out == SAMPLE_CONFIG

    def test_uncommented_yaml_is_valid_and_typed(self):
        out = sync_api.sync(SAMPLE_CONFIG, {"anthropic"})
        data = yaml.safe_load(out)
        entry = data["models"][0]
        assert entry["model"] == "claude-opus-4-8"
        assert entry["max_tokens"] == 32000  # stays an int, not a string
        assert entry["supports_vision"] is True

    def test_prose_comment_not_uncommented(self):
        out = sync_api.sync(SAMPLE_CONFIG, {"anthropic", "openrouter"})
        assert "  # QUICK START prose that must never be uncommented." in out

    def test_idempotent(self):
        once = sync_api.sync(SAMPLE_CONFIG, {"anthropic", "openrouter"})
        twice = sync_api.sync(once, {"anthropic", "openrouter"})
        assert once == twice

    def test_already_active_block_is_skipped(self):
        # First run activates anthropic; a second run must not duplicate it.
        once = sync_api.sync(SAMPLE_CONFIG, {"anthropic"})
        twice = sync_api.sync(once, {"anthropic"})
        assert _model_names(twice) == ["claude-opus-4-8"]

    def test_missing_markers_is_noop(self):
        text = "config_version: 1\nmodels:\n  - name: hand\n    model: x\nsandbox:\n  use: y\n"
        assert sync_api.sync(text, {"anthropic", "openrouter"}) == text

    def test_trailing_newline_preserved(self):
        assert sync_api.sync(SAMPLE_CONFIG, {"anthropic"}).endswith("\n")


class TestUncommentLine:
    def test_list_item(self):
        assert sync_api.uncomment_line("  # - name: x") == "  - name: x"

    def test_nested_key(self):
        assert sync_api.uncomment_line("  #   display_name: X") == "    display_name: X"

    def test_blank_separator_collapses(self):
        assert sync_api.uncomment_line("  #") == ""

    def test_inline_comment_preserved(self):
        # Only the leading "# " is stripped; the trailing YAML comment survives.
        assert sync_api.uncomment_line("  #       budget_tokens: 4096   # required") == "        budget_tokens: 4096   # required"

    def test_already_uncommented_unchanged(self):
        assert sync_api.uncomment_line("    display_name: X") == "    display_name: X"


class TestRealExampleConfig:
    """The shipped config.example.yaml blocks must round-trip to correct YAML."""

    def setup_method(self):
        self.text = (REPO_ROOT / "config.example.yaml").read_text()

    def test_both_blocks_present(self):
        assert sync_api.find_block(self.text.splitlines(), "anthropic") is not None
        assert sync_api.find_block(self.text.splitlines(), "openrouter") is not None

    def test_anthropic_block_enables_expected_models(self):
        out = sync_api.sync(self.text, {"anthropic"})
        data = yaml.safe_load(out)
        names = {m["model"] for m in data["models"]}
        assert {"claude-fable-5", "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"}.issubset(names)
        assert all(m["api_key"] == "$ANTHROPIC_API_KEY" for m in data["models"])

    def test_fable_5_omits_disabled_thinking_but_opus_sonnet_keep_it(self):
        """Fable 5 rejects `thinking: {type: disabled}` with a 400, so the shipped
        config must leave its `when_thinking_disabled` empty (the model factory then
        omits the parameter). Opus 4.8 / Sonnet 5 accept `type: disabled` and keep it.
        Regression guard against re-introducing the 400 on the disable path."""
        out = sync_api.sync(self.text, {"anthropic"})
        data = yaml.safe_load(out)
        by_model = {m["model"]: m for m in data["models"]}

        fable_disabled = by_model["claude-fable-5"].get("when_thinking_disabled") or {}
        assert not fable_disabled, f"Fable 5 must omit thinking when disabled, got {fable_disabled!r}"

        for slug in ("claude-opus-4-8", "claude-sonnet-5"):
            disabled = by_model[slug].get("when_thinking_disabled") or {}
            assert disabled.get("thinking", {}).get("type") == "disabled", slug

    def test_openrouter_block_enables_expected_models(self):
        out = sync_api.sync(self.text, {"openrouter"})
        data = yaml.safe_load(out)
        ids = {m["model"] for m in data["models"]}
        expected = {
            "anthropic/claude-fable-5",
            "x-ai/grok-4.5",
            "openai/gpt-5.5",
            "openai/gpt-5.5-codex",
            "google/gemini-3.5-pro",
            "google/gemini-3.5-flash",
            "meta-llama/llama-4-maverick",
            "minimax/minimax-m3",
            "qwen/qwen3.7-max",
            "moonshotai/kimi-k3",
            "mistralai/mistral-large-2512",
            "deepseek/deepseek-v4-pro",
            "z-ai/glm-5.2",
            "nvidia/nemotron-3-ultra-550b-a55b",
        }
        assert expected == ids
        assert all(m["api_key"] == "$OPENROUTER_API_KEY" for m in data["models"])

    def test_example_config_default_state_has_no_active_models(self):
        # Without any key, the example config stays fully commented (0 models).
        assert sync_api.sync(self.text, set()) == self.text
        data = yaml.safe_load(self.text)
        assert (data.get("models") or []) == []


class TestDuplicateTopLevelKeys:
    def test_duplicate_models_aborts(self):
        text = "models: []\nsandbox:\n  use: a\nmodels: []\n"
        with pytest.raises(SystemExit) as excinfo:
            sync_api.check_duplicate_top_level_keys(text, "config.yaml")
        assert "duplicate top-level key 'models'" in str(excinfo.value)

    def test_clean_config_passes(self):
        sync_api.check_duplicate_top_level_keys(SAMPLE_CONFIG, "config.yaml")
