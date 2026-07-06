"""Config-integrity tests: duplicate-key hard errors and unknown-key lint.

Covers the wiring of deerflow.config.yaml_guard into AppConfig.from_file and
the lint checks in deerflow.config.config_lint. Motivating incident: a
config.yaml with two top-level ``sandbox:`` keys silently reverted a user to
LocalSandboxProvider (YAML last-key-wins); the only symptom was "bash is
disabled" at runtime.
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pytest

from deerflow.config.app_config import AppConfig, reset_app_config
from deerflow.config.config_lint import lint_unknown_config_keys
from deerflow.config.yaml_guard import DuplicateKeyError, safe_load_guarded

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _reset_config():
    reset_app_config()
    yield
    reset_app_config()


class TestFromFileDuplicateKeys:
    def test_duplicate_top_level_sandbox_raises_with_both_line_numbers(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text(
            textwrap.dedent(
                """\
                sandbox:
                  use: deerflow.community.aio_sandbox:AioSandboxProvider
                models: []
                sandbox:
                  use: deerflow.sandbox.local:LocalSandboxProvider
                """
            ),
            encoding="utf-8",
        )
        with pytest.raises(DuplicateKeyError) as excinfo:
            AppConfig.from_file(str(config))
        message = str(excinfo.value)
        assert "duplicate top-level key 'sandbox'" in message
        assert "first defined at line 1" in message
        assert "duplicated at line 4" in message
        assert str(config) in message

    def test_clean_config_loads(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text(
            textwrap.dedent(
                """\
                sandbox:
                  use: deerflow.sandbox.local:LocalSandboxProvider
                models:
                  - name: gpt
                    use: langchain_openai:ChatOpenAI
                    model: gpt-test
                """
            ),
            encoding="utf-8",
        )
        loaded = AppConfig.from_file(str(config))
        assert loaded.models[0].name == "gpt"


class TestShippedExampleConfig:
    def test_example_config_has_no_duplicate_keys(self):
        example = REPO_ROOT / "config.example.yaml"
        with open(example, encoding="utf-8") as f:
            assert safe_load_guarded(f) is not None

    def test_example_config_passes_lint(self):
        example = REPO_ROOT / "config.example.yaml"
        with open(example, encoding="utf-8") as f:
            data = safe_load_guarded(f)
        assert lint_unknown_config_keys(data) == []


class TestSandboxKeyLint:
    def test_unknown_sandbox_key_warns_with_did_you_mean(self):
        warnings = lint_unknown_config_keys({"sandbox": {"use": "x", "allow_hostbash": True}})
        assert len(warnings) == 1
        assert "unknown key 'allow_hostbash' under sandbox:" in warnings[0]
        assert "did you mean 'allow_host_bash'" in warnings[0]

    def test_unknown_sandbox_key_without_close_match_still_warns(self):
        warnings = lint_unknown_config_keys({"sandbox": {"use": "x", "frobnicate": 1}})
        assert len(warnings) == 1
        assert "unknown key 'frobnicate' under sandbox:" in warnings[0]

    def test_declared_and_provider_specific_keys_do_not_warn(self):
        sandbox = {
            "use": "deerflow.community.aio_sandbox:AioSandboxProvider",
            "allow_host_bash": False,
            "image": "img",
            "port": 8080,
            "replicas": 3,
            "container_prefix": "p",
            "idle_timeout": 600,
            "mounts": [],
            "environment": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
            "bash_command_timeout": 600,
            # provider-specific keys read via getattr/model_extra
            "base_url": "http://localhost:8091",
            "request_timeout": 120.0,
            "provisioner_url": "http://provisioner:8002",
        }
        assert lint_unknown_config_keys({"sandbox": sandbox}) == []

    def test_non_dict_sandbox_is_ignored(self):
        assert lint_unknown_config_keys({"sandbox": None}) == []
        assert lint_unknown_config_keys({"sandbox": "nope"}) == []


class TestModelEntryLint:
    def test_typo_of_declared_field_warns(self):
        models = [{"name": "m1", "use": "x", "model": "y", "supports_thinkng": True}]
        warnings = lint_unknown_config_keys({"models": models})
        assert len(warnings) == 1
        assert "models entry 'm1'" in warnings[0]
        assert "'supports_thinkng'" in warnings[0]
        assert "possible typo of 'supports_thinking'" in warnings[0]

    def test_another_typo_warns(self):
        models = [{"name": "m1", "use": "x", "model": "y", "supports_visoin": True}]
        warnings = lint_unknown_config_keys({"models": models})
        assert len(warnings) == 1
        assert "possible typo of 'supports_vision'" in warnings[0]

    def test_legitimate_provider_passthrough_does_not_warn(self):
        # Shape produced by scripts/sync-ollama-models.py plus common extras —
        # all deliberate passthrough to the provider constructor.
        models = [
            {
                "name": "qwen3:8b",
                "display_name": "qwen3:8b (Ollama)",
                "use": "langchain_ollama:ChatOllama",
                "model": "qwen3:8b",
                "base_url": "http://localhost:11434",
                "num_predict": 8192,
                "temperature": 0.7,
                "reasoning": True,
                "supports_tools": False,
                "api_key": "$OPENAI_API_KEY",
                "max_tokens": 4096,
                "extra_body": {"chat_template_kwargs": {"enable_thinking": True}},
            }
        ]
        assert lint_unknown_config_keys({"models": models}) == []

    def test_malformed_entries_are_ignored(self):
        assert lint_unknown_config_keys({"models": ["not-a-dict", None]}) == []
        assert lint_unknown_config_keys({"models": "nope"}) == []
        assert lint_unknown_config_keys(None) == []


class TestFromFileLintWarnings:
    def test_unknown_sandbox_key_is_logged_at_load(self, tmp_path, caplog):
        config = tmp_path / "config.yaml"
        config.write_text(
            textwrap.dedent(
                """\
                sandbox:
                  use: deerflow.sandbox.local:LocalSandboxProvider
                  allow_hostbash: true
                models:
                  - name: gpt
                    use: langchain_openai:ChatOpenAI
                    model: gpt-test
                """
            ),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="deerflow.config.app_config"):
            AppConfig.from_file(str(config))
        assert any("allow_hostbash" in record.getMessage() for record in caplog.records)
