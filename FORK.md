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
| `ANTHROPIC_API_KEY` | Claude **Fable 5**, **Opus 5**, **Opus 4.8**, **Sonnet 5**, **Haiku 4.5** | direct Anthropic API (`langchain_anthropic:ChatAnthropic`) |
| `OPENROUTER_API_KEY` | Claude **Fable 5**, Claude **Opus 5**, **Grok 4.5**, **GPT-5.6 Sol**, **GPT-5.3 Codex**, **Gemini 3.6 Flash**, **Llama 4 Maverick**, **MiniMax M3**, **Qwen3.7 Max**, **Kimi K3**, **Mistral Large 3**, **DeepSeek V4 Pro**, **GLM-5.2**, **Nemotron 3 Ultra** | OpenRouter (`langchain_openai:ChatOpenAI` + `base_url`) |

Both keys present enables both blocks (Fable and Opus 5 each appear twice — once direct, once via OpenRouter — under distinct `name:`s). The four newest Claude models (Fable 5, Opus 5, Opus 4.8, Sonnet 5) use adaptive thinking (Haiku takes an explicit budget); every entry ships `supports_thinking: true` so DeerFlow's thinking toggle actually engages.

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

#### Which models to keep in the bundle

The shipped set is deliberately a curated "big names" list, not a catalog dump. When refreshing it, keep to this shape:

- **Anthropic (direct key):** all current Claude models — Fable 5, Opus 5, Opus 4.8, Sonnet 5, Haiku 4.5. This is the whole current lineup; add a legacy-but-active model (e.g. Opus 4.7/4.6, Sonnet 4.6) only if you specifically need to pin it.
- **OpenRouter:** the current flagship from each major lab plus a few strong/cheaper alternates — one main entry each for **xAI** (Grok), **OpenAI** (GPT, plus the Codex agentic-coding variant), **Google** (Gemini), **DeepSeek**, **Moonshot/Kimi**, and the big Chinese open models (**Qwen**, **Zhipu/GLM**, **MiniMax**); optionally Meta (Llama), Mistral, and NVIDIA (Nemotron). Prefer one primary tier per lab; sprinkle in a cheaper/faster tier (a Flash/mini/lite variant) rather than listing every size.
- **Cost spread:** keep at least one genuinely cheap option live (Haiku, Gemini Flash, GLM/MiniMax) so the mixed-model cost story in this doc holds in practice.

Rule of thumb: one primary model per big-name lab, a couple of secondary/cheaper ones, and nothing that isn't a recognizable flagship or a deliberate budget pick. Trim aggressively — a long list dilutes the picker and the auto-config.

#### Keep the model format current, and free of deprecated fields

Provider APIs change model IDs and request-shape rules faster than upstream DeerFlow does, so a refresh must re-validate the *format*, not just swap names. Before committing a model-block change:

- **Model IDs / slugs** — confirm each `model:` is the exact current id (Anthropic bare ids like `claude-opus-5`; OpenRouter `provider/model` slugs). A wrong or unreleased id fails at request time, not at load. When unsure of a live slug, verify against the provider's / OpenRouter's catalog rather than guessing.
- **Thinking config matches the model family** — the adaptive Claude models (Fable 5, Opus 5, Opus 4.8, Sonnet 5) reject the old `thinking: {type: enabled, budget_tokens: N}` form with a 400; use `type: adaptive`. Only pre-adaptive models (Haiku 4.5 and older) still take `budget_tokens` (min 1024, `< max_tokens`). Fable 5 additionally rejects `type: disabled`, so its disabled state must stay on adaptive. Sampling params (`temperature`/`top_p`/`top_k`) are rejected on the newest Claude models — don't add them to those entries.
- **No deprecated fields** — drop anything the provider has removed (e.g. `budget_tokens` on adaptive models, `output_format` in favour of `output_config.format`, retired tool-version strings). If a `supports_*` flag no longer maps to a real capability, remove it.
- **`supports_thinking: true` is load-bearing** — without it DeerFlow silently runs the model in non-thinking mode even with the UI toggle on.
- **Pricing (optional) uses one currency** — the console cost display sums across models, so every `pricing:` block must share a currency; mixed currencies disable the feature. Prices are per 1M tokens (`input_per_million` / `output_per_million`, optional `input_cache_hit_per_million`). The shipped Anthropic entries carry USD list prices as a worked example.
- **Regression-test the change** — `python3 scripts/sync-api-key-models.py --dry-run` must still uncomment the block cleanly, and `cd backend && uv run pytest tests/test_sync_api_key_models.py tests/test_config_integrity.py` must stay green.

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
- [ ] Frontend: `pnpm check && pnpm test`.
- [ ] `backend/uv.lock` reconciled: `cd backend && uv lock` (must include every fork extra — `camoufox`, `ollama`, `pymupdf` — alongside upstream's).

Then confirm each fork feature end-to-end:

| Fork feature | How to verify it survived the merge |
| --- | --- |
| **Ollama auto-populate** (§1) | `python3 scripts/sync-ollama-models.py --dry-run --verbose` — proposes entries when the daemon is up, prints `unreachable; skipping (no changes)` and exits 0 when it's down. Reconciliation logic is pinned by `backend/tests/test_sync_ollama_models.py`. |
| **API-key model auto-config** (§2) | On a *copy* of `config.example.yaml`: `ANTHROPIC_API_KEY=sk-ant-… python3 scripts/sync-api-key-models.py --config <copy> --dry-run --verbose` logs `enabled 'anthropic' model block`; with an empty env the file stays byte-identical. Pinned by `backend/tests/test_sync_api_key_models.py`. The `# === BEGIN/END auto-model-config: <provider> ===` marker blocks must still be present in `config.example.yaml`. |
| **Per-thread subagent model override** (§3, Ultra mode) | `input-box.tsx` renders the second "Subagent" `ModelSelector` only under `context.mode === "ultra"`, defaulting to "Follow lead", dimming `lacksToolSupport` models. It sets `subagent_model_name` in thread context; `_CONTEXT_CONFIGURABLE_KEYS` (`app/gateway/services.py`) forwards it; `task_tool.py` applies it as `model_override` and passes it to `SubagentExecutor`. |
| **Follow-up suggestions off by default + model picker** (§4) | `core/settings/local.ts` defaults `suggestions.enabled=false`; Settings → Suggestions page writes `suggestions.{enabled,modelName}`; `input-box.tsx` gates on `suggestionsConfig?.enabled && localSettings.suggestions.enabled` and sends `n: maxFollowupSuggestions`, `model_name: suggestionsModelName ?? context.model_name`. |
| **Memory toggle (off by default)** | `core/settings/local.ts` defaults `memory.enabled=false`; Settings → Memory page writes it; `core/threads/hooks.ts` sends `memory_enabled` in run context; `agents/lead_agent/agent.py::_apply_memory_preference` consumes it (operator `memory.enabled: false` still wins). Defaults pinned by `frontend/tests/unit/core/settings/local.test.ts`. |
| **Camoufox default `web_fetch`** | `config.example.yaml` web_fetch entry has `backend: camoufox`; `scripts/detect_uv_extras.py` emits `--extra camoufox` for it (pinned by `test_detect_uv_extras.py`). |
| **SearXNG default `web_search`** | active `web_search` tool uses `deerflow.community.searxng.tools:web_search_tool`; `scripts/detect_searxng.py` still resolves it. |
| **PDF/Office conversion** | `pymupdf` extra (`pymupdf4llm`) present in `backend/packages/harness/pyproject.toml`. |
| **Reduce animations (default on)** | `core/appearance` (`useReducedMotion`) + `components/reduce-motion-effect.tsx`; default pinned by `local.test.ts`. |
| **Full sandbox runs** | `skills/public/repo-runner/`; `sandbox.expose_ports` / `extra_capabilities` in `config.example.yaml` and honored by `LocalContainerBackend`. |
| **First-run config seeding** | `scripts/serve.sh::seed_missing_config` (and the equivalents in `deploy.sh` / `docker.sh`). |

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

## Full sandbox runs (clone a repo and run/debug it)

This fork rounds out the containerized AIO sandbox into a first-class "hand it a GitHub link, watch it clone, install, and debug the program" workflow. Everything here builds on upstream's `AioSandboxProvider` (root inside the container, private-repo clone via a forwarded `GITHUB_TOKEN`); the fork adds the ergonomics that were missing:

- **One-command per-thread container mode.** `make sandbox-enable MODE=container` writes an `AioSandboxProvider` block **without** a `base_url`, so DeerFlow spawns one container per thread and mounts that thread's user-data dirs. Unlike the shared external container (`make sandbox-up`), `/mnt/user-data` is host-backed, so uploads, outputs, and `present_files` all work. `make sandbox-enable` (no MODE) still writes the external block.
- **Timeouts that survive real installs.** `sandbox.bash_command_timeout` is now forwarded to the AIO sandbox per command (idle timeout on the shell path, wall-clock hard timeout on the env-bearing path), not just to the host-local sandbox. A long `pip install`/`cargo build` no longer dies at the old fixed 600s. DeerFlow warns once if you set it above `request_timeout` (the HTTP client would abort first) — raise both together.
- **Reach the program under debug from your browser.** `sandbox.expose_ports: [8000]` publishes container ports 1:1 to the host loopback in local container mode, so a dev server the agent starts is reachable at `localhost:8000`.
- **Native debuggers.** `sandbox.extra_capabilities: [SYS_PTRACE]` adds `--cap-add` flags (Docker only) so `gdb`/`strace` can attach.
- **A `repo-runner` public skill** (`skills/public/repo-runner/`) that encodes the whole loop: clone into the workspace → detect the toolchain → install deps in an isolated venv/`node_modules` → run (backgrounding servers) → iterate on failures → report reproducible commands.

The `expose_ports` / `extra_capabilities` keys are local-container-mode only; in external/provisioner mode they are warned-as-ignored (declare `ports:` / `cap_add:` in `docker/docker-compose.sandbox.yml` instead). Packages installed outside the mounted workspace (apt, global pip) are still lost when a container is recycled, so keep a project's dependencies in a workspace-local venv — the skill does this by default. Raise `sandbox.idle_timeout` to keep a warmed-up debug environment alive longer between turns.

## Credits

All credit for the underlying system goes to the [ByteDance DeerFlow](https://github.com/bytedance/deer-flow) team. This fork wires convenience features around their work.
