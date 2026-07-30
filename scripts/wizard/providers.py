"""LLM and search provider definitions for the Setup Wizard."""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass
class LLMProvider:
    name: str
    display_name: str
    description: str
    use: str
    models: list[str]
    default_model: str
    env_var: str | None
    package: str | None
    # Optional: some providers use a different field name for the API key in YAML
    api_key_field: str = "api_key"
    # Extra config fields beyond the common ones (merged into YAML)
    extra_config: dict = field(default_factory=dict)
    # Per-model supports_vision overrides for providers whose models differ in
    # capability (e.g. MiniMax M3 supports vision but M2.7 is text-only). The
    # provider-level extra_config holds the default (default_model) capability.
    model_vision_overrides: dict[str, bool] = field(default_factory=dict)
    auth_hint: str | None = None
    base_url_prompt: str | None = None
    model_prompt: str | None = None
    # For generic OpenAI-compatible gateways the wizard cannot infer whether the
    # user-supplied model supports thinking/reasoning, so prompt for it explicitly.
    ask_thinking_support: bool = False
    # When non-empty, the wizard writes this whole list of ready-to-use model
    # entries (the recommended latest set for the provider's single API key)
    # instead of prompting for one model. Used so first launch can enable the
    # full model set for the detected key — e.g. Anthropic Fable/Opus/Sonnet/Haiku,
    # or the OpenRouter Claude Fable + xAI/OpenAI/Google/alternatives set. Each dict
    # is a complete `models:` entry (already carrying api_key/base_url); the
    # first entry is treated as the primary/default model.
    bundle_models: list[dict] = field(default_factory=list)

    def extra_config_for(self, model_name: str) -> dict:
        """Return extra_config for a selected model, applying per-model overrides.

        Does not mutate the shared provider-level ``extra_config``.
        """
        config = dict(self.extra_config)
        if model_name in self.model_vision_overrides:
            config["supports_vision"] = self.model_vision_overrides[model_name]
        return config


@dataclass
class WebProvider:
    name: str
    display_name: str
    description: str
    use: str
    env_var: str | None  # None = no API key required
    tool_name: str
    extra_config: dict = field(default_factory=dict)


@dataclass
class SearchProvider:
    name: str
    display_name: str
    description: str
    use: str
    env_var: str | None  # None = no API key required
    tool_name: str = "web_search"
    extra_config: dict = field(default_factory=dict)


OPENAI_COMPAT_THINKING_CONFIG = {
    "supports_thinking": True,
    "when_thinking_enabled": {
        "extra_body": {
            "thinking": {
                "type": "enabled",
            }
        }
    },
    "when_thinking_disabled": {
        "extra_body": {
            "thinking": {
                "type": "disabled",
            }
        }
    },
}

# Latest Claude models (Opus 5, Opus 4.8, Sonnet 5) use adaptive thinking — the
# fixed `budget_tokens` form is rejected by these models. Haiku 4.5 still takes an
# explicit thinking budget. Opus 5 / Opus 4.8 / Sonnet 5 accept an explicit
# `thinking: {type: disabled}` when the toggle is off.
#
# Opus 5 caveat: it accepts `thinking: {type: disabled}` only at reasoning effort
# `high` or below (400 at `xhigh`/`max`). DeerFlow never sends an effort/
# `output_config` parameter to `langchain_anthropic:ChatAnthropic` — the factory
# only forwards `reasoning_effort` for models that opt in via
# `supports_reasoning_effort`, which these entries do not — so the API default
# (`high`) applies and the disable path stays legal.
#
# `display: summarized` is required for multi-turn tool use. These models default
# `thinking.display` to `"omitted"`, which returns thinking blocks whose `thinking`
# text is empty (only the encrypted `signature` is carried). When langchain-anthropic
# streams such a block it never sees a `thinking_delta`, so the reconstructed content
# block has no `thinking` key at all; replaying it on the next turn serializes to
# `{type: thinking, signature: ...}` with the field missing, and Anthropic rejects the
# request with `messages.N.content.0.thinking.thinking: Field required` (400). Asking
# for `summarized` makes the model return real (summarized) thinking text that streams
# and round-trips, so the block replays intact.
ANTHROPIC_ADAPTIVE_THINKING_CONFIG = {
    "supports_thinking": True,
    "when_thinking_enabled": {
        "thinking": {
            "type": "adaptive",
            "display": "summarized",
        }
    },
    "when_thinking_disabled": {
        "thinking": {
            "type": "disabled",
        }
    },
}

