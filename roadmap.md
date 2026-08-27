# Roadmap

Candidate improvements for this fork, written as **orchestrator prompts** — each item is
self-contained enough to hand to a coding agent as a single unit of work.

These are derived from a comparison of this fork against upstream
[bytedance/deer-flow](https://github.com/bytedance/deer-flow). The fork's thesis (see
[FORK.md](./FORK.md)) is a **personal AI you host at home**: private, cheap, reached from
your phone over Tailscale, mixing free local Ollama models with paid cloud keys. Every
item below either extends that thesis or reduces a risk the comparison surfaced.

Nothing here is committed work. Items are ordered by dependency and value, not priority —
pick per appetite.

---

## How to use this file

Each item has a **Goal**, **Why it fits**, **Depends on**, **Scope**, **Key files**, and
**Done when**. When dispatching one to an agent, prepend the shared context block below;
the per-item text assumes it.

<details>
<summary><strong>Shared context block</strong> (prepend to every prompt)</summary>

```
You are working in the AI-at-home repo, a fork of bytedance/deer-flow. Read AGENTS.md,
backend/AGENTS.md, and frontend/AGENTS.md before starting, and FORK.md for the fork's
design intent.

Repo conventions that are not optional:
- TDD is mandatory for backend work. Tests live in backend/tests/; write the failing test
  first. Frontend tests live in frontend/tests/.
- Keep docs in sync in the same change set: README.md for user-facing changes, the
  relevant AGENTS.md for architecture changes, FORK.md for anything that becomes a
  fork-vs-upstream difference (including a row in its Post-sync feature checklist).
- Format before pushing: `cd backend && make format && make lint && make test`;
  `cd frontend && pnpm format && pnpm check && pnpm test`. CI enforces
  `ruff format --check` and `prettier --check`.
- Prefer additive blocks on stable anchors over rewrites of upstream files — this fork
  merges upstream regularly and every rewritten upstream file becomes a recurring merge
  conflict.
- New defaults must be safe for a shared deployment, or must self-disable when
  DEER_FLOW_ENV/ENVIRONMENT is prod. Follow the pattern in
  backend/app/gateway/auth_disabled.py.

Work on a feature branch. Do not open a PR unless asked.
```

</details>

---

## 1. Durable auxiliary usage accounting

**Status** — ✅ **Implemented.** The registry is now a write-through cache over
`deerflow/runtime/aux_usage_store.py`, a small dedicated SQLite file
(`<DeerFlow home>/aux_usage.sqlite3`, kill switch `DEER_FLOW_AUX_USAGE_DB=0`). See
FORK.md §7 *Durable auxiliary counters* for the store choice and its trade-offs, and
`backend/tests/test_aux_usage.py` / `test_aux_usage_wiring.py` /
`blocking_io/test_aux_usage.py` for the coverage. Items 2 and 3 are unblocked.

**Goal** — Memory and follow-up-suggestion token usage survives a Gateway restart, so
anything built on cost data can be trusted over a period longer than one process
lifetime.

**Why it fits** — `deerflow/runtime/aux_usage.py` is deliberately process-local and
bounded (LRU over 4096 threads), documented in FORK.md §7 as "enough for a single-process
personal deployment." That was the right call for a display counter. It is the wrong
foundation for a budget or a spend report, both of which are on this roadmap. This item
exists to unblock them.

**Depends on** — nothing.

**Scope**

- Persist aux usage (category, model, thread, input/output/cache-read tokens) durably
  alongside run token usage.
- Solve the constraint that made it process-local in the first place: memory usage is
  recorded from the background extraction thread
  (`agents/memory/manager.py::_host_default_extraction_callback`), which cannot reach the
  async runs DB. Options worth evaluating before writing code: a sync write path, a queue
  drained by the Gateway event loop, or a small dedicated store. Pick one, write down why
  in the PR.
- Keep the in-memory registry as a write-through cache so the header stays fast.
- Preserve the existing `aux` shape in `GET /api/threads/{id}/token-usage`.

**Key files** — `backend/packages/harness/deerflow/runtime/aux_usage.py`,
`backend/packages/harness/deerflow/agents/memory/manager.py`,
`backend/app/gateway/utils/oneshot_llm.py` (recording side),
`backend/packages/harness/deerflow/persistence/run/sql.py`,
`backend/app/gateway/routers/thread_runs.py`.

**Done when** — aux totals for a thread are identical before and after a Gateway restart;
`backend/tests/test_aux_usage.py` and `test_aux_usage_wiring.py` are extended with a
cold-start round-trip; the FORK.md §7 "Caveats (deliberate)" paragraph is updated to
reflect the new behavior.

---

## 2. Currency-denominated spend caps

**Status** — ✅ **Implemented.** `config.yaml -> spend_budget` caps real money over a
rolling or calendar day/week/month window. Enforced at run admission (HTTP 402) and
in-run by `SpendBudgetMiddleware`, priced per model through the shared
`deerflow/pricing.py`; unpriced models cost 0 so a local run is never blocked; the
feature self-disables with a reason when nothing is priced, and `make doctor` says
which. Remaining budget shows in the chat header. See FORK.md §10.

**Goal** — The operator can set a daily / weekly / monthly budget in real money and have
runs warn and then hard-stop when it is exhausted.

**Why it fits** — This is the largest single gap the comparison found. The fork built an
entire pricing layer to make cost **visible** and never made it **bounded**. Upstream's
`token_budget` does not fill the hole: it is per-run and counted in tokens, and in a fork
whose premise is mixing Opus, Haiku, and free local Ollama in one session, a token is not
a unit of cost — 200k tokens is $5 or $0 depending on which model burned them.

