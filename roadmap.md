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
Removing a shipped item means removing its **At a glance** bullet in the same edit — an index
that outlives the item it points at is worse than no index.

Items **16–18** came out of working against the fork itself — gaps and loose ends noticed
while shipping earlier ones. Items **19–25** came from a different exercise: reading the
codebase against what the wider AI ecosystem settled on during 2026, and keeping only the
ideas that this fork's own thesis argues for. The rejected candidates from that pass are
recorded at the bottom of this file, because knowing what was considered and declined is
worth as much as the list itself.

Items **26–31** came from scouting what a connected Grok subscription reaches beyond chat
(2026-10-27). The Settings → Models connection (FORK.md §41) only uses Grok's chat proxy,
while xAI lets the same subscription login drive Grok Imagine, voice and X search through
its public API. Every one of those sends prompts — and, for edits, your images — to xAI,
so they arrive as opt-in features beside the local defaults, never as replacements.

---

## At a glance

Open items, one line each. The full orchestrator prompts follow.

- **16. Guarded local model downloads** — new checkpoints arrive without leaving the chat,
  under limits an operator sets; never custom nodes, not even behind a flag.
- **17. Output egress for the external AIO sandbox** — a file written to
  `/mnt/user-data/outputs` either reaches the artifact panel or says loudly that it cannot.
- **18. Mobile chat layout audit** — the chat route operable one-handed at 390px, with the
  desktop layout unchanged.
- **19. Local voice** — a spoken round trip from a phone on the tailnet, with no audio
  leaving the machine on the default path.
- **20. Measure, then expose, the local speed layer** — tokens/sec and TTFT per local model,
  and draft/MTP decoding where this host actually supports it.
- **21. Local embedding retrieval for DeerMem** — paraphrase recall without shipping the
  facts to a remote memory backend.
- **22. Event triggers** — a task fires because something happened, dispatched through the
  existing run lifecycle rather than a parallel one.
- **23. An untrusted-content boundary** — provenance as a second axis beside tool-name
  gating, with the consequential tools gated on it.
- **24. Track the MCP 2026-07-28 specification** — audit the fork's deepest surface against
  the stateless core and its neighbours.
- **25. A behavioural regression suite** — opt-in, judged, out of CI; the measuring stick for
  everything above it.
- **26. Grok API reach and feature switches** — measure which xAI features the connected
  Grok login can call, and let the operator switch each one on; the base for 27–31.
- **27. Grok Imagine images** — generate and edit pictures on the Grok subscription, landing
  in the artifact panel like ComfyUI output.
- **28. Grok Imagine video** — text-, image- and reference-to-video clips, with stills the
  agent can judge.
- **29. X search** — search X posts through Grok and answer with links to the posts.
- **30. Responses-only Grok chat models** — the Grok models the catalog drops today,
  selectable in the picker.
- **31. Grok voice, as a labelled cloud tier** — read-aloud and transcription on the
  subscription, off by default, beside item 19's local voice.

**Suggested order for 19–25.** Voice first (19), since it is the one missing modality and it
closes a live privacy leak. Then the injection boundary (23), *before* anything widens the
surface it defends. Then the two that make local models worth preferring rather than
tolerating (20, 21). Then proactive triggers and spec upkeep (22, 24). The regression suite
last (25), because every earlier item is a change it would have measured.

**Suggested order for 26–31.** The probe and switches first (26): every later item needs
its proof that the token reaches `api.x.ai` and its per-feature gate. Then images (27),
then video (28), which reuses 27's client, path handling and output writer. X search (29)
and the Responses models (30) are independent of each other. Voice last (31), because it
needs the most UI and must not pre-empt item 19's local-first default.

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

## 19. Local voice — speech in, speech out, without the audio leaving

**Goal** — Hold a spoken conversation with the instance from a phone on the tailnet, with
no audio reaching a third party.

**Why it fits** — The fork's shape is already "start a run from your phone over Tailscale,
pocket it, get pinged when it's done" (FORK.md §16). Voice is the modality that shape is
missing: the one input that works while walking or cooking, and the one the PWA cannot
fake. It is also the single place where the fork's own privacy claim currently leaks
silently — `frontend/src/core/voice-input/speech-recognition.ts` is the browser Web Speech
API, which on Chrome ships the audio to Google. A fork whose entire thesis is "your data
stays on your machine" should not have a microphone button that means the opposite without
saying so.

The hardware argument is already settled by the media work: the card that holds a diffusion
checkpoint has room for a small STT and a small TTS model, and `arbiter.py` exists
precisely to stop tenants from thrashing each other off it.

**Depends on** — the GPU residency arbiter (former item 12; FORK.md §23).

**Scope**

- STT and TTS run as their own long-lived local services reached over HTTP, the way
  ComfyUI is — not in-process, and not in the sandbox. The reasoning is the one already
  recorded under "GPU passthrough into the sandbox container": weights are large stateful
  data with no business inside a per-thread, `--rm`, warm-pooled container.
