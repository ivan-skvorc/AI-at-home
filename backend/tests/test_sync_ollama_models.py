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


class TestBaseUrl:
    """base_url written into entries is decoupled from the query host so the
    Docker launch paths can record a container-reachable URL (#Docker path)."""

    def test_default_base_url_is_localhost(self):
        out = sync_ollama.sync(CLEAN_CONFIG, [("qwen3:8b", ["tools"])])
        assert "base_url: http://localhost:11434" in out

    def test_render_entry_uses_provided_base_url(self):
        entry = sync_ollama.render_entry("qwen3:8b", ["tools"], "http://host.docker.internal:11434")
        assert "base_url: http://host.docker.internal:11434" in entry

    def test_sync_writes_container_base_url(self):
        out = sync_ollama.sync(CLEAN_CONFIG, [("qwen3:8b", ["tools"])], base_url="http://host.docker.internal:11434")
        assert "base_url: http://host.docker.internal:11434" in out
        assert "base_url: http://localhost:11434" not in out

    def test_container_base_url_double_sync_idempotent(self):
        base = "http://host.docker.internal:11434"
        models = [("qwen3:8b", ["tools"])]
        once = sync_ollama.sync(CLEAN_CONFIG, models, base_url=base)
        twice = sync_ollama.sync(once, models, base_url=base)
        assert once == twice


class TestContainerizeBaseUrl:
    def test_localhost_is_rewritten_to_host_gateway(self):
        assert sync_ollama.containerize_base_url("http://localhost:11434") == "http://host.docker.internal:11434"

    def test_loopback_ip_is_rewritten(self):
        assert sync_ollama.containerize_base_url("http://127.0.0.1:11434") == "http://host.docker.internal:11434"

    def test_ipv6_loopback_is_rewritten(self):
        assert sync_ollama.containerize_base_url("http://[::1]:11434") == "http://host.docker.internal:11434"

    def test_port_is_preserved(self):
        assert sync_ollama.containerize_base_url("http://localhost:1234") == "http://host.docker.internal:1234"

    def test_remote_host_is_left_unchanged(self):
        # A genuinely remote Ollama is already reachable from a container.
        assert sync_ollama.containerize_base_url("http://server.lan:11434") == "http://server.lan:11434"


class TestContainerOllamaWarning:
    """--container writes host.docker.internal, which resolves to the Docker
    bridge gateway on Linux. A loopback-only host Ollama (its default binding)
    refuses those connections, so the sync must warn with the exact fix."""

    @staticmethod
    def _docker(responses: dict[str, str | None]):
        def run(args, timeout=5.0):
            return responses.get(args[0])

        return run

    def test_warns_when_gateway_unreachable(self):
        docker = self._docker({"info": "Ubuntu 24.04", "network": "172.17.0.1\n"})
        warning = sync_ollama.container_ollama_warning("http://host.docker.internal:11434", docker=docker, probe=lambda url: False)
        assert warning is not None
        assert "OLLAMA_HOST=0.0.0.0" in warning
        assert "172.17.0.1" in warning

    def test_probes_gateway_at_base_url_port(self):
        probed: list[str] = []
        docker = self._docker({"info": "Ubuntu 24.04", "network": "172.17.0.1\n"})

        def probe(url: str) -> bool:
            probed.append(url)
            return True

        assert sync_ollama.container_ollama_warning("http://host.docker.internal:12345", docker=docker, probe=probe) is None
        assert probed == ["http://172.17.0.1:12345"]

    def test_silent_when_gateway_answers(self):
        docker = self._docker({"info": "Ubuntu 24.04", "network": "172.17.0.1\n"})
        assert sync_ollama.container_ollama_warning("http://host.docker.internal:11434", docker=docker, probe=lambda url: True) is None

    def test_silent_on_docker_desktop(self):
        # Docker Desktop proxies host loopback for host.docker.internal.
        docker = self._docker({"info": "Docker Desktop\n", "network": "192.168.65.1\n"})
        assert sync_ollama.container_ollama_warning("http://host.docker.internal:11434", docker=docker, probe=lambda url: False) is None

    def test_silent_when_gateway_cannot_be_determined(self):
        docker = self._docker({"info": "Ubuntu 24.04", "network": None})
        assert sync_ollama.container_ollama_warning("http://host.docker.internal:11434", docker=docker, probe=lambda url: False) is None

    def test_silent_for_non_alias_base_url(self):
        # A remote Ollama recorded verbatim needs no bridge-gateway reachability.
        docker = self._docker({"info": "Ubuntu 24.04", "network": "172.17.0.1\n"})
        assert sync_ollama.container_ollama_warning("http://server.lan:11434", docker=docker, probe=lambda url: False) is None


