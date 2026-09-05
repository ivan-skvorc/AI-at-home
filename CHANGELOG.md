# Changelog

All notable changes to DeerFlow are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **subagents:** **Local sub-agents now run as many at a time as the GPU can
  actually hold — no more, and no fewer.** Sub-agent concurrency used to be one
  startup number (`subagent_runtime.max_running`, default 3) applied to every
  model. Dispatching three of them onto a local model that fits your card once
  did not fail — Ollama queues the extras inside the daemon, invisible to the
  app, while each sub-agent's own timeout counts down; two different local
  models that do not co-reside are worse, because the daemon evicts one to load
  the other on every alternation. Local dispatch now asks the card instead: five
  sub-agents on a model that fits once run one at a time, on a model your card
  holds twice they run two at a time, and models small enough to co-reside still
  all run at once. A model too big for the card gets the card to itself rather
  than being refused. New keys `subagent_runtime.local_model_capacity.enabled`
  (default `true`) and `.queue_timeout_seconds` (default `1800`); the gate
  engages only when `ollama.vram_gb` is set and the model carries the sizing
  metadata `scripts/sync-ollama-models.py` writes, so hosted models and unsized
  local models dispatch exactly as before. `ollama.num_parallel` is the ceiling
  on how many sub-agents share one resident model and must match the daemon's
  `OLLAMA_NUM_PARALLEL`. The sync now also records each local model's
  `kv_bytes_per_token`, so the footprint is costed as weights plus the cache for
  the window the entry asks for rather than weights alone.

- **chat:** **Automatic conversation renaming is now a setting, with its own
  model picker.** A new **Settings → Conversation titles** page turns the
  rename-from-the-first-exchange behaviour off, and picks which model writes the
  name: *No model call* (the title is your first message, shortened — free and
  instant), any configured model, or *Server default*, which follows
  `config.yaml -> title.model_name` and ships as `null`, i.e. no model call. The
  operator master switch is unchanged (`title.enabled` / `title.model_name`, no
  new config keys); turning it off there greys out the toggle with an
  explanation. **The rename now happens once the answer has finished** rather
  than partway through it — the same moment the Gateway lets you rename a
  conversation by hand again, since it refuses a rename while a run is in flight.
  Two consequences: the title describes the answer as well as the question, and a
  first turn that ends by asking *you* a clarifying question is finally named at
  all (it leaves the run through a path that skipped the rename, and only the
  first turn is ever titled, so those conversations stayed *New Conversation*
  permanently).