- **A resident tenant is a new arbiter concept, not a third `kind`.** `GpuTenantConfig.kind`
  is `Literal["ollama", "comfyui"]` and the semaphore is depth-1 — "one tenant at a time".
  Voice models are ~100 MB–1 GB and want to stay resident *through* a lead-model turn, which
  is the opposite of what the current eviction contract expresses. Model that explicitly
  (a pinned class that is never evicted and never evicts) rather than bolting voice onto the
  evictable path, where every spoken turn would cost a lead-model reload.
- Stream TTS against the token stream, not after the final answer. Synthesizing a finished
  response makes perceived latency the whole response, which is the difference between a
  usable voice mode and a demo.
- Push-to-talk only. An always-listening microphone is a different feature with a different
  consent story and it must not arrive as a side effect of this one.
- If the Web Speech path stays as a fallback, label it in the UI as the one that leaves the
  machine. Offering no voice is better than offering cloud voice unmarked.

**Key files** — `frontend/src/core/voice-input/`,
`frontend/src/components/workspace/input-box.tsx`,
`backend/packages/harness/deerflow/community/comfyui/arbiter.py`,
`backend/packages/harness/deerflow/config/media_config.py`, `config.example.yaml` (a
`voice:` section shaped like `media:`), `scripts/doctor.py`, `scripts/detect_comfyui.py`
(the detect-or-start precedent), `backend/tests/test_voice_service.py` (new).

**Done when** — a phone on the tailnet completes a spoken round trip; `make doctor` reports
the voice services the way it reports ComfyUI and SearXNG; the default path sends no audio
off the machine; and a spoken turn does not evict the lead model mid-answer.

---

## 20. Measure — then expose — the local speed layer

**Goal** — Know what the local models actually cost in latency, and turn on the 2026
decoding wins where this machine supports them.

**Why it fits** — The cost story (FORK.md §Cost story) rests on a boundary: free local
models do the ordinary work, paid keys do the hard work. That boundary is set by local
*speed* as much as by local quality — a subagent that answers three times slower gets routed
around by hand, and then the 95%-saving row in that table is aspirational rather than
lived. The same section already admits the gap in its own footnote: subagent quality is
something "you should benchmark on your actual tasks", and there is no benchmark.

Meanwhile the decoding layer moved. Ollama grew a `DRAFT` Modelfile directive and MTP
speculative decoding, but it landed on the MLX runner first and rolled out unevenly across
backends — which for this fork's Arch/NVIDIA host means the honest answer is *unknown*, not
*yes*. The fork drives Ollama with its defaults and exposes no knob and no measurement, so
there is currently no way to find out.

**Depends on** — nothing.

**Scope**

- A repeatable local bench: fixed prompts, tokens/sec and time-to-first-token, per configured
  local model, written where a later run can diff against it. Model it on
  `scripts/audit_models.py` — an opt-in pass with a dated log, not a CI gate — and log it
  next to `docs/model-audit-log.md`.
- Detect and report whether the installed Ollama supports draft/MTP decoding on *this*
  backend before offering to configure it. Reporting "not available on this runner" is a
  successful outcome for this item; guessing is not.
- If it is available: a config surface for pairing a small draft model with a large target,
  and wizard support for syncing both (`scripts/wizard/steps/ollama.py`,
  `scripts/sync-api-key-models.py`) so a paired setup survives a re-sync.
- Feed the numbers back to the feature that needs them: cost-aware subagent routing
  (FORK.md §15) picks models on price, and price without latency is half the decision.
- Opt-in throughout. A speculative-decoding setup that backfires on a given model/hardware
  pair is a real outcome, and the bench is what should decide it.

**Key files** — `scripts/audit_models.py` (the shape to copy), `scripts/bench_local_models.py`
(new), `docs/model-audit-log.md` (sibling log), `scripts/wizard/steps/ollama.py`,
`backend/packages/harness/deerflow/config/model_config.py`,
`backend/tests/test_local_model_bench.py` (new).

**Done when** — one command reports tokens/sec and TTFT for every configured local model and
writes a dated row; the report states plainly whether draft/MTP decoding is available on this
host; and if it is, enabling it is a documented config change whose effect the same command
measures.

---

## 21. Local embedding retrieval for DeerMem

**Goal** — Memory recall that survives the user not reusing the same words.

