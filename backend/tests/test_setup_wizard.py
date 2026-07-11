"""Unit tests for the Setup Wizard (scripts/wizard/).

Run from repo root:
    cd backend && uv run pytest tests/test_setup_wizard.py -v
"""

from __future__ import annotations

import yaml
from wizard import ui as wizard_ui
from wizard.providers import LLM_PROVIDERS, SEARCH_PROVIDERS, WEB_FETCH_PROVIDERS, LLMProvider
from wizard.steps import channels as channels_step
from wizard.steps import llm as llm_step
from wizard.steps import ollama as ollama_step
from wizard.steps import search as search_step
from wizard.writer import (
    build_minimal_config,
    read_env_file,
    write_config_yaml,
    write_env_file,
)


class TestProviders:
    def test_llm_providers_not_empty(self):
        assert len(LLM_PROVIDERS) >= 8

    def test_llm_providers_cover_config_example_families(self):
        providers = {provider.name: provider for provider in LLM_PROVIDERS}

        expected = {
            "volcengine",
            "openai",
            "openai_responses",
            "ollama_qwen",
            "ollama_gemma",
            "anthropic",
            "google",
            "gemini_openai_gateway",
            "mimo",
            "deepseek",
            "kimi",
            "novita",
            "minimax",
            "minimax_cn",
            "openrouter",
            "vllm",
            "mindie",
            "codex",
            "claude_code",
        }
        assert expected.issubset(providers)

        assert providers["openai_responses"].extra_config["use_responses_api"] is True
        assert providers["gemini_openai_gateway"].use == "deerflow.models.patched_openai:PatchedChatOpenAI"
        assert providers["mimo"].use == "deerflow.models.patched_mimo:PatchedChatMiMo"
        assert providers["deepseek"].use == "deerflow.models.patched_deepseek:PatchedChatDeepSeek"
        assert providers["volcengine"].extra_config["api_base"] == "https://ark.cn-beijing.volces.com/api/v3"

    def test_minimax_vision_is_per_model(self):
        """M3 supports vision; M2.7 variants are text-only.

        The provider-level extra_config carries the default (M3) capability, but
        extra_config_for() must drop vision when an M2.7 model is selected.
        """
        providers = {provider.name: provider for provider in LLM_PROVIDERS}

        for name in ("minimax", "minimax_cn"):
            provider = providers[name]
            assert provider.extra_config["supports_vision"] is True
            assert provider.extra_config_for("MiniMax-M3")["supports_vision"] is True
            assert provider.extra_config_for("MiniMax-M2.7")["supports_vision"] is False
            assert provider.extra_config_for("MiniMax-M2.7-highspeed")["supports_vision"] is False
            # Override must not mutate the shared provider-level config.
            assert provider.extra_config["supports_vision"] is True

    def test_extra_config_for_returns_provider_config_without_override(self):
        """Providers without per-model overrides return their config unchanged."""
        providers = {provider.name: provider for provider in LLM_PROVIDERS}
        openai = providers["openai"]
        assert openai.extra_config_for("gpt-5") == openai.extra_config

    def test_llm_providers_have_required_fields(self):
        for p in LLM_PROVIDERS:
            assert p.name
            assert p.display_name
            assert p.use
            assert ":" in p.use, f"Provider '{p.name}' use path must contain ':'"
            assert p.models
            assert p.default_model in p.models

    def test_search_providers_have_required_fields(self):
        for sp in SEARCH_PROVIDERS:
            assert sp.name
            assert sp.display_name
            assert sp.use
            assert ":" in sp.use

    def test_search_and_fetch_include_firecrawl(self):
        assert any(provider.name == "firecrawl" for provider in SEARCH_PROVIDERS)
        assert any(provider.name == "firecrawl" for provider in WEB_FETCH_PROVIDERS)

    def test_web_fetch_providers_have_required_fields(self):
        for provider in WEB_FETCH_PROVIDERS:
            assert provider.name
            assert provider.display_name
            assert provider.use
            assert ":" in provider.use
            assert provider.tool_name == "web_fetch"

    def test_at_least_one_free_search_provider(self):
        """At least one search provider needs no API key."""
        free = [sp for sp in SEARCH_PROVIDERS if sp.env_var is None]
        assert free, "Expected at least one free (no-key) search provider"

    def test_at_least_one_free_web_fetch_provider(self):
        free = [provider for provider in WEB_FETCH_PROVIDERS if provider.env_var is None]
        assert free, "Expected at least one free (no-key) web fetch provider"


