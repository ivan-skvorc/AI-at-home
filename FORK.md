# Fork Notes — `deer-flow-2-local`

> **Vibe-coded disclaimer.** This fork was put together with heavy LLM assistance and only light human review. The two added features have been smoke-tested but not stress-tested. Treat this as a personal-use scratchpad, not production-grade work. Upstream is the source of truth for everything else: <https://github.com/bytedance/deer-flow>.

## What this fork adds

Convenience features on top of upstream, designed around running DeerFlow locally with mixed cloud + local models (more are covered in the sections further down):

### 1. Auto-synced Ollama models in `config.yaml`

`scripts/sync-ollama-models.py` queries the local Ollama daemon (or remote, via `OLLAMA_HOST`) and reconciles `config.yaml`'s `models:` section with whatever you have installed via `ollama pull`. Capabilities (`thinking`, `vision`, `tools`) are detected via `/api/show` and translated into DeerFlow's `supports_*` flags.

**Context window (`num_ctx`).** Ollama defaults `num_ctx` to just **2048 tokens** regardless of what a model actually supports — small enough to silently truncate the agent's context (system prompt + tools + skills + memory + conversation), and smaller than the 8192-token `num_predict` output budget the entries request. The sync therefore reads each model's **native context length** from `/api/show` (`model_info.<arch>.context_length`) and writes an explicit `num_ctx`, clamped to **32768** so a 128K-native model doesn't allocate an OOM-sized KV cache on a typical local GPU. Override the clamp with `--num-ctx-cap N` (or `--num-ctx-cap 0` for each model's full native length). `num_predict` is kept at or below half the window so there's always room for the prompt.

**VRAM-aware sizing.** Tell DeerFlow how much GPU memory you have and the flat 32768 clamp is replaced by a **per-model estimate**: the largest window whose KV cache fits next to that model's weights in your budget. The math uses each model's attention geometry from `/api/show` (layers × KV heads × head dims, so GQA models are costed correctly) and its weights size from `/api/tags`, minus a conservative overhead reserve; the result is floored to 2048-token steps and never below 4096. A 3B model on a 24 GB card gets its full native window; a 32B model on the same card gets what actually fits. Configure it via `make setup` (which auto-detects VRAM via `nvidia-smi` / `rocm-smi` / Apple unified memory) or by hand in `config.yaml`:

```yaml
ollama:
  vram_gb: 16            # GPU memory budget in GiB
  kv_cache_type: q8_0    # optional; must match the daemon's OLLAMA_KV_CACHE_TYPE
```

`kv_cache_type: q8_0` sizes for a quantized KV cache — near-lossless, roughly half the per-token memory, so roughly **double the affordable window**. It only *assumes* the setting: KV-cache quantization is a server-side Ollama env var that DeerFlow can't set per request, so enable it on the daemon (`sudo systemctl edit ollama` → `Environment="OLLAMA_KV_CACHE_TYPE=q8_0"`; older Ollama also needs `OLLAMA_FLASH_ATTENTION=1`). Models without flash-attention support silently fall back to f16 on the server — worst case the estimate is optimistic and Ollama offloads a few layers to CPU (slower, not fatal). An explicit `--num-ctx-cap` still applies as a hard ceiling, and models whose geometry can't be read keep the flat-cap behavior. `--vram-gb` / `--kv-cache-type` override the config per run.

The script is **idempotent and bounded** — it only owns content between its `BEGIN ollama-sync` / `END ollama-sync` markers. Anything you've hand-edited outside that block (cloud models, custom Ollama overrides) is never touched.

It is hooked into **every launch path**, so however you start DeerFlow your Ollama list is refreshed automatically. If the daemon is unreachable, the script no-ops with no changes:

| Path | Where it runs | `base_url` written into entries |
| --- | --- | --- |
| `make dev` / `make start` (+ daemons) | `scripts/serve.sh` | `http://localhost:11434` (local runtime) |
| `make docker-start` (Docker dev) | `scripts/docker.sh`, on the host before `compose up` | `http://host.docker.internal:11434` |
| `make up` (Docker prod) | `scripts/deploy.sh`, on the host before `compose up` | `http://host.docker.internal:11434` |

**Why the base_url differs on the Docker paths.** The sync always *queries* the host's Ollama over loopback, but inside a container `localhost` is the container itself, not the host where Ollama listens. So for the Docker paths the sync writes `http://host.docker.internal:11434` (the `--container` flag; `host.docker.internal` is mapped to the host gateway via `extra_hosts` in the compose files, and is already in the gateway's `NO_PROXY`). `config.yaml` is edited on the host **before** the containers mount it, so this works even though the gateway mounts `config.yaml` read-only. A genuinely remote `OLLAMA_HOST` (a non-loopback host) is recorded verbatim on every path, since it is reachable from both host and container.

> **Host-run Ollama + Docker:** for `host.docker.internal` to reach it, Ollama must listen on all interfaces (`OLLAMA_HOST=0.0.0.0 ollama serve`), not just `127.0.0.1` (its default). Otherwise the container can resolve the host but the connection is refused. The Docker launch paths now detect this: when the sync writes `host.docker.internal` entries but the host's Ollama doesn't answer on the Docker bridge gateway, it prints the exact fix (advisory only; Docker Desktop, which proxies host loopback, is exempt). The AIO sandbox containers additionally map the alias themselves and default `OLLAMA_HOST=http://host.docker.internal:11434` into the container env, so agent-run Ollama clients inside the sandbox target the host daemon out of the box — `make dev`'s sandbox preflight prints the same advisory when the host daemon is loopback-bound.

```bash
# Manual run (local runtime — base_url localhost)
python3 scripts/sync-ollama-models.py --verbose

# Manual run for a containerized runtime (base_url host.docker.internal)
python3 scripts/sync-ollama-models.py --container --verbose

# Dry-run (prints proposed config to stdout, doesn't write)
python3 scripts/sync-ollama-models.py --dry-run

# Remote Ollama (queried and written verbatim on every path)
OLLAMA_HOST=http://server.lan:11434 python3 scripts/sync-ollama-models.py

# Explicit base_url override (wins over --container)
python3 scripts/sync-ollama-models.py --base-url http://ollama:11434

# Use each model's full native context window (no 32768 clamp)
python3 scripts/sync-ollama-models.py --num-ctx-cap 0
```

### 2. API-key model auto-config in `config.yaml`

A companion to the Ollama sync for **cloud** models. `scripts/sync-api-key-models.py` runs on every launch, reads the provider API keys in your `.env` (falling back to the process environment), and **uncomments** the matching ready-to-use model block in `config.yaml` — so the right models are enabled on first start with no manual editing.

| `.env` key present | Models enabled | Provider / `use` |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Claude **Fable 5**, **Opus 5**, **Opus 4.8**, **Sonnet 5**, **Sonnet 4.6**, **Haiku 4.5** | direct Anthropic API (`langchain_anthropic:ChatAnthropic`) |
| `OPENROUTER_API_KEY` | Claude **Fable 5**, **Grok 4.5**, **GPT-5.6 Sol**, **GPT-5.3 Codex**, **Gemini 3.6 Flash**, **Llama 4 Maverick**, **MiniMax M3**, **Qwen3.7 Max**, **Kimi K3**, **Mistral Large 3**, **DeepSeek V4 Pro**, **GLM-5.2**, **Nemotron 3 Ultra** | OpenRouter (`langchain_openai:ChatOpenAI` + `base_url`) |
| `OPENAI_API_KEY` | **GPT-5.6 Sol**, **GPT-5.3 Codex**, **GPT-5.6 Mini** | direct OpenAI API (`langchain_openai:ChatOpenAI`) |
| `XAI_API_KEY` | **Grok 4.5**, **Grok 4.5 Fast** | direct xAI API (`langchain_openai:ChatOpenAI` + `base_url`) |
| `GEMINI_API_KEY` | **Gemini 3.6 Flash**, **3.5 Flash-Lite**, **3.1 Pro** | native Gemini SDK (`langchain_google_genai:ChatGoogleGenerativeAI`) |
| `DEEPSEEK_API_KEY` | **DeepSeek V4 Pro**, **V4 Flash** | direct DeepSeek API (`deerflow.models.patched_deepseek:PatchedChatDeepSeek`) |
| `MISTRAL_API_KEY` | **Mistral Large 3**, **Medium**, **Small** | direct Mistral API (`langchain_openai:ChatOpenAI` + `base_url`) |
| `MOONSHOT_API_KEY` | **Kimi K3**, **Kimi K2.6** | direct Moonshot API (`deerflow.models.patched_deepseek:PatchedChatDeepSeek`) |
| `DASHSCOPE_API_KEY` | **Qwen3.7 Max**, **Qwen3.7 Plus** | Alibaba DashScope (`langchain_openai:ChatOpenAI` + `base_url`) |
| `MINIMAX_API_KEY` | **MiniMax M3**, **MiniMax M2.7** | direct MiniMax API (`langchain_openai:ChatOpenAI` + `base_url`) |
| `ZAI_API_KEY` | **GLM-5.2**, **GLM-5.2 Air** | direct z.ai API (`langchain_openai:ChatOpenAI` + `base_url`) |

The first two rows are the aggregators; the rest are **first-party "home" API blocks**, one per big-name lab that ships its own API. This mirrors how Anthropic is handled — a lab's full lineup lives on the lab's own key, and the flagship is *doubled*: it's reachable through both its home API AND OpenRouter (the direct copy carries no `(p)` privacy caveat). So with a lab's own key set, its cheaper siblings light up on the home API only, while its flagship exists on both. OpenRouter keeps its trim "one flagship per lab" set unchanged — including the GPT **Sol + Codex** double.

Every block is independent: each key present enables its own block, and blocks never collide because their `name:`s are provider-prefixed (`openai-gpt-5.6-sol` on the direct block vs. `openrouter-gpt-5.6-sol` on the routed one, just as **Fable 5** appears once direct and once via OpenRouter). The adaptive Claude models (Fable 5, Opus 5, Opus 4.8, Sonnet 5, Sonnet 4.6) use adaptive thinking (Haiku takes an explicit budget); DeepSeek and Moonshot home entries ship the OpenAI-compatible `extra_body` thinking toggle, and every thinking-capable entry ships `supports_thinking: true` so DeerFlow's thinking toggle actually engages. (Gemini's home entries go through the native SDK, which has no thinking toggle here — use the OpenRouter Gemini entry or a `gemini_openai_gateway` for Gemini thinking; Mistral Large is not a reasoning model, matching its OpenRouter entry.)

**Bounded and idempotent — safe on a hand-edited config.** The script owns only the model entries between a provider's `# === BEGIN auto-model-config: <provider> ===` / `# === END … ===` markers in `config.yaml` (shipped in `config.example.yaml`, so `make config` copies them in). It:

- **only ever uncomments**, never re-comments — a model you enabled by hand is never turned back off;
- **skips a block whose models are already active**, so a config written by `make setup` (or by hand) is never duplicated;
- **no-ops when the key is missing** or is still a placeholder (`your-…`, empty, or an unresolved `$VAR`);
- **no-ops when the markers are absent** (an older `config.yaml` predating this feature) — nothing to uncomment;
- refuses to run against a config with duplicate top-level keys (same guard as the Ollama sync).

It is hooked into **every launch path**, right after the Ollama sync, so however you start DeerFlow the block is enabled once your key is in place:

| Path | Where it runs |
| --- | --- |
| `make dev` / `make start` (+ daemons) | `scripts/serve.sh` (reads the `.env` it already sourced) |
| `make docker-start` (Docker dev) | `scripts/docker.sh`, on the host before `compose up` |
| `make up` (Docker prod) | `scripts/deploy.sh`, on the host before `compose up` |

On the Docker paths `config.yaml` is edited on the host **before** the containers mount it (read-only), same as the Ollama sync. `make setup` still enables the identical sets interactively (`scripts/wizard/providers.py` is the shared source of truth for the model definitions).

```bash
# Manual run (reads repo-root .env and config.yaml)
python3 scripts/sync-api-key-models.py --verbose

# Preview without writing
python3 scripts/sync-api-key-models.py --dry-run

# Point at a specific config / env file
python3 scripts/sync-api-key-models.py --config config.yaml --env-file .env --verbose
```

Model ids current as of 2026-07 — edit the block in `config.example.yaml` (or `config.yaml` after it is enabled) to add, drop, or re-slug models.

**The bundled model list is a living list — keep it current.** Providers ship, rename, retire, and re-price models faster than upstream DeerFlow moves, so treat the roster as something to revisit periodically, not a one-time setup. Three things stay honest on each pass — *which* models are bundled, their *format/settings*, and their *pricing* — and each has its own criteria below, gathered into a single periodic checklist in *Auditing the model list*.

#### Which models to keep in the bundle

The shipped set is deliberately a curated "big names" list, not a catalog dump. When refreshing it, keep to this exact shape:

- **Anthropic (direct key) — the Claude lineup, by family generation:**
  - **Opus** and **Sonnet** each keep their **last 4.x _and_ the current 5** — i.e. Opus 4.8 + Opus 5, Sonnet 4.6 + Sonnet 5. These are the tiers people pin threads to, so the outgoing 4.x stays alongside its 5 successor rather than being dropped the day 5 ships.
  - **Haiku** and **Fable** keep **only the latest** — Haiku 4.5, Fable 5. The small/cheap tier and the top "most capable" tier each only need their current model; nobody pins an old Haiku or an old Fable.
  - When a new generation ships (say Opus 6), the rule rolls forward mechanically: the new model joins, the now-second-newest Opus stays as the "last 4.x-equivalent" pin, and the third-oldest drops.
