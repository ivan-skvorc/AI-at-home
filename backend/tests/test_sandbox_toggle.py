"""Tests for scripts/sandbox_toggle.py (make sandbox-enable / sandbox-disable).

Rewrites ONLY the top-level sandbox: section, preserving the rest of the file
and the environment: block, idempotent, backing up first, and hard-aborting on
duplicate sandbox: keys. In container mode, IMAGE=cad (and its absence) changes
only the image: line of a section that is already in container mode.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

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


class TestEnableContainerMode:
    def test_enable_container_writes_provider_without_base_url(self, tmp_path):
        config = _write(tmp_path, LOCAL_CONFIG)
        rc = toggle.toggle("enable", config, mode="container")
        assert rc == 0
        text = config.read_text(encoding="utf-8")
        assert "use: deerflow.community.aio_sandbox:AioSandboxProvider" in text
        # Container mode is per-thread; must NOT pin an external base_url.
        assert "base_url" not in text
        # Container mode spawns its own container, so a working image must be
        # pinned instead of the provider's broken :latest DEFAULT_IMAGE fallback.
        assert "image: ghcr.io/agent-infra/sandbox:1.11.0" in text
        assert "bash_command_timeout: 1800" in text
        assert "request_timeout: 1800.0" in text
        assert "GITHUB_TOKEN: $GITHUB_TOKEN" in text

    def test_enable_container_preserves_environment(self, tmp_path):
        config = _write(
            tmp_path,
            "sandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n  environment:\n    GITHUB_TOKEN: $GITHUB_TOKEN\n    CUSTOM_VAR: hello\ntools: []\n",
        )
        toggle.toggle("enable", config, mode="container")
        text = config.read_text(encoding="utf-8")
        assert "CUSTOM_VAR: hello" in text
        assert "base_url" not in text

    def test_enable_container_idempotent(self, tmp_path, capsys):
        config = _write(tmp_path, LOCAL_CONFIG)
        toggle.toggle("enable", config, mode="container")
        before = config.read_text(encoding="utf-8")
        (tmp_path / "config.yaml.bak").unlink()
        rc = toggle.toggle("enable", config, mode="container")
        assert rc == 0
        assert "already set to AIO container mode" in capsys.readouterr().out
        assert config.read_text(encoding="utf-8") == before
        assert not (tmp_path / "config.yaml.bak").exists()

    def test_switch_external_to_container_rewrites(self, tmp_path):
        config = _write(tmp_path, AIO_CONFIG_WITH_ENV)
        rc = toggle.toggle("enable", config, mode="container")
        assert rc == 0
        text = config.read_text(encoding="utf-8")
        assert "base_url" not in text
        assert "bash_command_timeout: 1800" in text
        # environment preserved across the mode switch
        assert "CUSTOM_VAR: hello" in text

    def test_main_accepts_mode_container_flag(self, tmp_path, monkeypatch):
        config = _write(tmp_path, LOCAL_CONFIG)
        monkeypatch.setattr(toggle, "resolve_config_path", lambda: config)
        rc = toggle.main(["sandbox_toggle.py", "enable", "--mode", "container"])
        assert rc == 0
        assert "base_url" not in config.read_text(encoding="utf-8")

    def test_main_rejects_bad_mode(self, tmp_path, monkeypatch, capsys):
        config = _write(tmp_path, LOCAL_CONFIG)
        monkeypatch.setattr(toggle, "resolve_config_path", lambda: config)
        rc = toggle.main(["sandbox_toggle.py", "enable", "--mode", "bogus"])
        assert rc == 2
        assert "usage:" in capsys.readouterr().err

    def test_main_rejects_mode_on_disable(self, tmp_path, monkeypatch, capsys):
        config = _write(tmp_path, LOCAL_CONFIG)
        monkeypatch.setattr(toggle, "resolve_config_path", lambda: config)
        rc = toggle.main(["sandbox_toggle.py", "disable", "--mode", "container"])
        assert rc == 2
        assert "usage:" in capsys.readouterr().err


CONTAINER_CONFIG_WITH_OPERATOR_KEYS = """\
config_version: 3
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  network_proxy:
    image: proxy:latest
  image: ghcr.io/agent-infra/sandbox:1.11.0
  devices: [/dev/kvm]
  expose_ports: [8000]
  environment:
    GITHUB_TOKEN: $GITHUB_TOKEN
