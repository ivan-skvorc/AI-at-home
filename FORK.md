# Fork Notes — `deer-flow-2-local`

> **Vibe-coded disclaimer.** This fork was put together with heavy LLM assistance and only light human review. The two added features have been smoke-tested but not stress-tested. Treat this as a personal-use scratchpad, not production-grade work. Upstream is the source of truth for everything else: <https://github.com/bytedance/deer-flow>.

## What this fork adds

Convenience features on top of upstream, designed around running DeerFlow locally with mixed cloud + local models (more are covered in the sections further down):

### Adding a new fork feature — what to write, and where

A feature that only exists in code is a feature the next person deletes by accident. Every fork addition lands the same documents — and its own tests — in the **same change set** as the code, and the two guidance files below are byte-budgeted, so where the depth goes is a decision, not a preference.

- **`README.md` — the user-facing half.** Add a `###` subsection under **Core Features** (or a top-level `##` if the feature is not a core-agent behavior, the way *Scheduled Tasks* and *Backup and Restore* sit on their own). Write it for someone deciding whether to turn the feature on, not for someone maintaining it. Cover, in this order and in prose rather than a bare list:
  - **What it is, in one paragraph**, naming the UI entry point (the page and the button) so the reader can find it. If it replaces or sits beside an existing flow, say which and how they differ.
  - **The interesting behavior**, especially any outcome a user would not expect — a feature that is allowed to say "no", a step that is deliberately read-only, a default that is off. Bold the surprising part; that sentence is what makes the section worth reading.
  - **The limits that bite**: size caps, ownership scoping, anything digested or truncated before a model sees it. Users hit these and file bugs otherwise.
  - **How to turn it on**, with the literal `config.yaml` block, every key that matters, and any *other* switch it depends on. State the default explicitly — "off by default" is not implied by an example that shows `enabled: true`.
  - **Add the anchor to the Table of Contents** in the same edit. The TOC is hand-maintained; a section missing from it is a section nobody browses to.
  - **Add a bullet to the leading list** in the blockquote at the top of the file ("On top of upstream, it adds — out of the box:"). That list is the fork's shop window and is meant to be **exhaustive** — every fork upgrade gets a line, with its own emoji, in the same change set that adds the feature. It is not a summary of the section below it: write two or three sentences that lead with what a user *gets*, name the surprising behavior, and say what it costs to turn on (a config key, a daemon setting, nothing). A feature that is documented everywhere except here is a feature nobody discovers, because this list is as far as most readers get.
- **`FORK.md` — this file, the maintainer's half.** Add a numbered `### N.` section under *What this fork adds* covering the reasoning the README deliberately omits: why the design is shaped this way, which properties are load-bearing, and what a future refactor must not "simplify" away. Then add a row to the [Post-sync feature checklist](#post-sync-feature-checklist) naming **the exact command that verifies it** and the specific asserts that are silent when broken — that row is what a sync 18 months from now actually runs, and `scripts/upstream_sync.py` renders it into every auto-generated sync PR.
- **The nearest `AGENTS.md` — the agent's half.** Invariants an AI coding agent needs *before* editing the code go beside the code, in the module-local guide. **Do not grow the root or module files**: `backend/tests/test_agent_guidance_check.py` is a hard assert (root 16 KiB, module 24 KiB, local 40 KiB), both module files run within a few hundred bytes of their budget, and *documenting a feature can fail CI on its own*. Put the depth in a local `AGENTS.md` next to the code, leave a one-line pointer in the module file, and register the new path in that test's approved-guidance list.
- **The checks themselves — write them, don't just cite them.** The FORK.md row above names a command; this is the work of making that command exist and mean something. A fork feature ships with **new** tests, not a note that the existing suite still passes: the pure model or helper in a unit test, the wiring in whatever layer owns it (`backend/tests/` for Python — TDD is mandatory there — `frontend/tests/unit/` for logic and hooks, `frontend/tests/e2e/` for anything a user clicks through), and a launch-time script in the test that already covers that script. Two rules make the difference between a test and a decoration:
  - **Prove the test fails without the change.** Revert the behavior (or neutralize the one line that implements it), watch the new test go red, put it back. A test that passes both ways pins nothing, and the fork is full of invariants — a per-thread lock, a stripped request option, a default that must stay off — where the broken state is *silent* and every other test stays green.
  - **Pin the property, not the implementation.** Name the thing that would be quietly "simplified" away and assert on that: the option that must reach the wire, the lock that must stay scoped, the branch that must decline rather than evict. Then say so in the row and in the local `AGENTS.md`, so the next person reads why before they refactor.
