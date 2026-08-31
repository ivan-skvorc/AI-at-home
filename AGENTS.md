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
| **SearXNG**     | `8088` | Self-hosted metasearch backing the default `web_search` tool. All launch scripts resolve it at startup via `scripts/detect_searxng.py`: an existing instance on the machine is reused when reachable (Docker stacks verify container reachability), otherwise the bundled container is started automatically. In the Docker stacks the Gateway uses the in-network `http://searxng:8080` (via `DEER_FLOW_SEARXNG_BASE_URL`); the host port is loopback-only. `make searxng` / `make searxng-stop` give manual control |
| **ComfyUI**     | `8188` | Local image/video generation (`media` tools, on by default). `scripts/detect_comfyui.py` reuses a running instance, else starts the bundled container where Docker and a GPU allow. Loopback-only. Depth: FORK.md §26 |
| **Provisioner** | `8002` | Optional — only when sandbox is configured for provisioner/K8s mode |

Nginx is the single public entry: it serves the frontend and proxies `/api/langgraph/*`
to the Gateway's LangGraph runtime, rewriting it to Gateway's native `/api/*` routes; all
other `/api/*` go straight to the Gateway REST routers. See
[backend/AGENTS.md](backend/AGENTS.md) for the runtime and router detail.
It compresses HTML and configured textual assets, while deliberately leaving SSE,
fonts, images, audio, and video uncompressed at the proxy layer.

Both compose files publish that entry as `"${BIND_HOST:-127.0.0.1}:${PORT:-2026}:2026"`
— **loopback by default**; a bare `"${PORT}:2026"` binds `0.0.0.0`, which is not. Any
new published port needs an explicit bind address (`test_compose_default_bind_host.py`
pins every service in both files). Nginx's `default_server` and the Gateway's
`0.0.0.0:8001` are container-internal: the published nginx port is the whole external
surface. `BIND_HOST` is one interface, not an allowlist, so naming a non-loopback one
would refuse the host's own `localhost` — both Docker scripts detect that
(`should_cobind_loopback`) and append `docker/docker-compose.loopback.yaml` to *also*
publish on `127.0.0.1`, host-only, leaving the external surface unchanged
(`test_deploy_loopback_cobind.py`). The root `PORT` is Docker ingress config only; local
orchestration pins Next.js to `3000`. Full reasoning: FORK.md, *Reaching the stack over
Tailscale*.

Two rules ride along, pinned by `test_docker_dev_tailnet.py`: a Docker script runs Compose
after `cd docker/`, so it must pass an absolute `--env-file <repo-root>/.env` or `ports:`
interpolation silently ignores the root `.env`; and tailnet reach is *detected*, not
configured — see FORK.md, *Reaching the stack over Tailscale*.

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

Third-party extensions are loaded from a top-level `plugins:` list in `config.yaml`
(operator-controlled on purpose — that list causes code to be imported, so it is deliberately
kept out of the API-writable `extensions_config.json`). Packaged extensions can contribute
middleware, task lifecycle, system-model observers, Gateway services, and FastAPI HTTP
routers; the [reference extension](examples/deerflow-extension-example/) demonstrates all
five. Manage them with `deerflow extensions install/list/enable/disable/remove` or the root
`make extension-*` wrappers. Every mutation requires a Gateway restart, and both build
hooks and extension code execute with Gateway privileges, so only trusted operator sources
belong in this path. The manager transaction, accepted source forms, lock discipline, and
contribution contract live in
[the extensions guide](backend/packages/harness/deerflow/extensions/AGENTS.md).

Runtime config lives at the **repo root**: copy `config.example.yaml` → `config.yaml`
(main app config) and `extensions_config.example.json` → `extensions_config.json` (MCP
servers + skills). Both real files are gitignored and may be edited at runtime via the
Gateway API. Config schema and resolution order are documented in
[backend/AGENTS.md](backend/AGENTS.md).

Skill quality review note: `skills/public/skill-reviewer/` is the built-in
read-only reviewer, and `scripts/review_changed_public_skills.py` is its CI gate
(with digest-pinned acknowledgments in `skills/public/.review-acknowledgments.json`).
See [the skills guide](backend/packages/harness/deerflow/skills/AGENTS.md) for the
ownership boundaries and the acknowledgment rules.

Scheduled-task note:
- The scheduled-task MVP adds a workspace page at `/workspace/scheduled-tasks` plus a background scheduler service gated by `config.yaml -> scheduler.enabled`.
- Scheduled background runs are intentionally non-interactive and execute through the normal run lifecycle. The occurrence states, the durable queue, the non-interactive rule, and the dispatch-time `scheduler.recursion_limit` are detailed in [backend/AGENTS.md](backend/AGENTS.md).

