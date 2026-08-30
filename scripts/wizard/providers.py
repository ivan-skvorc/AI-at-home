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
# Opus and Sonnet each ship their last 4.x alongside 5 (Opus 4.8 + Opus 5,
# Sonnet 4.6 + Sonnet 5); Haiku and Fable ship only the latest. Fable 5 / Opus 5 /
# Opus 4.8 / Sonnet 5 / Sonnet 4.6 use adaptive thinking; Haiku 4.5 takes a
# budget. Ordered most- to least-capable; the last-4.x models are kept alongside
# their 5 successors so existing threads can stay pinned to them.
ANTHROPIC_BUNDLE_MODELS: list[dict] = [
    {
        "name": "claude-fable-5",
        "display_name": "Claude Fable 5 (Anthropic)",
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
        "display_name": "Claude Opus 5 (Anthropic)",
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
        "display_name": "Claude Opus 4.8 (Anthropic)",
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
        "display_name": "Claude Sonnet 5 (Anthropic)",
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
        "name": "claude-sonnet-4-6",
        "display_name": "Claude Sonnet 4.6 (Anthropic)",
        "use": "langchain_anthropic:ChatAnthropic",
        "model": "claude-sonnet-4-6",
        "api_key": "$ANTHROPIC_API_KEY",
        "default_request_timeout": 600.0,
        "max_retries": 2,
        "max_tokens": 32000,
        "supports_vision": True,
        **ANTHROPIC_ADAPTIVE_THINKING_CONFIG,
    },
    {
        "name": "claude-haiku-4-5",
        "display_name": "Claude Haiku 4.5 (Anthropic)",
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


# One OPENROUTER_API_KEY reaches every provider. Claude Fable (the flagship,
# offered here for OpenRouter-only users — every other Claude lives on the direct
# Anthropic bundle above) plus the current xAI / OpenAI / Google / Meta flagships
# and strong open alternatives (MiniMax, Qwen, Kimi, Mistral, DeepSeek, GLM,
# Nemotron). Slugs current as of 2026-07.
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
#   (p)                  zero-data-retention NOT guaranteed (routed via OpenRouter to
#                        a third-party provider that may log prompts) — unlike the
#                        direct Anthropic bundle above.
#
# Prices are NOT in the name. They live in `MODEL_PRICES` below and are stamped
# onto each entry as a structured `price:` / `discount:` block. A name is a
# label; a price is data, and embedding one in the other meant the number a user
# read and the number they were billed against were two copies that could drift
# — and a discount could only "end" by someone editing a string.
OPENROUTER_BUNDLE_MODELS: list[dict] = [
    _openrouter_model("openrouter-fable-5", "Claude Fable 5 (OpenRouter) (p)", "anthropic/claude-fable-5", supports_vision=True),
    _openrouter_model("openrouter-grok-4.6", "Grok 4.6 (OpenRouter) (p)", "x-ai/grok-4.6", supports_vision=True),
    _openrouter_model("openrouter-gpt-5.6-sol", "GPT-5.6 Sol (OpenRouter) (p)", "openai/gpt-5.6-sol", supports_vision=True),
    _openrouter_model("openrouter-gpt-5.3-codex", "GPT-5.3 Codex (OpenRouter) (p)", "openai/gpt-5.3-codex", supports_vision=True),
    _openrouter_model("openrouter-gemini-3.6-flash", "Gemini 3.6 Flash (OpenRouter) (p)", "google/gemini-3.6-flash", supports_vision=True),
    _openrouter_model("openrouter-llama-4-maverick", "Llama 4 Maverick (OpenRouter) (p)", "meta-llama/llama-4-maverick", supports_vision=True, supports_thinking=False),
    _openrouter_model("openrouter-minimax-m3", "MiniMax M3 (OpenRouter) (p)", "minimax/minimax-m3", supports_vision=True, max_tokens=16000, temperature=1.0),
    _openrouter_model("openrouter-qwen3.8-max", "Qwen3.8 Max (OpenRouter) (p)", "qwen/qwen3.8-max"),
    _openrouter_model("openrouter-kimi-k3", "Kimi K3 (OpenRouter) (p)", "moonshotai/kimi-k3", supports_vision=True),
    _openrouter_model("openrouter-mistral-large-3", "Mistral Large 3 (OpenRouter) (p)", "mistralai/mistral-large-2512", supports_vision=True, supports_thinking=False),
    _openrouter_model("openrouter-deepseek-v4-pro", "DeepSeek V4 Pro (OpenRouter) (p)", "deepseek/deepseek-v4-pro"),
    _openrouter_model("openrouter-glm-5.3", "GLM-5.3 (OpenRouter) (p)", "z-ai/glm-5.3", max_tokens=16000),
    _openrouter_model("openrouter-nemotron-3-ultra", "Nemotron 3 Ultra (OpenRouter) (p)", "nvidia/nemotron-3-ultra-550b-a55b", max_tokens=16000),
]


# ── First-party "home" API bundles ─────────────────────────────────────────
# The direct-Anthropic bundle above enables the full Claude family on the native
# Anthropic API, while OpenRouter carries the flagships routed through one key.
# These bundles extend that same shape to every big-name lab that ships a
# first-party API: one bundle per provider, enabled when THAT provider's own key
# is present, so a lab's flagship is reachable through BOTH its home API and
# OpenRouter (the direct copy carries no `(p)` privacy caveat), and each lab's
# cheaper siblings are reachable through the home API only — mirroring how
# Anthropic's full lineup lives on the direct key while only Fable is doubled on
# OpenRouter. OpenRouter keeps its trim "one flagship per lab" set unchanged
# (including the GPT Sol + Codex double).
#
# Unlike the OpenRouter entries, these are direct/first-party, so their
# display_name carries the lab's own suffix — (OpenAI) / (xAI) / (Google) /
# (DeepSeek) / (Mistral) / (Moonshot) / (Qwen) / (MiniMax) / (z-ai), mirroring
# (Anthropic) — and never the `(p)` marker (no OpenRouter middleman). The price
# pair in the name is the provider's own list price; the OpenRouter-only promo
# stars stay on the OpenRouter entries. Slugs current as of 2026-08.
#
# The non-flagship siblings *look* like they follow each lab's tier naming, but
# that is an observation, not a rule you may apply: read every sibling id off the
# lab's own model list. Deriving one from the flagship's name is how the bundle
# came to ship `gpt-5.6-mini`, `grok-4.5-fast` and `glm-5.2-air`, none of which
# any lab released (FORK.md, audit log 2026-08-26).


def _home_openai_compat_model(
    name: str,
    display_name: str,
    model: str,
    *,
    api_key_env: str,
    base_url: str,
    supports_vision: bool = False,
    supports_thinking: bool = True,
    thinking_toggle: bool = False,
    max_tokens: int = 32000,
    temperature: float | None = None,
) -> dict:
    """Build one first-party OpenAI-compatible (`ChatOpenAI` + base_url) entry.

    ``thinking_toggle`` wires the shared ``extra_body.thinking`` enable/disable
    pair for gateways that honor it; otherwise the entry only advertises
    ``supports_thinking`` (mirroring how the OpenRouter copies of these models
    are handled — the reasoning switch is engaged without a provider-specific
    request field DeerFlow cannot verify for every lab).
    """
    entry: dict = {
        "name": name,
        "display_name": display_name,
        "use": "langchain_openai:ChatOpenAI",
        "model": model,
        "api_key": f"${api_key_env}",
        "base_url": base_url,
        "request_timeout": 600.0,
        "max_retries": 2,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        entry["temperature"] = temperature
    entry["supports_vision"] = supports_vision
    if supports_thinking:
        if thinking_toggle:
            entry.update(OPENAI_COMPAT_THINKING_CONFIG)
        else:
            entry["supports_thinking"] = True
    return entry


def _home_deepseek_style_model(
    name: str,
    display_name: str,
    model: str,
    *,
    api_key_env: str,
    api_base: str,
    supports_vision: bool = False,
    max_tokens: int = 32000,
) -> dict:
    """Build one first-party `PatchedChatDeepSeek` entry (DeepSeek / Moonshot).

    These labs' native endpoints honor the OpenAI-compatible ``extra_body``
    thinking toggle, so the entry ships the full enable/disable pair like the
    wizard's existing ``deepseek`` / ``kimi`` providers.
    """
    return {
        "name": name,
        "display_name": display_name,
        "use": "deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        "model": model,
        "api_base": api_base,
        "api_key": f"${api_key_env}",
        "timeout": 600.0,
        "max_retries": 2,
        "max_tokens": max_tokens,
        "supports_vision": supports_vision,
        **OPENAI_COMPAT_THINKING_CONFIG,
    }


def _home_gemini_model(name: str, display_name: str, model: str, *, max_tokens: int = 8192, supports_vision: bool = True) -> dict:
    """Build one first-party Gemini entry via the native `ChatGoogleGenerativeAI` SDK.

    The native SDK path in this repo does not wire a thinking toggle (the
    OpenRouter Gemini copy carries `supports_thinking` because OpenRouter drives
    reasoning), so these home entries advertise vision but not thinking, matching
    the existing ``google`` wizard provider. Users who want Gemini thinking use
    the OpenRouter entry or the `gemini_openai_gateway` provider.
    """
    return {
        "name": name,
        "display_name": display_name,
        "use": "langchain_google_genai:ChatGoogleGenerativeAI",
        "model": model,
        "gemini_api_key": "$GEMINI_API_KEY",
        "timeout": 600.0,
        "max_retries": 2,
        "max_tokens": max_tokens,
        "supports_vision": supports_vision,
    }


# OpenAI: GPT-5.6 Sol (flagship) + GPT-5.3 Codex (the acclaimed agentic-coding
# variant — the same double kept on OpenRouter) + the two cheaper GPT-5.6 tiers.
# GPT-5.6 shipped as Sol / Terra / Luna rather than a `-mini`/`-nano` pair, so
# `gpt-5.6-mini` never existed — Terra is the tier that took `mini`'s place and
# Luna the one below it.
OPENAI_HOME_BUNDLE_MODELS: list[dict] = [
    _home_openai_compat_model("openai-gpt-5.6-sol", "GPT-5.6 Sol (OpenAI)", "gpt-5.6-sol", api_key_env="OPENAI_API_KEY", base_url="https://api.openai.com/v1", supports_vision=True),
    _home_openai_compat_model("openai-gpt-5.3-codex", "GPT-5.3 Codex (OpenAI)", "gpt-5.3-codex", api_key_env="OPENAI_API_KEY", base_url="https://api.openai.com/v1", supports_vision=True),
    _home_openai_compat_model("openai-gpt-5.6-terra", "GPT-5.6 Terra (OpenAI)", "gpt-5.6-terra", api_key_env="OPENAI_API_KEY", base_url="https://api.openai.com/v1", supports_vision=True),
    _home_openai_compat_model("openai-gpt-5.6-luna", "GPT-5.6 Luna (OpenAI)", "gpt-5.6-luna", api_key_env="OPENAI_API_KEY", base_url="https://api.openai.com/v1", supports_vision=True, max_tokens=16000),
]

# xAI: Grok 4.6 (flagship) + Grok 4.3 (the cheaper, 1M-context tier). There is
# no `grok-4.5-fast` in xAI's models table, and grok-4.5 is priced identically to
# 4.6, so 4.3 is the real cheaper pick. Prices are the <200K-prompt base tier.
XAI_HOME_BUNDLE_MODELS: list[dict] = [
    _home_openai_compat_model("xai-grok-4.6", "Grok 4.6 (xAI)", "grok-4.6", api_key_env="XAI_API_KEY", base_url="https://api.x.ai/v1", supports_vision=True),
    _home_openai_compat_model("xai-grok-4.3", "Grok 4.3 (xAI)", "grok-4.3", api_key_env="XAI_API_KEY", base_url="https://api.x.ai/v1", supports_vision=True, max_tokens=16000),
]

# Google: Gemini 3.6 Flash (flagship) + 3.5 Flash-Lite (cheaper) + the newest
# shipped Pro (3.1 Pro preview — the exact set the config's OpenRouter note names).
GOOGLE_HOME_BUNDLE_MODELS: list[dict] = [
    _home_gemini_model("google-gemini-3.6-flash", "Gemini 3.6 Flash (Google)", "gemini-3.6-flash"),
    _home_gemini_model("google-gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite (Google)", "gemini-3.5-flash-lite"),
    _home_gemini_model("google-gemini-3.1-pro", "Gemini 3.1 Pro (Google)", "gemini-3.1-pro-preview"),
]

# DeepSeek: V4 Pro (flagship) + V4 Flash (cheaper) — the pair the wizard already ships.
DEEPSEEK_HOME_BUNDLE_MODELS: list[dict] = [
    _home_deepseek_style_model("deepseek-v4-pro", "DeepSeek V4 Pro (DeepSeek)", "deepseek-v4-pro", api_key_env="DEEPSEEK_API_KEY", api_base="https://api.deepseek.com", supports_vision=False, max_tokens=8192),
    _home_deepseek_style_model("deepseek-v4-flash", "DeepSeek V4 Flash (DeepSeek)", "deepseek-v4-flash", api_key_env="DEEPSEEK_API_KEY", api_base="https://api.deepseek.com", supports_vision=False, max_tokens=8192),
]

# Mistral: Large 3 (flagship) + Medium 3.5 + Small. Mistral Large is not a reasoning
# model (matching the OpenRouter entry), so the family ships without thinking.
# Medium is pinned to an explicit version rather than `mistral-medium-latest`: an
# alias re-points silently, so the name, the slug and the price drift apart with
# nothing raising.
MISTRAL_HOME_BUNDLE_MODELS: list[dict] = [
    _home_openai_compat_model("mistral-large-3", "Mistral Large 3 (Mistral)", "mistral-large-2512", api_key_env="MISTRAL_API_KEY", base_url="https://api.mistral.ai/v1", supports_vision=True, supports_thinking=False),
    _home_openai_compat_model("mistral-medium-3.5", "Mistral Medium 3.5 (Mistral)", "mistral-medium-3-5", api_key_env="MISTRAL_API_KEY", base_url="https://api.mistral.ai/v1", supports_vision=True, supports_thinking=False),
    _home_openai_compat_model(
        "mistral-small-3", "Mistral Small 3 (Mistral)", "mistral-small-latest", api_key_env="MISTRAL_API_KEY", base_url="https://api.mistral.ai/v1", supports_vision=True, supports_thinking=False, max_tokens=16000
    ),
]

# Moonshot/Kimi: K3 (flagship) + K2.6 (cheaper), via the international endpoint.
MOONSHOT_HOME_BUNDLE_MODELS: list[dict] = [
    _home_deepseek_style_model("moonshot-kimi-k3", "Kimi K3 (Moonshot)", "kimi-k3", api_key_env="MOONSHOT_API_KEY", api_base="https://api.moonshot.ai/v1", supports_vision=True, max_tokens=32768),
    _home_deepseek_style_model("moonshot-kimi-k2.6", "Kimi K2.6 (Moonshot)", "kimi-k2.6", api_key_env="MOONSHOT_API_KEY", api_base="https://api.moonshot.ai/v1", supports_vision=False, max_tokens=32768),
]

# Qwen (Alibaba DashScope, international OpenAI-compatible endpoint): 3.8 Max
# (flagship) + 3.7 Plus (cheaper).
QWEN_HOME_BUNDLE_MODELS: list[dict] = [
    _home_openai_compat_model("qwen-3.8-max", "Qwen3.8 Max (Qwen)", "qwen3.8-max", api_key_env="DASHSCOPE_API_KEY", base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1", supports_vision=False),
    _home_openai_compat_model("qwen-3.7-plus", "Qwen3.7 Plus (Qwen)", "qwen3.7-plus", api_key_env="DASHSCOPE_API_KEY", base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1", supports_vision=False, max_tokens=16000),
]

# MiniMax (international endpoint): M3 (flagship, vision) + M2.7 (cheaper, text-only).
MINIMAX_HOME_BUNDLE_MODELS: list[dict] = [
    _home_openai_compat_model("minimax-m3", "MiniMax M3 (MiniMax)", "MiniMax-M3", api_key_env="MINIMAX_API_KEY", base_url="https://api.minimax.io/v1", supports_vision=True, max_tokens=16000, temperature=1.0),
    _home_openai_compat_model("minimax-m2.7", "MiniMax M2.7 (MiniMax)", "MiniMax-M2.7", api_key_env="MINIMAX_API_KEY", base_url="https://api.minimax.io/v1", supports_vision=False, max_tokens=16000, temperature=1.0),
]

# Zhipu / z.ai: GLM-5.3 (flagship) + GLM-4.5 Air (cheaper). z.ai ships Air only
# in the 4.5 generation — there is no `glm-5.2-air` — and $0.2/1.1 is 4.5-Air's rate.
ZAI_HOME_BUNDLE_MODELS: list[dict] = [
    _home_openai_compat_model("zai-glm-5.3", "GLM-5.3 (z-ai)", "glm-5.3", api_key_env="ZAI_API_KEY", base_url="https://api.z.ai/api/paas/v4", supports_vision=False, max_tokens=16000),
    _home_openai_compat_model("zai-glm-4.5-air", "GLM-4.5 Air (z-ai)", "glm-4.5-air", api_key_env="ZAI_API_KEY", base_url="https://api.z.ai/api/paas/v4", supports_vision=False, max_tokens=16000),
]

# ── Machine-readable pricing: the single source of truth ─────────────────────
# A model's price lives here, as data, and is stamped onto the entry as a
# structured `price:` / `discount:` block. It is deliberately NOT in the
# display_name: a name is a label, and embedding the price in it meant the
# figure a user read and the figure they were billed against were two copies of
# one number that could drift apart. It also made a discount impossible to
# expire without a human editing a string, which is exactly how a chat header
# ends up advertising a promotion that ended months ago.
#
# `discount` carries the provider's temporary rate and, when the provider has
# announced one, the date it ends. Past that date the discount stops being
# applied on its own (see deerflow/pricing.py). Omitting `until` means "no end
# date announced" -- inventing one would expire a live discount early.
#
# Keep this table, the `config.example.yaml` marker blocks, and FORK.md in sync;
# `tests/test_config_integrity.py` and `tests/test_setup_wizard.py` pin it.
MODEL_PRICES: dict[str, dict] = {
    "claude-fable-5": {"price": {"currency": "USD", "input": 10.0, "output": 50.0, "cache_hit": 1.0}},
    "claude-opus-5": {"price": {"currency": "USD", "input": 5.0, "output": 25.0, "cache_hit": 0.5}},
    "claude-opus-4-8": {"price": {"currency": "USD", "input": 5.0, "output": 25.0, "cache_hit": 0.5}},
    "claude-sonnet-5": {"price": {"currency": "USD", "input": 2.0, "output": 10.0, "cache_hit": 0.2}},
    "claude-sonnet-4-6": {"price": {"currency": "USD", "input": 3.0, "output": 15.0, "cache_hit": 0.3}},
    "claude-haiku-4-5": {"price": {"currency": "USD", "input": 1.0, "output": 5.0, "cache_hit": 0.1}},
    # DeepSeek bills peak/off-peak since 2026-08-16; these are the peak (upper-bound)
    # rates, matching config.example.yaml. Off-peak is exactly half.
    "deepseek-v4-pro": {"price": {"currency": "USD", "input": 1.32, "output": 3.96}},
    "deepseek-v4-flash": {"price": {"currency": "USD", "input": 0.44, "output": 1.32}},
    "google-gemini-3.6-flash": {"price": {"currency": "USD", "input": 1.5, "output": 7.5}},
    "google-gemini-3.5-flash-lite": {"price": {"currency": "USD", "input": 0.3, "output": 1.2}},
    "google-gemini-3.1-pro": {"price": {"currency": "USD", "input": 2.0, "output": 12.0}},
    "minimax-m3": {"price": {"currency": "USD", "input": 0.6, "output": 2.4}},
    "minimax-m2.7": {"price": {"currency": "USD", "input": 0.3, "output": 1.2}},
    "mistral-large-3": {"price": {"currency": "USD", "input": 0.5, "output": 1.5}},
    "mistral-medium-3.5": {"price": {"currency": "USD", "input": 1.5, "output": 7.5}},
    "mistral-small-3": {"price": {"currency": "USD", "input": 0.1, "output": 0.3}},
    "moonshot-kimi-k3": {"price": {"currency": "USD", "input": 3.0, "output": 15.0}},
    "moonshot-kimi-k2.6": {"price": {"currency": "USD", "input": 0.95, "output": 4.0}},
    "openai-gpt-5.6-sol": {"price": {"currency": "USD", "input": 5.0, "output": 30.0}},
    "openai-gpt-5.3-codex": {"price": {"currency": "USD", "input": 1.75, "output": 14.0}},
    "openai-gpt-5.6-terra": {"price": {"currency": "USD", "input": 2.0, "output": 12.0}},
    "openai-gpt-5.6-luna": {"price": {"currency": "USD", "input": 0.2, "output": 1.2}},
    "openrouter-fable-5": {"price": {"currency": "USD", "input": 10.0, "output": 50.0}},
    "openrouter-grok-4.6": {"price": {"currency": "USD", "input": 2.0, "output": 6.0}},
    "openrouter-gpt-5.6-sol": {"price": {"currency": "USD", "input": 5.0, "output": 30.0}},
    "openrouter-gpt-5.3-codex": {"price": {"currency": "USD", "input": 1.75, "output": 14.0}},
    "openrouter-gemini-3.6-flash": {"price": {"currency": "USD", "input": 1.5, "output": 7.5}},
    "openrouter-llama-4-maverick": {"price": {"currency": "USD", "input": 0.2, "output": 0.8}},
    "openrouter-minimax-m3": {"price": {"currency": "USD", "input": 0.6, "output": 2.4}, "discount": {"input": 0.24, "output": 0.96}},
    "openrouter-qwen3.8-max": {"price": {"currency": "USD", "input": 2.0, "output": 6.0}},
    "openrouter-kimi-k3": {"price": {"currency": "USD", "input": 3.0, "output": 15.0}},
    "openrouter-mistral-large-3": {"price": {"currency": "USD", "input": 0.5, "output": 1.5}},
    "openrouter-deepseek-v4-pro": {"price": {"currency": "USD", "input": 0.44, "output": 0.87}},
    "openrouter-glm-5.3": {"price": {"currency": "USD", "input": 1.4, "output": 4.4}},
    "openrouter-nemotron-3-ultra": {"price": {"currency": "USD", "input": 0.5, "output": 2.2}},
    "qwen-3.8-max": {"price": {"currency": "USD", "input": 2.0, "output": 6.0}},
    "qwen-3.7-plus": {"price": {"currency": "USD", "input": 0.4, "output": 1.2}},
    "xai-grok-4.6": {"price": {"currency": "USD", "input": 2.0, "output": 6.0}},
    "xai-grok-4.3": {"price": {"currency": "USD", "input": 1.25, "output": 2.5}},
    "zai-glm-5.3": {"price": {"currency": "USD", "input": 1.4, "output": 4.4}},
    "zai-glm-4.5-air": {"price": {"currency": "USD", "input": 0.2, "output": 1.1}},
}


def _apply_prices(models: list[dict]) -> list[dict]:
    """Stamp the structured `price:` / `discount:` block onto every known entry."""
    for entry in models:
        record = MODEL_PRICES.get(entry.get("name", ""))
        if record is None:
            continue
        entry.setdefault("price", dict(record["price"]))
        if "discount" in record:
            entry.setdefault("discount", dict(record["discount"]))
    return models


for _bundle in (
    ANTHROPIC_BUNDLE_MODELS,
    OPENROUTER_BUNDLE_MODELS,
    OPENAI_HOME_BUNDLE_MODELS,
    XAI_HOME_BUNDLE_MODELS,
    GOOGLE_HOME_BUNDLE_MODELS,
    DEEPSEEK_HOME_BUNDLE_MODELS,
    MISTRAL_HOME_BUNDLE_MODELS,
    MOONSHOT_HOME_BUNDLE_MODELS,
    QWEN_HOME_BUNDLE_MODELS,
    MINIMAX_HOME_BUNDLE_MODELS,
    ZAI_HOME_BUNDLE_MODELS,
):
    _apply_prices(_bundle)
del _bundle


# Registry consumed by the config-block generator, the auto-config regression
# tests, and the config.example.yaml ↔ wizard parity check: provider marker slug
# -> (gating env var, bundle). Keep this in sync with the PROVIDERS list in
# scripts/sync-api-key-models.py and the marker blocks in config.example.yaml.
HOME_API_BUNDLES: dict[str, tuple[str, list[dict]]] = {
    "openai": ("OPENAI_API_KEY", OPENAI_HOME_BUNDLE_MODELS),
    "xai": ("XAI_API_KEY", XAI_HOME_BUNDLE_MODELS),
    "google": ("GEMINI_API_KEY", GOOGLE_HOME_BUNDLE_MODELS),
    "deepseek": ("DEEPSEEK_API_KEY", DEEPSEEK_HOME_BUNDLE_MODELS),
    "mistral": ("MISTRAL_API_KEY", MISTRAL_HOME_BUNDLE_MODELS),
    "moonshot": ("MOONSHOT_API_KEY", MOONSHOT_HOME_BUNDLE_MODELS),
    "qwen": ("DASHSCOPE_API_KEY", QWEN_HOME_BUNDLE_MODELS),
    "minimax": ("MINIMAX_API_KEY", MINIMAX_HOME_BUNDLE_MODELS),
    "zai": ("ZAI_API_KEY", ZAI_HOME_BUNDLE_MODELS),
}


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
        name="zai",
        display_name="Z.AI GLM-5.3-Flash",
        description="GLM-5.3-Flash with required thinking and native vision",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        models=["glm-5.3-flash"],
        default_model="glm-5.3-flash",
        env_var="ZAI_API_KEY",
        package="langchain-deepseek",
        extra_config={
            "api_base": "https://api.z.ai/api/paas/v4",
            "timeout": 600.0,
            "max_retries": 2,
            "temperature": 1.0,
            "top_p": 0.95,
            "max_tokens": 131072,
            "context_window": 1000000,
            "supports_thinking": True,
            # GLM-5.3-Flash only accepts low/high/max, while DeerFlow's current
            # generic UI can emit minimal/medium. Keep provider effort control
            # disabled until model-specific reasoning capabilities are exposed.
            "supports_reasoning_effort": False,
            "supports_vision": True,
            # The model cannot disable thinking. This unconditional base payload
            # deliberately avoids when_thinking_enabled/disabled so background
            # callers that request thinking_enabled=False cannot synthesize an
            # invalid disabled/minimal combination in the model factory.
            "extra_body": {
                "thinking": {
                    "type": "enabled",
                    # Avoid preserved-thinking history requirements until the
                    # reasoning-history abstraction handles summarization.
                    "clear_thinking": True,
                },
                "tool_stream": True,
            },
            # Z.AI streams terminal usage without requiring OpenAI's undocumented
            # stream_options.include_usage request field.
            "stream_usage": False,
        },
    ),
    LLMProvider(
        name="openai",
        display_name="OpenAI",
        description="GPT-5.6 Sol + GPT-5.3 Codex + GPT-5.6 Terra + Luna (direct OpenAI API)",
        use="langchain_openai:ChatOpenAI",
        models=[entry["model"] for entry in OPENAI_HOME_BUNDLE_MODELS],
        default_model=OPENAI_HOME_BUNDLE_MODELS[0]["model"],
        env_var="OPENAI_API_KEY",
        package="langchain-openai",
        extra_config={
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 32000,
            "supports_vision": True,
        },
        bundle_models=OPENAI_HOME_BUNDLE_MODELS,
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
        description="Latest Claude Fable 5, Opus 5, Opus 4.8, Sonnet 5, Sonnet 4.6 and Haiku 4.5",
        use="langchain_anthropic:ChatAnthropic",
        models=["claude-fable-5", "claude-opus-5", "claude-opus-4-8", "claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-4-5"],
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
        description="DeepSeek V4 Pro + V4 Flash with thinking support (direct DeepSeek API)",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        models=[entry["model"] for entry in DEEPSEEK_HOME_BUNDLE_MODELS],
        default_model=DEEPSEEK_HOME_BUNDLE_MODELS[0]["model"],
        env_var="DEEPSEEK_API_KEY",
        package="langchain-deepseek",
        extra_config={
            "api_base": "https://api.deepseek.com",
            "timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 8192,
            "supports_vision": False,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
        bundle_models=DEEPSEEK_HOME_BUNDLE_MODELS,
    ),
    LLMProvider(
        name="google",
        display_name="Google Gemini",
        description="Gemini 3.6 Flash + 3.5 Flash-Lite + 3.1 Pro (native Gemini SDK, no thinking)",
        use="langchain_google_genai:ChatGoogleGenerativeAI",
        models=[entry["model"] for entry in GOOGLE_HOME_BUNDLE_MODELS],
        default_model=GOOGLE_HOME_BUNDLE_MODELS[0]["model"],
        env_var="GEMINI_API_KEY",
        package="langchain-google-genai",
        api_key_field="gemini_api_key",
        extra_config={
            "timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 8192,
            "supports_vision": True,
        },
        bundle_models=GOOGLE_HOME_BUNDLE_MODELS,
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
        description="Kimi K3 + K2.6 with thinking support (direct Moonshot API)",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        models=[entry["model"] for entry in MOONSHOT_HOME_BUNDLE_MODELS],
        default_model=MOONSHOT_HOME_BUNDLE_MODELS[0]["model"],
        env_var="MOONSHOT_API_KEY",
        package="langchain-deepseek",
        extra_config={
            "api_base": "https://api.moonshot.ai/v1",
            "timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 32768,
            "supports_vision": True,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
        bundle_models=MOONSHOT_HOME_BUNDLE_MODELS,
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
        description="MiniMax M3 + M2.7 (international OpenAI-compatible endpoint)",
        use="langchain_openai:ChatOpenAI",
        models=[entry["model"] for entry in MINIMAX_HOME_BUNDLE_MODELS],
        default_model=MINIMAX_HOME_BUNDLE_MODELS[0]["model"],
        env_var="MINIMAX_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://api.minimax.io/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 16000,
            "temperature": 1.0,
            "supports_vision": True,
            "supports_thinking": True,
        },
        model_vision_overrides={
            "MiniMax-M2.7": False,
            "MiniMax-M2.7-highspeed": False,
        },
        bundle_models=MINIMAX_HOME_BUNDLE_MODELS,
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
        description="One key: Claude Fable 5 + xAI/OpenAI/Google flagships & open alternatives",
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
        name="xai",
        display_name="xAI Grok",
        description="Grok 4.6 + Grok 4.3 (direct xAI API)",
        use="langchain_openai:ChatOpenAI",
        models=[entry["model"] for entry in XAI_HOME_BUNDLE_MODELS],
        default_model=XAI_HOME_BUNDLE_MODELS[0]["model"],
        env_var="XAI_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://api.x.ai/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 32000,
            "supports_vision": True,
            "supports_thinking": True,
        },
        bundle_models=XAI_HOME_BUNDLE_MODELS,
    ),
    LLMProvider(
        name="mistral",
        display_name="Mistral",
        description="Mistral Large 3 + Medium 3.5 + Small 3 (direct Mistral API)",
        use="langchain_openai:ChatOpenAI",
        models=[entry["model"] for entry in MISTRAL_HOME_BUNDLE_MODELS],
        default_model=MISTRAL_HOME_BUNDLE_MODELS[0]["model"],
        env_var="MISTRAL_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://api.mistral.ai/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 32000,
            "supports_vision": True,
            "supports_thinking": False,
        },
        bundle_models=MISTRAL_HOME_BUNDLE_MODELS,
    ),
    LLMProvider(
        name="qwen",
        display_name="Qwen (Alibaba DashScope)",
        description="Qwen3.8 Max + 3.7 Plus (international DashScope OpenAI-compatible endpoint)",
        use="langchain_openai:ChatOpenAI",
        models=[entry["model"] for entry in QWEN_HOME_BUNDLE_MODELS],
        default_model=QWEN_HOME_BUNDLE_MODELS[0]["model"],
        env_var="DASHSCOPE_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 32000,
            "supports_vision": False,
            "supports_thinking": True,
        },
        bundle_models=QWEN_HOME_BUNDLE_MODELS,
    ),
    LLMProvider(
        name="zai",
        display_name="Zhipu z.ai (GLM)",
        description="GLM-5.3 + GLM-4.5 Air (direct z.ai API)",
        use="langchain_openai:ChatOpenAI",
        models=[entry["model"] for entry in ZAI_HOME_BUNDLE_MODELS],
        default_model=ZAI_HOME_BUNDLE_MODELS[0]["model"],
        env_var="ZAI_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://api.z.ai/api/paas/v4",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 16000,
            "supports_vision": False,
            "supports_thinking": True,
        },
        bundle_models=ZAI_HOME_BUNDLE_MODELS,
    ),
    LLMProvider(
        name="orcarouter",
        display_name="OrcaRouter",
        description="OpenAI-compatible adaptive routing gateway",
        use="langchain_openai:ChatOpenAI",
        models=["openai/gpt-5.5", "anthropic/claude-opus-4.8", "google/gemini-3.5-flash", "orcarouter/auto"],
        default_model="openai/gpt-5.5",
        env_var="ORCAROUTER_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://api.orcarouter.ai/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 8192,
            "temperature": 0.7,
        },
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
        name="serply",
        display_name="Serply",
        description="Google Search, News and Scholar results, API key required",
        use="deerflow.community.serply.tools:web_search_tool",
        env_var="SERPLY_API_KEY",
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