- **Fable also via OpenRouter.** Fable 5 is the one Claude that also gets an OpenRouter entry, for users who only hold an `OPENROUTER_API_KEY` and still want the flagship. Every **other** Claude lives **only** on the direct Anthropic block — routing an already-direct Claude through OpenRouter just adds the `(p)` privacy caveat and a middleman for no benefit.
- **First-party "home" block per big-name lab.** Every lab that ships its own API gets a direct block, gated by that lab's own key, carrying that lab's lineup on its native/OpenAI-compatible endpoint — the same shape as the Anthropic block above. Currently: **OpenAI** (`OPENAI_API_KEY`), **xAI** (`XAI_API_KEY`), **Google** (`GEMINI_API_KEY`, native SDK), **DeepSeek** (`DEEPSEEK_API_KEY`), **Mistral** (`MISTRAL_API_KEY`), **Moonshot** (`MOONSHOT_API_KEY`), **Qwen/Alibaba** (`DASHSCOPE_API_KEY`), **MiniMax** (`MINIMAX_API_KEY`), **Zhipu/z.ai** (`ZAI_API_KEY`). Two open-weight labs are deliberately **OpenRouter-only** — **Meta Llama** and **NVIDIA Nemotron** have no clean first-party consumer chat API, so they keep just their routed flagship. Each home block carries the flagship (**doubled** with the OpenRouter entry) **plus a small fuller family** — the same "a lab's direct key deserves its real lineup" logic that gives the Anthropic block six Claudes. Keep the home families tight (flagship + 1–2 acclaimed/cheaper siblings, like OpenAI's Sol + Codex + Mini); the trim-aggressively rule below still applies. Home entries carry the lab's own name suffix (`(OpenAI)`, `(xAI)`, …), **never** `(p)` (they're direct), and use the lab's own list price (no OpenRouter promo star).
- **OpenRouter — the "big names," one main model each.** One flagship entry per major lab: **xAI** (Grok), **OpenAI/ChatGPT** (GPT), **Google** (Gemini), **DeepSeek**, **Moonshot/Kimi**, **Qwen**, **Mistral**, plus the other strong open models that make sense (**Zhipu/GLM**, **MiniMax**, Meta **Llama**, NVIDIA **Nemotron**). **Mostly just the main model per lab** — add a _second, smaller_ model only when that smaller one is itself **critically acclaimed** in its own right (the shipped example is OpenAI: GPT-5.6 Sol as the flagship **and** GPT-5.3 Codex, the widely-praised agentic-coding variant). Don't list every size a lab offers. This trim set is kept **as-is** even though the labs now also have home blocks — the doubled flagship is the point, and the Sol + Codex double stays.
- **Cost spread.** Keep at least one genuinely cheap option live (Haiku, Gemini Flash, GLM/MiniMax) so the mixed-model cost story in this doc holds in practice.

Rule of thumb: the full Opus/Sonnet-4.x-plus-5 Claude set on the Anthropic key; a tight first-party home block (flagship + 1–2 siblings) for every lab that has its own API; Fable and each lab's flagship also on OpenRouter; one recognizable flagship per big-name lab on OpenRouter (a second only if the smaller model is acclaimed on its own); and nothing that isn't a flagship or a deliberate budget pick. Trim aggressively — a long list dilutes the picker and the auto-config.

#### Keep the model format current, and free of deprecated fields

Provider APIs change model IDs and request-shape rules faster than upstream DeerFlow does, so a refresh must re-validate the *format*, not just swap names. Before committing a model-block change:

- **Model IDs / slugs** — confirm each `model:` is the exact current id (Anthropic bare ids like `claude-opus-5`; OpenRouter `provider/model` slugs). A wrong or unreleased id fails at request time, not at load. When unsure of a live slug, verify against the provider's / OpenRouter's catalog rather than guessing.
- **Thinking config matches the model family** — the adaptive Claude models (Fable 5, Opus 5, Opus 4.8, Sonnet 5, Sonnet 4.6) reject the old `thinking: {type: enabled, budget_tokens: N}` form with a 400; use `type: adaptive`. Only pre-adaptive models (Haiku 4.5 and older) still take `budget_tokens` (min 1024, `< max_tokens`). Fable 5 additionally rejects `type: disabled`, so its disabled state must stay on adaptive. Sampling params (`temperature`/`top_p`/`top_k`) are rejected on the newest Claude models — don't add them to those entries.
- **No deprecated fields** — drop anything the provider has removed (e.g. `budget_tokens` on adaptive models, `output_format` in favour of `output_config.format`, retired tool-version strings). If a `supports_*` flag no longer maps to a real capability, remove it.
- **`supports_thinking: true` is load-bearing** — without it DeerFlow silently runs the model in non-thinking mode even with the UI toggle on.
- **Pricing (optional) uses one currency** — the console cost display sums across models, so every `pricing:` block must share a currency; mixed currencies disable the feature. Prices are per 1M tokens (`input_per_million` / `output_per_million`, optional `input_cache_hit_per_million`). The shipped Anthropic entries carry USD list prices as a worked example.
- **Regression-test the change** — `python3 scripts/sync-api-key-models.py --dry-run` must still uncomment the block cleanly, and `cd backend && uv run pytest tests/test_sync_api_key_models.py tests/test_config_integrity.py` must stay green.

#### The machine-readable `pricing:` block — how to write pricing in `config.yaml`

Beyond the price-in-the-name signal below, a model entry can carry an optional **`pricing:` block**. This is the machine-readable price the workspace **console cost display** actually bills runs against (the name is just a human glance). Write it as a child of the model entry in `config.yaml` (or the `config.example.yaml` marker block that seeds it):

```yaml
models:
  - name: Claude Opus 4.8 ($5/25) (Anthropic)
    use: langchain_anthropic:ChatAnthropic
    model: claude-opus-4-8
    max_tokens: 8192
    supports_thinking: true
    # ...other per-model settings...
    pricing:                        # optional; powers the console real-cost display
      currency: USD                 # ISO code (USD, CNY, ...); see the one-currency rule below
      input_per_million: 5.0        # price per 1M input tokens (cache MISS)
      output_per_million: 25.0      # price per 1M output tokens
      input_cache_hit_per_million: 0.5  # optional; prompt-cache reads ≈ 0.1x input
      promo_input_per_million: 2.5      # optional; a live discount — see below
      promo_output_per_million: 12.5
      promo_input_cache_hit_per_million: 0.25
```

The logic that block feeds, and the rules for writing it:

- **Prices are per 1,000,000 tokens**, in the stated `currency`. `input_per_million` is the cache-*miss* input price; `output_per_million` is the output price.
- **`promo_*_per_million` is an optional live discount, and it is strictly additive.** When a provider is currently discounting a model (an OpenRouter promotion, an Anthropic introductory window — see *Price signal in the display name* below), the promo rate goes here **beside** the standard one, never instead of it. Cost is still **billed at the standard rate**, because a promo can end at any time and a silently-too-low estimate is worse than a slightly-high one; the promo exists so the chat header can show what the conversation costs *today* (green) next to what it costs once the discount lapses (red). Both directions are required — a half-specified promo, a non-positive one, or one **above** the list price is a config error and the loader drops the whole promo with a warning rather than honouring part of it. `promo_input_cache_hit_per_million` follows the same optional/fallback rule as its standard counterpart.
- **`input_cache_hit_per_million` is optional.** Prompt-cache-hit input tokens are billed at this rate; **omit it and cache hits fall back to the miss price** (`input_per_million`) — a deliberate conservative upper bound. For Anthropic, cache reads run ≈ 0.1× the input price, so `input/10` is the right figure. The console is cache-aware: it reads each run's `token_usage_by_model` input/output split plus accumulated `cache_read` tokens and prices them separately.
- **One currency across every priced model.** The console sums cost across models, so a mix of currencies is meaningless — if two priced models declare different `currency` values, cost reporting is **disabled entirely** (the cost/currency fields go null) rather than producing an invalid total. Pick one currency and price every `pricing:` block in it.
- **The block is optional because the name already carries the price.** When a model entry has no `pricing:` block, `app/gateway/pricing.py::derive_pricing_from_display_name` reads the `($<in>/<out>)` pair (and any starred promo) straight out of `display_name`. **This is what makes the feature work on an existing install, and it is not a convenience.** Shipping blocks in `config.example.yaml` only ever reaches a *brand-new* `config.yaml`: `sync-api-key-models.py` skips a provider block whose models are already active (correct — it must not duplicate them) and `config_upgrade.py`'s `merge_missing` is dict-based, so it cannot add a key inside an existing list entry. Anyone who ran DeerFlow before a price shipped therefore keeps that model active and **unpriced forever**, and their chat header stays on `—` no matter how many times the example is corrected. Reproduced end to end: an upgraded config with 13 active models and 0 `pricing:` blocks produced `no changes` from both launch-path regenerators. An explicit block always wins over the derived one, and a malformed explicit block is *not* silently replaced by the name's price — that is an operator error worth surfacing. Pinned by `TestBundledModelPricing::test_every_bundled_model_prices_without_its_pricing_block`, which strips each bundled block and requires the same figures back.
- **Pricing is optional and additive.** A model with no `pricing:` block yields `cost: null` (it just doesn't contribute to the total); when *no* model is priced, the console omits cost columns. `ModelConfig` is `extra="allow"`, so adding the block needs no schema change.
- **What ships priced: everything.** All **40** bundled paid models across all eleven marker blocks carry a `pricing:` block, in both synced sources. This is load-bearing, not a nicety — a model without one contributes nothing to the total, so a conversation run entirely on unpriced models reports **no cost at all**. Shipping only the Anthropic block priced is exactly what made the chat header render `—` for anyone using another provider. Only Ollama (populated at runtime, genuinely free) stays unpriced. The blocks are **derived from the price-in-name pair**, so the human-readable price and the billed price cannot disagree: `config.example.yaml` carries them literally, and `scripts/wizard/providers.py` computes them once via `pricing_for_display_name()` applied to every bundle. Add a new bundled model and the wizard prices it automatically from its name; the config block needs the four literal lines. `input_cache_hit_per_million` is set only on the Anthropic entries (0.1x input, their published cache-read rate) — other providers differ or do not publish one, so their blocks omit it and cache hits fall back to the full input price, the documented conservative upper bound. The three currently-discounted entries (Claude Sonnet 5's intro window, MiniMax M3 and GLM-5.2 on OpenRouter) additionally carry `promo_*_per_million`, derived from the **starred** half of the same name pair. Pinned by `backend/tests/test_config_integrity.py::TestBundledModelPricing` (every model priced, well-formed, single-currency, price matches the name pair, **promo price matches the starred pair and sits below list**, and the two sources agree).
- **Keep it current with the roster.** The `pricing:` block is part of the same living bundle as the model list — refresh it on the same cadence as slugs and thinking config (see *Auditing the model list* below), reading each figure off the provider's own model page, never from memory.

#### Price signal in the display name

Every bundled model's `display_name` carries its price as a bracketed `($<input>/<output>)` pair in USD per 1M tokens, placed before the source suffix — `(Anthropic)` for the direct Anthropic API or `(OpenRouter)` for OpenRouter-routed models — and any trailing `(p)` marker. E.g. `Kimi K3 ($3/15) (OpenRouter) (p)` = $3 in / $15 out, `Claude Sonnet 4.6 ($3/15) (Anthropic)`. The model dropdown (`frontend/src/components/workspace/input-box.tsx`) renders `display_name`, so the pair shows up right in the picker and lets you compare cost at a glance without opening the config. The `$`-prefixed bracket keeps the numbers readable next to the model name instead of running into it.

The **discount** marker rides on **any** entry currently on a reduced price, direct or routed:

- **`($<list> → $<promo>*)` — a temporary discount.** When a model is currently on a reduced price, the name shows **both** prices: the standard list price, then the discounted price you actually pay now, starred. The `*` marks the second pair as a discount that can end at any time. Two sources of discount qualify:
  - **OpenRouter promotions.** As of 2026-08: **MiniMax M3** (`$0.6/2.4 → $0.24/0.96*`, 60% off) and **GLM-5.2** (`$1.15/3.6 → $0.28/0.87*`, 76% off). Derive the list price from the promo page's discounted figure and its stated discount (`list = discounted / (1 − discount)`), so both numbers stay internally consistent.
  - **Anthropic introductory pricing.** A newly launched Claude can ship at an intro rate below its standard list price for a fixed window. As of 2026-07 **Claude Sonnet 5** runs intro pricing through 2026-08-31, so it shows `Claude Sonnet 5 ($3/15 → $2/10*) (Anthropic)` — standard `$3/15`, intro `$2/10`. When the intro window ends, drop the starred pair back to the plain list price.

  A starred name has a machine-readable twin: the model's `pricing:` block keeps the **standard** rate (what cost is billed against) *and* carries the starred figures as `promo_*_per_million`. Both spellings must move together — a promo that ends in the name but survives in the block leaves the header advertising a discount nobody is getting. The model dropdown colours the pair straight out of the name (list red, promo green), and the chat header shows the same pair as two totals. Pinned by `TestBundledModelPricing::test_promo_price_matches_the_starred_pair_in_the_name`, which fails in **both** directions: a starred name with no `promo_*` block, and a `promo_*` block with no starred name.

The privacy marker rides only on the OpenRouter entries:

- **`(p)` — privacy caveat (zero-data-retention not guaranteed).** OpenRouter routes each request to a third-party provider that may log or retain prompts, unlike the direct Anthropic entries (or local Ollama). Every OpenRouter entry carries `(p)`; the direct Anthropic bundle and Ollama models do not. It flags "don't put sensitive data through this one" at a glance — steer private work to the direct Anthropic or local models. This is a routing property, so `(p)` stays on an OpenRouter entry regardless of which underlying lab it points at (the Fable-via-OpenRouter entry carries it too).

Rules for keeping it honest:

- **It is a rough signal, not billing truth.** Round to a clean pair; prompt-cache discounts and provider-variant routing shift the real number. The machine-readable `pricing:` block is what actually feeds the console and chat-header cost displays — keep that exact, keep the name approximate. (The two are kept from drifting apart by `TestBundledModelPricing`, which asserts the block matches the name pair, so "approximate" means *choose* a clean number, not let the two spellings diverge.)
- **Verify, never invent.** When adding or re-pricing a model, read the current figure off the provider's / OpenRouter's own model page (and its promotions/discounts page for a starred promo). Do not carry a price from memory for a model past your knowledge cutoff.
- **Refresh the pair when you re-slug or re-tier a model, and when a promo starts or ends**, the same way you re-check the slug and thinking config above — a stale price in the name is worse than none. When a promo ends, drop the starred pair back to the plain list price; when one starts, add the `$list → $promo*` pair.
- **Keep both model sources in sync.** The price-in-name lives in two places that must match: the `config.example.yaml` marker blocks (the auto-config path) and `scripts/wizard/providers.py` (`make setup`). Edit both, or a user gets prices on one path and bare names on the other. The `(p)` and `*`/promo markers live in the same two places — keep them in sync too.

#### Auditing the model list (settings + pricing)

Run this pass **periodically, whenever you touch the bundle, and as a step of the [Post-sync feature checklist](#post-sync-feature-checklist) on every upstream merge** — models, prices, and promos shift on the providers' schedule, not upstream's, so the sync is just a convenient recurring checkpoint to re-verify them. It keeps the enabled models, their per-model settings, and their prices honest. Everything below lives in the **two synced sources** — the `config.example.yaml` marker blocks and `scripts/wizard/providers.py` — so apply every change to both.

1. **Roster & order.** The bundle stays grouped by provider in this order: **Anthropic** (direct) → **OpenRouter** → the **first-party "home" blocks** (OpenAI, xAI, Google, DeepSeek, Mistral, Moonshot, Qwen, MiniMax, z-ai — in `config.example.yaml`'s FIRST-PARTY HOME API BLOCKS section) → **Ollama** (populated at runtime by `scripts/sync-ollama-models.py`, so it lands after the static blocks). Keep the "one flagship per big-name lab + a couple of cheaper picks" shape from *Which models to keep in the bundle* above, and keep each lab's flagship **doubled** (home + OpenRouter).
2. **Slugs.** Confirm each `model:` is the exact current id (bare Anthropic ids like `claude-opus-5`; OpenRouter `provider/model` slugs; **home** blocks use each lab's own bare id — the OpenRouter slug minus its `provider/` prefix, e.g. `openai/gpt-5.6-sol` → `gpt-5.6-sol`, `z-ai/glm-5.2` → `glm-5.2`). A wrong/unreleased id fails at request time, not at load — verify against the provider's / OpenRouter's catalog, never from memory.
3. **Per-model settings.** Sanity-check `max_tokens`, `supports_vision`, `supports_thinking`, `temperature`, and the thinking config against the model family (adaptive Claude vs. Haiku budget vs. OpenAI-compatible `extra_body` toggles — see *Keep the model format current* above). `supports_thinking: true` is load-bearing; drop deprecated fields. Confirm each home block's `base_url`/`api_base` and env var match the lab (e.g. `https://api.x.ai/v1` + `XAI_API_KEY`); Google's home block uses the native `ChatGoogleGenerativeAI` SDK with `gemini_api_key` and no thinking toggle.
4. **Pricing.** Read each price off the provider's / OpenRouter's own model page and refresh the `($<in>/<out>)` pair — **and the model's `pricing:` block with it** (all 40 bundled paid models carry one; `config.example.yaml` holds them literally, `providers.py` derives them from the same name pair, and `TestBundledModelPricing` fails if the two ever disagree). Then show both prices as `($<list> → $<promo>*)` for **any** currently discounted model — from OpenRouter's **promotions/discounts page** (derive list as `list = discounted / (1 − discount)`) **or** an Anthropic **introductory-pricing** window (a newly launched Claude below its standard rate for a fixed window, e.g. Sonnet 5 through 2026-08-31). Drop the starred pair back to plain list when a promo or intro window ends — **and drop the entry's `promo_*_per_million` lines in the same edit**, or the header keeps advertising a discount that has expired (the block is derived automatically in `providers.py`, but `config.example.yaml` holds it literally). **Home entries use the lab's own list price with no promo star** (the OpenRouter promo is a routing property that stays on the OpenRouter copy). Keep the machine-readable `pricing:` block exact: `input_per_million`/`output_per_million` stay the **standard** rate — the conservative upper bound cost is billed against even while a discount is live — and `promo_*_per_million` carries the starred figures beside it.
5. **Privacy marker.** Every OpenRouter entry carries `(p)` (zero-data-retention not guaranteed); the direct Anthropic, first-party **home**, and Ollama entries do not (they hit the lab directly, no middleman). Add `(p)` to any new OpenRouter entry, and the lab's own name suffix (`(OpenAI)`, `(xAI)`, …) to any new home entry.
6. **Regression-test.** `python3 scripts/sync-api-key-models.py --dry-run` must still uncomment the blocks cleanly, and `cd backend && uv run pytest tests/test_sync_api_key_models.py tests/test_setup_wizard.py tests/test_config_integrity.py` must stay green.

### 3. Per-thread subagent model override (Ultra mode)

A second model selector appears next to the lead-model picker when **Ultra mode** (subagents enabled) is active. Default is "Follow lead" (subagents inherit the lead model, identical to upstream behavior). Pick anything else and `task` tool delegations route to that model instead.

Backend reads `subagent_model_name` from the LangGraph thread context in `task_tool.py` and overrides the resolved subagent model. Frontend stores the choice in `AgentThreadContext` only — **ephemeral per thread**, no localStorage. Switch threads and it resets to "Follow lead".

Models flagged `supports_tools: false` (only Ollama models that don't report the tools capability) appear at the bottom of the list, dimmed, with a "(no tool support)" annotation. Still selectable in case the flag is wrong; tool-using subagents will simply fail at runtime.

### 4. Follow-up suggestions off by default (+ model picker)

Upstream generates the clickable follow-up-question chips after every answer via an extra one-shot LLM call. That is real per-turn cost you may not want, so this fork defaults it **off** and makes it a first-class, per-user preference.

- **Default off.** The client-side setting `suggestions.enabled` defaults to `false` (`frontend/src/core/settings/local.ts`), so a fresh browser makes no suggestion calls. The frontend only requests suggestions when the server master switch (`config.yaml → suggestions.enabled`, unchanged) **and** the per-user toggle are both on.
- **Toggle in settings.** A new **Settings → Suggestions** page (`suggestions-settings-page.tsx`) exposes the toggle. If the operator has disabled suggestions server-side, the toggle is greyed with an explanatory hint.
- **Model picker.** Under the toggle, a dropdown chooses which model writes the questions. The first option, **"Follow workflow selection"** (`modelName: undefined`), reuses the thread's current model — identical to the previous behavior. Pick any configured model instead (e.g. a cheap one) and it is sent as the suggestions request's `model_name`; the backend endpoint already accepts that override, so no backend change was needed.

The preference lives in `localStorage` (`deerflow.local-settings`) alongside the other client settings — per-browser, not per-thread. The goal is purely cost control: leave it off, or point it at a cheap model, and the suggestion feature stops being a silent tax on every turn.

### 5. Passwordless by default (local use)

Upstream ships a full email/password (plus optional SSO) login wall: on first run you create an admin through `/initialize`, and every browser then has to log in. For a personal machine — and especially for reaching the app from another device on your LAN — that wall is pure friction. This fork **defaults the local stack to no login at all**.

The mechanism is upstream's own `DEER_FLOW_AUTH_DISABLED` switch, which both the Gateway (`backend/app/gateway/auth_disabled.py`) and the Next.js SSR auth check (`frontend/src/core/auth/auth-disabled-user.ts`) already honor: when set, every request resolves to the built-in `default` admin user, the login/setup pages are skipped, and there is no password to manage. The fork just turns it **on by default** at launch:

- **Where it's wired.** `scripts/serve.sh` exports `DEER_FLOW_AUTH_DISABLED="${DEER_FLOW_AUTH_DISABLED:-1}"` (in the `apply_default_auth_mode` helper) right after loading `.env`, before the gateway and frontend are launched, so **both** child processes inherit it. This covers every local path: `make dev`, `make start`, and their `--daemon` variants. The Docker **prod** path (`make up` / `scripts/deploy.sh`) has a matching `apply_default_auth_mode` helper that resolves the value from `.env` (via `read_dotenv_value`, which honors an already-exported shell var first) and defaults it to `1`, then exports it; `make up` prints a warning line when auth ends up off. Because `deploy.sh` doesn't source `.env` into the shell and the frontend container reads only `frontend/.env`, `docker-compose.yaml` forwards `DEER_FLOW_AUTH_DISABLED` **and** the production markers `DEER_FLOW_ENV` / `ENVIRONMENT` to **both** the gateway and frontend `environment:` blocks — otherwise the two containers could disagree on whether auth is on. (Before this fix, `make up` was *not* wired with the default, so a home-lab Docker deploy hit the login wall unexpectedly — see "Troubleshooting: nginx 502 after `make up`" below.)
- **Opt-out, not forced.** Set `DEER_FLOW_AUTH_DISABLED=0` in `.env` to restore the normal email/password login. Any explicit value you set (0 or 1) is preserved — the default only fills in the unset case. Both `.env.example` files document the toggle.
- **Self-disabling in production.** The flag is ignored whenever `DEER_FLOW_ENV` / `ENVIRONMENT` is `prod`/`production` (enforced in both `auth_disabled.py` and `auth-disabled-user.ts`), so a real deployment that sets that variable keeps authentication on regardless of this default. The Docker stack also publishes its entry port on `127.0.0.1` (loopback) by default (`BIND_HOST`), so the default surface is local-only.
- **LAN note.** Because there's no login, any device that can reach the server (e.g. `http://<your-ip>:2026`) is in — that's the point, but it also means anyone on your network is too. Keep it to trusted networks, or flip `DEER_FLOW_AUTH_DISABLED=0` and use the login.
- **Dev-server access from other devices works out of the box too.** Next.js gates its dev resources (`/_next/*`, fonts, HMR) with `allowedDevOrigins` — an unlisted host 403s the client bundles, so the page renders but never hydrates (visible shell, dead buttons, no input box). To match the passwordless-for-LAN default, `frontend/src/dev-origins.js` now **defaults that allowlist to the private-LAN and Tailscale ranges** (`10.*`, `172.*`, `192.168.*`, `100.*` Tailscale CGNAT, `**.ts.net` MagicDNS, `*.local`), so `make dev` reached from a phone on the network or over Tailscale hydrates without extra config. `DEER_FLOW_DEV_ALLOWED_ORIGINS` still adds hosts the defaults miss (a custom domain, an IPv6 literal); `DEER_FLOW_DEV_ALLOWED_ORIGINS_STRICT=1` drops the built-in defaults for upstream's stricter behavior. Dev-only — production builds ignore `allowedDevOrigins`. Pinned by `frontend/tests/unit/dev-origins.test.ts` (which runs the defaults through Next's real matcher).

`config.yaml` is unchanged; this is purely an environment default, so it ships in the fork (via `serve.sh` / `deploy.sh` + the `.env.example` docs) rather than per-install. Pinned by `backend/tests/test_serve_auth_default.py` (local launcher) and `backend/tests/test_deploy_auth_default.py` (Docker prod launcher opt-out precedence + the compose forwarding of `DEER_FLOW_AUTH_DISABLED` / `DEER_FLOW_ENV` / `ENVIRONMENT` to both containers).

### 6. Multi-user mode toggle (combine or isolate histories)

Upstream scopes every conversation to an owner `user_id`, so each login only sees its own threads. That's right for a shared deployment, but it has a sharp edge on a personal fork: once you go passwordless (§5) the effective user is always `default`, yet any conversations created back when login was on live under real account ids — so they're "stranded", invisible under `default`, and the phone and PC appear to have separate histories. **Multi-user mode** is a toggle for exactly this.

- **What it does.** ON (default) = upstream behavior, per-login thread isolation. OFF = one shared workspace: thread listing and per-thread access ignore the owner filter, so **every conversation is visible regardless of which login or device created it** — including the stranded pre-passwordless ones.
- **Where it lives.** Settings → Account, as a switch (admin-only; in passwordless mode the built-in `default` user is admin). Turning it OFF pops a confirmation explaining it will combine all histories; turning it back ON is immediate and restores isolation. It is a **server-wide** setting (not a per-browser preference) — that's what makes it actually merge phone + PC — persisted as JSON under the DeerFlow home dir (`runtime_settings.json`), read hot (no restart), never touching the operator's `config.yaml`.
- **How it's wired.** `deerflow/config/runtime_settings.py` owns the setting plus `resolve_owner_scope()` — a read/access resolver that returns `None` (no owner filter) when the mode is OFF and otherwise defers to the normal `resolve_user_id`. The thread-metadata store (`search`/`get`/`check_access`) and run-store read helpers use it, so the sidebar lists everything and any thread can be opened/continued; `check_access` returning True covers every `owner_check` route guard in one place. **Writes still stamp the real owner**, so re-enabling isolation cleanly restores each login's own view. Gateway `GET`/`PUT /api/settings/multi-user-mode` reads/toggles it (PUT admin-gated).
- **Security.** With it OFF, anyone who can reach the server sees all conversations — the same trust model as passwordless. Leave it ON on any shared/public deployment.

Pinned by `backend/tests/test_multi_user_mode.py` (setting round-trip, owner-scope bypass, thread isolation ON vs OFF, admin-gated API) and `frontend/tests/unit/core/settings/multi-user-mode.test.ts`.

### 7. Live cost overview in the conversation header (model-aware) + memory/suggestions counters

The conversation header already showed a token counter (input / output / total for the whole thread). This fork adds a **real-cost estimate** next to it, and — because a personal deployment mixes premium, cheap, and free-local models on purpose (§"Why mix local and cloud" below) — makes it **model-aware** so the number reflects what you actually spent, not a single headline rate.

- **Where the price comes from.** Each model's `pricing:` block in `config.yaml` (`currency`, `input_per_million`, `output_per_million`, optional `input_cache_hit_per_million`, optional `promo_*_per_million`) — the same machine-readable pricing documented in §2's *"The machine-readable `pricing:` block"*. **All 40 bundled paid models ship priced** on both the auto-config and `make setup` paths, so the estimate works out of the box whichever provider you use; only unpriced local Ollama models contribute nothing. No `pricing:` anywhere → the cost line simply hides (token counts still show).
- **The cost is green, and a live discount shows both prices.** The figure reads as money rather than as another token counter, so it is rendered in green (`text-emerald-500`) in both the header pill and the dropdown. When any model in the thread is currently discounted, the dropdown shows **two** totals side by side — the green one is what the conversation costs at today's promo rate, the red one (`text-red-500`) is the same thread billed at the standard rate it reverts to when the promo ends — with a `promo rate now` / `standard rate` legend beneath. Both totals cover the **whole** thread: an undiscounted model contributes its ordinary cost to each, so the pair is directly comparable rather than being a discounted subtotal beside a full total. The header pill stays a single number (what you actually pay now); there is no room there to label a pair. `promo_total_cost` is null — and the UI falls back to one green figure — when nothing in the thread is discounted, or when the promo total happens to equal the standard one, because printing the same number twice in two colours claims a discount that does not exist.
- **A missing price explains itself.** A model that burned tokens with no `pricing:` block is reported in the endpoint's `unpriced_models`, and the header names it: *"No cost shown: no price is configured for `<model>`"* when nothing was priceable, or *"Excludes `<model>` — no price configured, so the real cost is higher"* when the total covers only some of the run. Without this a hand-added model silently renders a bare `—` (or a quietly low total), which is indistinguishable from the feature being broken — the exact failure that hid the two bugs above.
- **Model-aware, so subagents are billed correctly.** The cost is summed from each run's **per-model** `token_usage_by_model` split, not a flat rate on the thread total. A run whose lead was Opus and whose subagents ran on Haiku or a local Ollama model is priced Opus-for-Opus and Haiku-for-Haiku — the lever this fork exposes (§3, the per-thread subagent model dropdown) shows up directly in the number. Prompt-cache hits are billed at the cache-hit rate when configured (a conservative upper bound otherwise), reusing the exact same cache-aware math as the ops console.
- **Provider-reported model ids are resolved back to your config entry.** `token_usage_by_model` buckets are keyed by what the *provider* reported (`response_metadata.model_name`), which is routinely **not** the id in `config.yaml`: LangChain records the API-resolved model, so Anthropic hands back the dated snapshot its alias resolved to (`claude-opus-5` → `claude-opus-5-20260115`), OpenAI does the same, OpenRouter appends `:variant` routing tags, and a routed slug carries a `vendor/` prefix. Exact-string matching therefore found **no** price for any bucket, so every per-model `cost` was null and `total_cost` stayed null while `currency` was set — which is exactly the `—` the header rendered from the day this feature shipped. `lookup_pricing` now tries a small ordered set of normalized forms by **exact** lookup (never a prefix scan, so a normalization can only ever hit a model the operator actually configured): the reported id, then with the `vendor/` prefix peeled, the `:variant` tag dropped, and a terminal date stamp (`-20260115`, `-2026-01-15`, `@20260115`) removed. Most-specific-first, so a configured OpenRouter copy is still billed at its own routed price rather than the direct entry its slug reduces to; the date pattern is deliberately narrow, so a genuinely different sibling (`claude-opus-5-turbo`) stays unpriced instead of inheriting a neighbour's rate. Ollama tags (`qwen3:8b`) match exactly first and are unaffected.
- **Ollama / unpriced = $0.** A model with no `pricing:` block contributes nothing to the cost — local inference is treated as free even though it burns electricity. The header's **?** tooltip says exactly this so the number is never mistaken for a billing statement.
- **Separate memory & suggestions counters.** The two optional, off-by-default features that quietly cost tokens — background **memory** extraction (§"Long-term memory off by default") and follow-up **suggestions** (§4) — never become graph runs, so their tokens never reached the thread's run totals. They are now tracked in a small **durable** per-thread registry and shown as their **own** priced counters in the header dropdown when non-zero, so you can see what each is costing on top of the conversation itself. The registry survives a Gateway restart — see *Durable auxiliary counters* below.

**Where it's wired.**

| Piece | Location |
| --- | --- |
| Shared pricing math (build map, provider-id resolution, per-token cost, per-run cost, one-currency guard, promo rates) | `backend/app/gateway/pricing.py` — extracted from `routers/console.py` so the console and the thread endpoint price identically. `_pricing_lookup_candidates` owns the provider-reported-id normalization, so the console, the thread endpoint, and the memory/suggestions aux counters all resolve ids the same way. `_parse_promo_rates` validates a discount (both directions, positive, at or below list) and `ModelPricing.promo()` hands it back as an ordinary `ModelPricing`, so `token_cost` prices a promo through the same formula as a standard rate rather than a second one that could drift |
| Bundled model prices | All 40 paid entries in `config.example.yaml`'s marker blocks, mirrored by `scripts/wizard/providers.py::pricing_for_display_name()` (derived from the price-in-name pair — including the starred promo half — so the two sources cannot drift) |
| Thread cost endpoint | `GET /api/threads/{id}/token-usage` (`routers/thread_runs.py`) now returns `total_cost`, `promo_total_cost` (the same whole-thread total at live discount rates, null when nothing is discounted), `currency`, `unpriced_models` (models that spent tokens with no configured price), per-model `cost`/`input`/`output`/`cache_read`, and an `aux` map (memory/suggestions tokens+cost). The store aggregation (`runs/store/memory.py`, `persistence/run/sql.py`, shared `new_by_model_usage_entry()`) now carries the per-model input/output/cache-read split the pricing needs |
| Auxiliary-usage registry | `backend/packages/harness/deerflow/runtime/aux_usage.py` — thread-safe, bounded (LRU over 4096 threads), and **durable**: a write-through cache over `runtime/aux_usage_store.py`, a small dedicated SQLite file at `<DeerFlow home>/aux_usage.sqlite3`. Memory records via the existing `_host_default_extraction_callback` (`agents/memory/manager.py`); suggestions records via `run_oneshot_llm_with_usage` (`utils/oneshot_llm.py`) from `routers/suggestions.py`. Async callers (`routers/suggestions.py`, the `token-usage` endpoint) go through `arecord_aux_usage` / `aget_thread_aux_usage`, which offload the file IO |
| Frontend | `token-usage-indicator.tsx` renders the green cost (plus the red standard rate and its legend while a promo is live) + `?` tooltip + aux rows + the unpriced-model note; `core/threads/token-usage.ts` (`threadTokenUsageToCostSummary`, `formatCost`); both chat pages pass the summary; i18n `tokenUsage.cost` / `costHint` / `unpricedOnly` / `unpricedPartial` / `promoRate` / `standardRate` / `memory` / `suggestions` |

**Verify it works.** The pricing math and the endpoint are both offline-testable, so the backend tests are the fast gate:

```bash
cd backend && uv run pytest tests/test_pricing.py tests/test_thread_token_usage.py tests/test_aux_usage.py tests/test_aux_usage_wiring.py
cd backend && uv run pytest tests/blocking_io/test_aux_usage.py   # the durable aux store's IO stays off the event loop
make doctor      # 'model pricing' names the symptom when nothing configured can be priced
cd backend && uv run pytest tests/test_config_integrity.py -k BundledModelPricing   # every model priced; name pair == pricing block; promo pair == promo block
cd frontend && pnpm test token-usage                                                 # cost summary incl. promo + aux promo collapse
```

Then in the browser (`make dev` → open a chat that has run at least one turn): the header pill shows a **green** dollar amount; opening it shows **Estimated cost** in green, and — if any model in the thread is currently discounted — a red standard total beside it with the `promo rate now` / `standard rate` legend. Run an **Ultra-mode** turn with the subagent set to a discounted model (GLM-5.2 / MiniMax M3) and a full-price lead: the gap between the two totals should equal the subagent's saving only. Memory/suggestions rows are green and priced per their own model. **Then restart the Gateway** (`make stop && make dev`) and reopen the same thread: the memory/suggestions rows must come back with the same totals — that is the durability half, and it is the one thing a unit test cannot show you end to end. `<DeerFlow home>/aux_usage.sqlite3` is the file behind them.

**Durable auxiliary counters.** The memory and suggestions counters used to be process-local and reset on every Gateway restart. That was fine for a display counter and a bad foundation for a budget or a spend report, so they are now persisted.

- **Where.** `runtime/aux_usage_store.py`, a small dedicated SQLite file at `<DeerFlow home>/aux_usage.sqlite3` (default `backend/.deer-flow/`). Set `DEER_FLOW_AUX_USAGE_DB=<path>` to move it, or `DEER_FLOW_AUX_USAGE_DB=0` to go back to the old process-local counter.
- **Why a dedicated store and not the runs DB.** Memory usage is recorded from the memory updater's debounce worker — an ordinary `threading.Timer` thread with **no event loop** — and the application database is an async SQLAlchemy engine bound to the Gateway's loop. Reaching it would need a queue drained by that loop, which only works while a Gateway is running and loses whatever has not drained at shutdown. A plain `sqlite3` connection is usable from any thread, so one code path serves the Gateway, the embedded client, and the TUI; it commits where the call happens (nothing to lose on a hard crash); it needs no synchronous Postgres driver and no alembic revision; and aux usage has no foreign key into `runs`, so co-locating it buys nothing.
- **The in-memory registry is still there, as a write-through cache**, hydrated from the store on a thread's first touch — so the header keeps reading from memory. The LRU cap (4096 threads) now evicts *cache entries* rather than data: an evicted thread re-hydrates on its next touch.
- **Rows are append-only events with a `recorded_at`**, so a later spend window or attribution report can slice by date without a schema migration.
- **It is best-effort.** A store that cannot be opened or written logs one warning and the counter falls back to process-local for that run; memory extraction and chat responses are never disturbed.
- **Blocking IO.** The store is a local file, so `record_aux_usage` / `get_thread_aux_usage` touch the disk. They are safe from any thread (that is the point) but not from the event loop; async callers use `arecord_aux_usage` / `aget_thread_aux_usage`, pinned by `backend/tests/blocking_io/test_aux_usage.py`.
- **Multi-worker caveat.** The cache is per process, so with several Gateway workers one worker's header can lag a sibling's aux writes until that thread re-hydrates (restart or LRU eviction). The persisted totals are always complete; only a cached view can be behind. The fork's target is a single-process personal deployment.

**Caveats (deliberate).** Cost reflects **persisted runs only** (in-flight stream deltas aren't priced until the run completes). All priced models must share one currency (mixed currencies disable cost, same rule as the console).

**Tests (does it calculate correctly?).**

- `backend/tests/test_pricing.py` — the pricing math end-to-end: per-million pricing, cache-hit vs miss, the multi-model (subagent) run cost, unpriced/zero-priced skipping, and the mixed-currency guard. Also pins the **provider-reported id resolution** that made the header show `—`: Anthropic dated snapshots, OpenAI dashed-date and Vertex `@date` suffixes, OpenRouter `:variant` tags, a routed slug falling back to a direct entry, a configured routed copy still winning over that direct entry, sibling models never inheriting each other's rate (`claude-opus-4-8-…` vs `claude-opus-5`), an unconfigured/local id still resolving to `None`, and candidate ordering. `TestPricingDerivedFromDisplayName` covers the fallback that reaches existing installs — derivation from the name, the promo pair and Anthropic cache rate carried through, an explicit block always winning, a malformed explicit block *not* falling back, an unpriced name (Ollama, bare version numbers) staying unpriced, and a cross-check that the derived figures equal what `providers.py` generates for every bundled shape. `TestPromoPricing` covers the additive discount: promo rates exposed as a standalone `ModelPricing`, promo cache-hit accounting, `run_cost` still billing the standard rate, and every way an invalid promo (half-specified, malformed, zero/negative, above list) is dropped **whole** while the standard price survives.
- `backend/tests/test_aux_usage.py` — the registry: accumulation, category/model/thread isolation, deep-copy reads, the LRU cap, and thread-safety under concurrent writers. Plus **durability**: totals identical across a simulated restart (`reset_aux_usage_cache()` drops the cache and store handle, keeps the file), a post-restart write extending the hydrated totals instead of replaying them, a read miss never taking an LRU slot, an evicted thread re-hydrating rather than losing data, a second reader of the same file seeing the same totals, the `DEER_FLOW_AUX_USAGE_DB=0` kill switch restoring the old process-local behaviour, an unusable store degrading to the cache with exactly one warning, path resolution (default/disabled/explicit), the SQLite store's own aggregation, and the async wrappers.
- `backend/tests/test_aux_usage_wiring.py` — memory (`_host_default_extraction_callback`) and suggestions (`_record_suggestions_usage`) actually record into the registry, and both sinks survive a restart end to end.
- `backend/tests/blocking_io/test_aux_usage.py` — the strict Blockbuster anchor: `arecord_aux_usage` / `aget_thread_aux_usage` must offload the store's SQLite IO, so pointing the suggestions route or the `token-usage` endpoint back at the synchronous registry API fails CI instead of quietly stalling the event loop on every answer.
- `backend/tests/test_thread_token_usage.py` — the endpoint computes model-aware `total_cost`, per-model cost, and priced/unpriced `aux` counters (a worked example: Opus lead + cheap subagent + memory-on-unpriced + suggestions-on-priced), and nulls everything when no pricing is configured. `test_cost_tracks_model_switching_across_turns` pins the **"as the conversation goes on" property**: three turns on three different priced models (Opus → Sonnet → Haiku) drive the *real* cross-run per-model store aggregation through the *real* pricing helpers, asserting the cumulative cost is the sum of each turn billed at the model that actually ran it — no turn's tokens cross-attributed to another model's rate. `test_thread_token_usage_prices_provider_reported_model_ids` is the end-to-end regression for the `—` bug: it drives the **real endpoint** over the ids providers actually report (dated Anthropic snapshots plus an OpenRouter `:variant` slug) across a mid-conversation model switch and asserts a non-null cumulative cost — so a regression in the id resolution fails at the endpoint, not only in the pricing unit tests. Five further tests pin `promo_total_cost`: a mixed thread (one discounted model + one full-price) where the promo total bills the undiscounted model at its ordinary rate; null on both the no-promo and no-pricing-at-all paths; `test_promo_total_is_model_aware_across_lead_subagent_and_aux`, the Ultra-mode shape — full-price lead (dated Anthropic snapshot) + **discounted subagent** (OpenRouter `:variant` slug) + memory on the discounted model + suggestions on the full-price one, asserting the saving equals the subagent's alone rather than being smeared across the lead's tokens; and `test_unpriced_subagent_model_does_not_break_the_promo_total`, where a local Ollama subagent contributes 0 to both totals and is still named in `unpriced_models`.
- `backend/tests/test_token_usage_by_model.py`, `test_run_repository.py`, `test_persistence_scaffold.py` — updated for the enriched `by_model` shape (now carrying the input/output/cache-read split). `test_token_usage_by_model.py` also pins the store's cross-run merge when the lead model changes between turns, and memory/SQL-store parity (`test_memory_and_sql_stores_agree`).
- `frontend/tests/unit/core/threads/token-usage.test.ts` — `threadTokenUsageToCostSummary` (null without currency, drops zero-token aux rows, carries `promoTotalCost` and nulls it when absent **or** equal to the standard total) and `formatCost` (sub-cent precision, malformed-currency fallback).

### 8. Sortable / groupable model dropdown

The model picker can be **sorted by name or by price**, ascending or descending, and optionally **grouped by provider** (Anthropic / OpenRouter / Ollama). With a couple of dozen bundled models across premium cloud, cheap cloud, and local tiers (§2), the flat config-ordered list is hard to scan — this lets you line the models up by cost or name, or collapse them into provider sections, in one click.

- **Where the data comes from.** Price and provider are **not** structured fields on `/api/models` — they live only inside each model's `display_name` (the price-in-name pair from §2 and the `(Anthropic)`/`(OpenRouter)`/`(Ollama)` suffix). So this is a **frontend-only** feature: `frontend/src/core/models/sorting.ts` parses them. `parseModelPrice` reads the **current** price — the starred promo value when a `$list → $promo*` pair is present (§2's discount marker), else the single pair — and returns `null` for unpriced local/hand-added models. `parseModelProvider` reads the suffix. No backend change; if a name's format ever drifts, the parse degrades gracefully (unpriced sorts last, unknown suffix → an "Other" group) rather than throwing.
- **The price is coloured in the list.** `splitModelNamePriceSegments` splits a `display_name` into text and price runs so `ModelDisplayName` can paint the price green (`text-emerald-500`) — the money in a wall of model ids, matching the header's cost figure. A discounted `($list → $promo*)` name gets both halves coloured: the **promo** green (what you pay now) and the **list** price red (`text-red-500`, what it reverts to), the same green/red pairing the cost overview uses in §7. It is purely presentational and total: a name with no parseable price renders verbatim as one text segment, and the segments always rejoin to the original string, so no model can lose characters to the split. Used by all three pickers (lead, subagent, sidecar) in both the trigger label and the list row.
- **The collapsed trigger keeps the price, not the provider.** The composer's model button is capped at `max-w-40` / `sm:max-w-56`, and the price sits in the *middle* of a bundled name, so the promo half — the number you most want — was the first thing lost. Two changes fix it, and both are needed. (1) `compactModelDisplayName` drops trailing non-price groups (`(OpenRouter)`, `(Anthropic)`, and each lab's own home suffix) while keeping the `(p)` privacy marker, which is worth more at a glance than the provider and was previously truncated away first; the full name stays on hover via `title` and in the open list. (2) `ModelDisplayName variant="compact"` lays the segments out so only the **leading model name** may ellipsize — the price pair and `(p)` are `shrink-0`. **The host `ModelSelectorName` must carry `w-full`**, which is the actual pre-existing bug: it sits in a `flex-col items-start` container where its own `flex-1` sizes the *cross* axis (height), so it defaulted to `fit-content`, rendered **past** the capped button, and its `truncate` never fired at all. Measured in Chromium: a bundled promo name is 315px inside a 160px button; with `w-full` it is bounded to 142px and both prices stay visible at `max-w-40` and `sm:max-w-56` alike. If a trigger ever shows a clipped price again, check that `w-full` is still on all three `ModelSelectorName` triggers before touching the segment logic.
- **What the controls do.** Sort key `Default` (config order, the out-of-the-box default so nothing changes until you opt in) / `Name` / `Price`; a direction toggle (disabled for `Default`); and a **Group by provider** switch. Price sorts on the current **output** price (the dominant cost driver); unpriced models always sink to the bottom in both directions. The subagent picker additionally keeps tool-incapable models last (§3's `(no tool support)` rule) via the sorter's `demoteLast` option, and its "Follow lead" entry stays pinned at the top. While you type in the search box, `cmdk` orders by match relevance (the sort governs the browse order).
- **Where it lives.** The preference (`{ sortKey, sortDir, groupByProvider }`) is persisted **per browser** in `deerflow.local-settings` (`core/settings/local.ts`, `modelPicker`) — shared across threads, unlike the per-thread model selection. Shared UI in `components/workspace/model-picker-controls.tsx` (`ModelPickerControls` + `ModelPickerList`) is used by all three pickers: the lead and subagent selectors in `input-box.tsx` and the sidecar selector in `sidecar/sidecar-panel.tsx`, so ordering behaves identically everywhere. i18n keys live in `core/i18n/locales/{en-US,zh-CN}.ts`.

Pinned by `frontend/tests/unit/core/models/sorting.test.ts` (price/provider parsing incl. the promo pair and bare-version-number guard, name/price/default sorting, unpriced-last, `demoteLast`, provider grouping, `splitModelNamePriceSegments` — single vs. promo pair, the exact-reassembly property, no-price and empty names, and no shared regex state between calls — and `compactModelDisplayName` — provider suffix dropped, `(p)` kept, the price group never stripped, first-party home suffixes handled without a hardcoded list, a name that would compact to nothing returned whole, and the promo pair surviving for all three discounted bundled models). The *layout* half (does the price actually stay on screen?) is CSS, so no unit test covers it — it was verified by measuring the real cascade in Chromium, and the `w-full` note above is the regression guard.

**Verify it works.** The parsing/sorting/grouping is pure logic, so the unit test is the fast gate:

```bash
cd frontend && pnpm test sorting     # sorting.test.ts: parse price/provider, sort, group, demoteLast, price-segment split, compact trigger name
```

Then check the wiring end-to-end in the browser (`make dev` → open a chat): the model dropdown shows a **Sort** toggle (`Default` / `Name` / `Price`), a direction button (disabled on `Default`), and a **Group by provider** switch. `Price` orders by the current (promo-aware) output price with local/unpriced models last; `Group by provider` splits the list into Anthropic / OpenRouter / Ollama sections. Each row's price is green, and a discounted model (MiniMax M3, GLM-5.2, Claude Sonnet 5) shows its list price red beside the green promo. **Select one of those three and close the dropdown**: the collapsed button must still show both prices (the provider suffix is dropped to make room; hover for the full name). Check it at a narrow window width too — that is where it used to clip. The choice persists across reloads and threads (`deerflow.local-settings → modelPicker`). Confirm the same controls appear in the **Ultra-mode subagent** picker (no-tool models still sink to the bottom, "Follow lead" stays pinned) and the **sidecar** picker. Full frontend gate: `pnpm check && pnpm test`.

### 9. Browser-style keep-alive chat tabs

Upstream shows one live chat at a time: the sidebar lists your conversations, and clicking one navigates the single content pane — switching away tears the previous chat down (its stream, scroll position, and artifact panel are gone until you come back and reload). This fork adds a **browser-style tab strip** above the chat: drag a few conversations from the sidebar onto it (or use a row's **Open in tab** menu, or the strip's pin button) and they become **keep-alive tabs** that stay mounted and running as you switch between them — a background tab keeps streaming, keeps its scroll, and keeps its artifacts/browser panels.

- **What "keep-alive" means here.** The live chat was lifted out of the route into a persistent, workspace-level viewport (`keep-alive-chat-viewport.tsx`) mounted **above** the Next route, so navigating between chats never unmounts them. It renders one chat instance per pinned tab plus one for the current unpinned chat, and only the active one is shown — `display:none` on the rest keeps React state, DOM scroll position, and the SDK stream alive. Pinned tabs survive navigating to other workspace pages too (the whole viewport is just hidden). Switching tabs uses `history.replaceState`, not the Next router — the same reason the chat page already avoids the router on new→real, so nothing remounts.
- **Curated, reorderable, persisted.** Tabs are an explicit set you build by dragging from the sidebar (native HTML5 drag-and-drop) or the row's **Open in tab** action, reorder by dragging chips, and close with a chip's ✕. The current unpinned chat shows as a dashed "preview" chip with a pin button.
- **Persisted server-side, per user — the tab set survives a machine restart.** `localStorage` alone was not enough and lost people's tabs: it is scoped to one browser *and* one origin, so the set disappeared whenever the browser cleared site data on exit, evicted storage for an insecure-origin site (a plain-HTTP LAN deployment — the setup this fork documents), or the app was reopened on a different origin than the one that pinned them (`localhost` vs. a LAN/Tailscale address both reach the same server, with entirely separate stores). The durable store is `{base_dir}/users/{user_id}/ui_state.json` — a small per-user JSON bag beside the server-wide `runtime_settings.json`, written atomically, merged rather than replaced (so later per-user UI state can join it), and cached on the file's `(mtime, size)` so a sibling worker's write is picked up without a restart. It is exposed as `GET`/`PUT /api/settings/chat-tabs`, scoped to the calling user; unlike the multi-user-mode routes beside it there is **no admin gate**, because this is per-user UI state rather than a server-wide setting. The store validates, dedupes and caps the list exactly as the frontend model does, since the API is untrusted input.
- **`localStorage` is now a first-paint cache, not the source of truth.** The provider renders from it immediately, then reconciles: an unreachable gateway — the normal state right after a machine restart, when the browser reopens the app before the backend is up — **keeps the cache** rather than blanking the strip, and a server with no stored set **adopts the local one and seeds the server** (the upgrade path for tabs pinned before this existed). Writes back are coalesced and flushed on teardown/`pagehide`, so a browser tab closed right after a pin still records it. The local cache additionally refuses to write an empty set over a stored one unless a user action produced it: on the gateway-offline boot the provider starts on the `…anonymous` key (SSR has no user) and flips to the real one when the offline banner's probe resolves, and because the hydrate and persist effects run in the same commit the persist effect can still observe the pre-hydration `[]`.
- **The strip is always a drop target (even empty).** The whole point is to drag chats *up* onto the strip, so it must be visible before the first tab exists — otherwise there is nowhere to drop. On a brand-new chat with no tabs yet the strip therefore renders an **empty drop zone** with a hint ("Drag a chat here to keep it open as a tab") instead of collapsing to nothing; dragging a sidebar chat onto it pins the first tab and the hint disappears. The strip hides only when there is nothing to drag at all (a fresh install with no chat history) and, like the pinned instances, on non-chat workspace pages. This was the bug behind "the tabs don't work": the empty strip used to return `null`, so a user landing on the default new-chat page had no visible place to drag onto.
- **The single chat is now a reusable, controlled component.** `[thread_id]/page.tsx`'s body became `chat-instance.tsx` — **fully controlled** (the owner owns `threadId`/`isNewThread`; the instance reports its new→real promotion up) and wrapping its own provider stack with a per-instance `storageScope` so several artifacts panels never collide on one pathname. In app builds the route page is a thin **registrar** that reports the route to the tab strip and renders nothing; in **static-demo** builds the feature is off and the page renders the classic inline chat (the demo pre-renders these pages and enforces route asset budgets). Custom-agent chats keep the classic single-chat rendering.

**Where it's wired.**

| Piece | Location |
| --- | --- |
| Pure tab model (pin/close/reorder/promote, local-cache serialization, DnD MIME types) | `frontend/src/core/threads/chat-tabs.ts` |
| Durable per-user store + API | `backend/packages/harness/deerflow/config/user_ui_state.py` (`get_chat_tabs` / `set_chat_tabs` / `normalize_chat_tabs`, `ui_state.json`); `GET`/`PUT /api/settings/chat-tabs` in `backend/app/gateway/routers/settings.py` |
| Durable-store client | `frontend/src/core/threads/chat-tabs-api.ts` (`fetchChatTabs` returns `null` for "unknown" — distinct from "no tabs" — so an unreachable gateway never blanks the strip) |
| Tab state + active-slot coordination + server reconciliation | `frontend/src/core/threads/chat-tabs-context.tsx` (`ChatTabsProvider` / `useChatTabs`) |
| Persistent viewport + tab strip | `frontend/src/components/workspace/chats/keep-alive-chat-viewport.tsx`, `chat-tabs-bar.tsx` |
| Extracted controlled chat + its providers | `frontend/src/components/workspace/chats/chat-instance.tsx`, `chat-providers.tsx` |
| Route registrar / classic fallback | `frontend/src/app/workspace/chats/[thread_id]/page.tsx` |
| Shell mount + sidebar drag/menu | `frontend/src/app/workspace/workspace-content.tsx`, `components/workspace/recent-chat-list.tsx` |
| i18n | `core/i18n/locales/{en-US,zh-CN}.ts` (`chatTabs.*`) |

Pinned by `frontend/tests/unit/core/threads/chat-tabs.test.ts` (the pure model) and `frontend/tests/e2e/chat-tabs.spec.ts` (drag-from-sidebar onto the empty strip, drag-reorder between chips, open-as-tab via the row menu, keep-alive switch with both instances left mounted, close, reload persistence). The two drag tests drive native HTML5 drag-and-drop directly (`html5DragAndDrop` shares one `DataTransfer` across the source's `dragstart` and the target's `dragover`/`drop`), since Playwright's mouse-based `dragTo` does not fire the HTML5 DnD events the handlers listen for.

Durability is pinned separately, because the pure model cannot see it:

- `backend/tests/test_user_ui_state.py` — the store: round-trip across a **cold cache** (the "survives a restart" property), per-user isolation, an explicit empty set persisting, malformed/duplicate/oversized input degrading rather than raising, a corrupt file degrading to empty, unrelated keys preserved on write, atomic write leaving no temp file, and an out-of-band edit being picked up.
- `backend/tests/test_chat_tabs_settings_router.py` — the routes: round-trip, normalization/caps as the authoritative post-write state, explicit clear, per-user scoping, and an email-shaped identity not breaking per-user path resolution.
- `frontend/tests/unit/core/threads/chat-tabs-persistence.dom.test.tsx` — the provider's boot path: the gateway-offline boot and the `…anonymous → …default` storage-key flip never blanking the stored set, adopt-from-server on an empty browser, **unreachable gateway keeping the local cache**, seed-the-server from a local cache when the server has none, and mutations being pushed (including an explicit clear) with the debounced write flushed on teardown.

**Verify it works.**

```bash
cd frontend && pnpm test chat-tabs        # pure model + the boot-path/durability DOM tests
cd frontend && pnpm test:e2e chat-tabs    # real DnD from the sidebar + reorder + keep-alive + persistence
cd backend && uv run pytest tests/test_user_ui_state.py tests/test_chat_tabs_settings_router.py
```

Then end-to-end (`make dev` → land on a new chat): the empty tab strip with its drop hint is already visible; drag a sidebar conversation onto it (or use its **Open in tab** menu) → it becomes a tab and the hint disappears; open a second; switch between them and confirm the background chat keeps its scroll and stream (both instances stay in the DOM, only the active one is visible); drag one chip onto another to reorder; close a chip; reload and confirm the tabs come back. Full frontend gate: `pnpm format && pnpm check && pnpm test`.

### 10. Currency spend caps (`spend_budget`)

§7 made cost **visible**. This makes it **bounded**: a cap in real money over a
day, week, or month, in whatever single currency your `models[*].pricing` blocks
use.

Upstream's `token_budget` does not fill this hole. It is per-run and counted in
tokens, and in a fork whose premise is mixing Opus, Haiku and free local Ollama
in one session a token is not a unit of cost — 200k tokens is $5 or $0 depending
on which model burned them. So `spend_budget` mirrors `token_budget`'s shape
(`enabled`, limits, `warn_threshold`, `hard_stop_threshold`) and changes the
unit:

```yaml
spend_budget:
  enabled: true
  daily_limit: 5.00        # in the pricing currency
  weekly_limit: 25.00
  monthly_limit: 80.00
  window: rolling          # or `calendar` (since local midnight / Monday / the 1st)
  tz_offset_minutes: 0     # local offset for `calendar` boundaries
  warn_threshold: 0.8
  hard_stop_threshold: 1.0
```

- **Two enforcement points, one number.** At **run admission** the Gateway sums
  the window and refuses a new run with **HTTP 402** when a cap is already spent
  (`Spend budget exhausted: the daily cap of 5 USD is already at 5.12 USD…`).
  **During a run**, `SpendBudgetMiddleware` — modelled directly on
  `TokenBudgetMiddleware` — injects an in-context warning at `warn_threshold` and
  at `hard_stop_threshold` strips tool calls so the agent produces a final answer
  from what it has. It never raises; a budget stop is an orderly wrap-up. The
  admission check also hands the run its window **baseline**, and the middleware
  adds the live run's own spend on top, so one long run cannot blow through a cap
  it started just under.
- **Billed per model, so the fork's own lever shows up.** In-run spend is read
  from the `RunJournal`'s live per-model accumulator (a new
  `current_token_usage_by_model()`), which already folds subagent usage in by
  model. A premium lead with Haiku or local subagents is therefore billed
  Opus-for-Opus and Haiku-for-Haiku, exactly like the header. Without that, a
  cheap subagent would be billed at the lead's rate and a cap would fire early on
  precisely the configuration this fork recommends.
- **Unpriced models cost 0, so a local run is never blocked.** This is a hard
  requirement, not a side effect of a sparse pricing map: the whole point of
  local models is that they are free, and a spend cap that stops a fully local
  session would break the fork's central promise.
- **What counts.** Persisted run costs **plus** the durable memory/suggestions
  counters from §7 — those are real money and would otherwise be invisible to a
  budget. Both are priced through the one shared pricing module.
- **It self-disables rather than guessing.** With **no model priced**, a currency
  budget has nothing to measure, so the feature turns itself off with a reason
  instead of enforcing a cap against a permanent `0` (which would never fire) or
  against nothing (which would block everything). Same for
  `database.backend: memory`, which keeps no spend history to measure a window
  against. `make doctor`'s **`spend budget`** check names whichever applies, and
  the agent build logs a warning. `enabled: true` with no limit set is a config
  error and fails loudly at load — turning the feature on and configuring nothing
  to enforce is a mistake, not a preference.
- **Where it shows.** The header cost dropdown gains a **Budget left** line for
  the window with the least headroom (green → amber past the warn threshold →
  red once spent), plus an explicit note when the cap is reached. Only the
  tightest window is shown; three rows of headroom is noise.

**Where it's wired.**

| Piece | Location |
| --- | --- |
| Config | `deerflow/config/spend_budget_config.py` (`SpendBudgetConfig`, `SpendLimit`), `spend_budget:` block in `config.example.yaml`, `AppConfig.spend_budget` |
| Window math | `deerflow/runtime/spend_window.py` (`resolve_window_start`, rolling vs. calendar) |
| Accounting + admission | `backend/app/gateway/spend_budget.py` (`resolve_spend_budget_status`, `SpendBudgetStatus`, `exhausted_message`); the 402 and the baseline injection live in `app/gateway/services.py::start_run` |
| In-run enforcement | `deerflow/agents/middlewares/spend_budget_middleware.py`, appended in `agents/lead_agent/agent.py` after `TokenBudgetMiddleware` |
| Live per-model usage | `deerflow/runtime/journal.py::RunJournal.current_token_usage_by_model()` |
| Pricing | `deerflow/pricing.py` — **moved out of `app/gateway/pricing.py`** so the in-graph middleware can price without importing `app.*` (the harness boundary). `app/gateway/pricing.py` is now a re-export shim, so every existing importer is unchanged |
| Header line | `GET /api/threads/{id}/token-usage` → `spend_budget`; `core/threads/token-usage.ts::threadTokenUsageToSpendBudget`; `components/workspace/token-usage-indicator.tsx` |
| Diagnostic | `scripts/doctor.py::check_spend_budget` |

**Verify it works.**

```bash
cd backend && uv run pytest tests/test_spend_budget_config.py tests/test_spend_budget.py tests/test_spend_budget_middleware.py
cd backend && uv run pytest tests/blocking_io/test_aux_usage.py   # the window read stays off the event loop
cd backend && uv run pytest tests/test_doctor.py -k spend_budget
cd frontend && pnpm test token-usage                               # the header's budget line
make doctor                                                        # 'spend budget' names why a cap is not enforced
```

Then in the browser (`make dev`): set `spend_budget.enabled: true` with a
deliberately tiny `daily_limit` (say `0.01`), run a turn on a **priced** model,
and the header dropdown's **Budget left** goes red; the next message is refused
with the 402 message. Set the limit back, switch the thread to a **local Ollama**
model, and confirm the same tiny cap never blocks it — that is the rule the whole
feature is built around.

### 11. Spend history and attribution (`/workspace/spend`)

The header answers "what is this conversation costing". This answers the question
a person actually asks at the end of a month. A new workspace page beside
`/workspace/scheduled-tasks` reports one window three ways:

- **By feature** — conversation vs. memory vs. suggestions, so the two
  off-by-default background features from §7 are finally accountable in a
  cross-thread view rather than only per thread.
- **By model** — most expensive first, with unpriced models sorted **last** and
  labelled, never as if they were the cheapest.
- **By conversation** — with thread titles, so an expensive chat is identifiable.

Windows are 7 / 30 / 90 days. The three groupings are derived from the same
priced rows, so their totals agree — pinned by a test that asserts exactly that.

- **No second cost calculation.** The endpoint reuses `pricing.py` end to end
  (`run_cost` for runs, `token_cost` for the auxiliary sinks), so a model can
  never be billed differently here than in the chat header.
- **Unpriced models are named.** When nothing is priced the page says so and why;
  when only some models are, it names the ones missing a price and warns that the
  real cost is higher — the same rule the header follows, for the same reason (a
  quietly low total is indistinguishable from a broken feature).
- **Token counts work before pricing does**, so the page is useful on a config
  with no `pricing:` blocks at all.

**Where it's wired.**

| Piece | Location |
| --- | --- |
| Endpoint | `GET /api/console/spend?days=N` in `backend/app/gateway/routers/console.py` (`ConsoleSpendResponse`) |
| Auxiliary range read | `deerflow/runtime/aux_usage_store.py::AuxUsageStore.aggregate(since, until, thread_ids)` — the time-sliceable read the append-only `recorded_at` row shape was added for in §7 |
| Frontend client | `frontend/src/core/spend/{api,hooks,types}.ts` |
| Page + nav | `frontend/src/app/workspace/spend/page.tsx`, entry in `components/workspace/workspace-nav-chat-list.tsx`, i18n `spend.*` |

**Verify it works.**

```bash
cd backend && uv run pytest tests/test_console_router.py -k ConsoleSpend
cd frontend && pnpm check && pnpm test
```

Then in the browser (`make dev`): open **Spend** in the sidebar. With pricing
configured the three tables agree with the summary total; switch the window and
the figures move. On a config with no prices the tables still show tokens and the
page explains why there is no cost.

### Note: the "older messages disappear in long conversations" investigation

The request that shipped this cost feature also asked to fix messages vanishing from long conversations. Findings, so the next pass has a head start:

- **Trigger.** `summarization.enabled: true` is the default. In a long thread, context summarization periodically compacts older turns out of the model's *active context* with `RemoveMessage(ALL)` + a hidden summary + a retained tail. That compaction is what makes older turns flicker out of the live view.
- **Why it's not (usually) permanent.** The *visible* transcript is not the checkpoint's `messages` channel — it is the run-event feed, read back by `GET /api/threads/{id}/messages/page`. Summarization rewrites the checkpoint, not the run-event feed, so the full history is still there and a page reload (or scrolling up, which cursor-paginates all the way back) reloads it. The backend page scan is well-guarded (it raises rather than silently stopping on a non-advancing cursor).
- **The existing mitigation.** During a live session, before the run-event refetch catches up, the frontend keeps a **transient history bridge** + a **rendered-message ledger** (`core/threads/hooks.ts`, issue #3825 and follow-ups #4380/#4458/#4531) that overlay the just-removed turns so they don't blink out. This is exactly the anti-loss machinery, and it has been iterated on many times.
- **Why this pass did not change it.** Without a concrete reproduction, editing that resolver — some of the most intricate, most-fixed code in the repo — risks regressing prior fixes for more than it would gain. The safe, honest call was to diagnose rather than speculatively rewrite. If loss persists **after a reload** (i.e. it is not just the transient live glitch), that points at the run-event feed itself and is a different, higher-severity bug worth capturing a reproduction for (thread id + roughly when the turns vanished).

## Why mix local and cloud

Each tier of model has a job it's good at. Mixing them is how you get most of the quality of frontier models at a fraction of the cost:

- **Lead agent (cloud, premium):** plans, decomposes, judges. The lead writes the prompts that everything else executes. Worth spending tokens here — bad planning wastes downstream compute regardless of subagent quality.
- **Subagents (cheap, parallelizable):** classification, extraction, file edits, web fetches, repetitive code patches. Often called dozens of times per lead turn. This is where cost compounds.
- **Local (Ollama):** zero marginal cost, full data privacy. Slower than cloud and weaker on long-horizon reasoning, but excellent for bulk subagent fan-out on a workstation that's already turned on.

Anthropic's own framing ([Haiku 4.5 announcement](https://www.anthropic.com/news/claude-haiku-4-5)): *"Sonnet can break down a complex problem into multi-step plans, then orchestrate a team of multiple Haikus to complete subtasks in parallel."* This fork makes that pattern (and the local-model variant) selectable from the UI.

## Cost story

Anthropic API pricing as of May 2026 (per million tokens, input / output):

| Model           | Input  | Output |
| --------------- | ------ | ------ |
| Opus 4.7        | $5.00  | $25.00 |
| Sonnet 4.6      | $3.00  | $15.00 |
| Haiku 4.5       | $1.00  | $5.00  |
| Local (Ollama)  | $0     | $0     |

Subagent fan-out is where mixing models pays off. A typical research/coding task spends a large share of its token budget in `task` delegations — easily 60–80% of total tokens.

**Worked example** — assume 100M input + 20M output tokens of total work in a session, with 70% in subagents:

| Configuration                       | Lead cost          | Subagent cost      | Total     |
| ----------------------------------- | ------------------ | ------------------ | --------- |
| All Sonnet 4.6                      | $0.40 (lead share) | $7.10              | **$7.50** |
| Sonnet lead + Haiku subagents       | $0.40              | $2.37              | **$2.77** |
| Sonnet lead + local Ollama subagents | $0.40              | $0                 | **$0.40** |
| All local                           | $0                 | $0                 | **$0**    |

Mixed Sonnet/Haiku saves ~63% over pure Sonnet. Sonnet/local saves ~95% — at the cost of subagent quality you should benchmark on your actual tasks.

> Numbers are illustrative. Real ratios depend on prompt cache hit rate, batch API usage, and the share of the prompt that's static system context. The point is that the **cost surface is highly elastic in the subagent model choice**, and that's the lever this fork exposes in one click.

## Setup notes (Arch / CachyOS specifics)

- **nginx temp paths.** Arch packages nginx with `/var/lib/nginx` (root-owned) compiled in as default temp paths, which makes upstream's `make dev` fail for non-root users. This fork patches `docker/nginx/nginx.local.conf` to use relative `.deer-flow/nginx-tmp/` paths, and the `dev:` target creates that directory. No action needed.

- **`langchain-ollama`.** Required for synced Ollama entries to actually load. This fork adds it to `backend/pyproject.toml`. If you clone fresh, `make install` picks it up automatically.

- **Pre-commit hook.** Upstream installs a `pre-commit` hook that lives in `backend/.venv/bin/pre-commit`. If you commit from outside the venv, it fails with `pre-commit not found`. Fix once:
  ```fish
  mkdir -p ~/.local/bin
  ln -sf /home/<you>/deer-flow/backend/.venv/bin/pre-commit ~/.local/bin/pre-commit
  fish_add_path ~/.local/bin
  ```

- **Root-owned files from the DooD sandbox.** In Docker DooD mode the gateway container is host-root-equivalent and writes into host-mounted dirs **as root**. Over time `backend/.deer-flow/` (per-user integrations/uploads/backups) and, if a container ever created it, `backend/.venv/` end up owned by `root`, which then breaks host-side commands run as your normal user. Two symptoms and their fixes:
  - **`make config-upgrade` / `make sandbox-enable` fail** with `Failed to query Python interpreter … failed to canonicalize path backend/.venv/bin/python3: Permission denied (os error 13)`. The venv is root-owned. Fix: `sudo chown -R "$USER":"$USER" backend/.venv` (or delete it and let `make install` rebuild it).
  - **`make docker-start` fails during "load build context"** with `error from sender: open …/backend/.deer-flow/…: permission denied`. The build context sender can't read the root-owned runtime tree. This is now prevented at the source — the repo-root `.dockerignore` excludes `.deer-flow/` (and `**/.deer-flow/`), so the build never reads it (pinned by `backend/tests/test_dockerignore_deer_flow.py`). If you still hit it on an older checkout, either add those patterns or `sudo chown -R "$USER":"$USER" backend/.deer-flow`.
  - General remedy for either: `sudo chown -R "$USER":"$USER" .deer-flow backend/.deer-flow backend/.venv`. Running the local (non-Docker) `make dev` avoids creating root-owned files in the first place.

## Upstream sync

Pull upstream changes into this fork with:

```bash
git fetch upstream
git merge upstream/main      # merge, not rebase — see below
```

The fork's added files (`scripts/sync-ollama-models.py`, `scripts/sync-api-key-models.py`, `scripts/ensure_camoufox.py`, the input-box dropdown JSX, the `suggestions-settings-page.tsx` + its `settings-dialog.tsx` section, the task_tool.py override) are unlikely to conflict with upstream changes since they're either new files or additive blocks on stable anchors. The launch-script hooks (Ollama sync + API-key model auto-config + Camoufox fetch in `scripts/serve.sh`, `scripts/docker.sh`, `scripts/deploy.sh`, `docker/dev-entrypoint.sh`, `backend/Dockerfile`) are additive blocks on stable anchors. The auto-config's model definitions live in `config.example.yaml` (the `auto-model-config` marker blocks) and `scripts/wizard/providers.py`; if upstream restructures `task_tool.py`, `input-box.tsx`, or those launch scripts, expect a small merge.

**Merge, not rebase.** This is a long-lived, published fork whose `main` carries its own merge commits and merged PRs, so a sync is a `git merge upstream/main` — never a rebase, which would rewrite that public history, orphan the merged-PR refs, and force every overlapping-file conflict to be re-resolved commit-by-commit. Merge resolves each conflict once and keeps a clean "fork vs. upstream" audit trail.

### Post-sync feature checklist

After every upstream merge, run this checklist before pushing — passing unit tests do not prove the fork's *UI wiring* or *launch-time scripts* survived a large merge. Root commands run from the repo root; backend commands from `backend/`.

First, the mechanical gates:

- [ ] No leftover conflict markers: `git grep -nE '^(<{7}|={7}|>{7})( |$)'` returns nothing.
- [ ] Backend: `make lint && make test` (CI enforces `ruff format --check`).
- [ ] Frontend: `pnpm format && pnpm check && pnpm test`. **Watch the formatting gate:** `pnpm check` is only `eslint` + `tsc --noEmit` — it does **not** run Prettier, but CI's `lint-frontend` job (`.github/workflows/lint-check.yml`) runs `pnpm format` (`prettier --check .`) as its own step. So a change that is eslint/type-clean can still fail CI on formatting alone; always run `pnpm format` (or fix with `pnpm format:write`) before pushing. `eslint --fix` normalizes imports/optional-chains but not Prettier whitespace.
- [ ] `backend/uv.lock` reconciled: `cd backend && uv lock` (must include every fork extra — `camoufox`, `ollama`, `pymupdf` — alongside upstream's).
- [ ] Config schema in step: if the merge (or your own change) touched `config.example.yaml`'s **shape**, `config_version` is bumped and `make config-upgrade` merges the new keys into an existing `config.yaml` without clobbering hand edits. An existing install never gets a new section otherwise — the same delivery trap the pricing blocks hit (see the cost-overview row below).
- [ ] Model list still current: run the **[Auditing the model list](#auditing-the-model-list-settings--pricing)** pass (or confirm it ran recently). Provider model ids, prices, and promos drift *independently* of upstream DeerFlow, so a sync is only the calendar checkpoint — the audit itself must read each slug/price off the **provider's own page** (`scripts/sync-api-key-models.py --dry-run` and the model-format tests below do **not** catch a stale-but-well-formed price or a since-renamed slug, because both pass against any syntactically valid entry). Regression-gate whatever you change with `python3 scripts/sync-api-key-models.py --dry-run` + `cd backend && uv run pytest tests/test_sync_api_key_models.py tests/test_setup_wizard.py tests/test_config_integrity.py`.

Then confirm each fork feature end-to-end:

| Fork feature | How to verify it survived the merge |
| --- | --- |
| **Ollama auto-populate** (§1) | `python3 scripts/sync-ollama-models.py --dry-run --verbose` — proposes entries when the daemon is up, prints `unreachable; skipping (no changes)` and exits 0 when it's down. Reconciliation logic is pinned by `backend/tests/test_sync_ollama_models.py`. |
| **API-key model auto-config** (§2) | On a *copy* of `config.example.yaml`: `ANTHROPIC_API_KEY=sk-ant-… python3 scripts/sync-api-key-models.py --config <copy> --dry-run --verbose` logs `enabled 'anthropic' model block`; with an empty env the file stays byte-identical. Pinned by `backend/tests/test_sync_api_key_models.py`. All eleven `# === BEGIN/END auto-model-config: <provider> ===` marker blocks (anthropic, openrouter, and the nine first-party home blocks: openai, xai, google, deepseek, mistral, moonshot, qwen, minimax, zai) must still be present in `config.example.yaml`, each in sync with its `*_BUNDLE_MODELS` list in `scripts/wizard/providers.py` (`HOME_API_BUNDLES` registry) and its `PROVIDERS` entry in `scripts/sync-api-key-models.py`. |
| **Per-thread subagent model override** (§3, Ultra mode) | `input-box.tsx` renders the second "Subagent" `ModelSelector` only under `context.mode === "ultra"`, defaulting to "Follow lead", dimming `lacksToolSupport` models. It sets `subagent_model_name` in thread context; `_CONTEXT_CONFIGURABLE_KEYS` (`app/gateway/services.py`) forwards it; `task_tool.py` applies it as `model_override` and passes it to `SubagentExecutor`. Backend plumbing pinned by `backend/tests/test_task_tool_core_logic.py::test_task_tool_uses_subagent_model_override_for_tool_loading`. |
| **Follow-up suggestions off by default + model picker** (§4) | `core/settings/local.ts` defaults `suggestions.enabled=false`; Settings → Suggestions page writes `suggestions.{enabled,modelName}`; `input-box.tsx` gates on `suggestionsConfig?.enabled && localSettings.suggestions.enabled` and sends `n: maxFollowupSuggestions`, `model_name: suggestionsModelName ?? context.model_name`. The backend endpoint's `model_name` override is pinned by `backend/tests/test_suggestions_router.py`. |
| **Memory toggle (off by default)** | `core/settings/local.ts` defaults `memory.enabled=false`; Settings → Memory page writes it; `core/threads/hooks.ts` sends `memory_enabled` in run context; `agents/lead_agent/agent.py::_apply_memory_preference` consumes it (operator `memory.enabled: false` still wins). Frontend defaults pinned by `frontend/tests/unit/core/settings/local.test.ts`; the backend `_apply_memory_preference` behavior (override-false disables injection/extraction/tools; operator config still wins) by `backend/tests/test_lead_agent_memory_toggle.py`. |
| **Camoufox default `web_fetch`** | `config.example.yaml` web_fetch entry has `backend: camoufox`; `scripts/detect_uv_extras.py` emits `--extra camoufox` for it (pinned by `test_detect_uv_extras.py`). The dispatcher's code-level default — a `web_fetch` entry with no `backend:` key still routes to camoufox — is pinned by `backend/tests/test_web_fetch_dispatcher.py`; the browser auto-install by `backend/tests/test_ensure_camoufox.py` + `test_camoufox_fetch.py`. |
| **SearXNG default `web_search`** | active `web_search` tool uses `deerflow.community.searxng.tools:web_search_tool`; `scripts/detect_searxng.py` still resolves it (resolution pinned by `backend/tests/test_detect_searxng.py`). |
| **Camoufox + SearXNG auto-update** (see *Automatic updates*) | `scripts/update_camoufox_searxng.py` refreshes both; `scripts/searxng.sh` has an `update` subcommand (pull + recreate-if-running); `scripts/serve.sh` runs the updater `--if-stale 24` in the background (opt out `DEER_FLOW_AUTO_UPDATE=0`); `scripts/install_auto_update.py` + `make auto-update{,-install,-uninstall}` manage the daily `systemd --user` timer. Pinned by `backend/tests/test_update_camoufox_searxng.py`, `test_install_auto_update.py`, `test_searxng_update_script.py`. If upstream restructures `scripts/serve.sh`, re-add the throttled background `--if-stale` hook after the SearXNG block. |
| **PDF/Office conversion** | `pymupdf` extra (`pymupdf4llm`) present in `backend/packages/harness/pyproject.toml`. The feature stays off by default, and the converted-Markdown companion write (distinct names for multiple convertibles, never clobbering a same-request user `.md`) is pinned by `backend/tests/test_uploads_router.py` (`test_upload_files_does_not_auto_convert_documents_by_default`, `test_upload_files_two_convertibles_get_distinct_markdown_companions`, `test_upload_files_converted_markdown_does_not_overwrite_user_markdown`). |
| **Reduce animations (default on)** | `core/appearance` (`useReducedMotion`) + `components/reduce-motion-effect.tsx`; default pinned by `local.test.ts`. |
| **Full sandbox runs** | `skills/public/repo-runner/`; `sandbox.expose_ports` / `extra_capabilities` in `config.example.yaml` and honored by `LocalContainerBackend`. The container-sandbox default (chosen when a Docker/Apple Container runtime is present, even non-interactively) and per-thread container mode are pinned by `backend/tests/test_configure_script.py` + `test_docker_sandbox_mode_detection.py`; the enable/disable toggle by `test_sandbox_toggle.py`; the forwarded `bash_command_timeout` by `test_local_sandbox_command_timeout.py`. |
| **First-run config seeding** | `scripts/serve.sh::seed_missing_config` (and the equivalents in `deploy.sh` / `docker.sh`). Pinned by `backend/tests/test_serve_config_seed.py` (seeds `config.yaml` + companion config files on first run). |
| **Passwordless by default** (§5) | `scripts/serve.sh::apply_default_auth_mode` exports `DEER_FLOW_AUTH_DISABLED="${DEER_FLOW_AUTH_DISABLED:-1}"` after loading `.env` (pinned by `backend/tests/test_serve_auth_default.py`); both `.env.example` files document the `=0` opt-out. Backend honors it via `auth_disabled.py`, frontend via `core/auth/auth-disabled-user.ts` (both ignore it when `DEER_FLOW_ENV`/`ENVIRONMENT` is prod). |
| **Dev-origin defaults (§5, LAN/Tailscale)** | `frontend/src/dev-origins.js::getAllowedDevOrigins()` returns `DEFAULT_DEV_ORIGIN_PATTERNS` (private-LAN + Tailscale) merged with `DEER_FLOW_DEV_ALLOWED_ORIGINS`, unless `DEER_FLOW_DEV_ALLOWED_ORIGINS_STRICT`; wired in `next.config.js`. Pinned by `frontend/tests/unit/dev-origins.test.ts` (runs the defaults through Next's real `isCsrfOriginAllowed` matcher). |
| **Multi-user mode toggle** (§6) | `deerflow/config/runtime_settings.py` (`is_multi_user_mode_enabled` / `set_multi_user_mode` / `resolve_owner_scope`, default ON) gates `thread_meta` `search`/`get`/`check_access` and run-store read helpers (writes keep the real owner); `GET`/`PUT /api/settings/multi-user-mode` (`app/gateway/routers/settings.py`, PUT admin-gated). Frontend toggle + confirm dialog in `account-settings-page.tsx` via `core/settings/multi-user-mode.ts`. Pinned by `backend/tests/test_multi_user_mode.py` + `frontend/tests/unit/core/settings/multi-user-mode.test.ts`. |
| **Cost overview + aux counters** (§7) | Shared `app/gateway/pricing.py` (console + thread endpoint import it); `GET /api/threads/{id}/token-usage` returns `total_cost`/`promo_total_cost`/`currency`/per-model `cost`/`aux`; store aggregation carries the input/output/cache-read split (`new_by_model_usage_entry`); `deerflow/runtime/aux_usage.py` records memory (`agents/memory/manager.py::_host_default_extraction_callback`) + suggestions (`utils/oneshot_llm.py::run_oneshot_llm_with_usage`), **write-through to the durable `deerflow/runtime/aux_usage_store.py`** (`<DeerFlow home>/aux_usage.sqlite3`, kill switch `DEER_FLOW_AUX_USAGE_DB=0`). Frontend `token-usage-indicator.tsx` + `core/threads/token-usage.ts`. Pinned by `backend/tests/test_pricing.py`, `test_aux_usage.py`, `test_aux_usage_wiring.py`, `test_thread_token_usage.py`, `tests/blocking_io/test_aux_usage.py` + `frontend/tests/unit/core/threads/token-usage.test.ts`. **The aux registry's store is a local file, so its sync API blocks.** If upstream (or a refactor) re-points the suggestions route or the `token-usage` endpoint at `record_aux_usage` / `get_thread_aux_usage` instead of the `a*` wrappers, the strict Blockbuster anchor fails — do not "fix" it by marking the anchor `allow_blocking_io`; restore the offload. Equally, do not make the memory path async: it runs on the memory updater's loop-less debounce thread, which is the whole reason the durable store is a dedicated SQLite file rather than the async runs engine. **Two things make this render `—`, and neither raises an error.** (1) The provider-id resolution (`pricing.py::_pricing_lookup_candidates`): buckets are keyed by the *provider-reported* model id, not the `config.yaml` id, so exact-only matching nulls every cost — pinned by `test_thread_token_usage.py::test_thread_token_usage_prices_provider_reported_model_ids`. (2) A bundled model with no `pricing:` block contributes nothing, so a run on unpriced models reports no cost — pinned by `test_config_integrity.py::TestBundledModelPricing`, which fails if any bundled model loses its price or the two synced sources disagree. **The second one has a delivery trap worth reading twice:** fixing `config.example.yaml` does **not** fix an existing install. `sync-api-key-models.py` skips already-active provider blocks and `config_upgrade.py`'s `merge_missing` cannot add a key inside a list entry, so a config written before a price shipped keeps that model active and unpriced forever. That is why `pricing.py` derives the price from the `($in/out)` pair in `display_name` when no block is configured, and why `test_every_bundled_model_prices_without_its_pricing_block` requires every bundled model to survive with its block stripped. **Any future change to the bundled model blocks must answer the same question: does this reach a config that already exists?** `make doctor`'s `model pricing` check is the user-facing version — it warns, with the `—` symptom named, when nothing configured can be priced. **A third failure is silent rather than visible:** an *expired* promo. `promo_*_per_million` and the starred `($list → $promo*)` name are two spellings of one discount, so updating only one leaves the header advertising a price nobody is getting — pinned in both directions by `TestBundledModelPricing::test_promo_price_matches_the_starred_pair_in_the_name` (starred name with no promo block, promo block with no starred name, and a promo at or above list). Re-verify the live promos as part of step 4 of the [model audit](#auditing-the-model-list-settings--pricing); the test only checks the two sources agree with each other, never that the discount is still running. Cost is **per model everywhere**, including the promo: run buckets, and the memory/suggestions `aux` sinks, are each priced at their own model's rate, so an Ultra run with a discounted subagent and a full-price lead discounts only the subagent's tokens (`test_promo_total_is_model_aware_across_lead_subagent_and_aux`). Manual: run a turn (ideally Ultra mode, so a subagent model is involved too) and confirm the header shows a **green** dollar amount; on a discounted model the dropdown shows the green promo total beside the red standard one; if it shows `—`, the dropdown now names the unpriced model. |
| **Model dropdown sorting/grouping** (§8) | `cd frontend && pnpm test sorting` exercises the parse/sort/group logic (`frontend/tests/unit/core/models/sorting.test.ts`). Wiring: `core/models/sorting.ts` (`parseModelPrice` promo-aware, `parseModelProvider`, `sortModels`, `groupModelsByProvider`, `demoteLast`); preference `modelPicker` in `core/settings/local.ts`; shared UI `components/workspace/model-picker-controls.tsx` (`ModelPickerControls` + `ModelPickerList` + `ModelDisplayName`) used by the lead + subagent pickers in `input-box.tsx` and the sidecar picker in `sidecar/sidecar-panel.tsx`; i18n keys in `core/i18n/locales/{en-US,zh-CN}.ts`. Manual: open the model dropdown → Sort (Default/Name/Price) + direction toggle + Group-by-provider switch appear and reorder/group the list; every row's price renders green, and a discounted entry (MiniMax M3, GLM-5.2, Claude Sonnet 5) shows its red list price beside the green promo. If a whole model name turns green or a price stays uncoloured, `splitModelNamePriceSegments` has drifted from the name format — its reassembly test is the fast check. Then **close** the dropdown on a discounted model and confirm the collapsed trigger still shows both prices at a narrow window width; if it clips, the `w-full` on the three `ModelSelectorName` triggers has been dropped (see §8 — without it the span is `fit-content` inside a `flex-col items-start` and overflows the capped button instead of truncating). This half is CSS with no unit test, so it needs the manual look. |
| **Durable chat tabs** (§9) | `cd backend && uv run pytest tests/test_user_ui_state.py tests/test_chat_tabs_settings_router.py` covers the per-user store (`deerflow/config/user_ui_state.py`, `{base_dir}/users/{user_id}/ui_state.json`) and `GET`/`PUT /api/settings/chat-tabs` (caller-scoped, **no admin gate** — unlike the multi-user-mode routes in the same router). `frontend/tests/unit/core/threads/chat-tabs-persistence.dom.test.tsx` covers the provider's boot path. If upstream restructures `workspace/layout.tsx`'s gateway-offline branch, re-check that an unreachable gateway still **keeps** the local cache instead of blanking the strip (`fetchChatTabs` returns `null` for "unknown", never `[]`), and that a server with no stored set still adopts and seeds from the local cache — that is the upgrade path for tabs pinned before server persistence existed. Manual: pin a tab, restart the stack, hard-reload with site data cleared, and confirm the tabs come back. |
| **Keep-alive chat tabs** (§9) | `cd frontend && pnpm test chat-tabs` exercises the pure model (`frontend/tests/unit/core/threads/chat-tabs.test.ts`); `pnpm test:e2e chat-tabs` (`frontend/tests/e2e/chat-tabs.spec.ts`) covers drag-from-sidebar onto the empty strip / drag-reorder between chips / open-as-tab / keep-alive switch (both instances stay mounted) / close / reload persistence. Wiring: the live chat is `components/workspace/chats/chat-instance.tsx` (**fully controlled**, own provider stack via `chat-providers.tsx` with a per-instance `storageScope`); `keep-alive-chat-viewport.tsx` is mounted in `workspace-content.tsx` **above** the route inside `ChatTabsProvider` and renders one instance per slot (only the active shown, the rest `display:none`); the tab strip is `chat-tabs-bar.tsx`, which **always renders as a drop zone on chat routes** (an empty-state hint `chatTabs.dropHint` when there are no tabs yet but threads exist, so there is somewhere to drag onto — returning `null` here is the "tabs don't work" bug); `[thread_id]/page.tsx` is a thin registrar in app builds and the classic inline `<ChatInstance>` in static-demo; pure model + persistence in `core/threads/chat-tabs.ts`, state in `chat-tabs-context.tsx`; sidebar drag + **Open in tab** in `recent-chat-list.tsx`; `ChatBox` panel ids keyed by thread id (not pathname). **If upstream restructures `[thread_id]/page.tsx`,** re-extract its body onto `chat-instance.tsx` and keep the registrar/classic split; watch for a barrel (`components/workspace/chats/index.ts`) import of the client viewport into the server `workspace-content.tsx` (import the file directly to keep the `"use client"` boundary). |
| **Currency spend caps** (§10) | `cd backend && uv run pytest tests/test_spend_budget_config.py tests/test_spend_budget.py tests/test_spend_budget_middleware.py` covers the config/window math, the window aggregation (runs + auxiliary counters, owner-scoped), and the in-run warn / hard stop. Wiring: `deerflow/config/spend_budget_config.py` + the `spend_budget:` block in `config.example.yaml`; `deerflow/runtime/spend_window.py`; `app/gateway/spend_budget.py`; the **HTTP 402** admission refusal and the `__spend_budget` baseline injection in `app/gateway/services.py::start_run`; `SpendBudgetMiddleware` appended in `agents/lead_agent/agent.py` after `TokenBudgetMiddleware`; `RunJournal.current_token_usage_by_model()`; `scripts/doctor.py::check_spend_budget`; the header line via `GET /api/threads/{id}/token-usage -> spend_budget` and `core/threads/token-usage.ts::threadTokenUsageToSpendBudget`. **The pricing module moved into the harness** (`deerflow/pricing.py`) because the in-graph middleware may not import `app.*`; `app/gateway/pricing.py` is a re-export shim, and `test_pricing.py::test_gateway_shim_re_exports_the_canonical_helpers` fails if it rots. **Three invariants that are easy to break and silent when broken:** (1) an unpriced model must contribute **0**, so a fully local run is never blocked — pinned by `TestLocalModelsAreFree` and `TestLocalRunsAreNeverBlocked`; (2) in-run spend must come from the journal's **per-model** accumulator, or a cheap subagent gets billed at the lead's rate and the cap fires early on exactly the setup this fork recommends (`test_a_cheap_subagent_is_billed_at_its_own_rate`); (3) with nothing priced the feature must **self-disable with a reason**, not enforce against a permanent zero (`TestSelfDisabling`). If upstream restructures `services.py::start_run`, re-add the admission check before `create_or_reject` and the baseline injection after `inject_authenticated_user_context` — the baseline key is `__`-prefixed precisely so `build_run_config` strips a caller-supplied copy. Manual: set a tiny `daily_limit`, run a turn on a priced model (header **Budget left** goes red, the next message 402s), then repeat on a local model and confirm it is never blocked. |
| **Spend history page** (§11) | `cd backend && uv run pytest tests/test_console_router.py -k ConsoleSpend` covers `GET /api/console/spend`: the three groupings (model / thread / feature) agreeing with the total, unpriced models named and sorted last, the window boundary, the no-pricing state, and the 503 on the memory backend. Wiring: `ConsoleSpendResponse` in `app/gateway/routers/console.py`; `AuxUsageStore.aggregate()`; `frontend/src/core/spend/*`; `frontend/src/app/workspace/spend/page.tsx`; the sidebar entry in `components/workspace/workspace-nav-chat-list.tsx`; i18n `spend.*` in both locales. The page must keep reusing `pricing.py` rather than recomputing cost — a second formula is how the page and the chat header start disagreeing about the same run. Manual: open **Spend** in the sidebar and confirm the tables' totals match the summary tile for the same window. |

**Integration points that tend to need a hand** (where upstream refactors collide with fork additions — check these first when tests fail): the AIO sandbox provider (upstream's cross-instance ownership store adds instance attributes that minimal test fixtures built via `__new__` must seed), the skills tool-policy path (upstream's dynamic `SkillToolPolicyMiddleware` vs. any fork static filtering — reconcile onto the middleware and drop dead build-time filters), `scripts/check.py`'s Docker diagnostics (any upstream test that mocks `run_command` with a strict dict must tolerate the extra `docker` calls), and the `task_tool.py` / `input-box.tsx` model-override plumbing.

For environments that cannot reach `github.com/bytedance/deer-flow` directly (e.g. network-restricted CI or sandboxed agents), the **Mirror Upstream** workflow (`.github/workflows/mirror-upstream.yml`, manual `workflow_dispatch`) fetches upstream `main` on a GitHub runner and publishes the delta as a git bundle on the `upstream-sync-data` branch of this fork. Fetch that branch, extract the bundle parts (`cat upstream-delta.bundle.part.* > upstream.bundle`), and `git fetch <bundle> upstream-main-mirror` to get full upstream history locally. (The workflow cannot push the mirrored branch directly: `GITHUB_TOKEN` is not allowed to create or update workflow files, and upstream regularly changes theirs.)

## PDF and Office document support

Upstream supports converting PDF, DOCX, PPTX, and XLSX uploads to Markdown so the agent can read them, but the dependency (`pymupdf4llm`) is not bundled and the feature is off by default. This fork:

- Adds `pymupdf4llm` as a backend dependency so PDFs convert out of the box.
- Writes the converted Markdown under **two filenames** — `<original>.md` (upstream behavior) **and** `<original>.<ext>.md` (e.g. `report.pdf.md`). Agents tend to hallucinate one convention or the other; writing both eliminates the "file not found" failure mode. Cleanup on delete handles both names.

To turn the feature on, set `uploads.auto_convert_documents: true` in your `config.yaml`. `config.yaml` is gitignored, so the toggle ships per-install rather than in the fork.

## Local Camoufox `web_fetch` backend

Upstream's `web_fetch` tool defaults to the `jina` cloud reader. This fork adds a pluggable dispatcher and a **local, key-less, JavaScript-capable** backend built on [Camoufox](https://github.com/daijro/camoufox) (a stealth Firefox), and **makes it the default** — the shipped `config.example.yaml` sets `backend: camoufox` under the `web_fetch` tool, and the dispatcher's code-level default is camoufox too, so a `web_fetch` entry that omits `backend` gets the local browser as well. Switch to the cloud reader with an explicit `backend: jina` (or `make config`).

Camoufox needs two things: the `camoufox` Python package **and** its browser binaries (a large one-time download). Because it is the default backend, both install **automatically on every launch path** — you never have to run `make fetch-browser` by hand:

- **Local** (`make dev` / `make start`, foreground or daemon): `scripts/serve.sh` auto-detects the `camoufox` uv extra from `config.yaml`, installs it, then runs `scripts/ensure_camoufox.py` to fetch the browser.
- **Docker dev** (`make docker-start`): `docker/dev-entrypoint.sh` runs the same `ensure_camoufox.py` after `uv sync`; the download persists in the `gateway-camoufox` volume across container recreation.
- **Docker prod** (`make up`): the browser is **baked into the image** at build time (`backend/Dockerfile` builder stage runs `camoufox fetch` when the extra is present) and copied into the runtime stage, so no runtime download is needed.

Every path is **idempotent and best-effort**: an already-present browser is a no-op (checked via camoufox's `version.json`), and a failed download (e.g. offline) never blocks startup — the tool then returns an actionable install hint at call time. `make fetch-browser` still works for a manual pre-download.

## Automatic updates (Camoufox + SearXNG)

The two components this repo installs *for itself* — the Camoufox browser binaries and the bundled SearXNG Docker image — did not self-update after their first install:

- **Camoufox** only ever *fetched when absent*. `scripts/ensure_camoufox.py` short-circuits the moment camoufox's `version.json` exists, so a newer browser build (for an updated `camoufox` package, or a re-published build for the pinned one) was never pulled after the first download.
- **SearXNG** runs `docker.io/searxng/searxng:latest`, but Docker only pulls `:latest` when the image is missing locally, so a long-running stack keeps whatever image it started with indefinitely — never picking up upstream SearXNG fixes.

This fork adds a single **daily auto-update loop** that closes both gaps.

**The updater** — `scripts/update_camoufox_searxng.py` (`make auto-update`):

- **Camoufox:** runs `camoufox fetch` *unconditionally* (not the ensure-only guard). `fetch` is itself version-aware — it compares the installed browser to the expected version and re-downloads only when they differ — so running it is the update, and a no-op when already current. Skipped entirely when the `camoufox` extra isn't installed (the web_fetch backend wasn't selected).
- **SearXNG:** `scripts/searxng.sh update` runs `docker compose pull searxng` (fetch the newest `:latest`) and then `up -d searxng` **only if the bundled container is currently running** (a live stack rolls onto the new image; an idle checkout just pre-fetches it for its next `up`). It only ever touches the repo's own `deer-flow-searxng` container — it's skipped when the `web_search` provider isn't SearXNG, when Docker is unavailable, or when `DEER_FLOW_SEARXNG_BASE_URL` points at a foreign instance you manage yourself.

Everything is **idempotent and best-effort**: an already-current component is a no-op, and any failure is logged, never raised, so a scheduled or launch-time run never wedges. Flags: `--dry-run`, `--verbose`, `--camoufox-only`, `--searxng-only`.

**Two ways it runs automatically:**

1. **On launch, throttled (zero setup).** `scripts/serve.sh` runs the updater with `--if-stale 24` in the **background** after starting services, so `make dev` / `make start` refresh both components at most once a day without ever blocking startup. A stamp file (`.deer-flow/auto-update.stamp`) enforces the once-a-day throttle. Opt out with `DEER_FLOW_AUTO_UPDATE=0`.
2. **A `systemd --user` timer (runs even when the app isn't launched — daily *and* on boot).** `make auto-update-install` writes `~/.config/systemd/user/deer-flow-auto-update.{service,timer}` and enables a timer that fires both once a day (`OnCalendar=daily`) and shortly after the machine boots (`OnBootSec=2min`), with `RandomizedDelaySec=1h` (spreads a fleet out so a shared reboot / power-outage recovery doesn't hammer the registries at once) and `Persistent=true` (a missed daily run catches up after downtime). The boot trigger is what makes it "run when the PC starts up": a machine that's powered off at the daily slot refreshes both components on its next boot instead of skipping a day. systemd is the idiomatic scheduler on this fork's Arch/CachyOS target, and a *user* timer needs no root. `make auto-update-uninstall` removes it. On a machine without `systemd --user` (macOS, non-systemd Linux), the installer prints the equivalent `cron` lines instead — a daily entry plus a `@reboot` entry for the on-boot run.

```bash
make auto-update             # update both now (idempotent; no-op when current)
make auto-update-install     # install + enable the systemd --user timer (daily + on boot)
make auto-update-uninstall   # stop + disable + remove the timer
systemctl --user list-timers deer-flow-auto-update.timer   # inspect it
# `loginctl enable-linger` runs the boot + daily timer even while you're logged out.
```

Pinned by `backend/tests/test_update_camoufox_searxng.py` (camoufox present/absent, the SearXNG ownership decision matrix, docker-unavailable, dry-run, the `--if-stale` throttle, and `main()` wiring), `backend/tests/test_install_auto_update.py` (the systemd unit / cron content), and `backend/tests/test_searxng_update_script.py` (the `searxng.sh update` pull + recreate-if-running shell path).

## Full sandbox runs (clone a repo and run/debug it)

This fork rounds out the containerized AIO sandbox into a first-class "hand it a GitHub link, watch it clone, install, and debug the program" workflow. Everything here builds on upstream's `AioSandboxProvider` (root inside the container, private-repo clone via a forwarded `GITHUB_TOKEN`); the fork adds the ergonomics that were missing:

- **One-command per-thread container mode.** `make sandbox-enable MODE=container` writes an `AioSandboxProvider` block **without** a `base_url`, so DeerFlow spawns one container per thread and mounts that thread's user-data dirs. Unlike the shared external container (`make sandbox-up`), `/mnt/user-data` is host-backed, so uploads, outputs, and `present_files` all work. `make sandbox-enable` (no MODE) still writes the external block. The container block pins `image: ghcr.io/agent-infra/sandbox:1.11.0` — the same working image `docker/docker-compose.sandbox.yml` uses — so per-thread mode does not fall back to the provider's broken `:latest` default (which lacks the `/v1/bash/*` routes); `make config` (`scripts/configure.py`) and `make setup` write the same pinned block.
- **AIO is the default install when Docker is present.** `make config` (`scripts/configure.py`) and `make setup` both default to this container sandbox whenever a Docker/Apple Container runtime is detected — non-interactively too — falling back to the local sandbox only when no runtime exists. So a fresh clone with Docker installed lands on the containerized AIO sandbox out of the box; `make sandbox-disable` reverts to the local sandbox in one command.
- **Timeouts that survive real installs.** `sandbox.bash_command_timeout` is now forwarded to the AIO sandbox per command (idle timeout on the shell path, wall-clock hard timeout on the env-bearing path), not just to the host-local sandbox. A long `pip install`/`cargo build` no longer dies at the old fixed 600s. DeerFlow warns once if you set it above `request_timeout` (the HTTP client would abort first) — raise both together.
- **Reach the program under debug from your browser.** `sandbox.expose_ports: [8000]` publishes container ports 1:1 to the host loopback in local container mode, so a dev server the agent starts is reachable at `localhost:8000`.
- **Native debuggers.** `sandbox.extra_capabilities: [SYS_PTRACE]` adds `--cap-add` flags (Docker only) so `gdb`/`strace` can attach.
- **A `repo-runner` public skill** (`skills/public/repo-runner/`) that encodes the whole loop: clone into the workspace → detect the toolchain → install deps in an isolated venv/`node_modules` → run (backgrounding servers) → iterate on failures → report reproducible commands.

The `expose_ports` / `extra_capabilities` keys are local-container-mode only; in external/provisioner mode they are warned-as-ignored (declare `ports:` / `cap_add:` in `docker/docker-compose.sandbox.yml` instead). Packages installed outside the mounted workspace (apt, global pip) are still lost when a container is recycled, so keep a project's dependencies in a workspace-local venv — the skill does this by default. Raise `sandbox.idle_timeout` to keep a warmed-up debug environment alive longer between turns.

## Troubleshooting: nginx 502 after `make up`

**Symptom.** After a `git pull` + `make up` (Docker prod, containerized AiO sandbox), `http://localhost:2026` returned a bare nginx **502 Bad Gateway**. nginx was up on `:2026`, but the upstream gateway was not healthy, so nginx had nothing to proxy to. A stack that had previously worked passwordless suddenly wanted a login, and even the login/health routes 502'd.

**What actually happened.** Two independent problems stacked into one opaque failure:

1. **The gateway hard-crashed on config load.** `AppConfig.resolve_env_variables` raised `ValueError: Environment variable … not found` for **any** `$VAR` in `config.yaml` that wasn't set in the environment — *even when the block that referenced it was `enabled: false`*. A leftover `channels.slack` / `channels.telegram` block with `bot_token: $SLACK_BOT_TOKEN` and no token in `.env` was enough to take the whole gateway down. Because the crash happened at startup, the only external symptom was nginx's generic 502 — no hint about the missing variable.
2. **`make up` was silently re-enabling auth.** The fork's passwordless default was wired only into the local launchers (`serve.sh`); the Docker prod path (`deploy.sh`) left `DEER_FLOW_AUTH_DISABLED` unset, so `make up` came up with the login wall on. A home-lab user who expected "no login on my own network" got one, with no obvious escape hatch.

**The immediate workaround** (what unblocked the box):

```fish
# .env
DEER_FLOW_AUTH_DISABLED=1
# make sure DEER_FLOW_ENV / ENVIRONMENT are not prod/production (that forces auth back on)

# config.yaml: don't leave a live $SLACK_BOT_TOKEN etc. for a channel you haven't set up
make sandbox-enable MODE=container
make config-upgrade
make down && make up
```

**The in-repo fixes so it can't recur:**

- **A disabled section no longer crashes the gateway on a missing `$VAR`.** `AppConfig.resolve_env_variables` now propagates a "lenient" flag through the subtree of any `enabled: false` section: a missing `$VAR` there resolves to an empty string with a `WARNING` instead of raising. **Active** config stays strict — a missing API key for an *enabled* model still fails loudly at startup, which is the behavior you want. So a leftover placeholder for a channel you never turned on is tolerated, while a real misconfiguration still surfaces. Pinned by `backend/tests/test_config_env_resolution.py`.
- **`make doctor` lists referenced-but-missing `$VARS` before you start.** A new check (`scripts/doctor.py::check_env_placeholders`) scans `config.yaml`, and for any `$VAR` that isn't set it reports: a **failure** ("The Gateway crashes on load (bare nginx 502) if an active section references an unset `$VAR`") when the section is active, or an informational **note** ("unset but tolerated (enabled: false)") when it's disabled. `make doctor` is the recommended one-liner after a `git pull` and before `make up`. Pinned by `backend/tests/test_doctor.py::TestCheckEnvPlaceholders`.
- **`make up` is passwordless by default** (see §5). `deploy.sh` now defaults `DEER_FLOW_AUTH_DISABLED=1` (opt-out via `.env`), forwards it plus the production markers to both containers, and prints a warning when auth is off — so the home-lab Docker path matches `make dev` / `make start` instead of surprising you with a login wall. Production (`DEER_FLOW_ENV`/`ENVIRONMENT=production`) still forces auth on.

**Recommended post-update flow:**

```bash
git pull
make config-upgrade   # merge any new config fields; never leaves live placeholders for disabled features
make doctor           # catches missing $VARS + reports the auth posture, before the stack starts
make up
```

`make config-upgrade` only ever *adds missing keys* from `config.example.yaml` (whose channel blocks ship fully commented out), so it never injects a live `$PLACEHOLDER` for a feature you haven't enabled; combined with the lenient-resolution fix above, an uncommented-but-disabled block is now harmless.

## Troubleshooting: after an update — container name conflict, then localhost refused

Two more things that can bite right after `git pull` + `make up`, in the order they tend to appear.

### Container name conflict on `make up`

**Symptom.** `make up` fails with `Error response from daemon: Conflict. The container name "/deer-flow-gateway" (or -nginx / -frontend / -searxng) is already in use by container …`.

**Why.** The prod stack pins fixed `container_name:`s (`deer-flow-gateway`, etc.). If a container with that name is left behind — a previous stack that wasn't brought down cleanly, a crashed run, or a container created outside the current Compose project (e.g. a different `-p` project name, or the Docker **dev** stack sharing a name) — `docker compose up` refuses to clobber it and errors instead of recreating it.

**Fix.** Bring the old stack down first, which removes the named containers, then bring it up:

```bash
make down    # removes the named containers for the deer-flow project
make up
```

If a stray container survives `make down` (created outside the project), remove it by name: `docker rm -f deer-flow-gateway` (repeat for `-nginx` / `-frontend` / `-searxng`), then `make up`. **Look out for this when you change `container_name:` or add a service in `docker/docker-compose.yaml`** — a rename leaves the old name orphaned, and any host with the previous name still present will conflict until it is removed.

### `localhost` refused on the host, but it works over Tailscale from another device

**Symptom.** After `make up`, `http://localhost:2026` on the machine running the stack returns **connection refused**, yet the app is reachable from your phone over Tailscale (or another device on the LAN). Nothing is wrong with the app — it's the bind.

**Why.** `BIND_HOST` is a **single bind interface, not an allowlist**. The entry port is published as `${BIND_HOST}:${PORT}:2026`, so setting `BIND_HOST` to your Tailscale IP (e.g. `100.x.y.z`) to reach the app from your phone binds **only** that interface. The host's own `localhost` is a different interface (loopback), so nothing is listening there and the connection is refused. (`BIND_HOST=0.0.0.0` binds *all* interfaces including loopback, which is why the all-interfaces case doesn't hit this.)

**Fix (now automatic).** `scripts/deploy.sh` detects when `BIND_HOST` is a single specific interface — set, but not loopback (`127.0.0.1`/`::1`/`localhost`) and not a wildcard (`0.0.0.0`/`::`) — via `should_cobind_loopback`, and appends `docker/docker-compose.loopback.yaml`, which **also** publishes the entry port on `127.0.0.1`. So with `BIND_HOST=100.x.y.z` the port is now bound on **both** the Tailscale interface and loopback: the phone reaches it over Tailscale *and* `http://localhost:2026` works on the host. Loopback is host-only, so this never widens the external surface. `make up` prints a `✓ Co-binding 127.0.0.1 …` line when it's active. Compose concatenates the two `ports` entries (verified with `docker compose config`), so the base external mapping is untouched. Pinned by `backend/tests/test_deploy_loopback_cobind.py` (the decision function + the overlay's shape).

**Look out for this when you touch the port/bind wiring** — `docker/docker-compose.yaml`'s `nginx.ports`, the `should_cobind_loopback` predicate, or the overlay. If you make the base compose publish a wildcard by default, or add another loopback mapping, you can double-bind `127.0.0.1:${PORT}` and collide on the port (`bind: address already in use`); the predicate deliberately skips the overlay for loopback and wildcard binds for exactly that reason. The still-simplest way to reach the app from both the host and the network without any of this is `BIND_HOST=0.0.0.0` (behind your own firewall/TLS).

## Credits

All credit for the underlying system goes to the [ByteDance DeerFlow](https://github.com/bytedance/deer-flow) team. This fork wires convenience features around their work.