**Depends on** — item 1 (a budget that resets on restart is not a budget).

**Scope**

- Add a `spend_budget:` config section mirroring `token_budget:`'s shape
  (`enabled`, limits, `warn_threshold`, `hard_stop_threshold`) but denominated in the
  single configured pricing currency, over rolling or calendar windows.
- Enforce at run admission and during a run, priced through the existing `run_cost` path
  so lead and subagent tokens are billed at their own model's rate. Model
  `TokenBudgetMiddleware` for the in-run warn / forced-final-answer behavior.
- Unpriced models (local Ollama) contribute zero — a fully local run must never be
  blocked by a spend cap.
- Surface remaining budget in the existing header dropdown next to the cost figure.
- Decide and document what happens with no pricing configured (proposal: the feature
  disables itself and `make doctor` says why).

**Key files** — `backend/packages/harness/deerflow/config/token_budget_config.py` and
`agents/middlewares/token_budget_middleware.py` (as the pattern to follow),
`backend/app/gateway/pricing.py`, `config.example.yaml`,
`frontend/src/components/workspace/token-usage-indicator.tsx`.

**Done when** — a configured cap produces an in-context warning at the warn threshold and
a forced final answer at the hard stop; a local-only run is never blocked; backend tests
cover window rollover, the mixed lead/subagent case, and the unpriced-model case;
README.md and FORK.md document the section.

---

## 3. Spend history and attribution view

**Status** — ✅ **Implemented.** `GET /api/console/spend` aggregates persisted run
costs and the durable auxiliary counters over a window, grouped by model, thread and
feature, reusing `pricing.py` end to end and naming unpriced models explicitly. The
page lives at `/workspace/spend`. See FORK.md §11.

**Goal** — A workspace page answering "where did my money go this month," broken down by
model, thread, and feature.

**Why it fits** — The header answers "what is this conversation costing." It does not
answer the question a person actually asks at the end of a month. The data is already
collected per-model and per-feature; this is mostly a view over it.

**Depends on** — item 1.

**Scope**

- Aggregate persisted run costs and aux costs over a time range, grouped by model, by
  thread, and by category (conversation / memory / suggestions).
- Add a workspace page alongside `/workspace/scheduled-tasks`.
- Reuse `pricing.py` end to end — do not add a second cost calculation. Honor the
  one-currency rule and the promo/standard split already implemented there.
- Name unpriced models explicitly rather than reporting a quietly low total, matching the
  `unpriced_models` behavior the header already has.

**Key files** — `backend/app/gateway/pricing.py`,
`backend/app/gateway/routers/console.py` (existing aggregation to reuse),
`backend/packages/harness/deerflow/persistence/run/sql.py`,
`frontend/src/app/workspace/`.

**Done when** — the page reports a breakdown whose total matches the sum of per-thread
header figures for the same window; unpriced models are named; tests cover the
aggregation and the empty/no-pricing states.

---

## 4. Automated model and pricing audit

**Status** — ✅ **Implemented.** `scripts/audit_models.py` reads both synced sources
(the `config.example.yaml` marker blocks and `scripts/wizard/providers.py`) and diffs
them against the live OpenRouter catalog for retired slugs, moved list prices, and
promos that started or ended — plus two network-free checks (display name vs. its own
`pricing:` block, and parity between the two sources).
`.github/workflows/model-audit.yml` runs it weekly and maintains a single
`model-audit`-labelled issue, closing it when a run comes back clean. It never commits
a price, an unreachable provider is a skip rather than drift, and
`scripts/fixtures/model_audit_stale_catalog.json` is the audit's own regression test —
the workflow asserts it still detects drift before trusting a clean live run. FORK.md's
*Auditing the model list* now names the job as the trigger.

**Goal** — A scheduled CI job that diffs the bundled model roster against live provider
catalogs and opens an issue when a slug, price, or promo has drifted.

**Why it fits** — FORK.md concedes that the existing tests "do not catch a
stale-but-well-formed price or a since-renamed slug, because both pass against any
syntactically valid entry," and names the specific failure: an expired promo leaves the
chat header advertising a discount nobody is getting. The audit is currently a manual
discipline documented across two sections. The fork's entire cost story rots silently
without it — and *silently* is the operative word, which is what makes this worth
automating over almost anything else here.

**Depends on** — nothing.

**Scope**

