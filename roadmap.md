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

Items **43–51** came from wanting mechanical parts out of the same chat: describe a
bracket, get a script that can be edited, a STEP file for a CAD program and an STL for the
printer, on whichever model the conversation already uses. Item 49 is the exception: it is
not CAD, and it sits among them only because of when it was written. A separate desktop app
was planned first and dropped, because the models, the three subscription sign-ins, the
agent loop and the artifact panel already live here. The constraint that shapes every CAD
item is the default install: `LocalSandboxProvider` with `allow_host_bash: false` gives the
agent no shell, so "write a script and run it" is not available where most people start.
The CAD module therefore builds a part **without running what the model wrote**, as an
installed extension, and the files it writes are ordinary outputs that the Files view
lists. Item **43** — a plugin tool can write a bounded, host-checked file into the outputs
of the conversation that called it (`ToolContext.write_output`, extension API 0.2.13) —
landed: see [FORK.md §50](./FORK.md). Item **44** — the CAD module itself, a bundled
extension whose `cad_build` tool reads a CadQuery script, performs an allow-list of
operations in a child process and hands over STEP, STL and GLB only for a part that
measured right — landed: see [FORK.md §51](./FORK.md). Both numbers stay retired like
12–15.

Items **53–59** came from a review of the open CAD items on 2026-11-21, against the code
and against published results for CAD agents. The figures it measured itself were taken in
the kernel or in the context-fit harness; the published ones name their source. The review
found premises that no longer held. Item 50's reason for a container had gone stale,
because loops had landed and most of what it listed needs no container. The description
budget was quoted from an old measurement. Item 46's STEP step cannot fit the asset cap,
item 47's file evidence can be written by the subagent it judges, and 45's done-when graded
the model on its own numbers. Items 46, 47, 48, 50 and 51 were rewritten, and the ideas the
review declined are under *Deliberately not*. Item **45** — the CAD skill, proven on real
models — was merged rather than shipped: its live proof is item 48's first run, scored on
ground truth, and its skill revision is item 58. Its number stays retired like 12–15.

Every CAD item states what it costs per request, against two rules that no item loosens.
`cad_build` may cost at most 150 tokens of every request
(`test_the_bundled_cad_tool_stays_cheap_on_every_request`), and every composer mode must
fit `FIXED_REQUEST_ALLOWANCE_TOKENS` on a 32K window (`test_context_fit_critical.py`). The
per-tool cap is the one that binds. A count of spare tokens goes stale with the next prompt
change, so the items cite the rule and date their measurements.

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
- **46. GLB and STL rotate in the artifact panel** — a bundled three.js viewer, on by
  default like CAD, motion-free and usable on a phone; the STEP stays a download.
- **47. A delegated part is judged by its build result** — a generic acceptance leaf reads
  the subagent's newest `cad_build` answer; files the subagent could write are not evidence.
- **48. A CAD eval graded on ground truth** — one opt-in command re-measures every delivered
  STEP against truth the model never saw, seeded from CadQueryEval.
- **49. Ollama models from Settings** — find, size against the card, pull and delete
  without a terminal; the daemon downloads, under operator limits.
- **50. Full scripts where a container exists** — gated on item 48: only what the reader
  can never accept, built in the container and judged on the host.
- **51. A part made of several bodies** — print-in-place passes as N bodies with its
  smallest gap reported, and a kit also arrives laid out for printing.
- **52. Memory that helps a coding agent** — repository-scoped facts, build/test
  procedures, a search over past conversations, and project memory the agent can write.
- **53. See the part** — a PNG of every build that made geometry, inline in the reply and
  viewable once by a vision model.
- **54. Ready to print** — a 3MF, a GLB at real size, and print notes from the operator's
  printer profile; pass or fail never changes.
- **55. Scripts the way models write them** — tuple assignment, `math`, indexing and
  comprehensions are read rather than refused, and the description's opening gets cheaper.
- **56. Operations that need no new trust** — revolve, loft, sweep, angled workplanes and
  outline arcs on the default install.
- **57. Where the features are** — hole positions and axes, corners, fillet reach and
  report provenance, with the checks in a module that has no host imports.
- **58. Design for the printer** — an FDM and hardware reference, picture-first drafts and
  a fit-test coupon.
- **59. Lettering and threads** — `text()` with a bundled font and helix threads, as one
  reviewed widening of two SECURITY.md invariants.

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

**Suggested order for CAD.** 55, 56, 57, 53, 54, 51, 59, 58, 48, 47, 46, then 50 once its
gate is met. 55 first: it turns refusals that cost attempts today into accepted arithmetic,
and its shorter opening sentence pays for 51's parameter. 56 and 57 build on its reader and
its report fields, and 57 moves the checks into a module without host imports, which 48 and
50 reuse. 53 and 54 are what a user sees and prints, and 54's GLB scale is what 46's viewer
reads. 51 needs 55's tokens, 57's checks and 54's printer profile. 59 follows 56 as its own
reviewed commit, because it widens two SECURITY.md invariants. 58 teaches what 53, 54 and
57 settle. 48 then measures the result, and again after every change to the allow-list or
the skill. 47 before CAD is used in Ultra, where subagents report on their own work. 46
after 54. 50 only if 48 shows that the reader, and not the model, is what stops real parts.

**49** is not CAD and is independent of all of the above; it can start any time.

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

Follow change_cycle.md for the change itself; where this block and that file differ, that
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

## 46. GLB and STL rotate in the artifact panel

**Goal** — Selecting a `.glb`, `.stl` or `.failed.glb` in the artifact panel, the reader or
the Files view shows a model that can be rotated, with no motion of its own and with its
bounding box in millimetres, at desktop and at phone width. The original file still
downloads unchanged.

**Why it fits** — The `artifactPreviews` contract exists for this, and the Office preview
is the worked example of its layout: a packaged browser contribution, files read through
the authenticated artifact route, no public viewer service. It runs in the user's own
browser, so the WebGL failures that desktop webviews have on Linux with NVIDIA cards do not
arise. Item 53's picture covers the first look; this item adds rotation.

The viewer ships bundled and on, like CAD itself. A viewer that stays off until an operator
installs it leaves every default CAD user with GLB and STL files they can only download.
The parsers check every count before they allocate, run in a Worker that is terminated
after each file, and are tested against hostile files, which contains the attack surface;
`make extension-disable NAME=cad-preview` still turns it off.

The library was chosen by measurement. three.js core is 565 KB minified (140 KB gzip),
against 1.54 MB for Babylon. model-viewer has no STL loader and pulls its decoders from a
CDN, and Online3DViewer fetches its parts from jsdelivr at run time. WebGL2 works in
headless Chromium through SwiftShader, so the E2E spec can draw, and losing each mount's
context on dispose keeps twenty file switches within the browser's context limit. The STEP
step this item used to plan is dropped (see *Deliberately not*). The contract needs three
things written down that it does not state today: a named oversize error, the theme tokens
a preview inherits, and the rules for Workers in the opaque origin.

**Depends on** — 54, for the GLB's metre scale; until it lands, the viewer is developed
against a hand-scaled fixture. The CAD module (FORK.md §51) already writes the files.

**Scope**

- A new packaged extension, `examples/deerflow-extension-cad-preview/`, in the Office
  preview's layout: three 0.187.0 pinned exactly with a `package-lock.json` and
  `npm ci --ignore-scripts`, esbuild 0.25.12, `build.mjs`, `notices.mjs`,
  `THIRD_PARTY_NOTICES.md`, `README.md` and `AGENTS.md`; a `pyproject.toml` (MIT,
  `deerflow-extension-api>=0.2.3,<0.3`, uv cache keys); and `deerflow_extension_cad_preview/`
  with `BrowserAssets(module="cad-preview")`, `deerflow-extension.json` (en-US, zh-CN), a
  generated `ui_manifest.json` and a committed `static/dist`. It is separate from the CAD
  module's package, so that viewing a model does not need the kernel.