class TestBuildMinimalConfig:
    def test_produces_valid_yaml(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI / gpt-4o",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        data = yaml.safe_load(content)
        assert data is not None
        assert "models" in data
        assert len(data["models"]) == 1
        model = data["models"][0]
        assert model["name"] == "gpt-4o"
        assert model["use"] == "langchain_openai:ChatOpenAI"
        assert model["model"] == "gpt-4o"
        assert model["api_key"] == "$OPENAI_API_KEY"

    def test_gemini_uses_gemini_api_key_field(self):
        content = build_minimal_config(
            provider_use="langchain_google_genai:ChatGoogleGenerativeAI",
            model_name="gemini-2.0-flash",
            display_name="Gemini",
            api_key_field="gemini_api_key",
            env_var="GEMINI_API_KEY",
        )
        data = yaml.safe_load(content)
        model = data["models"][0]
        assert "gemini_api_key" in model
        assert model["gemini_api_key"] == "$GEMINI_API_KEY"
        assert "api_key" not in model

    def test_search_tool_included(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
            search_use="deerflow.community.tavily.tools:web_search_tool",
            search_extra_config={"max_results": 5},
        )
        data = yaml.safe_load(content)
        search_tool = next(t for t in data.get("tools", []) if t["name"] == "web_search")
        assert search_tool["max_results"] == 5

    def test_openrouter_defaults_are_preserved(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="google/gemini-2.5-flash-preview",
            display_name="OpenRouter",
            api_key_field="api_key",
            env_var="OPENROUTER_API_KEY",
            extra_model_config={
                "base_url": "https://openrouter.ai/api/v1",
                "request_timeout": 600.0,
                "max_retries": 2,
                "max_tokens": 8192,
                "temperature": 0.7,
            },
        )
        data = yaml.safe_load(content)
        model = data["models"][0]
        assert model["base_url"] == "https://openrouter.ai/api/v1"
        assert model["request_timeout"] == 600.0
        assert model["max_retries"] == 2
        assert model["max_tokens"] == 8192
        assert model["temperature"] == 0.7

    def test_web_fetch_tool_included(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
            web_fetch_use="deerflow.community.jina_ai.tools:web_fetch_tool",
            web_fetch_extra_config={"timeout": 10},
        )
        data = yaml.safe_load(content)
        fetch_tool = next(t for t in data.get("tools", []) if t["name"] == "web_fetch")
        assert fetch_tool["timeout"] == 10

    def test_no_search_tool_when_not_configured(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        data = yaml.safe_load(content)
        tool_names = [t["name"] for t in data.get("tools", [])]
        assert "web_search" not in tool_names
        assert "web_fetch" not in tool_names

    def test_sandbox_included(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        data = yaml.safe_load(content)
        assert "sandbox" in data
        assert "use" in data["sandbox"]
        assert data["sandbox"]["use"] == "deerflow.sandbox.local:LocalSandboxProvider"
        assert data["sandbox"]["allow_host_bash"] is False

    def test_bash_tool_disabled_by_default(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        data = yaml.safe_load(content)
        tool_names = [t["name"] for t in data.get("tools", [])]
        assert "bash" not in tool_names

    def test_can_enable_container_sandbox_and_bash(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
            sandbox_use="deerflow.community.aio_sandbox:AioSandboxProvider",
            include_bash_tool=True,
        )
        data = yaml.safe_load(content)
        assert data["sandbox"]["use"] == "deerflow.community.aio_sandbox:AioSandboxProvider"
        assert "allow_host_bash" not in data["sandbox"]
        tool_names = [t["name"] for t in data.get("tools", [])]
        assert "bash" in tool_names

    def test_can_disable_write_tools(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
            include_write_tools=False,
        )
        data = yaml.safe_load(content)
        tool_names = [t["name"] for t in data.get("tools", [])]
        assert "write_file" not in tool_names
        assert "str_replace" not in tool_names

    def test_config_version_present(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
            config_version=5,
        )
        data = yaml.safe_load(content)
        assert data["config_version"] == 5

    def test_cli_provider_does_not_emit_fake_api_key(self):
        content = build_minimal_config(
            provider_use="deerflow.models.openai_codex_provider:CodexChatModel",
            model_name="gpt-5.4",
            display_name="Codex CLI",
            api_key_field="api_key",
            env_var=None,
        )
        data = yaml.safe_load(content)
        model = data["models"][0]
        assert "api_key" not in model

    def test_responses_api_provider_defaults_are_preserved(self):
        provider = next(p for p in LLM_PROVIDERS if p.name == "openai_responses")
        content = build_minimal_config(
            provider_use=provider.use,
            model_name=provider.default_model,
            display_name=provider.display_name,
            api_key_field=provider.api_key_field,
            env_var=provider.env_var,
            extra_model_config=provider.extra_config,
        )
        data = yaml.safe_load(content)
        model = data["models"][0]
        assert model["use_responses_api"] is True
        assert model["output_version"] == "responses/v1"
        assert model["supports_vision"] is True

    def test_patched_thinking_provider_defaults_are_preserved(self):
        provider = next(p for p in LLM_PROVIDERS if p.name == "mimo")
        content = build_minimal_config(
            provider_use=provider.use,
            model_name=provider.default_model,
            display_name=provider.display_name,
            api_key_field=provider.api_key_field,
            env_var=provider.env_var,
            extra_model_config=provider.extra_config,
        )
        data = yaml.safe_load(content)
        model = data["models"][0]
        assert model["use"] == "deerflow.models.patched_mimo:PatchedChatMiMo"
        assert model["base_url"] == "https://api.xiaomimimo.com/v1"
        assert model["api_key"] == "$MIMO_API_KEY"
        assert model["supports_thinking"] is True
        assert model["when_thinking_enabled"]["extra_body"]["thinking"]["type"] == "enabled"
        assert model["when_thinking_disabled"]["extra_body"]["thinking"]["type"] == "disabled"

    def test_can_enable_selected_channel_connections(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
            channel_connection_providers=["feishu", "slack"],
        )

        data = yaml.safe_load(content)
        channel_connections = data["channel_connections"]

        assert channel_connections["enabled"] is True
        assert channel_connections["feishu"]["enabled"] is True
        assert channel_connections["slack"]["enabled"] is True
        assert channel_connections["telegram"]["enabled"] is False
        assert channel_connections["discord"]["enabled"] is False
        assert channel_connections["dingtalk"]["enabled"] is False
        assert channel_connections["wechat"]["enabled"] is False
        assert channel_connections["wecom"]["enabled"] is False

    def test_channel_connections_disabled_when_no_channels_selected(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
            channel_connection_providers=[],
        )

        data = yaml.safe_load(content)
        channel_connections = data["channel_connections"]

        assert channel_connections["enabled"] is False
        assert all(not config["enabled"] for provider, config in channel_connections.items() if provider != "enabled")


class TestLLMStep:
    def test_model_selection_defaults_to_provider_default_model(self, monkeypatch):
        provider = LLMProvider(
            name="test",
            display_name="Test",
            description="provider",
            use="langchain_openai:ChatOpenAI",
            models=["first-model", "default-model"],
            default_model="default-model",
            env_var="TEST_API_KEY",
            package="langchain-openai",
        )
        prompts: list[tuple[str, int | None]] = []

        def fake_choice(prompt, options, default=None):
            prompts.append((prompt, default))
            return default if default is not None else 0

        monkeypatch.setattr(llm_step, "LLM_PROVIDERS", [provider])
        monkeypatch.setattr(llm_step, "ask_choice", fake_choice)
        monkeypatch.setattr(llm_step, "ask_secret", lambda _prompt: "key")
        monkeypatch.setattr(llm_step, "print_header", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(llm_step, "print_info", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(llm_step, "print_success", lambda *_args, **_kwargs: None)

        result = llm_step.run_llm_step()

        assert result.model_name == "default-model"
        assert prompts == [("Enter choice", None), ("Select model", 1)]

    def test_base_url_prompt_is_used_for_custom_gateway(self, monkeypatch):
        provider = LLMProvider(
            name="gateway",
            display_name="Gateway",
            description="provider",
            use="langchain_openai:ChatOpenAI",
            models=["gateway/model"],
            default_model="gateway/model",
            env_var="GATEWAY_API_KEY",
            package="langchain-openai",
            base_url_prompt="Gateway URL",
        )

        monkeypatch.setattr(llm_step, "LLM_PROVIDERS", [provider])
        monkeypatch.setattr(llm_step, "ask_choice", lambda *_args, **_kwargs: 0)
        monkeypatch.setattr(llm_step, "ask_text", lambda *_args, **_kwargs: "https://gateway.example/v1")
        monkeypatch.setattr(llm_step, "ask_secret", lambda _prompt: "key")
        monkeypatch.setattr(llm_step, "print_header", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(llm_step, "print_info", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(llm_step, "print_success", lambda *_args, **_kwargs: None)

        result = llm_step.run_llm_step()

        assert result.base_url == "https://gateway.example/v1"


class TestChannelsStep:
    def test_returns_selected_channel_keys(self, monkeypatch):
        monkeypatch.setattr(channels_step, "print_header", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(channels_step, "print_info", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(channels_step, "print_success", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(channels_step, "ask_multi_choice", lambda *_args, **_kwargs: [0, 3, 6])

        result = channels_step.run_channels_step()

        assert result.enabled_providers == ["telegram", "feishu", "wecom"]

    def test_empty_selection_disables_channel_connections(self, monkeypatch):
        monkeypatch.setattr(channels_step, "print_header", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(channels_step, "print_info", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(channels_step, "print_success", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(channels_step, "ask_multi_choice", lambda *_args, **_kwargs: [])

        result = channels_step.run_channels_step()

        assert result.enabled_providers == []


class TestWizardUi:
    def test_multi_choice_blank_requires_input_without_default(self, monkeypatch):
        answers = iter(["", "2"])
        monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

        assert wizard_ui.ask_multi_choice("Pick", ["First", "Second"], default=None) == [1]

    def test_multi_choice_blank_accepts_empty_default(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _prompt: "")

        assert wizard_ui.ask_multi_choice("Pick", ["First", "Second"], default=[]) == []


# ---------------------------------------------------------------------------
# writer.py — env file helpers
# ---------------------------------------------------------------------------


class TestEnvFileHelpers:
    def test_write_and_read_new_file(self, tmp_path):
        env_file = tmp_path / ".env"
        write_env_file(env_file, {"OPENAI_API_KEY": "sk-test123"})
        pairs = read_env_file(env_file)
        assert pairs["OPENAI_API_KEY"] == "sk-test123"

    def test_update_existing_key(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=old-key\n")
        write_env_file(env_file, {"OPENAI_API_KEY": "new-key"})
        pairs = read_env_file(env_file)
        assert pairs["OPENAI_API_KEY"] == "new-key"
        # Should not duplicate
        content = env_file.read_text()
        assert content.count("OPENAI_API_KEY") == 1

    def test_preserve_existing_keys(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TAVILY_API_KEY=tavily-val\n")
        write_env_file(env_file, {"OPENAI_API_KEY": "sk-new"})
        pairs = read_env_file(env_file)
        assert pairs["TAVILY_API_KEY"] == "tavily-val"
        assert pairs["OPENAI_API_KEY"] == "sk-new"

    def test_preserve_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# My .env file\nOPENAI_API_KEY=old\n")
        write_env_file(env_file, {"OPENAI_API_KEY": "new"})
        content = env_file.read_text()
        assert "# My .env file" in content

    def test_read_ignores_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nKEY=value\n")
        pairs = read_env_file(env_file)
        assert "# comment" not in pairs
        assert pairs["KEY"] == "value"


# ---------------------------------------------------------------------------
# writer.py — write_config_yaml
# ---------------------------------------------------------------------------


class TestWriteConfigYaml:
    def test_generated_config_loadable_by_appconfig(self, tmp_path):
        """The generated config.yaml must be parseable (basic YAML validity)."""

        config_path = tmp_path / "config.yaml"
        write_config_yaml(
            config_path,
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI / gpt-4o",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        assert config_path.exists()
        with open(config_path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "models" in data

    def test_copies_example_defaults_for_unconfigured_sections(self, tmp_path):
        example_path = tmp_path / "config.example.yaml"
        example_path.write_text(
            yaml.safe_dump(
                {
                    "config_version": 5,
                    "log_level": "info",
                    "token_usage": {"enabled": True},
                    "tool_groups": [{"name": "web"}, {"name": "file:read"}, {"name": "file:write"}, {"name": "bash"}],
                    "tools": [
                        {
                            "name": "web_search",
                            "group": "web",
                            "use": "deerflow.community.ddg_search.tools:web_search_tool",
                            "max_results": 5,
                        },
                        {
                            "name": "web_fetch",
                            "group": "web",
                            "use": "deerflow.community.jina_ai.tools:web_fetch_tool",
                            "timeout": 10,
                        },
                        {
                            "name": "image_search",
                            "group": "web",
                            "use": "deerflow.community.image_search.tools:image_search_tool",
                            "max_results": 5,
                        },
                        {"name": "ls", "group": "file:read", "use": "deerflow.sandbox.tools:ls_tool"},
                        {"name": "write_file", "group": "file:write", "use": "deerflow.sandbox.tools:write_file_tool"},
                        {"name": "bash", "group": "bash", "use": "deerflow.sandbox.tools:bash_tool"},
                    ],
                    "sandbox": {
                        "use": "deerflow.sandbox.local:LocalSandboxProvider",
                        "allow_host_bash": False,
                    },
                    "summarization": {"max_tokens": 2048},
                },
                sort_keys=False,
            )
        )

        config_path = tmp_path / "config.yaml"
        write_config_yaml(
            config_path,
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI / gpt-4o",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        with open(config_path) as f:
            data = yaml.safe_load(f)

        assert data["log_level"] == "info"
        assert data["token_usage"]["enabled"] is True
        assert data["tool_groups"][0]["name"] == "web"
        assert data["summarization"]["max_tokens"] == 2048
        assert any(tool["name"] == "image_search" and tool["max_results"] == 5 for tool in data["tools"])

    def test_config_version_read_from_example(self, tmp_path):
        """write_config_yaml should read config_version from config.example.yaml if present."""

        example_path = tmp_path / "config.example.yaml"
        example_path.write_text("config_version: 99\n")

        config_path = tmp_path / "config.yaml"
        write_config_yaml(
            config_path,
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        with open(config_path) as f:
            data = yaml.safe_load(f)
        assert data["config_version"] == 99

    def test_model_base_url_from_extra_config(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        write_config_yaml(
            config_path,
            provider_use="langchain_openai:ChatOpenAI",
            model_name="google/gemini-2.5-flash-preview",
            display_name="OpenRouter",
            api_key_field="api_key",
            env_var="OPENROUTER_API_KEY",
            extra_model_config={"base_url": "https://openrouter.ai/api/v1"},
        )
        with open(config_path) as f:
            data = yaml.safe_load(f)
        assert data["models"][0]["base_url"] == "https://openrouter.ai/api/v1"


class TestSearchStep:
    def test_reuses_api_key_for_same_provider(self, monkeypatch):
        monkeypatch.setattr(search_step, "print_header", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(search_step, "print_success", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(search_step, "print_info", lambda *_args, **_kwargs: None)

        search_exa_idx = next(i for i, p in enumerate(search_step.SEARCH_PROVIDERS) if p.name == "exa")
        fetch_exa_idx = next(i for i, p in enumerate(search_step.WEB_FETCH_PROVIDERS) if p.name == "exa")
        choices = iter([search_exa_idx, fetch_exa_idx])
        prompts: list[str] = []

        def fake_choice(_prompt, _options, default=0):
            return next(choices)

        def fake_secret(prompt):
            prompts.append(prompt)
            return "shared-api-key"

        monkeypatch.setattr(search_step, "ask_choice", fake_choice)
        monkeypatch.setattr(search_step, "ask_secret", fake_secret)

        result = search_step.run_search_step()

        assert result.search_provider is not None
        assert result.fetch_provider is not None
        assert result.search_provider.name == "exa"
        assert result.fetch_provider.name == "exa"
        assert result.search_api_key == "shared-api-key"
        assert result.fetch_api_key == "shared-api-key"
        assert prompts == ["EXA_API_KEY"]


class TestOllamaSizingStep:
    """VRAM detection parsers + the optional Ollama context-sizing step."""

    def test_parse_nvidia_smi_sums_gpus(self):
        assert ollama_step.parse_nvidia_smi_gib("24576\n24576\n") == 48.0

    def test_parse_nvidia_smi_rejects_garbage(self):
        assert ollama_step.parse_nvidia_smi_gib("N/A\n") is None

    def test_parse_rocm_smi_sums_cards(self):
        payload = '{"card0": {"VRAM Total Memory (B)": "17179869184"}, "card1": {"VRAM Total Memory (B)": "17179869184"}}'
        assert ollama_step.parse_rocm_smi_gib(payload) == 32.0

    def test_parse_rocm_smi_rejects_garbage(self):
        assert ollama_step.parse_rocm_smi_gib("not json") is None

    def test_detect_prefers_nvidia_smi(self):
        def run(args, timeout=5.0):
            return "16384\n" if args[0] == "nvidia-smi" else None

        assert ollama_step.detect_vram_gb(run=run, system=lambda: "Linux") == (16.0, "nvidia-smi")

    def test_detect_falls_back_to_rocm_smi(self):
        def run(args, timeout=5.0):
            return '{"card0": {"VRAM Total Memory (B)": "17179869184"}}' if args[0] == "rocm-smi" else None

        detected = ollama_step.detect_vram_gb(run=run, system=lambda: "Linux")
        assert detected == (16.0, "rocm-smi")

    def test_detect_uses_metal_budget_on_macos(self):
        def run(args, timeout=5.0):
            return str(32 * 1024**3) if args[0] == "sysctl" else None

        detected = ollama_step.detect_vram_gb(run=run, system=lambda: "Darwin")
        assert detected is not None
        gib, source = detected
        assert gib == 32 * ollama_step.APPLE_METAL_FRACTION
        assert "Metal" in source

    def test_detect_returns_none_without_gpu_tools(self):
        assert ollama_step.detect_vram_gb(run=lambda *_a, **_k: None, system=lambda: "Linux") is None

    def _silence(self, monkeypatch):
        for name in ("print_header", "print_info", "print_success"):
            monkeypatch.setattr(ollama_step, name, lambda *_args, **_kwargs: None)
        monkeypatch.setattr(ollama_step, "detect_vram_gb", lambda *_args, **_kwargs: None)

    def test_step_collects_vram_and_q8(self, monkeypatch, capsys):
        self._silence(monkeypatch)
        monkeypatch.setattr(ollama_step, "ask_text", lambda *_args, **_kwargs: "16")
        monkeypatch.setattr(ollama_step, "ask_yes_no", lambda *_args, **_kwargs: True)

        result = ollama_step.run_ollama_step("Step 1/5")

        assert result.vram_gb == 16.0
        assert result.kv_cache_type == "q8_0"
        # The exact server-side setting must be shown when q8_0 is chosen.
        assert "OLLAMA_KV_CACHE_TYPE=q8_0" in capsys.readouterr().out

    def test_step_defaults_to_f16_when_q8_declined(self, monkeypatch):
        self._silence(monkeypatch)
        monkeypatch.setattr(ollama_step, "ask_text", lambda *_args, **_kwargs: "16")
        monkeypatch.setattr(ollama_step, "ask_yes_no", lambda *_args, **_kwargs: False)

        result = ollama_step.run_ollama_step("Step 1/5")

        assert result.vram_gb == 16.0
        assert result.kv_cache_type is None

    def test_blank_input_skips_sizing(self, monkeypatch):
        self._silence(monkeypatch)
        monkeypatch.setattr(ollama_step, "ask_text", lambda *_args, **_kwargs: "")

        result = ollama_step.run_ollama_step("Step 1/5")

        assert result.vram_gb is None
        assert result.kv_cache_type is None


class TestOllamaSectionInConfig:
    def test_ollama_section_written_when_vram_provided(self):
        content = build_minimal_config(
            provider_use="langchain_ollama:ChatOllama",
            model_name="qwen3:32b",
            display_name="Ollama / qwen3:32b",
            api_key_field="api_key",
            env_var=None,
            ollama_vram_gb=16.0,
            ollama_kv_cache_type="q8_0",
        )
        data = yaml.safe_load(content)
        assert data["ollama"] == {"vram_gb": 16.0, "kv_cache_type": "q8_0"}

    def test_kv_cache_type_omitted_when_unset(self):
        content = build_minimal_config(
            provider_use="langchain_ollama:ChatOllama",
            model_name="qwen3:32b",
            display_name="Ollama / qwen3:32b",
            api_key_field="api_key",
            env_var=None,
            ollama_vram_gb=16.0,
        )
        data = yaml.safe_load(content)
        assert data["ollama"] == {"vram_gb": 16.0}

    def test_no_ollama_section_without_vram(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-test",
            display_name="GPT Test",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        data = yaml.safe_load(content)
        assert "ollama" not in data