- **`CHANGELOG.md` — the release half.** One `### Added` bullet under `## [Unreleased]`, written from the user's perspective and leading with what changed for them, not with the module you touched. Name the config key and its default in the same bullet.
- **Config, if the feature has any.** **Any** new key means bumping `config_version` **and both chart copies** (`deploy/helm/deer-flow/values.yaml` and that chart's `README.md`) — `scripts/check_config_version.sh` is CI's `validate-chart` job, and nothing outside CI reads those copies. It is tempting to assume a single leaf key inside an existing section is exempt; it is not. `config_upgrade.py` compares the **shape**, nested keys included, and at equal versions it *warns and writes nothing*, so an existing install keeps a config permanently missing the key while every launch path prints the warning. Don't reason about it — prove it, on a copy of the previous example:

  ```bash
  git show HEAD:config.example.yaml > /tmp/prev-config.yaml
  python3 scripts/config_upgrade.py /tmp/prev-config.yaml config.example.yaml
  ```

  It must print `+ <your key>` and stamp the new version. If it instead says *stamped current but is missing N field(s)*, the bump is missing.

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

**Daemon lifecycle (`keep_alive`, preload, contention).** The sizing above stops
at the config file; the daemon itself was unmanaged, and three things followed
from that.

*Every subagent call paid a cold start.* Ollama unloads a model ~5 minutes after
its last call. In a turn where the lead thinks for a while and then delegates,
the local subagent's weights have already been evicted and get reloaded from
disk before it can answer — the cost landing on exactly the local-subagent
configuration this fork recommends. `ollama.keep_alive` is now written into
every synced entry (and forwarded by `ChatOllama` to the daemon), with
`ollama.keep_alive_overrides` for per-model values:

```yaml
ollama:
  keep_alive: 30m        # "1h", a bare number of seconds, or -1 to never unload
  preload: true          # warm models[0] at launch
  keep_alive_overrides:
    qwen3:8b: 1h
```

Unset leaves the daemon's own default, which is the prior behavior — pinning
weights in VRAM is a decision about the whole machine, so the sync does not
assume it.

*The first message of a session was always slow.* `ollama.preload: true` loads
`models[0]` (which is what `models/factory.py` resolves an unspecified model to)
into VRAM at launch, via `/api/generate` with an empty prompt — the load-only
request, no tokens generated. `scripts/serve.sh` runs it **backgrounded**:
loading weights can take tens of seconds and must never sit in front of the
stack starting. It is best-effort in both directions — a busy or absent daemon
is a no-op, and a cloud `models[0]` means there is nothing local to warm.

*Two local models could not both be resident, silently.* A local lead with a
local subagent means two sets of weights in VRAM at once. Ollama does not fail
there — it evicts one to load the other, so every delegation pays a full reload
and the run just crawls. When `vram_gb` is set, the sync now warns at launch
with the real numbers, reusing the same geometry math as the context sizing:

```
[ollama-sync] VRAM contention: qwen3:32b (19.9 GiB) + qwen3:14b (8.9 GiB) need
~30.3 GiB resident together (weights + a 4096-token KV cache each + 1.5 GiB
overhead), but the configured budget is 24 GiB. …
```

A warning, and only a warning: it never silently reassigns the user's model
choice. `make doctor` gained a matching **Local Models** section — daemon
reachable, configured models actually pulled (naming the `ollama pull` for any
that are not), and whether `keep_alive` is set. All warn-only; a deliberately
stopped daemon is not a broken install.

### 2. API-key model auto-config in `config.yaml`

A companion to the Ollama sync for **cloud** models. `scripts/sync-api-key-models.py` runs on every launch, reads the provider API keys in your `.env` (falling back to the process environment), and **uncomments** the matching ready-to-use model block in `config.yaml` — so the right models are enabled on first start with no manual editing.

| `.env` key present | Models enabled | Provider / `use` |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Claude **Fable 5**, **Opus 5**, **Opus 4.8**, **Sonnet 5**, **Sonnet 4.6**, **Haiku 4.5** | direct Anthropic API (`langchain_anthropic:ChatAnthropic`) |
| `OPENROUTER_API_KEY` | Claude **Fable 5**, **Grok 4.6**, **GPT-5.6 Sol**, **GPT-5.3 Codex**, **Gemini 3.6 Flash**, **Llama 4 Maverick**, **MiniMax M3**, **Qwen3.8 Max**, **Kimi K3**, **Mistral Large 3**, **DeepSeek V4 Pro**, **GLM-5.3**, **Nemotron 3 Ultra** | OpenRouter (`langchain_openai:ChatOpenAI` + `base_url`) |
| `OPENAI_API_KEY` | **GPT-5.6 Sol**, **GPT-5.3 Codex**, **GPT-5.6 Mini** | direct OpenAI API (`langchain_openai:ChatOpenAI`) |
| `XAI_API_KEY` | **Grok 4.6**, **Grok 4.5 Fast** | direct xAI API (`langchain_openai:ChatOpenAI` + `base_url`) |
| `GEMINI_API_KEY` | **Gemini 3.6 Flash**, **3.5 Flash-Lite**, **3.1 Pro** | native Gemini SDK (`langchain_google_genai:ChatGoogleGenerativeAI`) |
| `DEEPSEEK_API_KEY` | **DeepSeek V4 Pro**, **V4 Flash** | direct DeepSeek API (`deerflow.models.patched_deepseek:PatchedChatDeepSeek`) |
| `MISTRAL_API_KEY` | **Mistral Large 3**, **Medium**, **Small** | direct Mistral API (`langchain_openai:ChatOpenAI` + `base_url`) |
| `MOONSHOT_API_KEY` | **Kimi K3**, **Kimi K2.6** | direct Moonshot API (`deerflow.models.patched_deepseek:PatchedChatDeepSeek`) |
| `DASHSCOPE_API_KEY` | **Qwen3.8 Max**, **Qwen3.7 Plus** | Alibaba DashScope (`langchain_openai:ChatOpenAI` + `base_url`) |
| `MINIMAX_API_KEY` | **MiniMax M3**, **MiniMax M2.7** | direct MiniMax API (`langchain_openai:ChatOpenAI` + `base_url`) |
| `ZAI_API_KEY` | **GLM-5.3**, **GLM-5.2 Air** | direct z.ai API (`langchain_openai:ChatOpenAI` + `base_url`) |

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
- **What ships priced: everything.** All **40** bundled paid models across all eleven marker blocks carry a `price:` block, in both synced sources. This is load-bearing, not a nicety — a model without one contributes nothing to the total, so a conversation run entirely on unpriced models reports **no cost at all**. Shipping only the Anthropic block priced is exactly what made the chat header render `—` for anyone using another provider. Only Ollama (populated at runtime, genuinely free) stays unpriced. The price is **data, in one place**: `config.example.yaml` carries the block literally and `scripts/wizard/providers.py::MODEL_PRICES` holds the same figures for the wizard, with `test_config_integrity.py::TestBundledModelPricing::test_the_wizard_bundles_and_the_example_agree` asserting the two agree. It is deliberately **not** derived from the display name any more — see §17. `cache_hit` is set only on the Anthropic entries (0.1x input, their published cache-read rate); other providers differ or do not publish one, so their blocks omit it and cache hits fall back to the full input price, the documented conservative upper bound. The two currently-discounted entries (Claude Sonnet 5's intro window and MiniMax M3 on OpenRouter) additionally carry a `discount:` block; Sonnet's has the `until:` Anthropic announced, and the OpenRouter promotion is open-ended. GLM-5.2's 76%-off promotion left with the entry when the roster rolled forward to GLM-5.3 — a discount belongs to the model it was quoted for, so it is not carried across a version bump. Pinned by `backend/tests/test_config_integrity.py::TestBundledModelPricing` (every model priced, no price in any name, well-formed, single-currency, discounts below list with a readable expiry, and the two sources agree).
- **Keep it current with the roster.** The `pricing:` block is part of the same living bundle as the model list — refresh it on the same cadence as slugs and thinking config (see *Auditing the model list* below), reading each figure off the provider's own model page — or, when that page is unreachable, off several independent sources that agree (*Where a price may come from*) — never from memory.

#### Price signal in the display name

Bundled `display_name`s are labels: the model, its source suffix — `(Anthropic)` for the direct Anthropic API or `(OpenRouter)` for OpenRouter-routed models — and any trailing `(p)` marker. E.g. `Kimi K3 (OpenRouter) (p)`, `Claude Sonnet 4.6 (Anthropic)`. The price is **not** in the name; it lives in the model's `price:` block (§17), and the model dropdown renders it from there, so the figure in the picker is the same one the cost overview bills against rather than a second copy that can drift.

The **discount** marker rides on **any** entry currently on a reduced price, direct or routed:

- **`($<list> → $<promo>*)` — a temporary discount.** When a model is currently on a reduced price, the name shows **both** prices: the standard list price, then the discounted price you actually pay now, starred. The `*` marks the second pair as a discount that can end at any time. Two sources of discount qualify:
  - **OpenRouter promotions.** As of 2026-08: **MiniMax M3** (`$0.6/2.4 → $0.24/0.96*`, 60% off). (**GLM-5.2** ran `$1.15/3.6 → $0.28/0.87*`, 76% off, until the roster rolled forward to GLM-5.3; its promo was dropped with the entry rather than carried over.) Derive the list price from the promo page's discounted figure and its stated discount (`list = discounted / (1 − discount)`), so both numbers stay internally consistent.
  - **Anthropic introductory pricing.** A newly launched Claude can ship at an intro rate below its standard list price for a fixed window. As of 2026-07 **Claude Sonnet 5** runs intro pricing through 2026-08-31, so it shows `Claude Sonnet 5 ($3/15 → $2/10*) (Anthropic)` — standard `$3/15`, intro `$2/10`. When the intro window ends, drop the starred pair back to the plain list price.

  A starred name has a machine-readable twin: the model's `pricing:` block keeps the **standard** rate (what cost is billed against) *and* carries the starred figures as `promo_*_per_million`. Both spellings must move together — a promo that ends in the name but survives in the block leaves the header advertising a discount nobody is getting. The model dropdown colours the pair straight out of the name (list red, promo green), and the chat header shows the same pair as two totals. Pinned by `TestBundledModelPricing::test_promo_price_matches_the_starred_pair_in_the_name`, which fails in **both** directions: a starred name with no `promo_*` block, and a `promo_*` block with no starred name.

The privacy marker rides only on the OpenRouter entries:

- **`(p)` — privacy caveat (zero-data-retention not guaranteed).** OpenRouter routes each request to a third-party provider that may log or retain prompts, unlike the direct Anthropic entries (or local Ollama). Every OpenRouter entry carries `(p)`; the direct Anthropic bundle and Ollama models do not. It flags "don't put sensitive data through this one" at a glance — steer private work to the direct Anthropic or local models. This is a routing property, so `(p)` stays on an OpenRouter entry regardless of which underlying lab it points at (the Fable-via-OpenRouter entry carries it too).

Rules for keeping it honest:

- **It is a rough signal, not billing truth.** Round to a clean pair; prompt-cache discounts and provider-variant routing shift the real number. The machine-readable `pricing:` block is what actually feeds the console and chat-header cost displays — keep that exact, keep the name approximate. (The two are kept from drifting apart by `TestBundledModelPricing`, which asserts the block matches the name pair, so "approximate" means *choose* a clean number, not let the two spellings diverge.)
- **Verify, never invent — and corroborate when you cannot verify.** When adding or re-pricing a model, read the current figure off the provider's / OpenRouter's own model page (and its promotions/discounts page for a starred promo). When that page cannot be reached, *Where a price may come from* permits a figure that **several independent sources state identically**, recorded as corroborated in the audit log so the next pass re-checks it; a starred promo never qualifies. Do not carry a price from memory for a model past your knowledge cutoff — that is what neither tier allows.
- **Refresh the pair when you re-slug or re-tier a model, and when a promo starts or ends**, the same way you re-check the slug and thinking config above — a stale price in the name is worse than none. When a promo ends, drop the starred pair back to the plain list price; when one starts, add the `$list → $promo*` pair.
- **Keep both model sources in sync.** A model's price lives in two places that must match: the `price:`/`discount:` blocks in `config.example.yaml`'s marker blocks (the auto-config path) and `scripts/wizard/providers.py::MODEL_PRICES` (`make setup`). Edit both, or a user gets a priced model on one path and an unpriced one on the other — `test_the_wizard_bundles_and_the_example_agree` fails if they diverge. The `(p)` marker lives in the same two places; keep it in sync too.

#### Auditing the model list (settings + pricing)

**The trigger for this pass is the weekly audit job, not the calendar.**
`.github/workflows/model-audit.yml` runs `scripts/audit_models.py` every Monday:
it reads both synced sources and diffs them against the live OpenRouter catalog,
then opens (or updates) a single `model-audit`-labelled issue listing retired or
renamed slugs, list prices that moved, and promotions that started or ended —
with a suggested diff. It **never commits a price**: a price is confirmed against the
provider's own page, or — when that page cannot be reached — against several
independent sources that agree, and recorded as such (*Where a price may come
from*, below). Both are judgements a person makes and writes down; a wrong
automated price is worse than a stale one because it is wrong with confidence and
silences the next audit. An unreachable provider is reported as *skipped*, never as drift,
so the job does not become a weekly red tick people learn to ignore. The issue
closes itself when a later run comes back clean.

Two things the job checks without any network, so they hold for every provider:
each entry's display-name price agrees with its own `pricing:` block (the
half-update that renders a wrong number with nothing raising), and the two synced
sources still agree with each other. Providers without a machine-readable
catalog are listed as skipped in the issue — for those, the manual steps below
are still the whole audit. Run it yourself any time with
`python3 scripts/audit_models.py`, or against the deliberately stale fixture
(`--catalog scripts/fixtures/model_audit_stale_catalog.json`) to confirm the
audit itself still detects drift.

Run this pass **when that issue appears, whenever you touch the bundle, and as a step of the [Post-sync feature checklist](#post-sync-feature-checklist) on every upstream merge** — models, prices, and promos shift on the providers' schedule, not upstream's, so the sync is just a convenient recurring checkpoint to re-verify them. It keeps the enabled models, their per-model settings, and their prices honest. Everything below lives in the **two synced sources** — the `config.example.yaml` marker blocks and `scripts/wizard/providers.py` — so apply every change to both.

1. **Roster & order.** The bundle stays grouped by provider in this order: **Anthropic** (direct) → **OpenRouter** → the **first-party "home" blocks** (OpenAI, xAI, Google, DeepSeek, Mistral, Moonshot, Qwen, MiniMax, z-ai — in `config.example.yaml`'s FIRST-PARTY HOME API BLOCKS section) → **Ollama** (populated at runtime by `scripts/sync-ollama-models.py`, so it lands after the static blocks). Keep the "one flagship per big-name lab + a couple of cheaper picks" shape from *Which models to keep in the bundle* above, and keep each lab's flagship **doubled** (home + OpenRouter).
2. **First-party key coverage — every big name gets its own `.env` key.** Every big-name lab that ships a public API must be reachable **two ways**: a **home block gated by that lab's own key**, carrying a fuller lineup, *and* its flagship on **OpenRouter**, for users who hold only an `OPENROUTER_API_KEY`. This is the Anthropic shape generalised — `ANTHROPIC_API_KEY` lights up six Claudes while only Fable 5 is *also* routed — so `XAI_API_KEY` → Grok, `OPENAI_API_KEY` → ChatGPT/GPT, `GEMINI_API_KEY` → Gemini, `DASHSCOPE_API_KEY` → Qwen, `MOONSHOT_API_KEY` → Kimi, `DEEPSEEK_API_KEY` → DeepSeek, and the remaining home labs all behave the same way. A key drifts out of exactly one of **five** places at a time, so check all five:
   - **`config.example.yaml`** — an `auto-model-config: <provider>` marker block gated on that key, holding **more than the flagship**: flagship + 1–2 acclaimed or cheaper siblings. A home block that is a lone flagship is itself a finding — the fuller lineup *is* the reason to hold the lab's own key, and the routed flagship already covers the other case.
   - **`scripts/wizard/providers.py`** — the same lineup in `HOME_API_BUNDLES`, so `make setup` and the launch-path sync enable an identical set.
   - **`scripts/sync-api-key-models.py`** — the `(slug, ENV_VAR)` pair in `PROVIDERS`, **and** the key → lineup line in its `QUICK START` docstring. That docstring is one of the two entries no test reads (the README bullet below is the other), so it is where a roster roll-forward silently leaves a stale model name behind.
   - **`.env.example`** — a commented `# <LAB>_API_KEY=your-…-api-key` line in the **Model provider API keys** section (not down in the generic OpenAI-compatible list), naming the models it unlocks and, where the key is not obvious to obtain, the console that issues it. A key nobody knows to set enables nothing.
   - **`README.md`** — the §2 leading bullet's *A big name's own key present* line, which is where a user actually learns the option exists. The other four are wiring; this one is the advertisement, and a lab missing from it is a feature nobody uses.

   Then confirm the **doubling** still holds: each home flagship's bare id appears in the OpenRouter block as `<provider>/<same id>` (modulo case — `minimax/minimax-m3` ↔ MiniMax's own `MiniMax-M3`). `TestFirstPartyKeyCoverage` in `backend/tests/test_sync_api_key_models.py` pins the machine-readable half of this — every registered key documented in `.env.example`'s provider section, no home block trimmed to a lone flagship, every home flagship doubled, and **exactly** `meta-llama` + `nvidia` left routed-only — so that half needs no network. The docstring and the README bullet are the two it cannot read for you. **When a lab that was OpenRouter-only ships a first-party consumer API, give it a home block**; that is how the list grows. OpenRouter-only is reserved for labs with no such API — currently **Meta Llama** and **NVIDIA Nemotron**, whose flagships stay routed and alone.
3. **Slugs.** Confirm each `model:` is the exact current id (bare Anthropic ids like `claude-opus-5`; OpenRouter `provider/model` slugs; **home** blocks use each lab's own bare id — the OpenRouter slug minus its `provider/` prefix, e.g. `openai/gpt-5.6-sol` → `gpt-5.6-sol`, `z-ai/glm-5.3` → `glm-5.3`). A wrong/unreleased id fails at request time, not at load — verify against the provider's / OpenRouter's catalog, never from memory.
4. **Per-model settings.** Sanity-check `max_tokens`, `supports_vision`, `supports_thinking`, `temperature`, and the thinking config against the model family (adaptive Claude vs. Haiku budget vs. OpenAI-compatible `extra_body` toggles — see *Keep the model format current* above). `supports_thinking: true` is load-bearing; drop deprecated fields. Confirm each home block's `base_url`/`api_base` and env var match the lab (e.g. `https://api.x.ai/v1` + `XAI_API_KEY`); Google's home block uses the native `ChatGoogleGenerativeAI` SDK with `gemini_api_key` and no thinking toggle.
5. **Pricing.** Read each price off the provider's / OpenRouter's own model page — or, when that page cannot be reached, off several independent sources that agree exactly, logged as corroborated (*Where a price may come from*, below). Refresh the `($<in>/<out>)` pair — **and the model's `pricing:` block with it** (all 40 bundled paid models carry one; `config.example.yaml` holds them literally, `providers.py` derives them from the same name pair, and `TestBundledModelPricing` fails if the two ever disagree). Then show both prices as `($<list> → $<promo>*)` for **any** currently discounted model — from OpenRouter's **promotions/discounts page** (derive list as `list = discounted / (1 − discount)`) **or** an Anthropic **introductory-pricing** window (a newly launched Claude below its standard rate for a fixed window, e.g. Sonnet 5 through 2026-08-31). Drop the starred pair back to plain list when a promo or intro window ends — **and drop the entry's `promo_*_per_million` lines in the same edit**, or the header keeps advertising a discount that has expired (the block is derived automatically in `providers.py`, but `config.example.yaml` holds it literally). **Home entries use the lab's own list price with no promo star** (the OpenRouter promo is a routing property that stays on the OpenRouter copy). Keep the machine-readable `pricing:` block exact: `input_per_million`/`output_per_million` stay the **standard** rate — the conservative upper bound cost is billed against even while a discount is live — and `promo_*_per_million` carries the starred figures beside it.
6. **Privacy marker.** Every OpenRouter entry carries `(p)` (zero-data-retention not guaranteed); the direct Anthropic, first-party **home**, and Ollama entries do not (they hit the lab directly, no middleman). Add `(p)` to any new OpenRouter entry, and the lab's own name suffix (`(OpenAI)`, `(xAI)`, …) to any new home entry.
7. **Regression-test.** `python3 scripts/sync-api-key-models.py --dry-run` must still uncomment the blocks cleanly, and `cd backend && uv run pytest tests/test_sync_api_key_models.py tests/test_setup_wizard.py tests/test_config_integrity.py` must stay green.

##### Where a price may come from: verified, corroborated, or left alone

A price is only worth shipping if you can say where it came from. Three tiers, in
order of preference — use the first one that is actually available on the day:

1. **Verified — the provider's own page.** The lab's own pricing or model page
   (and its promotions page for a discount). For an **OpenRouter** entry, that
   model's OpenRouter page *is* the authoritative page, because OpenRouter's
   rate is what the entry bills at. This is the standard, and the only tier that
   needs no note.
2. **Corroborated — several independent sources that state the same figure.**
   When the authoritative page cannot be reached — an egress-restricted
   environment, a provider behind a login, a page that is simply down — a price
   **may** be taken from **two or more independent sources that agree exactly**.
   This is an allowed outcome, not a rule being bent: leaving a lab's current
   flagship out of the bundle, or shipping it with **no** `price:` block, is
   worse, because an unpriced model contributes *nothing* to every cost total
   (§17) and so under-reports spend silently. Conditions, all of them:
   - **Independent means independent.** Two sites reprinting one launch post, a
     tracker and its own API, or an aggregator and the mirror that scraped it,
     are **one** source. Prefer sources that had to look separately: a routing
     marketplace's model page, a comparison site that dates its figures, the
     lab's own docs when its pricing page is what is unreachable.
   - **They must agree exactly, on both numbers.** Input *and* output. A
     disagreement is a **stop**, not an input to a judgement call — never
     average, never take the lower or the higher, never round the gap away. Two
     sources that differ mean the price is unknown; fall to tier 3.
   - **Standard rate only, never a discount.** A promotion or intro window is
     the most volatile figure on the page and the one whose absence costs
     nothing, since spend is billed at the standard rate either way (§17). A
     discount that cannot be read off the provider's own promotions page is not
     shipped, and a discount is never carried across a version bump.
   - **Record it in the audit log.** Name the model, the figure, and that it was
     corroborated. This is the whole point of allowing the tier: a corroborated
     price nobody knows to re-check is precisely the wrong-with-confidence
     failure the verify rule exists to prevent, and a named list defeats that by
     **directing** the next pass instead of being silenced by it.
3. **Neither — leave the entry alone.** No authoritative page and no agreeing
   sources means the price is unknown. Keep what is already shipped, log the
   provider as unreachable, move on. **Never carry a price from memory**, and
   never let a model past your knowledge cutoff keep a figure you have not seen
   this pass — that is the one thing no tier permits.

The same three tiers cover a **slug** when the catalogs behind step 3 cannot be
reached; a wrong slug fails loudly at request time, so it is the less dangerous
of the two, but it gets logged the same way.

**The automated job stays at tier 1.** `scripts/audit_models.py` still never
commits a price. Corroboration is a judgement someone makes and writes down —
naming what they read and what agreed — not something a weekly cron can assert
on its own.

##### Audit log

Record each pass here — a dated line is what tells the next person whether the roster was checked last week or last year, and *which* providers the pass could actually reach.

- **2026-08-25 (rule addition, not a sync) — mechanical half clean, tier 1 unavailable for the
  sixth pass running, no roster or price change; three stale *descriptions* of the roster fixed.**
  Run while adding **step 2, First-party key coverage** above — the standing rule that every
  big-name lab gets its own `.env` key with a fuller lineup, flagship doubled on OpenRouter —
  and the `TestFirstPartyKeyCoverage` suite that pins its machine-readable half. **Tier 1 remains
  unreachable:** `openrouter.ai` answers `403 Forbidden` through this environment's proxy and the
  eleven first-party hosts are likewise blocked, so no figure was read off a provider's own page
  and **no price or slug was touched** — the roster is byte-identical to the 2026-08-20 pass.
  What *had* drifted was three places that only **describe** the roster, which is exactly the
  failure the new step exists to catch: `.env.example` and `sync-api-key-models.py`'s `QUICK START`
  docstring still advertised **Grok 4.5**, **Qwen3.7 Max** and **GLM-5.2** after the 2026-08-20
  roll-forward to **Grok 4.6 / Qwen3.8 Max / GLM-5.3**, and the README's §2 bullet listed only the
  Anthropic and OpenRouter keys — the nine first-party home keys were undocumented for users.
  All three now match `config.example.yaml`; `MINIMAX_API_KEY` also moved out of the generic
  "OpenAI-compatible" list into the model-provider key section where the other ten live.
  Mechanical half green: `scripts/audit_models.py` reports **no drift** (display-name/price
  agreement and two-source parity both hold) and correctly lists openrouter as *skipped* rather
  than as drift; `sync-api-key-models.py --dry-run` is a clean no-op; and
  `tests/test_sync_api_key_models.py` (47, including the four new ones),
  `test_setup_wizard.py`, `test_config_integrity.py`, `test_audit_models.py` are green.
  Each new test was also confirmed to *fail* on the drift it guards — a key dropped from
  `.env.example`, and a home block removed — so the step is enforced, not merely written down.

- **2026-08-24 (feature PR, not a sync) — mechanical half clean, tier 1 unavailable for the
  fifth pass running, no roster or price change.** Run as the audit step of the checklist while
  adding §21 (concurrent chats), not after an upstream merge. **Tier 1 remains unreachable:** the
  egress proxy still refuses `openrouter.ai` at CONNECT (`Tunnel connection failed: 403
  Forbidden`), and `audit_models.py` listed openrouter as *skipped* rather than as drift — the
  property that keeps this job from becoming a weekly red tick. The other eleven providers have
  no machine-readable catalog and are covered by the manual pass, which needs the same blocked
  pages. **No figure was corroborated this pass either**, because general web search was not
  reachable from this environment; nothing was edited, which is the correct outcome — a price
  written from memory is wrong with confidence and silences the next audit.

  Mechanical half green throughout: `scripts/audit_models.py` reports **no drift** (both offline
  checks hold — every entry's display-name price agrees with its own block, and the two synced
  sources agree with each other); the stale-fixture self-test
  (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still surfaces all four drift
  kinds with suggested diffs and still exits 0 on findings; `sync-api-key-models.py --dry-run` is
  a clean no-op on an empty env; the `display_name`-carries-a-price gate prints nothing; and the
  six model/pricing suites are green (269 passed).

  **Discount review, no change.** Claude Sonnet 5's `$2/10` intro window through **2026-08-31**
  is still open and expires on its own. MiniMax M3's OpenRouter promo still carries no `until` —
  legitimate and deliberately not a finding, and still resolvable only by a reachable promotions
  page.

  **Still owed to the next unrestricted pass**, unchanged from 2026-08-23: Gemini 3.1 Pro's
  `$2/12` (corroborated twice, never verified), the Gemini 3.7 Flash roster decision, the four
  figures in the 2026-08-22 table (Grok 4.6, Qwen3.8 Max, GLM-5.3, Mistral Medium 3.5), and
  MiniMax M3's promo status.

- **2026-08-23 (feature PR, not a sync) — mechanical half clean, tier 1 unavailable again, one
  figure re-corroborated, no roster or price change.** Run as the audit step while adding §20,
  not after an upstream merge. **Tier 1 was unavailable for the fourth pass running:** the egress
  proxy refuses every provider host tried (`openrouter.ai`, `www.anthropic.com`, `api.x.ai`,
  `platform.openai.com`, `z.ai`, `api-docs.deepseek.com`, `ai.google.dev` — all fail at CONNECT),
  and `audit_models.py` correctly listed openrouter as *skipped* rather than as drift. General
  web search **was** reachable, so tier 2 could run.

  Mechanical half green throughout: `scripts/audit_models.py` reports **no drift**; the
  stale-fixture self-test (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still
  surfaces all four drift kinds and still exits 0 on findings; `sync-api-key-models.py --dry-run`
  is a clean no-op on an empty env; the `display_name`-carries-a-price gate prints nothing; and
  the six model/pricing suites are green (269 passed).

  **Gemini 3.1 Pro re-corroborates at the corrected `$2/12`.** That was the single figure the
  2026-08-22 pass changed, so it was the highest-risk entry in the bundle and the one worth
  re-reading first. Independent trackers agree exactly on $2.00 in / $12.00 out for the standard
  tier (≤200K prompts; above that Google bills 2x input / 1.5x output, and per the Grok 4.6
  precedent the `price:` block carries the base tier). Still **corroborated, not verified** — it
  stays top of the owed list.

  **Roster checked for currency, nothing to roll forward.** The August 2026 releases visible from
  tier 2 are Grok 4.6, Qwen3.8-Max, GPT-5.6, Claude Fable 5, Gemini 3.7 Flash, GLM-5.2 Turbo, and
  DeepSeek V4-Pro-0813 GA. Every flagship among them is already bundled; DeepSeek's GA is the
  same `deepseek-v4-pro` id reaching general availability, not a new slug; GLM-5.2 Turbo is behind
  the bundled GLM-5.3; and Gemini 3.7 Flash remains deliberately out for the two reasons the last
  pass recorded (it is a cheaper sibling, not Google's flagship, and its current price is an
  introductory window that tier 2 may not ship). **No entry was edited this pass.**

  **Still owed to the next unrestricted pass**, unchanged in priority from 2026-08-22 minus the
  re-check above: Gemini 3.1 Pro's `$2/12` (now corroborated twice, still never verified), the
  Gemini 3.7 Flash roster decision, the four figures in the 2026-08-22 table (Grok 4.6, Qwen3.8
  Max, GLM-5.3, Mistral Medium 3.5), and MiniMax M3's promo status — a discount never qualifies
  for corroboration, so only a reachable OpenRouter promotions page can resolve it. Claude Sonnet
  5's `$2/10` intro window through **2026-08-31** is still open and expires on its own.

  **One checklist gate caught a real defect in the PR this pass ran alongside.** `config.example.yaml`
  gained an `agent_generation:` section and `config_version` was bumped 40 → 41, but the chart's two
  copies (`deploy/helm/deer-flow/values.yaml` and that chart's `README.md`) were left at 40 —
  exactly the "nothing outside CI reads it" trap the gate exists for. `scripts/check_config_version.sh`
  failed, both copies were bumped, and delivery was then verified end to end on a copy of the
  pre-change example: `config_upgrade.py` reports `+ agent_generation` and stamps 41.

- **2026-08-22 (second pass, upstream sync `f1f4af9`) — corroborated; one price corrected,
  and the four figures the last pass left owed are now cleared.** Provider pages were
  *still* unreachable — `openrouter.ai` and every first-party host answer 403 on CONNECT,
  so **tier 1 was unavailable again and nothing here is verified**. What was different this
  time is that general web search *was* reachable, so tier 2 could actually run instead of
  falling straight through to tier 3. Mechanical half clean, exactly as before:
  `scripts/audit_models.py` reports **no drift**, the stale-fixture self-test
  (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still surfaces all four
  drift kinds, `sync-api-key-models.py --dry-run` is a clean no-op on an empty env, and the
  six model/pricing suites are green (269 passed).

  **The four still-owed figures from 2026-08-20 all corroborate at the shipped numbers** —
  each read off several independent trackers that agree exactly on *both* numbers, none of
  them reprinting a single launch post. No edit was needed for any of them:

  | Model | Shipped | Corroborated | Verdict |
  | --- | --- | --- | --- |
  | Grok 4.6 | $2/6 | $2/6 (base tier; 200K+ prompts bill the whole request at $4/12) | confirmed |
  | Qwen3.8 Max | $2/6 | $2/6 | confirmed |
  | GLM-5.3 | $1.4/4.4 | $1.4/4.4 (z.ai list; resellers quote 10% off the same list) | confirmed |
  | Mistral Medium 3.5 | $1.5/7.5 | $1.5/7.5 | confirmed |

  GLM-5.3 was called out last pass as the most provisional of the four; it now has the same
  corroboration as the rest. These stay **corroborated, not verified** — the next
  unrestricted pass should still read them off the providers' own pages, but they are no
  longer the open risk they were.

  **One correction, applied to both synced sources: Gemini 3.1 Pro was priced wrong on both
  numbers — `$2.5/10.0` → `$2.0/12.0`.** Two independent searches over separate tracker sets
  agree exactly on $2.00 in / $12.00 out for the standard tier (prompts ≤200K; above that
  Google bills 2x input and 1.5x output, and per the Grok 4.6 precedent the `price:` block
  carries the base tier). Output was under-reported by 20% and input over-reported, so every
  cost total involving Google's flagship was wrong in both directions depending on the
  input/output mix. Corroborated, not verified — re-check it first on the next unrestricted pass.

  **Deliberately not changed — Gemini 3.7 Flash (shipped 2026-08-13) supersedes the bundled
  Gemini 3.6 Flash.** Two reasons it was left alone rather than rolled forward, both of which
  a later pass may reverse. First, the roll-forward rule in *Which models to keep in the
  bundle* moves a lab's **flagship** and leaves the cheaper siblings untouched; Google's
  flagship is Gemini 3.1 Pro (confirmed still current this pass — 3.5 Pro has slipped past
  its announced window and has no API model id), and 3.6 Flash is a cheaper sibling, so the
  mechanical rule does not fire here. Second, 3.7 Flash's *current* price is an introductory
  window ($0.75/3.75 through 2026-12-31, reverting to $1.5/7.5) — and tier 2 forbids shipping
  a discount from secondary sources, so the only figure this pass could legitimately give it
  is the post-window standard rate, which would over-report its real cost roughly 2x for the
  next four months. Deciding whether that trade is worth it is a judgement for a pass that
  can read Google's own page.

  **Discounts left alone, as the tier rules require.** MiniMax M3's OpenRouter promo could not
  be checked at all (OpenRouter unreachable) and a discount never qualifies for corroboration,
  so it ships unchanged. Claude Sonnet 5's `$2/10` intro window through **2026-08-31** was
  verified on 2026-08-20 and is still open; it expires on its own, and an expired window is the
  mechanism working, not a finding.

  **Still owed to the next unrestricted pass**, in priority order: Gemini 3.1 Pro's corrected
  `$2/12` (the one figure this pass changed), the Gemini 3.7 Flash roster decision above, the
  four corroborated figures in the table, and MiniMax M3's promo status. Also worth a look
  while there: Google is the one lab whose OpenRouter double is a cheaper sibling
  (Gemini 3.6 Flash) rather than its flagship, so the "every flagship doubled home +
  OpenRouter" shape does not currently hold for it.

- **2026-08-22 — offline only, no changes made.** Run as a step of the upstream-sync
  checklist. The mechanical half is clean: `scripts/audit_models.py` reports **no
  drift** (display-name/`price:` agreement and two-source parity both hold), the
  stale-fixture self-test (`--catalog scripts/fixtures/model_audit_stale_catalog.json`)
  still surfaces all four drift kinds, `sync-api-key-models.py --dry-run` is a
  clean no-op on an empty env, and `tests/test_audit_models.py`,
  `test_sync_api_key_models.py`, `test_setup_wizard.py`, `test_config_integrity.py`,
  `test_model_price_fields.py` and `test_pricing.py` are green (269 passed).
  **The network half could not run at all:** this environment's egress policy
  refuses `openrouter.ai` (403 on CONNECT) *and* every first-party provider host
  tried (anthropic.com, x.ai, platform.openai.com, deepseek.com, z.ai), so the
  audit listed openrouter as *skipped* — correctly, not as drift — and no figure
  could be read off a provider's own page. With no reachable page **and** no
  reachable secondary source, tier 2 was unavailable too, so this pass is tier 3
  throughout: **every entry left exactly as shipped**. Nothing here is evidence
  that the roster is current — only that it is self-consistent.
  **Still owed to the next unrestricted pass:** the four labs rolled forward on
  2026-08-20 from corroborated sources (Grok 4.6, Qwen3.8 Max, GLM-5.3, Mistral
  Medium 3.5) are still un-verified, and GLM-5.3's price remains the most
  provisional of them.

- **2026-08-20 — partial.** Offline half clean: `scripts/audit_models.py` reported no drift (display-name/price agreement and two-source parity both hold), the stale-fixture self-test still surfaces all four drift kinds, and `sync-api-key-models.py --dry-run` plus the four regression suites are green. **Anthropic block fully verified** against the provider's current model list — all six slugs (`claude-fable-5`, `claude-opus-5`, `claude-opus-4-8`, `claude-sonnet-5`, `claude-sonnet-4-6`, `claude-haiku-4-5`), all six price pairs, the 0.1x cache-read rates, and Sonnet 5's `$2/10` intro window through **2026-08-31** all match; the roster shape (Opus/Sonnet keep last-4.x + current-5, Haiku/Fable latest only) is correct as-is, and Mythos 5 stays out because it is invitation-only, so a normal `ANTHROPIC_API_KEY` cannot reach it. **Every other provider unverified:** the environment this pass ran in blocks egress to `openrouter.ai` and to all eleven first-party provider hosts, so no figure could be read off a provider's own page. Existing entries were therefore left alone — a price that is wrong *with confidence* silences the next audit, which is worse than one that is merely stale — but four labs had shipped a new flagship, and those were rolled forward from corroborated secondary sources and named below so the next pass re-checks them.

  **Roster rolled forward on four labs, from corroborated secondary sources — re-verify these on the next unrestricted pass.** Four new flagships had shipped since the last roster edit, and the *Which models to keep in the bundle* rule rolls each one forward mechanically (new flagship in, previous flagship out, cheaper sibling untouched). They were applied rather than deferred, because a lab's flagship being a generation behind is a visible loss to every user of that key, while the risk here is bounded and recorded:

  | Lab | Out | In | Slug | Price used |
  | --- | --- | --- | --- | --- |
  | xAI | Grok 4.5 | **Grok 4.6** | `grok-4.6` / `x-ai/grok-4.6` | $2/6 (unchanged from 4.5) |
  | Qwen | Qwen3.7 Max | **Qwen3.8 Max** | `qwen3.8-max` / `qwen/qwen3.8-max` | $2/6 (was $1.5/4.4) |
  | z.ai | GLM-5.2 | **GLM-5.3** | `glm-5.3` / `z-ai/glm-5.3` | $1.4/4.4 (was $1.15/3.6) |
  | Mistral | Medium 3 | **Medium 3.5** | `mistral-medium-3-5` | $1.5/7.5 (was $0.4/2.0) |

  **What "corroborated" means here, and why it is not the same as verified.** Every figure and slug above agreed across several independent price trackers *and* matched an OpenRouter model-page URL for the same slug — but none was read off the provider's own page, because the environment this pass ran in blocks egress to all of them. That is tier 2 of *Where a price may come from* — an allowed outcome rather than a rule bent, but weaker than a verified figure, so it is recorded rather than hidden precisely so the next audit is **directed** at these four rather than silenced by them: the failure mode the "verify, never invent" rule guards against is a wrong price that nobody knows to re-check, and a named list defeats that.

  Three judgement calls inside the roll-forward, each of which a later pass may reverse:

  - **GLM-5.2's 76%-off OpenRouter promotion was dropped, not carried over.** A discount is quoted for a specific model; carrying one across a version bump would advertise a price nobody was ever offered. z.ai had not published a per-token GLM-5.3 rate at the time of this pass, so its price is the most provisional of the four. Cost spread survives comfortably without it — DeepSeek V4 Flash ($0.14/0.28), Mistral Small ($0.1/0.3), Llama 4 Maverick ($0.2/0.8), GLM-5.2 Air ($0.2/1.1), Gemini 3.5 Flash-Lite ($0.3/1.2), and MiniMax M3's live promo all remain.
  - **Mistral Medium is now pinned (`mistral-medium-3-5`) instead of aliased (`mistral-medium-latest`).** The alias is what let this entry sit labelled "Medium 3" at Medium 3's price while the alias itself had moved on — the name, the slug, and the price were three things that could drift apart with nothing raising. Pinning costs the automatic follow and buys an entry whose three halves describe the same model. If the reported Medium 3.5 price is right, the aliased entry had been under-billing by roughly 4x.
  - **Grok 4.6's price is its base tier.** xAI bills the whole request at a higher rate once a prompt passes 200K tokens; the `price:` block holds one rate, so it carries the base tier, matching how every other entry in the bundle works.

  The bundle is still **40** paid models — this rolled the roster forward rather than growing it — every flagship is still doubled home + OpenRouter, and `scripts/fixtures/model_audit_stale_catalog.json` was regenerated against the new roster so all four drift kinds still fire (the fixture's `_comment` now spells out the four deliberate drifts to re-apply).

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
- **A streamed model id can arrive doubled, and is collapsed before anything prices it.** The reported id is not always *reported*: for a streamed response LangChain assembles it chunk by chunk with `merge_dicts`, which **concatenates** two equal strings under the same `response_metadata` key. `langchain_openai` writes `model_name` on every chunk carrying a `finish_reason`, and some OpenAI-compatible providers (OpenRouter among them) send more than one such chunk — so the assembled message says `deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro`, and its `finish_reason` says `stopstop`. Nothing raises: the id simply matches no configured model, so every token it burned counted as unpriced and the header fell back to `—` while the unpriced note named a model that does not exist. `deerflow.model_ids.normalize_reported_model_name` collapses a whole id repeated end to end, applied where a reported id is read — the run journal's per-model buckets (the single write path for every cost consumer), the subagent token collector, the one-shot LLM used by the memory/suggestions counters, and `SpendBudgetMiddleware`'s message fallback, where an unrecognized model prices at **zero** and would leave a capped account uncapped on exactly that provider. The rule is deliberately narrow — **only** an exact whole-string repetition, never a mismatched pair (`claude-opus-5claude-haiku-4-5`) or a partial one (`claude-opus-5claude-opus-5-20260115`), because guessing which half is real would bill one model at another's rate, and that is worse than showing no cost. Runs already persisted with the doubled key need no migration: `lookup_pricing` tries the collapsed form as one of its candidates, and the two store aggregations plus the console's spend/usage reports normalize on read, so an old bucket merges into the model it names instead of standing as a second, unpriced row. Pinned by `backend/tests/test_model_ids.py` and cases in `test_pricing.py`, `test_token_usage_by_model.py`, `test_thread_token_usage.py`, `test_console_router.py` and `test_spend_budget_middleware.py`.
- **Ollama / unpriced = $0.** A model with no `pricing:` block contributes nothing to the cost — local inference is treated as free even though it burns electricity. The header's **?** tooltip says exactly this so the number is never mistaken for a billing statement.
- **Separate memory & suggestions counters.** The two optional, off-by-default features that quietly cost tokens — background **memory** extraction (§"Long-term memory off by default") and follow-up **suggestions** (§4) — never become graph runs, so their tokens never reached the thread's run totals. They are now tracked in a small **durable** per-thread registry and shown as their **own** priced counters in the header dropdown when non-zero, so you can see what each is costing on top of the conversation itself. The registry survives a Gateway restart — see *Durable auxiliary counters* below.

**Where it's wired.**

| Piece | Location |
| --- | --- |
| Shared pricing math (build map, provider-id resolution, per-token cost, per-run cost, one-currency guard, promo rates) | `backend/app/gateway/pricing.py` — extracted from `routers/console.py` so the console and the thread endpoint price identically. `_pricing_lookup_candidates` owns the provider-reported-id normalization, so the console, the thread endpoint, and the memory/suggestions aux counters all resolve ids the same way. `_parse_promo_rates` validates a discount (both directions, positive, at or below list) and `ModelPricing.promo()` hands it back as an ordinary `ModelPricing`, so `token_cost` prices a promo through the same formula as a standard rate rather than a second one that could drift |
| Bundled model prices | All 40 paid entries carry a `price:` block in `config.example.yaml`'s marker blocks, mirrored by `scripts/wizard/providers.py::MODEL_PRICES`; a test asserts the two agree, and no price may appear in a `display_name` (§17) |
| Thread cost endpoint | `GET /api/threads/{id}/token-usage` (`routers/thread_runs.py`) now returns `total_cost`, `promo_total_cost` (the same whole-thread total at live discount rates, null when nothing is discounted), `currency`, `unpriced_models` (models that spent tokens with no configured price), per-model `cost`/`input`/`output`/`cache_read`, and an `aux` map (memory/suggestions tokens+cost). The store aggregation (`runs/store/memory.py`, `persistence/run/sql.py`, shared `new_by_model_usage_entry()`) now carries the per-model input/output/cache-read split the pricing needs |
| Auxiliary-usage registry | `backend/packages/harness/deerflow/runtime/aux_usage.py` — thread-safe, bounded (LRU over 4096 threads), and **durable**: a write-through cache over `runtime/aux_usage_store.py`, a small dedicated SQLite file at `<DeerFlow home>/aux_usage.sqlite3`. Memory records via the existing `_host_default_extraction_callback` (`agents/memory/manager.py`); suggestions records via `run_oneshot_llm_with_usage` (`utils/oneshot_llm.py`) from `routers/suggestions.py`. Async callers (`routers/suggestions.py`, the `token-usage` endpoint) go through `arecord_aux_usage` / `aget_thread_aux_usage`, which offload the file IO |
| Frontend | `token-usage-indicator.tsx` renders the green cost (plus the red standard rate and its legend while a promo is live) + `?` tooltip + aux rows + the unpriced-model note; `core/threads/token-usage.ts` (`threadTokenUsageToCostSummary`, `formatCost`); both chat pages pass the summary; i18n `tokenUsage.cost` / `costHint` / `unpricedOnly` / `unpricedPartial` / `promoRate` / `standardRate` / `memory` / `suggestions` |

**Cost per step — which turn got expensive.** The totals answer "what has this conversation cost". They structurally cannot answer *which turn* cost it, which is the question a thread that switches models mid-conversation actually raises. A small chart in the cost dropdown does, with a toggle between the two readings:

- **x axis = steps.** One step is one completed run — a user message and the answer to it — numbered from 1 in the order the conversation happened, not in whatever order a store returned the rows. A resumed or replayed run can land in the thread index out of order, so both stores sort by `created_at` explicitly (pinned by `test_runs_recorded_out_of_order_are_still_chronological`).
- **Two modes, and the form changes with them, because the job does.** *Each step* is a magnitude comparison across discrete turns → **columns**. *Running total* is a trend → a **line with an area wash**. Drawing a running total as columns would imply each bar is an independent quantity; drawing discrete turns as a line would imply the cost moved continuously between them. The last cumulative point equals the headline total by construction — pinned by `test_steps_sum_to_the_thread_total` (backend) and `the last cumulative value equals the thread total` (frontend), because a chart that disagrees with the number printed directly above it is worse than no chart.
- **A step is priced exactly the way the thread is** — each model in that run at its own rate, through the same `lookup_pricing` / `token_cost` helpers. An Ultra-mode step whose subagent ran on a cheap model is not billed at the lead's rate, and the promo basis follows the same rule as `promo_total_cost`: null when nothing in the step is discounted, so the UI never prints the same number twice in two colours.
- **An unpriced step is a gap, not a zero.** A local Ollama turn draws no column at all. A bar on the floor reads as "this turn was free", which is a different claim from "nothing could price this turn". The *cumulative* series treats it as contributing nothing, so the running total stays flat across it — matching the thread total, which also skips unpriced models.
- **The y axis always starts at zero.** A non-zero baseline exaggerates the difference between turns, which is the standard way a spend chart misleads. Pinned by `the y scale starts at zero so near-identical turns look near-identical`.
- **No charting dependency.** The chart is hand-rolled inline SVG: the repo enforces route asset budgets (`pnpm perf:check`), and pulling in a charting library for one 64px sparkline would spend that budget badly. The geometry lives in `core/threads/cost-chart.ts`, separate from the component, so the maths is unit-testable — an off-by-one in a scale is invisible at that size but makes the chart lie about money.
- **One series, so no legend; one direct label, not a number on every point.** Per-step labels the most expensive turn, cumulative labels where the total ended. The series colour is emerald-600 (`#059669`) rather than the emerald-500 used for the cost text: 600 is the step that passes the lightness band, chroma floor, and 3:1 contrast against **both** the light and dark chart surfaces, so one validated step serves both themes with no theme-conditional colour.

**Where the per-step data comes from.** `aggregate_tokens_by_thread` gained a `by_run` list beside `by_model` — one entry per completed run, oldest first, each keeping its own per-model split. Both stores build it through the shared `new_per_run_usage_entry` / `add_per_run_model_usage` helpers in `runs/store/base.py` so the memory and SQL aggregations cannot drift (pinned by `test_memory_and_sql_stores_agree_on_by_run`). The endpoint turns that into `steps[]`; a store that predates the field degrades to an empty chart rather than an error.

**Verify it works.** The pricing math and the endpoint are both offline-testable, so the backend tests are the fast gate:

```bash
cd backend && uv run pytest tests/test_pricing.py tests/test_thread_token_usage.py tests/test_aux_usage.py tests/test_aux_usage_wiring.py
cd backend && uv run pytest tests/test_thread_step_costs.py   # per-step costs: ordering, per-model pricing, promo basis, store parity
cd backend && uv run pytest tests/blocking_io/test_aux_usage.py   # the durable aux store's IO stays off the event loop
make doctor      # 'model pricing' names the symptom when nothing configured can be priced
cd backend && uv run pytest tests/test_config_integrity.py -k BundledModelPricing   # every model priced; name pair == pricing block; promo pair == promo block
cd frontend && pnpm test token-usage                                                 # cost summary incl. promo + aux promo collapse
cd frontend && pnpm test cost-chart && pnpm test cost-per-step-chart                  # chart geometry + the per-step/cumulative toggle
```

Then in the browser (`make dev` → open a chat that has run at least one turn): the header pill shows a **green** dollar amount; opening it shows **Estimated cost** in green, the **Cost per step** chart beneath it (switch the toggle and confirm the columns give way to a rising line whose end label matches the total above), and — if any model in the thread is currently discounted — a red standard total beside it with the `promo rate now` / `standard rate` legend. Run an **Ultra-mode** turn with the subagent set to a discounted model (MiniMax M3, or Claude Sonnet 5 while its intro window lasts) and a full-price lead: the gap between the two totals should equal the subagent's saving only. Memory/suggestions rows are green and priced per their own model. **Then restart the Gateway** (`make stop && make dev`) and reopen the same thread: the memory/suggestions rows must come back with the same totals — that is the durability half, and it is the one thing a unit test cannot show you end to end. `<DeerFlow home>/aux_usage.sqlite3` is the file behind them.

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

- **Where the data comes from.** Price is a structured field on `/api/models` (§17): the server resolves it through `deerflow/pricing.py` and returns it with any discount already expiry-filtered, so the picker cannot advertise a promotion that has ended. `core/models/sorting.ts::resolveModelPrice` prefers that field and `modelNameSegments` renders it as the same coloured pair the old embedded text produced. Provider is still parsed from the `(Anthropic)`/`(OpenRouter)`/`(Ollama)` suffix by `parseModelProvider`. The display-name price parser (`parseModelPrice`) is retained as the fallback for a config written before prices moved into their own field, and for hand-added models that follow the old convention; an unpriced model sorts last and an unknown suffix groups under "Other", so the parse still degrades gracefully rather than throwing.
- **The price is coloured in the list.** `splitModelNamePriceSegments` splits a `display_name` into text and price runs so `ModelDisplayName` can paint the price green (`text-emerald-500`) — the money in a wall of model ids, matching the header's cost figure. A discounted `($list → $promo*)` name gets both halves coloured: the **promo** green (what you pay now) and the **list** price red (`text-red-500`, what it reverts to), the same green/red pairing the cost overview uses in §7. It is purely presentational and total: a name with no parseable price renders verbatim as one text segment, and the segments always rejoin to the original string, so no model can lose characters to the split. Used by all three pickers (lead, subagent, sidecar) in both the trigger label and the list row.
- **The collapsed trigger keeps the price, not the provider.** The composer's model button is capped at `max-w-40` / `sm:max-w-56`, and the price sits in the *middle* of a bundled name, so the promo half — the number you most want — was the first thing lost. Two changes fix it, and both are needed. (1) `compactModelDisplayName` drops trailing non-price groups (`(OpenRouter)`, `(Anthropic)`, and each lab's own home suffix) while keeping the `(p)` privacy marker, which is worth more at a glance than the provider and was previously truncated away first; the full name stays on hover via `title` and in the open list. (2) `ModelDisplayName variant="compact"` lays the segments out so only the **leading model name** may ellipsize — the price pair and `(p)` are `shrink-0`. **The host `ModelSelectorName` must carry `w-full`**, which is the actual pre-existing bug: it sits in a `flex-col items-start` container where its own `flex-1` sizes the *cross* axis (height), so it defaulted to `fit-content`, rendered **past** the capped button, and its `truncate` never fired at all. Measured in Chromium: a bundled promo name is 315px inside a 160px button; with `w-full` it is bounded to 142px and both prices stay visible at `max-w-40` and `sm:max-w-56` alike. If a trigger ever shows a clipped price again, check that `w-full` is still on all three `ModelSelectorName` triggers before touching the segment logic.
- **What the controls do.** Sort key `Default` (config order, the out-of-the-box default so nothing changes until you opt in) / `Name` / `Price`; a direction toggle (disabled for `Default`); and a **Group by provider** switch. Price sorts on the current **output** price (the dominant cost driver); unpriced models always sink to the bottom in both directions. The subagent picker additionally keeps tool-incapable models last (§3's `(no tool support)` rule) via the sorter's `demoteLast` option, and its "Follow lead" entry stays pinned at the top. While you type in the search box, `cmdk` orders by match relevance (the sort governs the browse order).
- **Where it lives.** The preference (`{ sortKey, sortDir, groupByProvider }`) is persisted **per browser** in `deerflow.local-settings` (`core/settings/local.ts`, `modelPicker`) — shared across threads, unlike the per-thread model selection. Shared UI in `components/workspace/model-picker-controls.tsx` (`ModelPickerControls` + `ModelPickerList`) is used by all three pickers: the lead and subagent selectors in `input-box.tsx` and the sidecar selector in `sidecar/sidecar-panel.tsx`, so ordering behaves identically everywhere. i18n keys live in `core/i18n/locales/{en-US,zh-CN}.ts`.

Pinned by `frontend/tests/unit/core/models/sorting.test.ts` (price/provider parsing incl. the promo pair and bare-version-number guard, name/price/default sorting, unpriced-last, `demoteLast`, provider grouping, `splitModelNamePriceSegments` — single vs. promo pair, the exact-reassembly property, no-price and empty names, and no shared regex state between calls — and `compactModelDisplayName` — provider suffix dropped, `(p)` kept, the price group never stripped, first-party home suffixes handled without a hardcoded list, a name that would compact to nothing returned whole, and the promo pair surviving for all three discounted bundled models). The *layout* half (does the price actually stay on screen?) is CSS, so no unit test covers it — it was verified by measuring the real cascade in Chromium, and the `w-full` note above is the regression guard.

**Verify it works.** The parsing/sorting/grouping is pure logic, so the unit test is the fast gate:

```bash
cd frontend && pnpm test sorting     # sorting.test.ts: parse price/provider, sort, group, demoteLast, price-segment split, compact trigger name
```

Then check the wiring end-to-end in the browser (`make dev` → open a chat): the model dropdown shows a **Sort** toggle (`Default` / `Name` / `Price`), a direction button (disabled on `Default`), and a **Group by provider** switch. `Price` orders by the current (promo-aware) output price with local/unpriced models last; `Group by provider` splits the list into Anthropic / OpenRouter / Ollama sections. Each row's price is green, and a discounted model (MiniMax M3, Claude Sonnet 5) shows its list price red beside the green promo. **Select one of those three and close the dropdown**: the collapsed button must still show both prices (the provider suffix is dropped to make room; hover for the full name). Check it at a narrow window width too — that is where it used to clip. The choice persists across reloads and threads (`deerflow.local-settings → modelPicker`). Confirm the same controls appear in the **Ultra-mode subagent** picker (no-tool models still sink to the bottom, "Follow lead" stays pinned) and the **sidecar** picker. Full frontend gate: `pnpm check && pnpm test`.

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

### 12. Effective deployment exposure check

Passwordless auth, multi-user mode off, and a non-loopback `BIND_HOST` are
simultaneously this fork's happy path and its worst-case security posture. Each
setting is individually documented and individually defensible. The
*combination* is what decides who can reach the instance and as whom — and until
now nothing computed it, so the operator had to hold three settings in three
different files in their head at once.

`scripts/exposure.py` computes it. `make doctor` reports it, and the same
assessment prints at the end of `make up` and `make dev`, where it is actually
read.

**It changes no default.** This is diagnosis only — the defaults are the fork's
deliberate choice, and the check never returns a `fail`, so a home lab that is
exposed on purpose does not make `make doctor` exit non-zero.

**Two entry surfaces, and they do not share a bind address.** This is the part
that is easy to get wrong by reading `.env` alone:

| Entry | Bind address | Set by |
| --- | --- | --- |
| `make up` (Docker) | `${BIND_HOST:-127.0.0.1}` | `.env` → the published compose port; **loopback by default** |
| `make dev` / `make start` (local) | every interface | `docker/nginx/nginx.local.conf`'s `listen 2026;` has **no address**, so `BIND_HOST` does not apply at all |

So the local dev stack is on the LAN even when `.env` says `BIND_HOST=127.0.0.1`.
That is not a regression — it is what the local nginx config has always done —
but it was invisible. `make doctor` now prints one row per entry.

**Tiers.**

| Tier | When | Reported as |
| --- | --- | --- |
| `local-only` | the bind is loopback | ✓ ok, one line, no nagging — every other setting is irrelevant if nobody outside this machine can connect |
| `trusted-network` | reachable, but either auth is on, or the reach is a tailnet / private LAN | ⚠ warn |
| `open-network` | no login wall **and** a wildcard / public / unclassifiable bind | ⚠ warn, naming every contributing setting |

A Tailscale bind is deliberately not the same as `0.0.0.0`: 100.64.0.0/10 and
`fd7a:115c:a1e0::/48` are classified as `tailscale`, not `private`, because a
tailnet is a device-authenticated overlay. (Python's own `is_private` reports
CGNAT as private, so the ordering in `classify_bind_host` is load-bearing.)
`should_cobind_loopback` in `deploy.sh` already treats the two differently; this
matches it.

**Contributing settings are only named when they can matter.** Multi-user mode
off on a loopback-only box is the documented personal-server default, not a
finding — it is reported as contributing only once the instance is reachable
*and* passwordless. Same for `allow_host_bash`, which becomes "anyone on this
network gets host code execution" only under those same two conditions. A
`DEER_FLOW_AUTH_DISABLED=1` that is neutralized by `DEER_FLOW_ENV=production`
is credited as such rather than counted against the deployment.

| Piece | Where |
| --- | --- |
| Assessment | `scripts/exposure.py` (`classify_bind_host`, `resolve_facts`, `assess`) |
| Doctor check | `scripts/doctor.py::check_deployment_exposure` (one row per entry surface) |
| Launch summaries | `scripts/deploy.sh` (after the bind line), `scripts/serve.sh` (after the logs line) |
| Tests | `backend/tests/test_exposure.py` |

**Verify it works.**

```bash
cd backend && uv run pytest tests/test_exposure.py
python3 scripts/exposure.py --surface docker      # or --surface local, --format json
```

### 13. Whole-instance backup and restore (`make backup` / `make restore`)

There is per-feature memory import/export, but nothing snapshotted `.deer-flow`
**as a unit**: memory, threads, chat tabs, runtime settings, uploads, the
databases. A personal AI accumulates months of that on one machine with no
redundancy, which is exactly the deployment shape this fork targets.

```bash
make backup                              # → backups/deerflow-backup-YYYYmmdd-HHMMSS.tar.gz
make backup INCLUDE_SECRETS=1            # also .env + integration tokens (see below)
make restore ARCHIVE=backups/….tar.gz    # refuses while a stack is running
python3 scripts/backup.py inspect <file> # read the manifest without extracting
```

**What is in it.** `config.yaml`, `extensions_config.json`, the DeerFlow home
tree (`backend/.deer-flow` and a repo-root `.deer-flow`), and `skills/custom`.
Public skills are deliberately out — they are committed, so a restore onto a
clean checkout already has them. Rebuildable caches are out too (`skills_view`,
`.retrieval`, `__pycache__`, browser frames, staged `.upload-*.part` files).

**The secrets decision, stated rather than defaulted.** Credentials are
**excluded** unless you ask for them. Integration credentials under
`users/{user_id}/integrations/` are `0700`/`0600` for a reason and `.env` holds
every API key; copying them into a world-readable tarball in `~/Downloads` turns
a durability feature into a credential-exfiltration feature nobody asked for.
`--include-secrets` (`INCLUDE_SECRETS=1`) opts in, and then:

- the archive is created `0600` **from the first byte** — opened with an explicit
  mode rather than chmod'ed afterwards, because an archive that is briefly
  world-readable while it is written is world-readable;
- the manifest records `includes_secrets`, so a restore can say what it is about
  to write;
- restoring a secret-*free* archive leaves the target's existing credentials in
  place rather than deleting what the backup does not carry.

**Databases are handled explicitly, not hoped for.** With
`database.backend: sqlite` the file is inside the home tree and comes along.
With `postgres`, `pg_dump --no-owner --no-privileges` runs into the archive, and
a failed dump **aborts the backup** — a snapshot with no database in it is worse
than an error, because you only find out at restore time. Restore writes the
dump beside the config and tells you to load it; it never touches a live
database on your behalf.

**Restore refuses to run underneath a live stack.** Writing over SQLite that a
Gateway holds open, and over thread directories an active run is using, is how a
recovery becomes a second outage. `restore` probes the Gateway (8001) and nginx
(2026) ports and stops with the list of what is up and the `make stop` fix;
`--force` / `FORCE=1` is the deliberate override.

**Permissions survive; ownership is documented, not faked.** Extraction uses
`tarfile`'s `filter="tar"`, which keeps the recorded mode bits (so `0700`
credential directories come back `0700`) while still rejecting absolute paths
and traversal. The `data` filter would have stripped exactly the modes this
feature exists to preserve. Ownership can only be restored as root, so it is not
attempted — which also makes this the recovery path for the root-owned-files
problem in the Arch / DooD section: restore as your own user and the tree comes
back owned by you.

**Archive safety is enforced on the way in.** Every member must live under
`deerflow-backup/`, with no absolute path and no `..` component, and the archive
must carry a readable DeerFlow manifest — an arbitrary tarball is refused rather
than extracted over your instance.

| Piece | Where |
| --- | --- |
| Script | `scripts/backup.py` (`create_backup`, `restore_backup`, `inspect_backup`, `detect_running_services`) |
| Targets | `make backup` / `make restore` in the root `Makefile` |
| Tests | `backend/tests/test_backup.py` |

### 14. Model fallback chains

§3 above notes that models flagged `supports_tools: false` stay selectable and
"tool-using subagents will simply fail at runtime". That is one instance of a
general problem: running local models means absorbing local-model failure modes
— daemon down, OOM, context overflow, no tool support — and the user was
absorbing them by hand, one lost turn at a time. This is the reliability cost of
the fork's central bet, and paying it is what makes a cost-aware routing policy
safe to turn on.

```yaml
models:
  - name: qwen3:8b
    fallback: [claude-haiku-5]     # per-model, wins over the global chain

model_fallback:                    # default for models that declare none
  enabled: false                   # off by default
  chain: [claude-haiku-5]
```

**A failure falls back; a decision does not.** That distinction is the whole
design. A provider that is down, overloaded, or handed too many tokens has
failed, and trying the next model beats losing the turn. A user interrupt, a
spend cap (§10), and a guardrail refusal are things the system *meant* to do —
retrying those on another model would defeat them **and spend money doing it**.
A 401/403 is a third case: a bad key is a config error you need to see, not
something to paper over until the bill arrives.

| Falls back | Does not |
| --- | --- |
| connection failure / timeout to the provider | user interrupt (`CancelledError`, LangGraph interrupt) |
| context-length rejection | spend or token cap |
| unsupported tool calls | guardrail / moderation refusal |
| provider 5xx | 401 / 403, and any plain 4xx that is not context/tools |

Anything unrecognized also does **not** fall back: defaulting to "retry on
another model" would double the cost of every bug and bury the original error
behind a second, unrelated one.

**Cycles are not detected, they are inexpressible.** A chain member is built
*without* its own chain, so `a → b → a` is not a shape the config can produce;
`MAX_CHAIN` (3) bounds the rest. A member that cannot be constructed — missing
key, bad class path — is dropped with a warning rather than taking down the
model the user actually selected: degrading to "no fallback" always beats
degrading to "no model".

**Cost stays correct for free, and that is load-bearing.** The wrapper returns
the serving model's result untouched, so the `response_metadata.model_name` that
`RunJournal` keys `token_usage_by_model` on already names whichever model ran.
Rewriting it to the primary's name would bill a cloud fallback at a local
model's rate of zero — silently wrong in the direction of the spend cap (§10)
and the spend report (§11).

| Piece | Where |
| --- | --- |
| Classification + wrapper | `backend/packages/harness/deerflow/models/fallback.py` |
| Config | `ModelConfig.fallback`, `deerflow/config/model_fallback_config.py`, `config.example.yaml` |
| Wiring | `models/factory.py::_wrap_with_fallbacks` |
| Tests | `backend/tests/test_model_fallback.py` |

### 15. Cost-aware subagent routing

The fork exposes the cost lever — a per-thread lead model and a per-thread
subagent override (§3) — but the user has to pull it every session. The worked
example in *Cost story* below puts Sonnet-lead / Haiku-subagents at **~63%
cheaper** than all-Sonnet, and Sonnet-lead / local-subagents at **~95%**. A
policy turns that UI affordance into a standing saving.

```yaml
model_routing:
  enabled: false                # off by default
  rules:
    - name: tool-free-to-local
      when:
        needs_tools: false      # unset conditions are wildcards
        max_context: 24000      # estimated prompt + overhead, in tokens
      prefer: [qwen3:8b, claude-haiku-5]
    - name: everything-else-cheap
      prefer: [claude-haiku-5]
```

**No LLM classifies the task.** Requirements are read from facts already on the
table: whether the subagent was given business tools, whether it can view images
(`view_image` is only bound to a vision-capable model, so its presence is a real
capability signal), and the size of the prompt. Adding a classification call
would spend money to decide how to save money, and would make the routing
decision non-deterministic — two identical delegations could route differently.

**The explicit selection always wins, and it wins by standing the policy down
entirely** rather than by "outranking" it: `apply_routing_policy` returns the
override before the policy is consulted at all. The policy only ever fills the
default that would otherwise be inherited from the lead.

**A model is only chosen if it can do the job.** Capability filtering is applied
*to* the preference order, not merely alongside it: a candidate with
`supports_tools: false` is skipped for a tool-using subtask, one without vision
is skipped for an image subtask, and one whose `context_window` is below the
estimate is skipped too. Trading a cost saving for a failed turn is not a trade.
A rule that matches but offers nothing capable falls through to the next rule
rather than failing the delegation.

**The decision is inspectable.** The subagent card shows `(via <rule>)` beside
the model name, and the tooltip carries the full reason — including which
candidates were skipped and why. A routing decision nobody can inspect is a
routing decision nobody trusts, and "why did this *not* route?" is the first
question an operator asks, so a reason is produced even when nothing was routed.

| Piece | Where |
| --- | --- |
| Policy config | `deerflow/config/model_routing_config.py`, `model_routing:` in `config.example.yaml` |
| Requirements + resolution | `deerflow/subagents/routing.py` |
| Precedence | `tools/builtins/task_tool.py::apply_routing_policy` |
| Card | `core/tasks/lifecycle.ts`, `core/tasks/types.ts`, `components/workspace/messages/subtask-card.tsx` |
| Tests | `backend/tests/test_model_routing.py`, `frontend/tests/unit/core/tasks/lifecycle.test.ts` |

### 16. Installable PWA + push notifications that survive a closed browser

This was the biggest gap relative to the fork's own stated goal. There was a
notification settings page, but it used the plain browser `Notification` API
with **no service worker and no manifest** — so a notification only fired while
the tab was open, and iOS Safari would not deliver at all. The use case the fork
is built around ("start a sandbox run from my phone over Tailscale, pocket it,
get pinged when it's done") did not work on the device it is designed for.

**Installable.** `frontend/public/manifest.webmanifest` plus icons, linked from
the root layout's `metadata`, with `appleWebApp` set — on iOS, Add to Home Screen
is not a nicety, it is the *precondition* for receiving push at all.

**The service worker is deliberately push-only.** It handles `push` and
`notificationclick` and caches nothing. DeerFlow is a live, server-driven app —
SSE streams, per-thread state, an API that moves with every backend release — so
a stale cached shell served after an upgrade produces bugs that look like backend
faults and are miserable to diagnose. That is a far worse trade than offline
support nobody asked for.

**Web Push, end to end.** VAPID keys are minted on first use and kept
(`<DeerFlow home>/vapid.json`, mode `0600` from the first byte — regenerating
them silently invalidates every existing subscription). Subscriptions are stored
per user in the same `ui_state.json` bag as the pinned chat tabs, deduped by
endpoint so re-subscribing replaces rather than accumulates. `pywebpush` is an
**optional extra** (`uv sync --extra webpush`): push encryption is not something
to hand-roll, and most installs never turn this on, so the feature reports itself
unavailable with the install hint instead of making everyone carry it.

**A dead subscription deletes itself.** A push service answers 404/410 for a
subscription the browser discarded, and nothing else ever prunes those, so a user
who reinstalls their browser would otherwise accumulate undeliverable endpoints
forever.

**Only runs worth interrupting for.** A notification fires when a run finishes
*and* took longer than 30 seconds — by then the user has almost certainly
switched away, which is exactly when a push is useful. A notification for a
two-second question is noise, and noise is how a user turns notifications off for
good. An unknown duration is treated as short: a missed notification costs less
than a stream of unwanted ones. The whole path swallows its own failures — a push
service outage must never turn a successful run into a failed one.

#### The secure-context problem, said out loud

Service workers require a **secure context**: `https://…` or `http://localhost`.
The fork's documented deployment — a plain-HTTP LAN address like
`http://192.168.1.10:2026` — is not one, so on exactly the device this feature
targets, the browser API is simply **absent**.

Silently doing nothing there is the worst possible behavior: the user flips a
switch and has no way to find out why nothing happened. So each unsupported case
is detected separately and rendered with its own explanation and fix. The
insecure-origin case is checked **first**, because it makes every other API
absent too and "service workers are unavailable" would send the user hunting for
a browser setting that does not exist.

| Where you open DeerFlow | Push works? |
| --- | --- |
| `http://localhost:2026` on the machine itself | ✅ localhost is a secure context by definition |
| `https://<host>.ts.net` (Tailscale, see below) | ✅ and this is the phone case the fork is built for |
| `http://192.168.1.10:2026` (plain LAN) | ❌ explained in the UI, with the fix |

Tailscale issues a real certificate for your machine's `*.ts.net` name:

```bash
tailscale cert <your-machine>.<your-tailnet>.ts.net   # once
tailscale serve --bg https / http://127.0.0.1:2026    # proxy HTTPS to DeerFlow
```

Then open `https://<your-machine>.<your-tailnet>.ts.net` from the phone, install
it to the home screen, and enable background notifications in Settings.

| Piece | Where |
| --- | --- |
| Manifest + icons + SW | `frontend/public/manifest.webmanifest`, `frontend/public/icons/`, `frontend/public/sw.js`, `src/app/layout.tsx` |
| Browser side | `frontend/src/core/notification/push.ts`, the background-notification block in `settings/notification-settings-page.tsx` |
| Server side | `backend/app/gateway/web_push.py`, `routers/push.py`, `run_notifications.py`, the push helpers in `deerflow/config/user_ui_state.py` |
| Tests | `backend/tests/test_web_push.py`, `frontend/tests/unit/core/notification/push.test.ts` |

**Known gap, stated rather than papered over:** the mobile chat layout audit that
was scoped alongside this is *not* done. The keep-alive tab strip and the
artifact panel are still desktop-shaped on a narrow viewport. The PWA shell,
push delivery, and the install path are complete and usable; the responsive
pass on those two components remains open work.

### Note: the "older messages disappear in long conversations" investigation

The request that shipped this cost feature also asked to fix messages vanishing from long conversations. Findings, so the next pass has a head start:

- **Trigger.** `summarization.enabled: true` is the default. In a long thread, context summarization periodically compacts older turns out of the model's *active context* with `RemoveMessage(ALL)` + a hidden summary + a retained tail. That compaction is what makes older turns flicker out of the live view.
- **Why it's not (usually) permanent.** The *visible* transcript is not the checkpoint's `messages` channel — it is the run-event feed, read back by `GET /api/threads/{id}/messages/page`. Summarization rewrites the checkpoint, not the run-event feed, so the full history is still there and a page reload (or scrolling up, which cursor-paginates all the way back) reloads it. The backend page scan is well-guarded (it raises rather than silently stopping on a non-advancing cursor).
- **The existing mitigation.** During a live session, before the run-event refetch catches up, the frontend keeps a **transient history bridge** + a **rendered-message ledger** (`core/threads/hooks.ts`, issue #3825 and follow-ups #4380/#4458/#4531) that overlay the just-removed turns so they don't blink out. This is exactly the anti-loss machinery, and it has been iterated on many times.
- **Why this pass did not change it.** Without a concrete reproduction, editing that resolver — some of the most intricate, most-fixed code in the repo — risks regressing prior fixes for more than it would gain. The safe, honest call was to diagnose rather than speculatively rewrite. If loss persists **after a reload** (i.e. it is not just the transient live glitch), that points at the run-event feed itself and is a different, higher-severity bug worth capturing a reproduction for (thread id + roughly when the turns vanished).

### 17. The price is a field, not part of the name

A bundled model used to state its price twice: as `($3/15)` inside its
`display_name`, and again in a machine-readable block. One number, two places —
and they drifted the way that always drifts. A promotion could only "end" by a
human editing a string, so an expired discount kept being advertised; and a
model whose name had no pair, or whose block was missing, simply showed `—` in
the chat header with no explanation.

The price is now data, in one place:

```yaml
- name: openrouter-minimax-m3
  display_name: MiniMax M3 (OpenRouter) (p)   # a label, nothing more
  model: minimax/minimax-m3
  price:
    currency: USD        # optional, defaults to USD
    input: 0.6           # per 1M input tokens
    output: 2.4          # per 1M output tokens
    cache_hit: 0.03      # optional
  discount:
    input: 0.24
    output: 0.96
    until: 2026-08-31    # optional; inclusive, "through the 31st"
```

`price:` is the single source of truth for the chat-header cost, the spend page,
the budget caps, **and** the price shown in the model dropdown — so the number a
user reads is the number they are billed against, by construction rather than by
discipline. `wizard/providers.py::MODEL_PRICES` holds the same data for the
setup wizard, and a test asserts the two synced sources agree.

**The discount is additive and never billed against.** Spend is estimated at the
standard rate and the discount shown beside it, because a promotion can end at
any time and an under-estimate is worse than a slightly high one.

**Expiry is enforced once, at the bottom.** An expired discount is dropped in
`build_pricing_map`, so it never reaches a `ModelPricing`. Every consumer is
correct without repeating the check, and there is no second place for the two to
disagree. Do not add a downstream expiry check; that is how they drift.

**Two unknowns resolve to "expired", deliberately:** an `until` that cannot be
parsed, and a run where the current time is unavailable. The alternative —
assume it is still valid — reintroduces the bug the field removes. Over-stating
cost is corrected by the provider's bill; the other direction is silent. A
discount with no `until` is unaffected by an unknown clock, so the common case is
not punished for a problem it does not have. Not every promotion has an
announced end date, and an open-ended one is legitimate; it is a review item in
the post-sync checklist, not an audit finding, because a weekly issue nobody can
close is how that job becomes one people ignore.

**The UI is unchanged.** `core/models/sorting.ts::modelNameSegments` composes the
name and the price into the same coloured segments the embedded pair produced —
green for what you pay, red for the list price beside a live promo — now from
`GET /api/models`, which returns the resolved price with the discount already
expiry-filtered. A client therefore cannot advertise a promotion that has ended
by forgetting to compare dates.

**Nothing needs migrating.** The display-name parser is kept as the legacy path,
because `config_upgrade.py` cannot add a key inside an existing list entry: every
`config.yaml` written before this change still carries the old names and is
priced by that parser alone. Removing it would silently un-price every
pre-existing install. When a model has both, the embedded copy is stripped from
the rendered name so the price is not shown twice.

One trap worth restating: `ModelConfig` is `extra="allow"`, so `price` and
`discount` **must** stay in the model factory's exclude set. An unexcluded key is
forwarded into the provider client and from there into the completion request
payload — a cost annotation would become a malformed API call.

### 18. Gaslight mode — edit a message into a hidden conversation version

Upstream's per-turn action was **Branch**: it forked the conversation from a
completed turn into a *separate chat*, which then sat in the sidebar next to the
original as "Branch of …". That is the right primitive and the wrong surface —
trying three phrasings of the same question left four entries in the sidebar and
no indication of which was which.

This fork replaces that button with **Edit**, on **either half of a turn** — the
feature is **gaslight mode**, because the conversation carries on as though the
words had always been what you just made them. The version you were reading is
kept, and a `‹ 2/2 ›` switcher appears **on the edited message** to move between
them. One conversation stays one entry in the sidebar, however many times it is
edited. The per-message button stays labelled **Edit** — "gaslight mode" is the
name of the behaviour, in this file and in the README, not a string in the UI.

**Two halves, one mechanism, and the difference is what happens after the fork:**

- **Edit a prompt** — the conversation replays from that turn with the new
  wording, and the model answers the new question. The branch is taken at turn
  *k-1*'s terminal assistant message, so the new thread stops short of the turn
  being replaced, and the edited text is *sent* into it.
- **Edit an answer** — the branch is taken at that turn's **own** assistant
  message, so the new thread carries the question *and* its answer, and the
  Gateway writes your words in place of what the model said. **Nothing is
  re-generated**: there is no run to make, because the edited text is the answer.
  Whatever you send next is answered with those words standing in the history.
  This is the half the feature is named for.

The asymmetry is not an oversight. Re-running the turn after an answer edit would
discard the edit — the model's fresh reply would replace the words you just
wrote — so an answer edit that "regenerates" cannot keep what it was asked to
keep. The one that does nothing afterwards is the one that works.

**It is the branch endpoint underneath.** The prompt half changed nothing about
`POST /api/threads/{id}/branches`; the answer half adds one optional pair to it
(`replacement_assistant_message_id` + `replacement_assistant_text`), applied to
the copied checkpoint messages **and** to the seeded run events, because the
thread feed reads the latter — seeding it from the originals would show the old
answer the moment the feed refreshed, and the edit would read as silently
reverted. The pair is all-or-nothing, and the id must be one of the assistant
messages the branch is taken from: a half-specified or out-of-turn rewrite is
refused rather than branching without the edit that was asked for. The rest of
the fork is in how the result is presented:

1. Editing the **prompt** at turn *k* branches the thread at the terminal
   assistant message of turn *k-1*, so the new thread carries the history up to
   (but not including) the edited turn. Editing the **first** message has nothing
   to branch from, so it creates an empty thread (`POST /api/threads`) instead;
   that is the only case with no branch call, and it is the common one. Editing
   an **answer** always has something to branch from — its own turn — so it
   always takes the branch path.
2. The new thread is stamped `deerflow_edit_version: true` and is filtered out of
   every primary thread list (`filterThreadSearchResults`), so it never appears
   in the sidebar, the chats page, or the tab strip.
3. The family's **root** thread records the group in `deerflow_edit_version_groups`
   and the reader's current choice in `deerflow_edit_active_version`.
4. A **prompt** edit parks its text in session storage, replayed by whichever
   chat instance mounts the new thread — the click site navigates away, so it
   cannot send the message itself. An **answer** edit parks nothing: the branch
   already contains the rewritten answer, so a parked send would post the
   assistant's own words back as the user's next message.

**Three design points are load-bearing and easy to "fix" into bugs.**

*An answer edit must not park a pending send.* The prompt half hands its text to
the next mount through session storage (point 4 below); the answer half must not,
because the branch already contains the edited answer — parking it would post the
assistant's own words back as the user's next message. Pinned by
`edit-version-answer.dom.test.tsx`.

*The two halves need different group keys.* Editing the answer of turn *k* and
editing the prompt of turn *k+1* branch from the **same** assistant message, so a
bare message id would merge two unrelated sets of versions into one switcher
rendered on both messages. Answer groups are namespaced (`answer:<id>`); prompt
groups keep the bare id, so every group written before answer edits existed keeps
resolving unchanged.

*Groups are keyed on the assistant message they branch from, not on the turn
number.* Turn 4 of the original and turn 4 of a version that diverged at turn 2
are different conversations that happen to share an ordinal; keying on the base
message id makes them different groups automatically, because a version only
shares a base message id with threads whose history up to that point is the same
copied history. The turn index is stored alongside for display only.

*The single sidebar entry follows the reader.* `pathOfThread()` routes the root's
entry to `deerflow_edit_active_version`, and the switcher writes that key before
navigating. Without it the sidebar keeps reopening version 1 forever, which reads
as the edit having been lost — the exact failure the feature exists to avoid.

Known limits, deliberately: a turn whose predecessor ended in tool calls or a
clarification has no settled assistant message to fork from, so its **prompt**
shows no edit button (the first turn is always editable); only a turn's
**terminal** assistant message is editable, because rewriting an intermediate
tool-calling message would leave the turn describing work that never happened;
an answer still streaming is not editable, since there is nothing settled to
rewrite; deleting the root does not delete its hidden versions, which stay as
unreferenced threads; and the older latest-turn-only *in-place* edit
(`/runs/edit-regenerate/prepare`) is still implemented on both sides but is no
longer wired to any button.

### 19. The system prompt is a text box, not a black box

Every run starts from a system prompt the user never saw. It is assembled in
`backend/packages/harness/deerflow/agents/lead_agent/prompt.py` from a template
plus twelve substituted sections (soul, skills, subagents, deferred tools, ACP,
mounts, …), and nothing in the UI or the HTTP API exposed either the template or
the rendered result. Changing it meant editing Python and restarting the
Gateway.

**Settings → System prompt** puts it on screen and makes it editable:

- **Edit** shows the template in force — the built-in one, or your override —
  in a monospace editor, with the twelve placeholders listed as one-click
  insert buttons.
- **Preview** shows the *rendered* prompt: every placeholder substituted, i.e.
  the exact text the lead agent receives, with a switch for the Ultra-mode
  subagent block (which is where the available subagent roster is listed, so
  this is also the only place in the UI that names `general-purpose` / `bash`
  and any `subagents.custom_agents` you configured).
- **Reset to default** discards the override.

The override is a single Markdown file, `{base_dir}/SYSTEM_PROMPT.md`, written
atomically beside `USER.md`. `apply_prompt_template()` re-reads it on every
agent build, so a save applies from the next run with no Gateway restart, and
`make backup` picks it up with the rest of the instance state.

Three design points worth keeping if this is ever refactored:

- **The allowed placeholder set is derived from the built-in template, never
  duplicated.** `SYSTEM_PROMPT_PLACEHOLDERS` is
  `extract_placeholders(SYSTEM_PROMPT_TEMPLATE)`, so adding a `{new_section}`
  to the template automatically permits it in an override and lists it in the
  editor. A hardcoded second list would silently rot.
- **A saved prompt can change a run but must never break one.** Validation runs
  on save *and* again on every read, and `apply_prompt_template` still wraps the
  `.format()` call: an override that is hand-edited on disk, restored from an
  old backup, or written against a placeholder this version no longer supplies
  degrades to the built-in template with a warning instead of raising inside the
  agent build. Pinned by
  `backend/tests/test_system_prompt_store.py::TestApplyPromptTemplate`.
- **Omitting a placeholder is a feature, not an error.** Dropping
  `{skills_section}` is how you strip that block from the prompt, so the API
  reports `missing_placeholders` for the UI to note rather than refusing the
  save. What *is* refused: an unknown name (`KeyError` at render), a positional
  field (`IndexError` — the renderer passes keywords only), and dotted or
  indexed access like `{soul.__class__}` (renders object internals into the
  prompt).

**What a change to the prompt needs to be tested with.** The prompt is now two
things — a template *and* a stored override — so a change to either has a wider
blast radius than editing a string used to have. Anything touching
`prompt.py`'s template, `apply_prompt_template()`, or `system_prompt_store.py`
should carry:

- **A placeholder round-trip.** Adding or removing a `{placeholder}` changes the
  contract an existing saved override was written against. Adding one is safe by
  construction (the allowed set is derived), but *removing* one silently
  invalidates every override that used it — those fall back to the built-in
  template, which is the designed behaviour and must stay covered by
  `TestResolution::test_an_invalid_override_on_disk_falls_back_to_the_builtin`.
  Say so in the release note too: the user's saved prompt stops applying.
- **A render that passes `app_config` explicitly.** See the config gate in the
  mechanical checklist above — a `None` default reads the gitignored root
  `config.yaml` and splits local from CI.
- **A validation case per rejection class.** `validate_system_prompt_template`
  refuses unknown names, positional fields, dotted/indexed access, nested format
  specs, empty, and oversized. Each is a distinct failure mode at render time, so
  each keeps its own test; the nested-spec one exists specifically because field
  names alone do not prove renderability.
- **The admin gate on every route.** `TestAuthorization` covers all four. A new
  route on this router without a `require_admin_user` call is a way to read the
  prompt (and the skills roster it renders) unauthenticated.
- **The settings-page count.** `frontend/tests/unit/components/workspace/lazy-panels.test.ts`
  asserts the exact number of `dynamic()` imports in `settings-dialog.tsx`. Adding
  or removing any settings page — not just this one — must bump it.

The routes (`GET`/`PUT`/`DELETE /api/system-prompt`, `GET
/api/system-prompt/preview`) are admin-gated with the same
`require_admin_user` helper as skill and MCP management — writing the prompt has
that blast radius, and reading it returns context the prompt itself tells the
agent not to disclose. Under §5 (passwordless by default) the local user *is*
the admin, so the page works out of the box; no new `config.yaml` section was
added for it. The editor warns — but does not block — when an edit drops the
built-in **System-Context Confidentiality** section, because the consequence
(the agent will happily recite your prompt) is invisible until someone asks.

### 20. Generate an agent from work you have already done

Creating a custom agent used to mean answering an interview on
`/workspace/agents/new`. That works when you already know what agent you want —
but the best evidence for *which* agent you need is the work already sitting in
your history, and nothing read it. **Generate from history** (a button beside
**New Agent** on `/workspace/agents`) is the second way in: pick the model that
runs the analysis, pick the past conversations and/or scheduled tasks the agent
should be shaped around, and let it decide.

**Deciding "no" is the point, not a failure mode.** The verdict is one of two,
and `no_gap` — the work is one-off, too varied to specialize, or already covered
by an agent you have, named — is a first-class success. The system prompt says
out loud that this is the safe answer, because the obvious failure of a feature
like this is an eager one that proposes an agent for every selection until the
roster is five near-duplicates nobody maintains. That bias is load-bearing
enough to have its own test
(`test_build_system_instruction_biases_toward_no_gap`), so a later prompt edit
cannot quietly drop it.

When a gap *is* found you get an editable draft — name, description, full
`SOUL.md` — and **nothing is written until you press Create agent.**
`POST /api/agent-generation/analyze` is strictly read-only; creation stays on the
existing `POST /api/agents` behind an explicit click. That split is deliberate:
this is the one feature in the fork where a model's output would otherwise become
a persistent, privileged object (an agent with its own prompt and tool access)
with no human between the two.

Three properties carry the feature, and each is silent when broken:

- **Read-only analysis.** Pinned by
  `test_analyze_never_creates_the_agent_itself`, which asserts the agent store's
  `create`/`update` are never called on a `propose` verdict. Without it, a
  refactor that "helpfully" persisted the draft would look like a working feature.
- **Per-source ownership.** `require_permission`'s `owner_check` can only see a
  single `thread_id` path parameter, so it cannot cover a *list* of sources —
  this route checks each thread with
  `ThreadMetaStore.check_access(..., require_existing=True)` and each task through
  `ScheduledTaskRepo.get(..., user_id=…)`, and passes `user_id` into
  `list_messages` so the event store applies its own isolation too. Under §6
  (multi-user mode) this is what stops one user's analysis from reading another's
  conversations. Adding a new source kind means adding its ownership check —
  there is no decorator doing it for you.
- **Bounded prompt.** Threads here routinely run to hundreds of turns with
  multi-megabyte tool payloads, so sources are digested before concatenation:
  tool-result *bodies* are dropped (the calling assistant turn still names the
  tools it reached for, which is the signal without the bytes), only the most
  recent turns survive, and per-message / per-source character caps apply. The row
  fetch deliberately asks for *more* rows than the message cap, because digestion
  discards some — fetching exactly the cap leaves a busy conversation nearly empty.

**One injection surface, closed at the source.** Each digest is wrapped in a
`<source …>` block whose body is the user's own text, so a conversation
containing `</source>` could close the block early and have whatever followed
read as prompt structure. `transcript.py::neutralize_source_delimiters` escapes
that shape (with the same whitespace/attribute tolerance as the production
blocked-tag pattern) before it is embedded. This cannot be delegated to
`InputSanitizationMiddleware`: that middleware only rewrites the *lead agent's*
`ModelRequest` and never sees a one-shot `run_oneshot_llm` call — the same reason
the summarizer and memory-updater blocks are exempted in its anti-drift guard,
where `<source>` is now classified with that reasoning. Only the delimiter shape
is escaped, never every angle bracket: transcripts carry code, and mangling all
of it would cost the analysis the signal it is reading for.

The parse layer coerces a model-authored name ("Weekly Report Writer") to
`^[A-Za-z0-9-]+$` and then suffixes it (`-2`, `-3`…) against your existing
agents, so a draft can never 409 on the create route it is destined for. A
`propose` verdict carrying an empty `SOUL.md` is rejected exactly as
`setup_agent` rejects one (#3549) — an agent without a soul is unusable, and
failing loudly lets you retry instead of leaving a broken draft on screen.

**The optional goal box, and why it does not decide the verdict.** Above the
pickers is a free-text *What should this agent do?* field. It is deliberately
**optional**: the feature's original value is "read my history and tell me", and
requiring an intent statement would replace discovery with a worse version of the
bootstrap chat. When present it rides in its own `<goal>` block *before* the
transcripts — a one-line instruction buried under several thousand characters of
transcript is one the model ignores — and the system prompt gains a clause telling
it to weigh the goal as the primary signal of intent while still grounding every
claim in the sources. That clause explicitly forbids restating the goal back as
the `SOUL.md`, because an agent whose soul is the user's own sentence echoed at
them is exactly what `/workspace/agents/new` already does, better.

Crucially, **a goal does not remove the `no_gap` verdict.** Stating what you want
steers the analysis; it does not settle whether the agent should exist. Losing that
would cost the feature its best property, so `test_goal_alone_does_not_remove_the_no_gap_option`
pins that the two-verdict menu survives a stated goal.

**Overriding is a separate, explicit act.** A `no_gap` screen carries a *Generate
anyway* button, which re-runs with `force_proposal`. That mode **removes** the
`no_gap` option from the prompt rather than merely discouraging it — the user has
already been shown the overlap and decided, so re-offering the verdict would let
the model silently overrule a decision that is no longer its to make. For the same
reason `parse_analysis(require_proposal=True)` treats a `no_gap` reply as a
retryable failure rather than an answer to render. The overlapping agent is still
named and shown on the resulting draft: overriding the verdict must not mean hiding
what it collided with.

**Refining edits the draft; it does not regenerate one.** The result screen carries
a *Refine this draft* box whose guidance is sent alongside the draft **as it stands
in the form**, hand edits included, in a `<draft>` block. The revision prompt is a
separate, narrower instruction: apply the guidance and change nothing else, do not
re-litigate whether the agent should exist, do not rename it. A revision that
quietly rewrites the untouched half is indistinguishable from a regeneration and
throws away edits the user already made — which is also why a revision keeps the
draft's own name instead of re-uniquifying it against the roster, an operation that
would rename the agent out from under someone mid-edit
(`test_revision_keeps_the_drafts_own_name`). Refining with an empty box is a 422:
"make it shorter" needs something to be shorter *than*.

All three inputs are user-typed text embedded in a prompt, so `<goal>` and
`<draft>` join `<source>` in `transcript.py::BLOCK_TAG_NAMES` and are escaped by
the one shared `neutralize_block_delimiters`; both are classified in the
`test_input_sanitization_middleware.py` anti-drift guard for the same reason
`<source>` is. The goal is capped by `agent_generation.max_goal_chars` (default
2000), enforced in the route rather than as a Pydantic `max_length` so raising the
cap does not need a schema change, and mirrored in the UI so the limit is visible
while typing instead of after a round trip.

On by default via `agent_generation.enabled`, alongside `agents_api.enabled`
(§ the custom-agent API), since that is the route the accepted draft is created
through — the config endpoint reports `enabled` only when **both** are on, so the
UI never offers a draft you cannot save. Both defaulting on matches the fork's
local-trusted, passwordless posture (§5), where the local user is the admin;
`agents_api` still carries admin-equivalent write access to agent SOUL.md / config,
so a deployment that leaves the loopback model behind it should turn it back off.
The Pydantic defaults stay `false` (`agents_api_config.py`,
`agent_generation_config.py`): a config that omits the section entirely still
fails safe, and `config_upgrade.py` never overwrites a value an existing install
has already set — so this flips only what a *fresh* `make config` writes, not
anyone's hand-set choice. The
analysis call is billed to a new `agent_generation` aux-usage category (§7),
under a dedicated pseudo-thread id: one analysis spans several conversations, so
billing it to any single one would misattribute the cost, and a dedicated bucket
gives it its own row on `/workspace/spend`.

### 21. Concurrent chats — a second prompt without waiting for the first answer

§9 made a background chat *stay mounted*. This makes a background chat *keep
working*: start something slow in one conversation, leave it, and ask a second
conversation something else while the first is still thinking. Both answers
arrive.

Three things had to be true at once, and only the first was.

- **The backend already runs chats in parallel — keep it that way.** The run
  lock is scoped to one thread (`_checkpoint_thread_lock(thread_id)` in
  `runtime/runs/worker.py`), so two chats stream concurrently while two runs in
  *one* chat still take turns — which they must, since they mutate the same
  checkpoint. Nothing in the suite noticed the difference: a lock widened to a
  process-global one would have passed every existing test and quietly turned
  concurrent chats back into a queue. `backend/tests/test_concurrent_thread_runs.py`
  now pins both directions, the cross-thread case through a rendezvous that
  deadlocks (and times out) the moment the two runs are serialized.

- **Leaving a chat cancelled its run.** `on_disconnect` defaults to `"cancel"`
  (`app/gateway/run_models.py`), and leaving a chat that is not pinned as a tab
  tears its SSE stream down — so walking away from a slow answer to write the
  next prompt killed the answer you walked away to wait for. The submit paths in
  `core/threads/hooks.ts` now send `onDisconnect: "continue"` **explicitly**.
  They arguably did already: the SDK derives that value from `streamResumable`,
  which the fork passes — but `sanitizeRunStreamOptions` **strips
  `streamResumable` before the request** (the Gateway rejects it), so the
  survival of every backgrounded run rested on an SDK default keyed off a flag
  the Gateway never sees. One upstream change to that default and every
  backgrounded chat dies silently. It is asserted now, in
  `frontend/tests/unit/core/threads/run-disconnect.test.ts`, which fails if the
  option is dropped. Coming back to the chat rejoins the live run through the
  existing `reconnectOnMount` path. **This also changes what closing the browser
  does**: a run now finishes on the server instead of dying with the page —
  which is what §16's "get pinged when it's done" push notification always
  assumed, and it is the only reason a phone that locks its screen mid-run still
  gets an answer. The explicit **Stop** button is unaffected: it cancels the run
  through the cancel API, not by dropping the stream, and a runaway run is still
  bounded by the spend cap (§10).

- **Leaving a running chat dropped its live view.** Only *pinned* tabs are
  keep-alive; the current unpinned slot is replaced on navigation by design. So
  the run survived, but the chat you left went dark until you came back. Now
  `syncRoute` pins a slot it is leaving **while that slot reports a run in
  flight**, reusing the slot key so the mounted instance — stream, scroll,
  panels — is never torn down. Instances report their state through
  `reportBusy(slotKey, isStreaming)`; the strip renders a pulsing dot on a tab
  that is still answering, which is the only signal that a background chat is
  working, and its disappearance is the signal that it is done. Deliberate
  limits: a slot that has **not been promoted to a real thread id** is not
  pinned (a tab is addressed by thread id, and a brand-new chat's id is a
  client-side placeholder until the backend creates the thread), and a **full
  strip declines** rather than evicting a tab someone chose — in both cases the
  run still survives server-side and is rejoined on return. The completion
  notification also fires for a chat that is merely *not the visible slot*, not
  only for a hidden/unfocused document: a background tab is exactly the case
  where the user cannot see the run finish.

**Ollama is the part that needs a hand.** Everything above is about DeerFlow;
with a local model the queue moves into the daemon. Ollama serves
`OLLAMA_NUM_PARALLEL` requests per model at a time — **1** unless raised — and
queues the rest, so the second chat sits at "thinking" until the first finishes
even though both runs are genuinely live. Raising it is a daemon-side setting
(`systemctl edit ollama` → `Environment="OLLAMA_NUM_PARALLEL=2"`), and it has a
cost the sizing has to know about: Ollama allocates a **full KV cache per slot**
(`opts.NumCtx * numParallel` in its scheduler), so N slots divide the affordable
per-chat `num_ctx` by N. `ollama.num_parallel` in `config.yaml` is what tells
`scripts/sync-ollama-models.py` about it — it does not change the daemon, and
the two must be set to match. Set it and each model's synced `num_ctx` shrinks
accordingly, and the VRAM-contention warning (§1) counts the slots too; leave it
unset and the sizing is exactly what it was. `make doctor` reports the effective
number under **Local Models** with the fix, alongside the existing `keep_alive`
advisory — as an `ok`, not a warning, because one slot is a perfectly reasonable
choice on a small GPU.

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

**It also runs itself weekly.** `.github/workflows/upstream-sync.yml` fetches
upstream every Monday, merges (never rebases) onto a dated
`upstream-sync/<date>` branch, runs the mechanical gates below, and opens a PR
whose body is the checklist that follows — generated from this file by
`scripts/upstream_sync.py`, not copied into the workflow, so it stays current as
the fork grows. Nothing to sync means no PR.

Two behaviors are deliberate. **A conflicted merge still opens a PR**, flagged in
the title and listing every conflicted path, because a conflict is exactly when a
human is most needed and most needs to know early; the gates report as *skipped*
rather than passing, since a conflicted tree has nothing coherent to test, and
the body says not to merge it as-is. And **the job never force-pushes** — a
rejected push is reported as a warning and left alone, because the branch may
carry someone's in-progress resolution. The PR is a starting point: the feature
verification below is still a human pass, which is the whole reason the body is
a checklist rather than a green tick.

One known limitation: `GITHUB_TOKEN` may not push changes to files under
`.github/workflows/`, and upstream regularly changes theirs. When a merge touches
them the push is rejected; the PR body calls out the affected paths so the sync
can be finished locally with a personal access token.

### Post-sync feature checklist

After every upstream merge, run this checklist before pushing — passing unit tests do not prove the fork's *UI wiring* or *launch-time scripts* survived a large merge. Root commands run from the repo root; backend commands from `backend/`.

First, the mechanical gates:

- [ ] No leftover conflict markers: `git grep -nE '^(<{7}|={7}|>{7})( |$)'` returns nothing.
- [ ] Backend: `make lint && make test` (CI enforces `ruff format --check`).
- [ ] Frontend: `pnpm format && pnpm check && pnpm test`. **Watch the formatting gate:** `pnpm check` is only `eslint` + `tsc --noEmit` — it does **not** run Prettier, but CI's `lint-frontend` job (`.github/workflows/lint-check.yml`) runs `pnpm format` (`prettier --check .`) as its own step. So a change that is eslint/type-clean can still fail CI on formatting alone; always run `pnpm format` (or fix with `pnpm format:write`) before pushing. `eslint --fix` normalizes imports/optional-chains but not Prettier whitespace.
- [ ] **The backend suite passes with no `config.yaml` on disk.** `config.yaml` is gitignored: it exists on any machine that has run `make config` and on none of CI's runners. `make test` therefore tests a *different* repository state locally than in CI, and the gap is silent in the direction that matters — a test that reaches for ambient config is green here and red there. Observed live: PR #71's `apply_prompt_template` render tests called it with `app_config=None`, which falls back to `AppConfig.from_file()`; four store tests and three router tests passed locally and failed CI with `FileNotFoundError: config.yaml file not found`. The rule for new tests is to **inject the config** (`AppConfig(sandbox=SandboxConfig(use="test"))`, or `app.dependency_overrides[get_config]` for a route) rather than letting a `None` default find the developer's file. Verify the way CI sees it before pushing:

  ```bash
  mv config.yaml /tmp/config.yaml.aside      # CI has no config.yaml
  cd backend && make test
  mv /tmp/config.yaml.aside ../config.yaml   # put it back — make dev needs it
  ```

  Pinned for the prompt feature by `backend/tests/test_system_prompt_store.py::TestConfigIndependence`; the same trap applies to anything that resolves config, paths, skills, or models through a `None` default.
- [ ] **`AGENTS.md` byte budgets** — `backend/tests/test_agent_guidance_check.py` asserts every guidance file is at or under a **soft** budget (root 16 KiB, module 24 KiB, local 40 KiB, chain 80 KiB), and it is a hard assert, not a warning. The two module files run close to the line (`backend/AGENTS.md` had ~600 bytes of headroom when this was written; the root file had ~26), so *documenting a feature can fail CI on its own*. When a section does not fit, push the depth down to the nearest local guide — which has a 40 KiB budget and sits beside the code anyway — and leave a one-line pointer in the module file, the way `models/AGENTS.md` and `agents/AGENTS.md` already carry pricing and prompt detail. Check before pushing:

  ```bash
  cd backend && uv run pytest tests/test_agent_guidance_check.py -q
  ```
- [ ] `backend/uv.lock` reconciled: `cd backend && uv lock` (must include every fork extra — `camoufox`, `ollama`, `pymupdf` — alongside upstream's).
- [ ] Config schema in step: if the merge (or your own change) touched `config.example.yaml`'s **shape**, `config_version` is bumped, **the chart's copy is bumped with it** (`deploy/helm/deer-flow/values.yaml` *and* that chart's `README.md` — `scripts/check_config_version.sh` fails the `validate-chart` job otherwise, and it is easy to miss because nothing outside CI reads it), and `make config-upgrade` merges the new keys into an existing `config.yaml` without clobbering hand edits. An existing install never gets a new section otherwise — the same delivery trap the pricing blocks hit (see the cost-overview row below). Verify on a copy: `python3 scripts/config_upgrade.py <copy-of-an-older-config> config.example.yaml` must report the new field and leave the rest alone.
- [ ] **Upstream added a config section — bump `config_version` yourself.** This is not a rare case, it is the *expected* one on any sync that touches `config.example.yaml`, and it fails silently. Upstream's `config_version` sits **behind** the fork's (the fork bumps for its own sections, upstream never sees them), so upstream adding a top-level key does **not** move a version number the fork compares against. `config_upgrade.py` gates delivery on that version, so at equal versions an existing install keeps a config permanently missing the new upstream section. Observed live: the `bytedance/deer-flow@main` sync of 2026-08-12 added `mcp_tasks:` while leaving upstream's `config_version` at 33; the fork was at 36, so the upgrade was a no-op until the fork bumped to 37.

  It no longer fails *silently*: `config_upgrade.py` now compares the **shape** as well as the version, and a config that is stamped current but missing a shipped section is named on stdout with the fix. It still does not auto-deliver, and that is deliberate — the script runs on every launch path and the merge branch rewrites through `yaml.dump`, so auto-delivering would silently strip every comment from a user's config (see the limitation below). Warning loudly and leaving the file byte-identical is the trade; the version bump stays the explicit gate. Pinned by `backend/tests/test_config_upgrade_script.py::TestUpstreamSectionDelivery`. Detect it mechanically before trusting the gate above:

  ```bash
  # top-level keys upstream added that the fork's previous example did not have
  diff <(git show HEAD:config.example.yaml   | grep -oE '^[a-z_]+:') \
       <(git show upstream/main:config.example.yaml | grep -oE '^[a-z_]+:')
  ```

  Any line the merge introduces means **bump `config_version`** (plus both chart copies) even though upstream did not, then re-run the delivery check above and confirm the new key actually appears in the upgraded copy. **Known limitation, deliberately not fixed here — and it bites exactly when this gate fires.** The two upgrade paths behave differently: a *version-stamp-only* upgrade (no missing keys) is text surgery and preserves comments, pinned by `test_comments_survive_a_version_stamp_upgrade`. But the *merge* path — the one that runs precisely because a new section had to be delivered — rewrites through `yaml.dump` and drops **every comment** in the user's `config.yaml` (~3300 lines of inline documentation; measured on the `mcp_tasks` delivery above). Hand-edited *values* survive; a `.bak` is written beside the file. So the sync that finally delivers a new upstream section is also the one that strips a user's config of its documentation. Say so in the release note, and keep the `.bak` until the result has been re-read.
- [ ] **Upstream re-implemented something the fork already forked.** The fork does not only *edit* upstream files, it sometimes *replaces* one with its own module. When upstream later extracts or rewrites the same code into a **new** file, git reports no conflict — both sides "added" different files — and the fork silently ends up with two parallel implementations, only one of which is wired up. The dead copy then absorbs upstream's future improvements forever, invisibly. Observed live: upstream #4765 extracted the chat body into `frontend/src/components/workspace/chats/chat-page.tsx`, which duplicates the fork's `chat-instance.tsx` (the keep-alive tab renderer) but **lacks the fork's cost header**. Resolution taken: keep `chat-instance.tsx` as the single renderer, delete upstream's copy, and let the next sync raise a loud modify/delete conflict that forces a port. After every merge, list the files upstream added and check none of them shadows a fork module:

  ```bash
  git diff --diff-filter=A --name-only HEAD@{1}...upstream/main -- frontend/src backend/packages
  ```

  For each hit, confirm it is actually imported. An added upstream file that nothing references is the signature of this failure, not tidy dead code.
- [ ] **No price has crept back into a `display_name`, and every discount that *can* have an `until` has one.** The price is data in `price:`; a copy in the name is what used to drift, and it is what makes a discount unable to end without a human editing a string.

  ```bash
  # must print nothing: a bundled name carrying a price
  grep -nE 'display_name:.*\(\$[0-9]' config.example.yaml scripts/wizard/providers.py
  # review each discount and whether the provider has announced an end date
  grep -n -A 6 '^\s*#\?\s*discount:' config.example.yaml
  ```

  The first command is a hard gate — `test_no_bundled_model_carries_its_price_in_the_display_name` and the audit's `price_in_display_name` finding both enforce it. The second is a **review, not a gate**: several providers run open-ended promotions with no announced end date, so a missing `until` is legitimate and is deliberately *not* an audit finding (a weekly issue nobody can close is how that job becomes one people ignore). Add an `until` when the provider announces one.

  An expiry that has already passed is *not* a failure — that is the mechanism working, and the entry is inert until someone refreshes it. Removing the stale block is tidying, not a fix. Note the two fail-closed cases while you are here, because both look like "the discount vanished": an `until` that cannot be parsed, and a run where the current time is unavailable, are both treated as expired rather than eternal. Pinned by `backend/tests/test_model_price_fields.py::TestDiscountExpiry`.
- [ ] Model list still current: run the **[Auditing the model list](#auditing-the-model-list-settings--pricing)** pass (or confirm it ran recently). Provider model ids, prices, and promos drift *independently* of upstream DeerFlow, so a sync is only the calendar checkpoint — the audit itself must read each slug/price off the **provider's own page** — or, when that page cannot be reached, off several independent sources that agree exactly, recorded as corroborated in the audit log (*Where a price may come from*) (`scripts/sync-api-key-models.py --dry-run` and the model-format tests below do **not** catch a stale-but-well-formed price or a since-renamed slug, because both pass against any syntactically valid entry). Regression-gate whatever you change with `python3 scripts/sync-api-key-models.py --dry-run` + `cd backend && uv run pytest tests/test_sync_api_key_models.py tests/test_setup_wizard.py tests/test_config_integrity.py`.

Then confirm each fork feature end-to-end:

| Fork feature | How to verify it survived the merge |
| --- | --- |
| **Ollama auto-populate** (§1) | `python3 scripts/sync-ollama-models.py --dry-run --verbose` — proposes entries when the daemon is up, prints `unreachable; skipping (no changes)` and exits 0 when it's down. Reconciliation logic is pinned by `backend/tests/test_sync_ollama_models.py`. |
| **Ollama daemon lifecycle** (§1) | `cd backend && uv run pytest tests/test_ollama_lifecycle.py` covers the `keep_alive` settings parse (including the nested `keep_alive_overrides` map, whose children must **not** leak into the flat `ollama.*` settings), the resolution precedence, the rendered entry, the VRAM-contention warning, `default_local_model`, preload, and the doctor rows. Wiring: `parse_ollama_settings` / `resolve_keep_alive` / `vram_contention_warning` / `default_local_model` / `preload_model` in `scripts/sync-ollama-models.py`; the `--preload-only` **backgrounded** call in `scripts/serve.sh` right after the sync; `scripts/doctor.py::check_ollama_readiness` in the new **Local Models** section; the documented keys in `config.example.yaml`'s `ollama:` block. Model tuples grew a 4th field (`keep_alive`) — `sync()` reads the tail positionally so 2- and 3-tuple callers still work; keep that back-compatibility if the shape changes again. Preload must stay backgrounded in `serve.sh`: it blocks until the weights are loaded. Manual: set `ollama.keep_alive: 30m`, relaunch, and confirm the regenerated marker block carries `keep_alive: 30m` on every entry. |
| **API-key model auto-config** (§2) | On a *copy* of `config.example.yaml`: `ANTHROPIC_API_KEY=sk-ant-… python3 scripts/sync-api-key-models.py --config <copy> --dry-run --verbose` logs `enabled 'anthropic' model block`; with an empty env the file stays byte-identical. Pinned by `backend/tests/test_sync_api_key_models.py`. All eleven `# === BEGIN/END auto-model-config: <provider> ===` marker blocks (anthropic, openrouter, and the nine first-party home blocks: openai, xai, google, deepseek, mistral, moonshot, qwen, minimax, zai) must still be present in `config.example.yaml`, each in sync with its `*_BUNDLE_MODELS` list in `scripts/wizard/providers.py` (`HOME_API_BUNDLES` registry) and its `PROVIDERS` entry in `scripts/sync-api-key-models.py`. **The big-name shape is a rule, not a coincidence** — every lab with a public API gets its own `.env` key enabling a fuller lineup (never a lone flagship), with that flagship *also* on OpenRouter, exactly as `ANTHROPIC_API_KEY` gives six Claudes while only Fable 5 is routed. `TestFirstPartyKeyCoverage` fails if a key stops being documented in `.env.example`, a home block is trimmed to one model, a home flagship loses its OpenRouter twin, or a lab beyond Meta/NVIDIA is left routed-only. The two things no test can read — the script's `QUICK START` docstring and the README bullet advertising the keys — are step 2 of the [model audit](#auditing-the-model-list-settings--pricing). |
| **Per-thread subagent model override** (§3, Ultra mode) | `input-box.tsx` renders the second "Subagent" `ModelSelector` only under `context.mode === "ultra"`, defaulting to "Follow lead", dimming `lacksToolSupport` models. It sets `subagent_model_name` in thread context; `_CONTEXT_CONFIGURABLE_KEYS` (`app/gateway/services.py`) forwards it; `task_tool.py` applies it as `model_override` and passes it to `SubagentExecutor`. Backend plumbing pinned by `backend/tests/test_task_tool_core_logic.py::test_task_tool_uses_subagent_model_override_for_tool_loading`. |
| **Generate an agent from history** (§20) | `cd backend && uv run pytest tests/test_agent_generation.py tests/test_agent_generation_router.py` — the pure layer (digestion, caps, `<source>` delimiter escaping, name normalization, verdict parsing) and the route (feature switches, per-source ownership, dedupe/cap, verdicts, model selection, 502 paths, aux accounting). Wiring: `app/gateway/routers/agent_generation.py` registered in `app/gateway/app.py`; `packages/harness/deerflow/agents/generation/`; `config/agent_generation_config.py` wired into `AppConfig`; frontend `core/agent-generation/` + `components/workspace/agents/agent-generator.tsx` + the **Generate from history** button in `agent-gallery.tsx`. **Five asserts must not be 'simplified' away:** `test_analyze_never_creates_the_agent_itself` (the route stays read-only — a draft must never become an agent unattended), `test_build_system_instruction_biases_toward_no_gap` (a prompt edit must not drop the bias against proposing), `test_goal_alone_does_not_remove_the_no_gap_option` (a stated goal steers the analysis but must not decide the verdict), `test_force_proposal_rejects_a_no_gap_reply` (an override the model ignores is a failure, not an answer), and the delimiter-escaping tests (a transcript, goal, or draft containing `</source>`, `</goal>`, or `</draft>` must not break out of its block). Ownership survives both overrides — `test_revision_still_checks_source_ownership` and `test_forced_draft_still_checks_source_ownership` pin that skipping the verdict never skips the authorization. `<source>`, `<goal>`, and `<draft>` are classified in `test_input_sanitization_middleware.py::_EXEMPT_BLOCK_TAGS` with the reason — that guard will fail if a future block tag is added without a decision. Also note `backend/AGENTS.md` carries only a pointer: the depth lives in `packages/harness/deerflow/agents/generation/AGENTS.md`, registered in `test_agent_guidance_check.py`'s approved list. Frontend: `cd frontend && pnpm rstest run agent-generation` covers the selection and goal-cap helpers. Manual: enable both `agent_generation.enabled` and `agents_api.enabled`, pick two conversations, and confirm a `no_gap` verdict renders as a result rather than an error; then press **Generate anyway** and confirm the overlapping agent is still named on the draft, and that a **Refine** round keeps a hand edit you made to the SOUL.md before refining. |
| **Editable system prompt** (§19) | Settings → System prompt must render both tabs: **Edit** (template + one-click placeholder buttons) and **Preview** (placeholders substituted; the subagent switch changes the output). Wiring: `system-prompt-settings-page.tsx` registered in `settings-dialog.tsx` as a `dynamic()` import — `frontend/tests/unit/components/workspace/lazy-panels.test.ts` counts those imports, so adding or removing a settings page must bump that number; `core/system-prompt/{api,hooks,types}.ts`; `app/gateway/routers/system_prompt.py` registered in `app/gateway/app.py`. Backend pinned by `backend/tests/test_system_prompt_store.py` (validation, persistence, render fallback, config independence) and `backend/tests/test_system_prompt_router.py` (routes + admin gate). Run both **with `config.yaml` moved aside** — the render paths reach for it through a `None` default otherwise, which is how these first passed locally and failed CI. The full list of what a prompt change must be tested with is in §19. Manual: save an override, confirm `~/.deer-flow/SYSTEM_PROMPT.md` appears and the **next** run uses it with no restart; then hand-edit that file to `{bogus}` and confirm the run still works on the built-in prompt. |
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
| **Cost overview + aux counters** (§7) | Shared `app/gateway/pricing.py` (console + thread endpoint import it); `GET /api/threads/{id}/token-usage` returns `total_cost`/`promo_total_cost`/`currency`/per-model `cost`/`aux`; store aggregation carries the input/output/cache-read split (`new_by_model_usage_entry`); `deerflow/runtime/aux_usage.py` records memory (`agents/memory/manager.py::_host_default_extraction_callback`) + suggestions (`utils/oneshot_llm.py::run_oneshot_llm_with_usage`), **write-through to the durable `deerflow/runtime/aux_usage_store.py`** (`<DeerFlow home>/aux_usage.sqlite3`, kill switch `DEER_FLOW_AUX_USAGE_DB=0`). Frontend `token-usage-indicator.tsx` + `core/threads/token-usage.ts`. Pinned by `backend/tests/test_pricing.py`, `test_model_ids.py`, `test_aux_usage.py`, `test_aux_usage_wiring.py`, `test_thread_token_usage.py`, `tests/blocking_io/test_aux_usage.py` + `frontend/tests/unit/core/threads/token-usage.test.ts`. **The aux registry's store is a local file, so its sync API blocks.** If upstream (or a refactor) re-points the suggestions route or the `token-usage` endpoint at `record_aux_usage` / `get_thread_aux_usage` instead of the `a*` wrappers, the strict Blockbuster anchor fails — do not "fix" it by marking the anchor `allow_blocking_io`; restore the offload. Equally, do not make the memory path async: it runs on the memory updater's loop-less debounce thread, which is the whole reason the durable store is a dedicated SQLite file rather than the async runs engine. **Three things make this render `—`, and none of them raises an error.** (1) The provider-id resolution (`pricing.py::_pricing_lookup_candidates`): buckets are keyed by the *provider-reported* model id, not the `config.yaml` id, so exact-only matching nulls every cost — pinned by `test_thread_token_usage.py::test_thread_token_usage_prices_provider_reported_model_ids`. (2) A bundled model with no `pricing:` block contributes nothing, so a run on unpriced models reports no cost — pinned by `test_config_integrity.py::TestBundledModelPricing`, which fails if any bundled model loses its price or the two synced sources disagree. (3) The reported id can be *doubled*: LangChain merges a streamed response with `merge_dicts`, which concatenates equal `response_metadata` strings, and `langchain_openai` writes `model_name` on every chunk carrying a `finish_reason` — so a provider that sends more than one such chunk yields `deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro` (its `finish_reason` reads `stopstop`), which matches nothing and prices at zero. Collapsed by `deerflow/model_ids.py::normalize_reported_model_name` where a reported id is read, pinned by `test_model_ids.py` for the rule and `test_thread_token_usage.py::test_a_stream_duplicated_model_id_still_prices_and_is_named_once` end to end. If a bug report ever quotes a model id that does not exist, check that one first — the unpriced note prints whatever the bucket is keyed on, so a corrupted id shows up *as* the explanation. **The second one has a delivery trap worth reading twice:** fixing `config.example.yaml` does **not** fix an existing install. `sync-api-key-models.py` skips already-active provider blocks and `config_upgrade.py`'s `merge_missing` cannot add a key inside a list entry, so a config written before a price shipped keeps that model active and unpriced forever. That is why `pricing.py` derives the price from the `($in/out)` pair in `display_name` when no block is configured, and why `test_every_bundled_model_prices_without_its_pricing_block` requires every bundled model to survive with its block stripped. **Any future change to the bundled model blocks must answer the same question: does this reach a config that already exists?** `make doctor`'s `model pricing` check is the user-facing version — it warns, with the `—` symptom named, when nothing configured can be priced. **A fourth failure is silent rather than visible:** an *expired* promo. `promo_*_per_million` and the starred `($list → $promo*)` name are two spellings of one discount, so updating only one leaves the header advertising a price nobody is getting — pinned in both directions by `TestBundledModelPricing::test_promo_price_matches_the_starred_pair_in_the_name` (starred name with no promo block, promo block with no starred name, and a promo at or above list). Re-verify the live promos as part of step 5 of the [model audit](#auditing-the-model-list-settings--pricing); the test only checks the two sources agree with each other, never that the discount is still running. Cost is **per model everywhere**, including the promo: run buckets, and the memory/suggestions `aux` sinks, are each priced at their own model's rate, so an Ultra run with a discounted subagent and a full-price lead discounts only the subagent's tokens (`test_promo_total_is_model_aware_across_lead_subagent_and_aux`). Manual: run a turn (ideally Ultra mode, so a subagent model is involved too) and confirm the header shows a **green** dollar amount; on a discounted model the dropdown shows the green promo total beside the red standard one; if it shows `—`, the dropdown now names the unpriced model. |
| **Explicit `price:` / `discount:` fields** (§17) | `cd backend && uv run pytest tests/test_model_price_fields.py tests/test_config_integrity.py tests/test_pricing.py tests/test_audit_models.py` and `cd frontend && pnpm test sorting`. Covers: the field precedence (`price:` > legacy `pricing:` > a `($in/out)` pair in `display_name`), the additive discount, every expiry rule, that **no bundled model carries a price in its name**, that the two synced sources ship the same price, and that the dropdown renders the price from the field. Wiring: `deerflow/pricing.py` (`parse_discount_expiry`, `_raw_from_price_fields`, `_resolve_discount_window`), the `price`/`discount` fields on `ModelConfig`, the **factory exclude set** in `models/factory.py`, `ModelPriceResponse` on `GET /api/models`, `wizard/providers.py::MODEL_PRICES`, and `core/models/sorting.ts` (`resolveModelPrice`, `modelNameSegments`). **Four properties must not be "fixed" into their opposites:** (1) an expired discount is dropped in `build_pricing_map`, so it never reaches a `ModelPricing` and no consumer re-checks the window — do not add a second expiry check downstream; (2) an unparseable `until` and an unavailable clock both mean *expired*, never *eternal*; (3) `price`/`discount` must stay in the factory's exclude set, because `ModelConfig` is `extra="allow"` and an unexcluded key is forwarded into the provider client and from there into the completion request payload; (4) the display-name price **parser stays**, as the legacy path — `config_upgrade.py` cannot add a key inside an existing list entry, so every install written before this change is priced by that parser and nothing else. Manual: set a `discount:` with `until:` in the past and confirm the header and the dropdown both show only the standard rate; confirm the dropdown still shows a price at all. |
| **Model dropdown sorting/grouping** (§8) | `cd frontend && pnpm test sorting` exercises the parse/sort/group logic (`frontend/tests/unit/core/models/sorting.test.ts`). Wiring: `core/models/sorting.ts` (`parseModelPrice` promo-aware, `parseModelProvider`, `sortModels`, `groupModelsByProvider`, `demoteLast`); preference `modelPicker` in `core/settings/local.ts`; shared UI `components/workspace/model-picker-controls.tsx` (`ModelPickerControls` + `ModelPickerList` + `ModelDisplayName`) used by the lead + subagent pickers in `input-box.tsx` and the sidecar picker in `sidecar/sidecar-panel.tsx`; i18n keys in `core/i18n/locales/{en-US,zh-CN}.ts`. Manual: open the model dropdown → Sort (Default/Name/Price) + direction toggle + Group-by-provider switch appear and reorder/group the list; every row's price renders green, and a discounted entry (MiniMax M3, Claude Sonnet 5) shows its red list price beside the green promo. If a whole model name turns green or a price stays uncoloured, `splitModelNamePriceSegments` has drifted from the name format — its reassembly test is the fast check. Then **close** the dropdown on a discounted model and confirm the collapsed trigger still shows both prices at a narrow window width; if it clips, the `w-full` on the three `ModelSelectorName` triggers has been dropped (see §8 — without it the span is `fit-content` inside a `flex-col items-start` and overflows the capped button instead of truncating). This half is CSS with no unit test, so it needs the manual look. |
| **Durable chat tabs** (§9) | `cd backend && uv run pytest tests/test_user_ui_state.py tests/test_chat_tabs_settings_router.py` covers the per-user store (`deerflow/config/user_ui_state.py`, `{base_dir}/users/{user_id}/ui_state.json`) and `GET`/`PUT /api/settings/chat-tabs` (caller-scoped, **no admin gate** — unlike the multi-user-mode routes in the same router). `frontend/tests/unit/core/threads/chat-tabs-persistence.dom.test.tsx` covers the provider's boot path. If upstream restructures `workspace/layout.tsx`'s gateway-offline branch, re-check that an unreachable gateway still **keeps** the local cache instead of blanking the strip (`fetchChatTabs` returns `null` for "unknown", never `[]`), and that a server with no stored set still adopts and seeds from the local cache — that is the upgrade path for tabs pinned before server persistence existed. Manual: pin a tab, restart the stack, hard-reload with site data cleared, and confirm the tabs come back. |
| **Concurrent chats** (§21) | `cd backend && uv run pytest tests/test_concurrent_thread_runs.py` pins that two threads stream at once (the cross-thread test rendezvouses, so a process-global run lock times out instead of passing) and that two runs in one thread still serialize. `cd frontend && pnpm test run-disconnect chat-tabs-busy` covers the two frontend halves: every `thread.submit` sends `onDisconnect: "continue"` (the Gateway's default is `"cancel"`, and the SDK's own default is derived from the `streamResumable` flag `sanitizeRunStreamOptions` strips — so this must stay explicit), and `syncRoute` pins the slot it is leaving while that slot is streaming instead of dropping it (not pinned when the slot has no real thread id yet; a full strip declines). `pnpm test:e2e concurrent-chats` is the whole user story in one run: prompt chat A with its SSE response withheld, navigate to chat B, assert A became a keep-alive tab with `chat-tab-busy` visible and both `[data-slot-key]` instances mounted, send in B and get its answer while A is still unanswered, then release A and see its answer land in the background tab. Ollama half: `cd backend && uv run pytest tests/test_ollama_lifecycle.py -k "Parallel or concurrency"` — `ollama.num_parallel` parsing, CLI-over-config precedence, N slots dividing the sized `num_ctx`, slots counted in the contention warning, and the `make doctor` line. |
| **Keep-alive chat tabs** (§9) | `cd frontend && pnpm test chat-tabs` exercises the pure model (`frontend/tests/unit/core/threads/chat-tabs.test.ts`); `pnpm test:e2e chat-tabs` (`frontend/tests/e2e/chat-tabs.spec.ts`) covers drag-from-sidebar onto the empty strip / drag-reorder between chips / open-as-tab / keep-alive switch (both instances stay mounted) / close / reload persistence. Wiring: the live chat is `components/workspace/chats/chat-instance.tsx` (**fully controlled**, own provider stack via `chat-providers.tsx` with a per-instance `storageScope`); `keep-alive-chat-viewport.tsx` is mounted in `workspace-content.tsx` **above** the route inside `ChatTabsProvider` and renders one instance per slot (only the active shown, the rest `display:none`); the tab strip is `chat-tabs-bar.tsx`, which **always renders as a drop zone on chat routes** (an empty-state hint `chatTabs.dropHint` when there are no tabs yet but threads exist, so there is somewhere to drag onto — returning `null` here is the "tabs don't work" bug); `[thread_id]/page.tsx` is a thin registrar in app builds and the classic inline `<ChatInstance>` in static-demo; pure model + persistence in `core/threads/chat-tabs.ts`, state in `chat-tabs-context.tsx`; sidebar drag + **Open in tab** in `recent-chat-list.tsx`; `ChatBox` panel ids keyed by thread id (not pathname). **If upstream restructures `[thread_id]/page.tsx`,** re-extract its body onto `chat-instance.tsx` and keep the registrar/classic split; watch for a barrel (`components/workspace/chats/index.ts`) import of the client viewport into the server `workspace-content.tsx` (import the file directly to keep the `"use client"` boundary). **Upstream may also extract the same body into a *new* file rather than restructuring the route** — #4765 added `chats/chat-page.tsx`, a slot-less duplicate of `chat-instance.tsx` missing the fork's cost header. That is an *add/add*, so git reports no conflict and the duplicate silently becomes the file upstream's future chat work lands in. `chat-page.tsx` is therefore **deliberately deleted in this fork**; if a sync reintroduces it, port the delta into `chat-instance.tsx` and delete it again rather than wiring any route to it. |
| **Currency spend caps** (§10) | `cd backend && uv run pytest tests/test_spend_budget_config.py tests/test_spend_budget.py tests/test_spend_budget_middleware.py` covers the config/window math, the window aggregation (runs + auxiliary counters, owner-scoped), and the in-run warn / hard stop. Wiring: `deerflow/config/spend_budget_config.py` + the `spend_budget:` block in `config.example.yaml`; `deerflow/runtime/spend_window.py`; `app/gateway/spend_budget.py`; the **HTTP 402** admission refusal and the `__spend_budget` baseline injection in `app/gateway/services.py::start_run`; `SpendBudgetMiddleware` appended in `agents/lead_agent/agent.py` after `TokenBudgetMiddleware`; `RunJournal.current_token_usage_by_model()`; `scripts/doctor.py::check_spend_budget`; the header line via `GET /api/threads/{id}/token-usage -> spend_budget` and `core/threads/token-usage.ts::threadTokenUsageToSpendBudget`. **The pricing module moved into the harness** (`deerflow/pricing.py`) because the in-graph middleware may not import `app.*`; `app/gateway/pricing.py` is a re-export shim, and `test_pricing.py::test_gateway_shim_re_exports_the_canonical_helpers` fails if it rots. **Three invariants that are easy to break and silent when broken:** (1) an unpriced model must contribute **0**, so a fully local run is never blocked — pinned by `TestLocalModelsAreFree` and `TestLocalRunsAreNeverBlocked`; (2) in-run spend must come from the journal's **per-model** accumulator, or a cheap subagent gets billed at the lead's rate and the cap fires early on exactly the setup this fork recommends (`test_a_cheap_subagent_is_billed_at_its_own_rate`); (3) with nothing priced the feature must **self-disable with a reason**, not enforce against a permanent zero (`TestSelfDisabling`). Invariant (1) has a dark mirror: a model whose *reported* id arrived doubled (see the cost-overview row) also prices at zero, so the cap silently stops capping on exactly the provider whose stream is affected — `_message_model_name` normalizes it through `deerflow/model_ids.py`, pinned by `test_spend_budget_middleware.py::test_a_stream_duplicated_model_id_still_counts_against_the_cap`. If upstream restructures `services.py::start_run`, re-add the admission check before `create_or_reject` and the baseline injection after `inject_authenticated_user_context` — the baseline key is `__`-prefixed precisely so `build_run_config` strips a caller-supplied copy. Manual: set a tiny `daily_limit`, run a turn on a priced model (header **Budget left** goes red, the next message 402s), then repeat on a local model and confirm it is never blocked. |
| **Automated upstream sync** (see *[Upstream sync](#upstream-sync)*) | `cd backend && uv run pytest tests/test_upstream_sync.py` covers parsing this checklist out of FORK.md, the PR body for clean and conflicted merges, gate rendering (pass / fail / **skip**, which must stay distinguishable — a skipped gate reading as green is how a conflicted sync looks mergeable), the 65536-character GitHub body limit, and workflow invariants. Wiring: `scripts/upstream_sync.py`; `.github/workflows/upstream-sync.yml` (weekly + `workflow_dispatch`). **The body is generated from this section, never copied** — a copy is correct exactly once, and every fork feature added afterwards would be missing from the list meant to prove the fork still works. So the two parsers here are load-bearing: the mechanical gates come from the `- [ ]` lines and the features from the table rows below; renaming this heading or restructuring the table silently empties the PR body (`test_the_real_fork_md_parses` is the guard). Workflow invariants pinned by tests: `git merge` and never `git rebase`, no `--force` in any form, and the PR step runs under `if: always()` so a conflicted merge still surfaces. Manual: `python3 scripts/upstream_sync.py --upstream-sha abc --commit-count 1` and read the rendered body. |
| **Tailnet publish + origins** (see *Reaching the stack over Tailscale*) | `cd backend && uv run pytest tests/test_detect_tailscale.py tests/test_docker_dev_tailnet.py`. Wiring: `scripts/detect_tailscale.py`, `scripts/tailscale_lib.sh` (sourced by **both** `scripts/docker.sh` and `scripts/deploy.sh`), `docker/docker-compose.tailscale.yaml`. **Three properties must not be "fixed" into their opposites:** `scripts/docker.sh` must keep passing an **absolute** `--env-file $PROJECT_ROOT/.env` (it `cd`s into `docker/`, so without it the root `.env` stops reaching `ports:` — silently); the overlay's `${DEER_FLOW_TAILSCALE_IPV4:?…}` must keep no default (an empty value would collapse the mapping to a `0.0.0.0` wildcard); and no launch path may run `tailscale serve` or `tailscale serve reset` (Serve config is global to the machine and may hold the user's other rules). Manual: with Tailscale up, `make docker-start` prints a `📱 Tailnet:` line and the URL answers from another tailnet device; with Tailscale down, nothing extra is published. |
| **Per-step cost chart** (§7) | `cd backend && uv run pytest tests/test_thread_step_costs.py` (per-run aggregation ordering, per-model step pricing, the promo basis, memory/SQL parity) + `cd frontend && pnpm test cost-chart && pnpm test cost-per-step-chart`. Wiring: `by_run` in `aggregate_tokens_by_thread` (both stores, via `new_per_run_usage_entry`/`add_per_run_model_usage` in `runs/store/base.py`); `steps[]` on `GET /api/threads/{id}/token-usage`; `core/threads/cost-chart.ts` geometry; `components/workspace/cost-per-step-chart.tsx`. **Two properties must not be "fixed" into their opposites:** an unpriced step stays `null` (a zero draws a column on the floor that reads as "this turn was free"), and the y axis stays anchored at zero (a non-zero baseline exaggerates the gap between turns — the standard way a spend chart misleads). The last cumulative point must equal the headline total; if a change makes those two disagree, the chart is contradicting the number printed directly above it. |
| **Model & pricing audit** (see *[Auditing the model list](#auditing-the-model-list-settings--pricing)*) | `cd backend && uv run pytest tests/test_audit_models.py` covers marker-block parsing, the wizard-bundle load, each drift kind, internal consistency, source parity, the report, and the CLI exit codes. Wiring: `scripts/audit_models.py`; `.github/workflows/model-audit.yml` (weekly + `workflow_dispatch`); `scripts/fixtures/model_audit_stale_catalog.json`. **The fixture is the audit's own regression test** — the workflow's first step asserts it still produces findings, because a broken audit reports "no drift" forever and every clean run afterwards is a false all-clear. Regenerate it if the bundled roster changes (the generator is described in the fixture's `_comment`). **Two properties must not be "fixed" into their opposites:** an unreachable provider yields *zero* findings, never "every slug retired"; and the job must keep exiting 0 on findings (the issue is the signal, not a red tick). Manual: `python3 scripts/audit_models.py --catalog scripts/fixtures/model_audit_stale_catalog.json` and confirm all four drift kinds appear with a suggested diff. |
| **PWA + push notifications** (§16) | `cd backend && uv run pytest tests/test_web_push.py` plus `cd frontend && pnpm test push` cover VAPID key reuse and file mode, subscription storage (dedupe, cap, https-only), pruning a dead subscription, the run-duration threshold, and the browser-support detection. Wiring: `frontend/public/{manifest.webmanifest,sw.js,icons/}`; `metadata`/`viewport` in `src/app/layout.tsx`; `core/notification/push.ts`; `app/gateway/{web_push.py,routers/push.py,run_notifications.py}` (router registered in `app.py`, delivery composed into `deps.py::_build_run_completion_hook` **after** the scheduled-task hook); the push helpers + shared `_write_state` in `deerflow/config/user_ui_state.py`; the `webpush` extra in `packages/harness/pyproject.toml`. **Four invariants that are silent when broken:** (1) VAPID keys must be reused — regenerating invalidates every subscription with no error anywhere; (2) `vapid.json` is opened `0600`, not chmod'ed after; (3) the insecure-context branch must stay **first** in `detectPushSupport`, or a plain-HTTP LAN user is told service workers are unavailable and goes looking for a browser setting that does not exist; (4) `notify_run_completed` must never raise — it runs on the run-completion path. The service worker deliberately caches nothing; do not add asset caching without a version/cleanup strategy. Manual: open over `https://…ts.net` from a phone, install to the home screen, enable background notifications, send the test push, then run something long with the app closed. |
| **Cost-aware subagent routing** (§15) | `cd backend && uv run pytest tests/test_model_routing.py` plus `cd frontend && pnpm test lifecycle` cover requirement derivation, capability filtering, rule ordering, the precedence rule, config validation, and the card plumbing. Wiring: `deerflow/subagents/routing.py`; `deerflow/config/model_routing_config.py` + `AppConfig.model_routing`; `task_tool.py::apply_routing_policy` (called after the per-thread override is read, before the executor is built, and it also sets `model_override` so the executor's own re-resolution cannot discard the route); the `routing` key on `task_started`; `core/tasks/lifecycle.ts::normalizeRouting`. **Three invariants that are silent when broken:** (1) an explicit per-thread selection must short-circuit *before* the policy runs — "considering" it is not the same as standing down; (2) requirement derivation must stay free of any model call, or the decision becomes non-deterministic and costs money; (3) capability filtering must stay inside the preference loop, or a cheap model with `supports_tools: false` gets routed a tool-using subtask and the turn fails. `task_tool` resolves the config defensively (an unreadable `config.yaml` means "no policy", never a failed delegation) — `test_task_tool_core_logic.py` runs without a config and will catch a regression here. Manual: configure a `needs_tools: false` rule, run an Ultra-mode turn that delegates an extraction subtask, and confirm the card shows `(via <rule>)` with the reason in its tooltip. |
| **Model fallback chains** (§14) | `cd backend && uv run pytest tests/test_model_fallback.py` covers the failure/decision classification, chain resolution, the wrapper (sync + async, `bind_tools` across members), and the factory wiring. Wiring: `deerflow/models/fallback.py`; `ModelConfig.fallback` (and its entry in the factory's **exclude** set — `ModelConfig` is `extra="allow"`, so an unexcluded key is forwarded into the provider constructor and then the request payload); `deerflow/config/model_fallback_config.py` + `AppConfig.model_fallback`; `models/factory.py::_wrap_with_fallbacks`. **Four invariants that are silent when broken:** (1) unrecognized errors must keep returning `False` from `should_fall_back` — defaulting to retry doubles the cost of every bug; (2) intentional stops (interrupt, budget, guardrail, 401/403) must never fall back, or a spend cap becomes a spend multiplier; (3) chain members must keep being built with `_is_fallback_member=True`, which is what makes cycles inexpressible rather than merely unlikely; (4) the wrapper must return the serving model's result untouched, or `token_usage_by_model` bills a cloud fallback at the local model's rate of zero. Manual: point a local model's `fallback:` at a cloud model, stop the Ollama daemon mid-session, and confirm the turn completes on the fallback and the header attributes its cost to the cloud model. |
| **Backup / restore** (§13) | `cd backend && uv run pytest tests/test_backup.py` covers what goes in, the secrets exclusion and the owner-only opt-in archive, the postgres dump abort, the running-stack refusal, archive-path safety, and the mode-preserving round trip. Wiring: `scripts/backup.py`; `backup` / `restore` targets in the root `Makefile`; `/backups/` in `.gitignore`. **Three invariants that are silent when broken:** (1) credentials stay excluded by default — if `SECRET_PATTERNS` stops matching `users/*/integrations/` or `.env`, every backup starts shipping API keys; (2) the archive is opened `0600` via `os.open`, not chmod'ed afterwards, or it is briefly world-readable while being written; (3) extraction must keep `filter="tar"` — the `data` filter strips the permission bits this feature exists to preserve, so `0700` credential dirs would come back `0755`. A failed `pg_dump` must keep aborting: a backup with no database in it fails at restore time, when it is too late. Manual: `make backup`, `python3 scripts/backup.py inspect <archive>`, then restore into an empty directory and confirm threads/memory/tabs are there. |
| **Deployment exposure check** (§12) | `cd backend && uv run pytest tests/test_exposure.py` covers the bind classification, the fact resolution (`.env` vs. process env precedence, `runtime_settings.json`, sandbox mode), every tier, and the doctor rows. Wiring: `scripts/exposure.py`; `scripts/doctor.py::check_deployment_exposure` in the new **Deployment** section; the `--surface docker` call at the end of `scripts/deploy.sh` and `--surface local` at the end of `scripts/serve.sh`. **Two things are easy to break silently:** (1) the local surface must stay pinned to the wildcard — it reads `docker/nginx/nginx.local.conf`'s address-less `listen 2026;`, so if upstream gives that config an explicit address, update `LOCAL_BIND_SOURCE`/`resolve_facts` or the check will report a bind the stack does not use; (2) `classify_bind_host` must test the Tailscale ranges **before** `is_private`, because Python classifies CGNAT (100.64.0.0/10) as private and the two tiers are deliberately different. The check must never return `fail` — a deliberately exposed home lab is not a broken install. Manual: `python3 scripts/exposure.py --surface docker`, then set `BIND_HOST=0.0.0.0` in `.env` and confirm the tier moves to `open-network` and names each contributing setting. |
| **Spend history page** (§11) | `cd backend && uv run pytest tests/test_console_router.py -k ConsoleSpend` covers `GET /api/console/spend`: the three groupings (model / thread / feature) agreeing with the total, unpriced models named and sorted last, the window boundary, the no-pricing state, and the 503 on the memory backend. Wiring: `ConsoleSpendResponse` in `app/gateway/routers/console.py`; `AuxUsageStore.aggregate()`; `frontend/src/core/spend/*`; `frontend/src/app/workspace/spend/page.tsx`; the sidebar entry in `components/workspace/workspace-nav-chat-list.tsx`; i18n `spend.*` in both locales. The page must keep reusing `pricing.py` rather than recomputing cost — a second formula is how the page and the chat header start disagreeing about the same run. Manual: open **Spend** in the sidebar and confirm the tables' totals match the summary tile for the same window. |
| **Gaslight mode — edit into a hidden version** (§18) | `cd backend && uv run pytest tests/test_threads_router.py -k answer` covers the answer half end to end: the branch rewrites only the edited assistant message, the run-event seed carries the replacement (the feed reads events, not the checkpoint), a branch without the pair is byte-unchanged, and every half-specified or out-of-turn rewrite is refused. `cd frontend && pnpm test edit-version-answer && pnpm test edit-versions && pnpm test pending-edit-send && pnpm test "core/messages/utils"` covers the version model (group keying on the base message id, lineage resolution, a descendant inheriting its ancestor's position, the malformed-entry guards), the session-storage hand-off (read consumes it, so an edit is never replayed twice), and the per-turn edit anchors. `pnpm test:e2e edit-message-versions` drives the whole flow: edit a middle turn, land on the version with the earlier history and without the replaced answer, one sidebar entry pointing at the version, `2/2` on the edited message, switch back to `1/2`. Wiring: `core/threads/edit-versions.ts` (model + metadata keys); `core/threads/pending-edit-send.ts`; `useCreateEditVersion` / `useSetActiveEditVersion` in `core/threads/hooks.ts`; `createThread` in `core/threads/api.ts`; `components/workspace/chats/use-edit-versions.ts`; `components/workspace/messages/message-version-switcher.tsx`; the `onEditMessage` / `editVersionSwitchers` props on `MessageList`; the `deerflow_edit_version` filter in `core/threads/thread-search-query.ts`; the active-version hop in `pathOfThread` (`core/threads/utils.ts`). **Five things are silent when broken:** (0a) an **answer** edit must not park a pending send — the branch already carries the rewritten answer, so parking one replays the assistant's words back as the user's next message; (0b) answer groups must stay namespaced (`answer:<id>`) — editing the answer of turn *k* and the prompt of turn *k+1* branch from the same message, so a shared key renders both sets of versions on both messages; (1) groups must stay keyed on the **base message id** — keying on the turn index merges lineages that only share an ordinal; (2) `pathOfThread` must keep honouring `deerflow_edit_active_version`, or the one sidebar entry reopens version 1 forever and the edit reads as lost; (3) `takePendingEditSend` must keep *removing* on read — a non-consuming read replays the edited turn on every remount. If upstream restores a Branch button on the assistant action row, decide deliberately: this fork removed it on purpose, and two buttons that both fork the conversation is the confusing state the feature replaced. Manual: edit the first message of a chat (the no-branch path) and confirm the switcher appears, then reload from the sidebar and confirm you land back on the edited version. |

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

## Reaching the stack over Tailscale (both Docker paths)

The fork's whole point is a personal AI you reach from your phone, so tailnet access is a supported mode rather than something you re-derive after every upgrade. Both `make docker-start` and `make up` detect Tailscale on start and make the stack reachable from your other tailnet devices, with **no `.env` edit and nothing to redo after a `git pull`**.

**What broke, and why it was two bugs wearing one symptom.** The security change that made nginx loopback-only (`${BIND_HOST:-127.0.0.1}:${PORT:-2026}:2026`) is correct for LAN/WAN and silently ended tailnet access. The documented escape hatch — set `BIND_HOST` in the repo-root `.env` — then turned out not to work at all on the Docker-dev path:

- **Root `.env` never reached port interpolation.** `scripts/docker.sh` built its compose command with no `--env-file` and then `cd docker/`, so Compose resolved `${BIND_HOST}` / `${PORT}` against `docker/.env` — a file that does not exist. `env_file: ../.env` on a service only populates that *container's* environment; it has no effect on **interpolation**, which is what a `ports:` entry uses. So the setting was read, appeared to work, and changed nothing. `make up` / `scripts/deploy.sh` was already correct here (it passes `--env-file "$ENV_FILE"`), which is exactly why the two paths disagreed.
- **`BIND_HOST` is one interface, not an allowlist.** Pointing it at the tailnet IP publishes *only* that address and refuses the host's own `localhost` (the section below covers that footgun on its own).

**The fix: publish an extra port, never widen the bind.** `scripts/detect_tailscale.py` reads `tailscale status --json` and reduces it to this machine's tailnet IPv4 and MagicDNS name. When it finds one, the launch scripts append `docker/docker-compose.tailscale.yaml`, which publishes nginx on `<tailscale-ipv4>:${PORT}:2026` **in addition to** the loopback default. `100.64.0.0/10` is CGNAT — routable only inside your tailnet — so this does not expose the LAN or the internet the way `0.0.0.0` would. Compose concatenates `ports` across `-f` files, so the base mapping is untouched.

**Publishing the port is only half the fix, and the missing half is the one that looks like a Tailscale problem.** A browser on another tailnet device sends `Origin: http://100.x:2026` (or `https://<magicdns>.ts.net` through Serve). If those origins are not in the allowlists, the shell loads and every API call 403s — which reads as "Tailscale is broken", not "an origin list is short". So the same pass merges the detected origins into `GATEWAY_CORS_ORIGINS`, `DEER_FLOW_TRUSTED_ORIGINS`, and `DEER_FLOW_DEV_ALLOWED_ORIGINS`. The merge **only ever adds**: user entries keep their exact spelling and their position, duplicates are dropped on a normalized comparison so re-running a launch script is idempotent, and an operator who wrote `*` is left alone rather than silently narrowed.

The other origin-side pieces were already right and are worth knowing so they are not "fixed" into a regression: `docker/nginx/nginx.conf` maps an upstream `X-Forwarded-Proto` (added for the behind-another-TLS-proxy case, which is exactly the `tailscale serve` shape), the Gateway's `_request_origin` honours `X-Forwarded-Proto` / `X-Forwarded-Host`, and `frontend/src/dev-origins.js` already ships `100.*.*.*` and `**.ts.net` in its default dev-origin patterns.

**Two access styles, and the banner prints whichever is live:**

| URL | Requires | Notes |
| --- | --- | --- |
| `http://<tailscale-ipv4>:2026` | Detection only | The compatibility URL — what bookmarks and phones already use. Plain HTTP, so **not** a secure origin: Web Push stays unavailable on it. |
| `https://<magicdns>.ts.net` | `tailscale serve` on the host | A real certificate, so PWA install and Web Push work. Serve terminates TLS and forwards to loopback, so it needs no published port of its own. |

**Serve is never run for you, and never reset.** `tailscale serve` usually needs `--operator=$USER` or sudo, so a launch path that ran it would either prompt or fail; the banner prints the exact command instead. More importantly, Serve config is **global to the machine** and may carry rules for your other services — so DeerFlow never runs `tailscale serve reset` on stop, and `tailscale_serve_is_active` is a read-only status probe. Pinned by `test_the_library_never_runs_tailscale_serve_itself` and `test_stop_and_down_never_reset_tailscale_serve`.

**Do not use `https://100.x.y.z`.** The certificate is issued for the MagicDNS *name*, not the IP, so an HTTPS URL on the bare address is a certificate error every time. `tailnet_origins` deliberately never emits it — allowlisting an origin that can only ever fail to load helps nobody.

**Opt out** with `DEER_FLOW_TAILSCALE_PUBLISH=0` in `.env`, for a host that is on a tailnet but should not serve DeerFlow to it. Without Tailscale running, none of this applies: nothing extra is published and the default stays `127.0.0.1`.

**Look out for this when you touch the launch scripts.** The `--env-file` in `scripts/docker.sh` is load-bearing — drop it, or make it relative, and the root `.env` silently stops reaching `ports:` again. The overlay's `${DEER_FLOW_TAILSCALE_IPV4:?…}` is also deliberate: giving it a default would let `"${VAR}:${PORT}:2026"` collapse to `"${PORT}:2026"` on an empty value, which binds `0.0.0.0` — the exact wildcard the overlay exists to avoid. Pinned by `backend/tests/test_detect_tailscale.py` and `backend/tests/test_docker_dev_tailnet.py`, the latter including the regression that a repo-root `.env` `BIND_HOST` reaches the publish and that a stray `docker/.env` cannot mask it.

## Credits

All credit for the underlying system goes to the [ByteDance DeerFlow](https://github.com/bytedance/deer-flow) team. This fork wires convenience features around their work.
