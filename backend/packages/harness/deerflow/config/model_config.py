from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelConfig(BaseModel):
    """Config section for a model"""

    name: str = Field(..., description="Unique name for the model")
    display_name: str | None = Field(..., default_factory=lambda: None, description="Display name for the model")
    description: str | None = Field(..., default_factory=lambda: None, description="Description for the model")
    use: str = Field(
        ...,
        description="Class path of the model provider(e.g. langchain_openai.ChatOpenAI)",
    )
    model: str = Field(..., description="Model name")
    model_config = ConfigDict(extra="allow")
    use_responses_api: bool | None = Field(
        default=None,
        description="Whether to route OpenAI ChatOpenAI calls through the /v1/responses API",
    )
    output_version: str | None = Field(
        default=None,
        description="Structured output version for OpenAI responses content, e.g. responses/v1",
    )
    supports_thinking: bool = Field(default_factory=lambda: False, description="Whether the model supports thinking")
    supports_reasoning_effort: bool = Field(default_factory=lambda: False, description="Whether the model supports reasoning effort")
    when_thinking_enabled: dict | None = Field(
        default_factory=lambda: None,
        description="Extra settings to be passed to the model when thinking is enabled",
    )
    when_thinking_disabled: dict | None = Field(
        default_factory=lambda: None,
        description="Extra settings to be passed to the model when thinking is disabled",
    )
    supports_vision: bool = Field(default_factory=lambda: False, description="Whether the model supports vision/image inputs")
    context_window: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Positive total context window size in tokens (prompt + completion). Used to compute the real-time "
            "context usage percentage displayed in the chat UI, and attached to the model's langchain profile "
            "(`max_input_tokens`) so fraction-based summarization triggers can resolve their thresholds for "
            "third-party OpenAI-compatible models that carry no built-in profile. Distinct from `max_tokens`, "
            "which is the per-call output cap passed to the provider. Leave unset if unknown; the UI will hide "
            "the percentage and fraction summarization clauses will degrade with a warning."
        ),
    )
    size_bytes: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Fork feature. On-disk size of the model's weights in bytes, written by "
            "`scripts/sync-ollama-models.py` from Ollama's `/api/tags`. Presentation-only "
            "metadata: the model picker renders it beside the context window so a local "
            "model's GPU footprint is visible before it is selected. Never reaches the "
            "provider client. Meaningless for hosted models, which is why it is unset there."
        ),
    )
    fallback: list[str] | None = Field(
        default=None,
        description=(
            "Fork feature. Ordered model names to try when a call to this model fails with a "
            "recoverable provider error (connection failure, context-length rejection, unsupported "
            "tool calls, or a 5xx). Intentional stops — user interrupt, spend cap, guardrail refusal, "
            "auth failure — never fall back. Fallback models are built without their own chains, so "
            "the chain is flat and cycles cannot be expressed; it is also capped in length. Overrides "
            "the global `model_fallback.chain`."
        ),
    )
    price: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Fork feature. What this model costs, per one million tokens: `currency` (default USD), "
            "`input`, `output`, and the optional `cache_hit` for prompt-cache reads. The explicit, "
            "operator-facing replacement for the older `pricing:` block and for parsing a `($in/out)` "
            "pair out of `display_name`; both still work, and this wins over both. Presentation and "
            "budgeting only — it never reaches the provider client."
        ),
    )
    discount: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Fork feature. A temporary rate for this model, in the same shape as `price` (`input`, "
            "`output`, optional `cache_hit`) plus an optional `until` date/datetime. It is strictly "
            "additive: spend is still billed at `price`, and the discount is shown beside it, because "
            "a promotion can end at any time and an under-estimate is worse than a high one. Past its "
            "`until` the discount stops being applied automatically — as it does when `until` cannot be "
            "read, or when the current time is unavailable, both of which resolve to 'expired' rather "
            "than 'forever'."
        ),
    )
    stream_chunk_timeout: float | None = Field(
        default=None,
        description=(
            "Maximum seconds to wait between successive streaming chunks before "
            "langchain-openai raises StreamChunkTimeoutError. None means use the "
            "factory default (240s for OpenAI-compatible clients). Tune higher for "
            "reasoning models with long thinking pauses; lower for latency-sensitive "
            "interactive endpoints. Has no effect on non-OpenAI-compatible providers."
        ),
    )
    thinking: dict | None = Field(
        default_factory=lambda: None,
        description=(
            "Thinking settings for the model. If provided, these settings will be passed to the model when thinking is enabled. "
            "This is a shortcut for `when_thinking_enabled` and will be merged with `when_thinking_enabled` if both are provided."
        ),
    )