tools: []
"""


class TestImageOption:
    """`make sandbox-enable MODE=container IMAGE=cad` and the way back."""

    def test_enable_container_with_cad_image_writes_the_cad_tag(self, tmp_path, capsys):
        config = _write(tmp_path, LOCAL_CONFIG)
        rc = toggle.toggle("enable", config, mode="container", image="cad")
        assert rc == 0
        block = yaml.safe_load(config.read_text(encoding="utf-8"))["sandbox"]
        assert block["image"] == "deerflow-sandbox-cad:local"
        assert block["use"] == "deerflow.community.aio_sandbox:AioSandboxProvider"
        assert "base_url" not in block
        # The tag is local only, so the operator is told to build it.
        assert "make sandbox-cad-image" in capsys.readouterr().out

    def test_already_container_switches_only_the_image_line(self, tmp_path):
        config = _write(tmp_path, CONTAINER_CONFIG_WITH_OPERATOR_KEYS)
        rc = toggle.toggle("enable", config, mode="container", image="cad")
        assert rc == 0
        before = CONTAINER_CONFIG_WITH_OPERATOR_KEYS.splitlines()
        after = config.read_text(encoding="utf-8").splitlines()
        changed = [(old, new) for old, new in zip(before, after, strict=True) if old != new]
        # devices:, expose_ports: and the sub-mapping's own image: survive.
        assert changed == [("  image: ghcr.io/agent-infra/sandbox:1.11.0", "  image: deerflow-sandbox-cad:local")]
        assert (tmp_path / "config.yaml.bak").read_text(encoding="utf-8") == CONTAINER_CONFIG_WITH_OPERATOR_KEYS

    def test_container_mode_without_image_goes_back_to_the_stock_tag(self, tmp_path):
        config = _write(tmp_path, CONTAINER_CONFIG_WITH_OPERATOR_KEYS)
        toggle.toggle("enable", config, mode="container", image="cad")
        rc = toggle.toggle("enable", config, mode="container")
        assert rc == 0
        assert config.read_text(encoding="utf-8") == CONTAINER_CONFIG_WITH_OPERATOR_KEYS

    def test_cad_image_already_set_is_a_no_op(self, tmp_path, capsys):
        config = _write(tmp_path, LOCAL_CONFIG)
        toggle.toggle("enable", config, mode="container", image="cad")
        before = config.read_text(encoding="utf-8")
        (tmp_path / "config.yaml.bak").unlink()
        capsys.readouterr()
        rc = toggle.toggle("enable", config, mode="container", image="cad")
        assert rc == 0
        assert "already set to AIO container mode" in capsys.readouterr().out
        assert config.read_text(encoding="utf-8") == before
        assert not (tmp_path / "config.yaml.bak").exists()

    def test_container_section_without_an_image_gets_one_after_use(self, tmp_path):
        config = _write(tmp_path, "sandbox:\n    use: deerflow.community.aio_sandbox:AioSandboxProvider\n    idle_timeout: 600\ntools: []\n")
        rc = toggle.toggle("enable", config, mode="container", image="cad")
        assert rc == 0
        lines = config.read_text(encoding="utf-8").splitlines()
        assert lines[1:4] == ["    use: deerflow.community.aio_sandbox:AioSandboxProvider", "    image: deerflow-sandbox-cad:local", "    idle_timeout: 600"]

    def test_main_passes_the_image_in_either_order(self, tmp_path, monkeypatch):
        config = _write(tmp_path, LOCAL_CONFIG)
        monkeypatch.setattr(toggle, "resolve_config_path", lambda: config)
        rc = toggle.main(["sandbox_toggle.py", "enable", "--image", "cad", "--mode", "container"])
        assert rc == 0
        assert yaml.safe_load(config.read_text(encoding="utf-8"))["sandbox"]["image"] == "deerflow-sandbox-cad:local"

    @pytest.mark.parametrize("argv", [["enable", "--image", "cad"], ["enable", "--mode", "external", "--image", "cad"]], ids=["default-mode", "external"])
    def test_main_refuses_an_image_outside_container_mode(self, tmp_path, monkeypatch, capsys, argv):
        config = _write(tmp_path, AIO_CONFIG_WITH_ENV)
        monkeypatch.setattr(toggle, "resolve_config_path", lambda: config)
        rc = toggle.main(["sandbox_toggle.py", *argv])
        assert rc == 2
        assert "needs --mode container" in capsys.readouterr().err
        assert config.read_text(encoding="utf-8") == AIO_CONFIG_WITH_ENV

    def test_toggle_refuses_an_image_outside_container_mode(self, tmp_path):
        config = _write(tmp_path, LOCAL_CONFIG)
        assert toggle.toggle("enable", config, mode="external", image="cad") == 2
        assert config.read_text(encoding="utf-8") == LOCAL_CONFIG

    @pytest.mark.parametrize(
        "argv",
        [["enable", "--mode", "container", "--image", "vm"], ["disable", "--image", "cad"], ["enable", "--mode", "container", "--mode", "external"], ["enable", "--image"]],
        ids=["unknown-image", "disable", "repeated-flag", "missing-value"],
    )
    def test_main_rejects_bad_image_arguments(self, tmp_path, monkeypatch, capsys, argv):
        config = _write(tmp_path, LOCAL_CONFIG)
        monkeypatch.setattr(toggle, "resolve_config_path", lambda: config)
        assert toggle.main(["sandbox_toggle.py", *argv]) == 2
        assert "usage:" in capsys.readouterr().err
        assert config.read_text(encoding="utf-8") == LOCAL_CONFIG


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
