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
deleted from this file. Their numbers stay retired because the codebase cites them
(`grep -rn "roadmap item"` finds 16 references across workflows, routers and test
docstrings), so recycling one would silently point an existing comment at unrelated work.
What each became is documented in [FORK.md](./FORK.md) and its post-sync feature
checklist.

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

**GPU passthrough into the sandbox container.** Items 12 and 13 deliberately run ComfyUI
as its own long-lived service instead. `LocalContainerBackend._start_container` builds its
`docker run` argv by hand and has no `--gpus` flag; adding one is a few lines, but sandbox
containers are per-thread, `--rm`, warm-pooled and idle-reaped, so every new conversation
would reload tens of gigabytes of weights, and a models directory is large stateful data
with no business inside an ephemeral container. The fork already answered this question
once for local inference: Ollama runs on the host and containers reach it through the
mapped host-gateway alias.
