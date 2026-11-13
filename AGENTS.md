# DeerFlow

DeerFlow is an agent harness: a LangGraph-based backend with thread-isolated
sandboxes, memory, subagents, skills and MCP tools, and a Next.js frontend. IM
channels connect through the Gateway.

**Before making any repository change, read and follow [CHANGE_CYCLE.md](CHANGE_CYCLE.md).**
It applies automatically to every change request, whichever agent, model or
provider runs it, delegated agents included: run existing tests, add coverage
only where needed, review and remove unnecessary tests, and open a pull request.
The lead agent owns final validation and the PR. `CLAUDE.md` and `GEMINI.md`
only import this file; don't edit them, edit guidance here.

## How guidance is organized

Rules live in the `AGENTS.md` nearest to the code. Before you edit a directory,
read every `AGENTS.md` from that directory up to this file. Some coding agents do
not load the nested files on their own.

| Area | Guide |
| --- | --- |
| Backend: harness, Gateway, channels, tests | [backend/AGENTS.md](backend/AGENTS.md) |
| Frontend | [frontend/AGENTS.md](frontend/AGENTS.md) |
| nginx, Compose, provisioner | [docker/AGENTS.md](docker/AGENTS.md) |
| Orchestration scripts, `scripts/pnpm.py` | [scripts/AGENTS.md](scripts/AGENTS.md) |
| Skill review, skill tests | [skills/AGENTS.md](skills/AGENTS.md) |
| Extension examples | `examples/*/AGENTS.md` |

Humans start at [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/guide/](docs/guide/). Candidate fork work is in [roadmap.md](roadmap.md).

## Service topology

| Service | Port | Role |
| --- | --- | --- |
| Nginx | 2026 | The single entry point; open this in the browser |
| Gateway | 8001 | FastAPI REST API and the embedded agent runtime |
| Frontend | 3000 | Next.js web interface |
| SearXNG | 8088 | Fork, loopback-only: search behind the default `web_search` (`scripts/detect_searxng.py`) |
| ComfyUI | 8188 | Fork, loopback-only: local image and video generation (FORK.md §26) |
| Provisioner | 8002 | Optional; only for provisioner or Kubernetes sandboxes |

Nginx serves the frontend, proxies `/api/*` to the Gateway and rewrites
`/api/langgraph/*` to the Gateway's native routes. Keep the browser-stream
WebSocket location before the generic threads regex in every nginx config
(`test_nginx_browser_websocket.py`).

The published nginx port is the whole external surface and is **loopback by
default**: a new published port needs an explicit bind address, or it binds
`0.0.0.0`. That rule and the three that ride with it (the non-loopback
`BIND_HOST` co-bind, Compose's absolute `--env-file`, tailnet reach detected
rather than configured) are in FORK.md, *Reaching the stack over Tailscale*,
pinned by `test_compose_default_bind_host.py`, `test_deploy_loopback_cobind.py`
and `test_docker_dev_tailnet.py`.

Before changing ingress, port bindings or provisioner mounts, read
[service topology details](docs/agent-service-topology.md).

## Repository map

| Path | Content |
| --- | --- |
| `backend/packages/harness/` | `deerflow-harness`, import `deerflow.*`: the agent framework |
| `backend/packages/extension-api/` | `deerflow-extension-api`: the public extension contract |
| `backend/app/` | The Gateway and the IM channels, import `app.*` |
| `frontend/` | The Next.js app (pnpm) |
| `docker/`, `deploy/helm/` | Compose files, nginx config, provisioner, Helm chart |
| `skills/public/`, `skills/custom/` | Committed skills and local, gitignored skills |
| `contracts/` | JSON contracts shared across components |
| `examples/` | Installable extension examples |
| `scripts/`, `tests/` | Root orchestration scripts, and tests for public skills |

`config.yaml` and `extensions_config.json` are copied from the example files at
the repository root. Both are gitignored and the Gateway can write them. Do not
commit them.

## Commands