## Commands: Root vs. Module

**Root `make` targets drive the whole stack** (run from the repo root):

```bash
make setup       # Interactive setup wizard (recommended for new users)
make doctor      # Check configuration and system requirements
make support-bundle  # Generate redacted troubleshooting summary, AI issue draft, and optional zip
make backup      # Snapshot the whole instance (credentials excluded unless INCLUDE_SECRETS=1)
make restore ARCHIVE=<file>  # Restore a snapshot (refuses while the stack is running)
make config      # Generate local config files from the examples
make check       # Check that required tools are installed
make install     # Install all dependencies (frontend + backend + pre-commit hooks)
make extension-install SOURCE=...  # Install and enable a trusted Python extension
make extension-list                # List configured Python extensions
make extension-enable NAME=...     # Enable an installed extension (restart required)
make extension-disable NAME=...    # Disable without uninstalling (restart required)
make extension-remove NAME=...     # Remove package and config entry (restart required)
make dev         # Start all services with hot-reload (Gateway + Frontend + Nginx)
make start       # Production mode, local and optimized (SKIP_FRONTEND_BUILD=1 reuses the last frontend build)
make stop        # Stop all running services
make up / down   # Build/stop the production Docker stack (browser at localhost:2026)
make up-start    # Restart the prod stack from pre-built images — applies config-only .env/config.yaml changes (e.g. BIND_HOST) with no rebuild
make docker-start / docker-stop / docker-logs   # Docker development environment
make comfy-up / comfy-down / comfy-logs / comfy-models / comfy-model-add  # Local ComfyUI + its model files
make sandbox-enable / sandbox-disable           # Switch config.yaml between the containerized AIO sandbox and the local sandbox
make sandbox-up / sandbox-down / sandbox-logs   # Manage the standalone AIO sandbox container (docker/docker-compose.sandbox.yml, 127.0.0.1:8091)
make fetch-browser                              # Manually pre-download the Camoufox browser (also auto-installed on every launch path when the camoufox web_fetch backend is selected)
make auto-update                                # Update the Camoufox browser + bundled SearXNG image now (fork feature; also runs daily and on boot via a systemd --user timer / throttled on launch — see FORK.md "Automatic updates")
make auto-update-install / auto-update-uninstall # Install/remove the systemd --user timer for the update above (fires daily + on boot)
```

Production startup uses the image's pre-built Python environment with `uv run
--no-sync`, gives the Gateway a real `/health` probe, and makes `make up` wait
for that probe before printing its success banner. A readiness failure must
surface Compose status and recent Gateway logs instead of claiming the stack is
running.

Docker log and restart commands resolve `DEER_FLOW_ROOT` from the current
checkout before invoking Compose, matching the start and stop commands.

Run `make help` for the full list.

**Per-module commands drive a single module** (run inside that module):

```bash
# Backend (see backend/AGENTS.md for the full set)
cd backend && make dev        # Gateway API with reload (port 8001)
cd backend && make test       # Backend test suite
cd backend && make lint       # ruff check
cd backend && make format     # ruff format

# Frontend (see frontend/AGENTS.md for the full set)
cd frontend && pnpm dev       # Dev server: Webpack on Windows, Turbopack elsewhere (override with DEER_FLOW_DEV_BUNDLER)
cd frontend && pnpm check     # Lint + type check (run before committing)
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

- **Documentation update policy** — keep docs in sync with code: update `README.md` for
  user-facing changes and the relevant `AGENTS.md` for development/architecture changes in
  the same change set.
- **Test-driven development** — features and bug fixes ship with tests. Backend tests live
  in `backend/tests/` (TDD is mandatory there; see [backend/AGENTS.md](backend/AGENTS.md));
  frontend tests live in `frontend/tests/`.
- **Format before pushing** — run `make format` (backend) / `pnpm check` (frontend). Backend
  CI enforces `ruff format --check`, so formatting must be clean before a push.
- **Version sources must stay in lockstep** — a release version must match identically in
  `backend/pyproject.toml`, `frontend/package.json`, and `deploy/helm/deer-flow/Chart.yaml`
  (`version` + `appVersion`). Pushing a `v*` git tag triggers CI that runs
  `scripts/verify_versions.sh` and **blocks all publishing** if any source drifts. Before
  bumping a version, run `scripts/bump_version.sh <ver>` (aligns all four at once) and
  `scripts/verify_versions.sh <ver>` to catch drift early. See [RELEASING.md](RELEASING.md).
- **Don't edit `CLAUDE.md`** — it only contains `@AGENTS.md`. All agent guidance changes
  belong here in `AGENTS.md`; `CLAUDE.md` is a thin import shim.
