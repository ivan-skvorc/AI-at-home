"""Tests for the Ollama daemon lifecycle layer (fork feature, roadmap item 9).

`scripts/sync-ollama-models.py` already computes a per-model VRAM-aware context
window from real attention geometry — and then stops at the config file. These
tests cover the step further out: `keep_alive` written into synced entries,
preloading the default model, and the VRAM-contention warning for a lead plus a
subagent that are both local.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sync-ollama-models.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("sync_ollama_models_lifecycle", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync_ollama = _load_script()


# A 8B-class model: 32 layers, 8 KV heads of 128, GQA.
SHOW_8B = {
    "model_info": {
        "general.architecture": "llama",
        "llama.block_count": 32,
        "llama.attention.head_count_kv": 8,
        "llama.attention.key_length": 128,
        "llama.attention.value_length": 128,
        "llama.context_length": 32768,
    },
    "capabilities": ["completion", "tools"],
}


# ---------------------------------------------------------------------------
# keep_alive settings
# ---------------------------------------------------------------------------


class TestParseKeepAlive:
    def test_absent_section_yields_no_keep_alive(self):
        settings = sync_ollama.parse_ollama_settings("models:\n  - name: x\n")
        assert "keep_alive" not in settings

    def test_scalar_keep_alive(self):
        settings = sync_ollama.parse_ollama_settings("ollama:\n  keep_alive: 30m\n")
        assert settings["keep_alive"] == "30m"

    def test_quoted_and_numeric_forms_survive(self):
        assert sync_ollama.parse_ollama_settings('ollama:\n  keep_alive: "1h"\n')["keep_alive"] == "1h"
        # Ollama accepts a bare number of seconds, and -1 for "never unload".
        assert sync_ollama.parse_ollama_settings("ollama:\n  keep_alive: -1\n")["keep_alive"] == "-1"

    def test_blank_keep_alive_is_dropped_rather_than_written_empty(self):
        settings = sync_ollama.parse_ollama_settings("ollama:\n  keep_alive:\n")
        assert "keep_alive" not in settings

    def test_per_model_overrides(self):
        text = "ollama:\n  keep_alive: 30m\n  keep_alive_overrides:\n    qwen3:8b: 2h\n    llama3.2: -1\n"
        settings = sync_ollama.parse_ollama_settings(text)
        assert settings["keep_alive"] == "30m"
        assert settings["keep_alive_overrides"] == {"qwen3:8b": "2h", "llama3.2": "-1"}

    def test_overrides_do_not_leak_into_the_flat_settings(self):
        text = "ollama:\n  keep_alive_overrides:\n    vram_gb: 99\n"
        settings = sync_ollama.parse_ollama_settings(text)
        # A key nested under the overrides map must not be read as ollama.vram_gb.
        assert "vram_gb" not in settings
        assert settings["keep_alive_overrides"] == {"vram_gb": "99"}

    def test_the_next_top_level_section_ends_the_scan(self):
        text = "ollama:\n  keep_alive: 30m\nmodels:\n  - name: x\n    keep_alive: 9h\n"
        assert sync_ollama.parse_ollama_settings(text)["keep_alive"] == "30m"

    def test_existing_sizing_keys_still_parse_alongside(self):
        text = "ollama:\n  vram_gb: 16\n  kv_cache_type: q8_0\n  keep_alive: 30m\n  preload: true\n"
        settings = sync_ollama.parse_ollama_settings(text)
        assert settings["vram_gb"] == 16
        assert settings["kv_cache_type"] == "q8_0"
        assert settings["keep_alive"] == "30m"
        assert settings["preload"] is True


class TestResolveKeepAlive:
    def test_cli_wins_over_config(self):
        assert sync_ollama.resolve_keep_alive("qwen3:8b", {"keep_alive": "30m"}, cli_keep_alive="1h") == "1h"

    def test_per_model_override_wins_over_the_global_default(self):
        settings = {"keep_alive": "30m", "keep_alive_overrides": {"qwen3:8b": "2h"}}
        assert sync_ollama.resolve_keep_alive("qwen3:8b", settings) == "2h"
        assert sync_ollama.resolve_keep_alive("llama3.2", settings) == "30m"

    def test_nothing_configured_writes_nothing(self):
        assert sync_ollama.resolve_keep_alive("qwen3:8b", {}) is None


class TestRenderEntryKeepAlive:
    def test_keep_alive_is_written_when_configured(self):
        entry = sync_ollama.render_entry("qwen3:8b", ["tools"], keep_alive="30m")
        assert "  keep_alive: 30m" in entry

    def test_absent_keep_alive_leaves_the_entry_unchanged(self):
        entry = sync_ollama.render_entry("qwen3:8b", ["tools"])
        assert "keep_alive" not in entry

    def test_sync_with_keep_alive_is_idempotent(self):
        config = "config_version: 3\nmodels:\n  - name: hand\n    use: x\nsandbox:\n  use: y\n"
        models = [("qwen3:8b", ["tools"], 8192, "30m")]
        once = sync_ollama.sync(config, models)
        twice = sync_ollama.sync(once, models)
        assert once == twice
        assert "keep_alive: 30m" in once


# ---------------------------------------------------------------------------
# VRAM contention
# ---------------------------------------------------------------------------


class TestVramContentionWarning:
    def test_no_budget_means_no_warning(self):
        loaded = [("a", SHOW_8B, 5 * 1024**3), ("b", SHOW_8B, 5 * 1024**3)]
        assert sync_ollama.vram_contention_warning(loaded, None, "f16") is None

    def test_a_single_local_model_cannot_contend_with_itself(self):
        loaded = [("a", SHOW_8B, 5 * 1024**3)]
        assert sync_ollama.vram_contention_warning(loaded, 8 * 1024**3, "f16") is None

    def test_two_models_that_fit_together_produce_no_warning(self):
        loaded = [("small-a", SHOW_8B, 2 * 1024**3), ("small-b", SHOW_8B, 2 * 1024**3)]
        assert sync_ollama.vram_contention_warning(loaded, 48 * 1024**3, "f16") is None

    def test_two_large_models_warn_with_the_actual_numbers(self):
        loaded = [("big-a", SHOW_8B, 20 * 1024**3), ("big-b", SHOW_8B, 18 * 1024**3)]
        warning = sync_ollama.vram_contention_warning(loaded, 24 * 1024**3, "f16")
        assert warning is not None
        # The two models are named and the arithmetic is shown, not a generic message.
        assert "big-a" in warning and "big-b" in warning
        assert "24" in warning  # the budget
        assert "GiB" in warning

    def test_the_warning_names_the_two_largest_pair(self):
        loaded = [
            ("tiny", SHOW_8B, 1 * 1024**3),
            ("big-a", SHOW_8B, 20 * 1024**3),
            ("big-b", SHOW_8B, 18 * 1024**3),
        ]
        warning = sync_ollama.vram_contention_warning(loaded, 24 * 1024**3, "f16")
        assert warning is not None
        assert "tiny" not in warning

    def test_unknown_geometry_degrades_to_weights_only_rather_than_silence(self):
        # A model whose attention geometry cannot be read still has a known
        # on-disk size; weights alone are enough to prove two do not co-reside.
        blind = {"model_info": {}, "capabilities": []}
        loaded = [("big-a", blind, 20 * 1024**3), ("big-b", blind, 18 * 1024**3)]
        warning = sync_ollama.vram_contention_warning(loaded, 24 * 1024**3, "f16")
        assert warning is not None

    def test_it_never_reassigns_anything(self):
        loaded = [("big-a", SHOW_8B, 20 * 1024**3), ("big-b", SHOW_8B, 18 * 1024**3)]
        warning = sync_ollama.vram_contention_warning(loaded, 24 * 1024**3, "f16")
        # A warning, not an instruction to switch models for the user.
        assert "switch" not in warning.lower()


# ---------------------------------------------------------------------------
# Preload
# ---------------------------------------------------------------------------


class TestDefaultLocalModel:
    def test_first_models_entry_wins_when_it_is_an_ollama_entry(self):
        text = "models:\n  - name: qwen3:8b\n    use: langchain_ollama:ChatOllama\n    model: qwen3:8b\n  - name: gpt\n    use: langchain_openai:ChatOpenAI\n"
        assert sync_ollama.default_local_model(text) == "qwen3:8b"

    def test_a_cloud_default_means_nothing_to_preload(self):
        # models[0] is the app's default (models/factory.py). Preloading a local
        # model that is not the default would warm the wrong weights.
        text = "models:\n  - name: gpt\n    use: langchain_openai:ChatOpenAI\n  - name: qwen3:8b\n    use: langchain_ollama:ChatOllama\n"
        assert sync_ollama.default_local_model(text) is None

    def test_no_models_section(self):
        assert sync_ollama.default_local_model("sandbox:\n  use: x\n") is None

    def test_the_model_field_wins_over_the_display_name(self):
        text = "models:\n  - name: local-fast\n    use: langchain_ollama:ChatOllama\n    model: qwen3:8b\n"
        assert sync_ollama.default_local_model(text) == "qwen3:8b"


class TestPreload:
    def test_preload_posts_a_zero_token_load_request(self):
        calls = []

        def fake_post(url, payload, timeout):
            calls.append((url, payload, timeout))
            return True

        ok = sync_ollama.preload_model("http://localhost:11434", "qwen3:8b", keep_alive="30m", post=fake_post)
        assert ok is True
        url, payload, _ = calls[0]
        assert url.endswith("/api/generate")
        assert payload["model"] == "qwen3:8b"
        # An empty prompt loads the weights without generating a single token.
        assert payload["prompt"] == ""
        assert payload["keep_alive"] == "30m"

    def test_preload_without_keep_alive_omits_the_key(self):
        calls = []

        def fake_post(url, payload, timeout):
            calls.append(payload)
            return True

        sync_ollama.preload_model("http://localhost:11434", "qwen3:8b", keep_alive=None, post=fake_post)
        assert "keep_alive" not in calls[0]

    def test_an_unreachable_daemon_is_not_an_error(self):
        def fake_post(url, payload, timeout):
            return False

        assert sync_ollama.preload_model("http://localhost:11434", "qwen3:8b", post=fake_post) is False


# ---------------------------------------------------------------------------
# doctor readiness check
# ---------------------------------------------------------------------------


class TestDoctorOllamaReadiness:
    def test_skips_cleanly_when_no_local_models_are_configured(self, tmp_path):
        import doctor

        config = tmp_path / "config.yaml"
        config.write_text("models:\n  - name: gpt\n    use: langchain_openai:ChatOpenAI\n", encoding="utf-8")
        results = doctor.check_ollama_readiness(config, probe=lambda host: None)
        assert [r.status for r in results] == ["skip"]

    def test_unreachable_daemon_warns_rather_than_fails(self, tmp_path):
        import doctor

        config = tmp_path / "config.yaml"
        config.write_text("models:\n  - name: qwen3:8b\n    use: langchain_ollama:ChatOllama\n", encoding="utf-8")
        results = doctor.check_ollama_readiness(config, probe=lambda host: None)
        assert results[0].status == "warn"
        assert "unreachable" in results[0].detail

    def test_configured_model_missing_from_the_daemon_is_named(self, tmp_path):
        import doctor

        config = tmp_path / "config.yaml"
        config.write_text("models:\n  - name: qwen3:8b\n    use: langchain_ollama:ChatOllama\n", encoding="utf-8")
        results = doctor.check_ollama_readiness(config, probe=lambda host: ["llama3.2:latest"])
        statuses = {r.label: r for r in results}
        installed = statuses["local models installed"]
        assert installed.status == "warn"
        assert "qwen3:8b" in installed.detail
        assert "ollama pull" in (installed.fix or "")

    def test_everything_present_reports_ok(self, tmp_path):
        import doctor

        config = tmp_path / "config.yaml"
        config.write_text("models:\n  - name: qwen3:8b\n    use: langchain_ollama:ChatOllama\n", encoding="utf-8")
        results = doctor.check_ollama_readiness(config, probe=lambda host: ["qwen3:8b"])
        assert all(r.status == "ok" for r in results), [(r.label, r.detail) for r in results]

    def test_missing_keep_alive_is_reported_as_a_cold_start_cost(self, tmp_path):
        import doctor

        config = tmp_path / "config.yaml"
        config.write_text("models:\n  - name: qwen3:8b\n    use: langchain_ollama:ChatOllama\n", encoding="utf-8")
        results = doctor.check_ollama_readiness(config, probe=lambda host: ["qwen3:8b"])
        keep_alive = next(r for r in results if r.label == "local model keep_alive")
        assert keep_alive.status == "ok"
        assert "not set" in keep_alive.detail
        assert "keep_alive" in (keep_alive.fix or "")

    def test_configured_keep_alive_is_reported(self, tmp_path):
        import doctor

        config = tmp_path / "config.yaml"
        config.write_text(
            "models:\n  - name: qwen3:8b\n    use: langchain_ollama:ChatOllama\n    keep_alive: 30m\nollama:\n  keep_alive: 30m\n",
            encoding="utf-8",
        )
        results = doctor.check_ollama_readiness(config, probe=lambda host: ["qwen3:8b"])
        keep_alive = next(r for r in results if r.label == "local model keep_alive")
        assert keep_alive.status == "ok"
        assert "30m" in keep_alive.detail

    def test_readiness_never_fails_the_doctor_exit_code(self, tmp_path):
        import doctor

        config = tmp_path / "config.yaml"
        config.write_text("models:\n  - name: qwen3:8b\n    use: langchain_ollama:ChatOllama\n", encoding="utf-8")
        results = doctor.check_ollama_readiness(config, probe=lambda host: None)
        assert all(r.status != "fail" for r in results)
