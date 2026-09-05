# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, and others) when working with code in this repository. It is the source of truth; the sibling `CLAUDE.md` imports it via `@AGENTS.md`.

It is the **monorepo orientation layer**: it maps the whole repo and points to the
module guides that own the depth. For anything inside a module, read that module's
guide rather than expecting full detail here:

- **[backend/AGENTS.md](backend/AGENTS.md)** — backend depth: harness/app split, agent &
  middleware chain, sandbox, MCP, skills, memory, IM channels, persistence/migrations,
  config system, test layout.
- **[frontend/AGENTS.md](frontend/AGENTS.md)** — frontend depth: Next.js App Router layout,
  thread/streaming data flow, code style, commands.

## What is DeerFlow

DeerFlow is a LangGraph-based AI super-agent system with a full-stack architecture. The
backend runs a "super agent" with sandboxed execution, persistent memory, subagent
delegation, and extensible tools (built-in, MCP, community), all per-thread isolated. The
frontend is a Next.js chat UI. External IM platforms (Feishu, Slack, Telegram, Discord,
DingTalk) bridge into the same agent through the Gateway.

## Service Topology

A single `make dev` / Docker stack runs these cooperating services:

| Service         | Port   | Role                                                                 |
| --------------- | ------ | ------------------------------------------------------------------- |
| **Nginx**       | `2026` | Unified reverse-proxy entry point — open this in the browser        |
| **Gateway API** | `8001` | FastAPI REST API + embedded LangGraph-compatible agent runtime      |
| **Frontend**    | `3000` | Next.js web interface                                               |
| **SearXNG**     | `8088` | Self-hosted metasearch backing the default `web_search` tool. Every launch script resolves it at startup via `scripts/detect_searxng.py` — a reachable existing instance is reused, otherwise the bundled container starts. Docker stacks use the in-network `http://searxng:8080` (`DEER_FLOW_SEARXNG_BASE_URL`); the host port is loopback-only. `make searxng` / `make searxng-stop` for manual control |
| **ComfyUI**     | `8188` | Local image/video generation (`media` tools, on by default). `scripts/detect_comfyui.py` reuses a running instance, else starts the bundled container where Docker and a GPU allow. Loopback-only. Depth: FORK.md §26 |
| **Provisioner** | `8002` | Optional — only when sandbox is configured for provisioner/K8s mode |

Nginx is the single public entry: it serves the frontend and proxies `/api/langgraph/*`
to the Gateway's LangGraph runtime, rewriting it to Gateway's native `/api/*` routes; all
other `/api/*` go straight to the Gateway REST routers. See
[backend/AGENTS.md](backend/AGENTS.md) for the runtime and router detail.
It compresses HTML and configured textual assets, while deliberately leaving SSE,
fonts, images, audio, and video uncompressed at the proxy layer.

Both compose files publish that entry as `"${BIND_HOST:-127.0.0.1}:${PORT:-2026}:2026"`
— **loopback by default**. Any new published port needs an explicit bind address, or it
binds `0.0.0.0` (`test_compose_default_bind_host.py` pins every service in both files).
The published nginx port is the whole external surface; naming a non-loopback `BIND_HOST`
makes the Docker scripts co-bind `127.0.0.1` as well (`test_deploy_loopback_cobind.py`).
Full reasoning: FORK.md, *Reaching the stack over Tailscale*.

Two rules ride along, pinned by `test_docker_dev_tailnet.py`: a Docker script runs Compose
after `cd docker/`, so it must pass an absolute `--env-file <repo-root>/.env`; and tailnet
reach is *detected*, not configured. Both: FORK.md, *Reaching the stack over Tailscale*.

## Repository Map

```
deer-flow/
├── Makefile                        # Root orchestration: drives the full stack (dev/start/stop, docker, setup)
├── config.example.yaml             # Template → copy to config.yaml (gitignored) at repo root
├── extensions_config.example.json  # Template → copy to extensions_config.json (gitignored): MCP servers + skills
├── backend/                        # Python backend — see backend/AGENTS.md
│   ├── Makefile                    # Per-module backend commands (dev, gateway, test, lint, migrate-rev)
│   ├── extensions/sources/         # Deployable snapshots of locally installed Python extensions
│   ├── packages/extension-api/     # deerflow-extension-api package (import: deerflow_extension_api.*) — public extension contract
│   ├── packages/harness/           # deerflow-harness package (import: deerflow.*) — agent framework
│   └── app/                        # FastAPI Gateway + IM channels (import: app.*)
├── frontend/                       # Next.js frontend (pnpm) — see frontend/AGENTS.md
├── docker/                         # docker-compose files, nginx config, provisioner
├── skills/                         # Agent skills: public/ (committed), custom/ (gitignored)
│                                    # Managed integration skill packs are global at .deer-flow/integrations/skills/{provider}/
│                                    # Integration credentials and enabled state remain per-user
├── contracts/                      # Cross-component JSON contracts (e.g. subagent status, skill review)
├── examples/deerflow-extension-example/ # Standalone package demonstrating all extension contribution kinds
├── scripts/                        # Root orchestration scripts invoked by the Makefile — see scripts/AGENTS.md
├── tests/                          # Root-level tests (currently tests/skills/ — public skill tests)
└── docs/                           # Cross-cutting docs, plans, and design notes
```