- `ui/model-worker.js`: one self-contained module Worker per file, with a 15 s deadline,
  terminated on abort or dispose. It receives its own copy of the bytes and returns fixed
  diagnostic codes.
  - `stl.js` reads a file as binary when 84 + 50n equals its byte length, even when the
    header starts with `solid`, and otherwise runs a bounded ASCII reader. NaN and Inf are
    refused.
  - `glb.js` accepts a strict glTF 2.0 subset: header, chunk and alignment checks; a JSON
    chunk of at most 4 MiB; no `extensionsRequired` and no `uri` buffers; TRIANGLES only;
    accessor and bufferView bounds; every index below the vertex count; node TRS with cycle
    detection and a depth of at most 64.
  - Counts are summed before anything is allocated, against caps of 1M triangles, 1M
    vertices and 20k primitives and nodes. The output is merged into one draw call, with
    per-node group ranges kept for 51's bodies. Feature edges are computed in the Worker
    and hidden above about 600k triangles.
- `ui/viewer.js`:
  - a transparent canvas over `var(--background)`, with the edge colour resolved from
    `--foreground` through a 1×1 canvas and resolved again when the class, the style or
    `prefers-color-scheme` changes;
  - OrbitControls with no damping and no autoRotate, rendered on demand only;
  - Fit, Reset and Top/Front/Iso buttons, keyboard orbit through `listenToKeyEvents`, and a
    pixel ratio of at most 2;
  - a `role="status"` overlay, "Bounding box X × Y × Z mm (from the mesh)", in the CAD
    Z-up frame: a GLB is read as metres (after 54), an STL as millimetres rotated −90°
    about X;
  - a banner on `*.failed.glb` that points to the report;
  - the camera and the edges toggle saved through `saveReadingState`.

  `dispose()` is idempotent and runs in this order: the animation frame, observers,
  controls, geometries and materials, render lists, `renderer.dispose()`,
  `forceContextLoss()`, the canvas sized to zero and removed, the Worker terminated, Blob
  URLs revoked. A mount that was already aborted creates no context, `webglcontextlost`
  shows "Display lost – Reload", and a renderer failure calls `onError()`.
- One generic host change. `frontend/src/core/artifacts/binary-preview.ts` throws a named
  `PreviewTooLargeError`, and `MountedPreview` says "larger than the 25 MiB preview limit"
  (en-US, zh-CN). `docs/full-stack-plugins.md` documents that error, the theme tokens a
  preview inherits, that a Worker in the opaque origin can neither import nor fetch, and
  the same-origin rule for `new Worker(url)`.
- Bundled and on, like CAD: a snapshot under
  `backend/extensions/sources/deerflow-extension-cad-preview/`; an extensions-group entry
  and a `[tool.uv.sources]` path without a platform marker in `backend/pyproject.toml`, and
  `uv.lock`; an enabled record in `config.example.yaml` and a `config_upgrade` migration
  that appends it; `backend/tests/test_bundled_cad_preview_extension.py`; the frontend
  `catalog.ts`, i18n, and `bundled-documentation.json` through
  `scripts/sync_extension_documentation.py`; and the package in the `e2e-tests.yml` paths.
  Existing installs get the viewer through the migration on their next upgrade, and the
  FORK.md and README notes tell anyone who scaled the old millimetre GLB by hand that it is
  now in metres.
- Docs: `docs/guide/file-previews.md`, `examples/README.md`, a FORK.md section and a README
  bullet; in `docs/repo-map/`, the artifacts row's files and tests in
  `sidebar-and-workspace.md`, the CAD row's link in `generation-and-media.md`, and index
  rows for both package paths.

**Key files** — `examples/deerflow-extension-cad-preview/` (new),
`frontend/src/core/artifacts/binary-preview.ts`,
`frontend/src/components/workspace/artifacts/plugin-artifact-preview.tsx`
(`MountedPreview`), `frontend/src/core/i18n/locales/en-US.ts` and `zh-CN.ts`,
`frontend/src/core/extensions/catalog.ts`, `frontend/tests/e2e/cad-preview.spec.ts` with
its utils and `fixtures/cad-preview/` (new), `docs/full-stack-plugins.md`,
`docs/guide/file-previews.md`, `backend/extensions/sources/deerflow-extension-cad-preview/`
(new), `backend/pyproject.toml`, `backend/uv.lock`, `config.example.yaml` and its
`config_upgrade` migration, `backend/tests/test_bundled_cad_preview_extension.py` (new),
`.github/workflows/e2e-tests.yml`, and `docs/repo-map/` (`sidebar-and-workspace.md`,
`generation-and-media.md`, `index.md`).

**Done when**

- `node --test` covers, for STL, a binary file whose header starts with `solid`, truncated
  input and NaN values; and for GLB, a `uri` buffer, Draco in `extensionsRequired`, an
  out-of-bounds accessor, an index at or above the vertex count, cyclic nodes, and an
  indexed GLB of 3 vertices with more than 1M index triplets, which is rejected before
  anything is allocated.
- `frontend/tests/e2e/cad-preview.spec.ts` runs with `--enable-unsafe-swiftshader` on
  fixtures that a committed `generate-fixtures.py` writes in the CAD venv. A GLB, an STL
  and a failed GLB each render in the panel and in the reader at 1440 px and at 390 px: the
  canvas is visible and its centre pixel differs from the background, the overlay's bbox
  matches `report.json` within 0.1 mm, nothing overflows horizontally, and the failed
  banner shows.
- A 26 MiB file shows the 25 MiB reason and a download, and the amplifying GLB shows the
  plugin's reason and a download.
- Twenty consecutive file switches log no "Too many active WebGL contexts", and
  instrumented live contexts stay at one or fewer. No animation frame runs after a second
  idle. A theme switch updates the edge colour without a remount.
- With `/api/plugins` empty or the extension disabled, `.glb` and `.stl` files behave
  exactly as they do today.
- `test_bundled_cad_preview_extension.py`, `scripts/check_extension.py` on the package, a
  `PreviewTooLargeError` unit test, `pnpm check` and `test_repo_map.py` pass.
- The 390 px runs are emulated and the WebGL is SwiftShader; a real phone with a GPU is the
  owner's acceptance check, named as such.

---

## 47. A delegated part is judged by its build result

**Goal** — When the lead hands a part to a `task` subagent in Ultra, the acceptance
checklist passes only if that subagent's newest `cad_build` call for the part answered
`passed: true`. Files the subagent could have written are not evidence.

**Why it fits** — `acceptance_checks.py` already decides lead-supplied criteria in code on
the `task` tool's completed branch, but file evidence cannot decide a part. Subagents
inherit `write_file`, so they can forge `<name>.report.json` or a `.step`. The host names a
rebuild `<name>-K`, so a criterion written in advance cannot name the last build. And no
leaf reads a JSON field. A tool's result, on the other hand, is stamped by the host. The
executor already pairs calls with their results (`pair_tool_call_results`, which
`_harvest_bash_executions` uses) and `ToolReceiptMiddleware` stamps receipts, so a generic
leaf over tool results adds nothing CAD-specific to core.

Plus Ultracode is not part of this item. Its workflow agents run on isolated child threads,
where task acceptance checks never run; it needs merge workspaces and host evidence carried
on the workflow record, and on one local card its candidates run one at a time anyway.
Parallel subagents in Ultra share the lead's thread, and so share the CAD tool's attempt
table, which is why each needs its own part name.

**Depends on** — nothing open. The CAD module shipped (FORK.md §51).

**Scope**

- `acceptance_checks.py` gains a generic leaf,
  `tool_result:<namespace>/<tool> <field>=<json scalar> [where <arg>=<json scalar>]`.
  - The tool is resolved through `extensions.plugin_tools.plugin_tool_name`, because the
    names a model sees carry a hash suffix.
  - The newest matching call decides; an earlier pass does not save a later failure.
  - No matching call, a result that is not JSON or was truncated, or a call removed by
    compaction gives UNVERIFIED with a reason, never a pass.
- `executor.py` gains a bounded, failure-isolated harvest built on `pair_tool_call_results`,
  limited to the tool names some criterion names: the newest 20 calls, scalar arguments of
  at most 120 characters each, and top-level scalar result fields within a 64 KB parse cap.
  It feeds `tool_result`; `tests_passed` stays as it is.
- The leaf is documented in `subagents/ACCEPTANCE_CHECKS.md`, and the recipe in a new
  `skills/public/cad-modeling/references/delegation.md`: one distinct part name per
  subagent or candidate, the criterion
  `tool_result:cad/cad_build passed=true where name="bracket-a"`, Ultra only. The `task`
  tool's description does not change by a byte, so the leaf costs no tokens per request.
- Plus Ultracode stays later work, for the reasons above.