# Claude Fable 5 has thinking permanently on: an explicit
# `thinking: {type: disabled}` is rejected with a 400, so neither toggle state can
# turn thinking off. Both states therefore send adaptive thinking with
# `display: summarized` — `summarized` for the same multi-turn-replay reason as the
# adaptive config above (Fable's default `omitted` display otherwise breaks tool-use
# continuation), and `adaptive` (never `disabled`) so the disable path stays a legal
# request. This supersedes the earlier empty-`when_thinking_disabled` workaround: an
# empty dict avoided the disable-400 but left Fable on its default omitted display,
# which still tripped the replay-400 whenever the toggle was off.
ANTHROPIC_ALWAYS_ON_THINKING_CONFIG = {
    "supports_thinking": True,
    "when_thinking_enabled": {
        "thinking": {
            "type": "adaptive",
            "display": "summarized",
        }
    },
    "when_thinking_disabled": {
        "thinking": {
            "type": "adaptive",
            "display": "summarized",
        }
    },
}

ANTHROPIC_BUDGET_THINKING_CONFIG = {
    "supports_thinking": True,
    "when_thinking_enabled": {
        "thinking": {
            "type": "enabled",
            "budget_tokens": 4096,
        }
    },
    "when_thinking_disabled": {
        "thinking": {
            "type": "disabled",
        }
    },
}

# Retained for backward compatibility (older callers / the `other` gateway path).
ANTHROPIC_THINKING_CONFIG = ANTHROPIC_BUDGET_THINKING_CONFIG

# Latest Claude models, enabled together when the user has an ANTHROPIC_API_KEY.
# Fable 5 / Opus 5 / Opus 4.8 / Sonnet 5 use adaptive thinking; Haiku 4.5 takes a
# budget. Ordered most- to least-capable; Opus 4.8 is kept alongside its Opus 5
# successor so existing threads can stay pinned to it.
ANTHROPIC_BUNDLE_MODELS: list[dict] = [
    {
        "name": "claude-fable-5",
        "display_name": "Claude Fable 5 ($10/50) (Anthropic)",
        "use": "langchain_anthropic:ChatAnthropic",
        "model": "claude-fable-5",
        "api_key": "$ANTHROPIC_API_KEY",
        "default_request_timeout": 600.0,
        "max_retries": 2,
        "max_tokens": 32000,
        "supports_vision": True,
        **ANTHROPIC_ALWAYS_ON_THINKING_CONFIG,
    },
    {
        "name": "claude-opus-5",
        "display_name": "Claude Opus 5 ($5/25) (Anthropic)",
        "use": "langchain_anthropic:ChatAnthropic",
        "model": "claude-opus-5",
        "api_key": "$ANTHROPIC_API_KEY",
        "default_request_timeout": 600.0,
        "max_retries": 2,
        "max_tokens": 32000,
        "supports_vision": True,
        **ANTHROPIC_ADAPTIVE_THINKING_CONFIG,
    },
    {
        "name": "claude-opus-4-8",
        "display_name": "Claude Opus 4.8 ($5/25) (Anthropic)",
        "use": "langchain_anthropic:ChatAnthropic",
        "model": "claude-opus-4-8",
        "api_key": "$ANTHROPIC_API_KEY",
        "default_request_timeout": 600.0,
        "max_retries": 2,
        "max_tokens": 32000,
        "supports_vision": True,
        **ANTHROPIC_ADAPTIVE_THINKING_CONFIG,
    },
    {
        "name": "claude-sonnet-5",
        "display_name": "Claude Sonnet 5 ($3/15) (Anthropic)",
        "use": "langchain_anthropic:ChatAnthropic",
        "model": "claude-sonnet-5",
        "api_key": "$ANTHROPIC_API_KEY",
        "default_request_timeout": 600.0,
        "max_retries": 2,
        "max_tokens": 32000,
        "supports_vision": True,
        **ANTHROPIC_ADAPTIVE_THINKING_CONFIG,
    },
    {
        "name": "claude-haiku-4-5",
        "display_name": "Claude Haiku 4.5 ($1/5) (Anthropic)",
        "use": "langchain_anthropic:ChatAnthropic",
        "model": "claude-haiku-4-5",
        "api_key": "$ANTHROPIC_API_KEY",
        "default_request_timeout": 600.0,
        "max_retries": 2,
        "max_tokens": 16000,
        "supports_vision": True,
        **ANTHROPIC_BUDGET_THINKING_CONFIG,
    },
]