Third-party extensions are loaded from a top-level `plugins:` list in `config.yaml`, kept
out of the API-writable `extensions_config.json` on purpose: that list causes code to be
imported, and both build hooks and extension code run with Gateway privileges, so only
trusted operator sources belong there. Manage them with `deerflow extensions
install/list/enable/disable/remove` or the root `make extension-*` wrappers; every mutation
needs a Gateway restart. The five contribution kinds, the manager transaction, the accepted
source forms and the lock discipline are in
[the extensions guide](backend/packages/harness/deerflow/extensions/AGENTS.md), with a
[reference extension](examples/deerflow-extension-example/) demonstrating all five.

Runtime config lives at the **repo root**: copy `config.example.yaml` → `config.yaml`
(main app config) and `extensions_config.example.json` → `extensions_config.json` (MCP
servers + skills). Both real files are gitignored and may be edited at runtime via the
Gateway API. Config schema and resolution order are documented in
[backend/AGENTS.md](backend/AGENTS.md).

Skill quality review note: `skills/public/skill-reviewer/` is the built-in read-only
reviewer, `scripts/review_changed_public_skills.py` is its CI gate, and CI waivers live in
`.github/skill-review-waivers.v1.json`. Ownership boundaries, the waiver rules, and the
two-step manifest dance are in
[the skills guide](backend/packages/harness/deerflow/skills/AGENTS.md).

Scheduled-task note: the MVP adds `/workspace/scheduled-tasks` plus a background scheduler
gated by `config.yaml -> scheduler.enabled`. Scheduled runs are deliberately
non-interactive; the occurrence states, the durable queue and the dispatch-time
`scheduler.recursion_limit` are in [backend/AGENTS.md](backend/AGENTS.md).

## Commands: Root vs. Module

**Root `make` targets drive the whole stack** (run from the repo root):

```bash
make setup       # Interactive setup wizard (recommended for new users)
make doctor      # Check configuration and system requirements
make config      # Generate local config files from the examples
make check       # Check that required tools are installed
make install     # Install all dependencies (frontend + backend + pre-commit hooks)
make dev         # Start all services with hot-reload (Gateway + Frontend + Nginx)
make start       # Production mode, local and optimized (SKIP_FRONTEND_BUILD=1 reuses the last build)
make stop        # Stop all running services
make up / down   # Build/stop the production Docker stack (browser at localhost:2026)
make up-start    # Restart the prod stack from pre-built images — applies config-only .env/config.yaml changes (e.g. BIND_HOST) with no rebuild
make docker-start / docker-stop / docker-logs   # Docker development environment
```

Fork-specific target families, each documented in the FORK.md section named beside it:
`make support-bundle` / `backup` / `restore ARCHIVE=` (§13), `extension-*` (the extensions
guide), `comfy-*` (§26), `sandbox-enable/disable/up/down/logs`, `fetch-browser` and
`auto-update*` (*Automatic updates*). `make searxng` / `searxng-stop` control the bundled
metasearch.

Run `make help` for the full list.

**Per-module commands drive a single module** (run inside that module):

```bash
# Backend (see backend/AGENTS.md for the full set)
cd backend && make dev        # Gateway API with reload (port 8001)
cd backend && make test       # Default backend suite; excludes live and blocking-I/O tests
cd backend && make test-blocking-io  # Strict blocking-I/O suite
cd backend && make lint       # ruff check
cd backend && make format     # ruff format

# Frontend (see frontend/AGENTS.md for the full set)
cd frontend && pnpm dev       # Dev server: Webpack by default (override with DEER_FLOW_DEV_BUNDLER=turbo)
cd frontend && pnpm check     # Format + lint + types — the gates CI runs (before committing)
cd frontend && pnpm test      # Unit tests
```

Rule of thumb: **root `make` = the full application**; **`backend/Makefile` and `frontend/`
(`pnpm`) = per-module work.**