- Fetch current model catalogs (OpenRouter's models + promotions endpoints; each
  first-party lab's catalog where one is machine-readable).
- Diff against both synced sources — the `# === BEGIN auto-model-config: <provider> ===`
  marker blocks in `config.example.yaml` and the `*_BUNDLE_MODELS` lists in
  `scripts/wizard/providers.py` — for: retired or renamed slugs, changed list prices,
  started or ended promotions.
- Report as a GitHub issue with a suggested diff. Do not auto-commit price changes; the
  audit rules in FORK.md require reading the provider's own page, and a wrong automated
  price is worse than a stale one.
- Handle unreachable providers as a skip, never a failure — this must not become a red CI
  job people learn to ignore.

**Key files** — `.github/workflows/`, `config.example.yaml`,
`scripts/wizard/providers.py`, `scripts/sync-api-key-models.py`,
`backend/tests/test_config_integrity.py`.

**Done when** — the job runs weekly, produces a readable issue against a deliberately
stale fixture, skips cleanly when a provider is unreachable, and the
*Auditing the model list* section of FORK.md points at it as the trigger for the manual
pass rather than the calendar.

---

## 5. Cost-aware model routing policy

**Status** — ✅ **Implemented.** `model_routing:` maps declarative conditions (needs
tools / vision / thinking, estimated context) to an ordered model preference, resolved
in `deerflow/subagents/routing.py` from the capability flags that already exist on model
entries — no LLM call classifies the task. An explicit per-thread subagent selection
stands the policy down entirely, a candidate that cannot do the job is skipped rather
than routed to, and the effective decision (rule + skipped candidates) is shown on the
subagent card. Off by default. See FORK.md §15.

**Goal** — A declarative policy that routes subagents to the cheapest model that can
actually do the task, so the fork's cost saving is the default rather than a manual
choice.

**Why it fits** — The fork exposes the lever (per-thread model, per-thread subagent
override) but the user must pull it every session. FORK.md's own worked example puts
Sonnet-lead / Haiku-subagents at ~63% cheaper than all-Sonnet and Sonnet-lead /
local-subagents at ~95%. A policy turns a UI affordance into a standing saving.

**Depends on** — nothing. Item 6 makes it materially safer.

**Scope**

- Add a config-level routing policy: rules matching on task requirements (needs tools,
  needs vision, needs thinking, estimated context size) mapped to a model preference
  order.
- Decide requirements from the capability flags that already exist on model entries
  (`supports_tools`, `supports_vision`, `supports_thinking`, `context_window`) — do not
  add an LLM call to classify the task.
- The existing per-thread "Follow lead" / explicit subagent selection must always win
  over the policy. The policy fills the default, nothing more.
- Ship it **off by default**, consistent with how this fork treats anything that changes
  agent behavior.
- Show the effective routing decision on the subagent card so it is inspectable rather
  than mysterious.

**Key files** — `backend/packages/harness/deerflow/tools/builtins/task_tool.py`,
`backend/packages/harness/deerflow/subagents/executor.py`, `config.example.yaml`,
`frontend/src/components/workspace/input-box.tsx`.

**Done when** — with a policy configured, a tool-free extraction subtask routes to a cheap
or local model and a tool-using one does not; an explicit per-thread subagent selection
overrides the policy; the decision is visible in the UI; backend tests pin rule matching
and the override precedence.

---

## 6. Model fallback chains

**Status** — ✅ **Implemented.** `deerflow/models/fallback.py` wraps a model in a chain
resolved from per-model `fallback:` or the global `model_fallback.chain` (off by
default). It separates a **failure** (connection, context length, unsupported tools,
5xx → fall back) from a **decision** (interrupt, spend cap, guardrail, 401/403 →
re-raise), with unrecognized errors also re-raising. Cycles are inexpressible rather
than detected — chain members are built without their own chains — and tokens are
attributed to the serving model for free, which the spend cap and spend report depend
on. See FORK.md §14.

**Goal** — A failed model call retries down a configured chain (local → cheap cloud →
premium) instead of failing the turn.

**Why it fits** — FORK.md §3 notes that models flagged `supports_tools: false` stay
selectable and "tool-using subagents will simply fail at runtime." That is one instance of
a general problem: running local models means absorbing local-model failure modes — daemon
down, OOM, context overflow, no tool support. Right now the user absorbs them manually.
This is the reliability cost of the fork's central bet, and paying it makes item 5 safe to
turn on.

**Depends on** — nothing.

**Scope**

- Per-model or global `fallback:` chain in config.
- Trigger on: connection failure to the provider, context-length rejection, tool-call
  unsupported, and provider 5xx. Do **not** fall back on a user interrupt, a budget stop
  (item 2), or a guardrail refusal — those are intentional stops.
- Bound the chain and never retry indefinitely; log which model actually served the call.
- Attribute tokens to the model that actually ran, so cost stays correct — this is
  load-bearing for items 2 and 3.

**Key files** — `backend/packages/harness/deerflow/models/`,
`backend/packages/harness/deerflow/subagents/executor.py`,
`backend/packages/harness/deerflow/runtime/runs/worker.py`.

**Done when** — killing the Ollama daemon mid-session degrades to the configured cloud
fallback rather than failing the turn; a budget hard-stop does not trigger fallback; token
usage is attributed to the serving model; tests cover each trigger and each non-trigger.

---

## 7. PWA, service worker, and push notifications

**Status** — ✅ **Implemented, with one part deliberately left open.** The app is
installable (manifest + icons + `appleWebApp` metadata), a push-only service worker
delivers notifications with the browser closed, VAPID keys are minted once and kept
`0600`, subscriptions are stored per user beside the chat tabs, dead subscriptions
prune themselves, and a run longer than 30s notifies on completion. The secure-context
problem is surfaced rather than hidden: a plain-HTTP LAN origin gets a specific
explanation and the Tailscale HTTPS fix, documented in README.md. `pywebpush` is an
optional extra. **Not done:** the mobile chat layout audit — the keep-alive tab strip
and artifact panel are still desktop-shaped on a narrow viewport. See FORK.md §16.

**Goal** — The app installs to a phone home screen and delivers a notification when a
long-running agent task finishes, with the browser closed.

**Why it fits** — This is the biggest gap relative to the fork's own stated goal. There is
a notification settings page, but it uses the plain browser Notification API with no
service worker and no manifest, so a notification only fires while the tab is open — and
iOS Safari will not deliver at all without an installed PWA. The use case the fork is
built around ("start a sandbox run from my phone over Tailscale, pocket it, get pinged
when it's done") does not currently work on the device it is designed for.

**Depends on** — nothing.

**Scope**

- Add `manifest.json`, icons, and a service worker to `frontend/public` / the Next.js app.
- Add Web Push: VAPID keys generated at setup, subscription stored per user (reuse the
  `ui_state.json` per-user store pattern in
  `deerflow/config/user_ui_state.py`), and a Gateway endpoint to deliver on run
  completion.
- Extend the existing notification settings page rather than adding a second one; keep it
  opt-in and off by default.
- Must work on a plain-HTTP LAN origin **or** fail with a clear explanation — service
  workers require a secure context, so `localhost` and Tailscale HTTPS work while a plain
  LAN IP does not. Say so in the UI instead of silently doing nothing. Document the
  Tailscale HTTPS path in README.md.
- Audit the mobile chat layout in the same pass — the keep-alive tab strip and artifact
  panel are desktop-shaped.

**Key files** — `frontend/public/`, `frontend/next.config.js`,
`frontend/src/core/notification/hooks.ts`,
`frontend/src/components/workspace/settings/notification-settings-page.tsx`,
`backend/packages/harness/deerflow/config/user_ui_state.py`,
`backend/app/gateway/routers/settings.py`.

**Done when** — the app is installable on Android and iOS; a run finishing with the app
backgrounded produces a notification; an insecure origin shows the explanation rather than
failing silently; the feature is off until enabled.

---

## 8. Whole-instance backup and restore

**Status** — ✅ **Implemented.** `make backup` / `make restore` (`scripts/backup.py`)
write and read one timestamped archive of the DeerFlow home tree, `config.yaml`,
`extensions_config.json` and custom skills. **The secrets decision: excluded by
default**, opt in with `INCLUDE_SECRETS=1`, and then the archive is created `0600` at
open time. Postgres is dumped explicitly and a failed dump aborts the backup; restore
refuses while the Gateway or nginx is listening, rejects unsafe archive paths, and
preserves file modes (`filter="tar"`). Documented in README.md and SECURITY.md. See
FORK.md §13.

**Goal** — One command snapshots everything a personal instance has accumulated, and one
command restores it.

**Why it fits** — There is per-feature memory import/export, but no snapshot of
`.deer-flow` as a unit: memory, threads, chat tabs, runtime settings, uploads, integration
credentials. A personal AI accumulates months of memory on a single machine with no
redundancy, which is exactly the deployment shape this fork targets. It also doubles as
the recovery path for the root-owned-files problem FORK.md documents in the Arch / DooD
section.

**Depends on** — nothing.

**Scope**

- `make backup` / `make restore` writing a single timestamped archive.
- Include: the DeerFlow home tree, `config.yaml`, `extensions_config.json`, custom skills.
  Handle the database backend (sqlite file vs. Postgres dump) explicitly.
- **Secrets need a deliberate decision, not a default.** Integration credentials under
  `users/{user_id}/integrations/` are `0700`/`0600` for a reason. Either exclude them, or
  encrypt the archive and refuse to write it world-readable. Document the choice
  prominently — a backup that quietly widens credential exposure is worse than no backup.
- Restore must be safe against a running stack: refuse, or stop first, rather than writing
  underneath a live Gateway.
- Preserve ownership and permissions so a restore does not recreate the root-owned-files
  problem.

**Key files** — `Makefile`, `scripts/`, `backend/packages/harness/deerflow/config/`,
`FORK.md` (Arch / DooD troubleshooting section).

**Done when** — a backup taken on one machine restores onto a clean checkout with threads,
memory, tabs, and settings intact; restore against a running stack is refused with a clear
message; the secrets decision is documented in README.md and SECURITY.md.

---

## 9. Ollama daemon lifecycle management

**Status** — ✅ **Implemented.** `ollama.keep_alive` (plus `keep_alive_overrides` per
model) is written into every synced entry; `ollama.preload: true` warms `models[0]` at
launch via a backgrounded load-only request; a `vram_gb`-aware contention warning names
the two largest local models with real numbers when they cannot co-reside; and
`make doctor` gained a **Local Models** section (daemon reachable, configured models
pulled, `keep_alive` set). All warn-only, and nothing reassigns a model choice. See
FORK.md §1.

**Goal** — Local models are warm when needed and do not fight each other for VRAM.

**Why it fits** — `scripts/sync-ollama-models.py` computes a per-model VRAM-aware context
window from real attention geometry, which is the most sophisticated piece of the fork.
Then it stops at the config file. The daemon itself is unmanaged: no `keep_alive` control,
so a model unloads between turns and every subagent call pays a cold start; no preload of
the configured default; no handling for a lead and a subagent that are different local
models which do not both fit in VRAM. This is the same problem the sync already solves,
one step further out.

**Depends on** — nothing. Interacts with item 5 (a routing policy that picks local models
should know whether one is loaded).

**Scope**

- Expose `keep_alive` per model or globally, written into synced entries.
- Optionally preload the configured default model at startup.
- Detect the VRAM-contention case — lead and subagent both local, combined weights over
  budget — and warn at launch with the numbers, reusing the VRAM math already in the sync
  script. A warning is enough; do not silently reassign the user's model choice.
- Extend `make doctor` with a local-model readiness check.

**Key files** — `scripts/sync-ollama-models.py`, `scripts/doctor.py`,
`scripts/serve.sh`, `config.example.yaml`.

**Done when** — `keep_alive` is honored end to end; the contention case warns with actual
numbers rather than a generic message; `make doctor` reports local-model readiness; the
sync stays idempotent and still no-ops cleanly when the daemon is unreachable.

---

## 10. Automated upstream sync

**Status** — ✅ **Implemented.** `.github/workflows/upstream-sync.yml` merges
`upstream/main` weekly onto a dated `upstream-sync/<date>` branch (merge, never rebase;
never force-pushes), runs the mechanical gates, and opens a PR whose body is generated
from FORK.md's post-sync checklist by `scripts/upstream_sync.py` — so it stays current as
the fork grows instead of being a copy that rots. A conflicted merge still opens a PR,
flagged and listing every conflicted path, with gates reported as *skipped* rather than
passing. See FORK.md *Upstream sync*.

**Goal** — A scheduled job that merges `upstream/main`, runs the mechanical gates, and
opens a PR pre-populated with the post-sync checklist.

**Why it fits** — "Lags upstream" is a real reason to choose upstream over this fork, and
it compounds: the longer a sync is deferred, the larger the merge and the more likely the
fork's UI wiring silently breaks. FORK.md already carries a detailed post-sync checklist
and a Mirror Upstream workflow that solves the network-access half of the problem. This
turns a manual chore into a standing PR.

**Depends on** — nothing.

**Scope**

- Scheduled workflow: fetch upstream, merge (never rebase — FORK.md explains why), push a
  sync branch.
- Run the mechanical gates from the FORK.md checklist: conflict-marker grep, backend
  `make lint && make test`, frontend `pnpm format && pnpm check && pnpm test`,
  `uv lock` reconciliation.
- Open a PR whose body is the fork-feature verification table, so the manual half is a
  checklist rather than a memory exercise.
- On conflicts, still open the PR — flagged, with the conflicting paths listed. A conflict
  is the case where a human is most needed and most needs to know early.
- Reuse `.github/workflows/mirror-upstream.yml` where it already solves the fetch.

**Key files** — `.github/workflows/mirror-upstream.yml`, `.github/workflows/`, `FORK.md`
(Post-sync feature checklist, which becomes the PR body template).

**Done when** — the job produces a mergeable PR against a clean upstream delta, produces a
flagged PR listing paths against a conflicting one, and never force-pushes over the fork's
published history.

---

## 11. Deployment exposure check in `make doctor`

**Status** — ✅ **Implemented.** `scripts/exposure.py` computes the effective exposure
from bind address × auth × environment × multi-user mode × sandbox, and reports one
tier (`local-only` / `trusted-network` / `open-network`) per entry surface. `make doctor`
gained a **Deployment** section; the same summary prints at the end of `make up` and
`make dev`. A Tailscale bind is its own tier, the local dev surface is reported honestly
as the wildcard (`nginx.local.conf` listens without an address), no default changed, and
the check never returns `fail`. See FORK.md §12.

**Goal** — `make doctor` reports the instance's *effective* network exposure and names the
fix, instead of leaving the operator to reason about three independent settings.

**Why it fits** — Passwordless plus multi-user-mode-off plus a non-loopback `BIND_HOST` is
simultaneously this fork's happy path and its worst-case security posture. Each setting is
individually documented and defensible; the combination is what matters and nothing
computes it. `make doctor` already gained `check_env_placeholders` for exactly this class
of "loud beats silent" problem. Of everything here, this most directly reduces the
strongest argument for using upstream instead.

**Depends on** — nothing.

**Scope**

- Compute effective exposure from: `DEER_FLOW_AUTH_DISABLED`, `DEER_FLOW_ENV` /
  `ENVIRONMENT`, `BIND_HOST`, multi-user mode in `runtime_settings.json`, and whether the
  container sandbox is enabled.
- Report tiers plainly — loopback-only + auth off is fine and should say so; a non-loopback
  bind with auth off and histories merged is a loud warning naming each contributing
  setting and its one-line fix.
- Distinguish a Tailscale interface bind from `0.0.0.0`; they are not the same risk and
  the fork already treats them differently in `should_cobind_loopback`.
- Print the same summary line at the end of `make up` and `make dev`, where it is actually
  read.
- Do not change any default. This item is diagnosis only — the defaults are the fork's
  deliberate choice.

**Key files** — `scripts/doctor.py`, `scripts/deploy.sh`, `scripts/serve.sh`,
`backend/packages/harness/deerflow/config/runtime_settings.py`,
`backend/tests/test_doctor.py`.

**Done when** — each tier is reachable in tests with the corresponding settings; the
loopback-only default reports as safe without nagging; the warning names every
contributing setting; no default changes.

---

## 12. Local image generation through a ComfyUI service

**Goal** — `image-generation` works with no API key and no network: a prompt in chat
produces a PNG in the artifact panel, rendered by a diffusion model on your own GPU.

**Why it fits** — This is the fork's central move applied to a second modality. Text
inference already has a free local tier (Ollama, auto-synced, priced at zero); images and
video do not. Both bundled media skills call MiniMax or Gemini over HTTPS, so every image
costs money and every prompt leaves the house — the exact pair of properties the fork
replaced for chat. `_resolve_provider()` in both skill scripts is already a provider
seam with an override env var and a credential-based fallback; this adds a third branch
to it rather than a parallel system.

The output half is already built and needs nothing: AIO local-container mode bind-mounts
each thread's outputs directory (`_get_thread_mounts`), `present_files` accepts exactly
that directory, and `browserPreviewExtensions` in `frontend/src/core/utils/files.tsx`
already routes png/jpg/webp/gif/mp4/mov/webm to the artifact panel's preview iframe.

**Depends on** — nothing.

**Scope**

- ComfyUI as a **long-lived service**, not a sandbox tenant. Follow the SearXNG pattern:
  a tag-pinned compose file, a loopback-only published port, a `detect_comfyui.py` that
  reuses an already-running instance instead of starting a second one, a
  `DEER_FLOW_COMFYUI_BASE_URL` override documented in `.env.example`, and
  `make comfy-up` / `comfy-down` / `comfy-logs`.
- Follow the Ollama precedent for reachability from containers: the host-gateway alias is
  already mapped (`SANDBOX_OLLAMA_HOST_DEFAULT`, `--add-host` in `_start_container`), so
  a base-URL env var needs no new plumbing. Name it without `KEY`/`TOKEN`/`SECRET` in it
  or `env_policy.build_sandbox_env` will scrub it from skill subprocesses.
- A `deerflow/community/comfyui/` tool package, modelled on `community/image_search/`
  (135 lines and a four-line `config.yaml` block for the whole contract). It runs in the
  **Gateway process**, writing straight to the host-side outputs directory — that keeps
  it correct under every sandbox mode, including the one described in item 17.
- Structure every generation as `acquire → generate → release` from the first commit,
  even while the arbiter of item 13 is a no-op stub. Retrofitting that lifecycle later
  means rewriting the tool.
- Workflow templates stored as JSON in **API format** (ComfyUI's "Export (API)"); the UI
  format is not submittable. Patch parameters by node id: prompt, negative, seed, steps,
  cfg, dimensions, checkpoint.
- `POST /prompt` → `prompt_id`; poll `GET /history/{id}`; fetch bytes from `GET /view`;
  write to outputs; return the virtual path for `present_files`.
- A `list_media_models` tool over `GET /object_info`, whose enum for
  `CheckpointLoaderSimple.ckpt_name` *is* the list of installed checkpoints. This is the
  primitive that lets one sentence select a model, and it is the main reason to pick
  ComfyUI over a simpler HTTP wrapper.
- A `media.default_checkpoint` in config so a bare "make me a picture of a cat" needs no
  model reasoning at all.
- Save the submitted graph beside its output as `<name>.workflow.json`. It costs an hour,
  it is the whole of the "inspect how the nodes are set up" requirement, and it makes
  every failure reproducible by hand in ComfyUI's own editor.
- Validate templates against `/object_info` at startup and fail naming the node that
  moved. API-format graphs reference nodes by numeric id, so a custom-node update
  invalidates a template and the native error is a validation dump, not a sentence.
- Route the base URL through `community/url_safety.py::validate_public_http_url` with the
  documented `allow_private_addresses` opt-out, as `browser_automation` does. A loopback
  ComfyUI is precisely the intentional-internal-target case; do not bypass the guard.
- Do not let the model author raw graph JSON. Templates plus typed parameters.

**Key files** — `backend/packages/harness/deerflow/community/comfyui/` (new),
`backend/packages/harness/deerflow/community/image_search/tools.py` (the shape to copy),
`docker/docker-compose.comfyui.yml` (new), `scripts/detect_comfyui.py` (new, modelled on
`scripts/detect_searxng.py`), `Makefile`, `config.example.yaml`, `.env.example`,
`backend/packages/harness/deerflow/community/url_safety.py`,
`backend/tests/test_comfyui_tools.py` (new).

**Done when** — a chat request produces a PNG in the artifact panel with no API key set;
the tool resolves a checkpoint from `/object_info` rather than a hardcoded name; a stale
template fails with the offending node named; and the submitted graph opens in ComfyUI
and reproduces the image.

---

## 13. GPU residency arbiter

**Goal** — A language model and a diffusion model share one GPU that cannot hold both, by
declaring residency policy in config rather than hoping the operator sequences things by
hand.

**Why it fits** — The fork's local tier assumes weights live in VRAM and stay there:
`ollama.keep_alive` exists specifically to stop subagent cold starts, and the VRAM-aware
context sizing in `scripts/sync-ollama-models.py` budgets the whole card for one tenant.
Item 12 introduces a second tenant that wants the same card. On a 24 GB consumer GPU
they do not both fit, and the failure is silent rather than loud — Ollama does not error
when it cannot fit, it offloads layers to system RAM and runs several times slower.

**Depends on** — item 12.

**Scope**

- The eviction must happen **inside the tool call**, not in the agent's plan. An agent
  turn is a chain of model calls, so the lead model reloads the moment a tool returns; a
  swap sequenced at the plan level puts both tenants on the card at once. `generate_image`
  evicts the LLM, generates, evicts itself, and returns to an empty card. The agent must
  never need to know VRAM exists.
- Model the card as **tenants**, each declaring `location: local | cloud` and an eviction
  mechanism. Cloud then needs no special case anywhere — a cloud tenant is simply not
  resident, so the arbiter skips it.
- Eviction mechanisms: Ollama via `keep_alive: 0`, ComfyUI via its built-in `POST /free`
  (`unload_models` + `free_memory`).
- **Verify, never assume.** Re-read actual residency on acquire — Ollama `/api/ps`,
  ComfyUI `/system_stats`, `nvidia-smi` as tiebreak — rather than trusting in-process
  bookkeeping. A Gateway crash mid-generation leaves the card held, and the next local
  turn degrades silently instead of failing.
- `policy: exclusive | shared | none`, **computed by default** from `budget_gb` minus
  `reserve_gb` against the sum of local tenants' estimates, and logged with its reasoning.
  That is what makes a later GPU upgrade a config outcome rather than a code change:
  a bigger card resolves to `shared` on its own and the swapping stops.
- `budget_gb: auto` reuses `scripts/wizard/steps/ollama.py::detect_vram_gb`, which already
  parses `nvidia-smi` / `rocm-smi` / Apple unified memory. Do not write a second detector.
- Let the arbiter pass `keep_alive: 0` **per request** on the eviction call only. The
  global `ollama.keep_alive` exists for a good reason and should keep its value for
  ordinary chat; a global override would reintroduce the cold starts it was added to fix.
- One global GPU semaphore of depth 1, with a queue and an honest "waiting for the GPU"
  message. The arbiter serializes tenants, not callers — two threads generating at once
  will otherwise thrash with neither finishing.
- A `make doctor` check for VRAM held while nothing is generating.

**Key files** — `backend/packages/harness/deerflow/community/comfyui/` (new arbiter
module), `scripts/wizard/steps/ollama.py`, `scripts/doctor.py`, `config.example.yaml`,
`backend/tests/test_gpu_arbiter.py` (new), `backend/tests/test_doctor.py`.

**Done when** — a ~20 GB local lead and a ~16 GB checkpoint alternate for ten cycles on a
24 GB card with no OOM and no CPU offload; a cloud lead makes both evictions no-ops
without a code path of their own; the policy is derived and logged; and a killed Gateway
is recovered by the next acquire rather than by a restart.

---

## 14. Self-critiquing generation loop

**Goal** — The agent looks at what it generated, judges it against criteria fixed before
the first attempt, changes one thing, and tries again — stopping on success, on an
iteration cap, or on no improvement.

**Why it fits** — Local generation is free at the margin, which changes what is worth
doing: on a metered API, four attempts cost four times as much, and on your own GPU they
cost electricity. That is the same economics that justify the fork's local subagent
fan-out, applied to a modality where first-attempt quality is genuinely poor and iteration
is how good results are actually produced.

**Depends on** — item 12. Better with item 13, not blocked by it.

**Scope**

- **The agent owns the loop; no new loop engine.** A skill instructs generate → view →
  judge → adjust → repeat. Do not build the loop inside a tool that calls the model
  itself: that bypasses the run journal's per-model token accounting, hides the reasoning
  from the transcript, and breaks streaming.
- **Freeze the rubric before iteration 1.** The skill's first step derives 3–6 checkable
  criteria from the request and writes them to a session record; every iteration is judged
  against that frozen list. An open-ended "is this good?" either accepts immediately or
  never converges, because the standard drifts with each look.
- Structured verdicts, not prose: per-criterion pass/fail with a note, an overall
  `accept | retry | abandon`, and on retry exactly **one named change**. One change per
  iteration is what makes the loop diagnosable.
- **Seed discipline, stated explicitly in the skill** — hold the seed when changing prompt
  wording or weights so the delta is attributable; change it only when the composition
  itself is unlucky, and say so in the verdict. Without the rule every iteration is a
  fresh random draw and the critique is noise.
- **Count at the tool boundary, not in the model's head.** The tool returns a
  `session_id`, the server holds the counter, and iteration N+1 is refused with a message
  the agent can report. Same for a wall-clock budget. Models lose count; this is the
  classic way these loops run away.
- Persist the session as JSON beside the outputs — criteria, and per iteration the params,
  seed, verdict and filename. It is the audit trail, and it is what makes "target
  achieved" reviewable rather than asserted.
- Instruct the skill to view **only the newest** image each round, carrying forward
  written verdicts instead. Retaining every image in context bills full-resolution vision
  tokens repeatedly on a cloud lead.
- Note the constraint for offline profiles: `view_image` is only bound when the model
  reports vision support, so a text-only local lead has no judging step at all. Say so in
  the docs rather than letting the loop silently degrade to the model guessing.

**Key files** — `skills/public/image-refine/` (new),
`backend/packages/harness/deerflow/community/comfyui/`,
`backend/packages/harness/deerflow/tools/builtins/view_image_tool.py` (constraint, not a
change), `config.example.yaml`, `backend/tests/test_refine_session.py` (new).

**Done when** — a deliberately vague request converges within the cap; a deliberately
impossible one abandons cleanly instead of spinning; the cap holds when the model tries to
exceed it; and the session record shows one named change per iteration.

---

## 15. Local video generation

**Goal** — The same pipeline produces a short clip, and the critique step works on video.

**Why it fits** — Completes the pair the two cloud skills already cover, and it is the
modality where per-generation cost bites hardest, so a local tier is worth most.

**Depends on** — items 12 and 14.

**Scope**

- One video template, sized for what a 24 GB card actually runs. The 5B-class models are
  the realistic entry point; the 14B class is reachable quantized and is not where to
  start.
- **Video cannot be judged directly.** `view_image` accepts png/jpg/webp/gif only, capped
  at 20 MB — no MP4. The tool must also emit evenly-spaced stills *and* a single
  contact-sheet PNG. The sheet is the better critic input: one `view_image` call instead
  of six, and temporal faults (flicker, morphing, identity drift) read far more clearly
  side by side than frame by frame.
- Minutes per clip, so the wall-clock budget from item 14 stops being theoretical. The
  Gateway-side tool is not bound by `sandbox.bash_command_timeout`, which is one more
  reason the tool beats a skill script here — but give it an explicit timeout of its own
  rather than inheriting a default.
- Prefer GGUF quantization over fp8 in the documented defaults. Ampere has no FP8 tensor
  cores, so fp8 saves memory but runs by emulation — a `(p)`-style honesty note in the
  config comments, not a silent choice.

**Key files** — `backend/packages/harness/deerflow/community/comfyui/`,
`skills/public/image-refine/` (extended or a sibling), `config.example.yaml`,
`backend/tests/test_comfyui_video.py` (new).

**Done when** — a clip generates, renders in the artifact panel, is judged from its
contact sheet, and measurably improves on iteration 2.

---

## 16. Guarded local model downloads

**Goal** — New checkpoints arrive without leaving the chat, under limits an operator sets
rather than limits the agent chooses.

**Why it fits** — "Local models" is only self-service if acquiring them is. But this is
the sharpest edge in the whole feature: it is unattended file download onto the host, and
its obvious extension — installing custom nodes — is arbitrary code execution against the
machine holding your GPU and your data.

**Depends on** — item 12.

**Scope**

- A `download_model` tool: `.safetensors` (and `.gguf`) only, host allowlist, size cap,
  checksum recorded, target directory fixed by config.
- **Operator-gated, following the extensions precedent.** The extensions system keeps its
  source list in `config.yaml` rather than the API-writable `extensions_config.json`
  specifically because that list causes code to execute with Gateway privileges. Model
  downloads deserve the same treatment: the allowlist and the target directory are
  operator config, not agent-settable.
- **Never install custom nodes.** Not behind a flag, not with a confirmation. If that
  capability is ever wanted it is its own roadmap item with its own argument.
- Do not drive ComfyUI-Manager's endpoints. They are not a stable public API and a
  breakage there would surface as an unexplained failure in an unrelated tool.
- Re-read `/object_info` after a download so the new checkpoint is selectable without a
  restart, and say plainly in the docs if a given loader still needs one.

**Key files** — `backend/packages/harness/deerflow/community/comfyui/`,
`config.example.yaml`, `SECURITY.md` (allowlist rationale),
`backend/tests/test_model_download_guards.py` (new).

**Done when** — a disallowed host, an oversized file and a non-weights extension are each
refused with a clear reason; a permitted download is selectable in the next generation
without a restart; and no code path can install a custom node.

---

## 17. Output egress for the external AIO sandbox

**Goal** — Files an agent writes to `/mnt/user-data/outputs` are viewable regardless of
which AIO sandbox mode is configured — or the mode says loudly that they are not.

**Why it fits** — This is a gap found while scoping item 12, and it is not specific to
media. `make sandbox-enable` defaults to **external** mode (one shared container on
`:8091`). In that mode `mounts:` are ignored, `uses_thread_data_mounts` is false, and
unlike `e2b_sandbox_provider.py::_sync_outputs_to_host` there is no sandbox→host output
sync for AIO at all. `backend/app/gateway/routers/artifacts.py` resolves host paths, so
anything written inside that container is invisible to `present_files` and the artifact
panel. The failure is silent: the agent reports success and the user sees nothing.

External mode also cannot fix this with a volume, because the virtual path
`/mnt/user-data/outputs` is singular while the host directories are per-thread — which
means the honest options are a sync pass or a warning, not a compose-file tweak.

**Depends on** — nothing.

**Scope**

- Either implement a release-time output sync for AIO external mode, bounded the way E2B's
  is (per-file size cap plus aggregate file/byte/deadline ceilings, manifest-based so
  unchanged files are not re-downloaded), or decide that mode does not support outputs and
  make that explicit.
- If explicit: warn at Gateway startup when the sandbox resolves to external mode, and
  surface it in `make doctor` next to the deployment section from item 11.
- Either way, correct the docs. `docker/docker-compose.sandbox.yml`'s comments invite
  adding mounts for this, and `config.example.yaml` describes external mode without
  mentioning that outputs do not reach the host.
- `make sandbox-enable`'s default mode is worth revisiting in the same pass: `container`
  is the mode whose `/mnt/user-data` contract actually holds.

**Key files** —
`backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py`,
`backend/packages/harness/deerflow/community/e2b_sandbox/e2b_sandbox_provider.py` (the
bounded-sync shape to copy), `scripts/sandbox_toggle.py`, `scripts/doctor.py`,
`docker/docker-compose.sandbox.yml`, `config.example.yaml`,
`backend/tests/test_aio_sandbox.py`.

**Done when** — a file written to outputs inside an external-mode sandbox either appears
in the artifact panel or produces a warning that names the mode and the fix; and the
config documentation states which modes honour the `/mnt/user-data` contract.

---

## Deliberately not on this roadmap

**More model providers, more IM channels, more bundled skills.** The model bundle is
curated to a documented shape and FORK.md is explicit that a long list dilutes both the
picker and the auto-config. Breadth there adds work to every audit pass (item 4) and buys
a single-user deployment nothing.

**GPU passthrough into the sandbox container.** Items 12 and 13 deliberately run ComfyUI
as its own long-lived service instead. `LocalContainerBackend._start_container` builds its
`docker run` argv by hand and has no `--gpus` flag; adding one is a few lines, but sandbox
containers are per-thread, `--rm`, warm-pooled and idle-reaped, so every new conversation
would reload tens of gigabytes of weights, and a models directory is large stateful data
with no business inside an ephemeral container. The fork already answered this question
once for local inference: Ollama runs on the host and containers reach it through the
mapped host-gateway alias.
