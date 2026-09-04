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

    def test_context_window_mirrors_num_ctx(self):
        # num_ctx is the provider kwarg; context_window is what the UI indicator
        # and the cost-aware routing guard read. Without it the guard sees None
        # and short-circuits, so a prompt too large for the model is routed to
        # it anyway.
        entry = sync_ollama.render_entry("qwen3:8b", ["tools"], num_ctx=32768)
        assert "context_window: 32768" in entry

    def test_no_context_window_line_when_the_window_is_unknown(self):
        entry = sync_ollama.render_entry("mystery:7b", ["tools"])
        assert "context_window" not in entry

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


class TestWeightSizeReachesTheEntry:
    """The `/api/tags` size must actually travel into the written entry.

    `render_entry` accepting a size proves nothing on its own: the field is
    silent when broken — every entry stays valid, the sync stays idempotent, and
    the picker simply shows no size for any model, which looks exactly like a
    daemon that did not report one. This drives `main()` end to end so the drop
    is a failure rather than a blank chip.
    """

    def _run(self, monkeypatch, capsys, tmp_path, tags):
        config = tmp_path / "config.yaml"
        config.write_text(CLEAN_CONFIG)
        monkeypatch.setattr(sync_ollama, "fetch_tags", lambda host, timeout=2.0: tags)
        monkeypatch.setattr(
            sync_ollama,
            "fetch_show",
            lambda host, name, timeout=5.0: {"capabilities": ["tools"], "model_info": {"general.architecture": "qwen3", "qwen3.context_length": 40960}},
        )
        monkeypatch.setattr(sync_ollama.sys, "argv", ["sync-ollama-models.py", "--config", str(config), "--dry-run"])
        assert sync_ollama.main() == 0
        return capsys.readouterr().out

    def test_the_size_from_api_tags_lands_in_the_entry(self, monkeypatch, capsys, tmp_path):
        out = self._run(monkeypatch, capsys, tmp_path, [{"name": "qwen3:8b", "size": 5_200_000_000}])
        assert "- name: qwen3:8b" in out
        assert "size_bytes: 5200000000" in out

    def test_a_daemon_that_reports_no_size_still_writes_the_entry(self, monkeypatch, capsys, tmp_path):
        out = self._run(monkeypatch, capsys, tmp_path, [{"name": "qwen3:8b"}])
        assert "- name: qwen3:8b" in out
        assert "size_bytes" not in out


class TestRenderEntryWeightSize:
    """The weights a local model puts on the GPU, written for the model picker.

    The picker shows it next to the context window because those are the two
    halves of one question: a 20 GiB model and a 32K window do not both fit on a
    24 GiB card, and until the number was on the row the only way to find that
    out was to select the model and watch the daemon offload to CPU.
    """

    def test_size_written_when_the_daemon_reports_it(self):
        entry = sync_ollama.render_entry("qwen3:8b", ["tools"], size_bytes=5_200_000_000)
        assert "size_bytes: 5200000000" in entry

    def test_no_size_line_when_the_daemon_does_not_report_one(self):
        # /api/tags is the only source; an entry written without it must stay
        # valid rather than carrying a zero the UI would render as "0 B".
        assert "size_bytes" not in sync_ollama.render_entry("mystery:7b", ["tools"])
        assert "size_bytes" not in sync_ollama.render_entry("mystery:7b", ["tools"], size_bytes=0)

    def test_size_is_written_as_an_integer(self):
        # /api/tags returns a JSON number; a float would land in config.yaml as
        # `5200000000.0`, which ModelConfig's `int | None` rejects at load.
        entry = sync_ollama.render_entry("qwen3:8b", ["tools"], size_bytes=5_200_000_000.0)
        assert "size_bytes: 5200000000" in entry