**Key files** — `backend/packages/harness/deerflow/subagents/acceptance_checks.py`,
`backend/packages/harness/deerflow/subagents/executor.py`,
`backend/packages/harness/deerflow/subagents/ACCEPTANCE_CHECKS.md`,
`backend/tests/test_acceptance_tool_result.py` (new),
`skills/public/cad-modeling/references/delegation.md` (new), and the acceptance-checks row
in `docs/repo-map/`.

**Done when**

- `backend/tests/test_acceptance_tool_result.py` shows that the leaf holds on a passed
  result; fails when the newest matching result failed after an earlier pass; does not hold
  after a `write_file` of a forged `<part>.report.json` with no passing call; is not
  satisfied by a pass for another part name under `where name=`; and is UNVERIFIED for
  non-JSON, truncated and compacted results. A harvest exception leaves the run's outcome
  unchanged, and the harvest bounds hold.
- `test_acceptance_checks.py` and `test_acceptance_evidence_reused_call_ids.py` pass.
- `grep -rniwE 'cad|cad_build|cadquery' backend/packages/harness` finds nothing new.
- The `task` tool's description is byte-identical, the context-fit check is unchanged, and
  the repo map's acceptance-checks row lists the new test.
- A live Ultra delegation on a real model is the owner's acceptance check; the offline
  tests use synthetic message streams.

---

## 48. A CAD eval graded on ground truth

**Goal** — One opt-in command scores a configured model on fixed specs by re-measuring the
STEP it delivered against ground truth the model never saw. It reports the truth pass rate
with an interval, claim precision, single-shot pass against the repair loop, refusals by
construct, builds to pass, `view_image` use, and tokens and spend.

**Why it fits** — `decide()` checks the model's own expected numbers, so `cad_build`'s
`passed` is graded by the model that wrote the part: a part can pass every check and still
be the wrong part. Claim precision — how often a part presented as finished is right — is
what a checker moves; *Done Is Not Correct* reports 64.1% single-shot against 95.5% with a
checker. CadQueryEval (MIT code, 25 tasks, about 90 published model rows) makes the results
comparable; it is saturated for frontier models but still separates local ones. One sample
of each of 20 specs has a standard error of about 11%, so every spec runs at least three
times. CADTestBench's predicates are not vendored, because its dataset licence is not
stated.

`make drift-eval` is the precedent: opt-in, out of CI, end to end through the running
agent. Unlike drift it needs no judge model, because the checks are numbers. The refusal
counts tell the CAD module which construct to admit next, and decide item 50's gate.

This item also carries 45's acceptance. Its three parts (a plate with holes, an L-bracket,
an enclosure with a lid) are specs in band 1, its record of attempts, refusals and where
the model left the procedure is part of every row, and its conversation without the module
is the module-disabled spec. The first live run is the proof 45 asked for.

**Depends on** — 57 (`measure_cli`, and the provenance and file list in `report.json`) and
56 (the operations several reference scripts need). Specs that need 51 or 59 are marked and
join when those land. It does not wait for item 25, but belongs in that suite once it
exists.

**Scope**

- A runner at `backend/scripts/benchmark/cad_eval/`: `agent.py` drives the Gateway over
  public HTTP, as `drift_eval` does; `score.py` holds the pure scoring; `derive_truth.py`
  runs once, offline, from reference STLs that are not committed; and `specs/` holds the
  fixtures. A root `Makefile` target, `cad-eval MODEL= K=3 BAND=`, with a help line. It is
  opt-in and out of CI, and it refuses to start when `/api/plugins` has no `cad` namespace.
- Specs in three bands:
  1. Home prints: a plate with holes, an L-bracket, a knob (revolve), a name tag (after
     59) and an enclosure-and-lid kit (after 51).
  2. CadQueryEval's 25 tasks: the request text with its LICENSE and attribution vendored
     (the code is MIT; the licence of the task text is confirmed before it is vendored),
     and ground truth of one component, a bbox within 1 mm (axes sorted where the task
     fixes no orientation) and a volume within 2%.
  3. Fits and print-in-place: a hinge, a captive nut, and a thread if 59 ships.

  One more spec runs with the CAD module disabled, and passes only when the conversation
  ends with the install instruction and no invented geometry.
- A spec the allow-list cannot express is marked `expected_refused: <construct>`. It is
  still scored, and it feeds item 50's gate.
- Every reachable spec ships a `reference.py` in the allow-listed dialect.
  `examples/deerflow-extension-cad/tests/test_eval_specs.py` compiles, builds, exports and
  re-measures each one against its truth, and runs in CI's extension-package-check job.
- Scoring takes the newest passed STEP named in `report.json`'s `files`, downloads it
  through the artifact route and runs `measure_cli` against the truth; `passed` is never the
  score. It reports the truth pass rate with a Wilson 95% interval over k, claim precision
  (truth passes ÷ parts presented as finished), single-shot pass (attempt 1), refusals by
  `error.refused`, builds to pass, `view_image` calls, and tokens and spend under the
  configured cap.
