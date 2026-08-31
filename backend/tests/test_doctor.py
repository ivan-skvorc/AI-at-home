"""Unit tests for scripts/doctor.py.

Run from repo root:
    cd backend && uv run pytest tests/test_doctor.py -v
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import doctor

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script(path: Path, name: str):
    assert path.exists(), f"{path} must exist"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# check_python
# ---------------------------------------------------------------------------


class TestCheckPython:
    def test_current_python_passes(self):
        result = doctor.check_python()
        assert sys.version_info >= (3, 12)
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# check_pnpm
# ---------------------------------------------------------------------------


class TestCheckPnpm:
    def test_resolves_shared_runner_from_relative_script_path(self, monkeypatch):
        # Load the script as `scripts/doctor.py`, as a user would from the
        # repository root. The derived paths must not depend on that relative
        # invocation path.
        monkeypatch.chdir(REPO_ROOT)
        relative_doctor = _load_script(Path("scripts/doctor.py"), "deerflow_doctor_relative")

        assert relative_doctor.PNPM_SCRIPT_PATH == REPO_ROOT / "scripts" / "pnpm.py"
        assert relative_doctor.PNPM_SCRIPT_PATH.is_absolute()
        assert relative_doctor.FRONTEND_DIR == REPO_ROOT / "frontend"
        assert relative_doctor.FRONTEND_DIR.is_absolute()

    def test_uses_shared_runner_from_frontend(self, monkeypatch):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return doctor.subprocess.CompletedProcess(cmd, 0, stdout="10.26.2\n", stderr="")

        monkeypatch.setattr(doctor.subprocess, "run", fake_run)

        result = doctor.check_pnpm()

        expected_runner = doctor.Path(doctor.__file__).with_name("pnpm.py")
        assert result.status == "ok"
        assert result.detail == "10.26.2"
        assert captured["cmd"] == [sys.executable, str(expected_runner), "-v"]
        assert captured["kwargs"]["cwd"] == expected_runner.parent.parent / "frontend"
        assert captured["kwargs"]["shell"] is False
        assert captured["kwargs"]["check"] is False

    def test_runner_failure_is_reported_as_failure(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return doctor.subprocess.CompletedProcess(
                cmd,
                42,
                stdout="",
                stderr="Error: pnpm command failed with exit status 42.\n",
            )

        monkeypatch.setattr(doctor.subprocess, "run", fake_run)

        result = doctor.check_pnpm()

        assert result.status == "fail"
        assert "exit status 42" in result.detail
        assert result.fix is not None


# ---------------------------------------------------------------------------
# check_config_exists
# ---------------------------------------------------------------------------


class TestCheckConfigExists:
    def test_missing_config(self, tmp_path):
        result = doctor.check_config_exists(tmp_path / "config.yaml")
        assert result.status == "fail"
        assert result.fix is not None

    def test_present_config(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\n")
        result = doctor.check_config_exists(cfg)
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# check_config_version
# ---------------------------------------------------------------------------


class TestCheckConfigVersion:
    def test_up_to_date(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\n")
        example = tmp_path / "config.example.yaml"
        example.write_text("config_version: 5\n")
        result = doctor.check_config_version(cfg, tmp_path)
        assert result.status == "ok"

    def test_outdated(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 3\n")
        example = tmp_path / "config.example.yaml"
        example.write_text("config_version: 5\n")
        result = doctor.check_config_version(cfg, tmp_path)
        assert result.status == "warn"
        assert result.fix is not None

    def test_missing_config_skipped(self, tmp_path):
        result = doctor.check_config_version(tmp_path / "config.yaml", tmp_path)
        assert result.status == "skip"


# ---------------------------------------------------------------------------
# check_config_loadable
# ---------------------------------------------------------------------------


class TestCheckConfigLoadable:
    def test_loadable_config(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\n")
        monkeypatch.setattr(doctor, "_load_app_config", lambda _path: object())
        result = doctor.check_config_loadable(cfg)
        assert result.status == "ok"

    def test_invalid_config(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\n")

        def fail(_path):
            raise ValueError("bad config")

        monkeypatch.setattr(doctor, "_load_app_config", fail)
        result = doctor.check_config_loadable(cfg)
        assert result.status == "fail"
        assert "bad config" in result.detail


# ---------------------------------------------------------------------------
# check_models_configured
# ---------------------------------------------------------------------------


class TestCheckModelsConfigured:
    def test_no_models(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels: []\n")
        result = doctor.check_models_configured(cfg)
        assert result.status == "fail"

    def test_one_model(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels:\n  - name: default\n    use: langchain_openai:ChatOpenAI\n    model: gpt-4o\n    api_key: $OPENAI_API_KEY\n")
        result = doctor.check_models_configured(cfg)
        assert result.status == "ok"

    def test_missing_config_skipped(self, tmp_path):
        result = doctor.check_models_configured(tmp_path / "config.yaml")
        assert result.status == "skip"


# ---------------------------------------------------------------------------
# check_llm_api_key
# ---------------------------------------------------------------------------


class TestCheckLLMApiKey:
    def test_key_set(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels:\n  - name: default\n    use: langchain_openai:ChatOpenAI\n    model: gpt-4o\n    api_key: $OPENAI_API_KEY\n")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        results = doctor.check_llm_api_key(cfg)
        assert any(r.status == "ok" for r in results)
        assert all(r.status != "fail" for r in results)

    def test_key_missing(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels:\n  - name: default\n    use: langchain_openai:ChatOpenAI\n    model: gpt-4o\n    api_key: $OPENAI_API_KEY\n")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        results = doctor.check_llm_api_key(cfg)
        assert any(r.status == "fail" for r in results)
        failed = [r for r in results if r.status == "fail"]
        assert all(r.fix is not None for r in failed)
        assert any("OPENAI_API_KEY" in (r.fix or "") for r in failed)

    def test_missing_config_returns_empty(self, tmp_path):
        results = doctor.check_llm_api_key(tmp_path / "config.yaml")
        assert results == []


# ---------------------------------------------------------------------------
# check_llm_auth
# ---------------------------------------------------------------------------


class TestCheckLLMAuth:
    def test_codex_auth_file_missing_fails(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels:\n  - name: codex\n    use: deerflow.models.openai_codex_provider:CodexChatModel\n    model: gpt-5.4\n")
        monkeypatch.setenv("CODEX_AUTH_PATH", str(tmp_path / "missing-auth.json"))
        results = doctor.check_llm_auth(cfg)
        assert any(result.status == "fail" and "Codex CLI auth available" in result.label for result in results)

    def test_claude_oauth_env_passes(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels:\n  - name: claude\n    use: deerflow.models.claude_provider:ClaudeChatModel\n    model: claude-sonnet-4-6\n")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "token")
        results = doctor.check_llm_auth(cfg)
        assert any(result.status == "ok" and "Claude auth available" in result.label for result in results)


# ---------------------------------------------------------------------------
# check_web_search
# ---------------------------------------------------------------------------


class TestCheckWebSearch:
    def test_ddg_always_ok(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "config_version: 5\nmodels:\n  - name: default\n    use: langchain_openai:ChatOpenAI\n    model: gpt-4o\n    api_key: $OPENAI_API_KEY\ntools:\n  - name: web_search\n    use: deerflow.community.ddg_search.tools:web_search_tool\n"
        )
        result = doctor.check_web_search(cfg)
        assert result.status == "ok"
        assert "DuckDuckGo" in result.detail

    def test_searxng_ok(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "config_version: 5\nmodels:\n  - name: default\n    use: langchain_openai:ChatOpenAI\n    model: gpt-4o\n    api_key: $OPENAI_API_KEY\n"
            "tools:\n  - name: web_search\n    use: deerflow.community.searxng.tools:web_search_tool\n    base_url: http://localhost:8088\n"
        )
        result = doctor.check_web_search(cfg)
        assert result.status == "ok"
        assert "SearXNG" in result.detail

    def test_tavily_with_key_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.tavily.tools:web_search_tool\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "ok"

    def test_tavily_without_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.tavily.tools:web_search_tool\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "warn"
        assert result.fix is not None
        assert "make setup" in result.fix

    def test_brave_with_key_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "bsa-test")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.brave.tools:web_search_tool\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "ok"

    def test_brave_without_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.brave.tools:web_search_tool\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "warn"
        assert result.fix is not None
        assert "BRAVE_SEARCH_API_KEY" in result.fix

    def test_brave_with_inline_api_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text('config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.brave.tools:web_search_tool\n    api_key: "inline-key"\n')
        result = doctor.check_web_search(cfg)
        assert result.status == "warn"
        assert "literal api_key set in config" in result.detail
        assert "BRAVE_SEARCH_API_KEY" in (result.fix or "")

    def test_brave_with_api_key_env_ref_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "bsa-test")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.brave.tools:web_search_tool\n    api_key: $BRAVE_SEARCH_API_KEY\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "ok"
        assert "BRAVE_SEARCH_API_KEY set from config" in result.detail

    def test_serper_with_key_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "test-key")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.serper.tools:web_search_tool\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "ok"
        assert "serper" in result.detail

    def test_serper_without_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.serper.tools:web_search_tool\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "warn"
        assert "SERPER_API_KEY" in (result.fix or "")

    def test_serper_inline_api_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.serper.tools:web_search_tool\n    api_key: inline-key\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "warn"
        assert "literal api_key set in config" in result.detail
        assert "SERPER_API_KEY" in (result.fix or "")

    def test_serper_config_env_ref_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "test-key")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.serper.tools:web_search_tool\n    api_key: $SERPER_API_KEY\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "ok"
        assert "SERPER_API_KEY set from config" in result.detail

    def test_serper_unresolved_env_ref_falls_back_to_default_var(self, tmp_path, monkeypatch):
        # The referenced $VAR is unset, but the default SERPER_API_KEY is set,
        # which the tool uses as a runtime fallback; report ok rather than warn.
        monkeypatch.delenv("MY_CUSTOM_SERPER_KEY", raising=False)
        monkeypatch.setenv("SERPER_API_KEY", "test-key")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.serper.tools:web_search_tool\n    api_key: $MY_CUSTOM_SERPER_KEY\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "ok"
        assert "SERPER_API_KEY set" in result.detail

    def test_serper_unresolved_env_ref_without_default_warns(self, tmp_path, monkeypatch):
        # Neither the referenced $VAR nor the default SERPER_API_KEY is set.
        monkeypatch.delenv("MY_CUSTOM_SERPER_KEY", raising=False)
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.serper.tools:web_search_tool\n    api_key: $MY_CUSTOM_SERPER_KEY\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "warn"
        assert "SERPER_API_KEY" in (result.fix or "")

    def test_tencent_wsa_without_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TENCENTCLOUD_WSA_APIKEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.tencent_wsa.tools:web_search_tool\n")

        result = doctor.check_web_search(cfg)

        assert result.status == "warn"
        assert "tencent_wsa configured but TENCENTCLOUD_WSA_APIKEY not set" in result.detail
        assert "TENCENTCLOUD_WSA_APIKEY" in (result.fix or "")

    def test_serply_with_key_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SERPLY_API_KEY", "test-key")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.serply.tools:web_search_tool\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "ok"
        assert "serply" in result.detail

    def test_serply_without_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SERPLY_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.serply.tools:web_search_tool\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "warn"
        assert "SERPLY_API_KEY" in (result.fix or "")

    def test_no_search_tool_warns(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools: []\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "warn"
        assert result.fix is not None
        assert "make setup" in result.fix

    def test_missing_config_skipped(self, tmp_path):
        result = doctor.check_web_search(tmp_path / "config.yaml")
        assert result.status == "skip"

    def test_invalid_provider_use_fails(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.not_real.tools:web_search_tool\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "fail"


# ---------------------------------------------------------------------------
# check_web_fetch
# ---------------------------------------------------------------------------


class TestCheckWebFetch:
    def test_jina_always_ok(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_fetch\n    use: deerflow.community.jina_ai.tools:web_fetch_tool\n")
        result = doctor.check_web_fetch(cfg)
        assert result.status == "ok"
        assert "Jina AI" in result.detail

    def test_firecrawl_without_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_fetch\n    use: deerflow.community.firecrawl.tools:web_fetch_tool\n")
        result = doctor.check_web_fetch(cfg)
        assert result.status == "warn"
        assert "FIRECRAWL_API_KEY" in (result.fix or "")

    def test_no_fetch_tool_warns(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools: []\n")
        result = doctor.check_web_fetch(cfg)
        assert result.status == "warn"
        assert result.fix is not None

    def test_invalid_provider_use_fails(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_fetch\n    use: deerflow.community.not_real.tools:web_fetch_tool\n")
        result = doctor.check_web_fetch(cfg)
        assert result.status == "fail"


# ---------------------------------------------------------------------------
# check_web_capture
# ---------------------------------------------------------------------------


class TestCheckWebCapture:
    def test_browserless_self_host_without_token_ok(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BROWSERLESS_TOKEN", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_capture\n    use: deerflow.community.browserless.tools:web_capture_tool\n    base_url: http://localhost:3032\n")

        result = doctor.check_web_capture(cfg)

        assert result.status == "ok"
        assert "self-hosted" in result.detail

    def test_browserless_token_env_ref_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BROWSERLESS_TOKEN", "browserless-test")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_capture\n    use: deerflow.community.browserless.tools:web_capture_tool\n    base_url: https://production-sfo.browserless.io\n    token: $BROWSERLESS_TOKEN\n")

        result = doctor.check_web_capture(cfg)

        assert result.status == "ok"
        assert "BROWSERLESS_TOKEN set from config" in result.detail

    def test_browserless_cloud_without_token_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BROWSERLESS_TOKEN", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_capture\n    use: deerflow.community.browserless.tools:web_capture_tool\n    base_url: https://production-sfo.browserless.io\n")

        result = doctor.check_web_capture(cfg)

        assert result.status == "warn"
        assert "BROWSERLESS_TOKEN" in (result.fix or "")


# ---------------------------------------------------------------------------
# check_image_search
# ---------------------------------------------------------------------------


class TestCheckImageSearch:
    def test_ddg_always_ok(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: image_search\n    use: deerflow.community.image_search.tools:image_search_tool\n")
        result = doctor.check_image_search(cfg)
        assert result.status == "ok"
        assert "DuckDuckGo" in result.detail

    def test_serper_with_key_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "test-key")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: image_search\n    use: deerflow.community.serper.tools:image_search_tool\n")
        result = doctor.check_image_search(cfg)
        assert result.status == "ok"
        assert "serper" in result.detail

    def test_serper_without_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: image_search\n    use: deerflow.community.serper.tools:image_search_tool\n")
        result = doctor.check_image_search(cfg)
        assert result.status == "warn"
        assert "SERPER_API_KEY" in (result.fix or "")

    def test_serper_inline_api_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: image_search\n    use: deerflow.community.serper.tools:image_search_tool\n    api_key: inline-key\n")
        result = doctor.check_image_search(cfg)
        assert result.status == "warn"
        assert "literal api_key set in config" in result.detail
        assert "SERPER_API_KEY" in (result.fix or "")

    def test_serper_config_env_ref_without_env_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: image_search\n    use: deerflow.community.serper.tools:image_search_tool\n    api_key: $SERPER_API_KEY\n")
        result = doctor.check_image_search(cfg)
        assert result.status == "warn"
        assert "SERPER_API_KEY" in (result.fix or "")

    def test_brave_image_search_with_key_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "bsa-test")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: image_search\n    use: deerflow.community.brave.tools:image_search_tool\n")
        result = doctor.check_image_search(cfg)
        assert result.status == "ok"
        assert "brave" in result.detail

    def test_brave_image_search_without_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: image_search\n    use: deerflow.community.brave.tools:image_search_tool\n")
        result = doctor.check_image_search(cfg)
        assert result.status == "warn"
        assert "BRAVE_SEARCH_API_KEY" in (result.fix or "")

    def test_brave_image_search_inline_api_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: image_search\n    use: deerflow.community.brave.tools:image_search_tool\n    api_key: inline-key\n")
        result = doctor.check_image_search(cfg)
        assert result.status == "warn"
        assert "literal api_key set in config" in result.detail
        assert "BRAVE_SEARCH_API_KEY" in (result.fix or "")

    def test_infoquest_with_key_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INFOQUEST_API_KEY", "test-key")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: image_search\n    use: deerflow.community.infoquest.tools:image_search_tool\n")
        result = doctor.check_image_search(cfg)
        assert result.status == "ok"
        assert "infoquest" in result.detail

    def test_no_image_search_tool_warns(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools: []\n")
        result = doctor.check_image_search(cfg)
        assert result.status == "warn"
        assert result.fix is not None

    def test_invalid_provider_use_fails(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: image_search\n    use: deerflow.community.not_real.tools:image_search_tool\n")
        result = doctor.check_image_search(cfg)
        assert result.status == "fail"


# ---------------------------------------------------------------------------
# check_env_file
# ---------------------------------------------------------------------------


class TestCheckEnvFile:
    def test_missing(self, tmp_path):
        result = doctor.check_env_file(tmp_path)
        assert result.status == "warn"

    def test_present(self, tmp_path):
        (tmp_path / ".env").write_text("KEY=val\n")
        result = doctor.check_env_file(tmp_path)
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# check_frontend_env
# ---------------------------------------------------------------------------


class TestCheckFrontendEnv:
    def test_missing(self, tmp_path):
        result = doctor.check_frontend_env(tmp_path)
        assert result.status == "warn"

    def test_present(self, tmp_path):
        frontend_dir = tmp_path / "frontend"
        frontend_dir.mkdir()
        (frontend_dir / ".env").write_text("KEY=val\n")
        result = doctor.check_frontend_env(tmp_path)
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# check_sandbox
# ---------------------------------------------------------------------------


class TestCheckSandbox:
    def test_missing_sandbox_fails(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\n")
        results = doctor.check_sandbox(cfg)
        assert results[0].status == "fail"

    def test_local_sandbox_with_disabled_host_bash_warns(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nsandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n  allow_host_bash: false\ntools:\n  - name: bash\n    use: deerflow.sandbox.tools:bash_tool\n")
        results = doctor.check_sandbox(cfg)
        assert any(result.status == "warn" for result in results)

    def test_container_sandbox_without_runtime_warns(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nsandbox:\n  use: deerflow.community.aio_sandbox:AioSandboxProvider\ntools: []\n")
        monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
        results = doctor.check_sandbox(cfg)
        assert any(result.label == "container runtime available" and result.status == "warn" for result in results)

    def test_container_sandbox_without_bash_tool_warns(self, tmp_path):
        """A container sandbox with no bash tool means the agent cannot run commands at all."""
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nsandbox:\n  use: deerflow.community.aio_sandbox:AioSandboxProvider\ntools:\n  - name: web_search\n    use: deerflow.community.searxng.tools:web_search_tool\n")
        results = doctor.check_sandbox(cfg)
        bash_result = next(result for result in results if result.label == "bash tool present")
        assert bash_result.status == "warn"
        assert "config-upgrade" in bash_result.fix

    def test_container_sandbox_with_bash_tool_does_not_warn_about_bash(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nsandbox:\n  use: deerflow.community.aio_sandbox:AioSandboxProvider\ntools:\n  - name: bash\n    use: deerflow.sandbox.tools:bash_tool\n")
        monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/docker")
        results = doctor.check_sandbox(cfg)
        assert all(result.label != "bash tool present" for result in results)


# ---------------------------------------------------------------------------
# check_core_tools
# ---------------------------------------------------------------------------


_ALL_CORE_TOOLS_YAML = "tools:\n" + "".join(f"  - name: {name}\n    use: example.module:{name}_tool\n" for name in doctor.CORE_TOOL_NAMES)


class TestCheckCoreTools:
    def test_missing_config_skipped(self, tmp_path):
        result = doctor.check_core_tools(tmp_path / "config.yaml")
        assert result.status == "skip"

    def test_full_default_toolset_ok(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(f"config_version: 5\n{_ALL_CORE_TOOLS_YAML}")
        result = doctor.check_core_tools(cfg)
        assert result.status == "ok"

    def test_missing_tools_are_named_in_warning(self, tmp_path):
        """The wizard-declined-bash case: bash and web_fetch absent from the list."""
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.searxng.tools:web_search_tool\n  - name: ls\n    use: deerflow.sandbox.tools:ls_tool\n")
        result = doctor.check_core_tools(cfg)
        assert result.status == "warn"
        assert "bash" in result.detail
        assert "web_fetch" in result.detail
        assert "config-upgrade" in result.fix

    def test_no_tools_section_fails(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels: []\n")
        result = doctor.check_core_tools(cfg)
        assert result.status == "fail"
        assert "config-upgrade" in result.fix


# ---------------------------------------------------------------------------
# main() exit code
# ---------------------------------------------------------------------------


class TestMainExitCode:
    def test_returns_int(self, tmp_path, monkeypatch, capsys):
        """main() should return 0 or 1 without raising."""
        repo_root = tmp_path / "repo"
        scripts_dir = repo_root / "scripts"
        scripts_dir.mkdir(parents=True)
        fake_doctor = scripts_dir / "doctor.py"
        fake_doctor.write_text("# test-only shim for __file__ resolution\n")

        monkeypatch.chdir(repo_root)
        monkeypatch.setattr(doctor, "__file__", str(fake_doctor))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)

        exit_code = doctor.main()

        captured = capsys.readouterr()
        output = captured.out + captured.err

        assert exit_code in (0, 1)
        assert output
        assert "config.yaml" in output
        assert ".env" in output


# ---------------------------------------------------------------------------
# check_env_placeholders
# ---------------------------------------------------------------------------


class TestCheckEnvPlaceholders:
    def test_missing_var_in_active_section_fails(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nchannels:\n  telegram:\n    enabled: true\n    bot_token: $TELEGRAM_BOT_TOKEN\n")
        results = doctor.check_env_placeholders(cfg)
        present = next(r for r in results if r.label == "referenced env vars present")
        assert present.status == "fail"
        assert "TELEGRAM_BOT_TOKEN" in present.detail
        assert "502" in present.fix

    def test_missing_var_in_disabled_section_is_tolerated(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nchannels:\n  slack:\n    enabled: false\n    bot_token: $SLACK_BOT_TOKEN\n")
        results = doctor.check_env_placeholders(cfg)
        present = next(r for r in results if r.label == "referenced env vars present")
        assert present.status == "ok"
        note = next(r for r in results if r.label == "disabled-section placeholders")
        assert note.status == "ok"
        assert "SLACK_BOT_TOKEN" in note.detail

    def test_present_var_passes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nchannels:\n  telegram:\n    enabled: true\n    bot_token: $TELEGRAM_BOT_TOKEN\n")
        results = doctor.check_env_placeholders(cfg)
        present = next(r for r in results if r.label == "referenced env vars present")
        assert present.status == "ok"

    def test_no_config_returns_empty(self, tmp_path):
        assert doctor.check_env_placeholders(tmp_path / "missing.yaml") == []


class TestCheckModelPricing:
    """`make doctor` must be able to explain a `—` cost estimate.

    The cost display has no error path — an unpriceable model contributes
    nothing and the header renders a bare dash — so this is the one place a
    user can find out *why* before reading source.
    """

    @staticmethod
    def _config(tmp_path, models: str):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(f"config_version: 5\nmodels:\n{models}")
        return cfg

    def test_explicit_pricing_block_counts_as_priced(self, tmp_path):
        cfg = self._config(
            tmp_path,
            "  - name: m\n    display_name: Some Model\n    pricing:\n      currency: USD\n      input_per_million: 1\n      output_per_million: 2\n",
        )
        result = doctor.check_model_pricing(cfg)
        assert result.status == "ok"
        assert "1 model(s) priced" in result.detail

    def test_price_in_display_name_counts_as_priced(self, tmp_path):
        # The upgrade path for an existing install: no `pricing:` block, but the
        # name carries the pair the backend derives from.
        cfg = self._config(tmp_path, "  - name: m\n    display_name: Grok 4.5 ($2/6) (OpenRouter) (p)\n")
        result = doctor.check_model_pricing(cfg)
        assert result.status == "ok"
        assert "1 model(s) priced" in result.detail

    def test_no_priceable_model_warns_with_the_symptom(self, tmp_path):
        cfg = self._config(tmp_path, "  - name: m\n    display_name: Some Model\n  - name: n\n    display_name: Another\n")
        result = doctor.check_model_pricing(cfg)
        assert result.status == "warn"
        assert "—" in result.detail, "the check must name the symptom the user actually sees"
        assert "pricing:" in result.fix

    def test_mixed_priced_and_local_models_pass_and_name_the_unpriced(self, tmp_path):
        cfg = self._config(
            tmp_path,
            "  - name: cloud\n    display_name: Grok 4.5 ($2/6) (OpenRouter) (p)\n  - name: qwen3:32b\n    display_name: qwen3:32b (Ollama)\n",
        )
        result = doctor.check_model_pricing(cfg)
        # A local model is free by design, so this is informational, not a problem.
        assert result.status == "ok"
        assert "qwen3:32b" in result.detail

    def test_bare_version_number_is_not_mistaken_for_a_price(self, tmp_path):
        cfg = self._config(tmp_path, "  - name: m\n    display_name: Gemini 3.6 Flash\n")
        assert doctor.check_model_pricing(cfg).status == "warn"

    def test_missing_config_or_no_models_skips(self, tmp_path):
        assert doctor.check_model_pricing(tmp_path / "nope.yaml").status == "skip"
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels: []\n")
        assert doctor.check_model_pricing(cfg).status == "skip"

    def test_malformed_config_warns_instead_of_raising(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("models:\n  - [unclosed\n")
        assert doctor.check_model_pricing(cfg).status == "warn"


class TestCheckSpendBudget:
    """`make doctor` must explain a spend cap that is on but doing nothing.

    A currency budget silently measures nothing when no model carries a price —
    the same class of silent failure `model pricing` exists for, one level up.
    """

    @staticmethod
    def _config(tmp_path, body: str):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(f"config_version: 34\n{body}")
        return cfg

    _PRICED_MODEL = "models:\n  - name: m\n    display_name: Some Model ($1/2)\n"

    def test_skipped_when_not_enabled(self, tmp_path):
        cfg = self._config(tmp_path, "spend_budget:\n  enabled: false\n")
        assert doctor.check_spend_budget(cfg).status == "skip"

    def test_missing_section_is_skipped(self, tmp_path):
        assert doctor.check_spend_budget(self._config(tmp_path, "log_level: info\n")).status == "skip"

    def test_enabled_with_a_limit_and_a_priced_model_is_ok(self, tmp_path):
        cfg = self._config(tmp_path, f"spend_budget:\n  enabled: true\n  daily_limit: 5.0\n  window: calendar\n{self._PRICED_MODEL}")
        result = doctor.check_spend_budget(cfg)
        assert result.status == "ok"
        assert "calendar" in result.detail
        assert "daily 5" in result.detail

    def test_enabled_with_no_limit_fails_because_the_gateway_will_not_load(self, tmp_path):
        cfg = self._config(tmp_path, f"spend_budget:\n  enabled: true\n{self._PRICED_MODEL}")
        result = doctor.check_spend_budget(cfg)
        assert result.status == "fail"
        assert "daily_limit" in result.fix

    def test_enabled_without_any_priced_model_warns(self, tmp_path):
        cfg = self._config(tmp_path, "spend_budget:\n  enabled: true\n  daily_limit: 5.0\nmodels:\n  - name: local\n    display_name: Qwen3 8B (Ollama)\n")
        result = doctor.check_spend_budget(cfg)
        assert result.status == "warn"
        assert "measures nothing" in result.detail

    def test_memory_backend_warns_because_there_is_no_history(self, tmp_path):
        cfg = self._config(tmp_path, f"spend_budget:\n  enabled: true\n  daily_limit: 5.0\ndatabase:\n  backend: memory\n{self._PRICED_MODEL}")
        result = doctor.check_spend_budget(cfg)
        assert result.status == "warn"
        assert "no persisted spend history" in result.detail

    def test_missing_config_file_is_skipped(self, tmp_path):
        assert doctor.check_spend_budget(tmp_path / "nope.yaml").status == "skip"


class TestCheckMediaGeneration:
    """`make doctor` must surface VRAM held while nothing is generating.

    That is the silent case the GPU arbiter exists for: a Gateway that died
    mid-generation leaves the diffusion weights resident, nothing errors, and
    the next local chat turn merely runs several times slower because Ollama
    offloaded layers to system RAM.
    """

    @staticmethod
    def _config(tmp_path, body: str):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(f"config_version: 44\n{body}")
        return cfg

    _ENABLED = "tools:\n  - name: generate_image\n    use: deerflow.community.comfyui.tools:generate_image_tool\n"

    def test_skipped_when_the_media_tools_are_not_enabled(self, tmp_path):
        cfg = self._config(tmp_path, "tools:\n  - name: image_search\n    use: deerflow.community.image_search.tools:image_search_tool\n")
        results = doctor.check_media_generation(cfg)
        assert [r.status for r in results] == ["skip"]

    def test_commented_out_tool_entries_do_not_enable_the_check(self, tmp_path):
        cfg = self._config(tmp_path, "tools:\n  # - name: generate_image\n  #   use: deerflow.community.comfyui.tools:generate_image_tool\n")
        assert doctor.check_media_generation(cfg)[0].status == "skip"

    def test_an_unreachable_service_warns_with_the_fix(self, tmp_path):
        cfg = self._config(tmp_path, self._ENABLED)
        results = doctor.check_media_generation(cfg, probe=lambda _url: None, autostart=lambda: (True, "Docker and a GPU are available"))
        assert results[0].status == "warn"
        assert "make comfy-up" in results[0].fix

    def test_a_machine_that_never_auto_starts_one_is_skipped_rather_than_warned(self, tmp_path):
        """The tools ship enabled, so 'unreachable' must not cry wolf.

        On a GPU-less laptop nothing is wrong: no launch would have started a
        ComfyUI there, and the cloud generation skill still works. Warning on
        every `make doctor` run is how a real warning stops being read.
        """
        cfg = self._config(tmp_path, self._ENABLED)
        results = doctor.check_media_generation(cfg, probe=lambda _url: None, autostart=lambda: (False, "no GPU detected"))
        assert [r.status for r in results] == ["skip"]
        assert "no GPU detected" in results[0].detail

    def test_a_free_card_is_ok(self, tmp_path):
        cfg = self._config(tmp_path, self._ENABLED)
        results = doctor.check_media_generation(cfg, probe=lambda _url: {"devices": [{"torch_vram_total": 0}]}, nvidia_used=lambda: 200.0)
        assert [r.status for r in results] == ["ok", "ok"]
        assert "free" in results[1].detail

    def test_held_vram_while_idle_warns_and_says_how_to_free_it(self, tmp_path):
        cfg = self._config(tmp_path, self._ENABLED)
        results = doctor.check_media_generation(cfg, probe=lambda _url: {"devices": [{"torch_vram_total": 8 * 1024**3}]}, nvidia_used=lambda: 9000.0)
        residency = results[1]
        assert residency.status == "warn"
        assert "8.0 GiB" in residency.detail
        assert "/free" in residency.fix

    def test_vram_used_by_other_processes_is_reported_but_not_blamed_on_comfyui(self, tmp_path):
        cfg = self._config(tmp_path, self._ENABLED)
        results = doctor.check_media_generation(cfg, probe=lambda _url: {"devices": [{"torch_vram_total": 0}]}, nvidia_used=lambda: 12000.0)
        assert results[1].status == "ok"
        assert "other processes" in results[1].detail

    def test_the_base_url_comes_from_config_when_no_env_override(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEER_FLOW_COMFYUI_BASE_URL", raising=False)
        cfg = self._config(tmp_path, self._ENABLED + "media:\n  comfyui:\n    base_url: http://gpu-box:8188\n")
        seen = []

        def probe(url):
            seen.append(url)
            return None

        doctor.check_media_generation(cfg, probe=probe)
        assert seen == ["http://gpu-box:8188"]
