# Fork Notes — `deer-flow-2-local`

> **Vibe-coded disclaimer.** This fork was put together with heavy LLM assistance and only light human review. The two added features have been smoke-tested but not stress-tested. Treat this as a personal-use scratchpad, not production-grade work. Upstream is the source of truth for everything else: <https://github.com/bytedance/deer-flow>.

## What this fork adds

Two features on top of upstream, both designed around running DeerFlow locally with mixed cloud + local models:

### 1. Auto-synced Ollama models in `config.yaml`

`scripts/sync-ollama-models.py` queries the local Ollama daemon (or remote, via `OLLAMA_HOST`) and reconciles `config.yaml`'s `models:` section with whatever you have installed via `ollama pull`. Capabilities (`thinking`, `vision`, `tools`) are detected via `/api/show` and translated into DeerFlow's `supports_*` flags.

The script is **idempotent and bounded** — it only owns content between its `BEGIN ollama-sync` / `END ollama-sync` markers. Anything you've hand-edited outside that block (cloud models, custom Ollama overrides) is never touched.

It is hooked into **every launch path**, so however you start DeerFlow your Ollama list is refreshed automatically. If the daemon is unreachable, the script no-ops with no changes:

| Path | Where it runs | `base_url` written into entries |
| --- | --- | --- |
| `make dev` / `make start` (+ daemons) | `scripts/serve.sh` | `http://localhost:11434` (local runtime) |
| `make docker-start` (Docker dev) | `scripts/docker.sh`, on the host before `compose up` | `http://host.docker.internal:11434` |
| `make up` (Docker prod) | `scripts/deploy.sh`, on the host before `compose up` | `http://host.docker.internal:11434` |

**Why the base_url differs on the Docker paths.** The sync always *queries* the host's Ollama over loopback, but inside a container `localhost` is the container itself, not the host where Ollama listens. So for the Docker paths the sync writes `http://host.docker.internal:11434` (the `--container` flag; `host.docker.internal` is mapped to the host gateway via `extra_hosts` in the compose files, and is already in the gateway's `NO_PROXY`). `config.yaml` is edited on the host **before** the containers mount it, so this works even though the gateway mounts `config.yaml` read-only. A genuinely remote `OLLAMA_HOST` (a non-loopback host) is recorded verbatim on every path, since it is reachable from both host and container.

> **Host-run Ollama + Docker:** for `host.docker.internal` to reach it, Ollama must listen on all interfaces (`OLLAMA_HOST=0.0.0.0 ollama serve`), not just `127.0.0.1` (its default). Otherwise the container can resolve the host but the connection is refused.

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
```

### 2. Per-thread subagent model override (Ultra mode)

A second model selector appears next to the lead-model picker when **Ultra mode** (subagents enabled) is active. Default is "Follow lead" (subagents inherit the lead model, identical to upstream behavior). Pick anything else and `task` tool delegations route to that model instead.

Backend reads `subagent_model_name` from the LangGraph thread context in `task_tool.py` and overrides the resolved subagent model. Frontend stores the choice in `AgentThreadContext` only — **ephemeral per thread**, no localStorage. Switch threads and it resets to "Follow lead".

Models flagged `supports_tools: false` (only Ollama models that don't report the tools capability) appear at the bottom of the list, dimmed, with a "(no tool support)" annotation. Still selectable in case the flag is wrong; tool-using subagents will simply fail at runtime.

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
git merge upstream/main      # or rebase, your call
```

The fork's added files (`scripts/sync-ollama-models.py`, `scripts/ensure_camoufox.py`, the input-box dropdown JSX, the task_tool.py override) are unlikely to conflict with upstream changes since they're either new files or additive blocks on stable anchors. The launch-script hooks (Ollama sync + Camoufox fetch in `scripts/serve.sh`, `scripts/docker.sh`, `scripts/deploy.sh`, `docker/dev-entrypoint.sh`, `backend/Dockerfile`) are additive blocks on stable anchors. If upstream restructures `task_tool.py`, `input-box.tsx`, or those launch scripts, expect a small merge.

For environments that cannot reach `github.com/bytedance/deer-flow` directly (e.g. network-restricted CI or sandboxed agents), the **Mirror Upstream** workflow (`.github/workflows/mirror-upstream.yml`, manual `workflow_dispatch`) fetches upstream `main` on a GitHub runner and publishes the delta as a git bundle on the `upstream-sync-data` branch of this fork. Fetch that branch, extract the bundle parts (`cat upstream-delta.bundle.part.* > upstream.bundle`), and `git fetch <bundle> upstream-main-mirror` to get full upstream history locally. (The workflow cannot push the mirrored branch directly: `GITHUB_TOKEN` is not allowed to create or update workflow files, and upstream regularly changes theirs.)

## PDF and Office document support

Upstream supports converting PDF, DOCX, PPTX, and XLSX uploads to Markdown so the agent can read them, but the dependency (`pymupdf4llm`) is not bundled and the feature is off by default. This fork:

- Adds `pymupdf4llm` as a backend dependency so PDFs convert out of the box.
- Writes the converted Markdown under **two filenames** — `<original>.md` (upstream behavior) **and** `<original>.<ext>.md` (e.g. `report.pdf.md`). Agents tend to hallucinate one convention or the other; writing both eliminates the "file not found" failure mode. Cleanup on delete handles both names.

To turn the feature on, set `uploads.auto_convert_documents: true` in your `config.yaml`. `config.yaml` is gitignored, so the toggle ships per-install rather than in the fork.

## Local Camoufox `web_fetch` backend

Upstream's `web_fetch` tool defaults to the `jina` cloud reader. This fork adds a pluggable dispatcher and a **local, key-less, JavaScript-capable** backend built on [Camoufox](https://github.com/daijro/camoufox) (a stealth Firefox), selectable with `backend: camoufox` under the `web_fetch` tool in `config.yaml`.

Camoufox needs two things: the `camoufox` Python package **and** its browser binaries (a large one-time download). Both install **automatically on every launch path** once the backend is selected — you never have to run `make fetch-browser` by hand:

- **Local** (`make dev` / `make start`, foreground or daemon): `scripts/serve.sh` auto-detects the `camoufox` uv extra from `config.yaml`, installs it, then runs `scripts/ensure_camoufox.py` to fetch the browser.
- **Docker dev** (`make docker-start`): `docker/dev-entrypoint.sh` runs the same `ensure_camoufox.py` after `uv sync`; the download persists in the `gateway-camoufox` volume across container recreation.
- **Docker prod** (`make up`): the browser is **baked into the image** at build time (`backend/Dockerfile` builder stage runs `camoufox fetch` when the extra is present) and copied into the runtime stage, so no runtime download is needed.

Every path is **idempotent and best-effort**: an already-present browser is a no-op (checked via camoufox's `version.json`), and a failed download (e.g. offline) never blocks startup — the tool then returns an actionable install hint at call time. `make fetch-browser` still works for a manual pre-download.

## Credits

All credit for the underlying system goes to the [ByteDance DeerFlow](https://github.com/bytedance/deer-flow) team. This fork only wires up two convenience features around their work.