- Each result row carries the model, its quantisation and window, the module, cadquery and
  skill versions (57's provenance), k and a hash of the spec set, and per spec the
  attempts, the refusals and where the model left the skill's procedure. Results go into a
  dated table in `docs/guide/cad-eval.md`. Re-run after every change to the allow-list or
  the skill.

**Key files** — `backend/scripts/benchmark/cad_eval/` (new: `agent.py`, `score.py`,
`derive_truth.py`, `specs/`), `Makefile` (the `cad-eval` target),
`backend/tests/test_bench_cad_eval.py` (new),
`examples/deerflow-extension-cad/tests/test_eval_specs.py` (new), `docs/guide/cad-eval.md`
(new), and in `docs/repo-map/`, `index.md` and the CAD row's entry points and tests in
`generation-and-media.md`.

**Done when**

- Offline: `test_eval_specs.py` passes for every reachable spec.
- Offline: `backend/tests/test_bench_cad_eval.py`, with a fake Gateway in the style of the
  drift tests, shows that a self-passed part with a wrong bbox scores a truth failure, that
  refusals are counted from `error.refused`, that the Wilson interval is correct, and that
  the command refuses to start without the module.
- Offline: `make cad-eval` without `MODEL` prints its usage and exits non-zero, and
  `test_repo_map.py` passes with the new rows.
- Live, on the owner's host: one local 32K model and one cloud model at k=3, plus a
  baseline row on main's module. Two runs agree within the stated interval, and FORK.md §51
  records what the runs changed in the skill.
- The offline half can ship first. This item then keeps only its live-run half, as 34 kept
  only its unshipped half.

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

**Goal** — With the container sandbox in container mode, a part that needs what the reader
can never accept — callables, the Sketch API, or control flow that depends on a build — is
built from a full CadQuery script in the conversation's container. The CAD worker on the
host judges the STEP it wrote.

**Why it fits** — The reader is a floor, not a ceiling, and the floor has risen: loops
landed (FORK.md §51), revolve, loft and sweep come with 56, and text and threads with 59.
What remains is what an allow-list cannot read, and the best public results for CAD by
agents come from full scripts inside a measuring loop. Judging inside the container would
let the model's code patch the checker, so the judging happens on the host. That needs a
generic read hook, and FORK.md §50 made `ToolContext` write-only on purpose, so the hook
gets its own review.

Several constraints shape the rest. build123d 0.13 needs OCP 8 while CadQuery 2.8.0 needs
OCP below 8, so the image holds one line. External AIO mode surfaces no outputs (item 17).
The `sandbox-image-smoke` workflow only pulls images, so the layer needs its own build job.
Nothing of this could be built or tested where it was planned, which had no Docker daemon,
and the gate needs live data from 48.

**Depends on** — 48, whose run decides the gate, and the container sandbox
(`AioSandboxProvider`, local container mode). It adds nothing to the default install.

**Scope**

- The gate: start only when an item 48 run shows that, for some model users run, at least
  10% of specs fail on `expected_refused` constructs that 55, 56 and 59 cannot admit. The
  threshold is stated in `docs/guide/cad-eval.md`.
- A generic core hook: `ToolContext.read_output(path, max_bytes)` in extension API 0.2.14.
  It is read-only, limited to the calling thread's outputs, and refuses `..`, symlinks and
  oversize files. It has its own tests, and a FORK.md §50 amendment says why a read is now
  admitted.
- In the CAD module, `cad_check(name, step_path, bbox_xyz_mm, …)`, registered only when the
  operator sets `container_scripts: true`. It reads the STEP through `read_output` and runs
  the same worker measurement, 57's `checks.py` and `decide()`. It costs about 60–80 tokens
  per request, and only where the operator turns it on.
- An image layer under `docker/` on the pinned AIO image line, with `cadquery==2.8.0`
  only; build123d only as 0.12.x on OCP 7.9, and only if 48 asks for it. Nothing is
  installed at run time, so an offline conversation still builds. `scripts/sandbox_toggle.py`
  gains an image option that requires `MODE=container`.
- A new CI job builds and smoke-tests the layer when `docker/` paths change.
- The skill chooses `cad_build` first, and the container only when the tool refused a
  construct and `cad_check` exists. It never asks the user to enable host bash.
- No `--gpus`, no extra capability, no published port.
- SECURITY.md states that the host worker parses an untrusted STEP inside the child-process
  limits. The FreeCAD variant this item used to offer is under *Deliberately not*.

**Key files** — later: `backend/packages/extension-api/` (`read_output`),
`examples/deerflow-extension-cad/deerflow_extension_cad/` (`cad_check`), `docker/` (the
image layer), `scripts/sandbox_toggle.py`, `.github/workflows/` (the new build job),
`skills/public/cad-modeling/`, `SECURITY.md`, and FORK.md §50 and §51.

**Done when**

- A `parametricCurve` part is refused by `cad_build`, built in the container, and passes
  `cad_check` with a report in the same format.
- A report edited by hand inside the container changes nothing.
- Default installs have no `cad_check`, and the context-fit check is unchanged.
- `read_output` refuses another thread's outputs, `..`, symlinks and oversize files.
- The CI job builds the image.

---

## 51. A part made of several bodies

**Goal** — A print-in-place design (a hinge, a chain, a captive nut) passes as N bodies
with its smallest gap measured, and arrives as one printable 3MF object. A kit (a box and
its lid) is modelled assembled, checked in that pose, and also arrives as a laid-out 3MF
with one object per body.

**Why it fits** — `cad_build` passes a part only when it is exactly one solid. That is
right for a bracket and wrong for anything that moves after printing: the first real
request was a folding laptop stand with an accordion hinge. The kernel already returns
compounds, and BRepExtrema measures a 0.3 mm gap in 0.006 s.

The new key is paid on every request, so the per-tool cap decides it: `cad_build` may cost
at most 150 tokens. Measured on 2026-11-21, `bodies` takes `cad_build` from 136 tokens
(after 55) to 144; added to the description as it stands, it would make 153, which is why
55 comes first. A `min_gap_mm` parameter as well would reach 152, so the clearance comes
from 54's printer profile at no token cost. The gap is a note, not a check: pass or fail
stays on the user's numbers, and a gap of zero already fails the body count, because
touching bodies fuse.

**Depends on** — 55 (the tokens), 57 (`checks.py`) and 54 (the printer profile and the
3MF export). Loops (FORK.md §51) are what make such a script short enough to write.

**Scope**

- The schema gains `bodies` as `{"type": "integer"}`, so the test that every property is a
  bare type still holds; it is 1 by default and bounded to 1–20. It joins `EXPECTATIONS`
  and the Attempts logic that notices changed expectations.
- `decide()` in `checks.py`: for one body, "one closed solid" and every sentence stay as
  they are. For more, the check is "n valid closed solids", with the volume their sum and
  the bbox their union, which the re-import already measures.
- `measure.py`:
  - holes are measured per body, with air decided against that body alone, so a captive
    pin does not fill its bore;
  - the smallest pairwise gap (BRepExtrema after a bbox prefilter, at most 190 pairs) is
    reported with its pair and its direction;
  - notes for a gap under `printer.min_clearance_mm`, and for a vertical gap under
    `layer_mm` ("may fuse").
- Export:
  - STEP, STL and GLB hold every body in its built position, with one GLB node per body
    for 46;
  - `<stem>.3mf` keeps the kernel's one item with N components, the print-in-place layout;
  - a new `<stem>.parts.3mf` has one item per body, each dropped to z = 0 and spaced along
    x by its bbox plus 5 mm, written by rewriting the build items of the model XML with
    transforms. If that fails, the fallback is `<stem>.body-N.stl`, at most eight of them.
- `split(keepTop, keepBottom)` joins the allow-list as a keyword-only row, with a
  documented exception in the signature test, for cutting a part too tall for the bed.
- `NEXT_LOOSE` is rewritten for a count mismatch ("expected 1 body, got 3: if loose bodies
  are intended, pass bodies=3"). It changes in the same edit as its pinned tests in
  `test_cad_extension.py`, the skill's quotes and `failures.md`.
- The skill: step 3 explains `bodies`, step 7 says which 3MF to load in each case, and 58's
  `fdm.md` gives the clearances.

**Key files** — `examples/deerflow-extension-cad/deerflow_extension_cad/tool.py` (the
schema, `EXPECTATIONS`, `NEXT_LOOSE`), `checks.py`, `measure.py`, `build.py` (`export`,
`solid_of`), `allowlist.py` (`split`), the package tests `test_build.py` and
`test_measure.py`, `backend/tests/test_cad_extension.py`,
`backend/tests/test_context_fit_critical.py` (run, not edited),
`skills/public/cad-modeling/SKILL.md`, `references/failures.md`,
`tests/skills/test_cad_modeling.py`.

**Done when**

- A two-leaf hinge with a pin and 0.3 mm gaps passes with `bodies=3` and reports a gap of
  0.30 ± 0.01 mm with its direction. With a gap of zero it fails the body count; with a
  0.1 mm gap it passes and carries the clearance note.
- A captive pin's bore is measured as a hole of its body. A box and a lid with a 0.3 mm fit
  pass with `bodies=2`.
- `.3mf` has one item with N components, and `.parts.3mf` has N items on z = 0 that do not
  overlap in xy, or the per-body STL fallback is tested.
- Every one-body fixture gets the same answer as before; only the pinned sentence changes.
- `test_context_fit_critical.py` is green in every mode and with both workflows options,
  with `cad_build` at 145 tokens or fewer and no threshold changed.

---

## 52. Memory that helps a coding agent

**Goal** — The agent remembers how *this repository* is built and tested, what went wrong
last time, and how a past session solved a similar problem, without the user repeating it.

**Why it fits** — A review of `deerflow/agents/memory/` against coding work (FORK.md §55)
found long-term memory built for facts about the *user*: the extraction prompt
(`memory_update.chat.yaml`) stores only user-scoped, durable, descriptive facts and
explicitly forbids "workspace state, exact current file/commit/error state"; tool-call
turns are dropped before extraction; summaries are global per user. That is right for
preferences and wrong for "this repo's tests run with `make test` from `backend/`".
Procedures already have a home in skills (§55's learning loop); what is missing is the
small, always-relevant layer under them.

**Depends on** — nothing open. Skills (§55) stay the place for multi-step procedures.

**Scope**

- **Repository scope.** Key facts to a repository identity (the normalized `origin`
  URL, falling back to the workspace path) and inject only the facts of the repository
  the run is working in. Today the nearest thing, project memory
  (`deerflow/projects/memory.py`, 30 facts / 2 KiB), is keyed to a user-created
  conversation group with no repository field.
- **A procedure/constraint category** for "how to build, test, run, deploy here" and
  "never do X here", admitted by the deterministic gate only with evidence from a
  successful tool run in the same turn, so a guessed command never becomes memory.
- **Agent-writable project memory.** No tool reaches project facts; in `mode: tool`
  the agent can write user facts but not the conventions of the project it is in.
- **Search over past conversations.** `/threads/search` matches titles only and the FTS5
  index covers facts only; an FTS index over finished runs' final answers (not tool
  output) would let the agent find "how did we fix the flaky test last week".

**Key files** — `deerflow/agents/memory/backends/deermem/deermem/core/prompts/memory_update.chat.yaml`,
`core/storage.py`, `core/message_processing.py`, `deerflow/projects/memory.py`,
`deerflow/agents/memory/tools.py`, `app/gateway/routers/threads.py` (search).

**Done when** — a fact learned while testing repository A is injected in a later run on
A and never on B; a guessed command that failed is not stored; and the 32K critical
check still fits.

---

## 53. See the part

**Goal** — Every build that produced geometry, passed or failed, writes one picture: an iso
view beside top, front and right views, with the measured size printed on it. The reply
shows it inline, so a user on a phone sees the part without opening anything, and a vision
model can look at it once before it presents the part.

**Why it fits** — Today the GLB and STL only download, and nothing looks at the part.
Pictures catch gross errors that pass every numeric check, such as a feature on the wrong
face or a missing one: in CADSmith, removing vision raised the mean Chamfer distance from
0.74 to 18.19. Showing a PNG needs no core or frontend work. `png` is in
`browserPreviewExtensions`, `resolveMessageImageURL` renders
`![](/mnt/user-data/outputs/x.png)` inline in the chat, and `view_image` already allows the
outputs directory for `supports_vision` models. It needs no OpenGL either: a numpy and
Pillow z-buffer took 0.57–0.74 s on about 18k triangles, while VTK offscreen fails without
EGL or OSMesa, the Gateway image deliberately ships only the GL dispatch libraries, and
matplotlib writes a cache under HOME.

It costs nothing in the schema or the short tool form, about 15 answer tokens per passed
build, and about 1–1.5K image tokens only when a vision model calls `view_image`.

**Depends on** — nothing open.

**Scope**

- A new `deerflow_extension_cad/render.py` with
  `render_views(stl_bytes, bbox, *, size=960, failed_checks=None) -> bytes`:
  - it reads the binary STL that `export()` wrote, so the picture is the printed file;
  - a 2×2 sheet: iso (+X −Y +Z), top (+Z), front (−Y) and right (+X);
  - flat Lambert shading, with feature edges over 30° drawn dark;
  - a footer "W × D × H mm" from the measured bbox, in Pillow's built-in font, and an
    axis triad;
  - a "did not pass: <checks>" banner on a failed build;
  - it decimates above 200k triangles, and never imports matplotlib, VTK or GL.
- `worker.py`: after measuring, write `result.json` with the status `built` first, then
  enter the phase `rendering`, then rewrite `result.json` with `files.png`. `request.json`
  carries the wall-clock budget, and rendering is skipped with the note "no picture: the
  build used most of its time" when less than 3 s remain. A renderer exception becomes the
  note "no picture: <reason>".
- `tool.py`:
  - `rendering` joins `_PHASES`;
  - on a timeout in that phase with a built result present, `run_worker` returns that
    result with the no-picture note. Today it discards everything on a timeout, which is
    why the built result is written before rendering starts;
  - the save order for a passed part is `.py`, `.png`, `.glb`, `.stl`, (`.3mf` from 54),
    `.step` as the last geometry file, then `.report.json`; for a failed build, `.py`,
    `.failed.png`, `.failed.glb`, `.report.json`. Refusals and kernel failures write no
    image.
- `NEXT_REVIEW` gains one clause when a picture exists: "Show <stem>.png in your reply; if
  you can view images, look at it once and compare it with the request." It changes
  together with its pinned tests and the skill's quotes.
- `examples/deerflow-extension-cad/pyproject.toml` declares numpy and pillow explicitly,
  with ranges that match what `backend/uv.lock` already resolves through vtk and matplotlib,
  and `test_cad_runtime_deps.py` imports both.
- The skill: step 5 says the numbers decide and the picture finds what they do not
  measure, viewed once at review rather than on every attempt; step 7 embeds it as
  `![name](path)`; `failures.md` explains the no-picture note.
- Docs: the extension README's files table; FORK.md §51, which says the picture is not a
  check and carries no dimension beyond the bbox; a README bullet; and
  `docs/guide/cad-parts.md`, shared with 54.

**Key files** — `examples/deerflow-extension-cad/deerflow_extension_cad/render.py` (new),
`worker.py`, `tool.py`, `examples/deerflow-extension-cad/pyproject.toml`,
`backend/uv.lock`, `examples/deerflow-extension-cad/tests/test_render.py` (new),
`tests/test_worker_process.py`, `backend/tests/test_cad_extension.py`,
`backend/tests/test_cad_runtime_deps.py`, `skills/public/cad-modeling/SKILL.md`,
`tests/skills/test_cad_modeling.py`, `docs/guide/cad-parts.md` (new), and in
`docs/repo-map/`, `index.md` and the CAD row of `generation-and-media.md`.

**Done when**

- `tests/test_render.py`: a box, the 100-hole shelled enclosure and a failed build each
  give a PNG that Pillow decodes, at most 960×960 px and 400 KB. The top view shows
  background at a through hole's centre, the silhouette lies within 2 px of the projected
  bbox, and the enclosure renders in under 1.5 s.
- `test_worker_process.py`: a passed build saves `.png` before `.step`; a failed build
  saves `.failed.png`; a refusal saves no image; with the renderer forced to raise, the
  build still passes and carries the note; and a timeout forced during `rendering` still
  delivers the checked part.
- A frontend unit case resolves `![part](/mnt/user-data/outputs/part.png)` to the artifact
  URL.
- The context-fit check is unchanged, and `test_bundled_cad_extension.py` and
  `test_cad_runtime_deps.py` are green.
- Whether vision models make good use of the picture is measured by 48, which counts
  `view_image` calls.

---

## 54. Ready to print

**Goal** — A passed part comes with a slicer-ready `<name>.3mf` in millimetres, a GLB that
opens at real size in any glTF viewer, and a print block: bed contact, overhang, a sampled
thinnest wall, fit to the bed, a better face down, a watertight mesh, and grams. Pass or
fail never changes.

**Why it fits** — Nothing says today whether a part will print; SKILL.md step 1 marks "how
it prints" as unchecked. Prototypes measured a T-shape's overhang at 300 mm², its bed
contact at 100 mm² and its wall at 4.0 mm, and a 1 mm shell's wall at 1.000 mm, each in
0.02–0.3 s. CadQuery 2.8 writes 3MF itself, in millimetres, and on a compound it writes one
item with N components, which is the right layout for print-in-place. The GLB holds
millimetre values in a format defined in metres, so a 40 mm part opens as 40 m in Blender
or Scene Viewer. Printer facts in `config.yaml` cost no tokens, and the API cannot write
them.

It costs nothing in the schema or the short form, about 2 tokens in the full form, and
about 25–50 answer tokens per passed build for the print block and its notes.

**Depends on** — nothing open. Where 53 has landed, the 3MF takes its place in that save
order.

**Scope**

- `settings_from` reads an optional `printer:` mapping from the CAD record's config:
  `build_volume_mm` [x, y, z] (with no fit note when it is unset), `nozzle_mm` 0.4,
  `layer_mm` 0.2, `overhang_deg` 45, `min_clearance_mm` 0.3 and `density_g_cm3` 1.24. Each
  value is bounded, and an error names its key. `config.example.yaml` documents them,
  commented, in the CAD record. There is no `config_upgrade` migration, because every key
  is optional.
- A new `deerflow_extension_cad/printability.py`, numpy over the STL arrays:
  - `bed_contact_mm2`;
  - `overhang_mm2` beyond `overhang_deg`, with the bed faces excluded;
  - `watertight`, every edge shared by exactly two triangles;
  - the best of the six axis orientations, reported only when it at least halves the
    overhang;
  - the fit to the build volume, per axis.

  `measure.py` adds `thinnest_wall_sampled_mm`, by inward rays from sampled face points
  through the existing `IntCurvesFace` intersector, capped at 1 s.
- `worker.py`:
  - a phase `checking print`, skipped with a note when time runs short, like the render;
  - `report.json` always holds `measured.print`;
  - the answer carries a compact print block, and notes only past fixed thresholds: a wall
    under two nozzle widths, an overhang that needs support (naming the better face down),
    larger than the bed, not watertight;
  - `decide()` never reads the print block.
- `build.export` writes `part.3mf` after the STL, under the existing export cap, and
  `tool.py` saves `<stem>.3mf` for passed parts, before the STEP. The GLB's JSON chunk is
  rewritten so that the root node has the scale [0.001, 0.001, 0.001], keeping the 4-byte
  chunk alignment, for passed and failed GLBs alike.
- The full-form description's last sentence names 3MF, and the README states the units:
  GLB in metres; STL, STEP and 3MF in millimetres.
- The skill: step 1's "how it prints" becomes "reported, not checked"; step 2 builds in
  print orientation, with the bed face at the lowest z; step 7 says the 3MF is for the
  slicer. `docs/guide/cad-parts.md` covers the printer profile, what is checked and what is
  reported, and the limits.

**Key files** — `examples/deerflow-extension-cad/deerflow_extension_cad/printability.py`
(new), `measure.py`, `build.py` (`export`), `worker.py`, `tool.py` (`settings_from`, the
save order, the notes), `examples/deerflow-extension-cad/tests/test_printability.py` (new),
`tests/test_build.py`, `backend/tests/test_cad_extension.py`, `config.example.yaml` (the
CAD record), `docs/guide/cad-parts.md`, `skills/public/cad-modeling/SKILL.md`, FORK.md §51,
`docs/repo-map/generation-and-media.md`.

**Done when**

- `tests/test_printability.py`: the T-shape's overhang is 300 ± 1 mm² and its bed contact
  100 ± 1 mm²; the 1.0 mm shell's wall is 1.00 ± 0.05 mm; a 300 mm part on a 256 mm bed
  gets the fit note; a plate built standing on its edge reports a better face down; a cube
  is watertight; and the 17.6k-triangle enclosure adds under 1 s.
- The 3MF is a zip with `3D/3dmodel.model` in `unit="millimeter"`, and its vertex bounds
  equal the measured bbox. In `tests/test_build.py`, the GLB's accessor max times the root
  scale equals the bbox divided by 1000, within 1e-6.
- `passed` is identical with and without the print block on every existing fixture. A
  passed build saves `.py`, `.png`, `.glb`, `.stl`, `.3mf`, `.step` and `.report.json`, in
  that order.
- An invalid printer value fails install with a message that names the key (a host test,
  with no kernel).
- The context-fit check is unchanged, the bundled snapshot matches the package, and
  `docs/guide/cad-parts.md` is linked from the guide table in `README.md`.
- Whether the thresholds suit real printers is the owner's check, with 58's coupon.

---

## 55. Scripts the way models write them

**Goal** — Habits models already have — tuple assignment, `math`, `min` and `max`,
indexing, comprehensions — are read rather than refused, so the attempts go to geometry.
Every refusal names its construct in a structured field. The opening sentence of the tool
description gets cheaper, which pays for 51's parameter.

**Why it fits** — The reader refuses each of these today, and each refusal costs one of the
eight attempts: `w, d, t = 60, 40, 6`; `import math`; comprehensions; `p[0]`; and `min`,
`max`, `abs`, `round` and `int`. All of them are arithmetic the reader can compute itself,
so none of them reaches a lookup or the kernel. Refusals keep counting toward the eight
attempts, as the `MAX_ATTEMPTS` comment intends; 48 reports refusals separately, and that
data decides whether a separate budget is ever worth having.

The rewritten opening measured 136 tokens against 146 for the description as it stands
(2026-11-21), so this item gives back 10 tokens of every request, in every mode, under the
150-token cap. The interpreter is the security boundary, so this item lands as its own
commit, with its SECURITY.md text, for review.

**Depends on** — nothing open.

**Scope**

- `interpreter.py` accepts:
  - tuple-unpacking assignment of plain names, with equal arity and no starred targets;
  - `import math` in exactly that form, with a closed table — pi, tau, sin, cos, tan,
    asin, acos, atan, atan2, sqrt, hypot, radians, degrees, floor, ceil — computed by the
    reader's own functions, never by `getattr` on a module;
  - `min`, `max`, `abs`, `round`, `int`, `float` and `len`, on numbers and on lists the
    script stated;
  - subscripts with an integer index that is known at read time and in range, and no
    slices;
  - list comprehensions with one `for` over `range()` or a literal list and no `if`,
    unrolled like loops.

  Every evaluation counts toward `MAX_WORK` and passes the magnitude bound. A non-finite
  result or a domain error becomes a refusal with its line.
- `_RESERVED` gains `math`, `min`, `max`, `abs`, `round`, `int`, `float` and `len`, so a
  script cannot rebind them, and `math` is admitted only as the base of an attribute from
  the table.
- These stay refused: `if`, `while`, `def`, comparisons, conditional expressions,
  f-strings, `from math import`, any other import, and any other attribute.
- Structured refusals: `ScriptRefused` carries `.name`, and the worker's answer, the tool's
  answer and `report.json` carry `error.refused` (for example `import os`).
- The interpreter records `parameters`: the top-level numeric names assigned once before
  the first operation. They go into the report, for follow-up edits.
- The description's opening becomes "Build and check a part from a CadQuery script. It is
  read, not run: assignments, arithmetic, math, for loops and allow-listed Workplane
  methods; no if, while or def. Millimetres."
- Changed together, in the one reviewed commit: SKILL.md step 2's "may not contain" list;
  `references/failures.md`; the REFUSED list in `tests/skills/test_cad_modeling.py`, whose
  admitted idioms move to an accepted list; and one SECURITY.md bullet for the closed
  numeric table and the bounded subscripts.

**Key files** — `examples/deerflow-extension-cad/deerflow_extension_cad/interpreter.py`,
`worker.py`, `tool.py` (the description's opening, the refused field),
`examples/deerflow-extension-cad/tests/test_interpreter.py`,
`backend/tests/test_cad_extension.py`, `tests/skills/test_cad_modeling.py`,
`skills/public/cad-modeling/SKILL.md`, `references/failures.md`, `SECURITY.md`, and the
snapshot under `backend/extensions/sources/deerflow-extension-cad/`.

**Done when**

- `test_interpreter.py`: each idiom compiles to the same Program as its written-out form,
  and `20*math.sin(math.radians(30))` equals 10 within 1e-9.
- These are refused with their line: `math = 3`, `min = 2`, `math.system`,
  `math.__dict__`, `getattr(math, 'sin')`, `from math import *`, `p[1:2]`, an out-of-range
  index, `math.sqrt(-1)` and `int(1e400)`. A comprehension of 10^6 passes is stopped by
  `MAX_WORK`.
- The existing boundary tests still pass: one `ast.parse` call site, and no `exec`,
  `eval`, `compile` or script-driven `getattr`.
- The real handler builds a plate script that starts with `w, d, t = 60, 40, 6` and
  `import math`. A script that calls a method outside the table answers with
  `error.refused` naming that method.
- `test_context_fit_critical.py` is green with `cad_build` at 137 tokens or fewer (136 when
  measured), and no threshold is raised.

---

## 56. Operations that need no new trust

**Goal** — Knobs, pulleys, funnels, cups, swept rails, lofted transitions, angled holes and
curved outlines build on the default install, without item 50.

**Why it fits** — 61 of CadQuery 2.8.0's 107 Workplane methods are not on the allow-list.
The ones added here build valid solids in under 0.05 s and take only plain data, or a part
built earlier in the script (the existing WORKPLANE kind), so none of them needs new trust.
At least 5 of CadQueryEval's 25 tasks (7, 10, 11, 14 and 15) need them, and Text2CAD-Bench
shows execution collapsing exactly at sweep and loft.

The method list sits after the 280-character cut of the short tool form, so a small window
pays nothing for it (measured: 13 more names leave `cad_build` at 146 tokens). The full
form grows by about 30 tokens on larger windows, which no check pins. Moving the list into
the skill to save those tokens was considered and is not needed, and the list helps
large-window models.

**Depends on** — 55.

**Scope**

- `allowlist.py` rows, each a prefix of the kernel's positional order and checked against
  the 2.8.0 signatures:
  - `revolve(angleDegrees, axisStart, axisEnd, combine, clean)`;
  - `loft(ruled, combine, clean)`;
  - `sweep(path, multisection, sweepAlongWires, makeSolid, isFrenet, combine, clean,
    transition)`, with `path` of the WORKPLANE kind and `transition` from the closed set
    right, round, transformed; `normal` and `auxSpine` are not exposed;
  - `twistExtrude(distance, angleDegrees, combine, clean)`;
  - `transformed(rotate, offset)`;
  - `spline(listOfXYTuple, tangents, periodic)`;
  - `radiusArc`, `sagittaArc`, `tangentArcPoint`, `polarLine` and `polarLineTo`;
  - `offset2D(d, kind)`, with `kind` from the closed set arc, intersection;
  - `wedge`;
  - `end(n)`, `first()` and `last()`.
- `combine` stays the existing BOOL kind everywhere, so `'cut'`, `'a'` and `'s'` stay
  unreachable; `cut()` covers them.
- `build.py`: revolve, loft, sweep, twistExtrude and wedge join `_MUST_CHANGE`, `_SHAPING`
  and `_HINTS`. The hint sentences: a loft needs two or more closed outlines on separate
  workplanes; a sweep's path must start on the profile's plane; a revolve's axis must not
  cross the outline. A sweep whose path holds a solid instead of wires or edges is refused
  before the kernel runs.
- `tests/test_build.py`:
  - the forbidden-list test drops `sweep`, with the reason that its path is script
    geometry, not a file; `text`, `split`, `each`, `eachpoint`, `cutEach` and
    `parametricCurve` stay in it;
  - one example per new method builds a valid solid that matches an analytic volume: a
    square swept along a 20 + 20 mm L path gives 640 mm³, a frustum loft, a revolved ring,
    and a twistExtrude with the same volume as the plain extrude;
  - a self-intersecting sweep fails or times out cleanly in the worker;
  - a loft that changes nothing fails with its hint.
- `references/operations.md` is regenerated (`python deerflow_extension_cad/allowlist.py`).
  The description's Methods list and the README table and count change in the same edit;
  `test_the_tool_description_and_the_readme_list_exactly_the_allow_listed_methods` pins
  them together.
- Docs: SKILL.md step 2's "not available" sentence lists what is still missing after this
  item — text and threads (59), sketches, parametric curves, variable fillets, and loose
  bodies (51); `failures.md` gains entries for loft, sweep and revolve failures; and FORK.md
  §51's known gaps list each excluded method with its reason.

**Key files** — `examples/deerflow-extension-cad/deerflow_extension_cad/allowlist.py`,
`build.py` (`_MUST_CHANGE`, `_SHAPING`, `_HINTS`), `tool.py` (the Methods list),
`examples/deerflow-extension-cad/tests/test_build.py`,
`examples/deerflow-extension-cad/README.md`,
`skills/public/cad-modeling/references/operations.md`, `SKILL.md`,
`references/failures.md`, FORK.md §51, and the snapshot under
`backend/extensions/sources/deerflow-extension-cad/`.

**Done when**

- `cd examples/deerflow-extension-cad && uv run --no-project pytest -q` passes, including
  the signature-prefix test for every new row and the analytic-volume examples within
  0.1%.
- The reference scripts for CadQueryEval tasks 7, 10, 11, 14 and 15 build through
  `compile_script` and meet their ground truth (in 48's `test_eval_specs.py`).
- A loft or sweep that changes nothing fails with its `_HINTS` sentence, and a sweep along
  a solid is refused before the kernel loads. A method outside the table, such as
  `parametricCurve`, still answers "not on the allow-list"; `text()` and `split()` come
  only with 59 and 51, each in its own reviewed edit.
- `test_context_fit_critical.py` is unchanged and green, and `test_bundled_cad_extension.py`
  passes after the snapshot refresh.

---

## 57. Where the features are

**Goal** — The answer says where every hole is and which way it points, and a hole can be
checked by its position. It also says where the part sits and how many edges each fillet or
chamfer took. Every report names the module, kernel and script that produced it. The
checks live in a module with no host imports, so 48 and 50 can reuse them.

**Why it fits** — FORK.md §51's largest known gap is that the tool measures no positions,
so a feature on the wrong face passes every check. `measure_holes` already computes each
hole's axis point and then drops it. A fillet on `edges("|Z")` that also rounds a rim goes
unseen. The `hole_diameters_mm` items carry no type in the schema, so `[d, x, y, z]`
entries need no schema change; only `_problem_with` and `decide()` change. Item 48 needs
versions, a script hash and the file set in `report.json`, and 48 and 50 need `decide()`
importable without `deerflow_extension_api`, which `tool.py` imports at module level.

It costs nothing in the short form and about 8 tokens in the full form. The answer grows by
at most about 120 tokens on parts with many holes, capped and pinned by a test.

**Depends on** — 55 (`parameters` and `error.refused` for the report).

**Scope**

- A new `deerflow_extension_cad/checks.py` with no `deerflow_extension_api` import, holding
  `_close`, the tolerances, `decide()`, `notes_on()` and `unchecked()`; `tool.py` imports
  them.
- A new `deerflow_extension_cad/measure_cli.py`:
  `python -I -m deerflow_extension_cad.measure_cli <step> <truth.json>` re-imports one STEP
  under the worker's rlimits (`worker._limit`) and prints `measure_step` with a
  ground-truth verdict as JSON.
- `measure.py`: each hole gains `at`, the axis point on its entry face to 0.01 mm, and
  `axis`, a unit vector. `measure_step` adds `bbox_min_mm`, `bbox_max_mm`,
  `centre_of_mass_mm` and `area_mm2`.
- `build.py` records, for each fillet and chamfer the result is made of, how many edges its
  selection took (`measured.selections: [{line, method, edges}]`).
- `decide()` matches positioned holes:
  - a hole entry is a number or `[d, x, y, z]`;
  - a positioned entry passes when a measured hole of that diameter has its axis line
    within max(0.05 mm, 0.1% of the largest bbox side) of the point;
  - matching is one to one within each diameter;
  - plain-number entries behave exactly as they do today;
  - `_problem_with` accepts the mixed form, `MAX_HOLES` still applies, and the Attempts
    table holds the entries canonically sorted.
- The answer lists up to 12 holes with `at` and `axis`, and beyond that one note naming the
  report; it carries at most `MAX_LINES_SAID` selection notes. `report.json` holds
  everything, with each hole written once rather than in both `checks` and `measured`.
- `report.json` gains `module_version`, `cadquery_version`, `script_sha256`, `files` (the
  saved names of the set), `parameters` (from 55) and `error.refused`.
- The full-form description's sentence becomes "hole_diameters_mm lists one diameter, or
  [d, x, y, z], per expected hole". The short form does not change.
- The skill: step 1 makes positions a requirement line; step 3 shows an example with
  positioned holes; step 5 replaces "The tool measures no positions" with what it measures
  now, and what it still does not (pockets, bosses, slots); `failures.md` gains a selector
  that took more edges than intended. FORK.md §51's known gaps change to match.

**Key files** — `examples/deerflow-extension-cad/deerflow_extension_cad/checks.py` (new),
`measure_cli.py` (new), `measure.py`, `build.py`, `tool.py`,
`examples/deerflow-extension-cad/tests/test_measure.py`,
`backend/tests/test_cad_extension.py`, `skills/public/cad-modeling/SKILL.md`,
`references/failures.md`, FORK.md §51 (known gaps), and the snapshot under
`backend/extensions/sources/deerflow-extension-cad/`.

**Done when**

- `test_measure.py`: a plate with holes at (−15, 0) and (15, 5) and a side hole along X at
  (20, 0, 0) reports those axis points within 0.01 mm, with their axes; an off-origin box
  reports its corners; a 10 mm cube reports an area of 600 mm² and its centre as the centre
  of mass.
- `decide()`: four holes 1 mm off their stated centres fail, and the check gives both
  positions; at the right centres they pass. `[d, 25, 0, 0]` matches the side hole,
  because the point lies on its axis. Every existing plain-diameter test is unchanged.
- The rim-fillet fixture reports the larger edge count.
- A test using `estimate_tokens` shows that a four-hole plate's answer grows by at most 120
  tokens over today's.
- `report.json` carries the provenance keys, and a 400-hole report stays under 50,000
  bytes.
- `measure_cli` prints a verdict for a fixture STEP, and `checks.py` imports with
  `deerflow_extension_api` absent (a subprocess test).
- The context-fit check is unchanged.

---

## 58. Design for the printer

**Goal** — By default the model designs parts that print on a home FDM printer and fit
real screws, nuts and inserts, with fewer questions. Printer facts come from 54's print
block and clearances from a reference; a draft is shown as a picture before details are
argued; and a fit-test coupon is offered when a part must fit real hardware.

**Why it fits** — The skill teaches CadQuery but not printing. For a user on a phone, one
correction round on a picture replaces a round of questions, and a ten-minute coupon print
prevents a failed print of several hours. Reference files load on demand and the skill's
index line does not change, so the cost per request is nothing; `fdm.md` costs about 1.5K
tokens only when it is read. SKILL.md is already 9,017 bytes, so the bulk goes into the
reference file. This item also carries 45's skill revision. Whether real models follow it
is measured by 48.

**Depends on** — 53, 54 and 57, whose outputs and sentences it teaches.

**Scope**

- A new `skills/public/cad-modeling/references/fdm.md`:
  - FDM holes print undersized (+0.2 mm);
  - ISO 273 medium clearance holes (M2 2.4, M2.5 2.9, M3 3.4, M4 4.5, M5 5.5);
  - ISO 4032 nut traps, across flats (M3 5.5, M4 7, M5 8), plus 0.3 mm;
  - heat-set inserts: follow the vendor's table;
  - fits: press 0–0.1 mm, sliding 0.2 mm, print-in-place 0.3–0.5 mm;
  - 45° overhangs, teardrop horizontal holes, a chamfer rather than a fillet on bed
    edges, and walls of at least two nozzle widths;
  - build in print orientation;
  - the coupon recipe.
- SKILL.md:
  - step 1: do not ask for printer facts; ask only for the dimensions that decide the
    shape, and otherwise build with listed assumptions and show the picture;
  - step 2: diameters include the FDM allowance;
  - step 5: judge the print notes;
  - step 7: the picture inline, the 3MF for the slicer, the STEP to edit, and the coupon
    offer.

  The "good loop" example shows positioned holes and the picture.
- `tests/skills/test_cad_modeling.py`: `fdm.md` exists and SKILL.md links it; every
  clearance exceeds its nominal size, and across-flats sizes rise with the thread size; the
  quotes still match the tool's sentences.
- FORK.md §51 records the skill changes, and that real models have not yet been shown to
  follow them; it cites 48, not 45, for the live proof.

**Key files** — `skills/public/cad-modeling/references/fdm.md` (new),
`skills/public/cad-modeling/SKILL.md`, `references/failures.md`,
`tests/skills/test_cad_modeling.py`, FORK.md §51.

**Done when**

- The skill test is green with the new checks, and `operations.md` and `failures.md` agree
  with 55–57 and 59.
- SKILL.md stays at 10 KB or less, and `fdm.md` at 6 KB or less.
- FORK.md cites 48 for the live proof.
- Whether models follow the procedure is 48's live run, and whether the clearances fit is
  the owner's coupon print.

---

## 59. Lettering and threads

**Goal** — Name tags, labels and screw caps build on the default install: `text()` with a
font the package ships, and helix threads swept along a helix the reader makes.

**Why it fits** — These are common home-print requests, and both work in the kernel:
`text()` built a valid solid in 0.26 s with system fonts, and an M8×1.25×10 helix thread,
swept and unioned, built a valid solid in 1.27 s. Unlike 56, each widens a stated
invariant: SECURITY.md keeps fonts off the allow-list, and the reader allows nothing on
`cq` but `Workplane`. That is why they ship as their own reviewed commit, with threads
behind a build-time gate, since fine-pitch threads are where kernels hang. The slim Gateway
image has no system fonts, so the font is bundled.

It costs nothing on windows of 64K or less, and about 5 tokens in the full form.

**Depends on** — 56 (`sweep`).

**Scope**

- `text(txt, fontsize, distance, combine, clean)`, with `combine` of the BOOL kind (the
  kernel's default, `'cut'`, applies when it is left out), and `halign`, `valign` and
  `kind` as closed-set keywords.
  - `font` and `fontPath` are never in the table: `build.py` injects the path of the
    bundled font, DejaVu Sans with its licence in `deerflow_extension_cad/fonts/`.
  - `txt` is at most 64 printable characters and counts against `MAX_WORK`.
  - The signature-prefix test gets an explicit "injected by build.py" exception, and
    `fontPath` stays in the forbidden list.
- Threads:
  - `cq.Wire.makeHelix(pitch, height, radius, lefthand)` becomes the reader's only
    constructor outside `Workplane`, with bounded numbers and at most 200 turns;
  - its value is a new PATH kind, accepted only as `sweep`'s path;
  - it ships only if kernel tests build M8×1.25 and M24×3 threads valid in under 5 s
    each; otherwise threads move to item 50's list.
- SECURITY.md gains two bullets: the font is the package's, never the script's; and the one
  helix constructor. FORK.md §51 records the decisions, `failures.md` gains entries, and
  `fdm.md` a note: text at least 5 mm tall and 0.6 mm deep. The snapshot is refreshed; the
  font adds about 0.7 MB to the package and to the snapshot, and its licence file is
  confirmed before it ships.

**Key files** — `examples/deerflow-extension-cad/deerflow_extension_cad/allowlist.py`,
`interpreter.py`, `build.py`, `fonts/` (new),
`examples/deerflow-extension-cad/tests/test_build.py`, `tests/test_interpreter.py`,
`SECURITY.md`, `skills/public/cad-modeling/references/operations.md`, FORK.md §51.

**Done when**

- Kernel tests: a 40×15×3 plate with "HELLO" cut 0.6 mm deep passes `decide()`, and the
  M8 and M24 threads pass within the gate.
- These are refused, each with its reason: `fontPath=`, `font=`, `cq.Wire.makePolygon`,
  any other `cq.` attribute, and a helix path given to anything but `sweep`.
- The `operations.md` and description and README method-list tests are green, and the
  context-fit check is unchanged.
- SECURITY.md changes in the same commit, and `test_bundled_cad_extension.py` passes.

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
shape of the CAD idea behind the CAD items. This fork is a server reached from a browser,
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

**OpenSCAD or build123d as the core language.** Models write OpenSCAD easily and it
rebuilds quickly, but it has no true fillets or chamfers, exports meshes rather than STEP
by default, gives the checker no analytic holes to measure, and fails silently where
CadQuery fails loudly. build123d has no head-to-head result over CadQuery and less training
data behind it, and 0.13 needs OCP 8 where CadQuery 2.8.0 needs OCP below 8, so the two
cannot share a kernel. Either, if it is ever wanted, is one more input format for item 44,
argued on its own; build123d may enter item 50's image only as 0.12.x on OCP 7.9, and only
if item 48 asks for it.

**STEP preview in the browser.** Item 46 used to plan a second step that read STEP files
in the viewer through an OpenCascade WebAssembly build. `occt-import-js.wasm` is 7,604,031
bytes, over the 4 MiB per-asset cap; it is LGPL-2.1 and was last published in 2024-12; a
Worker in the opaque origin cannot fetch a separate WASM file; and it is a second OCCT
build that tessellates differently from the kernel that measured the part. The CAD module
already writes a GLB from the same shape, so the GLB is the preview and the STEP is the
download.

**A hosted text-to-CAD backend.** Zoo (KittyCAD), Onshape FeatureScript and CADAM are cloud
geometry engines: the design leaves the machine, they return KCL or meshes rather than a
script the user can edit, and they charge by the minute. That is the opposite of a
local-first fork with an offline switch.

**An OS process sandbox for full scripts without Docker.** bubblewrap and srt run on Linux
only and Seatbelt on macOS only, so each covers one of the supported hosts; Ubuntu 24.04
restricts the user namespaces they need through AppArmor; and each would need its own
security review. What it would unlock is unknown until item 48 counts refusals, and item 50
already names the route where a container exists.

**A FreeCAD file from a model-written script.** Item 50 used to offer an image variant that
wrote a native `.FCStd` beside the STEP. Opening a crafted `.FCStd` runs code in FreeCAD
before 1.1.2 (CVE-2026-34789), so a file the model's script wrote would carry that script's
reach out of the container and onto the user's unsandboxed desktop. The STEP stays the file
to edit.

**Slicing, or sending a job to a printer, from the CAD worker.** The worker starts no
process, and its process-group kill is reasoned from that. The slicers are AGPL binaries
that uv cannot install, and sending a job is a consequential action that waits for item 36.
If it is wanted, it comes later as a separate, optional extension that takes the 3MF item
54 writes.

**A separate refusal budget for the CAD tool.** The `MAX_ATTEMPTS` comment budgets one or
two refusals on purpose, item 55 removes the commonest ones, and a second budget would
change the pinned `NEXT_*` sentences. Item 48 reports refusals by construct; this is
revisited only if its data shows that refusals still use up the attempts.

**A CAD-specific repair store, and other CAD extras.** Repair patterns go to `failures.md`
through the skill learning loop (FORK.md §55), and item 55 records a part's parameters in
`report.json` for follow-up edits. Consensus sampling, FEA feedback, DXF export, a panel
that rebuilds a part from its parameters, and remixing uploaded STEP files have low
measured value for this user now, and each needs a new hook (`read_output`) or new UI.