Host-side pnpm consumers, including the root/frontend Makefiles and local diagnostic scripts, must run through `scripts/pnpm.py`. Diagnostic scripts resolve the runner and frontend directory to absolute paths before changing the child process working directory, so they remain independent of the caller's current directory. The runner preserves direct `pnpm`/`pnpm.cmd` priority, falls back to `corepack pnpm`, and is invoked from `frontend/` so Corepack honors the package-manager version pinned by that project.

### Prerequisites before `make dev`

`make dev` does **not** generate config files. First-time setup order:

```bash
make config      # copy config.example.yaml -> config.yaml and extensions_config.example.json -> extensions_config.json (both gitignored)
make install     # install frontend + backend deps and pre-commit hooks
make dev         # then start everything
```

Without `config.yaml` present, services fail to boot. `config.yaml` / `extensions_config.json`
may be edited at runtime via the Gateway API but are gitignored, so never commit them.

### Run a single test

```bash
# Backend (pytest); run one file or one test function
cd backend && python -m pytest tests/test_compose_default_bind_host.py -q
cd backend && python -m pytest tests/path/to/test.py::test_func -q

# Frontend (rstest)
cd frontend && pnpm rstest run <pattern>     # e.g. pnpm rstest run my-component
```

### Logs

- Docker stack: `make docker-logs` (or `docker compose -f docker/... logs -f <svc>`).
- Local `make dev`: each service logs to its own terminal pane. Frontend dev-server
  errors surface in the browser console at `localhost:3000`; backend tracebacks appear
  in the Gateway terminal.

## Where to Go Next

- Making a change → **[CHANGE_CYCLE.md](CHANGE_CYCLE.md)** (the procedure; the
  test list and model audit it runs live in [FORK.md](FORK.md))
- Backend work → **[backend/AGENTS.md](backend/AGENTS.md)**
- Frontend work → **[frontend/AGENTS.md](frontend/AGENTS.md)**
- Setup & install → **[Install.md](Install.md)**, **[CONTRIBUTING.md](CONTRIBUTING.md)**
- Project overview & usage → **[README.md](README.md)** (translations: `README_zh.md`,
  `README_ja.md`, `README_fr.md`, `README_ru.md`)
- Security policy → **[SECURITY.md](SECURITY.md)**
- Changes → **[CHANGELOG.md](CHANGELOG.md)**
- Cutting a release → **[RELEASING.md](RELEASING.md)**
- Candidate future work → **[roadmap.md](roadmap.md)** (fork-specific; each item is
  written as a self-contained orchestrator prompt)

## Cross-Cutting Conventions

These apply repo-wide; module guides own the module-specific detail.

- **The change cycle** — every change follows
  **[CHANGE_CYCLE.md](CHANGE_CYCLE.md)**: implement, decide whether a new test is
  owed and write it, add/edit/retire the matching row in
  [FORK.md's post-sync checklist](FORK.md#post-sync-feature-checklist), run that
  full list, run the [model audit](FORK.md#the-model-bundle-and-its-audit) only
  when it is due, then open the PR. Ending a request with "run the code change
  cycle from CHANGE_CYCLE.md" asks for exactly that, end to end.
- **Documentation update policy** — keep docs in sync with code: update `README.md` for
  user-facing changes and the relevant `AGENTS.md` for development/architecture changes in
  the same change set.
- **Test-driven development** — features and bug fixes ship with tests. Backend tests live
  in `backend/tests/` (TDD is mandatory there; see [backend/AGENTS.md](backend/AGENTS.md));
  frontend tests live in `frontend/tests/`.
- **Format before pushing** — run `make format` (backend) / `pnpm check` (frontend). Backend
  CI enforces `ruff format --check`, so formatting must be clean before a push.
- **Skill text encoding** — treat `SKILL.md` and other textual skill resources as UTF-8;
  Python utilities that read or write them must pass `encoding="utf-8"` rather than
  relying on the platform locale.
- **Version sources must stay in lockstep** — a release version must match identically in
  `backend/pyproject.toml`, `frontend/package.json`, and `deploy/helm/deer-flow/Chart.yaml`
  (`version` + `appVersion`). Pushing a `v*` git tag triggers CI that runs
  `scripts/verify_versions.sh` and **blocks all publishing** if any source drifts. Before
  bumping a version, run `scripts/bump_version.sh <ver>` (aligns all four at once) and
  `scripts/verify_versions.sh <ver>` to catch drift early. See [RELEASING.md](RELEASING.md).
- **Don't edit `CLAUDE.md`** — it only contains `@AGENTS.md`. All agent guidance changes
  belong here in `AGENTS.md`; `CLAUDE.md` is a thin import shim.