`make help` lists the root targets. First setup is `make config`, then
`make install`, then `make dev`, which serves the stack on `localhost:2026` and
writes `logs/gateway.log` and `logs/frontend.log`.

```bash
cd backend && make test && make test-blocking-io   # offline suites
cd backend && make format                          # CI runs ruff format --check
cd backend && python -m pytest tests/path/test_x.py::test_name -q
cd frontend && pnpm check && pnpm test
cd frontend && pnpm rstest run <pattern>
make check-agent-guidance                          # size budget of these guides
```

Fork-only targets, documented in FORK.md: `backup` / `restore` (§13), `comfy-*`
(§26), `drift-eval` (§25), `auto-update*`, `searxng*`, `sandbox-*`,
`fetch-browser`, and `up-start` (applies `.env` or `config.yaml` changes without
a rebuild).

## Rules for every change

- **[FORK.md](FORK.md) documents each fork feature, its reasons and its
  tests.** Keep its [post-sync checklist](FORK.md#post-sync-feature-checklist)
  current; the full checklist is due for upstream merges and broad changes, and
  the [model audit](FORK.md#the-model-bundle-and-its-audit) runs only when asked.
- **Evaluate an extension first.** Before you add a feature to core code, check
  whether it can ship as a packaged extension. Core is the place for bug fixes
  and for changes to the agent loop, memory, context compaction and
  authentication. When the existing hooks cannot express a feature, add a
  generic hook to the extension contract and an extension that uses it; business
  logic is not hard-coded into core. Contract and examples:
  [extensions guide](backend/packages/harness/deerflow/extensions/AGENTS.md),
  `examples/`.
- **Extensions are operator-controlled code.** They load from `plugins:` in
  `config.yaml`. The list stays out of the API-writable `extensions_config.json`,
  because loading an extension imports code with Gateway privileges. Install
  from trusted sources only, and restart the Gateway after every extension
  change.
- **Ship tests with every feature and bug fix.**
- **Document behavior next to its topic, in the same change**: user-facing
  behavior in `docs/guide/` or `backend/docs/`. `README.md` is an index, except
  that a new fork feature still owes its opening list a bullet (CHANGE_CYCLE.md
  step 7); keep those bullets, and put their reference detail in `docs/guide/`.
- **Keep the version fields identical**: `backend/pyproject.toml`,
  `backend/packages/harness/pyproject.toml`, `frontend/package.json`, and
  `version` and `appVersion` in `deploy/helm/deer-flow/Chart.yaml`.
  `scripts/bump_version.sh <ver>` updates them and `backend/uv.lock`, and
  `scripts/verify_versions.sh <ver>` checks the result. Tag CI blocks publishing
  on drift. See [RELEASING.md](RELEASING.md).

## What belongs in an `AGENTS.md`

An agent reads these files on every task, so each line costs attention. A guide
holds four kinds of content:

1. Scope: what the directory owns, in one or two sentences.
2. Verification: the exact commands.
3. Traps: where the code misleads, or where a plausible change breaks something
   that a local test run does not show.
4. Decisions and their reasons that the code cannot state, and links to docs.

Values, defaults, field lists, function inventories, test names, issue numbers
and history stay in the code, the tests and git. Write full sentences in the
positive form and give the reason. `make check-agent-guidance` enforces the size
budget of each file and of the chain an agent inherits. Move longer reference
material into a sibling doc not named `AGENTS.md` and leave a pointer, as
`middlewares/CHAIN.md`, `backend/docs/RUNTIME.md`, `frontend/src/DATA_FLOW.md`
and `app/gateway/AUTHORIZATION.md` do. Trim the nearest shared ancestor first,
because it pays into every chain below it.

### Office preview example

`examples/deerflow-extension-office-preview/` packages Office readers through the
optional `artifactPreviews` browser contract. Keep parser dependencies and resources
in the extension; rebuild its manifest and static module graph after UI changes.
Test packaged assets with the Office E2E fixtures; rendering must preserve original
downloads and state its search limits.
