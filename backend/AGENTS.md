# Backend (`backend/`)

The Python backend: the publishable harness in `packages/harness/deerflow/`, the
public extension contract in `packages/extension-api/`, and the unpublished
Gateway and IM channels in `app/`. In every deployment the agent runtime runs
inside the Gateway. Design docs are in [docs/](docs/); start with
[ARCHITECTURE.md](docs/ARCHITECTURE.md) and [API.md](docs/API.md).

## Guides by area

Read the guide for an area before you change it.

| Area | Guide |
| --- | --- |
| Run streaming, checkpoints, run ownership | [runtime](packages/harness/deerflow/runtime/AGENTS.md) |
| Repositories, leases, scheduled tasks, schema changes | [persistence](packages/harness/deerflow/persistence/AGENTS.md), [migrations](packages/harness/deerflow/persistence/migrations/AGENTS.md) |
| `config.yaml`, `extensions_config.json` | [config](packages/harness/deerflow/config/AGENTS.md) |
| Lead agent, prompt, thread state, middleware chain | [agents](packages/harness/deerflow/agents/AGENTS.md), [middlewares](packages/harness/deerflow/agents/middlewares/AGENTS.md) |
| Memory, subagents, skills, tools | [memory](packages/harness/deerflow/agents/memory/AGENTS.md), [subagents](packages/harness/deerflow/subagents/AGENTS.md), [skills](packages/harness/deerflow/skills/AGENTS.md), [tools](packages/harness/deerflow/tools/AGENTS.md) |
| Sandbox, uploads, MCP, models, extensions | [sandbox](packages/harness/deerflow/sandbox/AGENTS.md), [uploads](packages/harness/deerflow/uploads/AGENTS.md), [mcp](packages/harness/deerflow/mcp/AGENTS.md), [models](packages/harness/deerflow/models/AGENTS.md), [extensions](packages/harness/deerflow/extensions/AGENTS.md) |
| Trace ID, embedded client, other root modules | [harness package](packages/harness/deerflow/AGENTS.md) |
| Search, fetch and sandbox providers | [community](packages/harness/deerflow/community/AGENTS.md), then the provider's own guide |
| Gateway, routers, IM channels | [gateway](app/gateway/AGENTS.md), [routers](app/gateway/routers/AGENTS.md), [channels](app/channels/AGENTS.md) |
| Tests, benchmarks | [tests](tests/AGENTS.md), [benchmarks](scripts/benchmark/AGENTS.md) |

## Verify

```bash
make test               # offline suite in parallel shards
make test-blocking-io   # strict blocking-I/O suite
make lint
make format
make test-live          # calls real APIs; needs DEER_FLOW_RUN_LIVE_TESTS=1
```

[CHANGE_CYCLE.md](../CHANGE_CYCLE.md) sets the test scope: `make lint` and
`make test` after a code change, plus `make test-blocking-io` for async, runtime
or I/O changes. Live tests stay opt-in, so the default suite needs no network
and no API key.

## Rules

- **The harness never imports `app`.** `app.*` imports `deerflow.*`, and not the
  reverse, because the harness is published on its own.
  `tests/test_harness_boundary.py` enforces this in CI.
- **Start the Gateway with `make dev` or `make gateway`.** `make dev` excludes
  `DEER_FLOW_HOME` and `backend/sandbox` from the reload watcher. A bare
  `uvicorn --reload` restarts the Gateway during a run, because agent tasks write
  Python files below `DEER_FLOW_HOME`.
- **From the repository root, run backend tools with
  `uv run --no-sync --project backend`.** `--project` keeps the caller's working
  directory, so relative config paths still resolve. `--no-sync` keeps installed
  extras such as the PostgreSQL drivers.
- **Run Python through `uv run` inside `backend/`**, without `--no-sync`, so the
  environment matches the lock.
- **Guard POSIX-only test markers with `os.name`.** Windows collects the same
  files.
- **Tool approvals need addressable calls.** Strip missing, empty and duplicate
  tool-call IDs before creating a pause or a tool result. See the
  [run interaction policy](docs/RUN_INTERACTION_POLICY.md#hitl-tool-approval).
- **Add a schema change with `make migrate-rev MSG="..."`** and follow the
  migrations guide.

## Fork-specific backend

The fork adds durable auxiliary token counters, currency spend caps
(`SpendBudgetMiddleware`, HTTP 402 at admission), spend attribution, cost-aware
subagent routing, model fallback chains, `price:`/`discount:` model fields, Web
Push, multi-user mode, the per-user UI-state store, an editable system prompt
and ComfyUI generation. Read the feature's [FORK.md](../FORK.md) section before
you change it, because several fail silently: token attribution on a fallback,
discount expiry, the factory exclude set. Runtime invariants are in
[docs/RUNTIME.md](docs/RUNTIME.md). Fork guides in `packages/harness/deerflow/`:
`models/` (pricing, fallback), `agents/lead_agent/`, `agents/generation/`
(returns a draft, never an agent), `community/speech/` (cloud tier off by
default; Tailscale CGNAT counts as local), `community/comfyui/` and `documents/`.