**Why it fits** — DeerMem's retrieval adapter is SQLite FTS5/BM25 with a substring fallback:
lexical matching, no semantics. It is a good default — rebuildable derived data, no extra
service, no vendor — and it is why the fork can ship memory that works offline. But it misses
the paraphrase, which is the ordinary case in a personal assistant ("what did I decide about
the car" against a fact stored as "chose the Skoda over the Toyota"). The alternatives the
backend registry already offers — `mem0`, `honcho`, `openviking` — all solve this by sending
the facts to someone else's service, which is the trade this fork exists to refuse.

Ollama is already running and already serves embedding models. The missing piece is small:
one more adapter behind the same `RetrievalPort`.

**Depends on** — nothing. (Sequence it after item 20 if the bench exists, so the added
latency per recall is a measured number rather than an impression.)

**Scope**

- A second `RetrievalPort` adapter using a local embedding model through the existing Ollama
  connection, selected by config, with FTS5 remaining the default and the fallback.
- Hybrid, not replacement. BM25 wins on names, IDs, and exact strings; embeddings win on
  paraphrase. Fuse both rather than swapping one for the other.
- Honour the existing derived-data contract: the vectors are rebuildable, live beside the
  FTS index, and a corrupt store is deleted and rebuilt once before falling back — the same
  discipline `retrieval.py` already applies.
- Re-embedding on a model change is a migration, not a silent degradation. Record the model
  and dimension with the index and rebuild when they change.
- No new service and no new daemon. If it needs a vector database, it is the wrong design
  for this item.

**Key files** —
`backend/packages/harness/deerflow/agents/memory/backends/deermem/deermem/core/retrieval.py`,
`.../core/storage.py` (the `RetrievalPort` boundary),
`backend/packages/harness/deerflow/config/memory_config.py`,
`backend/packages/harness/deerflow/agents/memory/AGENTS.md`,
`backend/tests/test_memory_retrieval_embeddings.py` (new).

**Done when** — a paraphrased query retrieves a fact that BM25 alone misses; FTS5 remains
the default and still works with the adapter disabled; an embedding-model change triggers a
rebuild rather than silently mixing dimensions; and recall latency is documented.

---

## 22. Event triggers — the scheduler learns to watch, not only to wait

**Goal** — A task can fire because something happened, not only because a clock said so.

**Why it fits** — The fork already has every part of a proactive assistant except the
trigger. Scheduled tasks run non-interactively through the normal run lifecycle; push
notifications survive a closed browser (FORK.md §16); the IM channels give it somewhere to
speak. What it lacks is a reason to start: `scheduler/schedules.py` understands `cron` and
one-shot times and nothing else, so every "tell me when X happens" has to be spelled as
"check every fifteen minutes whether X happened" — which burns tokens on the 95% of polls
that find nothing, and still reports late.

This is also where the protocol is going: the MCP 2026 roadmap names triggers and
event-driven updates as an explicit direction, so building the concept now means adopting a
standard later rather than inventing one.

**Depends on** — the scheduled-task MVP and the PWA push work (FORK.md §16).

**Scope**

- A trigger abstraction alongside the schedule types, dispatching through the *same*
  `launch_scheduled_thread_run` path. `backend/AGENTS.md` is explicit that the scheduler may
  decide when work runs but must not grow a parallel execution stack; that rule governs this
  item completely.
- Start with sources the fork already has credentials for rather than adding integrations:
  a filesystem watch, an IM message matching a pattern, an HTTP webhook endpoint. Resist the
  urge to ship an email trigger in the same change — it is the one that needs its own
  auth story.
- The one-active-occurrence invariant is the hard part, not the watching.
  `uq_scheduled_task_run_active` allows one non-terminal occurrence per task, and an event
  source can fire ten times in a second. Decide the coalescing rule explicitly — latest-wins,
  debounce window, or queue-one-more — and pin it with a test that fires a burst.
- Every trigger needs a rate limit and a kill switch reachable from the UI. A misconfigured
  watch on a busy directory is an infinite loop that spends money, and `spend_budget`
  (FORK.md §10) is the backstop, not the design.
- **Treat trigger payloads as untrusted input.** The content that fires a run frequently
  becomes the content the run reasons about, which is item 23's problem arriving through a
  new door.

**Key files** — `backend/packages/harness/deerflow/scheduler/schedules.py`,
`backend/packages/harness/deerflow/config/scheduler_config.py`,
`backend/app/gateway/routers/github_webhooks.py` (an existing webhook receiver to model on),
`frontend/src/app/workspace/scheduled-tasks/`, `config.example.yaml`,
`backend/tests/test_scheduler_triggers.py` (new).

**Done when** — a file appearing in a watched directory starts a run that pushes a
notification to a phone; a burst of ten events produces exactly the coalescing behaviour the
tests specify and never a second concurrent occurrence; and every trigger can be paused from
the workspace page.

---

## 23. An untrusted-content boundary for the agent loop

**Goal** — Web pages, tool output, and file contents cannot quietly redirect the agent, and
when they try, it is visible.

**Why it fits** — This fork reads the open web by default (SearXNG, Camoufox, the fetch
tools), runs MCP servers, holds cloud API keys, and can spend real money. Prompt injection
is the #1 entry in the OWASP LLM top ten and Google measured a 32% rise in injection
payloads embedded in web content over a single recent quarter — which means the fork's most
distinctive surfaces are also its most exposed ones. The defences it has are real but
partial and each covers one door: `url_safety.py` screens SSRF, the MCP stdio allowlist
screens what a config can launch, the sandbox screens what code can touch. None of them
covers the case where a page the agent *legitimately* fetched contains instructions.

There is a good anchor to build on rather than a green field: `guardrails/` already defines a
provider interface with `GuardrailDecision` / `GuardrailRequest` and an allowlist provider.
It gates tools by name today; the missing axis is provenance.

**Depends on** — nothing. Item 22 widens the surface this covers, so landing this first is
worth something.

**Scope**

- Mark content by origin at the point it enters the loop — fetched pages, tool results,
  file reads, trigger payloads — and keep the marking through summarization and memory
  extraction, which are exactly where provenance is currently lost.
- Gate the *consequential* tools on it: spending, sending (IM channels), writing outside the
  workspace, installing anything. Reading is not where the blast radius is. The capability
  framing matters more than detection — the 2026 consensus is that no filter catches every
  injection, so the design goal is a bounded blast radius, not a clean detector.
- Extend the existing guardrail provider rather than adding a parallel mechanism, so
  `guardrails_config.py` stays the one place an operator looks.
- Surface it in the UI. A blocked action the user never sees is a bug report about the agent
  being broken; the system prompt is already a text box (FORK.md §19), so this fork's
  precedent is to show the machinery rather than hide it.
- **Memory is the persistence path and deserves its own test.** An injected instruction that
  gets extracted into a durable fact survives every future conversation, which turns a
  one-page compromise into a permanent one.

**Key files** — `backend/packages/harness/deerflow/guardrails/` (provider, middleware,
builtin), `backend/packages/harness/deerflow/config/guardrails_config.py`,
`backend/packages/harness/deerflow/community/url_safety.py`,
`backend/packages/harness/deerflow/agents/memory/` (the extraction path),
`backend/packages/harness/deerflow/agents/middlewares/`, `SECURITY.md`,
`backend/tests/test_untrusted_content_boundary.py` (new).

**Done when** — a fetched page carrying an instruction to send a message or spend money is
refused with a reason naming the origin; the refusal is visible in the conversation; an
injected instruction does not reach durable memory; and ordinary browsing and tool use are
unaffected.

---

## 24. Track the MCP 2026-07-28 specification

**Goal** — The fork's largest integration surface stays current with the standard it
implements.

**Why it fits** — MCP is where this fork has invested most heavily outside the agent itself:
three transports, OAuth, per-request credential mapping, interceptors, a stdio session pool,
a durable long-running-task runtime with leases and dead-lettering. All of that is written
against a specification that moved materially in 2026 — a stateless protocol core,
multi-round-trip requests, header-based routing, cacheable list results, authorization
hardening, and a formal extensions framework — and the protocol is now under
vendor-neutral governance at the Linux Foundation rather than one vendor's roadmap.

The reason to schedule this rather than let it drift: the fork's own value here is *depth*,
and depth against a moving spec is what turns into a silent incompatibility with a server
somebody wants to use. The stateless core in particular is a direct fit — it removes sticky
sessions, which is the assumption `session_pool.py` is built around.

**Depends on** — nothing.

**Scope**

- Audit first, implement second, and write the audit down. Which spec version does the
  pinned SDK implement, which of the 2026 changes does the fork's own code assume the
  absence of, and which of them would change `session_pool.py`, `cache.py`, or the task
  drivers. This may well be the whole item.
- Cacheable list results are the cheapest concrete win and interact directly with the
  existing content-signature invalidation in `cache.py` — check them for conflict before
  adopting either.
- The extensions framework deserves a deliberate answer, not adoption by default. This repo
  already has a Python extension system with its own security posture (operator-controlled
  `plugins:` in `config.yaml`, precisely because that list executes code); an MCP-level
  extension mechanism must not become a second, weaker path to the same privileges.
- Do not weaken the stdio launch policy in the process. `routers/mcp.py`'s command/args/env
  denylists are pinned against the real launchers' behaviour and are the fork's own work,
  not the spec's.

**Key files** — `backend/packages/harness/deerflow/mcp/` (`client.py`, `session_pool.py`,
`cache.py`, `tasks/`), `backend/packages/harness/deerflow/mcp/AGENTS.md`,
`backend/app/gateway/routers/mcp.py`, `backend/pyproject.toml` (the SDK pin),
`docs/plans/` (the audit).

**Done when** — a written audit states the fork's position against each 2026-07-28 change;
anything adopted has a test; the stdio launch policy is unchanged or strengthened; and
`mcp/AGENTS.md` names the spec version the code targets.

---

## 25. A behavioural regression suite for the agent itself

**Goal** — Answer "did that change make it worse" with a number instead of a hunch.

**Why it fits** — This is the item every other item on this list wants to exist. The fork
now has twenty-three features that shape agent behaviour — fallback chains, cost-aware
routing, democracy, the editable system prompt, memory extraction — and the only current way
to tell whether a change to any of them helped is to use the thing for a week and form an
impression. The cost story asks for exactly this in its own words: swapping subagents to
local models costs "subagent quality you should benchmark on your actual tasks", and there
is nothing to benchmark with.

Note what this is *not*: observability, which the fork already has three of (LangSmith,
Langfuse, Monocle). Traces say what happened in one run. This is about whether the outcome
was good, repeatedly, across a change.

**Depends on** — nothing, but it is most valuable last: every earlier item is a change whose
effect it would measure.

**Scope**

- A small fixed set of tasks reflecting real use of *this* instance — a research question, a
  sandbox coding task, a memory recall across sessions, a tool-selection case with a
  plausible wrong answer — not a public benchmark. The point is regression detection on a
  personal deployment, not a leaderboard.
- Run against the existing tracing rather than beside it. Langfuse metadata is already
  wired at the graph root with session/user/trace attributes; a suite that emits its own
  parallel telemetry is a second thing to maintain.
- Judged, not asserted. Exact-match scoring on agent output produces a suite that fails on
  rewording, which gets muted and then ignored. Use a model as judge with the rubric in the
  repo, and pin the judge model explicitly so a judge upgrade is a visible change.
- **Opt-in and out of CI.** It calls real models and costs real money, which makes it a
  sibling of `make test-live` and `scripts/audit_models.py`, not of `make test`. Dated log,
  run when asked.
- Report per-configuration so the interesting comparison is native: the same tasks under
  all-local, mixed, and all-cloud is precisely the table FORK.md's cost story fills in with
  illustrative numbers today.

**Key files** — `backend/tests/behavioural/` (new, excluded from `make test`),
`scripts/run_behaviour_suite.py` (new), `docs/behaviour-suite-log.md` (new),
`backend/packages/harness/deerflow/tracing/`, `Makefile` (a target beside `test-live`),
`FORK.md` (the cost-story table gains real numbers).

**Done when** — one command runs the suite under a named model configuration and writes a
dated scored row; deliberately degrading a component (a worse subagent model, memory
disabled) moves the score in the expected direction; and the suite never runs in ordinary
CI.

---

## 26. Grok API reach and feature switches

**Goal** — Before any Grok tool exists, know which xAI API features the connected Grok
subscription can actually call, show that in Settings, and let the operator switch each one
on.

**Why it fits** — The subscription is already paid for, so Imagine, X search and voice cost
nothing extra at the margin — the argument that made Ollama the free tier for text. None of
it is proven yet, though. This repo's Grok sign-in uses the Grok CLI's public client ID at
`auth.x.ai/oauth2` and already requests the `api:access` scope (`begin_grok_connection` in
`models/subscriptions.py`), but inference only goes to
`cli-chat-proxy.grok.com/v1/chat/completions`. Hermes Agent sends a SuperGrok token to
`https://api.x.ai/v1` for Responses chat, Imagine, TTS, transcription and `x_search`
([xAI, 2026-05-15](https://x.ai/news/grok-hermes);
[Hermes guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/xai-grok-oauth.md)).
Whether a token issued to the CLI's client is accepted there is unverified, and some
subscribers get HTTP 403 on that API despite an active plan (same guide). A tool the model
can see but the plan cannot call is a failed turn, so availability is measured, not assumed.

**Depends on** — the shipped subscription connections (FORK.md §41).

**Scope**

- **One shared xAI client**, `community/xai/client.py`. It takes the token from
  `deerflow.models.subscriptions.get_access_token("grok")` per request — the same lock and
  refresh rotation chat uses — and never stores it on a tool, model or client object. It
  never retries a 429 or quota error (the subscription chat stance), its errors carry status
  and endpoint only, never the response body, and it identifies as DeerFlow rather than
  impersonating the Grok CLI.
- **A probe on connect and on Refresh models**, beside catalog discovery: one cheap,
  non-generating, read-only call per feature, chosen from docs.x.ai (for example a model list
  for Imagine, `GET /v1/tts/voices` for voice). Record `available`, `not_on_plan` (401/403)
  or `unknown` (network, 5xx) per feature, plus the model IDs the account lists, in the
  encrypted Grok record. A temporary probe failure keeps the previous result, as catalog
  refresh already does.
- **Operator switches, off by default** — `image`, `video`, `x_search`, `voice` — stored in
  the same Grok record (operator-shared, like the connection) and cleared on disconnect. One
  admin-only mutation route (e.g. `PATCH /api/subscriptions/grok/features`) on the drained
  worker path the other subscription mutations use; `GET /api/subscriptions` reports each
  feature's `enabled` and `availability`.
- **Settings UI**: the Grok card in `subscription-settings.tsx` gains a Features list — a
  switch, an availability badge ("On your plan" / "Not on your plan" / "Couldn't check"),
  and one line saying the feature sends prompts (and, for edits, images) to xAI. The switch
  for an unavailable feature is disabled and says why. Strings go in every locale file.
- **Tool exposure is decided here, once**: a `grok_feature_ready(name)` check (connected,
  enabled, available) that `get_available_tools` applies beside the knowledge-group filter,
  so items 27–31 never offer the model a tool that will 403.
- **Extension-first evaluation, recorded.** The tools need the Grok credential, and
  authentication stays in core (AGENTS.md). The extension contract has no credential
  capability, and adding one would hand a refreshable plan token to third-party code. So
  this ships in core beside `community/comfyui/`, with the exception recorded in the
  extensions guide the way the project-shelf summaries exception is.

**Key files** — `backend/packages/harness/deerflow/models/subscriptions.py`,
`backend/app/gateway/routers/subscriptions.py`,
`backend/packages/harness/deerflow/community/xai/` (new),
`backend/packages/harness/deerflow/tools/tools.py`,
`backend/packages/harness/deerflow/extensions/AGENTS.md`,
`frontend/src/components/workspace/settings/subscription-settings.tsx`,
`frontend/src/core/models/subscriptions.ts`, `frontend/src/core/i18n/locales/`,
`backend/tests/test_subscriptions.py`, `backend/tests/test_xai_client.py` (new),
`frontend/tests/unit/components/workspace/settings/model-settings-page.dom.test.tsx`.

**Done when** — connecting Grok shows each feature's availability; a 403 shows "Not on your
plan" and keeps its switch disabled; switches survive a restart and vanish on disconnect;
and no token appears in any response, log or serialized model.

---

## 27. Grok Imagine images — generate and edit

**Goal** — Ask for a picture, or attach one and ask for a change, and get the result from
Grok Imagine in the artifact panel, the same way ComfyUI output arrives.

**Why it fits** — Local ComfyUI needs an NVIDIA GPU and installed weights; without them the
agent falls back to the paid MiniMax/Gemini `image-generation` skill. A Grok subscription
covers that machine at no extra cost, and adds natural-language editing, which the local
templates do not do.

**Depends on** — 26.

**Scope**

- **Two Gateway-side tools** in `community/xai/imagine.py`, shaped like
  `community/comfyui/tools.py` rather than a skill script: the token must never enter the
  sandbox, and writing from the Gateway is what keeps outputs correct under every sandbox
  mode.
  - `grok_generate_image(prompt, aspect_ratio?, n?, filename?)` → `POST /v1/images/generations`.
  - `grok_edit_image(prompt, images, filename?)` → `POST /v1/images/edits` with a JSON body
    (xAI rejects the OpenAI SDK's multipart edit), up to 5 source images
    ([image editing](https://docs.x.ai/developers/model-capabilities/images/editing)).
  - Model IDs come from item 26's probe. The docs say `grok-imagine-image-2.0`, Hermes lists
    `grok-imagine-image`; never hardcode either.
- **Source images are thread files.** Resolve `/mnt/user-data/{uploads,outputs,workspace}`
  virtual paths to host paths with the existing resolver, refuse anything outside the
  thread, cap the size, and send base64 data URIs — a home server has no public URL to give
  xAI.
- **Outputs**: ask for base64 where offered so nothing has to be fetched. If only a URL comes
  back, download it at once (xAI's URLs are temporary) through `url_safety`, with a host
  allowlist pinned from the first live response. Write to `outputs_path`, return the same
  `Command` + `artifacts` shape as ComfyUI so the panel opens the file, and save a
  `<name>.request.json` beside it (prompt, parameters, model — no token) as the
  reproduction record, the way `.workflow.json` is.
- **Not in the `media` group.** `media` is on `OFFLINE_ALLOWED_TOOL_GROUPS`
  (`tools/internet_access.py`) because ComfyUI is local; a cloud tool there would silently
  survive the per-conversation internet switch. Use a new group (e.g. `cloud_media`) and pin
  the exclusion in `test_internet_toggle.py`.
- **Local or Grok**: the tool docstrings say plainly that Grok leaves the machine and spends
  plan quota. Update the `image-generation` and `image-refine` skills so local ComfyUI stays
  the default when it is reachable, and Grok is used when asked for, for edits, or when
  there is no GPU. Refine sessions count Grok generations too (`session_id`, `sessions.py`).
- **Quota**: SuperGrok image limits are unpublished and move without notice, and failed
  generations reportedly count
  ([secondary source](https://www.atlascloud.ai/blog/guides/grok-xai-image-generation-daily-limit)).
  No retries; a limit reaches the user in one sentence.

**Key files** — `backend/packages/harness/deerflow/community/xai/`,
`backend/packages/harness/deerflow/community/comfyui/tools.py` (the shape to copy),
`backend/packages/harness/deerflow/community/comfyui/sessions.py`,
`backend/packages/harness/deerflow/tools/internet_access.py`, `config.example.yaml` (tool
entries and group), `skills/public/image-generation/SKILL.md`,
`skills/public/image-refine/SKILL.md`, `backend/tests/test_grok_imagine_tools.py` (new),
`backend/tests/test_internet_toggle.py`.

**Done when** — "draw a lighthouse at dusk" and "make the sky in this photo purple" (with an
attachment) each put a PNG in the artifact panel; with internet off, no Grok tool is
offered; with the feature off or Grok disconnected, the tools are absent; and a quota error
reaches the user without a retry.

---

## 28. Grok Imagine video

**Goal** — Short clips from text, from an attached still, or from reference images,
generated on the Grok subscription and playable in the artifact panel.

**Why it fits** — Local video is the heaviest thing the fork asks of a GPU: minutes per clip
on a 24 GB card, and impossible without one. `grok-imagine-video-1.5` documents clips up to
15 s at native 1080p, image-to-video, and up to 14 reference images
([video generation](https://docs.x.ai/developers/model-capabilities/video/generation)).

**Depends on** — 26, 27 (client, path resolution, output writer).

**Scope**

- `grok_generate_video(prompt, image?, reference_images?, duration?, aspect_ratio?, resolution?, filename?)`
  → `POST /v1/videos/generations` returns a `request_id`; poll `GET /v1/videos/{request_id}`
  until `done`, `failed` or `expired`, then download `video.url` at once (it is ephemeral).
- Its own wall-clock cap and poll interval in config, like `media.comfyui.video_timeout`. A
  cancelled run stops polling and says the remote job may still finish on xAI's side.
- **Stills for the critic.** `view_image` cannot read an MP4, and `comfyui/frames.py` only
  tiles frames ComfyUI already hands back. An xAI clip needs decoding, which the backend
  cannot do today (no PyAV, imageio-ffmpeg or ffmpeg dependency). Decide that dependency
  explicitly; until then the tool returns the MP4 and says no contact sheet was made — it
  never loses the clip over it.
- Video edit and extend are reported in xAI's docs; verify them on docs.x.ai, and add them
  as a follow-up only if the subscription can call them.
- Same group, exposure gate, quota stance and `.request.json` record as 27. Video quotas are
  reportedly small (about 20 a day on standard SuperGrok, same secondary source), so the
  tool description tells the model to confirm with the user before spending one.

**Key files** — `backend/packages/harness/deerflow/community/xai/`,
`backend/packages/harness/deerflow/community/comfyui/frames.py`,
`skills/public/video-generation/SKILL.md`, `config.example.yaml`,
`backend/tests/test_grok_imagine_video.py` (new).

**Done when** — an uploaded still becomes an MP4 that plays in the artifact panel; `failed`
and `expired` jobs are reported as such; a timeout says how long it waited; and a missing
decoder costs the contact sheet, never the clip.

---

## 29. X search

**Goal** — Ask what people on X are saying about something, and get an answer with links to
the actual posts.

**Why it fits** — X is the one corpus the bundled search backends cannot reach: SearXNG,
Tavily and the rest index the web, not X. xAI's `x_search` is a server-side tool on the
Responses API that reads the posts it fetches and cites them
([X Search](https://docs.x.ai/developers/tools/x-search)); on the subscription it draws
plan quota instead of the API's $5 per 1,000 posts
([pricing](https://docs.x.ai/developers/pricing), 2026-10).

**Depends on** — 26. Coordinate with 23: X posts are exactly the untrusted content that
item's boundary exists for.

**Scope**

- An `x_search(query, from_date?, to_date?, handles?)` tool that sends one
  `POST /v1/responses` with a Grok model and `tools: [{"type": "x_search"}]`, and returns the
  answer plus the cited post URLs.
- Group `web`, so the internet switch already removes it; exposure gate from 26.
- Return citations in the shape `web_search` results already use, so the chat's existing
  source rendering shows them. The citation format in Responses output is not clearly
  documented; pin it from a live response in a fixture.
- Mark the result as external, untrusted text in the tool output, and through item 23's
  provenance once that exists.
- Not in scope: xAI's `web_search` as another `web_search` backend — SearXNG already covers
  the web for free.

**Key files** — `backend/packages/harness/deerflow/community/xai/`,
`backend/packages/harness/deerflow/community/web_search/tools.py` (the result shape),
`config.example.yaml`, `backend/tests/test_x_search_tool.py` (new).

**Done when** — a question about a current X discussion returns cited `x.com` links;
internet-off and Grok-off conversations do not offer the tool; and a quota error is
reported, not retried.

---

## 30. Responses-only Grok chat models

**Goal** — Grok models that xAI serves only through its Responses API appear in the model
picker beside the ones that work today.

**Why it fits** — `_catalog` drops Grok entries whose `apiBackend` is `responses` or
`messages` (`models/subscriptions.py`), because the only Grok transport is chat completions
on the CLI proxy. Hermes lists models such as `grok-4.20-multi-agent-0309` and
`grok-build-0.1` on the same subscription through the Responses API — models the plan
already pays for that the picker cannot show.

**Depends on** — 26 (proves the token reaches `api.x.ai`).

**Scope**

- A `GrokResponsesSubscriptionChatModel` on `https://api.x.ai/v1/responses`, with
  `_SubscriptionChatOpenAI`'s request-local auth but `use_responses_api=True` — or built on
  the ChatGPT adapter's Responses transport if LangChain's Responses mode loses xAI's
  reasoning state. Decide by testing reasoning replay across a tool follow-up, the property
  the ChatGPT adapter already pins.
- Catalog: route `apiBackend: responses` entries to the new class instead of dropping them;
  keep dropping `messages` until there is a reason not to.
- Every subscription invariant still holds: no fallback chain, no per-token price, distinct
  usage names, credentials never on the model. `x-grok-model-override` stays proxy-only
  unless a live call shows the API needs it.

**Key files** — `backend/packages/harness/deerflow/models/subscription_providers.py`,
`backend/packages/harness/deerflow/models/subscriptions.py`,
`backend/packages/harness/deerflow/models/AGENTS.md`,
`backend/tests/test_subscription_providers.py`, `backend/tests/test_subscriptions.py`.

**Done when** — a Responses-only Grok model appears after Refresh models, completes a
tool-calling turn, and keeps its reasoning across the follow-up; existing proxy models are
unchanged.

---

## 31. Grok voice, as a labelled cloud tier

**Goal** — A "read aloud" button on answers and a transcription tier for the microphone,
both on the Grok subscription, both off by default and labelled as leaving the machine.

**Why it fits** — Only as an opt-in tier, and that is the first thing to settle. Item 19
argues for voice that never leaves the house, and the speech module's first invariant is
that the cloud tier is off by default. xAI's TTS (`POST /v1/tts`, voices from
`GET /v1/tts/voices`) and transcription (`grok-voice-transcribe-2.0`)
([TTS](https://docs.x.ai/developers/model-capabilities/audio/text-to-speech),
[STT](https://docs.x.ai/developers/models/speech-to-text)) make a good cloud tier for a
machine with no local voice models — under the opt-in `voice.allow_cloud_fallback` that
already exists for exactly this, never as the default.

**Depends on** — 26. Read item 19 first; this must not pre-empt its local path.

**Scope**

- **Read aloud**: a message action that calls a new Gateway route (e.g.
  `POST /api/voice/speak`), which calls xAI TTS with the Grok token and streams the MP3 back
  to an `<audio>` element. The text is capped server-side, and the UI says it goes to xAI.
- **Transcription**: xAI as the cloud tier behind `voice.allow_cloud_fallback`. The current
  client speaks OpenAI's `/v1/audio/transcriptions`; xAI's REST STT path is not confirmed to
  be that shape, so expect a second adapter rather than a base-URL change.
- Keep the speech module's invariants: the size cap is enforced while reading, errors never
  echo the service body, and Tailscale CGNAT still counts as local.
- Out of scope: the realtime Voice Agent API (see *Deliberately not on this roadmap*).

**Key files** — `backend/packages/harness/deerflow/community/speech/`,
`backend/app/gateway/routers/voice.py`,
`backend/packages/harness/deerflow/config/voice_config.py`,
`frontend/src/core/voice-input/`,
`frontend/src/components/workspace/messages/message-list-item.tsx` (message actions),
`backend/tests/test_voice_stt.py`.

**Done when** — with the cloud tier off, nothing reaches xAI and the button is absent; with
it on, an answer plays aloud on a phone over the tailnet and a recording is transcribed; and
the UI names xAI as the destination both times.

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

**Fine-tuning or LoRA training on the host.** Tempting next to a card that already holds
diffusion checkpoints, and wrong for this fork. Training is a long-running, stateful,
babysat job with its own dataset management and its own failure modes; the fork is an
*inference consumer* whose whole GPU story is one card with tenants that evict each other
(FORK.md §23). A training run holds the card for hours, which breaks every other feature on
the machine for as long as it runs. If this is ever wanted it belongs on separate hardware,
reached the way any other model provider is.

**A vector database service.** Item 21 deliberately adds a local embedding *adapter* behind
the existing `RetrievalPort` rather than a new daemon. A personal instance's memory is
thousands of facts, not millions; SQLite already holds the derived index; and the memory
backend registry already offers `mem0`, `honcho`, and `openviking` for anyone who wants a
managed store. Another always-on service to install, monitor, back up, and restore
(`make backup` covers what exists today) is a real cost with no matching benefit at this
scale.

**General desktop / computer-use control.** The most-starred local agents of 2026 got there
by driving the whole machine — browser, terminal, files — and the pull is obvious. The fork
already has the useful half of it: `browser_automation`, the fetch backends, and a sandbox
where code runs under a contract. What it does not have is unconstrained control of the
host session, and that is the one surface where a prompt injection stops being a bad answer
and becomes a keystroke. Item 23 exists because the *current* exposure already justifies a
provenance boundary; widening the blast radius to the desktop before that lands has the
order backwards.

**Grok's realtime Voice Agent API.** Speech-to-speech over a long-lived socket is a
different feature from item 31's push-to-talk tiers: it needs a WebSocket audio path
through nginx, holds the microphone open for the whole session, and sends all of it to
xAI. Item 19's push-to-talk, local-first voice is the one this fork wants; a realtime cloud
agent would make the opposite the default.
