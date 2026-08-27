# Roadmap

Candidate improvements for this fork, written as **orchestrator prompts** — each item is
self-contained enough to hand to a coding agent as a single unit of work.

The fork's thesis (see [FORK.md](./FORK.md)) is a **personal AI you host at home**:
private, cheap, reached from your phone over Tailscale, mixing free local Ollama models
with paid cloud keys. Every item below either extends that thesis or reduces a risk that
surfaced while working against it.

Nothing here is committed work. Items are ordered by dependency and value, not priority —
pick per appetite.

**Shipped items are removed, and their numbers are not reused.** Items 1–11 — the set
derived from the original comparison against upstream
[bytedance/deer-flow](https://github.com/bytedance/deer-flow) — all landed and have been
deleted from this file, and items **12–15** (local image generation through a ComfyUI
service, the GPU residency arbiter, the self-critiquing refine loop, and local video)
landed together as one change set: see [FORK.md §23](./FORK.md) and its three rows in the
post-sync feature checklist. Their numbers stay retired because the codebase cites them
(`grep -rn "roadmap item"` finds references across workflows, routers and test
docstrings), so recycling one would silently point an existing comment at unrelated work.

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

## 16. Guarded local model downloads

**Goal** — New checkpoints arrive without leaving the chat, under limits an operator sets
rather than limits the agent chooses.

**Why it fits** — "Local models" is only self-service if acquiring them is. But this is
the sharpest edge in the whole feature: it is unattended file download onto the host, and
its obvious extension — installing custom nodes — is arbitrary code execution against the
machine holding your GPU and your data.

**Depends on** — the shipped local media generation (former item 12; FORK.md §23).

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

**Why it fits** — This is a gap found while scoping the local media work (former item
12; FORK.md §23), and it is not specific to media. `make sandbox-enable` defaults to **external** mode (one shared container on
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
  surface it in `make doctor` next to its Deployment section (`scripts/exposure.py`).
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

## 18. Mobile chat layout audit

**Goal** — The chat surface is usable one-handed on a phone, not merely reachable from one.

**Why it fits** — This is the half of the PWA work (FORK.md §16) that was deliberately left
open when the rest shipped, and it is the only unfinished thing among items 1–11. Push
delivery, the installable manifest and the service worker all landed, so the fork now
does "start a sandbox run from my phone over Tailscale, pocket it, get pinged when it's
done" — right up to the moment you tap the notification and land on a desktop-shaped
layout. The remaining gap is the part the user actually touches.

**Depends on** — nothing.

**Scope**

- The keep-alive tab strip and the artifact panel are the two known offenders; both are
  still desktop-shaped on a narrow viewport.
- Audit the whole chat route at phone widths rather than only those two — composer,
  message actions, the model picker (which already has a documented clipping history at
  narrow widths), and the workspace navigation.
- Behavioural parity is the bar, not visual parity: anything reachable on desktop must be
  reachable on a phone, even if it moves into a sheet or a menu.
- Do not regress the desktop layout. This fork is used from both, and the desktop surface
  is where the long sessions happen.

**Key files** — `frontend/src/components/workspace/`, `frontend/src/app/workspace/`,
`frontend/tests/`.

**Done when** — the chat route has no horizontal overflow at 390px wide; the tab strip and
artifact panel are operable at that width; and the desktop layout is unchanged.

---

## Deliberately not on this roadmap

**More model providers, more IM channels, more bundled skills.** The model bundle is
curated to a documented shape and FORK.md is explicit that a long list dilutes both the
picker and the auto-config. Breadth there adds work to every pass of the model and
pricing audit (`scripts/audit_models.py`) and buys a single-user deployment nothing.

**GPU passthrough into the sandbox container.** The shipped media work (FORK.md §23)
deliberately runs ComfyUI as its own long-lived service instead. `LocalContainerBackend._start_container` builds its
`docker run` argv by hand and has no `--gpus` flag; adding one is a few lines, but sandbox
containers are per-thread, `--rm`, warm-pooled and idle-reaped, so every new conversation
would reload tens of gigabytes of weights, and a models directory is large stateful data
with no business inside an ephemeral container. The fork already answered this question
once for local inference: Ollama runs on the host and containers reach it through the
mapped host-gateway alias.
