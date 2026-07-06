"""Tests for scripts/sandbox_toggle.py (make sandbox-enable / sandbox-disable).

Rewrites ONLY the top-level sandbox: section, preserving the rest of the file
and the environment: block, idempotent, backing up first, and hard-aborting on
duplicate sandbox: keys.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sandbox_toggle.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("sandbox_toggle", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


toggle = _load_script()

LOCAL_CONFIG = """\
config_version: 3
models:
  - name: gpt
    use: langchain_openai:ChatOpenAI
    model: gpt-test
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: false
  bash_command_timeout: 600
tools: []
"""

AIO_CONFIG_WITH_ENV = """\
config_version: 3
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  base_url: http://localhost:8091
  request_timeout: 120.0
  environment:
    GITHUB_TOKEN: $GITHUB_TOKEN
    CUSTOM_VAR: hello
tools: []
"""


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(content, encoding="utf-8")
    return p


class TestEnable:
    def test_enable_writes_external_mode_and_backs_up(self, tmp_path, capsys):
        config = _write(tmp_path, LOCAL_CONFIG)
        rc = toggle.toggle("enable", config)
        assert rc == 0
        text = config.read_text(encoding="utf-8")
        assert "use: deerflow.community.aio_sandbox:AioSandboxProvider" in text
        assert "base_url: http://localhost:8091" in text
        assert "request_timeout: 120.0" in text
        # env defaulted since none existed
        assert "GITHUB_TOKEN: $GITHUB_TOKEN" in text
        # other sections untouched
        assert "config_version: 3" in text
        assert "name: gpt" in text
        assert text.rstrip().endswith("tools: []")
        assert (tmp_path / "config.yaml.bak").exists()

    def test_enable_preserves_existing_environment(self, tmp_path):
        config = _write(
            tmp_path,
            "sandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n  environment:\n    GITHUB_TOKEN: $GITHUB_TOKEN\n    CUSTOM_VAR: hello\ntools: []\n",
        )
        toggle.toggle("enable", config)
        text = config.read_text(encoding="utf-8")
        assert "CUSTOM_VAR: hello" in text
        assert "use: deerflow.community.aio_sandbox:AioSandboxProvider" in text

    def test_enable_idempotent_no_rewrite(self, tmp_path, capsys):
        config = _write(tmp_path, AIO_CONFIG_WITH_ENV)
        before = config.read_text(encoding="utf-8")
        rc = toggle.toggle("enable", config)
        assert rc == 0
        assert "already set to AIO" in capsys.readouterr().out
        assert config.read_text(encoding="utf-8") == before
        assert not (tmp_path / "config.yaml.bak").exists()


class TestDisable:
    def test_disable_reverts_to_local_and_keeps_guardrail_default(self, tmp_path):
        config = _write(tmp_path, AIO_CONFIG_WITH_ENV)
        rc = toggle.toggle("disable", config)
        assert rc == 0
        text = config.read_text(encoding="utf-8")
        assert "use: deerflow.sandbox.local:LocalSandboxProvider" in text
        assert "allow_host_bash: false" in text
        assert "base_url" not in text
        # environment preserved across the switch
        assert "CUSTOM_VAR: hello" in text

    def test_disable_idempotent_no_rewrite(self, tmp_path, capsys):
        config = _write(tmp_path, LOCAL_CONFIG)
        before = config.read_text(encoding="utf-8")
        rc = toggle.toggle("disable", config)
        assert rc == 0
        assert "already set to LocalSandboxProvider" in capsys.readouterr().out
        assert config.read_text(encoding="utf-8") == before
        assert not (tmp_path / "config.yaml.bak").exists()


class TestRoundTrip:
    def test_enable_then_disable_preserves_other_sections(self, tmp_path):
        config = _write(tmp_path, LOCAL_CONFIG)
        toggle.toggle("enable", config)
        toggle.toggle("disable", config)
        text = config.read_text(encoding="utf-8")
        assert "use: deerflow.sandbox.local:LocalSandboxProvider" in text
        assert "config_version: 3" in text
        assert "name: gpt" in text


class TestGuards:
    def test_duplicate_sandbox_key_aborts_with_line_numbers(self, tmp_path, capsys):
        config = _write(
            tmp_path,
            "sandbox:\n  use: a\nmodels: []\nsandbox:\n  use: b\n",
        )
        rc = toggle.toggle("enable", config)
        assert rc == 1
        out = capsys.readouterr().out
        assert "duplicate top-level key 'sandbox'" in out
        assert "first defined at line 1" in out
        assert "duplicated at line 4" in out
        assert not (tmp_path / "config.yaml.bak").exists()

    def test_missing_sandbox_section_aborts(self, tmp_path, capsys):
        config = _write(tmp_path, "models: []\ntools: []\n")
        rc = toggle.toggle("enable", config)
        assert rc == 1
        assert "No top-level `sandbox:` section" in capsys.readouterr().out


class TestExtractEnvironment:
    def test_extracts_block_with_entries(self):
        section = ["  use: x", "  environment:", "    A: 1", "    B: 2", "  other: y"]
        block = toggle.extract_environment_block(section)
        assert block == ["  environment:", "    A: 1", "    B: 2"]

    def test_empty_environment_returns_none(self):
        section = ["  use: x", "  environment:", "  other: y"]
        assert toggle.extract_environment_block(section) is None

    def test_no_environment_returns_none(self):
        assert toggle.extract_environment_block(["  use: x"]) is None
