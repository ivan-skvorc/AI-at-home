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

Items **26–31** — Grok features beyond chat on the connected Grok subscription (the
API-reach probe and feature switches, Grok Imagine images and video, X search,
Responses-only Grok models and Grok voice) — landed together as one change set: see
[FORK.md §43](./FORK.md). Their numbers stay retired like 12–15.

Item **32** — Double Plus Ultracode, a composer mode that plans substantive work as a
workflow script on the script-workflows extension (inspired by Claude Code's *ultracode*),
with exactly-once result delivery, shared workspaces and visible workflow spend — landed as
one change set: see [FORK.md §44](./FORK.md). Its number stays retired like 12–15.

Items **33–36** came out of one incident. A local model was handed a Project Gutenberg
cookbook — Escoffier's *A Guide to Modern Cookery*, a 3.3 MB HTML file — and asked for a few
recipes a beginner could manage. It never split the book. It read on until the window was
gone, and the run ended in `github_create_repository`, creating a public repository nobody
had asked for. Each item closes one link in that chain, and every figure quoted in them was
measured on that file. Item **33** and most of **34** — the pre-call window guard and the
window-derived compaction trigger — landed together: see [FORK.md §45](./FORK.md). 33's
number stays retired like 12–15; 34 keeps only its unshipped half.

Item **37** came out of the prompt pass in [FORK.md §47](./FORK.md): a brand-new Flash chat on
a 14B Ollama model was refused because the system prompt and tool schemas alone outgrew its
window. That pass shrank the one prompt every model gets; item 37 is the next step, a prompt
shaped for the model that reads it.

Items **38–39** came out of tuning those windows: once each local model's `num_ctx` was
sized to its GPU and a q8_0 cache, nothing showed what a conversation actually used of it.
Item 38 asks for context what the cost view already does for money. Item **39** — input and
output apart on the Token Usage page, the first thing that question needs — landed: see
[FORK.md §48](./FORK.md). Its number stays retired like 12–15.

Items **40–42** came from wanting the other two apps on this machine —
[StocktonRich](https://github.com/ivan-skvorc/StocktonRich) (newsdesk, and insider
beside it) and [FrontalRobotomy](https://github.com/ivan-skvorc/FrontalRobotomy) —
to feel like parts of this one: the same models, the same Grok sign-in, the same
light and dark look, opened from the empty-chat welcome. The reasoning, the two
machines they already run on, and the look they should share are in
[docs/companion-apps.md](docs/companion-apps.md). They do not pull training into
this fork; that decision stays under *Deliberately not*.

Items **43–50** came from wanting mechanical parts out of the same chat: describe a
bracket, get a script that can be edited, a STEP file for a CAD program and an STL for the
printer, on whichever model the conversation already uses. A separate desktop app was
planned first and dropped, because the models, the three subscription sign-ins, the agent
loop and the artifact panel already live here. The constraint that shapes all eight is the
default install: `LocalSandboxProvider` with `allow_host_bash: false` gives the agent no
shell, so "write a script and run it" is not available where most people start. The CAD
module therefore builds a part **without running what the model wrote**, as an installed
extension, and the files it writes are ordinary outputs that the Files view lists. Item
**43** — a plugin tool can write a bounded, host-checked file into the outputs of the
conversation that called it (`ToolContext.write_output`, extension API 0.2.12) — landed:
see [FORK.md §50](./FORK.md). Item **44** — the CAD module itself, an installable
extension whose `cad_build` tool reads a CadQuery script, performs an allow-list of
operations in a child process and hands over STEP, STL and GLB only for a part that
measured right — landed: see [FORK.md §51](./FORK.md). Both numbers stay retired like
12–15.

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
- **34. A model with an unknown window says so** — an Ollama model without `num_ctx` reads
  its window from `/api/show`, and one that still has none is marked as unprotected.
- **35. Long documents fan out in Ultra and Double Plus Ultracode** — outline first, then
  parts read in parallel by children inside their own windows, reduced hierarchically.
- **36. Consequential tool calls wait for a yes** — creating a repository, pushing, sending
  or spending pauses for approval unless the operator pre-approved it.
- **37. Model-aware system prompts** — one standard prompt as small as it can be, plus tuned
  overlays for a few big-name local and cloud families, each shipped only with measurements.
- **38. Context window analytics** — the header's context number measured the way the guard
  decides, and a per-turn view of what each turn added and what compaction took back out.
- **40. One model plane for the companion apps** — newsdesk and FrontalRobotomy name a
  model; this fork performs the call, with the transport and the Grok sign-in it already
  has. They stop keeping a second copy.
- **41. Companion apps on the welcome screen** — Stockton and Frontal Robotomy open from
  an empty chat, in the light and dark themes, and not from the marketing landing page.
- **42. One card, one turn** — Ollama and training stay on the daily PC; the home server
  only serves the pages; a training run and a chat take turns on the 3090.
- **45. A CAD skill** — the prompt: ask what is missing, write the numbers down, call the
  tool, read the numbers back, and never present a part that failed.
- **46. 3D files open in the artifact panel** — GLB and STL rotate in the panel and the
  reader, on a phone too; STEP after that.
- **47. Geometry decides a delegated part** — a subagent's part passes on the existing
  acceptance checklist or not at all.
- **48. A CAD eval** — one command says which configured model can make the part, what it
  cost, and which operations it reached for that the module does not have.
- **49. Ollama models from Settings** — find, size against the card, pull and delete
  without a terminal; the daemon downloads, under operator limits.
- **50. Full scripts where a container exists** — unrestricted build123d and CadQuery, and
  a native FreeCAD file, for the parts the allow-list cannot express.

**Suggested order for 19–25.** Voice first (19), since it is the one missing modality and it
closes a live privacy leak. Then the injection boundary (23), *before* anything widens the
surface it defends. Then the two that make local models worth preferring rather than
tolerating (20, 21). Then proactive triggers and spec upkeep (22, 24). The regression suite
last (25), because every earlier item is a change it would have measured.

**Suggested order for 34–36.** 36 first: the guard from item 34 removed the likeliest cause
of the stray tool call, but not the reach — a confused model can still create a repository —
and 35 multiplies the number of agents holding write tools. Then 35, which builds on the
part sizing and window accounting that landed in FORK.md §45. 34's remainder is small and can
go any time.

**37** can start any time; its profiles are better measured once item 25's regression suite
exists, and the standard prompt can ship first on its own.

**Suggested order for 40–42.** 40 first: a button that opens a second Grok login is not
the integration. 42 before the first night FrontalRobotomy trains on the PC while anything
else wants the card. 41 last of the three, once the URLs it opens are real; its look is
specified in [docs/companion-apps.md](docs/companion-apps.md), not designed again in the
change.

**Suggested order for 45–50.** 43 and 44 landed (FORK.md §50 and §51): the module builds
and checks a part on the default sandbox. 45 first: the module can build and measure, and
a model left alone still presents its first attempt. 46 next, since a part nobody can look
at is half delivered. 47 before CAD is used in Ultra or Plus Ultracode, where subagents
report on their own work. 48 after 45, and again after every change to the allow-list.
49 is independent of the rest. 50 only if 48 shows that the allow-list, and not the model,
is what stops real parts.

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

Follow CHANGE_CYCLE.md for the change itself; where this block and that file differ, that
file wins. Work on a branch, never on main, and open the pull request when the change is
done. That step does not wait to be asked for.
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

## 34. A model with an unknown window says so

**Goal** — A model whose context window DeerFlow cannot resolve is either given one or
visibly marked as unprotected, instead of silently getting none of the window machinery.

**Why it fits** — The rest of item 34 landed (FORK.md §45): a pre-call guard measures every
request against the serving model's prompt space, drops the oldest tool results or refuses to
send, and compaction's token trigger caps at half a small window. Every one of those — and the
§25 tool-output caps and part sizes before them — is a no-op when `resolve_context_budget`
returns `None`, deliberately, so an unknown window behaves exactly as before. That is the safe
default and the wrong place to stop. `scripts/sync-ollama-models.py` writes `num_ctx` and
`context_window` for the models it syncs, but an Ollama model added in Settings → Models, or
by hand, carries neither — and Ollama's own default window is small (2048 or 4096 tokens by
version), so the model most likely to overflow is the one with no protection at all.

**Depends on** — nothing.

**Scope**

- For an Ollama entry without `num_ctx`, read the model's native context length from
  `/api/show` (`model_info.<arch>.context_length`) the way the sync script does, apply the
  same 32,768 clamp, and set `num_ctx` and `context_window` on the entry — at save time in
  Settings → Models, and at config load for hand-written entries.
- Mark a model with no resolvable window in Settings → Models and in the model picker's
  detail line ("window unknown — overflow protection off"), with the one config key that
  fixes it.
- Keep `resolve_context_budget`'s contract: unknown stays `None`; this item supplies the
  number, it does not guess one.

**Found while scoping (2026-11-09), decide before building:**

- Settings → Models reaches Ollama only as an `openai-compatible` custom endpoint
  (`ChatOpenAI`, `config/managed_models.py`); there is no Ollama preset. Ollama documents
  that its OpenAI API cannot set the context size (its `openai.md`; from memory, verify), so
  `num_ctx` would not reach the daemon there, and writing `context_window` alone would protect
  a window the daemon does not serve. Either save such entries as `ChatOllama`, or read the
  served length (`/api/ps`) rather than the native one.
- Config load is synchronous and re-runs on file change; an `/api/show` read there needs a
  per-(host, model) cache, a short timeout, and must stay off the event loop (the
  `make test-blocking-io` suite).
- "No resolvable window" also counts LangChain model profiles (`_profile_input_tokens`),
  which `/api/models` does not see; the UI marker needs a server-computed flag, not
  `context_window == null`.

**Key files** — `scripts/sync-ollama-models.py` (the `/api/show` read to share),
`backend/packages/harness/deerflow/models/` (the Ollama factory),
`backend/app/gateway/routers/` (managed models), `frontend/src/core/models/management.ts`,
`frontend/src/components/workspace/model-picker-controls.tsx`,
`backend/packages/harness/deerflow/utils/context_budget.py`.

**Done when** — an Ollama model added in Settings → Models without a window gets `num_ctx`
and `context_window` from `/api/show` and the guard engages for it; a model whose window
cannot be found is marked as unprotected in the UI; and a model with a configured window is
untouched.

---

## 35. Long documents fan out in Ultra and Double Plus Ultracode

**Goal** — In Ultra (subagents) and Double Plus Ultracode (script workflows), a document past
the window is split along its outline and read in parallel, each part by a child inside its
own window, then reduced hierarchically — and an outline-first plan reads only the parts the
question needs.

**Why it fits** — "Split the book into parts" is what a user expects these modes to do, and
neither does it. Ultra adds the `task` tool, but neither the lead-agent prompt nor the
subagent prompts mention `analyze_document` or splitting a document; the only steering is the
per-upload text, which FORK.md §45 extended to HTML, EPUB, text and zipped books. `analyze_document` already owns the split
(`documents/chunking.py`, sized by `chunk_chars_for`) and the hierarchical reduce, but it maps
every part with one model at `documents.concurrency: 2`, and it cannot choose parts: asking
for "a few beginner-friendly recipes" pays for all 53 parts of the cookbook. The research
points the same way. *Chain of Agents* (NeurIPS 2024) has workers read consecutive segments
and pass notes to a manager, and reports up to 10% over RAG and full-context baselines
([proceedings](https://proceedings.neurips.cc/paper_files/paper/2024/hash/ee71a4b14ec26710b39ee6be113d7750-Abstract.html)).
*Recursive Language Models* (Zhang, Kraska, Khattab, December 2025) keep the input outside
the window as a variable the model probes and slices in code before recursing on the slices,
and report inputs two orders of magnitude past the window
([arXiv 2512.24601](https://arxiv.org/abs/2512.24601)). Chroma's *Context Rot* (July 2025)
found reliability falling as input grows across the 18 models it tested, even inside their
windows ([report](https://research.trychroma.com/context-rot)) — so the target is a small
part, not one that merely fits. A Double Plus Ultracode script is already the shape RLM
describes: code that plans, fans out with `pipeline()`, and reduces.

**Depends on** — the shipped §45 work (former item 33's HTML/EPUB/zip reading and item 34's
window guard, so every child call stays inside its window) and the shipped workflows
extension (former item 32, FORK.md §44).

**Scope**

- **One part plan.** Expose the chunker as a part plan — line ranges cut at outline headings,
  sized by `chunk_chars_for` for the *child* model's budget — so `analyze_document`, Ultra and
  a workflow script agree on what a part is. A second chunker is the failure to avoid.
- **Outline first.** Before mapping, the plan reads the outline with section sizes and selects
  parts for the question; reading everything stays available, and the coverage line stays
  honest about what was skipped. The upload block caps the outline at 50 headings
  (`MAX_OUTLINE_ENTRIES`) and the cookbook has 3,338, so the plan needs the full outline from
  a tool.
- **Ultra.** When an upload is flagged large and subagents are on, the routing text names the
  plan: delegate parts to subagents — on the Ultra subagent model, FORK.md §3 — with each
  part's line range and the question, then reduce. Or move `analyze_document`'s map step onto
  subagents directly. Pick one path, not both.
- **Double Plus Ultracode.** Add a long-document recipe to the brief in `ultracode.py`: part
  plan, then `pipeline(parts, …, {concurrency})` with a `schema` for the notes, then a
  hierarchical reduce, each child reading only its own range.
- **Concurrency from the GPU.** Take it from the model's parallel slots (FORK.md §34) rather
  than a constant; on one local card, extra parallelism only queues.

**Key files** — `backend/packages/harness/deerflow/documents/chunking.py`,
`backend/packages/harness/deerflow/documents/analysis.py`,
`backend/packages/harness/deerflow/tools/builtins/analyze_document_tool.py`,
`backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py` (routing text),
`backend/extensions/sources/deerflow-extension-workflows/deerflow_extension_workflows/ultracode.py`
and its `examples/` twin, `backend/scripts/benchmark/drift_eval/`.

**Done when** — on the §25a drift corpus and on the cookbook, an Ultra run and a Double Plus
Ultracode run each return a coverage line naming every part read, recover the planted late
fact, and keep every child prompt under its model's window; an outline-first run on a narrow
question reads strictly fewer parts than a full read; and wall-clock time beats sequential
`analyze_document` on the same model and GPU.

---

## 36. Consequential tool calls wait for a yes

**Goal** — A tool call that changes something outside the conversation — creating a
repository, pushing, opening an issue, sending a message, spending — pauses for the user's
approval unless the operator pre-approved it.

**Why it fits** — In the run behind items 33–36, a model asked about recipes created a public
GitHub repository through the GitHub MCP server, whose tools include `create_repository`
beside its reads. No injected text was involved, so item 23's provenance gate would not have
caught it: the instruction came from a confused model, not from fetched content. Today the
only stop is an operator-written denylist (`guardrails` with `AllowlistProvider` and
`denied_tools`), off by default. `McpToolOverride` carries nothing but routing, and scheduled
runs are non-interactive by design, so they have nobody to ask.

**Depends on** — nothing. It shares the `guardrails/` seam with item 23, so one provider
decides both, but it is the other axis: who asked, not where the text came from.

**Scope**

- Classify every tool as **read**, **local write** (inside the thread's workspace) or
  **outward**. Built-ins declare their class. MCP tools take their server's annotations
  (`readOnlyHint`, `destructiveHint`, `openWorldHint`) as a hint only — annotations come from
  the server — so an unannotated tool, or one from an untrusted server, defaults to outward.
- An outward call pauses with a LangGraph interrupt and an approve/deny card in the chat;
  a denial returns a tool error the model sees. Scheduled and other non-interactive runs deny
  outward calls that were not pre-approved, and the run history says why.
- Operator pre-approval per server and per tool in `extensions_config.json`
  (`tools.<name>.approval: auto | ask | deny`, on `McpToolOverride`, which already accepts
  extra fields), mirrored in Settings.
- Ship the GitHub MCP example read-only. The official server takes `--read-only` or
  `GITHUB_READ_ONLY=1` and narrows by `GITHUB_TOOLSETS`
  ([docs](https://pkg.go.dev/github.com/github/github-mcp-server)); the example still
  launches the older `@modelcontextprotocol/server-github`.
- Until this lands, the stop is config: `guardrails.enabled: true` with
  `deerflow.guardrails.builtin:AllowlistProvider` and `denied_tools` listing the write tools
  of every enabled MCP server.

**Key files** — `backend/packages/harness/deerflow/guardrails/` (provider, middleware,
builtin), `backend/packages/harness/deerflow/config/guardrails_config.py`,
`backend/packages/harness/deerflow/config/extensions_config.py` (`McpToolOverride`),
`backend/packages/harness/deerflow/mcp/tools.py`, `extensions_config.example.json` (the
`github` server), `frontend/src/components/workspace/` (the approval card), `SECURITY.md`,
`backend/tests/test_consequential_tool_approval.py` (new).

**Done when** — with the GitHub MCP server enabled, an interactive chat's `create_repository`
call shows an approval card and changes nothing until approved; a denial reaches the model as
a tool error; a scheduled run's outward call is denied with a reason; read tools run without
a prompt; and an MCP tool with no annotations is treated as outward.

---

## 37. Model-aware system prompts

**Goal** — The lead agent's system prompt comes in two shapes. A **standard** prompt, as
small as it can be while keeping every rule that matters, used by default and always on a
small window. And **tuned overlays** for a few big-name model families — local (Qwen, Gemma,
Meta's Muse and Llama, DeepSeek, Mistral) and cloud (Claude, GPT, Grok, Gemini, Kimi) — each
a handful of lines that adjust the standard prompt to how that family reads instructions,
formats answers and calls tools.

**Why it fits** — FORK.md §47 measured the fixed part of a request — system prompt plus tool
schemas — at 15K–22K tokens on a synced 32K Ollama entry, which is what refused a fresh Flash
chat on `deepseek-r1:14b`. That pass cut it to 7.4K–11.4K and the Flash prompt to ~2.5K, but
it is still one prompt for every model, written for a frontier cloud model. Families differ
in ways a single prompt can only average over: how a system message is treated (some local
templates fold it into the first user turn), how tool calls are emitted through Ollama's
chat templates, how much formatting an answer gets by default, and how literally a
capitalized MUST is taken — an emphatic rule a large model needs once can make a small one
over-clarify or refuse. The fork's thesis is local and cloud side by side, so the prompt
should be good for both rather than a compromise between them. Claims like these are
hypotheses until measured, which is why every overlay ships with numbers.

**Depends on** — nothing to start the standard prompt. The overlays are better measured on
item 25's regression suite; until it exists, a fixed task set run by hand will do, recorded
in the PR.

**Scope**

- **The standard prompt.** Split `SYSTEM_PROMPT_TEMPLATE` into a minimal core — identity,
  the user-input and confidentiality boundaries, response style (overview first, detail on
  request, commands in copy-pasteable blocks), file locations, the rules the tool schemas do
  not carry — and optional sections (citation detail, skill-system detail, worked examples)
  that a large window adds back. Keep every placeholder, so a saved `SYSTEM_PROMPT.md`
  (FORK.md §19) still renders and still wins over both shapes.
- **Profiles are data, not forks of the template.** One file per family (for example
  `lead_agent/prompt_profiles/<family>.md`) of additions and replacements at named anchors,
  so an upstream sync that edits the template touches one place, and a profile cannot drop a
  security rule because it cannot see one.
- **Which profile a model gets**: an explicit `prompt_profile:` on the model entry (config
  and Settings → Models), else a match on the model id (`qwen*`, `gemma*`, `llama*`/`muse*`,
  `deepseek*`, `mistral*`, `claude*`, `gpt-*`, `grok-*`, `gemini*`, `kimi*`), else standard.
  Resolve it where the small-window decision is made (`assemble_lead_agent`), and record it
  in the assembly descriptor so a trace says which prompt a run had.
- **Measured, never guessed.** An overlay ships only with a recorded comparison against
  standard on its family: answer length, overview-first compliance, fenced and runnable
  command blocks, valid tool calls, clarification and refusal rate, and tokens per answer.
  One that does not beat standard is not shipped.
- **The critical context-fit check runs per profile**: no profile may push any composer mode
  over `FIXED_REQUEST_ALLOWANCE_TOKENS` on a small window.
- **Visible and reversible**: Settings → System prompt shows which profile each model gets,
  and an administrator can switch profiles off and fall back to standard.

**Key files** — `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`,
`backend/packages/harness/deerflow/agents/lead_agent/system_prompt_store.py`,
`backend/packages/harness/deerflow/agents/lead_agent/agent.py`,
`backend/packages/harness/deerflow/config/model_config.py`,
`backend/packages/harness/deerflow/agents/assembly_descriptor.py`,
`backend/tests/test_context_fit_critical.py`,
`frontend/src/components/workspace/settings/` (the system prompt page), `scripts/benchmark/`.

**Done when** — the standard prompt renders by default, is smaller than today's and passes
the existing prompt contract tests; at least four overlays (two local families, two cloud)
ship, each with a recorded comparison that beats standard on its family; an unknown model
gets standard; a saved `SYSTEM_PROMPT.md` is untouched; and the critical context-fit check
passes for every profile.

---

## 38. Context window analytics

**Goal** — A per-conversation view of the model's context window that reads like the cost
view. It shows how full the window is now and against which limit, what fills it, and for
every turn how much was added and how much compaction or the context guard took back out.
The question it answers — why did this chat get refused, summarized or slow — is then
answered from the conversation itself, not from logs.

**Why it fits** — On a local model, context is the scarce resource, more than money, which a
local model does not spend; a 32K–190K window is this fork's everyday constraint. The fork
measures it today, but only now and only half. The header badge
(`app/gateway/context_usage.py`) counts the checkpoint's messages with LangChain's
approximate counter and divides by the configured `context_window`. That leaves out the
fixed part of every request — system prompt plus tool schemas, 7K–22K tokens per FORK.md
§47 — and divides by the whole window, though `num_predict` is reserved for the reply and
the guard fills only 90% of the rest. A chat the guard is about to refuse can read 40% in the
header. Tuning a window (`ollama.vram_gb`, `kv_cache_type`, the model choice) has no
feedback loop beyond the picker's label. The cost view already has the shape this needs:
`ThreadTokenUsageResponse.steps` gives one point per user turn, per run, with superseded runs
accounted for (FORK.md §17).

**Depends on** — nothing. It reuses the per-turn steps of the token-usage endpoint (§17),
durable run events (§28) and the guard's own estimator (`estimate_request_tokens`, §45 and
§47).

**Scope**

- **One measure: the guard's.** A model call's context is what the context guard measured for
  that call — the fixed part (system prompt plus tool schemas in the form actually sent, full
  or short), the conversation, the total, and the limit it enforced (prompt space ×
  `REQUEST_FIT_SHARE`). Where the provider reports input tokens (`usage_metadata`), record
  them beside the estimate, not instead of it: providers are not uniform about cached
  prefixes, so a provider count alone can read lower than what the window holds. Every chart
  says which number it shows.
- **Numbers, never content.** The guard and the summarization middleware emit one small
  structured record per model call into the run's events: token counts, the limit, and what
  was elided or compacted (messages and tokens, before and after). Never message text. With
  `run_events.backend: db` the history survives a restart, like scroll-back (§28).
- **Per turn, like the cost steps.** For each step: context at the turn's first model call, at
  its peak and at its end; tokens added (the user message, tool results, the answer) and
  removed (compaction, the guard eliding old tool results, `/compact`), with the turn that
  triggered a compaction marked. Subagent calls are listed under their step but kept apart
  from the lead's window, since each runs in its own.
- **A truthful badge.** The header percentage becomes the last call's total against the
  guard's limit, not the raw window, and its hover says what it counts. A thread without
  recorded calls (older threads, a run that failed before its first model call) keeps
  today's estimate, labelled as one.
- **The panel.** Clicking the badge opens a panel beside the cost overview:
  - a per-turn chart of context size, with compaction drops marked;
  - a composition bar for now — fixed, summary, user, assistant, tool results, attachments;
  - the next compaction trigger and the guard's limit, drawn as lines;
  - which model's window the chart is measured against. A model switch mid-thread changes
    the limit, and the chart shows the change rather than averaging it away.
- **One read per header render.** Extend `ThreadTokenUsageResponse.context_usage` with the
  per-step series, or add a sibling `GET /api/threads/{id}/context-usage` with the same owner
  scoping and the same handling of superseded runs as the cost steps.

**Key files** — `backend/app/gateway/context_usage.py`,
`backend/app/gateway/routers/thread_runs.py` (`ThreadContextUsage`, `ThreadTokenUsageStep`),
`backend/packages/harness/deerflow/agents/middlewares/context_window_guard_middleware.py`,
`backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py`,
`backend/packages/harness/deerflow/utils/context_budget.py`,
`frontend/src/components/workspace/context-usage-badge.tsx`,
`frontend/src/components/workspace/token-usage-indicator.tsx`,
`frontend/src/core/threads/token-usage.ts`.

**Done when**

- The badge's number equals the guard's own total for the last call, against the guard's
  limit; a test drives one request through the guard and compares the two.
- A thread's per-turn series shows the tokens added and removed by every turn, including
  each compaction and elision it went through.
- The series survives a Gateway restart on the database event store.
- No message text is stored for it.
- An older thread without records still shows today's estimate, labelled as one.
- The critical context-fit check is unchanged.

---

## 40. One model plane for the companion apps

**Goal** — newsdesk and FrontalRobotomy call a model by the name this fork already
resolved. The transport, the key and the Grok sign-in stay here. Neither app keeps a
second client or a second grant.

**Why it fits** — The fork's thesis is one personal AI, cheap because the local models
are local and the paid keys are few. newsdesk already *reads* the published
`config.example.yaml` and then reimplements every transport, and it signs in to Grok
again. FrontalRobotomy talks only to Ollama. A model added here, a Responses-only Grok
model, or a lapsed sign-in shows up in one app and not the others. The detail, including
the transports and the call shape, is [docs/companion-apps.md](docs/companion-apps.md).

**Depends on** — nothing shipped here. newsdesk's own catalog and subscription code is
the behaviour being replaced, not a dependency. FrontalRobotomy's orchestrator (its
roadmap item 12) is not required; when it is built it should call this, not grow a client.

**Scope**

- A loopback-only Gateway endpoint. The caller sends a model **name** from the resolved
  list, messages, and optionally tools. The Gateway picks the transport from the model
  entry, the way `deerflow/models/factory.py` already does: chat completions,
  `use_responses_api` for GPT-6, Anthropic, Gemini's native SDK, `ChatOllama` with the
  synced `num_ctx`, and the ChatGPT / Grok / Kimi subscription classes, including a Grok
  model that only answers on xAI's Responses API.
- The caller does not send a `base_url`, a key, or a token. An unknown name is a 404,
  not a request to a URL the caller chose. Provider addresses stay pinned in this fork.
- Streaming, and vision for the models that already declare `supports_vision`. Prices
  come back with the model so newsdesk's spend caps still mean something. newsdesk keeps
  its own budgets, fallbacks, role assignment and schema check; those are its policy.
- One Grok sign-in: this fork's Settings page. newsdesk's pasted provider keys and its
  own subscription sign-in come out only after a call through this endpoint works for
  the jobs that use them today, including a scheduled run. Don't delete the second grant
  in the same change that adds the endpoint.
- FrontalRobotomy's scorer and teacher may use the endpoint. Its training does not: a
  LoRA run is not a chat completion. Its later orchestrator (its item 12) names a model
  from this list.
- Do not mount `config.yaml` into the other containers.

**Key files** — `backend/packages/harness/deerflow/models/factory.py`,
`backend/packages/harness/deerflow/models/subscriptions.py`,
`backend/packages/harness/deerflow/models/subscription_providers.py`,
`backend/app/gateway/routers/models.py`, the nginx configs under `docker/nginx/`.
In StocktonRich: `newsdesk/llm/router.py`, `catalog.py`, `subscriptions.py`,
`ollama.py`, `openai_compat.py`, `responses.py`, `claude.py`. In FrontalRobotomy:
`frontalrobotomy/ollama/client.py`, and its roadmap item 12 when that is written.
The contract: [docs/companion-apps.md](docs/companion-apps.md).

**Done when**

- A newsdesk job and a FrontalRobotomy scoring run can both name `grok-…` on the
  connected Grok plan, an `use_responses_api` model, and an Ollama model, and the
  tokens never leave this fork's store. A test proves the caller cannot choose the
  address.
- newsdesk no longer fetches `config.example.yaml` to discover models, and no longer
  offers a second Grok sign-in. Its model audit's "port the client" step is deleted
  in the same change, because there is nothing left to port.
- A scheduled newsdesk run still answers if this fork's Gateway is up, and skips with
  the reason it skips today if the PC is off.
- No new key, token or provider URL is written into StocktonRich or FrontalRobotomy
  state, logs or diagnostics.

---

## 41. Companion apps on the welcome screen

**Goal** — An empty chat offers Stockton and Frontal Robotomy. They open already
wearing this fork's light or dark theme. The marketing landing page does not change.

**Why it fits** — The two apps are how this deployment handles news and training, and
today they are two more bookmarks on the tailnet. The welcome screen is the splash a
person actually lands on (`/workspace/chats/new`). The page at `/` is upstream's
landing and it is forced dark, so a launcher there cannot follow the theme and will
conflict on every sync.

**Depends on** — item 40 for the apps being worth opening as part of this one. The
buttons may be built against configured URLs before 40 lands, but they are not done
while each app still asks for its own Grok login. The look is specified in
[docs/companion-apps.md](docs/companion-apps.md); apply it, don't redesign it.

**Scope**

- Two buttons in `Welcome`, under the greeting: **Stockton** and **Frontal Robotomy**.
  Hidden when the URL is not configured. They open a new tab. On a 390px width they
  wrap with the greeting and do not cover the input.
- Serve them on this origin, proxied at `/apps/newsdesk/` and `/apps/frontal/`,
  loopback only. Forward newsdesk's `Tailscale-User-Login` header; do not disable
  that check. Do not publish FrontalRobotomy's `8742`. insider is not a third button
  and not a third proxy; it stays where newsdesk already links it.
- The URLs are operator config in `config.yaml`. Empty is the default.
- Theme: a `deerflow-theme` cookie of `light`, `dark` or `system`, written by the
  existing appearance control and by these buttons. `system` follows
  `prefers-color-scheme`; an explicit choice wins over the operating system. Both
  satellites read it and grow a control that writes it back. Tokens, radius, the
  indigo accent that goes away, and the chart colours that stay are in the doc.
  Do not import this fork's CSS into those apps.
- Not on `frontend/src/app/page.tsx`.

**Key files** — `frontend/src/components/workspace/welcome.tsx`,
`frontend/src/components/workspace/chats/chat-instance.tsx`,
`frontend/src/components/theme-provider.tsx`,
`frontend/src/components/workspace/settings/appearance-settings-page.tsx`,
`frontend/src/styles/globals.css`, `docker/nginx/nginx.conf`,
`docker/nginx/nginx.local.conf`. In StocktonRich: `newsdesk/web/static/app.css`
and `newsdesk/web/templates/base.html`. In FrontalRobotomy:
`frontalrobotomy/app/static/style.css` and the page headers. The spec:
[docs/companion-apps.md](docs/companion-apps.md).

**Done when**

- A fresh chat shows both buttons when the URLs are set, and neither when they are
  not. The marketing page at `/` is unchanged and still forced dark.
- Opening Stockton does not ask for a login this fork has already satisfied, and
  does not drop the Tailscale identity check.
- Switching to light here and opening either app shows the light tokens from the
  doc; switching to dark shows the dark ones; `system` follows the operating system.
  A contrast check of newsdesk's existing status and chart colours on the new
  backgrounds is recorded, and the colours are not replaced by `--chart-*`.
- At 390px the buttons wrap and the input is still usable. Item 18's layout is
  not regressed.
- No satellite port is bound on anything but loopback.

---

## 42. One card, one turn

**Goal** — Ollama and training stay on the daily PC (i9-12900K, 64 GB RAM, RTX
3090). The home server only serves the pages. A training run and a chat take turns
on that one card, instead of both grabbing it.

**Why it fits** — The card is the scarce thing, and three locks already miss each
other: newsdesk's flock lives on the server's disk, this fork's arbiter only sees a
GPU attached to the Gateway, and FrontalRobotomy's lock only covers its own jobs.
Training runs in Docker on the PC for hours. A server-side lock cannot see it. The
layout and the three locks are drawn in
[docs/companion-apps.md](docs/companion-apps.md).

**Depends on** — nothing. It is more urgent once item 41 makes training easy to
start, so do it before that night. It does not depend on item 40.

**Scope**

- One lock on the PC, taken before any Ollama call from this fork, newsdesk, insider
  or FrontalRobotomy, and before a training or conversion container starts. Training
  takes it before it unloads Ollama. The kernel releases it if the holder dies.
- A waiter says it is waiting. It does not start a second copy of the model, and it
  does not kill a training run to answer a chat.
- `OLLAMA_NUM_PARALLEL` stays 1. Confirm the 24 GiB budget is set (`ollama.vram_gb`
  or Settings → Models → *Local GPU memory*); a remote daemon is not measured, so an
  unset budget silently flattens every window to the clamp.
- ComfyUI counts as a holder only if it is running on that card. Don't leave it on
  the home server and expect it to draw.
- vast.ai does not take this lock, and neither does an API call. FrontalRobotomy's
  roadmap item 13 stays the rented-GPU plan; don't build another one here.
- Do not move the trainer into the Gateway. The *Deliberately not* entry on
  fine-tuning still holds.

**Key files** — `backend/packages/harness/deerflow/community/comfyui/arbiter.py`,
`backend/packages/harness/deerflow/subagents/local_residency.py`,
`scripts/sync-ollama-models.py`. In StocktonRich: `newsdesk/engine/gpu.py`,
insider's matching gate, `ollama.gpu_lock_file`. In FrontalRobotomy:
`frontalrobotomy/gpu.py`, `frontalrobotomy/train/remote.py`.

**Done when**

- With a training container running on the PC, a chat and a newsdesk run wait, say
  so, and proceed when the container exits — including when it is killed. A test
  stands in for the lock; the real card is the acceptance check, named as such.
- Two of those callers cannot hold the lock at once. A dead holder does not leave
  it taken.
- No code path unloads Ollama in order to jump the queue.
- The home server still has no published port except the ones Tailscale Serve
  already fronts, and the 3090 is still the only GPU any of this uses.

---

## 45. A CAD skill

**Goal** — A request for a part follows the same short procedure on every model: ask for
what is missing, write the numbers down, write the script, call the tool, read the numbers
back, repair, hand over the files.

**Why it fits** — The tool can build and measure. It cannot decide what to build, and a
model left alone presents its first attempt. A skill is where this fork keeps a procedure;
it is listed by name on a local model, so it costs the window nothing until it is used; and
it is read with the file tools, so it needs no shell.

**Depends on** — nothing open. The module shipped (FORK.md §51,
`examples/deerflow-extension-cad`); its allow-list is data, one summary and one example
per method in `allowlist.py`, which is what `references/` is generated from. The tool
takes `name`, `script`, `bbox_xyz_mm`, and optionally `volume_min_max_mm3` and
`hole_diameters_mm` (one diameter per expected hole).

**Scope**

- `skills/public/cad-modeling/`: `SKILL.md` and `references/`. No scripts.
- The procedure: at most three questions when a dimension is missing; millimetres; every
  dimension a named variable at the top of the script; the expected numbers passed to
  `cad_build` with the script; at most three repair rounds unless the user raises it; a
  failed part is reported as failed with its numbers, never presented; assumptions stated.
- `references/` holds the allow-listed operations with one example each, and the common
  failures with their fixes. It is generated from the module's allow-list, and a test
  fails when the two differ.
- Without `cad_build` in the tool list, the skill says the CAD module is not installed and
  stops. It does not imitate the tool.
- With item 50 present, it names the container route for parts the allow-list refuses.

**Key files** — `skills/public/cad-modeling/` (new), `tests/skills/` (the offline test
that the reference matches the allow-list), `skills/AGENTS.md` (one sentence, if a skill
that depends on an extension's tool needs a rule).

**Done when** — a plate with holes, an L-bracket and an enclosure with a lid each pass on
one cloud model and on one local model at a 32K window; a conversation without the module
ends with the install instruction and no invented geometry; and the reference cannot drift
from the allow-list without a red test.

---

## 46. 3D files open in the artifact panel

**Goal** — Selecting `part.glb` or `part.stl` in the artifact panel, the reader or the
Files view shows a model that can be rotated, on the desktop and on a phone. The original
file still downloads unchanged.

**Why it fits** — The `artifactPreviews` contract exists for exactly this, and the Office
preview is the worked example: a packaged, operator-installed browser contribution, files
read through the authenticated artifact route, no public viewer service. It runs in the
user's own browser, so the WebGL failures that desktop webviews have on Linux with NVIDIA
cards do not arise.

**Depends on** — nothing in code. The CAD module (FORK.md §51) already produces the files.

**Scope**

- A second packaged extension, `examples/deerflow-extension-cad-preview/`, modelled on
  `examples/deerflow-extension-office-preview/`. It registers `glb` and `stl` first. It is
  separate from the CAD module's package so that viewing a model does not require the
  kernel.
- The renderer and its parsers ship inside the trusted package and are served by content
  hash. Parsing runs in a Worker with a deadline, as the Office preview does.
- Limits stated in the README and enforced: the host's 25 MiB read cap, a triangle cap,
  and the download fallback with a reason when either is exceeded.
- Orbit, fit to view, bounding-box dimensions on screen, light and dark themes. No
  automatic rotation, since reduced motion is this fork's default.
- `dispose()` releases the WebGL context; opening twenty files in a row must not exhaust
  contexts.
- A second step adds `step` and `stp` through an OpenCascade WebAssembly reader in the
  same Worker, under the same limits. Until then the GLB is the preview and the STEP is
  the download.
- Off until an operator installs it, like every extension. Third-party notices included.

**Key files** — `examples/deerflow-extension-cad-preview/` (new, the Office preview's
layout: `ui/`, the Python package with `ui_manifest.json` and `deerflow-extension.json`,
`tests/test_registration.py`), `scripts/check_extension.py`, `examples/README.md`,
`frontend/tests/e2e/` (a GLB fixture, following the Office fixtures).
`docs/full-stack-plugins.md` should not need to change; if it does, the contract was the
wrong shape and that is its own change.

**Done when** — the GLB and STL from the CAD module, and a `part.failed.glb`, render in the panel
and the reader at desktop width and at 390px; an oversize file falls back to download and
says why; twenty consecutive previews leave no leaked context; the E2E spec is green; and
with the extension removed the files behave exactly as they do today.

---

## 47. Geometry decides a delegated part

**Goal** — When the lead hands a part to a `task` subagent, in Ultra or in a Plus
Ultracode workflow, the part passes or fails on measured numbers. The subagent's own
summary is not evidence.

**Why it fits** — `acceptance_checks.py` already decides lead-supplied criteria in code on
the `task` tool's completed branch. The CAD module writes `part.step` only for a part that
passed its checks, so the file leaf that exists today is enough, and it needs no shell.

**Depends on** — nothing open. The CAD module shipped (FORK.md §51).

**Scope**

- The lead's criteria name the STEP file with the existing file leaf. Confirm the leaf's
  path form for the outputs directory in `ACCEPTANCE_CHECKS.md` before writing the skill
  text.
- No new leaf and no CAD-specific code in core. If the file leaf proves too weak, the
  addition is a generic leaf that reads a JSON report, usable by any tool.
- A short recipe for Plus Ultracode in the skill's references: several candidate scripts
  from child agents, each built and measured, a second agent checking the findings, the
  first passing candidate returned. Local dispatch already runs children one at a time
  when the card holds one model.
- Repair rounds count against the existing run limits and the spend cap. No new limit.

**Key files** —
`backend/packages/harness/deerflow/subagents/acceptance_checks.py` and
`ACCEPTANCE_CHECKS.md` beside it (read; edit only for a generic leaf),
`skills/public/cad-modeling/references/`.

**Done when** — a subagent whose part fails produces a failed checklist that the lead sees
and acts on; a passing part passes; and a search of `backend/packages/harness/` finds
nothing specific to CAD.

---

## 48. A CAD eval

**Goal** — One command scores any configured model on a fixed set of part specs and prints
pass rate, repair rounds, tokens, cost, and the operations the model asked for that the
allow-list refused.

**Why it fits** — The thesis is local models worth preferring rather than tolerating, and
for CAD nobody knows which ones are until it is measured. `make drift-eval` is the
precedent: opt-in, out of CI, end to end through the running agent. Unlike drift it needs
no judge model, because the checks are numbers. The refused-operation count is what tells
the CAD module which method to add next, and item 50 whether it is needed at all.

**Depends on** — 45, on top of the CAD module (FORK.md §51). It does not wait for item 25,
but belongs in that suite once
it exists.

**Scope**

- Fifteen to twenty specs in three bands: prismatic parts; holes, patterns and pockets;
  fillets, shells and two-part fits. Each has the request text and the expected numbers.
- Runs against the running agent on the default sandbox, per model, under the run limits
  and spend cap already configured, and reports the spend.
- A dated results table in the docs. The table is evidence, so a row carries the model,
  its quantisation and window, the module version and the skill version.
- Out of CI. Re-run after any change to the allow-list or the skill.

**Key files** — a runner under `scripts/` and its `Makefile` target, following the layout
`drift-eval` uses; fixtures beside it; a results page under `docs/`.

**Done when** — the table has at least one local model and one subscription model; two
runs of the same model agree within a stated tolerance; and the command refuses to start
when the CAD module is not installed.

---

## 49. Ollama models from Settings

**Goal** — A local model is found, sized against the card, pulled and deleted from
Settings → Models. It appears in the picker with its window sized, without a terminal.

**Why it fits** — The README's promise is that the model list follows `ollama pull`.
Acquiring the model is the half still done by hand. Item 16 set the rule for downloads in
this fork: limits an operator sets, not limits the agent chooses. The download itself is
done by the Ollama daemon through its own API, on whichever machine runs it, so the
Gateway never writes weights to disk.

**Depends on** — nothing shipped. It reuses the VRAM sizing behind `ollama.vram_gb`.

**Scope**

- Admin-only. Pull with streamed progress, cancel, delete.
- A fit indicator before the download: fits, tight, or too large for the configured card,
  from the same sizing the sync uses.
- Finding a model: a short curated list committed in the repo (name, size, tool calling,
  vision, window), plus pulling by exact name. No scraping of the Ollama website; Ollama
  documents no library-search endpoint.
- A size cap and the registry host are operator config, in `config.yaml`, not in anything
  the API can write.
- After a pull, run the existing sync so the new entry gets its `num_ctx`.
- Not an agent tool. A model in a conversation cannot start a download.
- It does not touch ComfyUI checkpoints; item 16 owns those.

**Key files** — `scripts/sync-ollama-models.py`,
`backend/app/gateway/routers/models.py`,
`frontend/src/components/workspace/settings/model-settings-page.tsx`, the `ollama:` block
of `config.example.yaml`, `SECURITY.md`.

**Done when** — a model over the cap and a name outside the registry are each refused with
the reason; a permitted pull shows progress, survives a page reload and ends with the
model selectable and sized; a non-admin cannot start one; and the context-fit critical
check passes for the newly synced entry.

---

## 50. Full scripts where a container exists

**Goal** — With the container sandbox configured, a part the allow-list cannot express is
built from an unrestricted build123d or CadQuery script run inside the conversation's
container, and judged by the same checks.

**Why it fits** — The allow-list is a floor, not a ceiling. Lofts, sweeps along curves,
text and anything that needs a loop are refused by the CAD module, correctly. The container is
the place this fork already has for code a model wrote, and the best public results for
CAD by agents come from full scripts inside a measuring loop.

**Depends on** — 45, the CAD module (FORK.md §51), and the container sandbox (`AioSandboxProvider`, local
container mode). It adds nothing to the default install.

**Scope**

- An image layer under `docker/`, built from the supported AIO image line, with pinned
  build123d and CadQuery, and a make target beside the `sandbox-*` targets that builds it
  and writes the sandbox `image:` value. Nothing is installed at run time, so an offline
  conversation still builds.
- The CAD module's checker (`measure.py`) packaged as a command inside that image, so a
  script's STEP is
  measured by the same code and reported in the same format. One checker, two entry
  points.
- The skill chooses: `cad_build` first; the container only when the tool refused a
  construct and a container is configured. It never asks the user to enable host bash.
- An optional image variant with FreeCAD, for a native `.FCStd` with a feature tree beside
  the STEP: FreeCAD Python run with `freecadcmd`, headless, judged on its exported STEP.
- No `--gpus`, no extra capability, no published port.

**Key files** — `docker/` (the image layer), `Makefile` (`sandbox-*` targets),
`examples/deerflow-extension-cad/` (the shared checker), `skills/public/cad-modeling/`,
`backend/docs/CONFIGURATION.md`.

**Done when** — a lofted part that `cad_build` refuses is built in the container and
passes the same report; the same conversation on the default sandbox ends with the refusal
and its reason, not an attempt; and the FreeCAD variant, when present, produces a file
whose sketch and pad are editable in FreeCAD.

---

## Deliberately not on this roadmap

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
reached the way any other model provider is. Items 40–42 do not reverse this.
FrontalRobotomy keeps the trainer, on the daily PC; this fork launches it, lends it the
model list, and takes a turn on the card. The trainer does not move into the Gateway.

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
different feature from the push-to-talk Grok voice tier (FORK.md §43): it needs a WebSocket audio path
through nginx, holds the microphone open for the whole session, and sends all of it to
xAI. Item 19's push-to-talk, local-first voice is the one this fork wants; a realtime cloud
agent would make the opposite the default.

**Raising the context clamp until the book fits.** `scripts/sync-ollama-models.py` clamps
`num_ctx` at 32,768 so a 128K-native model does not allocate a KV cache the GPU cannot hold
(FORK.md §1). No local window holds a 539K-token cookbook anyway, and Chroma's *Context Rot*
found reliability falling with input length even inside the window. A bigger window moves
the cliff; the reading in parts that FORK.md §45 extended, and item 35, remove the need to
stand at it.

**A downloadable desktop app.** An installer for Windows, macOS and Linux was the first
shape of the CAD idea behind items 43–50. This fork is a server reached from a browser,
the Script workflows extension does not run on a Windows Gateway, and packaging a geometry
kernel for three systems is a project of its own. The items give up the installer and keep
everything else.

**A CAD tool that executes what the model wrote.** On the default sandbox the shortcut is
obvious: `exec` the script in the Gateway with a trimmed set of builtins. A trimmed `exec`
is not a boundary, and the default sandbox has no shell because `LocalSandboxProvider` is
not an isolation boundary either. Item 44 interprets an allow-list instead, and item 50
runs real scripts where a container exists. There is no third route; a Gateway-side MCP
server that runs scripts is the same shortcut under another name.

**A CAD model trained here.** Tuning a small model on CAD code is plausible on one 24 GB
card, and it is still training. It stays with FrontalRobotomy under the fine-tuning entry
above. Item 48's eval and the passed parts from item 44 are what this fork can hand it.

**Driving a desktop CAD program.** SolidWorks, or any other program operated through its
window, is the computer-use surface this file already declines.

**OpenSCAD.** Models write it easily and it rebuilds quickly, but it has no true fillets or
chamfers, exports meshes rather than STEP by default, and fails silently where CadQuery
fails loudly. If it is ever wanted it is one more input format for item 44, argued on its
own.
