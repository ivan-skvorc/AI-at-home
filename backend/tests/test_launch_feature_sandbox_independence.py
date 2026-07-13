"""Regression tests: the three launch-time features are sandbox-mode-independent.

Ollama auto-populate, the Camoufox `web_fetch` extra, and the SearXNG
`web_search` setup all run in the gateway/host at launch time and have nothing
to do with which sandbox provider the agent uses. This pins that property:
switching `sandbox.use` between the local provider and the AIO provider (in
either external `base_url` mode or per-thread container mode) must not change
what these detectors/sync decide, and the Ollama sync must leave the sandbox
block untouched.

The concern this guards against is a future change coupling one of these
host-side features to the sandbox choice (e.g. a detector that bails when it
sees an AIO block). The detectors are loaded from `scripts/` the same way their
own test modules load them.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import detect_searxng
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def _load(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detect_uv_extras = _load("_indep_detect_uv_extras", "detect_uv_extras.py")
sync_ollama = _load("_indep_sync_ollama", "sync-ollama-models.py")


# A minimal config carrying all three default features, with a placeholder for
# the sandbox block so each variant differs ONLY in `sandbox.use`.
_CONFIG_TEMPLATE = """\
config_version: 23

models:
  - name: hand-edited
    use: langchain_openai:ChatOpenAI
    model: gpt-test

tools:
  - name: web_search
    group: web
    use: deerflow.community.searxng.tools:web_search_tool
  - name: web_fetch
    group: web
    use: deerflow.community.web_fetch.tools:web_fetch_tool
    backend: camoufox

{sandbox_block}
"""

_SANDBOX_BLOCKS = {
    "local": "sandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n",
    "aio_external": "sandbox:\n  use: deerflow.community.aio_sandbox:AioSandboxProvider\n  base_url: http://localhost:8091\n",
    "aio_container": "sandbox:\n  use: deerflow.community.aio_sandbox:AioSandboxProvider\n  expose_ports: [8000]\n  extra_capabilities: [SYS_PTRACE]\n",
}

SANDBOX_MODES = list(_SANDBOX_BLOCKS)


def _config_for(mode: str) -> str:
    return _CONFIG_TEMPLATE.format(sandbox_block=_SANDBOX_BLOCKS[mode])


@pytest.fixture
def config_file(tmp_path):
    def _make(mode: str) -> Path:
        path = tmp_path / f"config.{mode}.yaml"
        path.write_text(_config_for(mode), encoding="utf-8")
        return path

    return _make


@pytest.mark.parametrize("mode", SANDBOX_MODES)
def test_camoufox_extra_detected_regardless_of_sandbox(mode, config_file):
    """The camoufox uv extra is selected from web_fetch, never from the sandbox."""
    assert detect_uv_extras.detect_from_config(config_file(mode)) == ["camoufox"]


def test_camoufox_detection_identical_across_sandbox_modes(config_file):
    results = {mode: detect_uv_extras.detect_from_config(config_file(mode)) for mode in SANDBOX_MODES}
    assert len(set(map(tuple, results.values()))) == 1, results


@pytest.mark.parametrize("mode", SANDBOX_MODES)
def test_searxng_activation_regardless_of_sandbox(mode):
    """config_uses_searxng gates the SearXNG launch setup; it must ignore the sandbox."""
    assert detect_searxng.config_uses_searxng(_config_for(mode)) is True


def test_searxng_activation_identical_across_sandbox_modes():
    results = {mode: detect_searxng.config_uses_searxng(_config_for(mode)) for mode in SANDBOX_MODES}
    assert set(results.values()) == {True}, results


@pytest.mark.parametrize("mode", SANDBOX_MODES)
def test_ollama_sync_writes_model_block_regardless_of_sandbox(mode):
    """The managed Ollama block is written identically no matter the sandbox."""
    out = sync_ollama.sync(_config_for(mode), [("llama3.2:latest", ["tools"])])
    assert "# === BEGIN ollama-sync" in out
    assert "name: llama3.2:latest" in out
    assert "base_url: http://localhost:11434" in out


def test_ollama_sync_managed_block_identical_across_sandbox_modes():
    """The bytes of the managed block do not depend on the sandbox provider."""
    models = [("llama3.2:latest", ["tools"])]
    blocks = {}
    for mode in SANDBOX_MODES:
        out = sync_ollama.sync(_config_for(mode), models)
        start = out.index("# === BEGIN ollama-sync")
        end = out.index("# === END ollama-sync", start)
        blocks[mode] = out[start:end]
    assert len(set(blocks.values())) == 1, "managed Ollama block differs by sandbox mode"


@pytest.mark.parametrize("mode", ["aio_external", "aio_container"])
def test_ollama_sync_leaves_aio_sandbox_block_intact(mode):
    """Syncing models must not touch the sandbox section (AIO settings preserved)."""
    out = sync_ollama.sync(_config_for(mode), [("llama3.2:latest", ["tools"])])
    assert "use: deerflow.community.aio_sandbox:AioSandboxProvider" in out
    if mode == "aio_external":
        assert "base_url: http://localhost:8091" in out
    else:
        assert "expose_ports: [8000]" in out
        assert "extra_capabilities: [SYS_PTRACE]" in out


def test_ollama_container_base_url_independent_of_sandbox():
    """The --container base_url rewrite depends on the launch path, not the sandbox."""
    for mode in SANDBOX_MODES:
        out = sync_ollama.sync(_config_for(mode), [("llama3.2:latest", ["tools"])], base_url="http://host.docker.internal:11434")
        assert "base_url: http://host.docker.internal:11434" in out
        assert "base_url: http://localhost:11434" not in out
