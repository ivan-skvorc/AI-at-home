"""Tests for scripts/sync-ollama-models.py config-integrity behavior.

The script is a text-surgery editor for the `models:` section. These tests pin:
- it refuses to edit a config with duplicate top-level keys (which would make
  it edit a section the application never reads);
- regeneration is idempotent — re-running sync on its own output is a no-op.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sync-ollama-models.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("sync_ollama_models", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync_ollama = _load_script()

CLEAN_CONFIG = """config_version: 3
models:
  - name: hand-edited
    use: langchain_openai:ChatOpenAI
    model: gpt-test
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
"""


class TestDuplicateTopLevelKeys:
    def test_duplicate_sandbox_aborts_with_both_line_numbers(self):
        text = "sandbox:\n  use: a\nmodels: []\nsandbox:\n  use: b\n"
        with pytest.raises(SystemExit) as excinfo:
            sync_ollama.check_duplicate_top_level_keys(text, "config.yaml")
        message = str(excinfo.value)
        assert "duplicate top-level key 'sandbox'" in message
        assert "first defined at line 1" in message
        assert "duplicated at line 4" in message

    def test_duplicate_models_aborts(self):
        text = "models: []\nsandbox:\n  use: a\nmodels: []\n"
        with pytest.raises(SystemExit) as excinfo:
            sync_ollama.check_duplicate_top_level_keys(text, "config.yaml")
        assert "duplicate top-level key 'models'" in str(excinfo.value)

    def test_clean_config_passes(self):
        sync_ollama.check_duplicate_top_level_keys(CLEAN_CONFIG, "config.yaml")

    def test_indented_and_commented_lines_are_not_top_level_keys(self):
        text = "models:\n  - name: a\n    model: b\n# models: in a comment\n  # sandbox: nested comment\nsandbox:\n  use: x\n"
        sync_ollama.check_duplicate_top_level_keys(text, "config.yaml")


class TestSyncIdempotence:
    def test_double_sync_is_byte_identical(self):
        models = [("qwen3:8b", ["tools"]), ("llava:13b", ["vision"])]
        once = sync_ollama.sync(CLEAN_CONFIG, models)
        twice = sync_ollama.sync(once, models)
        assert once == twice
        # hand-edited entry outside the markers is preserved
        assert "hand-edited" in once
        assert once.count(sync_ollama.BEGIN_MARKER) == 1
        assert once.count(sync_ollama.END_MARKER) == 1

    def test_sync_with_no_models_removes_managed_block_only(self):
        models = [("qwen3:8b", ["tools"])]
        with_block = sync_ollama.sync(CLEAN_CONFIG, models)
        removed = sync_ollama.sync(with_block, [])
        assert sync_ollama.BEGIN_MARKER not in removed
        assert "hand-edited" in removed
