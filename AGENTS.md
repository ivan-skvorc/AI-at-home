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
| **SearXNG**     | `8088` | Self-hosted metasearch behind the default `web_search`. `scripts/detect_searxng.py` reuses a reachable instance at startup, else starts the bundled container; Docker stacks use in-network `http://searxng:8080` (`DEER_FLOW_SEARXNG_BASE_URL`). Loopback-only. `make searxng` / `searxng-stop` |
| **ComfyUI**     | `8188` | Local image/video generation (`media` tools, on by default). `scripts/detect_comfyui.py` reuses a running instance, else starts the bundled container where Docker and a GPU allow. Loopback-only. Depth: FORK.md §26 |
| **Provisioner** | `8002` | Optional — only when sandbox is configured for provisioner/K8s mode |

Nginx is the single public entry: it serves the frontend and proxies `/api/langgraph/*`
to the Gateway's LangGraph runtime, rewriting it to Gateway's native `/api/*` routes;
all other `/api/*` go straight to the Gateway REST routers (detail:
[backend/AGENTS.md](backend/AGENTS.md)). It compresses HTML and configured textual
assets, leaving SSE, fonts, images, audio, and video uncompressed at the proxy layer.

The published nginx port is the whole external surface, and it is **loopback by
default**: any new published port needs an explicit bind address or it binds
`0.0.0.0`. That rule and three that ride with it — the non-loopback `BIND_HOST`
co-bind, Compose's absolute `--env-file`, and tailnet reach being *detected*
rather than configured — are in FORK.md, *Reaching the stack over Tailscale*,
pinned by `test_compose_default_bind_host.py`, `test_deploy_loopback_cobind.py`
and `test_docker_dev_tailnet.py`.

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

Third-party extensions load from a top-level `plugins:` list in `config.yaml`, kept out
of the API-writable `extensions_config.json` on purpose: that list causes code to be
imported, and build hooks and extension code run with Gateway privileges, so only trusted
operator sources belong there. Manage with `deerflow extensions
install/list/enable/disable/remove` or `make extension-*`; every mutation needs a Gateway
restart. Contribution kinds, the manager transaction, source forms and lock discipline:
[the extensions guide](backend/packages/harness/deerflow/extensions/AGENTS.md), with a
[reference extension](examples/deerflow-extension-example/) demonstrating all five.

Runtime config lives at the **repo root** — `config.yaml` (main) and
`extensions_config.json` (MCP servers + skills), both copied from their examples by
`make config` below, both gitignored, both editable at runtime via the Gateway API.
Schema and resolution order: [backend/AGENTS.md](backend/AGENTS.md).

Skill quality review: `skills/public/skill-reviewer/` is the built-in read-only reviewer,
`scripts/review_changed_public_skills.py` its CI gate, waivers in
`.github/skill-review-waivers.v1.json`. Ownership boundaries, waiver rules and the
two-step manifest dance: [the skills
guide](backend/packages/harness/deerflow/skills/AGENTS.md).

Scheduled tasks: `/workspace/scheduled-tasks` plus a background scheduler gated by
`config.yaml -> scheduler.enabled`. Scheduled runs are deliberately non-interactive; the
occurrence states, durable queue and dispatch-time `scheduler.recursion_limit` are in
[backend/AGENTS.md](backend/AGENTS.md).

## Commands: Root vs. Module

**Root `make` targets drive the whole stack** (run from the repo root):

```bash
make setup       # Interactive setup wizard (recommended for new users)
make doctor      # Check configuration and system requirements
make config      # Generate local config files from the examples
make check       # Check that required tools are installed
make install     # All dependencies (frontend + backend + pre-commit hooks)
make dev         # All services with hot-reload (Gateway + Frontend + Nginx)
make start       # Production mode, local (SKIP_FRONTEND_BUILD=1 reuses the last build)
make stop        # Stop all running services
make up / down   # Build/stop the production Docker stack (browser at localhost:2026)
make up-start    # Restart the prod stack from pre-built images — applies config-only
                 # .env/config.yaml changes (e.g. BIND_HOST) with no rebuild
make docker-start / docker-stop / docker-logs   # Docker development environment
```

Fork-specific families, each documented in the FORK.md section named beside it:
`support-bundle` / `backup` / `restore ARCHIVE=` (§13), `extension-*` (the extensions
guide), `comfy-*` (§26), `sandbox-enable/disable/up/down/logs`, `fetch-browser`,
`auto-update*` (*Automatic updates*), `searxng` / `searxng-stop`. `make help` lists all.

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
make config      # copy both examples to config.yaml / extensions_config.json (gitignored)
make install     # install frontend + backend deps and pre-commit hooks
make dev         # then start everything
```

Without `config.yaml` present, services fail to boot, and neither real file is ever
committed.

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
  when the request asks for one, then open the PR. Ending a request with "run the code change
  cycle from CHANGE_CYCLE.md" asks for exactly that, end to end.
- **Documentation update policy** — keep docs in sync with code: update `README.md` for
  user-facing changes and the relevant `AGENTS.md` for development/architecture changes in
  the same change set.
- **Test-driven development** — features and bug fixes ship with tests: `backend/tests/`
  (TDD mandatory there, see [backend/AGENTS.md](backend/AGENTS.md)) and `frontend/tests/`.
- **Format before pushing** — `make format` (backend) / `pnpm check` (frontend); backend CI
  enforces `ruff format --check`.
- **Skill text encoding** — treat `SKILL.md` and other textual skill resources as UTF-8;
  Python utilities reading or writing them must pass `encoding="utf-8"` rather than
  relying on the platform locale.
- **Version sources must stay in lockstep** — a release version must match identically in
  `backend/pyproject.toml`, `frontend/package.json`, and `deploy/helm/deer-flow/Chart.yaml`
  (`version` + `appVersion`); a `v*` tag runs `scripts/verify_versions.sh` in CI and
  **blocks all publishing** on any drift. Bump with `scripts/bump_version.sh <ver>` (aligns
  all four) and check with `scripts/verify_versions.sh <ver>`. See
  [RELEASING.md](RELEASING.md).
- **Don't edit `CLAUDE.md`** — it only contains `@AGENTS.md`. All agent guidance changes
  belong here in `AGENTS.md`; `CLAUDE.md` is a thin import shim.
