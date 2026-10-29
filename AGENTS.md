# AGENTS.md

This is the source of truth for repository agent guidance; `CLAUDE.md` imports it via `@AGENTS.md`.

**Before making any repository change, read and follow [CHANGE_CYCLE.md](CHANGE_CYCLE.md).**
It applies automatically to every change request, whichever agent, model or
provider runs it, with no special trigger or agent-specific opt-in: run existing
tests, add coverage only where needed, review and remove unnecessary tests, and
open a pull request. Read the applicable nested
`AGENTS.md` files too; delegated agents follow the same guidance, and the lead
agent owns final validation and the PR. For tools that do not discover `AGENTS.md`,
configure them to read this file before working (see [CONTRIBUTING.md](CONTRIBUTING.md#development-workflow)).

This **monorepo orientation layer** maps the repo. For module details, read its guide:

- **[backend/AGENTS.md](backend/AGENTS.md)** — backend depth: harness/app split, agent &
  middleware chain, sandbox, MCP, skills, memory, IM channels, persistence/migrations,
  config system, test layout.
- **[frontend/AGENTS.md](frontend/AGENTS.md)** — frontend depth: Next.js App Router layout,
  thread/streaming data flow, code style, commands.

## What is DeerFlow

DeerFlow combines LangGraph and Next.js with thread-isolated sandbox execution,
memory, subagents and extensible tools. IM channels connect through the Gateway.

## Service Topology

A single `make dev` / Docker stack runs these cooperating services:

| Service | Port | Role |
| --- | --- | --- |
| **Nginx** | `2026` | Unified reverse-proxy entry point — open this in the browser |
| **Gateway API** | `8001` | FastAPI REST API + embedded LangGraph-compatible agent runtime |
| **Frontend** | `3000` | Next.js web interface |
| **SearXNG** | `8088` | Self-hosted metasearch behind the default `web_search`. `scripts/detect_searxng.py` reuses a reachable instance at startup, else starts the bundled container; Docker stacks use in-network `http://searxng:8080` (`DEER_FLOW_SEARXNG_BASE_URL`). Loopback-only. `make searxng` / `searxng-stop` |
| **ComfyUI** | `8188` | Local image/video generation (`media` tools, on by default). `scripts/detect_comfyui.py` reuses a running instance, else starts the bundled container where Docker and a GPU allow. Loopback-only. Depth: FORK.md §26 |
| **Provisioner** | `8002` | Optional — only when sandbox is configured for provisioner/K8s mode |

Nginx is the single public entry: it serves the frontend and proxies `/api/langgraph/*`
to the Gateway's LangGraph runtime, rewriting it to Gateway's native `/api/*` routes;
all other `/api/*` go straight to the Gateway REST routers (detail:
[backend/AGENTS.md](backend/AGENTS.md)). It compresses HTML and configured textual
assets, leaving SSE, fonts, images, audio, and video uncompressed at the proxy layer.

Keep the dedicated `/api/threads/{thread_id}/browser/stream` WebSocket regex before
the generic threads regex in Docker, local and Helm nginx configs. Upgrade headers
and the 600s read timeout are pinned by `backend/tests/test_nginx_browser_websocket.py`.

The published nginx port is the whole external surface, and it is **loopback by
default**: any new published port needs an explicit bind address or it binds
`0.0.0.0`. That rule and three that ride with it — the non-loopback `BIND_HOST`
co-bind, Compose's absolute `--env-file`, and tailnet reach being *detected*
rather than configured — are in FORK.md, *Reaching the stack over Tailscale*,
pinned by `test_compose_default_bind_host.py`, `test_deploy_loopback_cobind.py`
and `test_docker_dev_tailnet.py`.

Provisioner PVC mode declares `USERDATA_PVC_NAME` once as `user-data`; extra and
Lark broker credential mounts reuse it with their existing subPaths and read-only
flags. Keep credential mounts broker-only and keep distinct volumes in hostPath mode.

## Repository Map

```
deer-flow/
├── Makefile  # Root orchestration: drives the full stack (dev/start/stop, docker, setup)
├── config.example.yaml  # Template → copy to config.yaml (gitignored) at repo root
├── extensions_config.example.json  # Template → copy to extensions_config.json (gitignored): MCP servers + skills
├── backend/  # Python backend — see backend/AGENTS.md
│   ├── Makefile  # Per-module backend commands (dev, gateway, test, lint, migrate-rev)
│   ├── extensions/sources/  # Deployable snapshots of locally installed Python extensions
│   ├── packages/extension-api/  # deerflow-extension-api package (import: deerflow_extension_api.*) — public extension contract
│   ├── packages/harness/  # deerflow-harness package (import: deerflow.*) — agent framework
│   └── app/  # FastAPI Gateway + IM channels (import: app.*)
├── frontend/  # Next.js frontend (pnpm) — see frontend/AGENTS.md
├── docker/  # docker-compose files, nginx config, provisioner
├── skills/  # Agent skills: public/ (committed), custom/ (gitignored)
│  # Managed integration skill packs are global at .deer-flow/integrations/skills/{provider}/
│  # Integration credentials and enabled state remain per-user
├── contracts/  # Cross-component JSON contracts (e.g. subagent status, skill review)
├── examples/  # Extension examples: deerflow-extension-{example,bookmarks,agent-teams,jev-*}
├── scripts/  # Root orchestration scripts invoked by the Makefile — see scripts/AGENTS.md
├── tests/  # Root-level tests (currently tests/skills/ — public skill tests)
└── docs/  # Cross-cutting docs, plans, and design notes
```

Third-party extensions load from operator-controlled `config.yaml -> plugins:`.
This imports code, so the list stays outside API-writable `extensions_config.json`.
Extensions contribute middleware, lifecycle observers, Gateway services, FastAPI
routers, and experimental full-stack plugins. Use
`deerflow extensions install/upgrade/list/enable/disable/remove` or root
`make extension-*` wrappers (`upgrade` keeps the extension's config). Restart
Gateway after every mutation. Build hooks and extension code run with Gateway
privileges; use only trusted operator sources. Transactions, accepted source
forms, locking, and contribution contracts:
[extensions guide](backend/packages/harness/deerflow/extensions/AGENTS.md).
User manual: `frontend/src/content/{en,zh}/harness/extensions/`.

**Extension-first evaluation** — before implementing a feature by editing core code,
evaluate whether it can ship as a packaged extension through the contribution points
above. Stay in core for bug fixes and for changes to the agent loop, memory, context
compaction, or authentication. If existing hooks cannot express the feature, add a
generic hook to the extension contract plus an extension that uses it — do not
hard-code business logic into core. Working examples:
`examples/deerflow-extension-{example,bookmarks,agent-teams}`.
[Workflow guide](examples/deerflow-extension-workflows/AGENTS.md): public
AgentRuns; POSIX, one process/store; approval and session-authorized recovery; uncertain admissions need reconciliation;
no multi-Gateway failover or hard currency budget.

Knowledge management/space policy: `examples/deerflow-extension-knowledge-{management,platform}/`
(scoped `AGENTS.md`, `CONTRACT.md`). Use existing plugin/router/principal contracts;
retrieval stays independent. Space policy intersects administrator/resource/operation
and upstream grants, never grants chat access. SQLite holds plugin-owned space policy.
Provider stages are not completion evidence; reconcile uncertain writes, never retry.

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
[backend/AGENTS.md](backend/AGENTS.md). `scheduler.tool_enabled` (default off) offers
owner-bound schedule tools through Gateway capability admission; a scheduled turn may
only stop its own schedule, and one occurrence's goal success does not end a recurring one.

## Commands: Root vs. Module

**Root stack commands** (from repo root):

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

Production uses image Python (`uv run --no-sync`) and `exec` for SIGTERM;
Compose sets `init: true` (`backend/tests/test_gateway_sigterm_delivery.py`).
`make up` waits for Gateway `/health`; failures show Compose status and Gateway logs.

Fork-specific families, each documented in the FORK.md section named beside it:
`support-bundle` / `backup` / `restore ARCHIVE=` (§13), `extension-*` (the extensions
guide), `comfy-*` (§26), `sandbox-enable/disable/up/down/logs`, `fetch-browser`,
`auto-update*` (*Automatic updates*), `searxng` / `searxng-stop`, `drift-eval` (§25).
`make help` lists all.

**Module commands** (from each module):

```bash
# Backend (see backend/AGENTS.md for the full set)
cd backend && make dev        # Gateway API with reload (port 8001)
cd backend && make test       # Four parallel shards; excludes live and blocking-I/O tests
cd backend && make test-blocking-io  # Strict blocking-I/O suite
cd backend && make lint       # ruff check
cd backend && make format     # ruff format

# Frontend (see frontend/AGENTS.md for the full set)
cd frontend && pnpm dev       # Dev server: Webpack by default (override with DEER_FLOW_DEV_BUNDLER=turbo)
cd frontend && pnpm check     # Format + lint + types — the gates CI runs (before committing)
cd frontend && pnpm test      # Unit tests
```

Host pnpm calls use `scripts/pnpm.py`: native Windows tries `pnpm.cmd` before
`pnpm`; POSIX reverses the order. Its Corepack fallback applies the same ordering
to `corepack.cmd` and `corepack`. The runner operates from `frontend/` so
Corepack honors its pinned package-manager version.

### Prerequisites before `make dev`

Run `make config`, then `make install`, then `make dev` on first setup.
`make dev` requires existing config; both runtime configs are API-editable and
gitignored. Never commit them.

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
- Local `make dev`: Gateway and frontend output goes to
  `logs/gateway.log` and `logs/frontend.log` in the repository root.
  Run `tail -f logs/gateway.log logs/frontend.log` there to follow both.

## References

- Making a change → **[CHANGE_CYCLE.md](CHANGE_CYCLE.md)** (the procedure; the
  test list and model audit it runs live in [FORK.md](FORK.md))
- Backend work → **[backend/AGENTS.md](backend/AGENTS.md)**
- Frontend work → **[frontend/AGENTS.md](frontend/AGENTS.md)**
- Setup & install → **[Install.md](Install.md)**, **[CONTRIBUTING.md](CONTRIBUTING.md)**
- Project overview & usage → **[README.md](README.md)** (translations: `README_zh.md`,
  `README_ja.md`, `README_fr.md`, `README_ru.md`, `README_pt.md`, `README_ko.md`)
- Security policy → **[SECURITY.md](SECURITY.md)**
- Changes → **[CHANGELOG.md](CHANGELOG.md)**
- Cutting a release → **[RELEASING.md](RELEASING.md)**
- Candidate future work → **[roadmap.md](roadmap.md)** (fork-specific; each item is
  written as a self-contained orchestrator prompt)

## Cross-Cutting Conventions

Repo-wide conventions:

- **The change cycle** — every change follows
  **[CHANGE_CYCLE.md](CHANGE_CYCLE.md)** automatically. Maintain the tests and
  [FORK.md's post-sync checklist](FORK.md#post-sync-feature-checklist), run existing
  checks at the scope step 5 requires, then commit, push, and open the PR. The full
  checklist is due for upstream merges or broad changes; the
  [model audit](FORK.md#the-model-bundle-and-its-audit) runs only when requested.
- **Documentation update policy** — keep docs in sync with code: update `README.md` for
  user-facing changes and the relevant `AGENTS.md` for development/architecture changes in
  the same change set.
- **The guidance budget** — `scripts/check_agent_guidance.py` caps each `AGENTS.md` and
  the *effective chain* an agent inherits at that path. When a sync pushes a chain over,
  move reference material into a sibling doc and leave a pointer: the checker counts only
  files named `AGENTS.md` along the ancestors, so `middlewares/CHAIN.md`,
  `backend/docs/RUNTIME.md`, `frontend/src/DATA_FLOW.md` and
  `app/gateway/AUTHORIZATION.md` stay discoverable without being inherited. Trim the
  nearest shared ancestor first — it pays into every chain below it.
- **Useful tests** — reuse coverage first; add or extend tests for uncovered
  behavior and regressions, and prune proven redundant or obsolete tests in the
  area being changed. Follow CHANGE_CYCLE.md step 3 and the backend's TDD policy.
  Skill-creator tests must preserve YAML values/body, restore bytecode settings,
  and check invalid metadata through offline CLI subprocesses.
  Public skill script regressions live in `tests/skills/` and run in Skill Review CI
  independently of package review. Exercise dependency fallbacks with the optional
  import unavailable and mock HTTP transport to keep tests offline.
  Video, podcast, and chart-visualization CLI failures exit non-zero;
  diagnostics on stderr, success URLs on stdout; test offline.
- **Format code before pushing** — `make format` (backend) / `pnpm check` (frontend); backend CI
  enforces `ruff format --check`.
- **Skill text encoding** — use explicit UTF-8 for textual skill resources.
  Read `SKILL.md` with `encoding="utf-8-sig"` to strip a leading BOM; write with
  `encoding="utf-8"`. Never rely on the platform locale.
- **Version sources must stay in lockstep** — a release version must match identically in
  `backend/pyproject.toml`, `frontend/package.json`, and `deploy/helm/deer-flow/Chart.yaml`
  (`version` + `appVersion`), and `backend/uv.lock` must record the root package's PEP 440
  form (e.g. `2.1.0rc0`); a `v*` tag runs `scripts/verify_versions.sh` in CI and
  **blocks all publishing** on any drift. Bump with `scripts/bump_version.sh <ver>` (aligns
  all four and refreshes `uv.lock`; needs `uv` on `PATH`) and check with
  `scripts/verify_versions.sh <ver>`. See [RELEASING.md](RELEASING.md).
- **Don't edit `CLAUDE.md`** — it only contains `@AGENTS.md`. All agent guidance changes
  belong here in `AGENTS.md`; `CLAUDE.md` is a thin import shim.