class TestResolveBaseUrl:
    def test_explicit_base_url_wins(self):
        resolved = sync_ollama.resolve_base_url("http://localhost:11434", "http://custom:9999", container=True)
        assert resolved == "http://custom:9999"

    def test_container_rewrites_loopback(self):
        resolved = sync_ollama.resolve_base_url("http://localhost:11434", None, container=True)
        assert resolved == "http://host.docker.internal:11434"

    def test_no_flags_keeps_query_host(self):
        # Non-container local runtime records the query host verbatim, so a
        # remote OLLAMA_HOST is written correctly instead of a bogus localhost.
        resolved = sync_ollama.resolve_base_url("http://server.lan:11434", None, container=False)
        assert resolved == "http://server.lan:11434"


class TestParseContextLength:
    """The model's native context window is read from /api/show -> model_info."""

    def test_reads_architecture_scoped_key(self):
        show = {"model_info": {"general.architecture": "qwen3", "qwen3.context_length": 40960}}
        assert sync_ollama.parse_context_length(show) == 40960

    def test_falls_back_to_any_context_length_key(self):
        # Architecture missing/mismatched: still find the *.context_length entry.
        show = {"model_info": {"llama.context_length": 8192}}
        assert sync_ollama.parse_context_length(show) == 8192

    def test_missing_model_info_returns_none(self):
        assert sync_ollama.parse_context_length({"capabilities": ["tools"]}) is None

    def test_missing_context_length_returns_none(self):
        show = {"model_info": {"general.architecture": "phi3"}}
        assert sync_ollama.parse_context_length(show) is None

    def test_bool_is_not_treated_as_context_length(self):
        # bool is a subclass of int — guard against `enable: true` style keys.
        show = {"model_info": {"x.context_length": True}}
        assert sync_ollama.parse_context_length(show) is None

    def test_float_is_coerced_to_int(self):
        show = {"model_info": {"general.architecture": "gemma", "gemma.context_length": 8192.0}}
        assert sync_ollama.parse_context_length(show) == 8192


class TestResolveNumCtx:
    def test_clamps_native_to_cap(self):
        assert sync_ollama.resolve_num_ctx(131072, cap=32768) == 32768

    def test_native_below_cap_is_kept(self):
        assert sync_ollama.resolve_num_ctx(8192, cap=32768) == 8192

    def test_cap_zero_uses_full_native(self):
        assert sync_ollama.resolve_num_ctx(131072, cap=0) == 131072

    def test_unknown_native_returns_none(self):
        assert sync_ollama.resolve_num_ctx(None) is None
        assert sync_ollama.resolve_num_ctx(0) is None


class TestRenderEntryNumCtx:
    def test_num_ctx_written_when_known(self):
        entry = sync_ollama.render_entry("qwen3:8b", ["tools"], num_ctx=32768)
        assert "num_ctx: 32768" in entry

    def test_num_predict_never_exceeds_context(self):
        # A small context window shrinks the output budget so the prompt still fits.
        entry = sync_ollama.render_entry("old:7b", ["tools"], num_ctx=4096)
        assert "num_ctx: 4096" in entry
        assert "num_predict: 2048" in entry

    def test_default_num_predict_when_context_is_large(self):
        entry = sync_ollama.render_entry("qwen3:8b", ["tools"], num_ctx=32768)
        assert f"num_predict: {sync_ollama.DEFAULT_NUM_PREDICT}" in entry

    def test_no_num_ctx_line_when_unknown(self):
        # Backward-compatible: unknown context length leaves Ollama's own default.
        entry = sync_ollama.render_entry("mystery", ["tools"])
        assert "num_ctx" not in entry
        assert f"num_predict: {sync_ollama.DEFAULT_NUM_PREDICT}" in entry


class TestSyncNumCtxIdempotence:
    def test_three_tuple_entries_write_num_ctx_and_stay_idempotent(self):
        models = [("qwen3:8b", ["tools"], 32768), ("llava:13b", ["vision"], 8192)]
        once = sync_ollama.sync(CLEAN_CONFIG, models)
        twice = sync_ollama.sync(once, models)
        assert once == twice
        assert "num_ctx: 32768" in once
        assert "num_ctx: 8192" in once
        assert "hand-edited" in once

    def test_two_tuple_entries_still_supported(self):
        # Pre-existing (name, caps) callers keep working — no num_ctx emitted.
        once = sync_ollama.sync(CLEAN_CONFIG, [("qwen3:8b", ["tools"])])
        assert "num_ctx" not in once
