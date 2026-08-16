### Model Factory (`packages/harness/deerflow/models/factory.py`)

- `create_chat_model(name, thinking_enabled)` instantiates LLM from config via reflection
- Supports `thinking_enabled` flag with per-model `when_thinking_enabled` overrides
- Supports vLLM-style thinking toggles via `when_thinking_enabled.extra_body.chat_template_kwargs.enable_thinking` for Qwen reasoning models, while normalizing legacy `thinking` configs for backward compatibility
- Supports `supports_vision` flag for image understanding models
- Config values starting with `$` resolved as environment variables
- Missing provider modules surface actionable install hints from reflection resolvers (for example `uv add langchain-google-genai`)

### vLLM Provider (`packages/harness/deerflow/models/vllm_provider.py`)

- `VllmChatModel` subclasses `langchain_openai:ChatOpenAI` for vLLM 0.19.0 OpenAI-compatible endpoints
- Preserves vLLM's non-standard assistant `reasoning` field on full responses, streaming deltas, and follow-up tool-call turns
- Designed for configs that enable thinking through `extra_body.chat_template_kwargs.enable_thinking` on vLLM 0.19.0 Qwen reasoning models, while accepting the older `thinking` alias
- `cumulative_stream_usage` is an opt-in model setting (default `false`) for endpoints that repeat cumulative token totals on each streaming chunk. The provider converts snapshots to deltas only when a stable completion id is present, isolates interleaved streams by id, and leaves the original usage untouched otherwise. Per-model tracking is lock-protected and cleared on the trailing empty-`choices` frame whether or not that frame carries usage. A soft cap of 1024 ids evicts only entries idle for at least one hour; active streams may temporarily exceed the cap so eviction cannot corrupt their deltas. Regression coverage lives in `tests/test_vllm_provider.py`.

### Model pricing and fallback (fork features)

Full rationale lives in [FORK.md](../../../../../FORK.md) (§7, §14, §17); the code-adjacent invariants:

- **`price:` / `discount:` (§17)** — the model's cost surface, and the **single source of truth**: `price: {currency, input, output, cache_hit}` and `discount: {input, output, cache_hit, until}`, per one million tokens. Bundled models no longer carry a price in `display_name`; `wizard/providers.py::MODEL_PRICES` mirrors the same figures for the setup wizard and a test asserts the two agree. `pricing.py::_raw_from_price_fields` normalizes them into the internal shape the legacy `pricing:` block uses, so precedence is `price:` > `pricing:` > `derive_pricing_from_display_name` with **one** cost path rather than three. The discount is strictly additive — spend bills at `price`, the discount is shown beside it.
- **Expiry is applied once, in `build_pricing_map`.** A lapsed discount is dropped before a `ModelPricing` is constructed, so the chat header, the spend page, `SpendBudgetMiddleware` and `GET /api/models` are all correct without repeating the check. Do not add a downstream expiry test; that is how two checks drift apart.
- **Both unknowns mean expired, never eternal.** `parse_discount_expiry` returns `(None, False)` for an unreadable `until`, and `build_pricing_map(..., now=None)` means "the current time is unknown" (distinct from the argument being omitted, which resolves the wall clock). Either drops the discount. Over-stating cost is corrected by the provider's bill; advertising a promotion that has ended is silent. A discount with no `until` is unaffected by an unknown clock. A bare `until: 2026-08-31` is **inclusive**, and a naive timestamp is read as UTC.
- **`price`, `discount`, `pricing` and `fallback` must stay in `create_chat_model`'s exclude set.** `ModelConfig` is `extra="allow"`, so an unexcluded key reaches the provider constructor and from there the completion request payload — a cost annotation would become a malformed API call.
- **`derive_pricing_from_display_name` is a legacy path and must stay.** `config_upgrade.py` cannot add a key inside an existing list entry, so every `config.yaml` written before prices moved into `price:` still carries the old `($in/out)` names and is priced by that parser and nothing else. Deleting it would silently un-price every pre-existing install.
- Tests: `tests/test_model_price_fields.py`, `tests/test_pricing.py`, `tests/test_config_integrity.py`, `tests/test_model_fallback.py`.