- **sidebar:** **Folders in the conversation list.** The sidebar's chat list is a
  tree now: press **+** in the *Recent chats* header to create a folder, drag
  conversations onto it (or use **Move to folder** in a chat's menu), and open or
  close it with the arrow beside its name. A conversation you file is **inside
  the folder and no longer listed outside it**, the way a file manager works, so
  a collapsed folder genuinely takes its chats off the list rather than showing
  them twice. **Rename** and **Delete** live in the folder's own **⋯** menu,
  beside the menu each conversation already has; deleting a folder never deletes
  the conversations in it — they return to the main list. Folder names, order and
  membership are stored per user on the server (the same `ui_state.json` store as
  the keep-alive chat tabs, via `GET`/`PUT /api/settings/chat-folders`), so they
  follow you across browsers and devices; only which folders are *expanded* is
  per browser. Filing a conversation does not count as activity, so it keeps its
  place in the recency order instead of jumping to the top. Ceiling of 50
  folders, one level deep. No configuration — on by default.

- **search/fetch:** **Three defaults that made a fresh install fail behind a VPN.**
  (1) The gateway image shipped Camoufox without the GTK/X11 libraries it loads,
  so the *default* `web_fetch` backend was present on disk and unable to start on
  every clean build — and every presence check passed, so it surfaced only as a
  fetch tool that errored on each call. (2) A stale `GITHUB_TOKEN` (loaded into
  the gateway with the rest of `.env`, where it exists for the sandbox) made
  Camoufox's release lookup fail with 401 instead of falling back to the
  anonymous path that works; the token is now stripped for that one subprocess.
  (3) When SearXNG's engines are blocked it answers HTTP 200 with an empty result
  list and names the failures in `unresponsive_engines` — which was discarded, so
  a total engine outage looked like a successful empty search and the agent
  re-queried straight into the 180-second suspension, extending it. That state is
  now an error naming the engines; a genuinely empty result set is still a
  success, and a partial failure still returns what it has. `web_fetch`'s timeout
  goes 10s → 30s (it drives a full Firefox render, not an HTTP GET), and the
  bundled SearXNG enables `mojeek`, `qwant` and `bing` so a blocked consumer
  engine costs some results instead of all of them. `fallback: jina` stays off by
  default on purpose — it would send every fetched URL to a third party.

- **models:** **A local model too big for your card gets a context window it can
  actually run in.** The launch-time Ollama sync sized every model as
  `vram - weights - overhead` and fell back to a 4096-token window when that went
  negative — smaller than the agent's own system prompt, so a 128K-native model
  was configured into uselessness. Such a model now gets a usable window, and a
  deliberately **bounded** one: Ollama splits whole layers between GPU and CPU and,
  when weights and KV cache do not both fit, keeps the cache and pushes layers to
  the CPU — so an unlimited window would trade a model that cannot run for one
  that merely crawls. Models that fit in VRAM are sized exactly as before. New
  optional key `ollama.system_ram_gb` (**unset by default**, detected by
  `make setup`) adds one launch-time warning naming any installed model whose
  weights exceed VRAM and RAM together, the state where Ollama pages from disk.
  It never changes a model choice.

- **chat:** **An internet switch on the conversation.** The composer gains a globe
  button that takes *this chat* offline: the run is assembled with no
  internet-reaching tool in it at all — `web_search`, `web_fetch`, browser
  control, every MCP tool and the external-agent tool are left out of the
  catalog, so the model is never even shown a schema for them — and the agent
  answers from the conversation, the thread's files and its own knowledge.
  **Subagents inherit it**, so delegating a `task` is not a way around a switch
  you turned off. The state belongs to the conversation rather than the app, so
  one chat can work offline while another keeps browsing, and it survives a
  reload. There is no config key and no restart: internet is **on** until you
  click the globe, and callers with no composer (IM channels, the TUI, scheduled
  tasks, the embedded client) are unaffected. Two limits are deliberate and
  documented: the switch governs the model's tools, not a sandbox shell's own
  network (the offline run is told not to use it as a workaround), and it does
  not stop the chat model call itself — a conversation that reaches nothing is
  this switch plus a local model.
- **models:** **The model dropdown lines its prices up, and says how big a local
  model is.** Rows now read *provider, name, price* — with the price pinned to
  the right edge of the row, so with a couple of dozen models the rates form a
  column you can compare down instead of trailing wherever each name happened to
  end. Under the name, next to the model id, a local model shows **its weights
  and the context window it was sized for** (`qwen3:8b · 5.2 GiB · 32K ctx`):
  those are the two numbers that decide whether a model actually fits on your
  card, and until now the only way to find out was to pick it and watch Ollama
  offload to CPU. The size is recorded per entry by
  `scripts/sync-ollama-models.py` (new `size_bytes:` key, read from the daemon's
  own `/api/tags`) and served, with the existing `context_window`, from
  `GET /api/models`; a model the daemon reports no size for, and every hosted
  model, simply shows nothing there. No configuration: re-running any launch
  path refreshes the synced block, and grouping by provider drops the per-row
  provider the section heading already carries.
- **media:** **Local image and video generation is on by default, and there is a
  button for it.** The `media` tool entries ship active in `config.example.yaml`
  (`config_version` 47; existing configs pick them up on the next
  `make config-upgrade`), and every launch path now resolves *or provisions* the
  service: a ComfyUI already running on the machine is reused, and when none
  answers the bundled container is started for you — but only where Docker **and**
  a GPU are detected, because the image reserves an NVIDIA device and starting it
  elsewhere fails at `compose up` rather than degrading.
  `DEER_FLOW_COMFYUI_AUTOSTART` overrides in both directions, and on a machine
  that cannot run one the tools stay bound and say so, which is what makes the
  agent fall back to the cloud generation skill instead of insisting (`make
  doctor` skips with the reason there rather than warning). Model files are still
  yours to supply, and now have a command for **both** shapes of the integration:
  `make comfy-models` lists what the running instance has, and `make
  comfy-model-add SOURCE=<url|path> TYPE=checkpoints` installs one into whichever
  ComfyUI is in use — the bundled container's bind mount, or the models directory
  of the instance you run yourself (resolved from `--models-dir`,
  `DEER_FLOW_COMFYUI_EXTERNAL_MODELS`, that container's own `models` mount, or a
  well-known install path, and refused rather than guessed at, because a
  successful download into the wrong ComfyUI looks exactly like success).
  Downloads are checksum-verified and renamed into place only once complete, so a
  truncated checkpoint never lists as installed. The workspace sidebar gains an
  **Image** entry beside *New chat* and *Democracy*: a setup page for what to
  generate, image or clip, resolution, checkpoint and whether to run the refine
  loop, which seeds the composer rather than sending — a clip is minutes per
  attempt. A toggle decides **who writes the prompt**: hand over a prompt to be
  submitted exactly as written (with your own negative prompt beside it), or
  describe the picture and have the assistant write the positive prompt — and a
  negative prompt where the chosen model uses one — and show you both before it
  generates. Checkpoints that sample at CFG 1 (Flux, turbo, lightning, LCM,
  Hyper) ignore a negative prompt, so the page says so instead of offering a box
  the sampler will never read. Resolution is two numbers rather than a shape
  name, with the aspect presets filling them in: values are snapped to ComfyUI's
  latent grid and the snapped size is the one shown, and the ceiling is lower for
  a clip, where an oversized run fails after minutes rather than seconds.

- **documents:** **Large documents and scanned PDFs no longer defeat small
  models.** A 300-page PDF does not fit a 32K-token local model, and the fallback
  — let the agent navigate it with `grep`/`read_file` — is a multi-step tool loop,
  which is the first capability a quantized model loses on long input. The new
  `analyze_document` tool reads a document in parts sized for whichever model is
  serving the run (a chapter at a time on a 200K cloud model, a few pages on a
  32K local one) and combines the notes in a separate, hierarchical pass, so no
  model call ever holds more than one part. A **scanned** PDF — one whose text
  layer is empty, which previously converted "successfully" into a file with
  nothing in it — is now detected, flagged in the upload list, and transcribed
  page by page by a vision model before anything is summarised; transcription and
  summarisation stay separate passes. The same window resolution lowers the
  `read_file`/`bash`/`ls` truncation caps and the `tool_output` thresholds, which
  were fixed character counts calibrated for a 200K cloud model. A configured
  limit is only ever a ceiling: an unknown window changes nothing, and an
  explicit `0` ("no limit") is never turned back on. Converted PDFs now carry
  `<!-- page: N -->` anchors so an answer can cite a page. Configured under
  `documents:` (`config_version` 46), on by default; OCR runs only on a document
  whose text layer is actually missing. `max_chunk_chars` bounds the derived part
  size however large the window is, so a 128K-window model is not handed ~55K
  tokens per call. See README → *Large Documents and Scanned PDFs* and FORK.md §25.
- **models:** `scripts/sync-ollama-models.py` now writes `context_window`
  alongside `num_ctx`. Only Ollama reads `num_ctx`; `context_window` is what the
  UI's context indicator and the cost-aware routing guard read, and without it
  that guard short-circuited on `None` for every local model — so a
  large-prompt subagent could be routed to a model whose window could not hold
  it.

- **voice:** **Dictation no longer sends your audio to Google.** The composer's
  microphone wrapped the browser `SpeechRecognition` API, whose implementation
  streams audio from the browser straight to Google (Chrome) or Apple (Safari) —
  bypassing the Gateway entirely, so self-hosting, auth and Tailscale never
  covered it. Voice input now runs in tiers: Chrome 139+'s on-device recognition
  first (no audio leaves the device, nothing to configure), then transcription by
  a service on your own machine, then the vendor cloud only if you opt in. With
  neither local tier available the button reports voice as **unavailable** rather
  than quietly falling back — `voice.allow_cloud_fallback` defaults to `false`,
  and so does `voice.stt.enabled`. Point `voice.stt.base_url` at anything
  speaking the OpenAI `/v1/audio/transcriptions` shape (faster-whisper-server,
  speaches, whisper.cpp, LocalAI) to enable the server tier; a `base_url` outside
  this machine or its private network — Tailscale's `100.64.0.0/10` counts as
  private — is warned about at startup and labelled in the composer. Note the
  microphone needs a secure context, so over Tailscale use the
  `https://<magicdns>.ts.net` address rather than the plain-HTTP tailnet IP.

- **cost:** **The chat's cost figure now covers everything the conversation
  spends, not just its answers.** Two LLM calls were being made per conversation
  and billed to nobody: the composer's **prompt polish** rewrite — which is
  `input_polish.enabled: true` out of the box, so it is the one you pay for
  without having turned anything on — and the per-turn **goal check** that runs
  while a goal is active. Neither becomes a run of its own, so neither reached
  the header's total; the number was simply lower than the money spent, with
  nothing on screen to say so. Both now appear as their own priced rows in the
  cost dropdown ("Prompt polish", "Goal check") beside the existing memory and
  suggestions counters, each billed at the rate of the model that actually
  served it — so pointing `input_polish.model_name` at a cheap model shows up as
  the saving it is. Like the other two, they are persisted in
  `aux_usage.sqlite3` and survive restarting the stack or the machine. No new
  config keys; nothing to turn on.
- **models:** **The sortable, grouped model picker is now on every screen that
  picks a model.** Sorting by name or price, grouping by provider, the search
  box and the coloured prices were only ever in the chat composer; Democracy
  setup, the follow-up-suggestions model, the subagent default in Settings, the
  agent generator and a custom agent's own settings each still showed a plain
  list in `config.yaml` order with the price as grey text. All five now use the
  same picker as the chat, and they share one saved preference — so a sort you
  choose in a conversation is already applied everywhere else. The default stays
  config order, so nothing moves until you opt in. The picker publishes a stable
  `data-slot="model-select"` so tests can find it without depending on whichever
  primitive it is built from.
- **media:** **Images and short video clips now generate on your own GPU, with no
  API key and nothing leaving the house.** A long-lived ComfyUI service (`make
  comfy-up`, published loopback-only on `127.0.0.1:8188`) backs five new tools —
  `generate_image`, `generate_video`, `list_media_models`, `refine_start` and
  `refine_verdict` — that run in the Gateway and write straight into the chat's
  outputs directory, so the result opens in the artifact panel on its own and the
  exact workflow that produced it is saved beside it as `<name>.workflow.json`.
  Models are read from the running ComfyUI itself, so the agent can only pick
  checkpoints you actually installed, and it needs none: a bare "make me a
  picture" uses `media.default_checkpoint`, or the first one ComfyUI reports.
  The new `image-refine` skill then lets the agent **look at what it made and try
  again** — three to six criteria frozen before the first attempt, one named
  change per round, and an iteration counter the *server* holds, so attempt five
  is refused rather than trusted to stop. Clips get evenly spaced stills and a
  contact-sheet PNG, because `view_image` cannot read an MP4. Sharing one card
  between a chat model and a diffusion model is handled by a GPU arbiter that
  evicts and restores inside the tool call, verifies residency from the services
  rather than from memory, and derives its exclusive/shared policy from
  `media.gpu.budget_gb` (default `auto`) — so a bigger card stops the swapping
  with no code change. **Off by default:** the `media:` config section ships
  configured (`config_version` 44) but the tool entries are commented out, since
  a fresh machine has neither ComfyUI nor a checkpoint. `make doctor` reports
  whether the service is reachable and whether VRAM is being held while nothing
  is generating.

- **chat:** **Democracy panels are now a setup page, keep running after the first
  answer, take files, and grade their panelists.** The launcher under *New chat*
  opens a page of its own (`/workspace/democracy/new`) instead of a popup, with
  room for the roster and the cost warning. The task now accepts **file
  attachments** alongside text — the organizer reads them once and shares them
  with the panel. Ask a **follow-up** and the whole panel runs again rather than
  leaving you with the organizer alone: each panelist is re-briefed with its own
  previous answers, what the review round argued about, and the last final
  answer, and you still get exactly one answer per question instead of a fan-out
  to reconcile. Finally, the organizer can **grade** each panelist — *Score out
  of 5* or a plain *yes/no*, chosen at setup — on what it contributed that turn,
  scoring the contribution rather than agreement with the conclusion, so a
  dissent that turned out to be right scores well and an echo of the majority
  does not. Leave grading off and answers end exactly where they did. The cost
  warning now says the charge is per question, because a standing panel bills
  again on every follow-up.

- **chat:** **Democracy — several models answer the same question, then decide
  together.** A new **Democracy** launcher under *New chat* asks how many
  panelists you want, which model organizes, which model fills each seat, and
  what the task is. The organizer gathers the facts **once** and hands every
  panelist the identical brief (five models each doing the same lookup costs five
  times as much and produces five slightly different datasets), the panelists
  answer independently and then review each other **anonymously**, and the
  organizer synthesizes — reporting the real split and naming dissenters instead
  of averaging them into "the panel concluded". Facts are deliberately taken as
  given and **not** re-verified by the panel. It is extremely token-heavy — up to
  N x 2 full model runs for N panelists, on top of the organizer's own work — so
  the setup dialog states the run count and estimates the panel's rates as a
  multiple of one ordinary answer, naming any unpriced local model that counts as
  $0, before you commit. Under the hood `task` gained a per-call `model=`
  argument that outranks both the per-thread subagent dropdown and the cost-aware
  routing policy, so a panel cannot silently collapse onto one model. Needs no
  config keys and works as soon as two models are configured; panelists run
  concurrently up to `subagent_runtime.max_running` (default 3, restart required
  to raise).

- **chat:** **A second chat no longer waits for the first one's answer.** Ask one
  conversation something slow, leave it, and prompt another one — both keep
  going. Leaving a chat used to cancel its run (the Gateway cancels on client
  disconnect unless the run says otherwise), and a chat you left went dark even
  when it survived. Now every run is submitted with `on_disconnect: "continue"`,
  and a chat you leave **while it is still answering** is kept as a keep-alive
  tab instead of being torn down: it goes on streaming in the background with a
  pulsing dot on its tab, and the completion notification fires for a chat that
  is merely off-screen, not only for a hidden window. Closing the browser no
  longer cancels a run either — it finishes on the server, which is what the
  run-finished push notification always assumed; **Stop** still cancels
  outright, and a spend cap still bounds a runaway run. Nothing to turn on. With a
  **local Ollama model** there is one more step: the daemon answers
  `OLLAMA_NUM_PARALLEL` requests per model at a time (1 by default) and queues
  the rest, so raise it on the daemon and set the new `ollama.num_parallel` in
  `config.yaml` to match — each slot allocates its own KV cache, and that value
  is what divides each model's synced `num_ctx` accordingly. `make doctor`
  reports how many chats can generate at once under **Local Models**. No
  `config_version` bump: the `ollama:` block is commented out in the example, so
  the config shape is unchanged.

- **agents:** **Agent creation and generation now work out of the box.**
  `config.example.yaml` ships `agents_api.enabled` and `agent_generation.enabled`
  set to `true`, so a fresh `make config` gets the Agents pages — create/edit an
  agent, and *Generate from history* — without hand-editing config. This matches
  the fork's local-trusted, loopback-only, passwordless posture, where the local
  user is the admin. `agents_api` still grants admin-equivalent write access to
  agent SOUL.md / config, so set it back to `false` before exposing the gateway on
  an untrusted network (which also hides generation). Only what a fresh install
  writes changes: the Pydantic defaults stay `false` so an absent section fails
  safe, and `config_upgrade.py` never overwrites a value an existing `config.yaml`
  already carries. No `config_version` bump — the change is a value, not the config
  shape.

- **agents:** **Tell the agent generator what you're after.** The
  *Generate from history* wizard gains an optional **What should this agent do?**
  box — a rough description of what to tune the agent for. It steers which parts of
  the selected work matter and shapes the draft, but it deliberately does **not**
  decide the verdict: a stated goal is still checked against your existing roster,
  and the flow can still tell you an agent already covers it. When it does, a new
  **Generate anyway** button overrides it, carrying the overlapping agent onto the
  draft as a note rather than hiding it. Drafts also gain a **Refine this draft**
  box — "make it more concise", "focus on the review side" — which revises the
  draft exactly as it stands in the form, hand edits included: only what you asked
  about changes, everything else survives verbatim, and the agent is not renamed.
  `POST /api/agent-generation/analyze` gains `goal`, `force_proposal`, and
  `revise_from`; the goal is capped by the new `agent_generation.max_goal_chars`
  (default 2000). `config_version` is now `42`: `config_upgrade.py` compares the
  config's nested shape, so even one new key needs the bump to reach an existing
  install.

- **agents:** **Generate a custom agent from work you have already done.** A new
  **Generate from history** button on `/workspace/agents` opens a wizard: pick the
  model to run the analysis, pick the past conversations and/or scheduled tasks the
  agent should be shaped around, and the model decides whether a new agent is
  warranted at all. Concluding that one is *not* — because the work is one-off, too
  varied, or already covered by an agent you have — is a first-class answer, and the
  covering agent is named; the prompt is biased that way on purpose, since a roster
  of near-duplicate agents is worse than no agent. When a gap is found you get an
  editable draft (name, description, full `SOUL.md`) and nothing is written until you
  press **Create agent**: `POST /api/agent-generation/analyze` is strictly read-only,
  so a hallucinated proposal cannot become an agent unattended. Transcripts are
  digested before they are sent — tool-result bodies dropped (the calling turn still
  names the tools), most-recent turns kept, per-message and per-source character caps
  — and every source is ownership-checked against the caller, so the analysis only
  ever reads your own history. The call is billed to the new `agent_generation`
  category on the Spend page. Off by default: enable
  `agent_generation.enabled` (it also needs `agents_api.enabled`), which is where the
  analysis model and the size caps are tuned. `config_version` is now `41`.

- **chat:** **Gaslight mode now covers answers, not just prompts.** The Edit
  button appears on the assistant's reply too: your text simply *becomes* what it
  said, in a new hidden version, and nothing is re-generated — whatever you send
  next is answered with those words standing in the history. Re-running the turn
  would have discarded the edit (the model's fresh reply replacing the words you
  just wrote), so an answer edit deliberately makes no run. `POST
  /api/threads/{id}/branches` gains an optional
  `replacement_assistant_message_id` + `replacement_assistant_text` pair, applied
  to the copied checkpoint messages *and* the seeded run events; the pair is
  all-or-nothing and the id must be one of the assistant messages the branch is
  taken from, so a half-specified or out-of-turn rewrite is refused rather than
  branching without the edit that was asked for. Only a turn's terminal assistant
  message is editable, and not while it is still streaming. See FORK.md §18.

- **chat:** The per-turn **Branch** button is replaced by an **Edit** button on
  the user message itself. Editing replays the conversation from that turn with
  the new wording and keeps the version you were reading, reachable through a
  `‹ 2/2 ›` switcher on the edited message. The alternative versions are hidden
  from the sidebar, the chats page, and the tab strip, so one conversation stays
  one entry however many times it is edited, and the entry reopens whichever
  version you last switched to. Editing the first message of a chat works too.
  Under the hood this is still the existing branch endpoint — the change is in
  how the result is presented. See FORK.md §18.

- **pricing:** The conversation cost is now rendered in **green**, so it reads
  as money rather than as another token counter, and a model on a live
  promotional/introductory rate shows **both** prices. The `pricing:` block
  gained optional `promo_input_per_million` / `promo_output_per_million` (plus a
  matching cache-hit rate); the token-usage endpoint returns `promo_total_cost`
  beside `total_cost`, and the header dropdown shows the green promo total —
  what the thread costs today — next to the red standard total it reverts to
  when the discount ends. Promo rates are strictly additive: cost is still
  *billed* against the standard rate, because a promo can lapse at any time and
  a silently-too-low estimate is worse than a slightly-high one. Both totals
  cover the whole thread, so an undiscounted model contributes its ordinary cost
  to each and the pair stays comparable. A half-specified, non-positive, or
  above-list "promo" is a config error and is dropped whole rather than
  partially honoured. The three currently-discounted bundled models (Claude
  Sonnet 5's intro window, MiniMax M3 and GLM-5.2 on OpenRouter) ship with the
  block, derived from the starred half of the same price-in-name pair.

- **models:** The composer's collapsed model button now keeps the price
  visible. It is capped at ~160-224px and the price sits mid-name, so the promo
  half was cut off; the trigger now drops the provider suffix (keeping the `(p)`
  privacy marker) and lets only the model name ellipsize. This also fixes a
  pre-existing layout bug behind it: the name span sits in a `flex-col
  items-start` container where its `flex-1` sizes height, not width, so it was
  `fit-content` — measured at 315px inside a 160px button — overflowing instead
  of truncating, with its `truncate` never firing.

- **models:** The model dropdown now colours each entry's price — green for what
  you pay, and on a discounted `($list → $promo*)` entry the list price in red
  beside the green promo, matching the cost overview. Purely presentational and
  total: a name whose price cannot be parsed renders verbatim.

- **chat tabs:** The keep-alive chat tab strip is now persisted **server-side
  per user** (`GET`/`PUT /api/settings/chat-tabs`, backed by
  `{base_dir}/users/{user_id}/ui_state.json`), with `localStorage` demoted to a
  first-paint cache. Tabs were "forgotten" after a machine restart because the
  browser store is scoped to one browser *and* one origin, so the set was lost
  to a site-data-on-exit clear, storage eviction for an insecure-origin site (a
  plain-HTTP LAN deployment), or reopening the app on a different origin than
  the one that pinned them (`localhost` vs. a LAN/Tailscale address). The
  provider still renders instantly from the cache, then reconciles: an
  unreachable gateway — the normal state right after a restart — keeps the
  cache instead of blanking the strip, and a server with no stored set adopts
  and seeds from the local one (the upgrade path for existing tabs). Writes are
  coalesced and flushed on teardown, and the local cache can no longer be
  blanked by an empty set the user did not produce.

### Changed

- **models:** **The model audit can now grow the roster, not just correct it.** Every
  automated check asked only about models already bundled, so a lab shipping a new
  flagship raised nothing — one pass found four labs a generation behind at once, all
  caught by eye. The weekly audit issue now also lists **newer models from labs the
  bundle already carries**: any non-variant OpenRouter slug published after the newest
  entry that lab has, three per lab, newest first. It proposes and never instructs —
  whether a model belongs is a judgement, and the audit now says how to make it:
  *critically acclaimed* means climbing OpenRouter's own rankings and trending boards,
  named and dated in the audit log, not a launch post and not a benchmark table. A
  candidate stops being reported 60 days after its release, so one you looked at and
  declined ages out instead of becoming a weekly issue nobody can close. A cloaked
  codename that tops the trending board (the `ox-alpha` shape) is a pointer to watch
  rather than an entry to add — bundling an alias breaks the same rule as `*-latest`.
  The rule that keeps an outgoing flagship beside its successor now applies to every
  lab rather than only to Claude.

### Fixed

- **cost:** **What a reply cost is now recorded when it runs, instead of being
  recomputed from today's config.** Every cost figure — the chat header, the
  per-step chart, the spend page, the console — was priced by looking each run's
  model up in the live `config.yaml` at read time, which made a historical number
  a statement about today's roster rather than about what the run cost. Editing a
  price rewrote every total that model ever appeared in, and a model that left
  the roster stopped resolving altogether: its runs contributed **nothing**, the
  conversation got *cheaper*, and the model was reported as unpriced as though
  the operator had forgotten to price it. Rolling entries forward is a routine
  outcome of the model audit, so that second case was expected to happen rather
  than unlikely. Runs now persist the per-model rates they were billed at
  (`runs.pricing_snapshot`, migration `0019`), taken from the config the run
  actually executed under, and the read path prefers them per model. Existing
  runs are not backfilled — they price from the live config exactly as before,
  so nothing about an existing install changes until its next turn. A snapshot
  never re-expires its own discount, a deployment that switched currency
  re-prices rather than summing two currencies into one total, and a snapshot
  cannot switch cost reporting back on where the operator has turned it off.
  Thread totals are now summed from the per-run buckets, which also makes the
  cost dropdown's stated relation (`sum(steps) + superseded turns = total`) an
  identity rather than two calculations that agree.

- **chat history:** **A long conversation no longer stops loading older messages
  after the server restarts.** Scrolling back is served by
  `GET /api/threads/{thread_id}/messages/page`, which reads the run-event store
  and nothing else. That store defaulted to `run_events.backend: memory` —
  process state — while the LangGraph checkpoint stayed durable on the default
  `database.backend: sqlite`. Restarting the Gateway therefore emptied the
  history feed but not the checkpoint: the conversation still opened and still
  rendered its most recent turns, then returned `has_more: false` and refused to
  page backwards, so the load-more sentinel never fired. Nothing was logged on
  either side, and on a chat long enough to have been compacted every turn before
  the compaction point simply disappeared from the UI. `run_events.backend` now
  defaults to `db`, which writes into the database `database:` already
  configures, so durability needs no extra setup; `database.backend: memory`
  still falls back to the in-memory store. `config.example.yaml` ships the new
  value (`config_version: 50`) and `make config-upgrade` migrates an existing
  `config.yaml` off `memory` — the one value the upgrade rewrites deliberately,
  anchored to the `run_events:` section so `database:` is untouched. `make doctor`
  reports the combination for installs that never run the upgrade. History
  already lost to earlier restarts cannot be recovered; the rows were never
  written.

- **embedded client:** **An abandoned `DeerFlowClient.stream()` now cleans up when it
  ends, not when the garbage collector gets round to it.** The wrapper that releases a
  turn's sandbox execution lease was left as a `for` loop's anonymous iterator, so it was
  finalized during frame teardown — after the turn's trace binding had already been torn
  down, and only at GC for a caller that drops the generator without closing it. A
  cancelled or abandoned turn therefore kept a sandbox reserved past the end of the
  stream, and the agent's own cleanup logs and callbacks correlated with no trace id at
  all. Neither raised. Holding the wrapper by name and closing it in the same frame runs
  both while the stream is still unwinding.

- **models:** **Model audit, 2026-09-02 — Anthropic verified against its own
  pages, and four bundled entries were wrong.** Anthropic's docs were reachable
  for the first time in three passes, so the Claude block was checked at tier 1
  rather than left alone: **Claude Fable 5 rolls forward to Fable 5.1**
  (`claude-fable-5-1`, direct and routed) under the *Fable keeps only the latest*
  rule, and its **cache-read rate is corrected from $1.00 to $0.25** — Fable 5.1
  caches at 0.025x base input, not the 0.1x every other Claude uses, so the old
  figure was well-formed and 4x too high. Three prices were corrected from
  corroborating sources: **Mistral Small** was still bundled as the
  `mistral-small-latest` **alias**, labelled "Small 3" at $0.10/$0.30 while
  serving **Small 4** — now pinned to `mistral-small-2603` at $0.15/$0.60, which
  doubles its output rate; **Qwen3.7 Plus** output $1.20 → **$1.60**; and
  **Gemini 3.5 Flash-Lite** output $1.20 → **$2.50**. Each understated real spend
  in every cost total. FORK.md gains the rule the first two of these share: a
  `*-latest` alias must never be bundled, because it moves while the entry's name
  and price stay put. All seven roster copies (marker blocks, `HOME_API_BUNDLES`,
  `PROVIDERS`, and the four prose ones no test reads) were updated together, and
  the pass — including what could *not* be verified and is owed to the next one —
  is recorded in `docs/model-audit-log.md`.
- **docs:** The setup wizard's Mistral provider description still listed an
  unversioned "Small" — the last of the seven places that describe the bundled
  roster to carry it, after the 2026-08-26 pass corrected the other six.
  `make setup` now prints **Mistral Large 3 + Medium 3.5 + Small 3**, matching the
  bundled `mistral-small-3` entry.

- **models:** **Three bundled models did not exist, and picking any of them
  failed at request time.** Each was a "cheaper sibling" whose id had been spelled
  out of the flagship's name instead of read off the lab's model list, so the
  entry looked right until a run failed:
  - `gpt-5.6-mini` — GPT-5.6 shipped as **Sol / Terra / Luna**, with no `-mini`
    member. Replaced by the two real tiers: **GPT-5.6 Terra** (`gpt-5.6-terra`,
    `$2/12`) and **GPT-5.6 Luna** (`gpt-5.6-luna`, `$0.20/1.20`).
  - `grok-4.5-fast` — xAI's model list has no `-fast` text model, and `grok-4.5`
    costs the same as the flagship. Replaced by **Grok 4.3** (`grok-4.3`,
    `$1.25/2.50`, 1M context), which is xAI's actual cheaper tier.
  - `glm-5.2-air` — z.ai ships Air only in the 4.5 generation. Replaced by
    **GLM-4.5 Air** (`glm-4.5-air`); the `$0.20/1.10` price was already
    GLM-4.5 Air's, so only the id and the name were wrong.

  The bundle is now **41** priced models. An existing `config.yaml` keeps
  whatever it already has — `make config-upgrade` does not rewrite entries you
  already have — so delete the three old entries and re-copy the OpenAI, xAI and
  z.ai blocks from `config.example.yaml`.

- **pricing:** **DeepSeek runs were being costed at a third of their real input
  price and under a quarter of their real output price.** DeepSeek moved to
  peak/off-peak billing on 2026-08-16 and raised its rates; the bundle still
  carried the old flat ones. **DeepSeek V4 Pro** goes
  from `$0.44/0.87` to `$1.32/3.96` and **V4 Flash** from `$0.14/0.28` to
  `$0.44/1.32` — the **peak** rate in both cases, because `price:` is a single
  flat pair and under-stating cost is what silently stops a `spend_budget:` cap
  from firing. Off-peak (every hour outside 01:00–04:00 and 06:00–10:00 UTC
  Mon–Fri, weekends included) is exactly half; the figure is in a comment beside
  each entry if you want to halve them. The OpenRouter copy of DeepSeek V4 Pro is
  unchanged — it bills at OpenRouter's rate, not DeepSeek's.

- **pricing:** **Kimi K2.6** is `$0.95/4.00`, not `$1.00/3.00` — its output rate
  had been under-reported by 25%.

- **docs:** Four places that only *describe* the bundled roster had drifted
  behind it: `config.example.yaml`'s `QUICK START` comment still advertised
  Grok 4.5, Qwen3.7 Max and GLM-5.2 three roster rolls after they were replaced,
  the setup wizard's OpenAI provider description named the removed GPT-5.6 Mini,
  and two lineup tables listed an unversioned "Mistral Medium / Small". All now
  match the shipped blocks.

- **pricing:** **Claude Sonnet 5 was about to get 50% more expensive on paper,
  against a price nobody is charged.** It shipped priced at a `$3/15` standard
  rate with a `$2/10` introductory discount set to expire on 2026-08-31 — the
  window Anthropic announced at launch. Anthropic has since made the `$2/10`
  rate permanent and cancelled the 1 September increase, so on that date every
  cost figure for a Sonnet 5 thread — the chat header, the cost overview, and
  anything a spend cap is measured against — would have silently jumped to the
  higher rate while the real bill stayed flat. Sonnet 5 is now priced at a plain
  `$2/10` standard rate (cache reads `$0.20`) with no discount attached. Nothing
  to configure; an existing `config.yaml` written before this change keeps the
  old figures, and `make config-upgrade` does not rewrite a value you already
  have — re-copy the Anthropic block, or edit the two numbers by hand.

- **pricing:** A conversation on some OpenAI-compatible providers (OpenRouter
  among them) showed no cost at all, and the note meant to explain it named a
  model that does not exist: *"no price is configured for
  `deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro`"*. The id was **assembled**,
  not reported. LangChain merges a streamed response chunk by chunk with
  `merge_dicts`, which *concatenates* two equal strings under the same
  `response_metadata` key; `langchain_openai` writes `model_name` on every chunk
  carrying a `finish_reason`, and these providers send more than one such chunk
  — so the assembled message named the model twice over (its `finish_reason`
  reads `stopstop` for the same reason). That doubled id is what
  `token_usage_by_model` is keyed on, so it matched no configured model, every
  token counted as unpriced, and the header fell back to `—`. A provider-reported
  id is now collapsed to one copy where it is read (`deerflow.model_ids`), which
  also keeps the spend cap and the spend report honest — an unrecognized model
  prices at zero, so a cap could never fire on the affected provider. The
  collapse is deliberately narrow: only a whole id repeated end to end, never a
  mismatched pair, because guessing there would bill one model at another's
  rate. Threads that already ran keep working with no migration — the price
  lookup and the per-model aggregations normalize the stored key on read, so an
  old doubled bucket merges into the model it names instead of showing up as a
  second, unpriced row.

- **pricing:** The cost estimate stayed on `—` for anyone who had run DeerFlow
  before the prices shipped. Adding `pricing:` blocks to
  `config.example.yaml` only ever reaches a **brand-new** `config.yaml`:
  `sync-api-key-models.py` skips a provider block whose models are already
  active (correct — it must not duplicate them), and `config_upgrade.py`'s
  `merge_missing` is dict-based, so it cannot add a key inside an existing list
  entry. An upgraded install therefore kept its models active and unpriced
  forever, no matter how many times the example was corrected — reproduced with
  13 active models and 0 pricing blocks, where both launch-path regenerators
  reported "no changes". The price was never actually missing from those
  configs: it is in `display_name` (`Grok 4.5 ($2/6) (OpenRouter) (p)`), which
  is what the shipped blocks are generated from. Cost estimation now derives a
  price from that pair when no block is configured, so existing installs price
  correctly with no migration and hand-added models following the convention
  are priced for free. An explicit block still wins, and a malformed explicit
  block is deliberately *not* papered over with the name's price. `make doctor`
  gained a `model pricing` check that names the `—` symptom when nothing
  configured can be priced.

- **pricing:** Only the six direct-Anthropic models shipped with a machine-readable
  `pricing:` block, so the other **34** bundled paid models were unpriceable and a
  conversation run on any of them reported no cost — the chat header rendered `—`
  even though tokens were counted. Every bundled paid model now carries a pricing
  block on both the auto-config and `make setup` paths (`providers.py` derives it
  from the same price-in-name pair the display uses, so the two synced sources
  cannot drift), and `TestBundledModelPricing` fails if a bundled model ever loses
  its price again. `make setup` previously wrote *no* pricing at all, even for
  Anthropic; it now matches the config path exactly.

- **pricing:** A missing price no longer renders as an unexplained dash. The
  token-usage endpoint reports `unpriced_models` — models that spent tokens with
  no configured price — and the header names them, distinguishing "add a pricing
  block for this model" from "the cost feature is broken". When only some models
  are priced it says so, rather than quietly showing a total that understates the
  real spend.

- **pricing:** The conversation cost estimate always showed `—` and never
  reported a spend. `token_usage_by_model` buckets are keyed by the
  *provider-reported* model id rather than the `config.yaml` id — LangChain
  records the API-resolved model, so Anthropic returns the dated snapshot its
  alias resolved to (`claude-opus-5` → `claude-opus-5-20260115`), OpenAI
  appends a dashed date, OpenRouter appends `:variant` tags, and routed slugs
  carry a `vendor/` prefix. `lookup_pricing` matched the exact string only, so
  every bucket looked unpriced, every per-model `cost` was null, and
  `total_cost` stayed null while `currency` was set. Ids are now resolved
  through an ordered set of normalized forms tried by exact lookup (never a
  prefix scan), most-specific-first so a configured OpenRouter copy is still
  billed at its own routed price. Fixes the ops console, the per-thread
  endpoint, and the memory/suggestions aux counters at once, and holds across
  mid-conversation model switches.

- **docker build:** The gateway image build failed on a stock install/update
  with `extra 'camoufox' is not defined`. `config.example.yaml` ships
  `web_fetch` with `backend: camoufox`, so `scripts/detect_uv_extras.py`
  auto-detects `UV_EXTRAS=camoufox` and the Dockerfile runs
  `uv sync --extra camoufox` — but the backend (root workspace) package only
  declared `postgres`/`redis`/`browser`/… extras, not `camoufox` (it lived only
  in the harness sub-package). Added the forwarding extra
  `camoufox = ["deerflow-harness[camoufox]"]` so the build resolves. A new
  regression test pins that *every* extra `detect_uv_extras.py` can emit is
  declared in `backend/pyproject.toml`, closing the class of drift rather than
  just this instance.

- **skills:** Reconcile the fork's static skill tool-policy exemption with
  upstream's dynamic `SkillToolPolicyMiddleware` after the upstream sync. The
  fork's `allowed_tool_names_for_skills` treats an empty / framework-only
  `allowed-tools` declaration as "no restriction" (so merely *enabling* a
  framework skill such as `skill-reviewer` never disarms the agent), but the
  lead agent's dynamic middleware — which only sees *actively* invoked skills
  (slash / `skill_context`) — needs an explicit empty declaration to restrict
  to framework tools. That collision left `task` (and other non-framework
  tools) leaking through the active-skill policy. The framework-only exemption
  is now opt-in (`exempt_framework_only`, default on for the static subagent
  path); the middleware opts out, restoring upstream's active-skill semantics.
  Fixes 4 `backend-unit-tests` failures introduced by the merge
  (`test_skill_tool_policy_middleware.py`, `test_lead_agent_model_resolution.py`).

### Changed

- **sandbox:** A debug port opened with `sandbox.expose_ports` no longer lands on
  **every** host interface when the sandbox host is non-loopback (the
  Docker-outside-of-Docker case, `DEER_FLOW_SANDBOX_HOST=host.docker.internal`).
  That path used to publish `0.0.0.0:<port>`, which put the program under test —
  and, on the API port, an **unauthenticated shell endpoint** — in front of
  anything that could reach the machine. Both now bind the address the sandbox
  host actually resolves to, so the port is still reachable exactly where the
  sandbox itself is, and nowhere else. Loopback runs are unaffected (they already
  bound `127.0.0.1`). Operators who genuinely need the old behavior — a remote
  client talking to the sandbox API directly — restore it with
  `DEER_FLOW_SANDBOX_BIND_HOST=0.0.0.0`, which should be paired with an external
  firewall.

- **docs:** The model-and-pricing audit now states **where a price may come
  from**, as three ordered tiers instead of one absolute rule. *Verified* (the
  provider's own page) stays the standard; when that page cannot be reached, a
  figure that **two or more independent sources state identically** is now an
  accepted outcome rather than a rule being bent — provided the sources are
  genuinely independent, agree exactly on both numbers (a disagreement is a stop,
  never an average), carry no discount, and are recorded as corroborated in the
  audit log so the next pass is directed at them. Failing both, the entry is left
  alone; a price is still never carried from memory. Shipping a lab's flagship
  with no `price:` block is the failure this permits you to avoid, because an
  unpriced model contributes nothing to every cost total. The weekly job's report
  says the same thing and still never commits a price. See FORK.md, *Where a
  price may come from*.

- **docs:** The README's fork feature list gained the two features it was
  missing: the **price graph** in the cost dropdown and **gaslight mode** (the
  per-message edit that replays the conversation into a hidden version).
  "Gaslight mode" is the documented name of the behaviour in the README and
  FORK.md §18; the per-message button is still labelled **Edit** in the UI.

- **config:** `config_version` 39 → 40. Upstream's hybrid fact-eviction work
  added ten new fields under `memory.backend_config`
  (`fact_eviction_policy`, the eviction weights and half-lives, the correction
  reserve, and the audit cap) without moving its own `config_version`, which
  sits behind this fork's. `config_upgrade.py` gates delivery on that number, so
  at an unchanged version an existing `config.yaml` would have stayed
  permanently without the new section — the documented sync trap. Run
  `make config-upgrade` to receive the fields; hand-edited values are preserved
  and a `.bak` is written, but note the merge path rewrites through `yaml.dump`
  and drops comments, so keep the `.bak` until you have re-read the result.

- **suggestions:** Follow-up question suggestions now default **off** to avoid
  the extra per-turn LLM call (and its cost). A new **Settings → Suggestions**
  page adds a per-browser toggle plus a model dropdown to choose which model
  generates them — the first option, "Follow workflow selection", reuses the
  thread's current model; any configured model can be picked instead (e.g. a
  cheap one) and is sent as the suggestions request's `model_name`. The
  server-side `suggestions.enabled` master switch is unchanged and still gates
  generation; the toggle shows a hint when the server has it disabled. Client
  preference stored in `localStorage` (`deerflow.local-settings`).

### Added

- **deploy / docs:** New `make up-start` (`./scripts/deploy.sh start`) restarts
  the production Docker stack from pre-built images so a config-only change
  (e.g. editing `BIND_HOST` / `PORT` in `.env`) applies without the slow image
  rebuild the default `make up` performs; the `deploy.sh` banner and README now
  point beginners at it. Documented the `BIND_HOST` + Tailscale gotcha in
  `.env.example` and the README security section: the port is published as
  `${BIND_HOST}:${PORT}:2026`, so `BIND_HOST` is a single bind interface, not an
  allowlist — binding only the Tailscale IP (`100.x`) drops loopback and breaks
  `http://localhost:2026`; use `BIND_HOST=0.0.0.0` to reach it from both
  localhost and Tailscale.

- **auto-update:** A daily auto-update loop for the two components this repo
  installs itself — the Camoufox browser binaries and the bundled SearXNG
  `:latest` Docker image — neither of which self-updated after first install
  (`ensure_camoufox.py` only fetched when absent; Docker only pulls `:latest`
  when missing locally). `scripts/update_camoufox_searxng.py` (`make
  auto-update`) force-runs the version-aware `camoufox fetch` and, via a new
  `scripts/searxng.sh update` subcommand, `docker compose pull`s the SearXNG
  image and recreates the container only when it is running. It only touches
  the repo's own `deer-flow-searxng` container and is skipped for a
  foreign-configured instance. It runs automatically two ways: throttled in the
  background from `scripts/serve.sh` on every local launch (`--if-stale 24`,
  opt out with `DEER_FLOW_AUTO_UPDATE=0`), and via a `systemd --user` timer
  installed by `make auto-update-install` (`scripts/install_auto_update.py`)
  that fires both **daily** (`OnCalendar=daily`) **and on boot**
  (`OnBootSec=2min`), so a machine powered off at the daily slot still refreshes
  on startup; where systemd `--user` is absent it prints the equivalent daily +
  `@reboot` cron lines instead. Idempotent and best-effort — an up-to-date
  component is a no-op and failures are logged, not raised. Tests:
  `backend/tests/test_update_camoufox_searxng.py`,
  `test_install_auto_update.py`, `test_searxng_update_script.py`.
- **models:** API-key model auto-config. A new `scripts/sync-api-key-models.py`
  runs on every launch path (right after the Ollama sync in `scripts/serve.sh`,
  `scripts/docker.sh`, `scripts/deploy.sh`), reads the provider keys in your
  `.env`, and uncomments the matching cloud-model block in `config.yaml` so the
  right models are enabled on first start with no manual editing:
  `ANTHROPIC_API_KEY` → Claude Fable 5 / Opus 4.8 / Sonnet 5 / Haiku 4.5
  (direct Anthropic API); `OPENROUTER_API_KEY` → Claude Fable 5 + Grok 4.5 /
  GPT-5.5 / MiniMax M3 / Qwen3.7 Max / Gemini 3.5 Flash / DeepSeek V4 Pro /
  GLM-4.5 / Nemotron 3 Ultra (via OpenRouter). The script is bounded to the
  `# === BEGIN/END auto-model-config: <provider> ===` markers shipped in
  `config.example.yaml`: it only ever uncomments (never re-comments), skips a
  block whose models are already active (so `make setup` / hand-edits are never
  duplicated), no-ops when the key is a placeholder / missing or when the
  markers are absent, and refuses to run on a duplicate-key config.
  `make setup` enables the same sets interactively
  (`scripts/wizard/providers.py` is the shared source of truth). Tests:
  `backend/tests/test_sync_api_key_models.py`.

- **ollama:** VRAM-aware context sizing for auto-populated Ollama models. Set
  a GPU memory budget (`ollama.vram_gb` in `config.yaml` — `make setup` now
  asks for it when an Ollama provider is selected, auto-detecting via
  `nvidia-smi` / `rocm-smi` / Apple unified memory) and
  `scripts/sync-ollama-models.py` replaces its flat 32768 `num_ctx` cap with a
  per-model estimate: the largest window whose KV cache fits next to that
  model's weights, computed from the attention geometry in `/api/show` and the
  weights size in `/api/tags` (floored to 2048-token steps, never below 4096;
  an explicit `--num-ctx-cap` still applies as a hard ceiling, and models
  whose geometry can't be read keep the flat-cap behavior).
  `ollama.kv_cache_type: q8_0` sizes for a quantized KV cache — roughly double
  the affordable window — and the wizard prints the matching server-side
  setting (`OLLAMA_KV_CACHE_TYPE=q8_0`), since that env var is Ollama's to
  set, not DeerFlow's; sizing defaults to f16 unless opted in. Without
  `ollama.vram_gb`, nothing changes.

- **sandbox:** Host-run Ollama is now reachable from inside the AIO sandbox
  out of the box. Both the external sandbox container
  (`docker/docker-compose.sandbox.yml`) and the per-conversation containers
  created by `AioSandboxProvider` map `host.docker.internal` to the Docker
  host gateway (Linux daemons don't provide the alias automatically) and
  advertise `OLLAMA_HOST=http://host.docker.internal:11434` in the container
  environment, so agent-run Ollama clients target the host daemon instead of
  the container's own loopback (override with `DEER_FLOW_SANDBOX_OLLAMA_HOST`
  in external mode or an `OLLAMA_HOST` entry in `sandbox.environment`).
  Because a loopback-bound host Ollama — its default — still refuses
  bridge-gateway connections, the sandbox preflight and the Docker launch
  paths (`sync-ollama-models.py --container`) now detect that case and print
  the exact fix (`OLLAMA_HOST=0.0.0.0`) instead of leaving containers to fail
  with "connection refused". Advisory only: nothing fails, detection stays
  quiet when reachability can't be determined, and Docker Desktop (which
  proxies host loopback) is exempt.

- **sandbox:** Make the containerized AIO sandbox a first-class, out-of-the-box
  mode with secure private-GitHub-repo access. When `config.yaml` selects
  `AioSandboxProvider`, `make dev` now runs a preflight
  (`scripts/sandbox-preflight.sh`): it verifies Docker (or Apple Container) is
  usable, pulls the sandbox image on first run, and prints actionable errors
  with a `LocalSandboxProvider` fallback hint; `make check` reports Docker as
  an optional dependency. Each freshly created sandbox container gets a git
  credential helper that resolves `GITHUB_TOKEN` from the container
  environment (forwarded via `sandbox.environment` — see the commented AIO
  block in `config.example.yaml` and the new `.env.example` guidance on
  fine-grained, Contents-only PATs), so the agent can
  `git clone https://github.com/owner/repo.git` for private repos with the
  token never appearing in clone URLs, tool output, logs, or `.git/config`.
  Without a token, public repos keep working and private clones fail fast
  with a helpful hint (`GIT_TERMINAL_PROMPT=0` is defaulted in the container
  env). The default sandbox remains `LocalSandboxProvider`, unchanged.

- **tools:** Startup scripts now auto-provision SearXNG for `web_search`:
  `make up`, `make docker-start`, and host-run `make dev` / `make start` run
  `scripts/detect_searxng.py` before starting services. An existing SearXNG
  instance on the machine (ports `8088`/`8080`, or `DEER_FLOW_SEARXNG_BASE_URL`)
  is reused when it answers the JSON search API — Docker contexts additionally
  verify the instance is reachable from containers (bridge gateway probe, with
  a Docker Desktop loopback-proxy allowance) — otherwise the bundled container
  is started automatically. Detection is skipped entirely when `config.yaml`
  doesn't use the SearXNG provider. `make searxng` now shares the `deer-flow`
  compose project with `make up` so the standalone container and the production
  stack no longer conflict (if you ran the old target before, remove the stale
  container once with `docker rm -f deer-flow-searxng`).

- **tools:** Bundle a self-hosted SearXNG instance as the default `web_search`
  backend. The Docker stacks start a `deer-flow-searxng` service (in-network
  `http://searxng:8080`, loopback-only host port `8088`); host-run dev uses
  `make searxng` / `make searxng-stop`. The SearXNG provider now honours a
  `DEER_FLOW_SEARXNG_BASE_URL` env override so one `config.yaml` works in both
  environments, the setup wizard and `make doctor` know the provider, and
  DuckDuckGo remains available as the zero-dependency fallback in
  `config.example.yaml`.

### Fixed

- **docker:** `make up` and `make docker-start` never actually started the
  bundled `deer-flow-searxng` service — both scripts pass an explicit service
  list to `docker compose up` and it omitted `searxng`, leaving the Gateway
  pointing at a dead `http://searxng:8080` and `web_search` failing on every
  call. The service is now included whenever the bundled instance is the
  resolved provider.

- **docker:** the compose files declared `env_file: ../.env` and
  `../frontend/.env` as required, so any compose invocation on a clone without
  those (gitignored) files failed with "env file not found"; both are now
  marked optional (`required: false`), matching how `deploy.sh` already treats
  `.env`. Relatedly, `make searxng` could not even parse the compose file when
  the `DEER_FLOW_*` interpolation variables were unset (empty bind-mount
  specs); it now runs through `scripts/searxng.sh`, which supplies parse-only
  defaults and works from a fresh clone.
This section accumulates work toward the **2.1.0** milestone
([milestone 2](https://github.com/bytedance/deer-flow/milestone/2)).

### ⚠ Breaking changes

- **gateway:** Request trace ids are now issued unconditionally, and every
  Gateway HTTP response carries an `X-Trace-Id` header. Previously both were
  gated behind `logging.enhance.enabled`, which now controls **log output
  only** — whether records carry a `trace_id` field, and in which format. The
  header cannot be turned off; installations running the default
  `enabled: false` will start seeing it after upgrading. Scheduled tasks, MCP
  task notification runs, IM channel messages, and the embedded
  `DeerFlowClient` bind an id per unit of work, so the id also reaches the run
  record, the checkpoint metadata, and Langfuse traces that previously had
  none. A `deerflow_trace_id` supplied in a run request's `metadata` or
  `config.context` is now ignored and overwritten so the response header, the
  logs, and the persisted run cannot disagree — send the `X-Trace-Id` request
  header to pin a correlation id across services. `logging` remains
  restart-required. No config keys were added or removed. ([#5119])
- **skills:** Sandboxes now reserve `/mnt/skills` for managed enabled-only
  projections. `DEER_FLOW_HOST_SKILLS_PATH` and `SKILLS_HOST_PATH` are no longer
  used; Docker/AIO and hostPath deployments derive projection paths from
  `DEER_FLOW_HOST_BASE_DIR`. E2B operator mounts targeting `/mnt/skills` or any
  child path are skipped with a warning so they cannot shadow the managed
  projection; move extra E2B content to a different container path. User
  projections re-read global enable state from disk so toggles propagate across
  Gateway workers on the next sandbox acquire. Existing E2B sandboxes retain
  their creation-time snapshot until they are recreated. PVC-backed provisioner
  deployments still mount the operator-supplied PVC snapshot directly, so
  disabled-skill filesystem isolation does not apply in PVC mode until dynamic
  PVC materialization is implemented. ([#4178])
- **sandbox:** E2B now enforces `sandbox.replicas` as a process-local capacity
  limit. The default `wait` policy waits for `acquire_timeout`, then fails the
  agent turn. DeerFlow does not retry the turn automatically. Use `burst` with
  `burst_limit` to permit bounded extra VMs. The `reject` policy can remove one
  warm VM before it returns a capacity error. ([#4391])
- **skills:** A directory containing `SKILL.md` is now a runtime package
  boundary. Nested `SKILL.md` files inside that package are supporting data and
  are no longer registered as independent skills; unusual custom layouts must
  move independently loadable skills under a namespace directory without its
  own `SKILL.md`. ([#4098])
- **memory:** The memory system is now pluggable (`memory.manager_class` selects
  a backend; default `deermem` is self-contained). DeerMem-private settings moved
  from the top level of `memory:` into `memory.backend_config`, and the
  `/memory/config` response (and `client.get_memory_config()`) changed shape.
  ([#4122])
- **memory:** `/memory/config` and `client.get_memory_config()` no longer return
  flat DeerMem fields (`storage_path`, `max_facts`, `debounce_seconds`,
  `token_counting`, `guaranteed_*`, `staleness_*`, ...). They return
  `{enabled, mode, injection_enabled, manager_class, backend_config}` where
  `backend_config` is an opaque dict the active backend self-interprets. Memory
  *data* responses (`/memory`, `/memory/status` data) are unchanged. External
  API/SDK clients reading the old flat fields must read `backend_config` instead.
  ([#4122])
- **memory:** Custom `memory.storage_class` moved: the old default path
  `deerflow.agents.memory.storage.FileMemoryStorage` no longer exists (now
  `deerflow.agents.memory.backends.deermem.deermem.core.storage.FileMemoryStorage`).
  Custom `MemoryStorage` subclasses must accept `config` in `__init__` (was
  no-arg). A broken/old `storage_class` logs an error and falls back to
  `FileMemoryStorage` (won't crash) -- update the path + signature to restore it.
  ([#4122])
- **memory:** `storage_path` semantics changed from a FILE path to a root
  DIRECTORY. Pre-abstraction, an absolute `storage_path` was the shared memory
  file (opting out of per-user isolation) and a relative value was the global
  file under the data base_dir. Now `storage_path` (absolute or relative) is the
  root directory; per-user memory lives at `{storage_path}/users/{uid}/memory.json`.
  An upgrade keeping the old default `storage_path: memory.json` (a relative file
  name) would orphan per-user memory or hit `NotADirectoryError` on save, so the
  legacy migration **drops file-style `storage_path` values (ending in `.json`)
  with a warning** and the factory **raises** if `storage_path` resolves to an
  existing file. Set `memory.backend_config.storage_path` to a directory for a
  custom root. ([#4122])
- **memory:** `memory.mode: tool` with a backend that does not implement
  `search()` now fails fast at Gateway startup with a `ValueError` from the
  `MemoryManager` invariant, instead of starting successfully and silently
  returning empty results on every `memory_search` call. Both shipping backends
  implement `search()` (DeerMem retrieves; `noop` returns `[]`), so this only
  affects a custom backend that onboards without overriding `search()`. It is
  intentional -- silent empties are worse than a loud startup error. Fix: switch
  to `mode: middleware` or override `search()` (and set `supports_search=True`).
  ([#4324])
- **config:** `database.checkpoint_delta_snapshot_frequency` moved to
  `database.checkpoint_delta.snapshot_frequency` and its default changed from
  `1000` to `10`. A legacy top-level value is still honored with a deprecation
  warning and mapped onto the nested key (an explicitly set nested key wins).
  Deployments that relied on the old default now snapshot 100x more often in
  delta mode -- set `database.checkpoint_delta.snapshot_frequency: 1000`
  explicitly to keep the previous cadence. ([#4516])
- **docker:** The published entry port now binds to loopback (`127.0.0.1`) by
  default in both compose files, matching the documented local-trust deployment
  model. Deployments that relied on the old `0.0.0.0` binding must set
  `BIND_HOST` to expose the stack on other interfaces. ([#4618])

### Added

#### Authentication
- **auth:** Personal access tokens (PAT) for programmatic API access:
  `POST/GET/DELETE /api/v1/auth/pats` manage tokens (shown once, stored as
  SHA-256 digests); a default-deny route policy admits only the thread/run
  lifecycle routes, narrowed further by the token's `threads`/`runs` scopes,
  and any request dimension that carries cancel capability (`?action=`,
  `multitask_strategy`) additionally requires `runs:cancel`. ([#5041])

#### Agents & runtime

- **middleware:** New `TokenBudgetMiddleware` enforces a per-run token budget,
  shared additively across the lead agent and subagents. ([#3412])
- **middleware:** Structured tool-result metadata and a tool-progress state
  machine give the runtime first-class visibility into multi-step tool flows.
  ([#3601])
- **context:** Record the effective memory identity per run and persist durable
  context (system messages, memory, and tool state) across summarization,
  emitting it as structured runtime metadata so compaction no longer drops it.
  ([#3556], [#3887], [#3906])
- **runtime:** Goal continuations let a run resume toward a goal across multiple
  agent turns, with `continuation_count` tracked and capped. ([#3858])
- **subagents:** A system-maintained delegation ledger prevents redundant
  re-delegation of an in-flight task, and a total delegation cap bounds fan-out
  per run. ([#3877], [#4115])
- **subagents:** Persist and display subagent step history in the thread.
  ([#3845])
- **tools:** Structured synopses replace raw oversized tool output in previews.
  ([#3377])
- **files:** Deterministic read-before-write version gate for file tools
  prevents clobbering concurrent edits. ([#3912])
- **gateway:** Cache-aware cost accounting attributes token costs to cached vs.
  uncached paths; a Redis stream bridge enables distributed event streaming; and
  manual context compaction is exposed to the user. ([#3920], [#3191], [#3969])
- **gateway:** The stream-bridge heartbeat interval is configurable via
  `stream_bridge.heartbeat_interval_seconds` (default 15s), so deployments
  behind aggressive proxy idle timeouts can tune SSE, `/wait`, and internal
  subscribers together. ([#5017])
- **runtime:** Dual-mode checkpoint storage with LangGraph `DeltaChannel` cuts
  thread storage from O(N²) to near-linear for long research/coding runs.
  ([#4292])
- **runtime:** Delta-mode checkpoint history cache (memory/redis) with O(1)
  incremental composition, configured via `database.checkpoint_cache`. ([#4638])
- **agent:** Config-declared lead-agent middlewares let deployments add custom
  `AgentMiddleware` classes without patching the runtime chain. ([#3964])
- **agents:** Per-agent model and generation settings (`temperature`,
  `max_tokens`, `thinking_enabled`, `reasoning_effort`) override the shared
  model profile. ([#4347])
- **runtime:** Record terminal artifact-delivery receipts so runs expected to
  `present_files` no longer report success when delivery fails. ([#4365])
- **uploads:** Lazy-load historical files via a `list_uploaded_files` tool
  instead of injecting the full manifest. ([#4174])
- **scheduler:** `scheduler.recursion_limit` in `config.yaml` sets the LangGraph
  super-step cap for scheduled runs (default 1000, matching the web UI's
  interactive budget, clamped by `max_recursion_limit`). ([#4848])
- **runtime:** Every tool call now carries a runtime-stamped, tamper-evident
  tool receipt, and a bounded receipt ledger is injected into the model
  context so agents can cite execution evidence in their reports. Enabled
  by default via the new `verification` config section. ([#4659])
- **subagents:** Subagent delegations are now verifiable, layering RFC #4651:
  every subagent's report contract requires citing tool receipts (e.g.
  `[r3 write_file]`) and attaching a verifiable handle to each deliverable,
  the lead agent cross-checks those citations against the subagent's actual
  execution record, and `acceptance_criteria` on a `task` delegation are
  checked deterministically parent-side (file existence/non-emptiness,
  recorded test-command exit status) with anything undecidable reported
  UNVERIFIED instead of silently passed. ([#5076], [#5090], [#5109])
- **clarification:** Human-input (clarification) cards support structured
  form fields, so an agent can request exactly the input it needs instead
  of free text only. ([#4406])
- **subagents:** Built-in subagents now receive the current-date context
  anchor, so delegated tasks involving relative dates behave like tasks the
  lead agent handles directly. ([#4797])
- **subagents:** A Settings page manages a deployment-level Subagent catalog
  (admin-managed worker definitions alongside built-in and `config.yaml`
  ones), and Custom Agents can restrict delegation to an explicit worker
  allowlist enforced at both prompt and execution time. ([#4887])
- **subagents:** Subagent concurrency is now governed by one process-wide
  capacity controller, and an opt-in `batch_task` tool runs large
  collections of independent items as durable, resumable SQL-backed batches
  with leases, bounded retries, pause/resume/cancel, and a chat panel for
  tracking progress. ([#4998])

#### Memory

- **memory:** Memory consolidation synthesizes fragmented facts, and a staleness
  review prunes silently-outdated facts using LLM-assigned per-fact
  `expected_valid_days` / `staleFactsToExtend`. ([#3996], [#3860], [#4143])
- **memory:** Guaranteed injection of correction facts (with graceful fallback)
  so user corrections always reach the model. ([#3592])
- **memory:** Slim the pluggable `MemoryManager` interface for backend
  onboarding - new backends no longer implement unused abstract methods, and
  DeerMem-specific hook injection moves out of the shared factory. ([#4326])
- **memory:** Incremental agent-scoped Markdown fact storage isolates per-agent
  facts and updates a single fact without rewriting or reindexing the whole
  collection. ([#4279])
- **memory:** Memory message processing adds a conversation watermark,
  trivial-turn filtering, and a durable queue so extraction no longer re-feeds
  the full conversation every turn. ([#4447])
- **memory:** A built-in FTS5/BM25 retrieval adapter provides full-text
  search over stored memories without an external retrieval service.
  ([#4360])
- **memory:** New pluggable memory backends: OpenViking and mem0 over HTTP,
  plus Honcho as a user-model memory provider. ([#4509], [#4528], [#4730])
- **memory:** A hybrid fact eviction policy blends multiple signals when
  deciding which stored facts to drop as memory fills. ([#4789])

#### Skills

- **skills:** Native SkillScan (phase 1) statically analyzes skill packages at
  load, and `describe_skill` enables deferred discovery so the model fetches a
  skill's schema on demand instead of loading all skills up front. ([#3033],
  [#3775])
- **skills:** Per-user custom skill isolation with sandbox mounting. ([#3889])
- **skills:** The skill list reopens after a skill is selected, so several
  skills can be attached in a row. ([#4639])
- **skills:** Install local `.skill` archives directly from the Skills
  settings page, reusing the existing per-user installer and security scan.
  ([#5039])

#### Models & integrations

- **community:** New web search/fetch engines - GroundRoute, Crawl4AI
  (`web_fetch`), and a fastCRW provider - plus a Browserless `web_capture`
  screenshot tool and Brave `image_search`. ([#3675], [#3821], [#3585], [#3881],
  [#3866])
- **mcp:** Per-server `tool_call_timeout` for MCP tool calls, and routing hints
  that guide the model to the right server. ([#3843], [#4004])
- **mcp:** Add an official OpenViking `/mcp` example that exposes the native
  tool set through DeerFlow's generic MCP client. ([#4745])
- **community:** Agentic browser control as a first-class thread capability -
  Playwright-backed browser sessions the agent operates while the user observes
  or takes over from the workspace. ([#4187])
- **community:** Lark/Feishu CLI integration bundles the runtime install, the
  official `lark-*` skill pack, and an interactive auth flow so the integration
  is no longer environment-dependent. ([#3971])
- **integrations:** Lark/Feishu app credentials can be switched per user
  from Settings > Integrations: new App ID/Secret values are validated
  before anything is committed, and the previous OAuth token is revoked
  after a successful switch. ([#4703])
- **acp:** MiniMax Code (`mcode acp`) is supported and documented as a
  native external coding agent, and ACP thought chunks are no longer
  concatenated into tool results. ([#4846])
- **models:** A Z.AI GLM-5.3-Flash profile keeps thinking permanently enabled
  and stops generic reasoning-effort forwarding, since the model rejects
  disabled thinking and only accepts its own effort values. ([#5074])
- **community:** New web search providers - Serply (with news and scholar
  verticals) and Tencent Cloud WSA - plus native recency filters
  (day/week/month/year) shared across DDGS, Brave, Tavily, and SearXNG.
  ([#5023], [#5057], [#5099])
- **knowledge:** Opt-in read-only RAGFlow retrieval exposes a
  `knowledge_search(query)` agent tool over configured RAGFlow datasets, with
  a dataset-ID allowlist and credential/dataset-id redaction on error paths.
  ([#4955])

#### MCP

- **mcp:** A durable task runtime for MCP: long-running tool tasks survive
  Gateway restarts through a durable driver, and their progress and
  completion notifications surface in the chat UI. ([#4665], [#4690],
  [#4833])
- **mcp:** Shared MCP servers can inject per-user credentials: a single
  server entry authenticates each DeerFlow user with their own header
  value, unmapped users are denied by default, and stored credentials are
  masked in Gateway API responses. ([#4868])
- **mcp:** Per-server `tool_name_prefix` option lets servers that already
  namespace their own tools keep their original tool names; the default
  behavior is unchanged. ([#4624])
- **mcp:** Settings > Tools can add, edit, and delete MCP servers through
  targeted Gateway endpoints, with a copy-paste JSON workflow that preserves
  advanced fields and masked secret placeholders. ([#5022])
- **mcp:** Shared HTTP/SSE servers can map request-scoped secrets to headers
  via `headers_from_context`: callers supply per-request values in
  `config.context.secrets`, the config stores only key names, and missing
  values deny by default. ([#5010])

#### Channels

- **channels:** Expose the IM `channel_user_id` to sandbox commands as
  `DEERFLOW_CHANNEL_USER_ID`. ([#3926])
- **channels:** Queue rapid same-thread messages and preserve topic-card
  previews across batches. ([#3988])
- **channels:** Inbound webhook deduplication moves to Postgres, so several
  Gateway pods can serve the same IM channel without double-processing
  events. ([#4210])
- **channels:** DingTalk inbound messages support file and image
  attachments. ([#4423])
- **channels:** New Buzz (Nostr) channel connector, including the frontend
  experience for the channel. ([#4649], [#4727])

#### Auth & guardrails

- **auth:** Generic OIDC/SSO authentication with Keycloak support. ([#3506])
- **guardrails:** Authenticated runtime context is exposed in `GuardrailRequest`,
  and security interventions are persisted as run events. ([#3665], [#3837])
- **auth:** "Keep me signed in" login option with a centralized session-cookie
  policy (persistent `Secure` cookies on HTTPS, session cookies on public HTTP).
  ([#4255])
- **auth:** Deployments can close local self-registration to restrict new
  accounts to SSO/OIDC provisioning. ([#4311])
- **authz:** Built-in RBAC authorization provider with a unified factory, plus
  tool-authorization enforcement at both assembly (tools removed before the
  model sees them) and runtime (denied calls blocked). ([#4260], [#4370])
- **authz:** Gateway route permissions are derived from the configured
  AuthorizationProvider rather than a fixed table. ([#4439])
- **authz:** Model authorization is enforced at Gateway routes and again in
  the agent runtime, and `sandbox:execute` is checked when a sandbox is
  acquired - users can no longer reach models or sandboxes they are not
  authorized for. ([#4540], [#4911])

#### Sandbox & provisioner

- **sandbox:** New E2B and BoxLite (micro-VM) sandbox providers; BoxLite ships
  with a warm pool. ([#3883], [#3940], [#3951])
- **provisioner:** ClusterIP Services and scoped per-skill PVC mounts, plus a
  configurable sandbox container port. ([#4016], [#3928])
- **sandbox:** New cloud sandbox providers: Tenki and OpenSandbox.
  ([#4382], [#4877])
- **sandbox:** An optional lark-cli credential broker sidecar (K8s
  provisioner mode) keeps Lark app secrets and OAuth tokens out of the
  sandbox filesystem entirely - the sandbox sees only a shim that forwards
  commands to a loopback broker in the pod. Off by default. ([#4501])
- **sandbox:** The E2B mount-upload wall-clock deadline is configurable via
  `mount_upload_deadline_seconds` (default 120s). ([#4876])

#### Extensions & plugins

- **extensions:** An out-of-tree Python extension system: extensions can
  contribute middleware, task-lifecycle and system-model observers, Gateway
  services, and HTTP routers, and are managed with `deerflow extensions`
  install/enable/disable/remove. ([#4636], [#4684], [#4780])
- **extensions:** Extensions can observe what the agent did - message
  provenance, middleware policy declarations, agent-assembly fingerprints,
  context-compaction records, guardrail decisions, and the MCP origin of a
  tool. `deerflow-extension-api` moves to 0.2.0; extensions written against
  0.1 are refused at startup with an install hint. ([#4863])

#### Persistence

- **persistence:** A custom PostgreSQL schema can be selected via
  `postgres_schema`; ORM, LangGraph checkpointer, and store tables are all
  created there, and the schema is created automatically at startup.
  ([#3442])

#### Frontend

- **frontend:** Branching support for assistant turns and side conversations for
  quoted follow-ups. ([#3950], [#3934])
- **frontend:** Regenerate the latest answer. ([#3637])
- **frontend:** Citation-sources evidence panel, workspace change review for
  agent runs, and a visualized `ask_clarification` card. ([#3907], [#3945],
  [#3956])
- **frontend:** Voice dictation, prompt-history recall with arrow keys, composer
  input polishing, and a "(thought for N seconds)" thinking-duration chip.
  ([#4036], [#3718], [#3986], [#3627])
- **frontend:** Feature-gate the agents UI behind the `agents_api` flag, and
  persist AI turn duration in backend and UI. ([#3769], [#3663])
- **frontend:** Render slash-skill activations as inline chips. ([#3981])
- **frontend:** Localized AI-assistance disclaimer. ([#4374])
- **frontend:** Pin recent chats. ([#4442])
- **frontend:** Validate `/goal` objective length in the composer. ([#4337])
- **frontend:** Real-time context window usage is shown as a conversation
  grows. ([#3183])
- **frontend:** The latest user turn can be edited and rerun in place.
  ([#4377])
- **frontend:** Replies can be typed and sent while a clarification card is
  pending. ([#4530])
- **suggestions:** The number of follow-up suggestions is configurable via
  `suggestions.max_suggestions` (default 3). ([#4533])
- **artifacts:** Text artifacts can be edited inline in the artifact panel.
  ([#4596])
- **artifacts:** Markdown artifacts open rendered in a new-window reader (with
  "View source" and "Download" fallbacks), and all files presented in a run
  can be downloaded as one zip archive derived from the run's delivery
  receipt. ([#5056], [#5117])
- **frontend:** Browser Live is available in Custom Agent chats. ([#4719])
- **frontend:** A conversation outline navigates long chats: past 5 user turns,
  a compact side menu lists the conversation's questions and jumps between
  them, tracking the current section. ([#5025])
- **frontend:** Scheduled tasks can be duplicated into an editable draft that
  carries over the configuration but not the run history. ([#5064])
- **threads:** Branched conversations get distinguishing titles
  (automatic `Title (2)`, `Title (3)` sibling numbering) and the
  recent-chats list shows parent-child lineage with tree connectors.
  ([#4983])

#### Observability & tooling

- **observability:** Trace-id correlation with enhanced logging and agent
  observability via Monocle. ([#3902], [#4024])
- **tooling:** A Hermes-like terminal workbench (`deerflow` CLI) backed by
  `DeerFlowClient`, plus a redacted community support-bundle generator. ([#3760],
  [#3886])
- **setup:** The setup wizard now asks whether OpenAI-compatible gateway models
  support thinking, and a Volcengine Coding Plan quick-setup path was added.
  ([#3428], [#4141])
- **tui:** `clear` command. ([#4306])
- **tui:** The TUI supports a transparent terminal background. ([#4631])

### Changed

- **frontend performance:** Keep the public root and localized docs static;
  lazy-load closed workspace panels and editor/highlighter dependencies;
  incrementally derive streamed message state; bound streaming Markdown work;
  virtualize long message and chat lists; pause offscreen decorative effects;
  and enforce representative route JS/CSS budgets.
- **browser:** Negotiate binary Browser Live JPEG frames, retain the legacy
  JSON/base64 protocol for older clients, coalesce presentation to the latest
  frame per refresh, and revoke replaced object URLs.
- **artifacts:** Stream regular text artifacts with HTTP byte-range support and
  limit the initial Web UI preview to 1 MiB until the user explicitly loads the
  complete file.
- **sandbox:** The Helm chart now defaults per-sandbox Services to `ClusterIP`
  instead of `NodePort`, so the code-execution sandbox is reachable only inside
  the cluster via Service DNS (`http://sandbox-<id>-svc.<ns>.svc.cluster.local`)
  and is no longer bound on every node's interfaces - including the
  externally-reachable ones on GKE/EKS/AKS. Existing chart installs flip
  NodePort -> ClusterIP on upgrade. To preserve the old reachability (an
  external probe hitting the 30xxx port, or the Docker-Compose/hybrid path
  where the gateway is not in K8s), set `provisioner.sandboxServiceType: NodePort`
  (with `provisioner.nodeHost` if needed). The provisioner itself is unchanged
  (mode-aware since #4016). ([#4190])
- **skills:** An active restrictive skill must explicitly list `task` in
  `allowed-tools` to delegate to a subagent. Read-only discovery infrastructure
  (`tool_search` and `describe_skill`) remains available, but cannot grant schema
  visibility or execution for a denied business tool. ([#4098])
- **memory:** Pre-abstraction top-level `memory.*` DeerMem fields
  (`storage_path`, `max_facts`, `debounce_seconds`, `model_name`,
  `token_counting`, `staleness_*`, `consolidation_*`, ...) are **auto-migrated
  into `backend_config`** on load with a warning, so an upgrade does NOT silently
  revert customized settings to defaults (`model_name` ->
  `backend_config.model.model`). Move them under `memory.backend_config` in
  `config.yaml` to silence the warning. ([#4122])
- **memory:** Added `memory.mode` (`middleware` | `tool`); `tool` mode registers
  memory tools (`memory_search`/`add`/`update`/`delete`) the model calls directly
  instead of passive per-turn summarization. `manager_class` resolution is now
  fail-fast (raises `ValueError` on an unknown backend instead of silently
  falling back). ([#4023])
- **middleware:** Declarative layered middleware builder; `ThreadData` now runs
  before `Uploads`. ([#3809])
- **sandbox:** The host->virtual output-masking regex now has a single owner,
  eliminating duplicated pattern compilation. ([#4108])
- **docs:** `AGENTS.md` is now the source of truth for agent guidance, imported
  by `CLAUDE.md` via `@AGENTS.md`; module guides refreshed. ([#3770])
- **memory:** The OpenViking memory backend now uses the official OpenViking
  adapter; the old trusted-mode `auth_mode`/`account` fields are rejected in
  favor of a credential-bound USER API key. ([#4707])
- **gateway:** Threads created before the run-event journal have their
  checkpoint history backfilled as seed events before the first new run, so
  legacy conversations stay visible and correctly ordered after an upgrade.
  ([#4590])
- **agents:** Subagent delegation is now routed by net benefit: the lead agent
  defaults to direct execution unless parallel latency, specialist capability,
  or context isolation clearly pays off. ([#4384])

### Fixed

- **gateway:** Stop persisting a caller-supplied `deerflow_trace_id` on the run
  record. `body.metadata` reaches both the live run config, which the run
  worker restamps, and the run record echoed verbatim by the runs API; only the
  first was covered, so a client could make the most durable surface of a run
  disagree with the `X-Trace-Id` and the log lines from the same request. The
  id is now stamped once at the trust boundary, `config.context` is closed off
  the same way, and a thread's own metadata is no longer seeded with the
  run-scoped id of whichever run created it. ([#5119])
- **gateway:** Expose `X-Trace-Id` in `Access-Control-Expose-Headers`. It is not
  CORS-safelisted, so split-origin browser clients — the ones that cannot read
  the Gateway's logs either — could not read the correlation id they are meant
  to quote in a bug report. ([#5119])
- **gateway:** Keep `X-Trace-Id` on unhandled-exception 500s. Starlette's
  `ServerErrorMiddleware` emits those through the raw send outside every user
  middleware, so the 500 for a server bug — the response most in need of
  correlation — was the only one shipped without the id. `TraceMiddleware` now
  sends its own 500 carrying the header before re-raising; the server's
  exception logging is untouched and mid-stream failures propagate unchanged.
  This fallback is emitted outside `CORSMiddleware` and stays CORS-opaque, so
  split-origin browser clients cannot read the id on this one response — same
  as the `ServerErrorMiddleware` 500 it replaces. ([#5119])
- **gateway:** Strip a forged `deerflow_trace_id` from the persisted request
  echo. `body.config` is stored verbatim as `runs.kwargs_json` and served back
  by the runs API, so a forged id in `config.metadata` or `config.context`
  survived on that one surface while every other carried the real id.
  `redact_config_secrets` now drops the key from both containers, and
  `build_run_config` merges run metadata onto a copy so the server-stamped id
  can no longer be written through into the caller's request body. ([#5119])
- **artifacts:** Keep explicit full-file loading scoped to the source thread, so a same-path artifact in another conversation keeps its 1 MiB preview. ([#4634])
- **sandbox:** `SandboxAuditMiddleware` no longer blocks ordinary command
  substitution that only captures output. The rule now judges *position* instead
  of matching any `$(`: `x=$(curl url)`, `echo $(curl url)`, an argument, and a
  `for` word list all run normally, while a substitution in command position
  (`$(curl url)`, after a `|`/`&&`/`;`, behind leading assignments or an
  `env`/`nohup`/`time` style wrapper, or as an `eval`/`source` argument) still
  blocks because it executes fetched content. An interpreter's code-string flag
  (`bash -c`, `python -c`, `perl -e`, `node -p`, `php -r`, and the `<<<`
  here-string) is treated as an execution context wherever it appears, so
  `bash -c "$(curl url)"` blocks; `source <(curl url)` and the backtick spelling
  of `eval`/`source` now block too, neither of which was detected before. An
  unquoted newline separates statements like `;`, so `echo hi` followed by a
  new line starting `$(curl url)` blocks as well, while heredoc bodies are
  consumed as data — writing a file whose content happens to start a line with
  `$(curl url)` is not a command.
  Variable expansions whose name merely starts with a risky executable
  (`$shell`, `$bashrc`, `$python_version`) and lookalike binaries
  (`shellcheck`, `shasum`) are no longer false positives.
  ([#4611], [#4623])
- **mcp:** Isolate Settings > Tools enable/disable updates to one MCP server, so
  an unrelated disallowed stdio command no longer blocks every switch; allow
  disabling a disallowed target while still rejecting its re-enable, preserve
  the raw extensions config, honor the MCP-spec `transport` alias when enabling
  SSE/HTTP servers, surface backend validation details in the UI, and atomically
  replace the shared config for MCP, skill, and embedded-client updates so
  interrupted writes cannot leave it truncated.
  ([#4574], [#4577])
- **runtime:** Thread metadata now switches to `running` only after the run passes
  the startup barrier, so pending-cancelled runs no longer briefly project
  `running`; clients may observe the prior thread status during worker startup.
  ([#4450])
- **runtime:** Re-check orphan candidates through an atomic, lease-aware takeover
  claim so a successful heartbeat after the scan keeps the run active and only
  one reconciler reports recovery. ([#4424], [#4434])
- **skills:** Apply `allowed-tools` only to slash-activated or actually loaded
  lead-agent skills, preventing passive enabled skills and evaluation fixtures
  from removing MCP, web, file, and delegation tools from every run. ([#4095],
  [#4098], [#4192])
- **models:** Honor `api_base` on every `BaseChatOpenAI` subclass (`VllmChatModel`,
  `MindIEChatModel`, `PatchedChatMiMo`, `PatchedChatStepFun`, `PatchedChatMiniMax`),
  not just `ChatOpenAI` / `PatchedChatOpenAI`. Those five previously dropped the
  configured endpoint silently and then failed every request with an opaque
  `unexpected keyword argument 'api_base'`; the unknown-config-key warning was
  disabled for them as well. Both now gate on `issubclass(BaseChatOpenAI)`.
  ([#4146])
- **agents:** Coalesce `SystemMessage`s before the LLM request; ensure a visible
  response after tool runs; avoid a default LLM title call before stream end;
  reserve ellipsis room so the local title respects `max_chars`; and snap the
  tool-output tail forward so fallback truncation respects `max_chars`. ([#3711],
  [#4033], [#3885], [#4052], [#4017])
- **agents:** Skip dateless reminders in the dynamic-context date scan; load
  `SOUL.md` from agent dirs without `config.yaml`; require `config.yaml` in
  `update_agent`'s legacy-agent guard; and refuse empty `SOUL.md` updates.
  ([#3685], [#4136], [#4166], [#4219])
- **middleware:** Window the loop-detection tool-frequency counter so long runs
  no longer false-trip; prevent the title middleware from streaming tokens;
  fix positional fallback consuming an unrelated todo when the same-content list
  is exhausted; acquire the token-budget lock across `_apply`, `before_agent`,
  `_clear_run_state`, and `_drain_pending_warnings`; drop orphan `ToolMessage`s
  so strict providers don't 400; sanitize invalid tool-call arguments; and
  recover from empty tool-call names and malformed tool-call ids in dangling
  repair. ([#4072], [#3566], [#3709], [#3714], [#4080], [#4193], [#4008],
  [#4246])
- **subagents:** Inherit `LoopDetectionMiddleware` and summarization middleware
  so tool loops break and steps are captured; surface the turn-budget cap as
  `MAX_TURNS_REACHED` with a partial result; unify guardrail caps on the additive
  `stop_reason` + `token_budget`; inject durable context before compaction;
  preserve the parent checkpoint namespace; prohibit the `task` tool in the
  general-purpose system prompt; re-buffer subagent events on flush failure to
  avoid losing steps; and fix the lost `loop_capped` stop reason when a
  subagent's `run_id` is `None`. ([#3931], [#4009], [#3949], [#3980], [#4040],
  [#4215], [#4161], [#4082], [#4059])
- **memory:** Harden against null/empty edge cases - skip whitespace-only facts;
  coerce null `confidence` / `source.confidence` in updates, searches, and the
  three remaining raw reads; treat explicit `null` `backend_config` values as
  omitted; fix `KeyError` / `UnboundLocalError` when a fact has no id or the
  facts list is empty; stop the busy-spin in the debounced update queue; and
  flush the memory queue on graceful shutdown to prevent loss. ([#3719], [#4074],
  [#4076], [#4034], [#4217], [#3993], [#3992], [#4073], [#4181])
- **runs:** Close multi-worker ownership gaps in run atomicity; fail-stop local
  execution when lease renewal cannot be confirmed before its deadline and
  fence late completion writes after peer takeover; degrade cancel to lease
  takeover for multi-worker; keep `create_thread` idempotent when the insert
  loses a race; read `stop_reason` from runtime context; and persist run duration
  in checkpoints for history reads. ([#4003], [#4064], [#4414], [#3800], [#4188],
  [#4118], [#4431])
- **runtime:** Serialize SQLite event-store writes to prevent per-thread
  sequence collisions; skip hidden human messages in the journal; and drop the
  silent delta-discard in `_merge_stream_text`. ([#4077], [#3698], [#4085])
- **gateway:** Attach thread-message feedback by real `event_type`; offload
  blocking filesystem IO in artifact serving, gateway uploads, and the Discord
  channel; limit the uploaded-file context manifest; and live-tail malformed
  Redis reconnect ids. ([#3651], [#3551], [#3935], [#3927], [#3917], [#4012])
- **uploads:** Claim the converted-Markdown companion filename before writing
  it, so two convertible uploads sharing a stem (or a convertible plus a
  same-stem `.md` upload) no longer silently clobber each other within one
  request. When `uploads.auto_convert_documents` is on, the companion `.md` now
  gets a unique name (e.g. `a_1.md`); `POST /threads/{id}/uploads` and
  `DeerFlowClient.upload_files` both report the actual name in `markdown_file`.
  ([#4288])
- **config:** Coerce null object config sections to their defaults; honor the
  unified database configuration in the store and sync checkpointer; and have
  legacy DB backfill create missing `Index` objects on existing tables. ([#3573],
  [#3904], [#3994], [#4090])
- **models:** Apply the `stream_chunk_timeout` default to all `BaseChatOpenAI`
  subclasses; and normalize `api_base` -> `base_url` for `ChatOpenAI` with a
  warning on unknown config keys. ([#4102], [#3790])
- **mcp:** Isolate tool-discovery failures per server; synchronize the
  session-pool singleton lifecycle; invalidate the tools cache on config content
  + path (not just newer mtime); validate MCP tool names at load so deferred
  prompts stay inert; and route tools by source server, not name prefix. ([#3772],
  [#3797], [#4124], [#4154], [#3812])
- **skills:** Activate a slash skill once per run, not per model call; close the
  skill-install security-scan coverage gap; recognize fully deleted skill
  packages in review CI and remaining `requests` / `httpx` methods as network
  sinks in SkillScan; reuse the resolved app config in the no-arg skills prompt
  section; and reload mounted skills without restarting the Gateway. ([#4103],
  [#3924], [#4169], [#4130], [#4160], [#4264])
- **sandbox:** Guard the reverse path-translation and output-masking regexes
  with segment boundaries; handle one-sided line ranges and empty files in
  `read_file` / `str_replace`; align the AIO bash working directory; use
  `os.sep` in the reverse-resolve containment check on Windows; normalize
  Windows backslash paths in bash commands; stop `glob` / `grep` / `ls` from
  surfacing disabled skills' files; and allow valid heredoc commands in the
  sandbox audit. ([#4035], [#4053], [#4078], [#4079], [#4051], [#4058], [#3869],
  [#4096], [#3786])
- **sandbox:** Synchronize the sandbox provider singleton lifecycle (with
  concurrency regression tests) and keep k8s calls off the event loop in the
  provisioner. ([#3730], [#3941])
- **sandbox:** Align sandbox artifact mounts with the channel user; fix
  local-dev (`make dev`) on non-root / NFS hosts; reap macOS nginx processes on
  stop; and fix production Postgres UV-extras detection in Docker. ([#3729],
  [#3590], [#3828], [#3897])
- **channels:** Validate the channel provider before resolving its config;
  dedupe GitHub webhook redeliveries and drop redundant GitHub review-comment
  webhook fan-out; scope the slash-skill whitelist check to the run's owner;
  batch Feishu file messages into one thread and dispatch Feishu group commands
  prefixed with a bot @mention; accept leading @mentions before `/connect` bind
  codes and don't treat a bare "connect" as a bind command; stop Feishu from
  creating thread topics and throttle card updates; let the UI runtime channel
  config win over `config.yaml`; fix `require_mention` gating on
  whitespace-only `bot_login` / `mention_login`; guard null quote fields in
  WeCom; and key inbound dedupe on chat-scoped workspaces so Telegram, Feishu,
  WeChat and DingTalk redeliveries stop re-running the agent on a default
  (unbound) configuration, releasing the dedupe key on transient failures so a
  redelivery can still recover. ([#4100], [#4104], [#4131], [#4129], [#3753],
  [#4229], [#4222], [#4251], [#3810], [#3674], [#4055], [#4069], [#4287])
- **frontend:** Preserve messages and durable context across summarization;
  preserve artifacts and stabilize artifact paths during streaming; resolve
  relative artifact image paths; retain presented artifacts in the header
  dropdown; keep orphan tool messages visible; show assistant text during tool
  steps; reset new chat on client-side navigation; prevent stream cancellation
  on concurrent submit; fix stale-run reconnect and cancel handling; fix chat
  math rendering, single-tilde markdown, double reasoning rendering, UTF-16
  markdown binary classification, and `<memory>` tags in Streamdown; make
  recent-chat rows fully clickable; validate attachment limits before upload and
  fix uploaded-file metadata in message copy; fix mobile workspace and
  accessibility blockers, the card tool-message bug, and side-chat toolbar /
  panel-button behavior; block unresolved suggestion-template placeholders;
  refresh notification permissions; show the branch action only for completed
  turns; enable regenerate in custom agent chats; and generate a fallback title
  for interrupted first-turn runs. ([#3826], [#3791], [#4094], [#4038], [#3854],
  [#3880], [#4114], [#3673], [#3878], [#3908], [#3557], [#4245], [#3870], [#3966],
  [#4209], [#3733], [#3900], [#3944], [#3740], [#3976], [#3959], [#3961], [#3764],
  [#3768], [#4147], [#3967], [#3874], [#3644])
- **tui:** Interrupt an active run before `/quit` exits. ([#4235])
- **harness:** Don't flag the outline as truncated at exactly `MAX_OUTLINE_ENTRIES`
  headings. ([#3856])
- **tracing:** Attach Langfuse trace metadata to the goal evaluator. ([#4202])
- **context:** Resolve the context-compress bug. ([#4065])
- **threaddata:** Fix `AttributeError` when `runtime.context` is `None`. ([#3989])
- **goal:** Stop `continuation_count` double-bump during stand-down. ([#4199])
- **circuit-breaker:** Stop wedging after a non-retriable half-open probe. ([#3991])
- **github:** Match `allow_authors` logins case-insensitively. ([#4218])
- **community:** `image_search` now returns the full-resolution image URL. ([#3990])
- **skills:** Offload blocking filesystem IO in the skill-history endpoint.
  ([#3563])
- **skills:** Don't treat a lazily evaluated PEP 695 type alias as a network
  sink in SkillScan. ([#4315])
- **tracing:** Resolve the Langfuse trace user from runtime context. ([#3794])
- **guardrails:** Propagate internal owner attribution into the guardrail
  context. ([#3839])
- **subagents:** Clamp the subagent limit consistently with
  `MIN_SUBAGENT_LIMIT`. ([#4081])
- **subagents:** Load user-scoped skills. ([#4356])
- **mcp:** Per-server fail-soft OAuth priming, and persist rotated refresh
  tokens. ([#4084])
- **mcp:** Ignore malformed path-like text. ([#4456])
- **auth:** Resolve email accounts case-insensitively. ([#4101])
- **auth:** Recover from setup-status timeouts. ([#4371])
- **scheduler:** Close a dispatch race that could launch two runs for one
  scheduled task. ([#4105])
- **channels:** Buffer and drain GitHub comments queued during a busy run.
  ([#4133])
- **channels:** Escape Slack reserved characters before mrkdwn conversion.
  ([#4197])
- **channels:** Check `response.success()` on Feishu card/reaction SDK calls.
  ([#4234])
- **channels:** Drop inbound DingTalk messages that carry no conversation
  identity. ([#4316])
- **channels:** Receive inbound Telegram attachments. ([#4392])
- **memory:** Consolidated facts inherit `expected_valid_days` from their
  sources. ([#4225])
- **config:** Sync `_memory_config` with AppConfig auto-reload. ([#4208])
- **postgres:** Harden the async engine with `pool_recycle` and
  `command_timeout` to stop stale-connection 504s. ([#4230])
- **harness:** Add a timeout to `invoke_acp_agent` to prevent indefinite hangs.
  ([#4238])
- **community:** Surface the target-page error status in `web_fetch`
  (Browserless). ([#4239])
- **sandbox:** Widen the BoxLite/AIO tenant hash and verify identity on reclaim.
  ([#4171])
- **sandbox:** Make an empty `old_str` a no-op in `str_replace` on any file.
  ([#4256])
- **sandbox:** Serialize E2B release transitions. ([#4355])
- **sandbox:** Bound E2B output-synchronization resources. ([#4364])
- **sandbox:** Unwrap `Overwrite`-wrapped sandbox state in `after_agent`.
  ([#4381])
- **sandbox:** Bypass proxies for local AIO traffic. ([#4444])
- **models:** Surface length-capped model responses instead of dropping them.
  ([#4309])
- **streaming:** Keep large file generation responsive. ([#4354])
- **streaming:** Expose custom events to `astream_events`. ([#4403])
- **streaming:** Signal replay history gaps. ([#4426])
- **summarization:** Summarize with the run model and fall back on
  summary-provider failure. ([#4361])
- **runtime:** Remove transient image context after model calls. ([#4267])
- **runtime:** Stop subgraph stream frames from impersonating root frames.
  ([#4407])
- **runtime:** Reject unsupported run options and stream modes. ([#4430])
- **runtime:** Serialize checkpoint writes with active runs, linearize
  delta-mode checkpoint resume, and accept the SDK's default
  `stream_resumable=false` to avoid resume races. ([#4437], [#4460], [#4468])
- **checkpoint:** Unwrap `Overwrite` first writes into empty channels. ([#4383])
- **nginx:** Allow long chat prompts through `/api/langgraph/` without a raw
  500. ([#4277])
- **gateway:** Prefer `X-Trace-Id` over `metadata.deerflow_trace_id` when the
  header is set. ([#4283])
- **gateway:** Seed branch run-events so inherited history survives forking.
  ([#4385])
- **gateway:** Scope branch-history seed run ids per inherited turn. ([#4459])
- **frontend:** Harden artifact and markdown rendering. ([#4117])
- **frontend:** Classify a symlink replacing a file distinctly from deleted in
  workspace-change review. ([#4170])
- **frontend:** Offload blocking filesystem IO in the workspace-change
  text-cache lifecycle. ([#4268])
- **frontend:** Encode artifact URL path segments. ([#4278])
- **frontend:** Clarify run-duration display. ([#4348])
- **frontend:** Preserve regenerate state in branched threads. ([#4358])
- **frontend:** Default the reasoning-effort label to Medium when unset.
  ([#4373])
- **frontend:** Strip and parse the `<current_uploads>` upload-context tag.
  ([#4402])
- **frontend:** Keep leading orphan tool messages visible. ([#4408])
- **frontend:** Keep completed subtask cards stable after reload. ([#4432])
- **frontend:** Apply message-image `maxWidth` via inline style. ([#4446])
- **frontend:** Restore resizing for the artifacts and sidecar panels. ([#4469])
- **frontend:** Allow dev-server access from non-localhost hosts. ([#4471])
- **safety:** Backfill empty content-filter responses so they don't poison the
  thread. ([#4394])
- **tools:** Exclude injected runtime from the `list_uploaded_files` schema.
  ([#4376])
- **mcp:** Bound MCP server bring-up — tool discovery (subprocess spawn +
  `initialize` + `tools/list`) and persistent stdio session initialization —
  with a new per-server `session_init_timeout` (default 60s, `null` disables),
  so a hung stdio server can no longer block agent construction, or the whole
  Gateway event loop, indefinitely. `tool_call_timeout` still bounds individual
  stdio tool calls. ([#4657])
- **runtime:** Tool-output budget externalization no longer trips run delivery
  verification. The default `.tool-results` storage dir (and any custom
  `tool_output.storage_subdir`) is excluded from workspace-change snapshots and
  produced-artifact detection, so a run that only externalized oversized tool
  outputs succeeds instead of failing as an error. ([#4657])
- **frontend:** Hide stale follow-up suggestion chips while a turn is still
  streaming. ([#3396])
- **frontend:** Fix streaming render glitches: stop the word animation from
  replaying, keep step text stable, preserve message order during long runs,
  and keep reasoning above the answer. ([#4266], [#4510], [#4513], [#4578])
- **frontend:** Encode thread IDs in chat routes so IDs with special
  characters no longer break navigation. ([#4302])
- **frontend:** Render citation links from React children. ([#4486])
- **frontend:** Localize conversation export failure messages. ([#4493])
- **frontend:** Sync side panel state when a drag collapses the panel. ([#4556])
- **frontend:** Render one workspace-change card per run instead of
  duplicates. ([#4559])
- **frontend:** Refresh the active artifact's content when it changes. ([#4584])
- **gateway:** Reject non-positive read limits in API requests. ([#4284])
- **gateway:** Handle a null `config.configurable` when resolving the thread
  id instead of failing. ([#4301])
- **gateway:** Unify thread id validation across API routes. ([#4589])
- **gateway:** Merge concurrent thread metadata updates instead of letting
  them silently overwrite each other's changes. ([#4489])
- **gateway:** Expose the run metadata response header to cross-origin
  clients, so a split-origin frontend learns new run ids instead of staying
  stuck on the new-thread placeholder route until reload. ([#4535])
- **gateway:** Replay edit and rerun from a settled checkpoint so the edited
  prompt actually runs (previously a first turn's edit replayed the original
  prompt and vanished after reload), and keep a manual rename through the
  rerun. ([#4534], [#4539])
- **runtime:** Cancel a run from any live gateway worker, not only the one
  that owns it, so the stop button no longer depends on request routing.
  ([#4500])
- **runtime:** Close a replacement run when interrupt or rollback admission
  is cancelled mid-flight, instead of stranding an unseen active run on the
  thread. ([#4472])
- **runtime:** Regenerating a response now preserves the thread's current
  title and supports the latest interrupted response whose partial message
  never reached a checkpoint. ([#4480], [#4524])
- **agents:** Classify web_fetch error pages such as 404s as errors rather
  than successful evidence, so retries and stagnation guards can react.
  ([#4314])
- **agents:** Handle XML-to-dict option shapes when normalizing
  clarification choices. ([#4527])
- **subagents:** Run delegated subagents with isolated callbacks and lazy
  skill activation, fixing cross-event-loop failures and passive skills
  stripping baseline tools like `write_file`. ([#4497])
- **sandbox:** Handle overwrite-wrapped state when ensuring the sandbox is
  initialized. ([#4429])
- **sandbox:** Reconcile E2B sandboxes safely: pick the first healthy
  candidate, adopt the canonical instance per user and thread, defer a
  peer's live duplicates, and reap orphans after a grace window. ([#4443])
- **sandbox:** Claim ownership before destroying a sandbox that failed its
  readiness check, so a peer gateway can no longer adopt the not-yet-ready
  sandbox and kill a live turn. ([#4505])
- **sandbox:** Allow grep to search a single file. ([#4512])
- **sandbox:** Enforce the E2B capacity limit deployment-wide when sandbox
  ownership uses Redis, so multiple gateways cannot create past it. ([#4575])
- **skills:** Activate managed integration skills from the managed
  integrations root on slash invocation. ([#4570])
- **skills:** Offload blocking filesystem IO when updating a skill and
  serialize concurrent writes. ([#3565])
- **mcp:** Ignore oversized path-like text. ([#4582])
- **memory:** Harden long-term memory: reject duplicate facts inside the
  create critical section, truncate injected mem0 context on entry
  boundaries, and keep task-scoped instructions such as "inspect only" out
  of long-term memory. ([#4599], [#4600], [#4604])
- **scheduler:** Keep a successfully launched scheduled run's slot and run
  id when post-launch bookkeeping fails, preventing a later dispatch from
  launching a duplicate run. ([#4504])
- **config:** Treat a deleted extensions config file as absent instead of
  raising, so tool and skill config resolution keeps working. ([#4275])
- **config:** Normalize the `postgres://` short scheme for the async ORM
  engine. ([#4293])
- **console:** Disable cost reporting when model pricing mixes currencies
  instead of reporting a meaningless cross-currency total. ([#4564])
- **browserless:** Accept the `timeout` config key and harden its coercion.
  ([#4519])
- **docker:** Send `Connection: upgrade` only when the browser requests it,
  fixing login-page refresh loops when the Docker dev stack is accessed via
  a remote host. ([#4250])
- **runtime:** Group JSONL batch event writes by run, so a batch covering
  several runs no longer lands all events in the first run's file and makes
  later runs unreadable through per-run APIs. ([#4938])
- **runtime:** Restore standalone LangGraph Studio compatibility: the graph
  entrypoint and file-based app load again, the Studio identity can discover
  system assistants, and the documented `langgraph dev` workflow works.
  ([#4760], [#4838])
- **gateway:** Stamp `turn_duration` on a run's last AI message only in
  `/messages/page`, so multi-step turns no longer repeat the same run
  lifetime as thinking latency on every intermediate message. ([#4755])
- **gateway:** Preserve exact history attribution beyond the event page
  limit, so older AI messages on long-lived threads are no longer credited
  to a later turn's run and duration. ([#4953])
- **gateway:** Reject MCP task cancellation with HTTP 503 when the task
  worker is stopped, instead of acknowledging a cancellation that would
  never run. ([#4963])
- **middleware:** Correct four context-handling defects: fallback
  dynamic-context injection targets the latest user message instead of
  resurrecting an old prompt as the current turn; bare string blocks in
  list-form user content are sanitized like all other user text; duplicate
  placeholders are no longer emitted for the same invalid tool call; and
  summarization no longer compresses away the current request's user message
  while leaving the previous turn's behind. ([#4667], [#4668], [#4693],
  [#4882])
- **middleware:** Restore the system-prompt injection that teaches the model
  about the `write_todos` tool, which the todo middleware's model-call
  override had silently dropped. ([#4735])
- **agents:** Make SQL agent-store signatures content-sensitive, so an agent
  update that reuses its previous timestamp no longer leaves the GitHub
  agent registry serving stale webhook routing. ([#4709])
- **tools:** Resolve presented files with the runtime user, so `present_files`
  no longer rejects valid artifacts as outside the outputs directory when
  the request user context is unavailable. ([#4677])
- **tools:** Retain a strong reference to deferred subagent cleanup tasks, so
  garbage collection can no longer destroy a pending cleanup and leak
  cancelled subagent records, locks, and memory. ([#4928])
- **subagents:** Give every background subagent run a server-side execution
  ID, so concurrent runs that reuse a provider tool-call ID can no longer
  overwrite, poll, or cancel each other's state. ([#4758])
- **harness:** Offload ACP workspace creation and MCP config loading from the
  event loop, so invoking an ACP agent no longer raises blocking-IO errors
  or stalls other async work. ([#4965])
- **mcp:** Reject non-finite `poll_after_seconds` values on task snapshots
  when they arrive, so a bad polling interval no longer crashes scheduling
  and persistence after a successful poll. ([#4750])
- **mcp:** Keep the configured `grant_type` authoritative over
  `extra_token_params` during OAuth token exchange, so extra parameters can
  no longer silently switch the configured flow and be rejected by the token
  endpoint. ([#4860])
- **mcp:** Exclude the internal stdio MCP temp directory (`.mcp/tmp`) from
  workspace changes, so MCP temporary and debug files no longer appear
  alongside user deliverables or crowd real changes out of the file budget.
  ([#4898])
- **mcp:** Cancel the remote task when a durable task submission is cancelled
  mid-flight, so an interrupted submission no longer leaves a remote task
  running with no record to poll or stop. ([#4933])
- **sandbox:** Accept the documented E2B reconciliation config fields, so
  valid E2B configuration no longer produces misleading startup warnings.
  ([#4772])
- **sandbox:** Bound E2B mount upload resource use per file, per mount, and
  across the whole upload pass (shared size and file budgets plus a
  wall-clock deadline), so large mounts can no longer spike Gateway memory
  or hold sandbox capacity indefinitely. ([#4812], [#4842])
- **sandbox:** Preserve trailing whitespace in E2B-synced filenames and
  tolerate out-of-range remote mtimes, so output sync no longer re-downloads
  files repeatedly or aborts mid-sync. ([#4861])
- **sandbox:** Reject non-finite Redis lease-timing values in sandbox
  ownership config at parse time instead of crashing with an `OverflowError`
  during startup. ([#4960])
- **sandbox:** Resolve structured skill reads through the sandbox provider's
  path mappings, so `read_file` opens legacy and per-user custom skills
  under the same enabled-state projection as `ls` and shell execution.
  ([#4792])
- **skills:** Parse Responses API content blocks in the moderation scanner,
  so valid skill-management decisions returned as content blocks are no
  longer rejected as unparseable. ([#4936])
- **memory:** Reject non-positive and non-finite timeout and character-limit
  settings in the Honcho and Mem0 backends at config parse time, so a bad
  value fails fast instead of silently truncating stored text or crashing on
  the first HTTP call. ([#4783], [#4823])
- **memory:** Scope custom-agent bootstrap facts to the selected agent's
  bucket, so facts learned during setup no longer leak into the default
  bucket and influence ordinary lead-agent conversations. ([#4804])
- **artifacts:** Support atomic saves on Windows, and serve a SHA-256 ETag on
  artifact reads so inline preview and editing work on non-secure contexts
  such as plain-HTTP LAN origins where `crypto.subtle` is unavailable.
  ([#4629], [#4865])
- **frontend:** Keep conversation order stable around long runs: the
  submitted user message no longer renders twice or sinks below its own
  processing steps, and after a mid-run page reload a turn's steps can no
  longer appear above the user message that started the run. ([#4620],
  [#4660], [#4834])
- **frontend:** Stop matching `<header>` as `<head>` when injecting the base
  href into HTML artifact previews, so relative assets in report fragments
  that begin with `<header>` now load in the sandboxed preview iframe.
  ([#4625])
- **frontend:** Open landing-page case studies on a public read-only
  `/showcase/` route so anonymous visitors are no longer redirected to
  login. ([#4635])
- **frontend:** Sort the chats page by pinned state, so pinned threads no
  longer render below unpinned ones. ([#4643])
- **frontend:** Keep `<think>` pairs written inside markdown inline code in
  the rendered content instead of hollowing them out into the Reasoning
  panel, and restore the copy button for turns that contain only reasoning.
  ([#4647])
- **frontend:** Surface model-loading failures with a workspace error banner
  and retry action instead of a silently empty model list. ([#4840], [#5021])
- **frontend:** Preserve copy and other actions on completed assistant
  messages while a later turn is still streaming. ([#4844])
- **frontend:** Keep the browser live stream connected after a successful
  reconnect instead of tearing down the new socket and immediately creating
  another. ([#4951])
- **frontend:** Reuse the shared clipboard fallback when copying the Lark
  authorization link, so the copy action works in browsers without the
  Clipboard API. ([#4767])
- **frontend:** Use consistent "DeerFlow" casing in the composer disclaimer
  and fix the "What's New" heading on the landing page. ([#4970])
- **channels:** Bound inbound intake with a fixed worker pool and bounded
  admission queues, and await real cross-thread tasks on shutdown, so
  message floods are rejected promptly instead of accumulating and channel
  shutdown no longer tears down transports with work still in flight.
  ([#4800], [#4816])
- **channels:** Offload outbound attachment file IO for Feishu, Telegram, and
  WeCom to worker threads, so sending a large artifact no longer stalls the
  Gateway event loop. ([#4633])
- **channels:** Run Telegram connection-identity lookups on the Gateway event
  loop, so inbound messages and commands no longer crash with a cross-loop
  error when channel connections are enabled. ([#4815])
- **feishu:** Keep file receiving off the event loop and preserve every
  inbound attachment: duplicate provider filenames no longer overwrite each
  other, writes can no longer be redirected outside the thread bucket, and a
  failed attachment no longer blocks the rest of the message. ([#4627],
  [#4903])
- **dingtalk:** Strip leading `@bot` mentions before command classification,
  so slash commands like `/new` sent in group chats are recognized instead
  of treated as plain chat. ([#4724])
- **discord:** Refuse to start typing-indicator loops after the channel
  stops, so shutdown no longer leaves an infinite typing task sending
  events in the background. ([#4752])
- **wecom:** Serialize WebSocket start/stop transitions and await the SDK's
  real receive-task shutdown, so stopping the WeCom channel can no longer
  return before the socket closes or clear a newer connection's state.
  ([#4762])
- **buzz:** Drop replayed events across reconnects using a persistent
  seen-id store, so the agent no longer re-answers the last message in a
  channel after a relay or Gateway restart. ([#4888])
- **lark:** Keep the CLI lock directory writable inside sandboxes while the
  credential-bearing config root stays read-only, restoring Lark API
  commands that previously failed with a read-only filesystem error.
  ([#4701])
- **scheduler:** Enforce the global `max_concurrent_runs` budget for manual
  triggers too, returning HTTP 409 when the cap is reached instead of
  letting manual launches exceed it. ([#4769])
- **scheduler:** Coerce serialized task timestamps on read, so
  scheduled-task operations no longer fail when string-form timestamp values
  reach the database layer. ([#4785])
- **scheduler:** Support safe multi-instance scheduler recovery: startup no
  longer treats live runs owned by peer Gateway instances as local
  leftovers, so a restarting instance cannot interrupt a live run or trigger
  a duplicate execution; multi-instance mode is opt-in via
  `scheduler.multi_instance`. ([#4713])
- **scheduler:** Enqueue busy scheduled task runs instead of skipping them:
  occurrences that hit a busy reused thread now wait in a durable queue
  (bounded by `scheduler.queue_timeout_seconds`) and survive Gateway
  restarts, and the UI explains the queueing behavior. ([#4918])
- **cli:** Add `--recursion-limit` to headless `--print`, `--json`, and
  `--cli` runs, so long-running agent loops are no longer stuck at the
  default recursion limit of 100. ([#4615])
- **dev:** Exclude backend runtime state from the Uvicorn reload watcher in
  the backend `make dev` launcher, so an agent task writing files under the
  runtime tree can no longer restart the Gateway and reset concurrent
  users' requests. ([#4759])
- **dev:** Resolve diagnostic script paths from the script's own location, so
  root diagnostic commands work when invoked from any working directory.
  ([#4736])
- **docker:** Harden local and container startup: `make up` waits for the
  Gateway health probe before declaring the stack ready, Docker startup no
  longer aborts when `.env` is missing, the Gateway can write
  `extensions_config.json` in production, runtime data stays out of the
  image build context, log commands resolve the checkout root correctly,
  and the default loopback origins are allowed so the dev setup page can
  hydrate. ([#4658], [#4806], [#4852], [#4853], [#4956], [#4959])
- **gateway:** Stamp the server-authoritative feed position onto persisted
  messages, so an early user message no longer vanishes or jumps into the
  middle of the step stream once history exceeds one page and context
  compaction has fired. ([#4696])
- **lark:** Preserve the new app secret during managed credential switches by
  clearing the previous app's OAuth data before the replacement is written,
  so the subsequent browser authorization no longer resolves an empty
  `client_secret`. ([#4820])
- **messages:** Drop legacy `<uploaded_files>` tag handling: the backend treats
  the pre-#4174 spelling as ordinary content and strips only
  `<current_uploads>`, while the frontend keeps stripping the legacy tag so
  old threads still render cleanly. ([#4826])
- **skills:** Reject a blank `SKILL.md` description at the write gate, matching
  what the loader already requires, so editing a custom skill with an empty
  description no longer writes a file the loader then rejects - which
  destroyed the skill on disk. ([#4867])
- **sandbox:** Make the model-facing `description` argument optional (empty by
  default) across `bash`, `ls`, `glob`, `grep`, `read_file`, `write_file`,
  `str_replace`, and `task`, so providers that omit it are no longer rejected
  before execution. ([#4878])
- **sandbox:** Bound Windows command execution: host commands run in a new
  process group killed via `taskkill /T /F` on timeout so a descendant cannot
  hold the call open, and output flows through the existing bounded 10 MiB
  capture. ([#4946])
- **sandbox:** Scope the Windows MSYS path-conversion exclusion to safe virtual
  path prefixes instead of disabling conversion globally, so host-native CLI
  launchers that need normal conversion work again. ([#5003])
- **skills:** Rebuild per-user skill storage after an app-config hot reload,
  so it no longer stays bound to paths from the previous config instance.
  ([#4972])
- **skills:** Tokenize portable `allowed-tools` scalars with parenthesis
  awareness, so `Bash(tvly *)`-style entries stay intact, unmatched
  parentheses are rejected instead of silently fragmenting, and
  argument-scoped entries remain literal rather than broadening access.
  ([#4984])
- **agents:** Normalize `ToolMessage`s returned inside `Command` results, so
  error payloads no longer earn a default success receipt and tool-progress
  tracking sees them. ([#4977])
- **mcp:** Tear down the in-flight session owner when `get_session` is
  cancelled during eviction, so a cancelled caller no longer leaks the owner
  task or parks past its timeout. ([#5008])
- **mcp:** Reconnect ordinary stdio tools after a transport disconnect: the
  failed pooled session is evicted (only if still registered), the original
  error surfaces without automatic replay, and a later retry starts a fresh
  subprocess. ([#5018])
- **mcp:** Preserve pooled stdio sessions after protocol timeouts during
  durable MCP task polling - a 408 is not a disconnect - so task state
  survives and the next poll no longer reports `task_not_found`. ([#5027])
- **mcp:** Reject credentials that cannot travel as HTTP header values
  (trailing newline or whitespace, non-ASCII) at the config boundary, so the
  transport's exception - which echoes the full value - can no longer leak a
  secret into model context, checkpoints, and traces. ([#5066])
- **subagents:** Clean up the background-task entry when the poller exits
  unexpectedly and drop a PENDING registry entry when submission fails, so a
  failed or crashed poll no longer leaks the entry or leaves the subagent
  running unattended. ([#5069])
- **subagents:** Stop the zombie PENDING registry entry on the submit-failure
  path, and derive the capacity snapshot's queued count from the waiters'
  length instead of iterating a deque other threads mutate. ([#5086])
- **channels:** Synchronize `ChannelStore` reads with mutations, so
  `get_thread_id()`/`list_entries()` can no longer raise `dictionary changed
  size during iteration`. ([#5083])
- **discord:** Retain strong references to ack-reaction tasks and drain them
  on shutdown, so a GC pass can no longer silently drop a reaction or pin the
  channel across restart cycles. ([#5049])
- **buzz:** Move seen-event persistence off the event loop with coalesced
  atomic writes, preserving dirty generations when events arrive mid-write
  and awaiting the final flush on shutdown. ([#5103])
- **streaming:** Stop an `IndexError` in `MemoryStreamBridge._make_gap` when a
  subscriber reconnects to an empty or drained stream with an expired cursor.
  ([#5047])
- **uploads:** Keep deduplicated filenames within the 255-byte limit by
  truncating the stem on a UTF-8 code-point boundary, so two max-length files
  that differ only by a dedupe suffix upload successfully instead of failing
  the whole batch. ([#5059])
- **frontend:** Format structured upload error details (FastAPI validation
  issues, objects, arrays) instead of showing `[object Object]`. ([#5071])
- **frontend:** Keep a renamed thread's title in sync across the active chat
  header, document title, search results, and metadata caches without a
  reload. ([#5045])
- **frontend:** Truncate selected model names to the selector button width, so
  long model names ellipsize in the composer and sidecar instead of
  overflowing. ([#5050])
- **frontend:** Truncate long subtask card titles to one line with a tooltip,
  so a delegation whose model omitted `description` (falling back to the full
  prompt) no longer overflows the chat layout. ([#5136])
- **dev:** Default the frontend dev server to Webpack on all platforms
  (`DEER_FLOW_DEV_BUNDLER=turbo` opts back into Turbopack), avoiding
  Turbopack's macOS PostCSS worker leak and its Windows runtime panics.
  ([#5036], [#5133])
- **scripts:** Run repo shell scripts through an explicit interpreter
  (`bash scripts/...`), so a lost executable bit - zip/tarball downloads,
  `core.fileMode=false`, non-POSIX filesystems - no longer breaks
  `make docker-start` and friends with `Permission denied`. ([#5031])
- **deps:** Depend on the renamed `tenki` package instead of the PyPI-removed
  `tenki-sandbox` (same `tenki_sandbox` import), so clean checkouts can
  resolve dependencies again on `make dev`/`uv sync`. ([#5087])

### Performance

- **runtime:** Index `MemoryRunStore` by `thread_id` and `MemoryRunEventStore`
  events by `run_id` to avoid O(n) scans. ([#3562], [#3686])
- **subagents:** Deduplicate streamed AI messages via a seen-id set (O(n²) ->
  O(n)). ([#3687])
- **sandbox:** Cache `LocalSandbox` path-rewrite regexes and local-path masking
  patterns per instance instead of recompiling per search match. ([#3648],
  [#3713])
- **messages:** Index tool-call results per group. ([#4411])
- **frontend:** Coalesce streaming renders to a frame budget instead of per
  chunk. ([#4425])
- **frontend:** Stop re-deriving message content on every stream chunk.
  ([#4441])
- **sandbox:** `read_file` reads only the requested line range from the
  sandbox instead of fetching the whole file first. ([#3824])
- **browser:** Encode Browser Live progress frames as JPEG to cut progress
  payload size. ([#4836])
- **middleware:** Inject `view_image` content via `wrap_model_call` instead of
  a checkpointed hidden message, so up to 20 MB of base64 no longer sits in
  two checkpoints per viewed image and an interrupted run can no longer leave
  the payload behind. ([#5014])
- **frontend:** Cache settled copy-data derivation across streaming chunks, so
  each chunk no longer re-derives toolbar/copy text for every settled
  message. ([#5095])
- **runtime:** Bound gateway memory after terminal runs, stopping the post-GC
  low-water mark from creeping upward across completed sessions. ([#5112])

### Security

- **prompt-injection:** New input-sanitization middleware defends against
  prompt-injection, forged framework tags in the input guardrail are blocked,
  and system context is injected as a `SystemMessage` for role isolation. ([#3662],
  [#4155], [#3661])
- **prompt-injection:** HTML-escape untrusted content rendered into model prompts
  - memory facts and summaries, `SOUL.md`, subagent descriptions, skill metadata,
  and the conversation block in the memory-update prompt - and neutralize
  prompt-injection tags in `web_capture` tool results. ([#4028], [#4119], [#4137],
  [#4157], [#4162], [#4099], [#4060], [#4097], [#4128])
- **secrets:** Scrub inherited secret environment variables (`MYSQL_PWD`,
  `REDISCLI_AUTH`, abbreviated `*_PASS`, and Postgres `PGPASSFILE`) from the
  skill environment; request-scoped secrets are bound for both slash-activated
  and autonomously-invoked skills. ([#4018], [#4026], [#3871], [#3938])
- **web_fetch:** SSRF guard for self-hosted providers. ([#3942])
- **guardrails:** An empty allowlist now denies all tools instead of failing
  open. ([#4067])
- **authz:** Global skills-management endpoints now require admin; the legacy
  skills mount is gated by user visibility; artifacts honor a trusted
  `owner-user-id` header; and the trusted authorization principal is propagated
  through the runtime. ([#3855], [#3985], [#3982], [#4203])
- **auth:** Persist the `csrf_token` cookie for the access-token lifetime.
  ([#3872])
- **storage:** Stop persisting base64 image data in checkpoint state. ([#4140])
- **mcp:** Reject legacy MCP credentials in run metadata. ([#4448])
- **mcp:** Constrain stdio launcher arguments and environment variables at
  the config API, rejecting launcher flags and env names that could turn an
  allowlisted `npx`/`uvx` server registration into arbitrary code execution.
  ([#4617])
- **auth:** Harden validation of the post-login `next` path. ([#4587])
- **runtime:** Honor the LangGraph Server's authenticated user identity
  across agents, uploads, thread data, memory, and skills, and reject
  client-supplied auth identity fields. ([#4538])
- **frontend:** Send the session cookie on model, workspace-change, and
  ranged artifact reads in split-origin deployments. ([#4827])
- **frontend:** Restore sanitization in custom streamdown rehype chains, so
  artifact markdown previews and the memory settings summary can no longer
  render hostile HTML such as `javascript:` links or `on*` event handlers.
  ([#4987])
- **skills:** Copy projected skill files instead of hardlinking them, so a
  sandboxed write can no longer mutate the canonical skill source, and fail
  closed on a drifted projection namespace on every platform, including
  Windows. ([#4825], [#4830])
- **scripts:** Redact secret-shaped keys (`db_pass`, `signing_key`, ...)
  wherever they appear in bundled config, not only under well-known key
  names. ([#4242])
- **sandbox:** Sanitize MCP-sourced tool results through the same trust
  boundary as the built-in web tools, so a hostile or compromised MCP server
  can no longer hand the model forged `<system-reminder>` or user-input
  boundary tags. ([#4839])
- **sandbox:** Harden local Docker sandbox containers: published ports bind
  the Docker bridge gateway instead of `0.0.0.0` when the sandbox host is
  non-loopback (`DEER_FLOW_SANDBOX_BIND_HOST=0.0.0.0` restores the broad
  bind), Docker's default seccomp profile replaces unconditional
  `seccomp=unconfined` (opt back in with `DEER_FLOW_SANDBOX_SECCOMP_UNCONFINED=1`),
  and containers drop all capabilities, get `no-new-privileges`, and run with
  bounded resources. ([#4986])
- **authz:** Enforce run-create authorization on stateless stream/wait
  endpoints (`runs:create`), and require both `threads:write` and
  `runs:create` for scheduled-task create, update, resume, and manual-trigger
  mutations. ([#5030])
- **authz:** Re-check the authorization policy before reusing a persisted
  sandbox, so a revoked `sandbox:execute` grant takes effect on the next
  sandbox-backed turn instead of outliving the policy in the cached sandbox.
  ([#5006])
- **skills:** Enforce custom-Agent skill allowlists at the sandbox filesystem
  level: an explicit `skills` policy materializes a signed per-user/thread
  skills view, so a custom agent with shell or file tools can no longer read
  skills its policy excludes. ([#5077])
- **runs:** Reject cancel/rollback actions on GET stream joins with
  `405 Method Not Allowed` - cancel-then-stream is a POST operation - closing
  a state change that CSRF middleware deliberately exempted on safe methods;
  action-less GET joins are unchanged. ([#5092])

### Documentation

- **docs:** Clarify how `LocalSandboxProvider` resolves `sandbox.mounts[].host_path`
  under production Docker, with gateway bind-mount and config examples. ([#3833])
- **docs:** Document that Crawl4AI >= 0.9 requires a bearer token. ([#4518])
- **docs:** Document the GitHub inbound-dedupe TTL semantics, including what
  redeliveries are not deduped, and tighten the redelivery tests. ([#4274])
- **docs:** Update the agent AGENTS.md and ARCHITECTURE.md guides. ([#4817])
- **docs:** Document the Honcho memory backend with a dedicated guide and a
  long-term memory section entry in the README. ([#4822])

### Internal

- **tests:** Migrate frontend unit tests to rstest and run hook-level tests in
  a DOM environment. ([#3703], [#4453])
- **tests:** Require explicit opt-in for live client tests. ([#4482])
- **tests:** Rename the LLM-error test stand-in instead of the shared
  FakeError. ([#4744])
- **tests:** Replace the magic unwritable absolute path in tool-output tests
  with a self-constructed failure condition. ([#4722])
- **tests:** Add multi-turn message-stream invariants as graph integration
  tests. ([#3708])
- **tests:** Add trace-based behavioral tests with Monocle Test Tools,
  asserting agent routing, tool calls, and token/duration cost. ([#4025])
- **tests:** Cover passive skill tool visibility in the MCP layer. ([#4247])
- **tests:** Add SQL and concurrent-reconciler coverage for lease-aware orphan
  recovery. ([#4427])
- **tests:** Restore memory updater regression coverage. ([#4490])
- **tests:** Lock in POST logout from the gateway-offline banner. ([#4506])
- **tests:** Document known instance-client false negatives in the SkillScan
  tests. ([#4644])
- **refactor:** Extract frontend placeholder detection into a tested utility.
  ([#3783])
- **refactor:** Consolidate E2B client lifecycle helpers and reuse the kill
  helper during warm-pool eviction. ([#4262], [#4298])
- **refactor:** Name the E2B capacity-ledger meta-field count so the admission
  offset is explicit. ([#4764])
- **dev:** Trace self/cls attribute chains and local aliases in the
  blocking-IO detector's call graph, closing false negatives. ([#4200])
- **ci:** Publish the lark-cli-init and lark-broker images. ([#4558])
- **dev:** Route host-side pnpm consumers through a shared runner with a
  Corepack fallback so local workflows work without a pnpm shim. ([#4405])
- **bench:** Add an isolated checkpoint channel-mode benchmark comparing `full`
  and `delta` across latency, storage, and replay metrics. ([#4395])
- **deps:** Bump `cryptography` 49.0.0 -> 50.0.0, `postcss` 8.4.31 -> 8.5.25,
  `h2` 4.3.0 -> 4.4.1, `langgraph-checkpoint-sqlite` and
  `langgraph-checkpoint-postgres` 3.1.0 -> 3.1.1, and `nanoid` 5.1.6 -> 5.1.16.
  ([#4681], [#4683], [#4737], [#4738], [#4747], [#4748])
- **bench:** Add a reproducible hybrid memory-eviction evaluation under
  `backend/scripts/benchmark/deermem_eviction/` with a deterministic,
  blind-by-construction grader for the #4789 policy. ([#4810])
- **bench:** Measure Postgres checkpoint/blob/write storage growth in the
  checkpoint benchmark alongside memory and SQLite. ([#5051])
- **tests:** Exclude `tests/blocking_io/` from `make test`; the dedicated
  `make test-blocking-io` suite (and its CI workflow) remains the owner.
  ([#5105])
- **refactor:** Share sandbox identity derivation and acquire serialization
  across the five remote sandbox providers (RFC #4741), replacing five
  per-provider lock tables that grew unboundedly with process lifetime;
  derived ids are pinned byte-identical by per-provider golden vectors.
  ([#5089])

## [2.0.0] — 2026-06-15

DeerFlow 2.0 is a ground-up rewrite around a "super agent" harness with
sub-agents, persistent memory, sandbox execution, and an extensible
skills/tools system. It shares no code with the 1.x line, which now lives on
the [`main-1.x` branch](https://github.com/bytedance/deer-flow/tree/main-1.x).

This release closes [milestone 2.0.0](https://github.com/bytedance/deer-flow/milestone/1)
with **180 merged pull requests** since the first 2.0 milestone tag.

### ⚠ Breaking changes

- **harness:** Hydrate runs from `RunStore` and persist interrupted status. Run
  cancellation/multitask semantics now require a working RunStore on the
  worker that owns the run; cross-worker cancels return 409 instead of
  silently appearing successful. ([#2932])

### Added

#### Agents & runtime
- **agent:** Custom-agent self-updates with user isolation — agents can persist
  edits to their own `SOUL.md` / `config.yaml` from inside a normal chat.
  ([#2713])
- **loop-detection:** Make loop detection configurable with per-tool frequency
  overrides; keep configurable on/off switch. ([#2586], [#2711])
- **loop-detection:** Defer warning injection so detector pairs cleanly with
  tool-call lifecycle. ([#2752])
- **run:** Propagate `model_name` from the gateway request through the runtime
  and persistence stack into the SQLite-backed store. ([#2775])
- **subagents:** Stream subagent token usage to the header via terminal task
  events. ([#2882])
- **memory:** Add `memory.token_counting` config to opt out of tiktoken for
  network-restricted deployments. ([#3465])
- **suggest:** Make AI follow-up question suggestions optional. ([#3591])

#### Models & integrations
- **models:** Add StepFun reasoning model adapter. ([#3461])
- **community:** Add Brave Search web search tool. ([#3528])
- **channels:** Enhance Discord with mention-only mode, thread routing, and
  typing indicators. ([#2842])
- **im:** Add user-owned IM channel connections — users can bind their own
  Slack/Telegram/Discord/Feishu/DingTalk/WeChat/WeCom accounts on top of the
  operator-configured bots. ([#3487])
- **models:** Add patched MiMo reasoning content support. ([#3298])
- **models:** Add MiniMax provider for image/video/podcast skills plus a new
  music-generation skill. ([#3437])
- **community:** Add SearXNG and Browserless web search/fetch tools. ([#3451])
- **community:** Add Serper Google Images provider for `image_search`. ([#3575])
- **channels:** Stream Telegram agent replies by editing the placeholder
  message in place. ([#3534])

#### Observability
- **trace:** Set the LangGraph trace name to `lead_agent` (or the custom
  agent's `agent_name`) for cleaner Langfuse/LangSmith traces. ([#3101])
- **frontend:** Refine token usage display modes. ([#2329])
- **defaults:** Enable token usage tracking by default. ([#2841])
- **defaults:** Raise default summarization trigger threshold. ([#3174])
- **trace:** Attribute subagent spans to the parent thread's Langfuse trace.
  ([#3611])

#### Skills
- **skill:** Add `blocking-io-guard` skill for blocking-IO triage and runtime
  anchors. ([#3503])
- **skill:** Add maintainer issue and PR workflow skill. ([#3554])
- **skill:** Strengthen the maintainer orchestrator review workflow. ([#3606])

### Performance

- **harness:** Push thread metadata filters into SQL instead of post-filtering
  in Python. ([#2865])
- **runtime:** Index runs by `thread_id` to avoid O(n) scans in `RunManager`.
  ([#3499])
- **runtime:** Index messages in `MemoryRunEventStore` to avoid O(n) scans.
  ([#3531])
- **persistence:** Cache `Base.to_dict` column reflection per class. ([#3654])
- **sandbox:** Speed up `should_ignore_name` in glob/grep walks. ([#3657])

### Security

- **upload:** Reject symlinked upload destinations. ([#2623])
- **uploads:** Add Windows support for safe symlink-protected uploads.
  ([#2794])
- **mcp:** Mask sensitive values in MCP config API responses. ([#2667])
- **mcp:** Harden the MCP config endpoint against malformed input. ([#3425])
- **auth:** Reject cross-site auth POSTs. ([#2740])
- **gateway:** Cap skill artifact preview decompression to prevent
  zip-bomb-style abuse. ([#2963])
- **sandbox:** Mount the host Docker socket only in aio (DooD) sandbox mode.
  ([#3517])
- **sandbox:** Do not bind-mount host CLI auth dirs by default. ([#3521])

### Fixed

#### Runtime, gateway & persistence
- **runtime:** Rollback restore checkpoint now supersedes newer checkpoints.
  ([#2582])
- **runtime:** Persist run message summaries. ([#2850])
- **runtime:** Bound `write_file` execution-failure observations to keep
  failure traces from blowing out the context. ([#3133])
- **runtime:** Protect the sync singleton's init and reset paths. ([#3413])
- **runtime:** Avoid PostgreSQL aggregate `FOR UPDATE` on run events.
  ([#2962])
- **runs:** Restore historical runs from persistent store after a gateway
  restart. ([#2989])
- **gateway:** Return ISO 8601 timestamps from threads endpoints. ([#2599])
- **gateway:** Make cancel idempotent for already-interrupted runs. ([#3058])
- **gateway:** Split `stream_existing_run` into per-method routes for unique
  OpenAPI `operationId`s. ([#3228])
- **events:** Serialize structured DB event content. ([#2762])
- **persistence:** Emit timezone-aware timestamps from SQLite-backed stores.
  ([#3130])
- **persistence:** Reuse token usage model grouping expression. ([#2910])
- **runs:** Ignore stale run reconnect conflicts. ([#3284])
- **nginx:** Defer CORS to the gateway allowlist instead of double-applying it.
  ([#2861])
- **persistence:** Fix runtime journal run lifecycle events. ([#3470])
- **gateway:** Enforce thread ownership on stateless run endpoints. ([#3473])
- **runtime:** Propagate interrupt through SSE values events for the LangGraph
  SDK. ([#3605])
- **serialization:** Strip base64 image data from streamed values events.
  ([#3631])
- **history:** Strip base64 image data from REST endpoint responses. ([#3535])
- **gateway:** Attribute token usage to the actual models. ([#3658])

#### Agents, subagents & middleware
- **subagents:** Make subagent timeout terminal state atomic. ([#2583])
- **subagents:** Use model override for tools and middleware. ([#2641])
- **subagents:** Consolidate `system_prompt` and skills into a single
  `SystemMessage`. ([#2701])
- **subagent:** Isolate subagents from the parent run's checkpointer.
  ([#3559])
- **agents:** Make `update_agent` honor `runtime.context` `user_id` like
  `setup_agent` does. ([#2867])
- **agents:** Resolve duplicate `todos` channel type conflict in
  `TodoMiddleware`. ([#3200])
- **agents:** Offload blocking filesystem IO in the custom-agent router off
  the event loop. ([#3457])
- **agents:** Keep new agent bootstrap in user scope. ([#2784])
- **loop-detection:** Keep tool-call pairing on warn injection. ([#2725])
- **middleware:** Sync raw tool-call metadata. ([#2757])
- **middleware:** Handle invalid tool calls in dangling pairing middleware.
  ([#2891])
- **middleware:** Prevent todo completion reminder IM-message leak. ([#2907])
- **middleware:** Normalize tool result adjacency before model calls.
  ([#2939])
- **agents:** Require `config.yaml` in `resolve_agent_dir` to skip memory-only
  directories. ([#3481])
- **agents:** Sync `agent_name` across context/configurable and reject empty
  soul. ([#3553])
- **middleware:** Offload the uploads scan in `UploadsMiddleware` off the event
  loop. ([#3311])
- **middleware:** Offload memory injection off the event loop to prevent
  tiktoken blocking. ([#3411])
- **middleware:** Externalize oversized tool output into the sandbox for
  non-mounted sandboxes. ([#3417])
- **middleware:** Preserve the sandbox reducer in middleware state. ([#3629])
- **subagents:** Raise general-purpose `max_turns` to 150 and default timeout to
  30 min. ([#3610])

#### Memory & tracing
- **memory:** Replace short-lived `asyncio.run()` with a persistent event
  loop. ([#2627])
- **memory:** Isolate queued memory updates by agent. ([#2941])
- **memory:** Parse wrapped memory-update JSON responses. ([#3252])
- **tracing:** Propagate `session_id` and `user_id` into Langfuse traces.
  ([#2944])
- **trace:** Decode unicode escape sequences in non-ASCII memory trace info.
  ([#3104])

#### Tools, sandbox & MCP
- **mcp:** Fix env resolution in MCP config lists. ([#2556])
- **models:** Record Codex token usage in `usage_metadata`. ([#2585])
- **sandbox:** Supplement `list_running` in `RemoteSandboxBackend`. ([#2716])
- **sandbox:** Disable MSYS path conversion for Git Bash on Windows.
  ([#2766])
- **sandbox:** Avoid blocking sandbox readiness polling. ([#2822])
- **sandbox:** Uphold the `/mnt/user-data` contract at the `Sandbox` API
  boundary. ([#2881])
- **sandbox:** Scope provisioner PVC data by user. ([#2973])
- **sandbox:** Merge idempotent sandbox state updates. ([#3518])
- **tools:** Introduce `Runtime` type alias to eliminate Pydantic serialization
  warnings. ([#2774])
- **tools:** Preserve `tool_search` promotions across re-entrant
  `get_available_tools`. ([#2885])
- **harness:** Wrap async-only config tools for sync client execution.
  ([#2878])
- **harness:** Wrap all async-only tools for sync clients. ([#2935])
- **tool-search:** Reliably hide deferred MCP schemas by removing the
  ContextVar. ([#3342])
- **search:** Fix DDGS Wikipedia region handling. ([#3423])
- **web_fetch:** Support a proxy for the Jina reader in restricted networks.
  ([#3430])
- **sandbox:** Persist lazily-acquired sandbox state via `Command`. ([#3464])
- **sandbox:** Fix stale AIO sandbox cache reuse. ([#3494])
- **sandbox:** Create a shell session before retrying on a fresh id. ([#3577])
- **sandbox:** Stop flagging string-literal path fragments as unsafe absolute
  paths. ([#3623])
- **sandbox:** Return an actionable hint when `read_file` hits a binary file.
  ([#3624])
- **mcp:** Make stdio MCP-produced files resolvable via virtual sandbox paths.
  ([#3600])
- **mcp:** Surface admin-required state on the settings tools page. ([#3533])
- **mcp:** Add a tools cache reset endpoint. ([#3602])
- **uploads:** Fix the upload file size contract. ([#3408])

#### Skills & channels
- **skills:** Enforce `allowed-tools` metadata. ([#2626])
- **skills:** Harden slash skill activation across chat channels. ([#3466])
- **skills:** Fix custom skill install permissions. ([#3241])
- **channels:** Authenticate gateway command requests. ([#2742])
- **skills:** Surface the offending line and a quoting hint on SKILL.md YAML
  errors. ([#3335])
- **skills:** Keep skill archive installation off the event loop. ([#3505])
- **channels:** Ignore hidden control messages when extracting replies.
  ([#3270])
- **channels:** Reload config on channel restart. ([#3514])
- **channels:** Surface WeCom WebSocket connection failures. ([#3526])
- **channels:** Close the Discord file handle after upload. ([#3561])
- **channels:** Require a bound identity for user-owned IM messages. ([#3578])
- **channels:** Scope IM files and helper commands to the owner. ([#3579])
- **channels:** Make runtime provider state authoritative. ([#3580])
- **channels:** Harden runtime credential management APIs. ([#3581])
- **channels:** Make the channel connect flow deterministic. ([#3582])
- **channels:** Centralize shared channel retry helpers. ([#3583])
- **channels:** Add operational guardrails. ([#3584])
- **channels:** Unsubscribe channel listeners by equality. ([#3608])

#### Auth
- **auth:** Replace setup-status 429 rate limit with a cached response.
  ([#2915])
- **auth:** Persist auto-generated JWT secret so it survives restarts.
  ([#2933])
- **auth:** Align auth-disabled mode with mock history loading. ([#3471])

#### Frontend
- **frontend:** Restore `localhost` fallback for `getGatewayConfig` in prod
  mode. ([#2718])
- **chat:** Prevent the first user message from being swallowed in new
  conversations. ([#2731])
- **frontend:** Use backend thread token usage for the header total. ([#2800])
- **frontend:** Wait for async chat submit before clearing the input.
  ([#2940])
- **frontend:** Resolve login page flickering and the resize-observer loop.
  ([#2954])
- **frontend:** Deduplicate restored thread messages. ([#2958])
- **frontend:** Avoid duplicate optimistic user message. ([#3002])
- **frontend:** Hide the copy button for streaming assistant messages.
  ([#3176])
- **frontend:** Show a new thread in the sidebar immediately on creation.
  ([#3283])
- **frontend:** Isolate new chat thread messages. ([#3508])
- **frontend:** Cap deeply nested list indentation to prevent render crashes.
  ([#3393], [#3570])
- **token-usage:** Dedupe token usage aggregation by message id. ([#2770])
- **frontend:** Fall back to Streamdown clipboard copy. ([#3397])
- **frontend:** Remove the Backspace shortcut for deleting prompt attachments.
  ([#3410])
- **frontend:** Restructure the Memory settings toolbar into two rows. ([#3433])
- **suggestions:** Strip inline `<think>` reasoning before parsing follow-up
  questions. ([#3435])
- **frontend:** Stop fetching follow-up suggestions when they are disabled.
  ([#3599])
- **frontend:** Paginate the workspace chat list beyond 50 threads. ([#3485])
- **frontend:** Prevent user message bubble overflow with long unbreakable
  strings. ([#3488])
- **frontend:** Keep the workspace interactive when the SSR auth probe cannot
  reach the gateway. ([#3495])
- **frontend:** Render user messages as plain text and cap blockquote nesting.
  ([#3502])
- **frontend:** Reset the active chat after deletion. ([#3519])
- **frontend:** Improve the mobile workspace layout. ([#3646])
- **frontend:** Render full content for multi-part AI messages. ([#3649])

#### Build, deploy, scripts & config
- **packaging:** Add `postgres` extra for store/checkpointer support; clarify
  install guidance. ([#2584])
- **harness:** Resolve runtime paths from the project root. ([#2642])
- **docker:** Force nginx to resolve upstream names at request time.
  ([#2717])
- **docker:** Default Gateway to a single worker to prevent multi-worker
  breakage. ([#3475])
- **scripts:** Preserve `uv` extras across `make dev` restarts. ([#2767],
  [#2754])
- **scripts:** Clean up local nginx on stop. ([#3005])
- **deploy:** Fall back to `python` / `openssl` when `python3` is absent for
  secret generation. ([#3074])
- **config:** Make the reload boundary discoverable from code. ([#3144],
  [#3153])
- **replay-e2e:** Key replay fixtures by caller and conversation. ([#3453])
- **setup:** Refresh LLM provider wizard defaults. ([#3421])
- **config:** Coerce null `config.yaml` list sections to an empty list. ([#3434])
- **scripts:** Exclude runtime state from gateway reload. ([#3426])
- **scripts:** Create the backend/sandbox dir before the uvicorn reload-exclude.
  ([#3460])
- **scripts:** Stop next-server correctly after `make start-daemon`. ([#3498])
- **makefile:** Fix per-commit hooks installation. ([#3569])
- **replay-e2e:** Match replay by conversation, not the living system prompt.
  ([#3436])

### Changed

- **provider (refactor):** Share assistant payload replay matching across
  providers. ([#3307])
- **lead-agent (refactor):** Make `build_middlewares` public to drop the last
  cross-module private import. ([#3458])
- **todo (refactor):** Remove the unused completion reminder counter. ([#3530])

### Documentation

- Document blocking-IO detection usage and maintenance. ([#3233])
- Clean standalone LangGraph server remnants from docs. ([#3301])
- Add AI assistance disclosure to the PR template and CONTRIBUTING. ([#3398])
- Document custom AIO sandbox images. ([#3548])

### Internal

- **dev:** Add async/thread boundary detector. ([#2936])
- **runtime:** Add lifecycle end-to-end coverage. ([#2946])
- **windows:** Add `PYTHONIOENCODING` and `PYTHONUTF8` to backend Makefile
  targets. ([#3069])
- **blocking-io:** Fail-loud repo-root resolution and shared detector CLI
  shim. ([#3512])
- **runtime:** Add a Blockbuster runtime anchor for `JsonlRunEventStore` async
  IO. ([#3313])
- **ci:** Consolidate PR/issue labeling and fix the reviewing-job crash and
  label thrash. ([#3455])

[2.0.0]: https://github.com/bytedance/deer-flow/releases/tag/v2.0.0

[#2329]: https://github.com/bytedance/deer-flow/pull/2329
[#2556]: https://github.com/bytedance/deer-flow/pull/2556
[#2582]: https://github.com/bytedance/deer-flow/pull/2582
[#2583]: https://github.com/bytedance/deer-flow/pull/2583
[#2584]: https://github.com/bytedance/deer-flow/pull/2584
[#2585]: https://github.com/bytedance/deer-flow/pull/2585
[#2586]: https://github.com/bytedance/deer-flow/pull/2586
[#2599]: https://github.com/bytedance/deer-flow/pull/2599
[#2623]: https://github.com/bytedance/deer-flow/pull/2623
[#2626]: https://github.com/bytedance/deer-flow/pull/2626
[#2627]: https://github.com/bytedance/deer-flow/pull/2627
[#2641]: https://github.com/bytedance/deer-flow/pull/2641
[#2642]: https://github.com/bytedance/deer-flow/pull/2642
[#2667]: https://github.com/bytedance/deer-flow/pull/2667
[#2701]: https://github.com/bytedance/deer-flow/pull/2701
[#2711]: https://github.com/bytedance/deer-flow/pull/2711
[#2713]: https://github.com/bytedance/deer-flow/pull/2713
[#2716]: https://github.com/bytedance/deer-flow/pull/2716
[#2717]: https://github.com/bytedance/deer-flow/pull/2717
[#2718]: https://github.com/bytedance/deer-flow/pull/2718
[#2725]: https://github.com/bytedance/deer-flow/pull/2725
[#2731]: https://github.com/bytedance/deer-flow/pull/2731
[#2740]: https://github.com/bytedance/deer-flow/pull/2740
[#2742]: https://github.com/bytedance/deer-flow/pull/2742
[#2752]: https://github.com/bytedance/deer-flow/pull/2752
[#2754]: https://github.com/bytedance/deer-flow/pull/2754
[#2757]: https://github.com/bytedance/deer-flow/pull/2757
[#2762]: https://github.com/bytedance/deer-flow/pull/2762
[#2766]: https://github.com/bytedance/deer-flow/pull/2766
[#2767]: https://github.com/bytedance/deer-flow/pull/2767
[#2770]: https://github.com/bytedance/deer-flow/pull/2770
[#2774]: https://github.com/bytedance/deer-flow/pull/2774
[#2775]: https://github.com/bytedance/deer-flow/pull/2775
[#2784]: https://github.com/bytedance/deer-flow/pull/2784
[#2794]: https://github.com/bytedance/deer-flow/pull/2794
[#2800]: https://github.com/bytedance/deer-flow/pull/2800
[#2822]: https://github.com/bytedance/deer-flow/pull/2822
[#2841]: https://github.com/bytedance/deer-flow/pull/2841
[#2842]: https://github.com/bytedance/deer-flow/pull/2842
[#2850]: https://github.com/bytedance/deer-flow/pull/2850
[#2861]: https://github.com/bytedance/deer-flow/pull/2861
[#2865]: https://github.com/bytedance/deer-flow/pull/2865
[#2867]: https://github.com/bytedance/deer-flow/pull/2867
[#2878]: https://github.com/bytedance/deer-flow/pull/2878
[#2881]: https://github.com/bytedance/deer-flow/pull/2881
[#2882]: https://github.com/bytedance/deer-flow/pull/2882
[#2885]: https://github.com/bytedance/deer-flow/pull/2885
[#2891]: https://github.com/bytedance/deer-flow/pull/2891
[#2907]: https://github.com/bytedance/deer-flow/pull/2907
[#2910]: https://github.com/bytedance/deer-flow/pull/2910
[#2915]: https://github.com/bytedance/deer-flow/pull/2915
[#2932]: https://github.com/bytedance/deer-flow/pull/2932
[#2933]: https://github.com/bytedance/deer-flow/pull/2933
[#2935]: https://github.com/bytedance/deer-flow/pull/2935
[#2936]: https://github.com/bytedance/deer-flow/pull/2936
[#2939]: https://github.com/bytedance/deer-flow/pull/2939
[#2940]: https://github.com/bytedance/deer-flow/pull/2940
[#2941]: https://github.com/bytedance/deer-flow/pull/2941
[#2944]: https://github.com/bytedance/deer-flow/pull/2944
[#2946]: https://github.com/bytedance/deer-flow/pull/2946
[#2954]: https://github.com/bytedance/deer-flow/pull/2954
[#2958]: https://github.com/bytedance/deer-flow/pull/2958
[#2962]: https://github.com/bytedance/deer-flow/pull/2962
[#2963]: https://github.com/bytedance/deer-flow/pull/2963
[#2973]: https://github.com/bytedance/deer-flow/pull/2973
[#2989]: https://github.com/bytedance/deer-flow/pull/2989
[#3002]: https://github.com/bytedance/deer-flow/pull/3002
[#3005]: https://github.com/bytedance/deer-flow/pull/3005
[#3033]: https://github.com/bytedance/deer-flow/pull/3033
[#3058]: https://github.com/bytedance/deer-flow/pull/3058
[#3069]: https://github.com/bytedance/deer-flow/pull/3069
[#3074]: https://github.com/bytedance/deer-flow/pull/3074
[#3101]: https://github.com/bytedance/deer-flow/pull/3101
[#3104]: https://github.com/bytedance/deer-flow/pull/3104
[#3130]: https://github.com/bytedance/deer-flow/pull/3130
[#3133]: https://github.com/bytedance/deer-flow/pull/3133
[#3144]: https://github.com/bytedance/deer-flow/pull/3144
[#3153]: https://github.com/bytedance/deer-flow/pull/3153
[#3174]: https://github.com/bytedance/deer-flow/pull/3174
[#3176]: https://github.com/bytedance/deer-flow/pull/3176
[#3191]: https://github.com/bytedance/deer-flow/pull/3191
[#3200]: https://github.com/bytedance/deer-flow/pull/3200
[#3228]: https://github.com/bytedance/deer-flow/pull/3228
[#3233]: https://github.com/bytedance/deer-flow/pull/3233
[#3241]: https://github.com/bytedance/deer-flow/pull/3241
[#3252]: https://github.com/bytedance/deer-flow/pull/3252
[#3270]: https://github.com/bytedance/deer-flow/pull/3270
[#3283]: https://github.com/bytedance/deer-flow/pull/3283
[#3284]: https://github.com/bytedance/deer-flow/pull/3284
[#3298]: https://github.com/bytedance/deer-flow/pull/3298
[#3301]: https://github.com/bytedance/deer-flow/pull/3301
[#3307]: https://github.com/bytedance/deer-flow/pull/3307
[#3311]: https://github.com/bytedance/deer-flow/pull/3311
[#3313]: https://github.com/bytedance/deer-flow/pull/3313
[#3335]: https://github.com/bytedance/deer-flow/pull/3335
[#3342]: https://github.com/bytedance/deer-flow/pull/3342
[#3377]: https://github.com/bytedance/deer-flow/pull/3377
[#3393]: https://github.com/bytedance/deer-flow/pull/3393
[#3397]: https://github.com/bytedance/deer-flow/pull/3397
[#3398]: https://github.com/bytedance/deer-flow/pull/3398
[#3408]: https://github.com/bytedance/deer-flow/pull/3408
[#3410]: https://github.com/bytedance/deer-flow/pull/3410
[#3411]: https://github.com/bytedance/deer-flow/pull/3411
[#3412]: https://github.com/bytedance/deer-flow/pull/3412
[#3413]: https://github.com/bytedance/deer-flow/pull/3413
[#3417]: https://github.com/bytedance/deer-flow/pull/3417
[#3421]: https://github.com/bytedance/deer-flow/pull/3421
[#3423]: https://github.com/bytedance/deer-flow/pull/3423
[#3425]: https://github.com/bytedance/deer-flow/pull/3425
[#3426]: https://github.com/bytedance/deer-flow/pull/3426
[#3428]: https://github.com/bytedance/deer-flow/pull/3428
[#3430]: https://github.com/bytedance/deer-flow/pull/3430
[#3433]: https://github.com/bytedance/deer-flow/pull/3433
[#3434]: https://github.com/bytedance/deer-flow/pull/3434
[#3435]: https://github.com/bytedance/deer-flow/pull/3435
[#3436]: https://github.com/bytedance/deer-flow/pull/3436
[#3437]: https://github.com/bytedance/deer-flow/pull/3437
[#3451]: https://github.com/bytedance/deer-flow/pull/3451
[#3453]: https://github.com/bytedance/deer-flow/pull/3453
[#3455]: https://github.com/bytedance/deer-flow/pull/3455
[#3457]: https://github.com/bytedance/deer-flow/pull/3457
[#3458]: https://github.com/bytedance/deer-flow/pull/3458
[#3460]: https://github.com/bytedance/deer-flow/pull/3460
[#3461]: https://github.com/bytedance/deer-flow/pull/3461
[#3464]: https://github.com/bytedance/deer-flow/pull/3464
[#3465]: https://github.com/bytedance/deer-flow/pull/3465
[#3466]: https://github.com/bytedance/deer-flow/pull/3466
[#3470]: https://github.com/bytedance/deer-flow/pull/3470
[#3471]: https://github.com/bytedance/deer-flow/pull/3471
[#3473]: https://github.com/bytedance/deer-flow/pull/3473
[#3475]: https://github.com/bytedance/deer-flow/pull/3475
[#3481]: https://github.com/bytedance/deer-flow/pull/3481
[#3485]: https://github.com/bytedance/deer-flow/pull/3485
[#3487]: https://github.com/bytedance/deer-flow/pull/3487
[#3488]: https://github.com/bytedance/deer-flow/pull/3488
[#3494]: https://github.com/bytedance/deer-flow/pull/3494
[#3495]: https://github.com/bytedance/deer-flow/pull/3495
[#3498]: https://github.com/bytedance/deer-flow/pull/3498
[#3499]: https://github.com/bytedance/deer-flow/pull/3499
[#3502]: https://github.com/bytedance/deer-flow/pull/3502
[#3503]: https://github.com/bytedance/deer-flow/pull/3503
[#3505]: https://github.com/bytedance/deer-flow/pull/3505
[#3506]: https://github.com/bytedance/deer-flow/pull/3506
[#3508]: https://github.com/bytedance/deer-flow/pull/3508
[#3512]: https://github.com/bytedance/deer-flow/pull/3512
[#3514]: https://github.com/bytedance/deer-flow/pull/3514
[#3517]: https://github.com/bytedance/deer-flow/pull/3517
[#3518]: https://github.com/bytedance/deer-flow/pull/3518
[#3519]: https://github.com/bytedance/deer-flow/pull/3519
[#3521]: https://github.com/bytedance/deer-flow/pull/3521
[#3526]: https://github.com/bytedance/deer-flow/pull/3526
[#3528]: https://github.com/bytedance/deer-flow/pull/3528
[#3530]: https://github.com/bytedance/deer-flow/pull/3530
[#3531]: https://github.com/bytedance/deer-flow/pull/3531
[#3533]: https://github.com/bytedance/deer-flow/pull/3533
[#3534]: https://github.com/bytedance/deer-flow/pull/3534
[#3535]: https://github.com/bytedance/deer-flow/pull/3535
[#3548]: https://github.com/bytedance/deer-flow/pull/3548
[#3551]: https://github.com/bytedance/deer-flow/pull/3551
[#3553]: https://github.com/bytedance/deer-flow/pull/3553
[#3554]: https://github.com/bytedance/deer-flow/pull/3554
[#3556]: https://github.com/bytedance/deer-flow/pull/3556
[#3557]: https://github.com/bytedance/deer-flow/pull/3557
[#3559]: https://github.com/bytedance/deer-flow/pull/3559
[#3561]: https://github.com/bytedance/deer-flow/pull/3561
[#3562]: https://github.com/bytedance/deer-flow/pull/3562
[#3563]: https://github.com/bytedance/deer-flow/pull/3563
[#3566]: https://github.com/bytedance/deer-flow/pull/3566
[#3569]: https://github.com/bytedance/deer-flow/pull/3569
[#3570]: https://github.com/bytedance/deer-flow/pull/3570
[#3573]: https://github.com/bytedance/deer-flow/pull/3573
[#3575]: https://github.com/bytedance/deer-flow/pull/3575
[#3577]: https://github.com/bytedance/deer-flow/pull/3577
[#3578]: https://github.com/bytedance/deer-flow/pull/3578
[#3579]: https://github.com/bytedance/deer-flow/pull/3579
[#3580]: https://github.com/bytedance/deer-flow/pull/3580
[#3581]: https://github.com/bytedance/deer-flow/pull/3581
[#3582]: https://github.com/bytedance/deer-flow/pull/3582
[#3583]: https://github.com/bytedance/deer-flow/pull/3583
[#3584]: https://github.com/bytedance/deer-flow/pull/3584
[#3585]: https://github.com/bytedance/deer-flow/pull/3585
[#3590]: https://github.com/bytedance/deer-flow/pull/3590
[#3591]: https://github.com/bytedance/deer-flow/pull/3591
[#3592]: https://github.com/bytedance/deer-flow/pull/3592
[#3599]: https://github.com/bytedance/deer-flow/pull/3599
[#3600]: https://github.com/bytedance/deer-flow/pull/3600
[#3601]: https://github.com/bytedance/deer-flow/pull/3601
[#3602]: https://github.com/bytedance/deer-flow/pull/3602
[#3605]: https://github.com/bytedance/deer-flow/pull/3605
[#3606]: https://github.com/bytedance/deer-flow/pull/3606
[#3608]: https://github.com/bytedance/deer-flow/pull/3608
[#3610]: https://github.com/bytedance/deer-flow/pull/3610
[#3611]: https://github.com/bytedance/deer-flow/pull/3611
[#3623]: https://github.com/bytedance/deer-flow/pull/3623
[#3624]: https://github.com/bytedance/deer-flow/pull/3624
[#3627]: https://github.com/bytedance/deer-flow/pull/3627
[#3629]: https://github.com/bytedance/deer-flow/pull/3629
[#3631]: https://github.com/bytedance/deer-flow/pull/3631
[#3637]: https://github.com/bytedance/deer-flow/pull/3637
[#3644]: https://github.com/bytedance/deer-flow/pull/3644
[#3646]: https://github.com/bytedance/deer-flow/pull/3646
[#3648]: https://github.com/bytedance/deer-flow/pull/3648
[#3649]: https://github.com/bytedance/deer-flow/pull/3649
[#3651]: https://github.com/bytedance/deer-flow/pull/3651
[#3654]: https://github.com/bytedance/deer-flow/pull/3654
[#3657]: https://github.com/bytedance/deer-flow/pull/3657
[#3658]: https://github.com/bytedance/deer-flow/pull/3658
[#3661]: https://github.com/bytedance/deer-flow/pull/3661
[#3662]: https://github.com/bytedance/deer-flow/pull/3662
[#3663]: https://github.com/bytedance/deer-flow/pull/3663
[#3665]: https://github.com/bytedance/deer-flow/pull/3665
[#3673]: https://github.com/bytedance/deer-flow/pull/3673
[#3674]: https://github.com/bytedance/deer-flow/pull/3674
[#3675]: https://github.com/bytedance/deer-flow/pull/3675
[#3685]: https://github.com/bytedance/deer-flow/pull/3685
[#3686]: https://github.com/bytedance/deer-flow/pull/3686
[#3687]: https://github.com/bytedance/deer-flow/pull/3687
[#3698]: https://github.com/bytedance/deer-flow/pull/3698
[#3709]: https://github.com/bytedance/deer-flow/pull/3709
[#3711]: https://github.com/bytedance/deer-flow/pull/3711
[#3713]: https://github.com/bytedance/deer-flow/pull/3713
[#3714]: https://github.com/bytedance/deer-flow/pull/3714
[#3718]: https://github.com/bytedance/deer-flow/pull/3718
[#3719]: https://github.com/bytedance/deer-flow/pull/3719
[#3729]: https://github.com/bytedance/deer-flow/pull/3729
[#3730]: https://github.com/bytedance/deer-flow/pull/3730
[#3733]: https://github.com/bytedance/deer-flow/pull/3733
[#3740]: https://github.com/bytedance/deer-flow/pull/3740
[#3753]: https://github.com/bytedance/deer-flow/pull/3753
[#3760]: https://github.com/bytedance/deer-flow/pull/3760
[#3764]: https://github.com/bytedance/deer-flow/pull/3764
[#3768]: https://github.com/bytedance/deer-flow/pull/3768
[#3769]: https://github.com/bytedance/deer-flow/pull/3769
[#3770]: https://github.com/bytedance/deer-flow/pull/3770
[#3772]: https://github.com/bytedance/deer-flow/pull/3772
[#3775]: https://github.com/bytedance/deer-flow/pull/3775
[#3786]: https://github.com/bytedance/deer-flow/pull/3786
[#3790]: https://github.com/bytedance/deer-flow/pull/3790
[#3791]: https://github.com/bytedance/deer-flow/pull/3791
[#3794]: https://github.com/bytedance/deer-flow/pull/3794
[#3797]: https://github.com/bytedance/deer-flow/pull/3797
[#3800]: https://github.com/bytedance/deer-flow/pull/3800
[#3809]: https://github.com/bytedance/deer-flow/pull/3809
[#3810]: https://github.com/bytedance/deer-flow/pull/3810
[#3812]: https://github.com/bytedance/deer-flow/pull/3812
[#3821]: https://github.com/bytedance/deer-flow/pull/3821
[#3826]: https://github.com/bytedance/deer-flow/pull/3826
[#3828]: https://github.com/bytedance/deer-flow/pull/3828
[#3837]: https://github.com/bytedance/deer-flow/pull/3837
[#3839]: https://github.com/bytedance/deer-flow/pull/3839
[#3843]: https://github.com/bytedance/deer-flow/pull/3843
[#3845]: https://github.com/bytedance/deer-flow/pull/3845
[#3854]: https://github.com/bytedance/deer-flow/pull/3854
[#3855]: https://github.com/bytedance/deer-flow/pull/3855
[#3856]: https://github.com/bytedance/deer-flow/pull/3856
[#3858]: https://github.com/bytedance/deer-flow/pull/3858
[#3860]: https://github.com/bytedance/deer-flow/pull/3860
[#3866]: https://github.com/bytedance/deer-flow/pull/3866
[#3869]: https://github.com/bytedance/deer-flow/pull/3869
[#3870]: https://github.com/bytedance/deer-flow/pull/3870
[#3871]: https://github.com/bytedance/deer-flow/pull/3871
[#3872]: https://github.com/bytedance/deer-flow/pull/3872
[#3874]: https://github.com/bytedance/deer-flow/pull/3874
[#3877]: https://github.com/bytedance/deer-flow/pull/3877
[#3878]: https://github.com/bytedance/deer-flow/pull/3878
[#3880]: https://github.com/bytedance/deer-flow/pull/3880
[#3881]: https://github.com/bytedance/deer-flow/pull/3881
[#3883]: https://github.com/bytedance/deer-flow/pull/3883
[#3885]: https://github.com/bytedance/deer-flow/pull/3885
[#3886]: https://github.com/bytedance/deer-flow/pull/3886
[#3887]: https://github.com/bytedance/deer-flow/pull/3887
[#3889]: https://github.com/bytedance/deer-flow/pull/3889
[#3897]: https://github.com/bytedance/deer-flow/pull/3897
[#3900]: https://github.com/bytedance/deer-flow/pull/3900
[#3902]: https://github.com/bytedance/deer-flow/pull/3902
[#3904]: https://github.com/bytedance/deer-flow/pull/3904
[#3906]: https://github.com/bytedance/deer-flow/pull/3906
[#3907]: https://github.com/bytedance/deer-flow/pull/3907
[#3908]: https://github.com/bytedance/deer-flow/pull/3908
[#3912]: https://github.com/bytedance/deer-flow/pull/3912
[#3917]: https://github.com/bytedance/deer-flow/pull/3917
[#3920]: https://github.com/bytedance/deer-flow/pull/3920
[#3924]: https://github.com/bytedance/deer-flow/pull/3924
[#3926]: https://github.com/bytedance/deer-flow/pull/3926
[#3927]: https://github.com/bytedance/deer-flow/pull/3927
[#3928]: https://github.com/bytedance/deer-flow/pull/3928
[#3931]: https://github.com/bytedance/deer-flow/pull/3931
[#3934]: https://github.com/bytedance/deer-flow/pull/3934
[#3935]: https://github.com/bytedance/deer-flow/pull/3935
[#3938]: https://github.com/bytedance/deer-flow/pull/3938
[#3940]: https://github.com/bytedance/deer-flow/pull/3940
[#3941]: https://github.com/bytedance/deer-flow/pull/3941
[#3942]: https://github.com/bytedance/deer-flow/pull/3942
[#3944]: https://github.com/bytedance/deer-flow/pull/3944
[#3945]: https://github.com/bytedance/deer-flow/pull/3945
[#3949]: https://github.com/bytedance/deer-flow/pull/3949
[#3950]: https://github.com/bytedance/deer-flow/pull/3950
[#3951]: https://github.com/bytedance/deer-flow/pull/3951
[#3956]: https://github.com/bytedance/deer-flow/pull/3956
[#3959]: https://github.com/bytedance/deer-flow/pull/3959
[#3961]: https://github.com/bytedance/deer-flow/pull/3961
[#3964]: https://github.com/bytedance/deer-flow/pull/3964
[#3966]: https://github.com/bytedance/deer-flow/pull/3966
[#3967]: https://github.com/bytedance/deer-flow/pull/3967
[#3969]: https://github.com/bytedance/deer-flow/pull/3969
[#3971]: https://github.com/bytedance/deer-flow/pull/3971
[#3976]: https://github.com/bytedance/deer-flow/pull/3976
[#3980]: https://github.com/bytedance/deer-flow/pull/3980
[#3981]: https://github.com/bytedance/deer-flow/pull/3981
[#3982]: https://github.com/bytedance/deer-flow/pull/3982
[#3985]: https://github.com/bytedance/deer-flow/pull/3985
[#3986]: https://github.com/bytedance/deer-flow/pull/3986
[#3988]: https://github.com/bytedance/deer-flow/pull/3988
[#3989]: https://github.com/bytedance/deer-flow/pull/3989
[#3990]: https://github.com/bytedance/deer-flow/pull/3990
[#3991]: https://github.com/bytedance/deer-flow/pull/3991
[#3992]: https://github.com/bytedance/deer-flow/pull/3992
[#3993]: https://github.com/bytedance/deer-flow/pull/3993
[#3994]: https://github.com/bytedance/deer-flow/pull/3994
[#3996]: https://github.com/bytedance/deer-flow/pull/3996
[#4003]: https://github.com/bytedance/deer-flow/pull/4003
[#4004]: https://github.com/bytedance/deer-flow/pull/4004
[#4008]: https://github.com/bytedance/deer-flow/pull/4008
[#4009]: https://github.com/bytedance/deer-flow/pull/4009
[#4012]: https://github.com/bytedance/deer-flow/pull/4012
[#4016]: https://github.com/bytedance/deer-flow/pull/4016
[#4017]: https://github.com/bytedance/deer-flow/pull/4017
[#4018]: https://github.com/bytedance/deer-flow/pull/4018
[#4023]: https://github.com/bytedance/deer-flow/pull/4023
[#4024]: https://github.com/bytedance/deer-flow/pull/4024
[#4026]: https://github.com/bytedance/deer-flow/pull/4026
[#4028]: https://github.com/bytedance/deer-flow/pull/4028
[#4033]: https://github.com/bytedance/deer-flow/pull/4033
[#4034]: https://github.com/bytedance/deer-flow/pull/4034
[#4035]: https://github.com/bytedance/deer-flow/pull/4035
[#4036]: https://github.com/bytedance/deer-flow/pull/4036
[#4038]: https://github.com/bytedance/deer-flow/pull/4038
[#4040]: https://github.com/bytedance/deer-flow/pull/4040
[#4051]: https://github.com/bytedance/deer-flow/pull/4051
[#4052]: https://github.com/bytedance/deer-flow/pull/4052
[#4053]: https://github.com/bytedance/deer-flow/pull/4053
[#4055]: https://github.com/bytedance/deer-flow/pull/4055
[#4058]: https://github.com/bytedance/deer-flow/pull/4058
[#4059]: https://github.com/bytedance/deer-flow/pull/4059
[#4060]: https://github.com/bytedance/deer-flow/pull/4060
[#4064]: https://github.com/bytedance/deer-flow/pull/4064
[#4065]: https://github.com/bytedance/deer-flow/pull/4065
[#4067]: https://github.com/bytedance/deer-flow/pull/4067
[#4069]: https://github.com/bytedance/deer-flow/pull/4069
[#4072]: https://github.com/bytedance/deer-flow/pull/4072
[#4073]: https://github.com/bytedance/deer-flow/pull/4073
[#4074]: https://github.com/bytedance/deer-flow/pull/4074
[#4076]: https://github.com/bytedance/deer-flow/pull/4076
[#4077]: https://github.com/bytedance/deer-flow/pull/4077
[#4078]: https://github.com/bytedance/deer-flow/pull/4078
[#4079]: https://github.com/bytedance/deer-flow/pull/4079
[#4080]: https://github.com/bytedance/deer-flow/pull/4080
[#4081]: https://github.com/bytedance/deer-flow/pull/4081
[#4082]: https://github.com/bytedance/deer-flow/pull/4082
[#4084]: https://github.com/bytedance/deer-flow/pull/4084
[#4085]: https://github.com/bytedance/deer-flow/pull/4085
[#4090]: https://github.com/bytedance/deer-flow/pull/4090
[#4094]: https://github.com/bytedance/deer-flow/pull/4094
[#4095]: https://github.com/bytedance/deer-flow/issues/4095
[#4096]: https://github.com/bytedance/deer-flow/pull/4096
[#4097]: https://github.com/bytedance/deer-flow/pull/4097
[#4098]: https://github.com/bytedance/deer-flow/pull/4098
[#4099]: https://github.com/bytedance/deer-flow/pull/4099
[#4100]: https://github.com/bytedance/deer-flow/pull/4100
[#4101]: https://github.com/bytedance/deer-flow/pull/4101
[#4102]: https://github.com/bytedance/deer-flow/pull/4102
[#4103]: https://github.com/bytedance/deer-flow/pull/4103
[#4104]: https://github.com/bytedance/deer-flow/pull/4104
[#4105]: https://github.com/bytedance/deer-flow/pull/4105
[#4108]: https://github.com/bytedance/deer-flow/pull/4108
[#4114]: https://github.com/bytedance/deer-flow/pull/4114
[#4115]: https://github.com/bytedance/deer-flow/pull/4115
[#4117]: https://github.com/bytedance/deer-flow/pull/4117
[#4118]: https://github.com/bytedance/deer-flow/pull/4118
[#4119]: https://github.com/bytedance/deer-flow/pull/4119
[#4122]: https://github.com/bytedance/deer-flow/pull/4122
[#4124]: https://github.com/bytedance/deer-flow/pull/4124
[#4128]: https://github.com/bytedance/deer-flow/pull/4128
[#4129]: https://github.com/bytedance/deer-flow/pull/4129
[#4130]: https://github.com/bytedance/deer-flow/pull/4130
[#4131]: https://github.com/bytedance/deer-flow/pull/4131
[#4133]: https://github.com/bytedance/deer-flow/pull/4133
[#4136]: https://github.com/bytedance/deer-flow/pull/4136
[#4137]: https://github.com/bytedance/deer-flow/pull/4137
[#4140]: https://github.com/bytedance/deer-flow/pull/4140
[#4141]: https://github.com/bytedance/deer-flow/pull/4141
[#4143]: https://github.com/bytedance/deer-flow/pull/4143
[#4146]: https://github.com/bytedance/deer-flow/pull/4146
[#4147]: https://github.com/bytedance/deer-flow/pull/4147
[#4154]: https://github.com/bytedance/deer-flow/pull/4154
[#4155]: https://github.com/bytedance/deer-flow/pull/4155
[#4157]: https://github.com/bytedance/deer-flow/pull/4157
[#4160]: https://github.com/bytedance/deer-flow/pull/4160
[#4161]: https://github.com/bytedance/deer-flow/pull/4161
[#4162]: https://github.com/bytedance/deer-flow/pull/4162
[#4166]: https://github.com/bytedance/deer-flow/pull/4166
[#4169]: https://github.com/bytedance/deer-flow/pull/4169
[#4170]: https://github.com/bytedance/deer-flow/pull/4170
[#4171]: https://github.com/bytedance/deer-flow/pull/4171
[#4174]: https://github.com/bytedance/deer-flow/pull/4174
[#4178]: https://github.com/bytedance/deer-flow/pull/4178
[#4181]: https://github.com/bytedance/deer-flow/pull/4181
[#4187]: https://github.com/bytedance/deer-flow/pull/4187
[#4188]: https://github.com/bytedance/deer-flow/pull/4188
[#4190]: https://github.com/bytedance/deer-flow/pull/4190
[#4192]: https://github.com/bytedance/deer-flow/issues/4192
[#4193]: https://github.com/bytedance/deer-flow/pull/4193
[#4197]: https://github.com/bytedance/deer-flow/pull/4197
[#4199]: https://github.com/bytedance/deer-flow/pull/4199
[#4202]: https://github.com/bytedance/deer-flow/pull/4202
[#4203]: https://github.com/bytedance/deer-flow/pull/4203
[#4208]: https://github.com/bytedance/deer-flow/pull/4208
[#4209]: https://github.com/bytedance/deer-flow/pull/4209
[#4215]: https://github.com/bytedance/deer-flow/pull/4215
[#4217]: https://github.com/bytedance/deer-flow/pull/4217
[#4218]: https://github.com/bytedance/deer-flow/pull/4218
[#4219]: https://github.com/bytedance/deer-flow/pull/4219
[#4222]: https://github.com/bytedance/deer-flow/pull/4222
[#4225]: https://github.com/bytedance/deer-flow/pull/4225
[#4229]: https://github.com/bytedance/deer-flow/pull/4229
[#4230]: https://github.com/bytedance/deer-flow/pull/4230
[#4234]: https://github.com/bytedance/deer-flow/pull/4234
[#4235]: https://github.com/bytedance/deer-flow/pull/4235
[#4238]: https://github.com/bytedance/deer-flow/pull/4238
[#4239]: https://github.com/bytedance/deer-flow/pull/4239
[#4245]: https://github.com/bytedance/deer-flow/pull/4245
[#4246]: https://github.com/bytedance/deer-flow/pull/4246
[#4251]: https://github.com/bytedance/deer-flow/pull/4251
[#4255]: https://github.com/bytedance/deer-flow/pull/4255
[#4256]: https://github.com/bytedance/deer-flow/pull/4256
[#4260]: https://github.com/bytedance/deer-flow/pull/4260
[#4264]: https://github.com/bytedance/deer-flow/pull/4264
[#4267]: https://github.com/bytedance/deer-flow/pull/4267
[#4268]: https://github.com/bytedance/deer-flow/pull/4268
[#4277]: https://github.com/bytedance/deer-flow/pull/4277
[#4278]: https://github.com/bytedance/deer-flow/pull/4278
[#4279]: https://github.com/bytedance/deer-flow/pull/4279
[#4283]: https://github.com/bytedance/deer-flow/pull/4283
[#4287]: https://github.com/bytedance/deer-flow/pull/4287
[#4288]: https://github.com/bytedance/deer-flow/pull/4288
[#4292]: https://github.com/bytedance/deer-flow/pull/4292
[#4306]: https://github.com/bytedance/deer-flow/pull/4306
[#4309]: https://github.com/bytedance/deer-flow/pull/4309
[#4311]: https://github.com/bytedance/deer-flow/pull/4311
[#4315]: https://github.com/bytedance/deer-flow/pull/4315
[#4316]: https://github.com/bytedance/deer-flow/pull/4316
[#4324]: https://github.com/bytedance/deer-flow/issues/4324
[#4326]: https://github.com/bytedance/deer-flow/pull/4326
[#4337]: https://github.com/bytedance/deer-flow/pull/4337
[#4347]: https://github.com/bytedance/deer-flow/pull/4347
[#4348]: https://github.com/bytedance/deer-flow/pull/4348
[#4354]: https://github.com/bytedance/deer-flow/pull/4354
[#4355]: https://github.com/bytedance/deer-flow/pull/4355
[#4356]: https://github.com/bytedance/deer-flow/pull/4356
[#4358]: https://github.com/bytedance/deer-flow/pull/4358
[#4361]: https://github.com/bytedance/deer-flow/pull/4361
[#4364]: https://github.com/bytedance/deer-flow/pull/4364
[#4365]: https://github.com/bytedance/deer-flow/pull/4365
[#4370]: https://github.com/bytedance/deer-flow/pull/4370
[#4371]: https://github.com/bytedance/deer-flow/pull/4371
[#4373]: https://github.com/bytedance/deer-flow/pull/4373
[#4374]: https://github.com/bytedance/deer-flow/pull/4374
[#4376]: https://github.com/bytedance/deer-flow/pull/4376
[#4381]: https://github.com/bytedance/deer-flow/pull/4381
[#4383]: https://github.com/bytedance/deer-flow/pull/4383
[#4385]: https://github.com/bytedance/deer-flow/pull/4385
[#4391]: https://github.com/bytedance/deer-flow/pull/4391
[#4392]: https://github.com/bytedance/deer-flow/pull/4392
[#4394]: https://github.com/bytedance/deer-flow/pull/4394
[#4402]: https://github.com/bytedance/deer-flow/pull/4402
[#4403]: https://github.com/bytedance/deer-flow/pull/4403
[#4407]: https://github.com/bytedance/deer-flow/pull/4407
[#4408]: https://github.com/bytedance/deer-flow/pull/4408
[#4411]: https://github.com/bytedance/deer-flow/pull/4411
[#4414]: https://github.com/bytedance/deer-flow/issues/4414
[#4424]: https://github.com/bytedance/deer-flow/issues/4424
[#4425]: https://github.com/bytedance/deer-flow/pull/4425
[#4426]: https://github.com/bytedance/deer-flow/pull/4426
[#4430]: https://github.com/bytedance/deer-flow/pull/4430
[#4431]: https://github.com/bytedance/deer-flow/pull/4431
[#4432]: https://github.com/bytedance/deer-flow/pull/4432
[#4434]: https://github.com/bytedance/deer-flow/pull/4434
[#4437]: https://github.com/bytedance/deer-flow/pull/4437
[#4441]: https://github.com/bytedance/deer-flow/pull/4441
[#4442]: https://github.com/bytedance/deer-flow/pull/4442
[#4444]: https://github.com/bytedance/deer-flow/pull/4444
[#4446]: https://github.com/bytedance/deer-flow/pull/4446
[#4447]: https://github.com/bytedance/deer-flow/pull/4447
[#4450]: https://github.com/bytedance/deer-flow/pull/4450
[#4456]: https://github.com/bytedance/deer-flow/pull/4456
[#4459]: https://github.com/bytedance/deer-flow/pull/4459
[#4460]: https://github.com/bytedance/deer-flow/pull/4460
[#4468]: https://github.com/bytedance/deer-flow/pull/4468
[#4469]: https://github.com/bytedance/deer-flow/pull/4469
[#4471]: https://github.com/bytedance/deer-flow/pull/4471
[#4516]: https://github.com/bytedance/deer-flow/pull/4516
[#4611]: https://github.com/bytedance/deer-flow/issues/4611
[#4745]: https://github.com/bytedance/deer-flow/pull/4745
[#4574]: https://github.com/bytedance/deer-flow/issues/4574
[#4577]: https://github.com/bytedance/deer-flow/pull/4577
[#4623]: https://github.com/bytedance/deer-flow/pull/4623
[#4634]: https://github.com/bytedance/deer-flow/pull/4634
[#4638]: https://github.com/bytedance/deer-flow/pull/4638
[#4848]: https://github.com/bytedance/deer-flow/pull/4848
[#3183]: https://github.com/bytedance/deer-flow/pull/3183
[#3396]: https://github.com/bytedance/deer-flow/pull/3396
[#3442]: https://github.com/bytedance/deer-flow/pull/3442
[#3565]: https://github.com/bytedance/deer-flow/pull/3565
[#3703]: https://github.com/bytedance/deer-flow/pull/3703
[#3708]: https://github.com/bytedance/deer-flow/pull/3708
[#3783]: https://github.com/bytedance/deer-flow/pull/3783
[#3824]: https://github.com/bytedance/deer-flow/pull/3824
[#3833]: https://github.com/bytedance/deer-flow/pull/3833
[#4025]: https://github.com/bytedance/deer-flow/pull/4025
[#4200]: https://github.com/bytedance/deer-flow/pull/4200
[#4210]: https://github.com/bytedance/deer-flow/pull/4210
[#4242]: https://github.com/bytedance/deer-flow/pull/4242
[#4247]: https://github.com/bytedance/deer-flow/pull/4247
[#4250]: https://github.com/bytedance/deer-flow/pull/4250
[#4262]: https://github.com/bytedance/deer-flow/pull/4262
[#4266]: https://github.com/bytedance/deer-flow/pull/4266
[#4274]: https://github.com/bytedance/deer-flow/pull/4274
[#4275]: https://github.com/bytedance/deer-flow/pull/4275
[#4284]: https://github.com/bytedance/deer-flow/pull/4284
[#4293]: https://github.com/bytedance/deer-flow/pull/4293
[#4298]: https://github.com/bytedance/deer-flow/pull/4298
[#4301]: https://github.com/bytedance/deer-flow/pull/4301
[#4302]: https://github.com/bytedance/deer-flow/pull/4302
[#4314]: https://github.com/bytedance/deer-flow/pull/4314
[#4360]: https://github.com/bytedance/deer-flow/pull/4360
[#4377]: https://github.com/bytedance/deer-flow/pull/4377
[#4382]: https://github.com/bytedance/deer-flow/pull/4382
[#4384]: https://github.com/bytedance/deer-flow/pull/4384
[#4395]: https://github.com/bytedance/deer-flow/pull/4395
[#4405]: https://github.com/bytedance/deer-flow/pull/4405
[#4406]: https://github.com/bytedance/deer-flow/pull/4406
[#4423]: https://github.com/bytedance/deer-flow/pull/4423
[#4427]: https://github.com/bytedance/deer-flow/pull/4427
[#4429]: https://github.com/bytedance/deer-flow/pull/4429
[#4439]: https://github.com/bytedance/deer-flow/pull/4439
[#4443]: https://github.com/bytedance/deer-flow/pull/4443
[#4448]: https://github.com/bytedance/deer-flow/pull/4448
[#4453]: https://github.com/bytedance/deer-flow/pull/4453
[#4472]: https://github.com/bytedance/deer-flow/pull/4472
[#4480]: https://github.com/bytedance/deer-flow/pull/4480
[#4482]: https://github.com/bytedance/deer-flow/pull/4482
[#4486]: https://github.com/bytedance/deer-flow/pull/4486
[#4489]: https://github.com/bytedance/deer-flow/pull/4489
[#4490]: https://github.com/bytedance/deer-flow/pull/4490
[#4493]: https://github.com/bytedance/deer-flow/pull/4493
[#4497]: https://github.com/bytedance/deer-flow/pull/4497
[#4500]: https://github.com/bytedance/deer-flow/pull/4500
[#4501]: https://github.com/bytedance/deer-flow/pull/4501
[#4504]: https://github.com/bytedance/deer-flow/pull/4504
[#4505]: https://github.com/bytedance/deer-flow/pull/4505
[#4506]: https://github.com/bytedance/deer-flow/pull/4506
[#4509]: https://github.com/bytedance/deer-flow/pull/4509
[#4510]: https://github.com/bytedance/deer-flow/pull/4510
[#4512]: https://github.com/bytedance/deer-flow/pull/4512
[#4513]: https://github.com/bytedance/deer-flow/pull/4513
[#4518]: https://github.com/bytedance/deer-flow/pull/4518
[#4519]: https://github.com/bytedance/deer-flow/pull/4519
[#4524]: https://github.com/bytedance/deer-flow/pull/4524
[#4527]: https://github.com/bytedance/deer-flow/pull/4527
[#4528]: https://github.com/bytedance/deer-flow/pull/4528
[#4530]: https://github.com/bytedance/deer-flow/pull/4530
[#4533]: https://github.com/bytedance/deer-flow/pull/4533
[#4534]: https://github.com/bytedance/deer-flow/pull/4534
[#4535]: https://github.com/bytedance/deer-flow/pull/4535
[#4538]: https://github.com/bytedance/deer-flow/pull/4538
[#4539]: https://github.com/bytedance/deer-flow/pull/4539
[#4540]: https://github.com/bytedance/deer-flow/pull/4540
[#4556]: https://github.com/bytedance/deer-flow/pull/4556
[#4558]: https://github.com/bytedance/deer-flow/pull/4558
[#4559]: https://github.com/bytedance/deer-flow/pull/4559
[#4564]: https://github.com/bytedance/deer-flow/pull/4564
[#4570]: https://github.com/bytedance/deer-flow/pull/4570
[#4575]: https://github.com/bytedance/deer-flow/pull/4575
[#4578]: https://github.com/bytedance/deer-flow/pull/4578
[#4582]: https://github.com/bytedance/deer-flow/pull/4582
[#4584]: https://github.com/bytedance/deer-flow/pull/4584
[#4587]: https://github.com/bytedance/deer-flow/pull/4587
[#4589]: https://github.com/bytedance/deer-flow/pull/4589
[#4590]: https://github.com/bytedance/deer-flow/pull/4590
[#4596]: https://github.com/bytedance/deer-flow/pull/4596
[#4599]: https://github.com/bytedance/deer-flow/pull/4599
[#4600]: https://github.com/bytedance/deer-flow/pull/4600
[#4604]: https://github.com/bytedance/deer-flow/pull/4604
[#4615]: https://github.com/bytedance/deer-flow/pull/4615
[#4617]: https://github.com/bytedance/deer-flow/pull/4617
[#4618]: https://github.com/bytedance/deer-flow/pull/4618
[#4620]: https://github.com/bytedance/deer-flow/pull/4620
[#4624]: https://github.com/bytedance/deer-flow/pull/4624
[#4625]: https://github.com/bytedance/deer-flow/pull/4625
[#4627]: https://github.com/bytedance/deer-flow/pull/4627
[#4629]: https://github.com/bytedance/deer-flow/pull/4629
[#4631]: https://github.com/bytedance/deer-flow/pull/4631
[#4633]: https://github.com/bytedance/deer-flow/pull/4633
[#4635]: https://github.com/bytedance/deer-flow/pull/4635
[#4636]: https://github.com/bytedance/deer-flow/pull/4636
[#4639]: https://github.com/bytedance/deer-flow/pull/4639
[#4643]: https://github.com/bytedance/deer-flow/pull/4643
[#4644]: https://github.com/bytedance/deer-flow/pull/4644
[#4647]: https://github.com/bytedance/deer-flow/pull/4647
[#4649]: https://github.com/bytedance/deer-flow/pull/4649
[#4657]: https://github.com/bytedance/deer-flow/pull/4657
[#4658]: https://github.com/bytedance/deer-flow/pull/4658
[#4659]: https://github.com/bytedance/deer-flow/pull/4659
[#4660]: https://github.com/bytedance/deer-flow/pull/4660
[#4665]: https://github.com/bytedance/deer-flow/pull/4665
[#4667]: https://github.com/bytedance/deer-flow/pull/4667
[#4668]: https://github.com/bytedance/deer-flow/pull/4668
[#4677]: https://github.com/bytedance/deer-flow/pull/4677
[#4681]: https://github.com/bytedance/deer-flow/pull/4681
[#4683]: https://github.com/bytedance/deer-flow/pull/4683
[#4684]: https://github.com/bytedance/deer-flow/pull/4684
[#4690]: https://github.com/bytedance/deer-flow/pull/4690
[#4693]: https://github.com/bytedance/deer-flow/pull/4693
[#4701]: https://github.com/bytedance/deer-flow/pull/4701
[#4703]: https://github.com/bytedance/deer-flow/pull/4703
[#4707]: https://github.com/bytedance/deer-flow/pull/4707
[#4709]: https://github.com/bytedance/deer-flow/pull/4709
[#4713]: https://github.com/bytedance/deer-flow/pull/4713
[#4719]: https://github.com/bytedance/deer-flow/pull/4719
[#4722]: https://github.com/bytedance/deer-flow/pull/4722
[#4724]: https://github.com/bytedance/deer-flow/pull/4724
[#4727]: https://github.com/bytedance/deer-flow/pull/4727
[#4730]: https://github.com/bytedance/deer-flow/pull/4730
[#4735]: https://github.com/bytedance/deer-flow/pull/4735
[#4736]: https://github.com/bytedance/deer-flow/pull/4736
[#4737]: https://github.com/bytedance/deer-flow/pull/4737
[#4738]: https://github.com/bytedance/deer-flow/pull/4738
[#4744]: https://github.com/bytedance/deer-flow/pull/4744
[#4747]: https://github.com/bytedance/deer-flow/pull/4747
[#4748]: https://github.com/bytedance/deer-flow/pull/4748
[#4750]: https://github.com/bytedance/deer-flow/pull/4750
[#4752]: https://github.com/bytedance/deer-flow/pull/4752
[#4755]: https://github.com/bytedance/deer-flow/pull/4755
[#4758]: https://github.com/bytedance/deer-flow/pull/4758
[#4759]: https://github.com/bytedance/deer-flow/pull/4759
[#4760]: https://github.com/bytedance/deer-flow/pull/4760
[#4762]: https://github.com/bytedance/deer-flow/pull/4762
[#4764]: https://github.com/bytedance/deer-flow/pull/4764
[#4767]: https://github.com/bytedance/deer-flow/pull/4767
[#4769]: https://github.com/bytedance/deer-flow/pull/4769
[#4772]: https://github.com/bytedance/deer-flow/pull/4772
[#4780]: https://github.com/bytedance/deer-flow/pull/4780
[#4783]: https://github.com/bytedance/deer-flow/pull/4783
[#4785]: https://github.com/bytedance/deer-flow/pull/4785
[#4789]: https://github.com/bytedance/deer-flow/pull/4789
[#4792]: https://github.com/bytedance/deer-flow/pull/4792
[#4797]: https://github.com/bytedance/deer-flow/pull/4797
[#4800]: https://github.com/bytedance/deer-flow/pull/4800
[#4804]: https://github.com/bytedance/deer-flow/pull/4804
[#4806]: https://github.com/bytedance/deer-flow/pull/4806
[#4812]: https://github.com/bytedance/deer-flow/pull/4812
[#4815]: https://github.com/bytedance/deer-flow/pull/4815
[#4816]: https://github.com/bytedance/deer-flow/pull/4816
[#4817]: https://github.com/bytedance/deer-flow/pull/4817
[#4822]: https://github.com/bytedance/deer-flow/pull/4822
[#4823]: https://github.com/bytedance/deer-flow/pull/4823
[#4825]: https://github.com/bytedance/deer-flow/pull/4825
[#4827]: https://github.com/bytedance/deer-flow/pull/4827
[#4830]: https://github.com/bytedance/deer-flow/pull/4830
[#4833]: https://github.com/bytedance/deer-flow/pull/4833
[#4836]: https://github.com/bytedance/deer-flow/pull/4836
[#4838]: https://github.com/bytedance/deer-flow/pull/4838
[#4840]: https://github.com/bytedance/deer-flow/pull/4840
[#4842]: https://github.com/bytedance/deer-flow/pull/4842
[#4844]: https://github.com/bytedance/deer-flow/pull/4844
[#4846]: https://github.com/bytedance/deer-flow/pull/4846
[#4852]: https://github.com/bytedance/deer-flow/pull/4852
[#4853]: https://github.com/bytedance/deer-flow/pull/4853
[#4860]: https://github.com/bytedance/deer-flow/pull/4860
[#4861]: https://github.com/bytedance/deer-flow/pull/4861
[#4863]: https://github.com/bytedance/deer-flow/pull/4863
[#4865]: https://github.com/bytedance/deer-flow/pull/4865
[#4868]: https://github.com/bytedance/deer-flow/pull/4868
[#4877]: https://github.com/bytedance/deer-flow/pull/4877
[#4882]: https://github.com/bytedance/deer-flow/pull/4882
[#4887]: https://github.com/bytedance/deer-flow/pull/4887
[#4888]: https://github.com/bytedance/deer-flow/pull/4888
[#4898]: https://github.com/bytedance/deer-flow/pull/4898
[#4903]: https://github.com/bytedance/deer-flow/pull/4903
[#4911]: https://github.com/bytedance/deer-flow/pull/4911
[#4918]: https://github.com/bytedance/deer-flow/pull/4918
[#4928]: https://github.com/bytedance/deer-flow/pull/4928
[#4933]: https://github.com/bytedance/deer-flow/pull/4933
[#4936]: https://github.com/bytedance/deer-flow/pull/4936
[#4938]: https://github.com/bytedance/deer-flow/pull/4938
[#4951]: https://github.com/bytedance/deer-flow/pull/4951
[#4953]: https://github.com/bytedance/deer-flow/pull/4953
[#4956]: https://github.com/bytedance/deer-flow/pull/4956
[#4959]: https://github.com/bytedance/deer-flow/pull/4959
[#4960]: https://github.com/bytedance/deer-flow/pull/4960
[#4963]: https://github.com/bytedance/deer-flow/pull/4963
[#4965]: https://github.com/bytedance/deer-flow/pull/4965
[#4970]: https://github.com/bytedance/deer-flow/pull/4970
[#4983]: https://github.com/bytedance/deer-flow/pull/4983
[#4987]: https://github.com/bytedance/deer-flow/pull/4987
[#4998]: https://github.com/bytedance/deer-flow/pull/4998
[#4696]: https://github.com/bytedance/deer-flow/pull/4696
[#4810]: https://github.com/bytedance/deer-flow/pull/4810
[#4820]: https://github.com/bytedance/deer-flow/pull/4820
[#4826]: https://github.com/bytedance/deer-flow/pull/4826
[#4834]: https://github.com/bytedance/deer-flow/pull/4834
[#4839]: https://github.com/bytedance/deer-flow/pull/4839
[#4867]: https://github.com/bytedance/deer-flow/pull/4867
[#4876]: https://github.com/bytedance/deer-flow/pull/4876
[#4878]: https://github.com/bytedance/deer-flow/pull/4878
[#4946]: https://github.com/bytedance/deer-flow/pull/4946
[#4955]: https://github.com/bytedance/deer-flow/pull/4955
[#4972]: https://github.com/bytedance/deer-flow/pull/4972
[#4977]: https://github.com/bytedance/deer-flow/pull/4977
[#4984]: https://github.com/bytedance/deer-flow/pull/4984
[#4986]: https://github.com/bytedance/deer-flow/pull/4986
[#5003]: https://github.com/bytedance/deer-flow/pull/5003
[#5006]: https://github.com/bytedance/deer-flow/pull/5006
[#5008]: https://github.com/bytedance/deer-flow/pull/5008
[#5010]: https://github.com/bytedance/deer-flow/pull/5010
[#5014]: https://github.com/bytedance/deer-flow/pull/5014
[#5017]: https://github.com/bytedance/deer-flow/pull/5017
[#5018]: https://github.com/bytedance/deer-flow/pull/5018
[#5021]: https://github.com/bytedance/deer-flow/pull/5021
[#5022]: https://github.com/bytedance/deer-flow/pull/5022
[#5023]: https://github.com/bytedance/deer-flow/pull/5023
[#5025]: https://github.com/bytedance/deer-flow/pull/5025
[#5027]: https://github.com/bytedance/deer-flow/pull/5027
[#5030]: https://github.com/bytedance/deer-flow/pull/5030
[#5031]: https://github.com/bytedance/deer-flow/pull/5031
[#5036]: https://github.com/bytedance/deer-flow/pull/5036
[#5039]: https://github.com/bytedance/deer-flow/pull/5039
[#5041]: https://github.com/bytedance/deer-flow/pull/5041
[#5045]: https://github.com/bytedance/deer-flow/pull/5045
[#5047]: https://github.com/bytedance/deer-flow/pull/5047
[#5049]: https://github.com/bytedance/deer-flow/pull/5049
[#5050]: https://github.com/bytedance/deer-flow/pull/5050
[#5051]: https://github.com/bytedance/deer-flow/pull/5051
[#5056]: https://github.com/bytedance/deer-flow/pull/5056
[#5057]: https://github.com/bytedance/deer-flow/pull/5057
[#5059]: https://github.com/bytedance/deer-flow/pull/5059
[#5064]: https://github.com/bytedance/deer-flow/pull/5064
[#5066]: https://github.com/bytedance/deer-flow/pull/5066
[#5069]: https://github.com/bytedance/deer-flow/pull/5069
[#5071]: https://github.com/bytedance/deer-flow/pull/5071
[#5074]: https://github.com/bytedance/deer-flow/pull/5074
[#5076]: https://github.com/bytedance/deer-flow/pull/5076
[#5077]: https://github.com/bytedance/deer-flow/pull/5077
[#5083]: https://github.com/bytedance/deer-flow/pull/5083
[#5086]: https://github.com/bytedance/deer-flow/pull/5086
[#5087]: https://github.com/bytedance/deer-flow/pull/5087
[#5089]: https://github.com/bytedance/deer-flow/pull/5089
[#5090]: https://github.com/bytedance/deer-flow/pull/5090
[#5092]: https://github.com/bytedance/deer-flow/pull/5092
[#5095]: https://github.com/bytedance/deer-flow/pull/5095
[#5099]: https://github.com/bytedance/deer-flow/pull/5099
[#5103]: https://github.com/bytedance/deer-flow/pull/5103
[#5105]: https://github.com/bytedance/deer-flow/pull/5105
[#5109]: https://github.com/bytedance/deer-flow/pull/5109
[#5112]: https://github.com/bytedance/deer-flow/pull/5112
[#5117]: https://github.com/bytedance/deer-flow/pull/5117
[#5133]: https://github.com/bytedance/deer-flow/pull/5133
[#5136]: https://github.com/bytedance/deer-flow/pull/5136
[#5119]: https://github.com/bytedance/deer-flow/pull/5119