def _openrouter_model(
    name: str,
    display_name: str,
    model: str,
    *,
    supports_vision: bool = False,
    supports_thinking: bool = True,
    max_tokens: int = 32000,
    temperature: float | None = None,
) -> dict:
    """Build one OpenRouter model entry (shared api_key + base_url + defaults)."""
    entry: dict = {
        "name": name,
        "display_name": display_name,
        "use": "langchain_openai:ChatOpenAI",
        "model": model,
        "api_key": "$OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "request_timeout": 600.0,
        "max_retries": 2,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        entry["temperature"] = temperature
    entry["supports_vision"] = supports_vision
    if supports_thinking:
        entry["supports_thinking"] = True
    return entry


# One OPENROUTER_API_KEY reaches every provider. Claude Fable + Opus 5 plus the
# current xAI / OpenAI / Google / Meta flagships and strong open alternatives
# (MiniMax, Qwen, Kimi, Mistral, DeepSeek, GLM, Nemotron). Slugs current as of
# 2026-07.
#
# Two slugs corrected in this refresh — both named models that never shipped, so
# selecting them failed at request time:
#   - `openai/gpt-5.5-codex` -> `openai/gpt-5.3-codex`. There is no 5.5/5.6 Codex;
#     5.3-Codex is still the newest agentic-coding variant.
#   - `google/gemini-3.5-pro` -> dropped. Gemini 3.5 Pro has slipped three times
#     and is still unreleased (Google shipped 3.6 Flash / 3.5 Flash-Lite / Flash
#     Cyber on 2026-07-21 with no Pro). The newest shipped Pro is the older
#     `gemini-3.1-pro-preview`, which 3.5+ Flash already beats on coding, agentic
#     work and tool use — so the Gemini slot is one Flash entry, upgraded to 3.6.
#
# display_name markers (kept in sync with config.example.yaml's OpenRouter block):
#   ($<in>/<out>)        USD list price per 1M tokens (rough dropdown signal).
#   ($<list> → $<promo>*) a starred second pair = a temporary discount from
#                        OpenRouter's promotions page; the first pair is the list
#                        price. MiniMax M3 (60% off) and GLM-5.2 (51.65% off) as of
#                        2026-07 — drop the starred pair back to list when a promo ends.
#   (p)                  zero-data-retention NOT guaranteed (routed via OpenRouter to
#                        a third-party provider that may log prompts) — unlike the
#                        direct Anthropic bundle above.
OPENROUTER_BUNDLE_MODELS: list[dict] = [
    _openrouter_model("openrouter-fable-5", "Claude Fable 5 ($10/50) (OpenRouter) (p)", "anthropic/claude-fable-5", supports_vision=True),
    _openrouter_model("openrouter-opus-5", "Claude Opus 5 ($5/25) (OpenRouter) (p)", "anthropic/claude-opus-5", supports_vision=True),
    _openrouter_model("openrouter-grok-4.5", "Grok 4.5 ($2/6) (OpenRouter) (p)", "x-ai/grok-4.5", supports_vision=True),
    _openrouter_model("openrouter-gpt-5.6-sol", "GPT-5.6 Sol ($5/30) (OpenRouter) (p)", "openai/gpt-5.6-sol", supports_vision=True),
    _openrouter_model("openrouter-gpt-5.3-codex", "GPT-5.3 Codex ($1.75/14) (OpenRouter) (p)", "openai/gpt-5.3-codex", supports_vision=True),
    _openrouter_model("openrouter-gemini-3.6-flash", "Gemini 3.6 Flash ($1.5/7.5) (OpenRouter) (p)", "google/gemini-3.6-flash", supports_vision=True),
    _openrouter_model("openrouter-llama-4-maverick", "Llama 4 Maverick ($0.2/0.8) (OpenRouter) (p)", "meta-llama/llama-4-maverick", supports_vision=True, supports_thinking=False),
    _openrouter_model("openrouter-minimax-m3", "MiniMax M3 ($0.6/2.4 → $0.24/0.96*) (OpenRouter) (p)", "minimax/minimax-m3", supports_vision=True, max_tokens=16000, temperature=1.0),
    _openrouter_model("openrouter-qwen3.7-max", "Qwen3.7 Max ($1.5/4.4) (OpenRouter) (p)", "qwen/qwen3.7-max"),
    _openrouter_model("openrouter-kimi-k3", "Kimi K3 ($3/15) (OpenRouter) (p)", "moonshotai/kimi-k3", supports_vision=True),
    _openrouter_model("openrouter-mistral-large-3", "Mistral Large 3 ($0.5/1.5) (OpenRouter) (p)", "mistralai/mistral-large-2512", supports_vision=True, supports_thinking=False),
    _openrouter_model("openrouter-deepseek-v4-pro", "DeepSeek V4 Pro ($0.44/0.87) (OpenRouter) (p)", "deepseek/deepseek-v4-pro"),
    _openrouter_model("openrouter-glm-5.2", "GLM-5.2 ($1.4/4.4 → $0.68/2.13*) (OpenRouter) (p)", "z-ai/glm-5.2", max_tokens=16000),
    _openrouter_model("openrouter-nemotron-3-ultra", "Nemotron 3 Ultra ($0.5/2.2) (OpenRouter) (p)", "nvidia/nemotron-3-ultra-550b-a55b", max_tokens=16000),
]


def with_thinking_support(provider: LLMProvider, supports_thinking: bool) -> LLMProvider:
    """Return a copy of *provider* with thinking-capability flags applied.

    For generic OpenAI-compatible gateways the wizard cannot infer whether the
    user-supplied model supports thinking/reasoning. When the user confirms
    support we also wire the common OpenAI-compatible enable/disable toggles so
    the runtime can switch thinking on and off; otherwise we record the
    capability as unsupported. The shared provider definition is never mutated.
    """
    if supports_thinking:
        extra_config = {**provider.extra_config, **OPENAI_COMPAT_THINKING_CONFIG}
    else:
        extra_config = {**provider.extra_config, "supports_thinking": False}
    return replace(provider, extra_config=extra_config)


LLM_PROVIDERS: list[LLMProvider] = [
    LLMProvider(
        name="volcengine",
        display_name="Volcengine Doubao",
        description="Doubao Seed with thinking support",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        models=["doubao-seed-1-8-251228"],
        default_model="doubao-seed-1-8-251228",
        env_var="VOLCENGINE_API_KEY",
        package="langchain-deepseek",
        extra_config={
            "api_base": "https://ark.cn-beijing.volces.com/api/v3",
            "timeout": 600.0,
            "max_retries": 2,
            "supports_vision": True,
            "supports_reasoning_effort": True,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
    ),
    LLMProvider(
        name="volcengine_codingplan",
        display_name="Volcengine Coding Plan",
        description="One key, multi-vendor models (Doubao/GLM/DeepSeek/Kimi/MiniMax)",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        models=[
            "doubao-seed-2.0-code",
            "doubao-seed-2.0-pro",
            "doubao-seed-2.0-lite",
            "doubao-seed-code",
            "minimax-m2.7",
            "minimax-m3",
            "glm-5.2",
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "kimi-k2.6",
            "kimi-k2.7-code",
        ],
        default_model="glm-5.2",
        env_var="VOLCENGINE_API_KEY",
        package="langchain-deepseek",
        extra_config={
            "api_base": "https://ark.cn-beijing.volces.com/api/coding/v3",
            "timeout": 600.0,
            "max_retries": 2,
            "supports_vision": True,
            "supports_reasoning_effort": True,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
        model_vision_overrides={
            "doubao-seed-2.0-code": True,
            "doubao-seed-2.0-pro": True,
            "doubao-seed-2.0-lite": True,
            "doubao-seed-code": True,
            "minimax-m2.7": False,
            "minimax-m3": True,
            "glm-5.2": False,
            "deepseek-v4-flash": False,
            "deepseek-v4-pro": False,
            "kimi-k2.6": False,
            "kimi-k2.7-code": False,
        },
    ),
    LLMProvider(
        name="openai",
        display_name="OpenAI",
        description="GPT-5, GPT-4.1, GPT-4o",
        use="langchain_openai:ChatOpenAI",
        models=["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o"],
        default_model="gpt-5",
        env_var="OPENAI_API_KEY",
        package="langchain-openai",
        extra_config={
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 4096,
            "temperature": 0.7,
            "supports_vision": True,
        },
    ),
    LLMProvider(
        name="openai_responses",
        display_name="OpenAI Responses API",
        description="GPT-5 via /v1/responses",
        use="langchain_openai:ChatOpenAI",
        models=["gpt-5", "gpt-5-mini"],
        default_model="gpt-5",
        env_var="OPENAI_API_KEY",
        package="langchain-openai",
        extra_config={
            "request_timeout": 600.0,
            "max_retries": 2,
            "use_responses_api": True,
            "output_version": "responses/v1",
            "supports_vision": True,
        },
    ),
    LLMProvider(
        name="anthropic",
        display_name="Anthropic",
        description="Latest Claude Fable 5, Opus 5, Opus 4.8, Sonnet 5 and Haiku 4.5",
        use="langchain_anthropic:ChatAnthropic",
        models=["claude-fable-5", "claude-opus-5", "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
        default_model="claude-opus-5",
        env_var="ANTHROPIC_API_KEY",
        package="langchain-anthropic",
        extra_config={
            "default_request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 32000,
            "supports_vision": True,
            **ANTHROPIC_ADAPTIVE_THINKING_CONFIG,
        },
        bundle_models=ANTHROPIC_BUNDLE_MODELS,
    ),
    LLMProvider(
        name="deepseek",
        display_name="DeepSeek",
        description="DeepSeek V4 with thinking support",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        models=["deepseek-v4-pro", "deepseek-v4-flash"],
        default_model="deepseek-v4-pro",
        env_var="DEEPSEEK_API_KEY",
        package="langchain-deepseek",
        extra_config={
            "timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 8192,
            "supports_vision": False,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
    ),
    LLMProvider(
        name="google",
        display_name="Google Gemini",
        description="Native Gemini SDK, no thinking support",
        use="langchain_google_genai:ChatGoogleGenerativeAI",
        models=["gemini-2.5-pro", "gemini-2.0-flash"],
        default_model="gemini-2.5-pro",
        env_var="GEMINI_API_KEY",
        package="langchain-google-genai",
        api_key_field="gemini_api_key",
        extra_config={
            "timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 8192,
            "supports_vision": True,
        },
    ),
    LLMProvider(
        name="gemini_openai_gateway",
        display_name="Gemini OpenAI-compatible",
        description="Gemini thinking via an OpenAI-compatible gateway",
        use="deerflow.models.patched_openai:PatchedChatOpenAI",
        models=["google/gemini-2.5-pro-preview"],
        default_model="google/gemini-2.5-pro-preview",
        env_var="GEMINI_API_KEY",
        package="langchain-openai",
        extra_config={
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 16384,
            "supports_vision": True,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
        base_url_prompt="Gateway base URL (e.g. https://your-gateway.example/v1)",
    ),
    LLMProvider(
        name="ollama_qwen",
        display_name="Ollama Qwen3",
        description="Native local Ollama provider with thinking support",
        use="langchain_ollama:ChatOllama",
        models=["qwen3:32b"],
        default_model="qwen3:32b",
        env_var=None,
        package="langchain-ollama",
        extra_config={
            "base_url": "http://localhost:11434",
            "num_predict": 8192,
            "temperature": 0.7,
            "reasoning": True,
            "supports_thinking": True,
            "supports_vision": False,
        },
        auth_hint="No API key is required. Ensure Ollama is running and the model is pulled.",
    ),
    LLMProvider(
        name="ollama_gemma",
        display_name="Ollama Gemma",
        description="Native local Ollama provider with vision support",
        use="langchain_ollama:ChatOllama",
        models=["gemma4:27b"],
        default_model="gemma4:27b",
        env_var=None,
        package="langchain-ollama",
        extra_config={
            "base_url": "http://localhost:11434",
            "num_predict": 8192,
            "temperature": 0.7,
            "reasoning": True,
            "supports_thinking": True,
            "supports_vision": True,
        },
        auth_hint="No API key is required. Ensure Ollama is running and the model is pulled.",
    ),
    LLMProvider(
        name="mimo",
        display_name="Xiaomi MiMo",
        description="MiMo thinking models with reasoning replay",
        use="deerflow.models.patched_mimo:PatchedChatMiMo",
        models=["mimo-v2.5-pro", "mimo-v2.5", "mimo-v2-pro", "mimo-v2-omni", "mimo-v2-flash"],
        default_model="mimo-v2.5-pro",
        env_var="MIMO_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://api.xiaomimimo.com/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 8192,
            "supports_vision": False,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
    ),
    LLMProvider(
        name="kimi",
        display_name="Moonshot Kimi",
        description="Kimi K2.5 with thinking support",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        models=["kimi-k2.5"],
        default_model="kimi-k2.5",
        env_var="MOONSHOT_API_KEY",
        package="langchain-deepseek",
        extra_config={
            "api_base": "https://api.moonshot.cn/v1",
            "timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 32768,
            "supports_vision": True,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
    ),
    LLMProvider(
        name="novita",
        display_name="Novita AI",
        description="DeepSeek V3.2 via OpenAI-compatible API",
        use="langchain_openai:ChatOpenAI",
        models=["deepseek/deepseek-v3.2"],
        default_model="deepseek/deepseek-v3.2",
        env_var="NOVITA_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://api.novita.ai/openai",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 4096,
            "temperature": 0.7,
            "supports_vision": True,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
    ),
    LLMProvider(
        name="minimax",
        display_name="MiniMax",
        description="International OpenAI-compatible endpoint",
        use="langchain_openai:ChatOpenAI",
        models=["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed"],
        default_model="MiniMax-M3",
        env_var="MINIMAX_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://api.minimax.io/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 4096,
            "temperature": 1.0,
            "supports_vision": True,
            "supports_thinking": True,
        },
        model_vision_overrides={
            "MiniMax-M2.7": False,
            "MiniMax-M2.7-highspeed": False,
        },
    ),
    LLMProvider(
        name="minimax_cn",
        display_name="MiniMax CN",
        description="China OpenAI-compatible endpoint",
        use="langchain_openai:ChatOpenAI",
        models=["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed"],
        default_model="MiniMax-M3",
        env_var="MINIMAX_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://api.minimaxi.com/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 4096,
            "temperature": 1.0,
            "supports_vision": True,
            "supports_thinking": True,
        },
        model_vision_overrides={
            "MiniMax-M2.7": False,
            "MiniMax-M2.7-highspeed": False,
        },
    ),
    LLMProvider(
        name="openrouter",
        display_name="OpenRouter",
        description="One key: Claude Fable/Opus 5 + xAI/OpenAI/Google flagships & open alternatives",
        use="langchain_openai:ChatOpenAI",
        models=[entry["model"] for entry in OPENROUTER_BUNDLE_MODELS],
        default_model=OPENROUTER_BUNDLE_MODELS[0]["model"],
        env_var="OPENROUTER_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://openrouter.ai/api/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 16000,
        },
        bundle_models=OPENROUTER_BUNDLE_MODELS,
    ),
    LLMProvider(
        name="vllm",
        display_name="vLLM",
        description="Self-hosted OpenAI-compatible serving",
        use="deerflow.models.vllm_provider:VllmChatModel",
        models=["Qwen/Qwen3-32B", "Qwen/Qwen2.5-Coder-32B-Instruct"],
        default_model="Qwen/Qwen3-32B",
        env_var="VLLM_API_KEY",
        package=None,
        extra_config={
            "base_url": "http://localhost:8000/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 8192,
            "supports_thinking": True,
            "supports_vision": False,
            "when_thinking_enabled": {
                "extra_body": {
                    "chat_template_kwargs": {
                        "enable_thinking": True,
                    }
                }
            },
            "when_thinking_disabled": {
                "extra_body": {
                    "chat_template_kwargs": {
                        "enable_thinking": False,
                    }
                }
            },
        },
    ),
    LLMProvider(
        name="mindie",
        display_name="MindIE",
        description="Qwen3-Coder on MindIE Engine",
        use="deerflow.models.mindie_provider:MindIEChatModel",
        models=["Qwen3-Coder-480B-A35B-Instruct-Client"],
        default_model="Qwen3-Coder-480B-A35B-Instruct-Client",
        env_var="OPENAI_API_KEY",
        package=None,
        extra_config={
            "base_url": "http://localhost:8989/v1",
            "temperature": 0,
            "max_retries": 1,
            "supports_thinking": False,
            "supports_vision": False,
            "supports_reasoning_effort": False,
            "read_timeout": 900.0,
            "connect_timeout": 30.0,
            "write_timeout": 60.0,
            "pool_timeout": 30.0,
        },
    ),
    LLMProvider(
        name="codex",
        display_name="Codex CLI",
        description="Uses Codex CLI local auth (~/.codex/auth.json)",
        use="deerflow.models.openai_codex_provider:CodexChatModel",
        models=["gpt-5.4", "gpt-5-mini"],
        default_model="gpt-5.4",
        env_var=None,
        package=None,
        api_key_field="api_key",
        extra_config={"supports_thinking": True, "supports_reasoning_effort": True},
        auth_hint="Uses existing Codex CLI auth from ~/.codex/auth.json",
    ),
    LLMProvider(
        name="claude_code",
        display_name="Claude Code OAuth",
        description="Uses Claude Code local OAuth credentials",
        use="deerflow.models.claude_provider:ClaudeChatModel",
        models=["claude-sonnet-4-6", "claude-opus-4-1"],
        default_model="claude-sonnet-4-6",
        env_var=None,
        package=None,
        extra_config={"max_tokens": 4096, "supports_thinking": True},
        auth_hint="Uses Claude Code OAuth credentials from your local machine",
    ),
    LLMProvider(
        name="other",
        display_name="Other OpenAI-compatible",
        description="Custom gateway with base_url and model name",
        use="langchain_openai:ChatOpenAI",
        models=["gpt-4o"],
        default_model="gpt-4o",
        env_var="OPENAI_API_KEY",
        package="langchain-openai",
        base_url_prompt="Base URL (e.g. https://api.openai.com/v1)",
        model_prompt="Model name",
        ask_thinking_support=True,
    ),
]

SEARCH_PROVIDERS: list[SearchProvider] = [
    SearchProvider(
        name="searxng",
        display_name="SearXNG (self-hosted, free, no key needed)",
        description="Bundled with the Docker stacks; `make searxng` for host-run dev",
        use="deerflow.community.searxng.tools:web_search_tool",
        env_var=None,
        extra_config={"base_url": "http://localhost:8088", "max_results": 5},
    ),
    SearchProvider(
        name="ddg",
        display_name="DuckDuckGo (free, no key needed)",
        description="No API key or local service required",
        use="deerflow.community.ddg_search.tools:web_search_tool",
        env_var=None,
        extra_config={"max_results": 5},
    ),
    SearchProvider(
        name="tavily",
        display_name="Tavily",
        description="Recommended, free tier available",
        use="deerflow.community.tavily.tools:web_search_tool",
        env_var="TAVILY_API_KEY",
        extra_config={"max_results": 5},
    ),
    SearchProvider(
        name="infoquest",
        display_name="InfoQuest",
        description="Higher quality vertical search, API key required",
        use="deerflow.community.infoquest.tools:web_search_tool",
        env_var="INFOQUEST_API_KEY",
        extra_config={"search_time_range": 10},
    ),
    SearchProvider(
        name="exa",
        display_name="Exa",
        description="Neural + keyword web search, API key required",
        use="deerflow.community.exa.tools:web_search_tool",
        env_var="EXA_API_KEY",
        extra_config={
            "max_results": 5,
            "search_type": "auto",
            "contents_max_characters": 1000,
        },
    ),
    SearchProvider(
        name="firecrawl",
        display_name="Firecrawl",
        description="Search + crawl via Firecrawl API",
        use="deerflow.community.firecrawl.tools:web_search_tool",
        env_var="FIRECRAWL_API_KEY",
        extra_config={"max_results": 5},
    ),
    SearchProvider(
        name="fastcrw",
        display_name="fastCRW",
        description="Firecrawl-compatible web scraper, single binary, self-host or cloud",
        use="deerflow.community.fastcrw.tools:web_search_tool",
        env_var="CRW_API_KEY",
        extra_config={"max_results": 5},
    ),
    SearchProvider(
        name="brave",
        display_name="Brave Search",
        description="Independent index, official API, API key required",
        use="deerflow.community.brave.tools:web_search_tool",
        env_var="BRAVE_SEARCH_API_KEY",
        extra_config={"max_results": 5},
    ),
    SearchProvider(
        name="groundroute",
        display_name="GroundRoute",
        description="One key across six engines, price-routed with failover, API key required",
        use="deerflow.community.groundroute.tools:web_search_tool",
        env_var="GROUNDROUTE_API_KEY",
        extra_config={"max_results": 5},
    ),
]

WEB_FETCH_PROVIDERS: list[WebProvider] = [
    WebProvider(
        name="camoufox",
        display_name="Camoufox (local browser, no key needed)",
        description="JS-capable headless browser, auto-installed on launch; DeerFlow's default",
        use="deerflow.community.web_fetch.tools:web_fetch_tool",
        env_var=None,
        tool_name="web_fetch",
        extra_config={"backend": "camoufox"},
    ),
    WebProvider(
        name="jina_ai",
        display_name="Jina AI Reader",
        description="Cloud reader API, no API key required",
        use="deerflow.community.jina_ai.tools:web_fetch_tool",
        env_var=None,
        tool_name="web_fetch",
        extra_config={"timeout": 10},
    ),
    WebProvider(
        name="exa",
        display_name="Exa",
        description="API key required",
        use="deerflow.community.exa.tools:web_fetch_tool",
        env_var="EXA_API_KEY",
        tool_name="web_fetch",
    ),
    WebProvider(
        name="infoquest",
        display_name="InfoQuest",
        description="API key required",
        use="deerflow.community.infoquest.tools:web_fetch_tool",
        env_var="INFOQUEST_API_KEY",
        tool_name="web_fetch",
        extra_config={"timeout": 10, "fetch_time": 10, "navigation_timeout": 30},
    ),
    WebProvider(
        name="firecrawl",
        display_name="Firecrawl",
        description="Search-grade crawl with markdown output, API key required",
        use="deerflow.community.firecrawl.tools:web_fetch_tool",
        env_var="FIRECRAWL_API_KEY",
        tool_name="web_fetch",
    ),
    WebProvider(
        name="groundroute",
        display_name="GroundRoute",
        description="Page fetch via routed engines, API key required",
        use="deerflow.community.groundroute.tools:web_fetch_tool",
        env_var="GROUNDROUTE_API_KEY",
        tool_name="web_fetch",
    ),
    WebProvider(
        name="fastcrw",
        display_name="fastCRW",
        description="Firecrawl-compatible web scraper with markdown output, self-host or cloud",
        use="deerflow.community.fastcrw.tools:web_fetch_tool",
        env_var="CRW_API_KEY",
        tool_name="web_fetch",
    ),
    WebProvider(
        name="crawl4ai",
        display_name="Crawl4AI",
        description="Self-hosted headless Chromium with markdown output, no API key required",
        use="deerflow.community.crawl4ai.tools:web_fetch_tool",
        env_var=None,
        tool_name="web_fetch",
        extra_config={"base_url": "http://localhost:11235", "timeout": 30},
    ),
]
