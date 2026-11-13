# Models: fork notes

Fork-only invariants for `deerflow/models/`, split out of
[`AGENTS.md`](AGENTS.md) to keep that guide within its budget
(`scripts/check_agent_guidance.py`). Read the section that matches your change
before you edit pricing, fallback or a subscription provider.

## Model pricing and fallback

Full rationale lives in [FORK.md](../../../../../FORK.md) (§7, §14, §17); the code-adjacent invariants:

- **`price:` / `discount:` (§17)** — the model's cost surface, and the **single source of truth**: `price: {currency, input, output, cache_hit}` and `discount: {input, output, cache_hit, until}`, per one million tokens. Bundled models no longer carry a price in `display_name`; `wizard/providers.py::MODEL_PRICES` mirrors the same figures for the setup wizard and a test asserts the two agree. `pricing.py::_raw_from_price_fields` normalizes them into the internal shape the legacy `pricing:` block uses, so precedence is `price:` > `pricing:` > `derive_pricing_from_display_name` with **one** cost path rather than three. The discount is strictly additive — spend bills at `price`, the discount is shown beside it.
- **Expiry is applied once, in `build_pricing_map`.** A lapsed discount is dropped before a `ModelPricing` is constructed, so the chat header, the spend page, `SpendBudgetMiddleware` and `GET /api/models` are all correct without repeating the check. Do not add a downstream expiry test; that is how two checks drift apart.
- **Both unknowns mean expired, never eternal.** `parse_discount_expiry` returns `(None, False)` for an unreadable `until`, and `build_pricing_map(..., now=None)` means "the current time is unknown" (distinct from the argument being omitted, which resolves the wall clock). Either drops the discount. Over-stating cost is corrected by the provider's bill; advertising a promotion that has ended is silent. A discount with no `until` is unaffected by an unknown clock. A bare `until: 2026-08-31` is **inclusive**, and a naive timestamp is read as UTC.
- **`price`, `discount`, `pricing`, `fallback`, `context_window` and `size_bytes` must stay in `create_chat_model`'s exclude set.** `ModelConfig` is `extra="allow"`, so an unexcluded key reaches the provider constructor and from there the completion request payload — a cost annotation would become a malformed API call. `size_bytes` (a local model's weights on disk, written into every synced Ollama entry by `scripts/sync-ollama-models.py`) is the one whose breakage misreads: it rides on *only* local entries, so un-excluding it takes out Ollama and nothing else, which looks like a daemon problem rather than a config one.
- **`context_window` and `size_bytes` are returned by `/api/models`** (both routes — the list and the single-model one build `ModelResponse` by hand). The picker shows them together because they are one question: how much of the GPU the weights already hold decides how much room the window has left. Null means "nothing to show", which is why neither is defaulted to `0`.
- **`derive_pricing_from_display_name` is a legacy path and must stay.** `config_upgrade.py` cannot add a key inside an existing list entry, so every `config.yaml` written before prices moved into `price:` still carries the old `($in/out)` names and is priced by that parser and nothing else. Deleting it would silently un-price every pre-existing install.
- **A reported model id is normalized before it prices anything (`deerflow/model_ids.py`).** `response_metadata["model_name"]` is *assembled* for a streamed response, and LangChain's `merge_dicts` concatenates equal strings under the same key — so a provider that repeats `model` across two `finish_reason` chunks yields `deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro` (and `stopstop`). That id matches nothing, and an unmatched id costs **zero**, so the symptom is a silent one: no cost in the header, no cap enforcement, a spend row for a model that does not exist. `normalize_reported_model_name` collapses only a whole id repeated end to end — never a mismatched or partial pair, since billing one model at another's rate is worse than reporting nothing. Apply it where a reported id is *read* (`RunJournal._record_model_usage` is the single write path for the cost buckets); `_pricing_lookup_candidates` and the by-model aggregations also normalize on read so rows persisted before the fix still price without a migration.
- Tests: `tests/test_model_price_fields.py`, `tests/test_pricing.py`, `tests/test_config_integrity.py`, `tests/test_model_fallback.py`, `tests/test_model_ids.py`.

## Subscription connections

`subscriptions.py` owns operator-shared encrypted grants and discovered catalog
snapshots. Configuration merging is network-free, preserves YAML/managed names,
and never mutates an active AppConfig. Resolve credentials per inference under
the shared thread/process lock; rotating refresh tokens are one transaction.
Catalog snapshot reads must not wait on the credential transaction's network I/O.
No token belongs in a ModelConfig, LangChain serialized model, status response,
validation error, or log. Route mutations use drained workers.

`subscription_providers.py` keeps the public ChatGPT SIWC transport separate from
legacy Codex CLI auth. Preserve namespace/tool-result correlation, encrypted
reasoning replay, stream terminal checks and subscription-specific usage names.
Grok always streams with its routing/auth headers. Responses-only Grok models
(`GrokResponsesSubscriptionChatModel`, `api.x.ai`) are listed only after the reach
probe shows the grant gets there; they replay encrypted reasoning with
`store: false` and must keep renaming usage to the subscription identity. The
probe, feature switches and Grok tools: [xai guide](../community/xai/AGENTS.md).
Kimi preserves reasoning on
tool followups and rejects inherited non-interactive policy before auth/network.
Subscription-selected models bypass API fallback chains and per-token pricing.
Remote ChatGPT OAuth starts server-owned PKCE and accepts a manual loopback URL
handoff. Bind the encrypted pending attempt to its owner, expiry and generation;
verify the exact saved URI and state before consuming it. Never fetch pasted URLs
or expose PKCE verifiers/tokens in browser responses. Save issued registrations
before exchange and renewable grants before discovery. Keep only non-secret
registration metadata on disconnect. The packaged `chatgpt_subscription_login.py`
and JSON import remain a fallback; imports verify both signed grants and retain
the runtime's own host ID. Full operator flow: FORK.md §41. Focused coverage:
`tests/test_{subscriptions,subscription_providers,chatgpt_subscription_auth}.py`.