class TestRenderEntryKvBytesPerToken:
    """The cache half of a local model's GPU footprint, written for the Gateway.

    ``size_bytes`` alone answers "will the weights fit"; the subagent
    GPU-residency gate has to answer "will the weights *and the window this
    entry asks for* fit, twice", and the per-token cache cost is the only
    missing term. It is computed here already — the num_ctx sizing is built on
    it — and nowhere else in the stack, so not writing it means the runtime
    silently costs a local model at its weights and over-admits.
    """

    def test_the_per_token_cache_cost_is_written(self):
        entry = sync_ollama.render_entry("qwen3:8b", ["tools"], size_bytes=5_200_000_000, kv_bytes_per_token=131072.0)
        assert "kv_bytes_per_token: 131072" in entry

    def test_no_line_when_the_geometry_did_not_yield_one(self):
        # `parse_kv_bytes_per_token` returns None for a payload that does not
        # expose the geometry. A zero written into config.yaml would be read as
        # "this model has no cache", which is worse than an absent field: absent
        # means "unknown" and leaves the dispatch ungated.
        assert "kv_bytes_per_token" not in sync_ollama.render_entry("mystery:7b", ["tools"], size_bytes=1)
        assert "kv_bytes_per_token" not in sync_ollama.render_entry("mystery:7b", ["tools"], size_bytes=1, kv_bytes_per_token=0)

    def test_the_value_is_rounded_rather_than_written_as_a_float_repr(self):
        # q8_0 and q4_0 make this a non-terminating fraction; `%g` on the raw
        # float would put a 17-digit number in a file people hand-edit.
        entry = sync_ollama.render_entry("qwen3:8b", ["tools"], size_bytes=1, kv_bytes_per_token=64 * 8 * (128 + 128) * (34 / 32))
        assert "kv_bytes_per_token: 139264" in entry

    def test_the_sync_writes_it_from_the_same_show_payload_the_sizing_uses(self, monkeypatch, capsys, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text(CLEAN_CONFIG)
        monkeypatch.setattr(sync_ollama, "fetch_tags", lambda host, timeout=2.0: [{"name": "qwen3:8b", "size": 5_200_000_000}])
        monkeypatch.setattr(sync_ollama, "fetch_show", lambda host, name, timeout=5.0: QWEN3_SHOW)
        monkeypatch.setattr(sync_ollama.sys, "argv", ["sync-ollama-models.py", "--config", str(config), "--dry-run"])
        assert sync_ollama.main() == 0
        out = capsys.readouterr().out
        expected = sync_ollama.parse_kv_bytes_per_token(QWEN3_SHOW)
        assert expected is not None
        # Written even with no `ollama.vram_gb` configured: it is a property of
        # the model, not of this machine's card, so declaring a budget later
        # must not require another /api/show round trip.
        assert f"kv_bytes_per_token: {round(expected, 3):g}" in out


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

    def test_five_tuple_entries_write_the_weight_size_and_stay_idempotent(self):
        models = [("qwen3:8b", ["tools"], 32768, "30m", 5_200_000_000)]
        once = sync_ollama.sync(CLEAN_CONFIG, models)
        twice = sync_ollama.sync(once, models)
        assert once == twice
        assert "size_bytes: 5200000000" in once
        assert "keep_alive: 30m" in once

    def test_shorter_tuples_still_omit_the_weight_size(self):
        # The tail is read positionally so a caller that has not been taught
        # about the new field keeps working — the same back-compatibility
        # `keep_alive` relies on (FORK.md §1's checklist row).
        once = sync_ollama.sync(CLEAN_CONFIG, [("qwen3:8b", ["tools"], 32768, "30m")])
        assert "size_bytes" not in once
        assert "num_ctx: 32768" in once


# ── VRAM-aware context sizing ────────────────────────────────────────────────

# Realistic /api/show geometry for qwen3:8b (GQA: 32 query heads, 8 KV heads).
QWEN3_SHOW = {
    "capabilities": ["tools", "thinking"],
    "model_info": {
        "general.architecture": "qwen3",
        "qwen3.block_count": 36,
        "qwen3.context_length": 40960,
        "qwen3.embedding_length": 4096,
        "qwen3.attention.head_count": 32,
        "qwen3.attention.head_count_kv": 8,
        "qwen3.attention.key_length": 128,
        "qwen3.attention.value_length": 128,
    },
}

GIB = 1024**3
QWEN3_WEIGHTS = 5_200_000_000  # ~q4_K_M on disk


class TestParseKvBytesPerToken:
    """KV cache per token = layers x kv_heads x (key_dim + value_dim) x bytes/element."""

    def test_f16_geometry(self):
        assert sync_ollama.parse_kv_bytes_per_token(QWEN3_SHOW) == 36 * 8 * 256 * 2.0

    def test_q8_0_shrinks_per_token_cost(self):
        f16 = sync_ollama.parse_kv_bytes_per_token(QWEN3_SHOW, "f16")
        q8 = sync_ollama.parse_kv_bytes_per_token(QWEN3_SHOW, "q8_0")
        assert q8 == 36 * 8 * 256 * (34 / 32)
        assert q8 < f16

    def test_unknown_kv_type_falls_back_to_f16(self):
        assert sync_ollama.parse_kv_bytes_per_token(QWEN3_SHOW, "q2_K") == sync_ollama.parse_kv_bytes_per_token(QWEN3_SHOW, "f16")

    def test_head_dim_falls_back_to_embedding_over_head_count(self):
        show = {
            "model_info": {
                "general.architecture": "llama",
                "llama.block_count": 36,
                "llama.embedding_length": 4096,
                "llama.attention.head_count": 32,
                "llama.attention.head_count_kv": 8,
            }
        }
        # head_dim = 4096 / 32 = 128 -> same as explicit key/value_length above
        assert sync_ollama.parse_kv_bytes_per_token(show) == 36 * 8 * 256 * 2.0

    def test_per_layer_kv_head_list_uses_mean(self):
        show = {
            "model_info": {
                "general.architecture": "hybrid",
                "hybrid.block_count": 36,
                "hybrid.attention.head_count_kv": [8, 8, 4, 4],
                "hybrid.attention.key_length": 128,
                "hybrid.attention.value_length": 128,
            }
        }
        assert sync_ollama.parse_kv_bytes_per_token(show) == 36 * 6 * 256 * 2.0

    def test_missing_model_info_returns_none(self):
        assert sync_ollama.parse_kv_bytes_per_token({"capabilities": ["tools"]}) is None

    def test_missing_geometry_returns_none(self):
        show = {"model_info": {"general.architecture": "phi3", "phi3.block_count": 32}}
        assert sync_ollama.parse_kv_bytes_per_token(show) is None


class TestVramNumCtxLimit:
    """Largest window whose KV cache fits: (VRAM - weights - overhead) / per-token."""

    def test_tight_vram_limits_the_window(self):
        # 8 GiB - 5.2 GB weights - 1.5 GiB overhead = ~1.66 GiB for KV cache
        # -> 12066 tokens at f16, floored to the 2048 step.
        limit = sync_ollama.vram_num_ctx_limit(QWEN3_SHOW, QWEN3_WEIGHTS, 8 * GIB)
        assert limit == 10240

    def test_q8_0_roughly_doubles_the_window(self):
        f16 = sync_ollama.vram_num_ctx_limit(QWEN3_SHOW, QWEN3_WEIGHTS, 8 * GIB, "f16")
        q8 = sync_ollama.vram_num_ctx_limit(QWEN3_SHOW, QWEN3_WEIGHTS, 8 * GIB, "q8_0")
        assert q8 == 22528
        assert q8 > 2 * f16 * 0.9

    def test_big_vram_exceeds_native_length(self):
        # 16 GiB fits ~70K tokens -> resolve_num_ctx clamps to the 40960 native.
        limit = sync_ollama.vram_num_ctx_limit(QWEN3_SHOW, QWEN3_WEIGHTS, 16 * GIB)
        assert limit == 69632

    def test_no_room_takes_the_offload_floor_not_the_old_4096(self):
        # Weights + overhead exceed 6 GiB, so this is the partial-offload path.
        # It used to return MIN_VRAM_NUM_CTX (4096), which is smaller than the
        # agent's own system prompt — a window that "fits" but cannot be used.
        # Ollama degrades by moving layers to CPU rather than crashing, so the
        # right answer is a usable window, bounded (see
        # TestVramNumCtxLimitUnderOffload) so it does not evict the weights.
        limit = sync_ollama.vram_num_ctx_limit(QWEN3_SHOW, QWEN3_WEIGHTS, 6 * GIB)
        assert limit == sync_ollama.MIN_OFFLOAD_NUM_CTX

    def test_unknown_geometry_returns_none(self):
        assert sync_ollama.vram_num_ctx_limit({"model_info": {}}, QWEN3_WEIGHTS, 8 * GIB) is None

    def test_unknown_weights_returns_none(self):
        assert sync_ollama.vram_num_ctx_limit(QWEN3_SHOW, None, 8 * GIB) is None


class TestResolveNumCtxWithVramLimit:
    def test_vram_limit_caps_native(self):
        assert sync_ollama.resolve_num_ctx(40960, cap=0, vram_limit=10240) == 10240

    def test_native_below_vram_limit_is_kept(self):
        assert sync_ollama.resolve_num_ctx(8192, cap=0, vram_limit=10240) == 8192

    def test_explicit_cap_still_wins_over_vram_limit(self):
        assert sync_ollama.resolve_num_ctx(40960, cap=8192, vram_limit=10240) == 8192

    def test_unknown_native_stays_none(self):
        assert sync_ollama.resolve_num_ctx(None, cap=0, vram_limit=10240) is None


class TestEffectiveNumCtxCap:
    """Cap precedence: explicit --num-ctx-cap > VRAM sizing (cap off) > flat default."""

    def test_default_flat_cap_without_vram(self):
        assert sync_ollama.effective_num_ctx_cap(None, None) == sync_ollama.DEFAULT_NUM_CTX_CAP

    def test_vram_sizing_replaces_the_default_cap(self):
        assert sync_ollama.effective_num_ctx_cap(None, 69632) == 0

    def test_explicit_cap_always_applies(self):
        assert sync_ollama.effective_num_ctx_cap(16384, 69632) == 16384

    def test_explicit_zero_disables_the_cap(self):
        assert sync_ollama.effective_num_ctx_cap(0, None) == 0


class TestParseOllamaSettings:
    """The `ollama:` config section is parsed with the same no-PyYAML text scan
    the script uses everywhere else."""

    def test_reads_vram_and_kv_type(self):
        text = "config_version: 5\nollama:\n  vram_gb: 16          # GPU budget\n  kv_cache_type: q8_0\nmodels:\n  - name: x\n"
        assert sync_ollama.parse_ollama_settings(text) == {"vram_gb": 16.0, "kv_cache_type": "q8_0"}

    def test_absent_section_returns_empty(self):
        assert sync_ollama.parse_ollama_settings(CLEAN_CONFIG) == {}

    def test_section_header_comment_is_tolerated(self):
        text = "ollama:   # sizing\n  vram_gb: 24.5\n"
        assert sync_ollama.parse_ollama_settings(text) == {"vram_gb": 24.5}

    def test_invalid_values_are_dropped(self):
        text = "ollama:\n  vram_gb: lots\n  kv_cache_type: q2_K\n"
        assert sync_ollama.parse_ollama_settings(text) == {}

    def test_section_ends_at_next_top_level_key(self):
        text = "ollama:\n  vram_gb: 16\nsandbox:\n  vram_gb: 99\n"
        assert sync_ollama.parse_ollama_settings(text) == {"vram_gb": 16.0}


class TestResolveSizingSettings:
    _CONFIG = "ollama:\n  vram_gb: 16\n  kv_cache_type: q8_0\n"

    def test_config_values_apply(self):
        vram_bytes, kv = sync_ollama.resolve_sizing_settings(None, None, self._CONFIG)
        assert vram_bytes == 16 * GIB
        assert kv == "q8_0"

    def test_cli_overrides_config(self):
        vram_bytes, kv = sync_ollama.resolve_sizing_settings(24.0, "f16", self._CONFIG)
        assert vram_bytes == 24 * GIB
        assert kv == "f16"

    def test_defaults_without_config_or_cli(self):
        vram_bytes, kv = sync_ollama.resolve_sizing_settings(None, None, CLEAN_CONFIG)
        assert vram_bytes is None
        assert kv == "f16"


# ── Models bigger than VRAM ───────────────────────────────────────────────────
# Ollama splits whole layers between GPU and CPU (num_gpu); it does not offload
# MoE experts the way llama.cpp's --n-cpu-moe does (ollama/ollama#11772 is open),
# and when weights and KV cache do not both fit it keeps the cache and drops GPU
# layers (ollama/ollama#9750). So context is bought with layers, and the sizing
# has to be bounded in both directions: 4096 leaves the agent unable to run, and
# "whatever fits" evicts the weights it needs.
GPT_OSS_120B_SHOW = {
    "capabilities": ["tools", "thinking"],
    "model_info": {
        "general.architecture": "gptoss",
        "general.parameter_count": 116_800_000_000,
        "gptoss.block_count": 36,
        "gptoss.context_length": 131072,
        "gptoss.embedding_length": 2880,
        "gptoss.attention.head_count": 64,
        "gptoss.attention.head_count_kv": 8,
        "gptoss.attention.key_length": 64,
        "gptoss.attention.value_length": 64,
        "gptoss.expert_count": 128,
        "gptoss.expert_used_count": 4,
        "gptoss.expert_feed_forward_length": 2880,
    },
}
GPT_OSS_120B_WEIGHTS = int(60.8 * GIB)  # native MXFP4 on disk


class TestVramNumCtxLimitUnderOffload:
    """The regression this change exists for, bounded on both sides."""

    def test_a_model_bigger_than_vram_gets_a_window_the_agent_can_run_in(self):
        # Was MIN_VRAM_NUM_CTX (4096) — below the agent's own system prompt,
        # tool schemas, skills and memory, so the model was unusable.
        limit = sync_ollama.vram_num_ctx_limit(GPT_OSS_120B_SHOW, GPT_OSS_120B_WEIGHTS, 24 * GIB)
        assert limit >= sync_ollama.MIN_OFFLOAD_NUM_CTX

    def test_it_does_not_hand_the_whole_card_to_the_kv_cache(self):
        # Ollama pays for context in GPU layers, so an unbounded window would
        # push the weights onto the CPU and make generation crawl. Cap the KV
        # cache's share of VRAM.
        limit = sync_ollama.vram_num_ctx_limit(GPT_OSS_120B_SHOW, GPT_OSS_120B_WEIGHTS, 24 * GIB)
        per_token = sync_ollama.parse_kv_bytes_per_token(GPT_OSS_120B_SHOW)
        assert limit * per_token <= 24 * GIB * sync_ollama.OFFLOAD_KV_VRAM_SHARE

    def test_a_model_that_fits_still_takes_all_the_spare_vram(self):
        # Every pre-existing expectation: the fits-in-VRAM path is untouched.
        assert sync_ollama.vram_num_ctx_limit(QWEN3_SHOW, QWEN3_WEIGHTS, 8 * GIB) == 10240
        assert sync_ollama.vram_num_ctx_limit(QWEN3_SHOW, QWEN3_WEIGHTS, 16 * GIB) == 69632

    def test_parallel_slots_still_divide_the_offloaded_window(self):
        one = sync_ollama.vram_num_ctx_limit(GPT_OSS_120B_SHOW, GPT_OSS_120B_WEIGHTS, 24 * GIB, "f16", 1)
        two = sync_ollama.vram_num_ctx_limit(GPT_OSS_120B_SHOW, GPT_OSS_120B_WEIGHTS, 24 * GIB, "f16", 2)
        assert two < one

    def test_unknown_geometry_returns_none(self):
        assert sync_ollama.vram_num_ctx_limit({"model_info": {}}, GPT_OSS_120B_WEIGHTS, 24 * GIB) is None

    def test_unknown_weights_returns_none(self):
        assert sync_ollama.vram_num_ctx_limit(GPT_OSS_120B_SHOW, None, 24 * GIB) is None


class TestSystemRamSetting:
    """`ollama.system_ram_gb` is the second memory pool offload spills into."""

    def test_reads_system_ram_gb(self):
        text = "ollama:\n  vram_gb: 24\n  system_ram_gb: 64\n"
        assert sync_ollama.parse_ollama_settings(text) == {"vram_gb": 24.0, "system_ram_gb": 64.0}

    def test_invalid_system_ram_is_dropped(self):
        text = "ollama:\n  vram_gb: 24\n  system_ram_gb: plenty\n"
        assert sync_ollama.parse_ollama_settings(text) == {"vram_gb": 24.0}

    def test_non_positive_system_ram_is_dropped(self):
        text = "ollama:\n  vram_gb: 24\n  system_ram_gb: 0\n"
        assert sync_ollama.parse_ollama_settings(text) == {"vram_gb": 24.0}


class TestOffloadCapacityWarning:
    """Weights that exceed VRAM + system RAM page from disk — tokens/sec collapses."""

    def test_warns_when_weights_exceed_both_pools(self):
        warning = sync_ollama.offload_capacity_warning(
            [("deepseek-v4-flash:q4", GPT_OSS_120B_SHOW, int(156 * GIB))],
            vram_bytes=24 * GIB,
            system_ram_bytes=64 * GIB,
        )
        assert warning is not None
        assert "deepseek-v4-flash:q4" in warning
        assert "156" in warning

    def test_silent_when_the_model_fits_the_two_pools(self):
        warning = sync_ollama.offload_capacity_warning(
            [("gpt-oss:120b", GPT_OSS_120B_SHOW, GPT_OSS_120B_WEIGHTS)],
            vram_bytes=24 * GIB,
            system_ram_bytes=64 * GIB,
        )
        assert warning is None

    def test_silent_without_a_system_ram_budget(self):
        # Nothing configured means nothing to compare against; stay quiet
        # rather than guessing the machine's RAM.
        warning = sync_ollama.offload_capacity_warning(
            [("huge:model", GPT_OSS_120B_SHOW, int(900 * GIB))],
            vram_bytes=24 * GIB,
            system_ram_bytes=None,
        )
        assert warning is None

    def test_names_every_oversized_model(self):
        warning = sync_ollama.offload_capacity_warning(
            [
                ("a:big", GPT_OSS_120B_SHOW, int(200 * GIB)),
                ("b:ok", GPT_OSS_120B_SHOW, GPT_OSS_120B_WEIGHTS),
                ("c:big", GPT_OSS_120B_SHOW, int(300 * GIB)),
            ],
            vram_bytes=24 * GIB,
            system_ram_bytes=64 * GIB,
        )
        assert "a:big" in warning
        assert "c:big" in warning
        assert "b:ok" not in warning


class TestVramContentionForBigModels:
    """Two models bigger than the card still evict each other."""

    def test_two_oversized_models_contend(self):
        loaded = [
            ("gpt-oss:120b", GPT_OSS_120B_SHOW, GPT_OSS_120B_WEIGHTS),
            ("gpt-oss:120b-b", GPT_OSS_120B_SHOW, GPT_OSS_120B_WEIGHTS),
        ]
        assert sync_ollama.vram_contention_warning(loaded, 24 * GIB) is not None

    def test_two_dense_models_that_fit_do_not(self):
        loaded = [
            ("qwen3:8b", QWEN3_SHOW, QWEN3_WEIGHTS),
            ("qwen3:8b-b", QWEN3_SHOW, QWEN3_WEIGHTS),
        ]
        assert sync_ollama.vram_contention_warning(loaded, 24 * GIB) is None
