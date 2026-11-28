> # AI too expensive? Doesn't matter because you can have AI at home!
>
> On top of [upstream](https://github.com/bytedance/deer-flow), it adds — out of the box:
>
> **Getting it running**
>
> - 🔓 **Passwordless on your own network** — `make dev` / `make start` come up with no login wall, so your phone and laptop reach it over the LAN or [Tailscale](https://tailscale.com/) immediately. Opt out with `DEER_FLOW_AUTH_DISABLED=0`; auth stays on in production regardless.
> - 🦙 **Auto-populated Ollama models** — `config.yaml` syncs from your `ollama pull` list on every launch, with capabilities detected and each model's context window sized to your GPU instead of Ollama's 2048-token default. The GPU is detected on its own (an NVIDIA or AMD card beside the daemon). When Ollama runs on another machine, enter its GPU memory in **Settings → Models**: updates and syncs never reset it, and it wins over `ollama.vram_gb`. Local models are **free** — you pay for electricity.
> - 🔑 **API-key model auto-config** — drop a cloud key in `.env` and the matching models uncomment themselves in `config.yaml` on the next launch. Anthropic, OpenAI, xAI, Gemini, DeepSeek, Moonshot, Qwen, Mistral, MiniMax, Z.ai direct, plus a routed set via OpenRouter — one flagship per lab, except Anthropic and OpenAI, whose top tier is really two models a factor of two or more apart in price, so both halves are routed (Fable 5.2 + Opus 5.5, GPT-6.2 Astra + GPT-6.2 Sol), and DeepSeek, whose V4.1 Flash rides beside V4 Pro because it tops OpenRouter's rankings on its own.
> - 🎟️ **Subscription models from Settings → Models** — connect a ChatGPT plan in your browser, sign in to Grok with a device code, or add a Kimi Code subscription key. Available models populate the picker automatically, with encrypted server-side credentials and refresh/disconnect controls. ChatGPT uses a manual return-URL handoff for LAN/Tailscale access; Kimi is restricted to personal interactive chats. A Grok or Kimi plan request that is accepted and then never answered now times out and, after the usual retries, ends in a visible error instead of showing "Working" for ever.
> - 🎨 **Grok Imagine, X search and voice on your Grok plan** — once Grok is connected, an administrator can switch on image generation and editing, short video clips, X (Twitter) search and Grok voice (read answers aloud, transcribe speech), all paid for by the Grok subscription instead of API billing. **Every switch starts off**, a feature xAI refuses for your plan stays locked (image and video run on the plan's own Imagine quota, so the plan is checked on their first request), and each one says it sends your prompt (and, for edits, your images) to xAI; the internet switch turns them all off for a chat. Costs nothing to turn on beyond the plan you already have.
> - 🔎 **Self-hosted search, no API key** — a bundled SearXNG is provisioned at startup (an existing instance is reused) and backs the default `web_search`.
> - 🦊 **A local browser for page fetching, no API key** — Camoufox replaces the Jina cloud reader as the default `web_fetch`, and installs itself on every launch path.
> - 📱 **Installable on your phone** — a web app manifest and service worker, so you can add it to your home screen and get a Web Push notification when a long run finishes with the browser closed. Needs a secure origin; the settings page says so if you are on plain HTTP.
> - 🩹 **Arch / CachyOS fixes** — an nginx temp-path patch and bundled `langchain-ollama` so `make dev` works for non-root users out of the box.
>
> **Using it every day**
>
> - ➕ **Plus Ultracode — the plan becomes a script** — inspired by Claude Code's *ultracode* (this is the mode that used to be called Double Plus Ultracode). In this composer mode the agent answers a substantive request by writing an inspectable workflow script that many agents run in the background (understand, change, verify, with findings checked by a second agent), and the result **comes back to the same chat on its own**, exactly once. The Script workflows extension it runs on is bundled and on by default. Agent and time limits live under **Settings → Subagents**, one failed agent no longer ends the whole workflow, and the usual **tool-call limits still apply** — a runaway tool loop is still told to wrap up.
> - 🧬 **Double Plus Ultracode — the same script, with the automatic limits lifted** — the same workflow as Plus Ultracode with **no step limit** (not even the 1,000-step ceiling), **no loop or tool-call limits** (including the number of subtasks per run), **no token budgets and no workflow time limit**, for the lead, every workflow agent, every subagent it delegates to and the turn that receives the result. That is not "nothing stops it": the workflow's **agent count and size limits** still apply (**Settings → Subagents**), a **spend cap applies only if you set one** (Settings → Run limits; it is off by default, and agents running in parallel can overshoot it), a configuration change mid-run ends the workflow, and the model provider's own stops (output length, safety, failed retries) still end a turn. A **warning line stays in the composer** for as long as the mode is selected — **token-risky**, meant for **extremely large tasks** — with the full text on hover or focus. Do not leave this selected for ordinary chat.
> - 🎚️ **Run limits you can change or switch off in Settings** — the spend cap, the tool-call limits that tell an agent to "wrap up" after 30 calls to one tool, the token budgets and the step limit for background runs all live under **Settings → Run limits**, so a long merge or refactor — in Plus Ultracode or any other mode — no longer stops halfway because of a number buried in `config.yaml`. Double Plus Ultracode already ignores every limit on that page but the spend cap, for that one run (the workflow's own limits are not on the page and still apply). Each limit shows whether it comes from `config.yaml` or was set on the page, and **one click goes back to `config.yaml`**. Administrators only; changes apply from the next run, with no restart.
> - 🔀 **Independent model per conversation, remembered by the conversation** — every chat keeps its own model, subagent model, mode and reasoning effort, recorded on the chat itself rather than in one browser. Switching conversations switches the picker to *that* chat's model instead of leaving the last one selected — on your phone and after a site-data clear too — and a brand-new chat no longer forgets its model the moment it is created.
> - 🚦 **Concurrent chats** — leaving a chat used to cancel its run. Now a chat you leave mid-answer keeps streaming in the background and notifies you when it lands; come back and the answer is already there.
> - 🗃️ **Folders in the sidebar, with subfolders** — the chat list is a tree. A conversation you file is **inside its folder and gone from the list outside it**, the way a file manager works, and folders nest up to five levels. Drag chats and folders around, or use the **⋯** menus. Deleting a folder never deletes the chats in it. Stored per user on the server; nothing to configure.
> - ☑️ **Select several chats and act on them at once** — **Select** beside *New folder* (or in a chat's **⋯** menu) puts a checkbox on every sidebar row: click to tick, Shift-click for a range, then move the batch into a folder, make a **new folder from the selection**, archive it with one Undo, or delete it. **Deleting is permanent**, as it is for one chat: the confirmation names the chats and says so, and a chat whose answer is still running stays ticked for you to try again rather than being retried on its own. Nothing to configure.
> - 🧹 **Clean-up mode: a model renames and files your chats** — **Clean up…** in the selection toolbar (or **Clean up all…** for your 200 most recent chats) has a model you pick read each conversation, suggest a clearer title and file it into folders you name or folders it proposes. **Nothing changes until you have reviewed the plan and pressed Apply**, and applying it never reorders the sidebar. One model call per chat (plus, in auto mode, at most one to group the folders), counted in each chat's cost and stopped by your spend cap; nothing to configure.
> - 🗂️ **A file explorer for each conversation** — a labelled **Files** button right after the token counter in the chat header (or **Show files** in a chat's sidebar menu) browses the folders the agent created in that chat: its `workspace`, your `uploads` and the `outputs`, as a tree you open folder by folder, with sizes and times. Any file opens in the preview panel or downloads, including the scratch files the agent never presented, and open folders refresh while a run is working. The tab says plainly that this folder is **deleted together with the chat**. Read-only; nothing to configure.
> - 📒 **Shared folders remember which chats wrote to them** — a folder a conversation creates or edits inside a writable custom `sandbox.mounts` directory is recorded, with an edit log, and listed under **Shared folders** in that chat's **Files** tab. Such folders outlive the chat, so when you delete the last conversation that used one, DeerFlow **offers** to delete it: never on its own, with nothing pre-ticked, and only for a folder a conversation was seen creating. Needs the default SQL database and a writable mount; nothing else to switch on.
> - 🧩 **Extensions whose tools produce files** — an installed extension's tool can write a file into the conversation that called it, and the file opens in the artifact panel and the Files view like one from a built-in tool. It works on the default sandbox with no shell, because the Gateway does the writing. **The tool only names a file:** it cannot choose a conversation or a folder, and an existing file is never replaced. Nothing to switch on; `plugin_outputs` in `config.yaml` caps a file at 8 MiB and one tool call at 32 MiB.
> - 🧊 **CAD models you can turn in the file preview** — a `.glb` or `.stl` file, the bodies of a CAD design among them, opens in the artifact panel, the reader and the Files view as a model you can rotate, zoom and view from the top, the front or an angle, with its size in millimetres, on a phone too. **It never moves on its own** and draws only when you touch it, and each file is checked against fixed caps in a background worker before anything is drawn, so a file that is too large or malformed falls back to a download. The original always downloads unchanged. Bundled and on; nothing to configure, and `make extension-disable NAME=cad-preview` turns it off.
> - 🏗️ **A design page for CAD parts** — **Designs** in the sidebar opens a page with the conversation on the left and the design's versions on the right. The prompt row has the chat's own model picker, mode and reasoning effort. The assistant writes the part as parametric multi-body OpenSCAD and runs the whole loop itself: it renders every body, **checks the bodies for clashes and gaps in every pose and through every swing**, looks at cross-sections and a shaded render, checks the print (overhangs, bridges, thin walls, a slicer run without supports) and works out the loads by hand, then fixes what failed and renders again. Each render is a version you can open: the bodies in 3D with one colour each, the view images, the check results, the code and the files. On delivery it writes a print and assembly guide (PDF) and a zip of the files with a manifest, after reading every STEP, 3MF and STL back against the body it came from; it can also try several values of one dimension side by side, cut one joint out as a short test print, and prove a body rebuilt in CadQuery as an editable STEP against the original. **The model's code runs only in the design's own sandbox container, never in the Gateway**, so the page needs Docker and the CAD image: `make sandbox-cad-image` (a local build on the pinned AIO sandbox, which is over 13 GB) and `make sandbox-enable MODE=container IMAGE=cad`; until then it shows those commands. Every figure is a check on the model, not on a print. Ordinary chats pay nothing for it. Bundled and on; `make extension-disable NAME=cad-design` turns it off.
> - 🕯️ **Gaslight mode** — edit **either half of a turn**. Edit your own message and it replays from there; edit the assistant's answer and your text simply *becomes* what it said. Both versions are kept behind a `‹ 2/2 ›` switcher, and one conversation stays **one** sidebar entry however many times you edit it.
> - 🌐 **An internet switch on the composer** — a globe takes *this* conversation offline: search, fetching, browser control, MCP and external agents are left out of the run, and subagents inherit it. Per chat, not a global setting.
> - 📄 **PDF / Office uploads that just work** — `pymupdf4llm` is bundled, so PDF / DOCX / PPTX / XLSX uploads are reliably readable by the agent (`uploads.auto_convert_documents: true`).
> - 📚 **Big documents on small models** — `analyze_document` reads a document in parts sized for whichever model is serving, so a 300-page PDF never has to fit in a 32K local model. A **scanned** PDF is detected and transcribed by a vision model rather than summarised into fiction. An upload too large to read in one window now says so in the prompt — with its real extracted size, not the compressed file size — and every answer names the **pages** it came from, so a read that stopped early hands back a `start_part` to continue from instead of quietly answering about the first 40%.
> - 📖 **Books in any format, zipped or not** — an HTML, EPUB, plain-text or zipped book (a Project Gutenberg download, say) now states its size in the prompt and, when it is too big for one window, is routed to `analyze_document`, which reads HTML and EPUB as Markdown and reads the documents inside a zip. **Nothing is parsed or unpacked on the host to size an upload**, and a zip that would unpack past 64 MB, holds over 1,000 files, nests another archive or is encrypted is refused with the reason. Nothing to turn on.
> - 🧱 **No request bigger than the window** — before every model call the whole request (system prompt, tool schemas, conversation) is measured against the serving model's window. If it does not fit, the oldest tool results are dropped from that request — never your messages or the instructions — and if it still does not fit it is **not sent**: the chat says why, instead of Ollama silently cutting off the start of the prompt. On a local model the request is also **built to fit from the first message**: tools are described in short form, skills are listed by name and MCP tools wait behind a search, so a synced 32K Ollama model keeps about 15K tokens for the conversation in Flash mode (it had about 7K). Compaction fires before the window fills, and a refusal states the real limit and what is using it. Nothing to turn on; a model whose window is unknown is left alone.
> - 🎯 **A drift check for long documents** — `make drift-eval` gives a model a large PDF with facts planted at known pages, then has a *second* model judge whether the answer still addresses the question that was asked or quietly became "summarise this document". The planted facts grade the judge too, so a judge that waves through a wrong answer is reported as the judge failing. Runs offline against the document path, or end to end through the running agent with `MODE=agent`.
> - 🔭 **A deviation monitor that stops a run once it drifts off your request** — the compass under the message box turns it on for one chat: pick the model that checks and how often (every few agent steps, or just before the final answer of every few turns), and while the agent works that second model judges whether its recent steps still serve what you asked. **A confirmed drift stops the run** before the drifting tool calls run, with a note naming your request; in Ultra, Democracy and the Ultracode modes it first retries once, split across subagents. An unsure verdict is shown and never acted on. Off in every chat until you turn it on; each check is a model call the agent waits for, billed to the run (`deviation_monitor:` in `config.yaml`, offered by default).
> - 🛠️ **A coding agent that checks its own work** — `str_replace` refuses an edit whose text matches more than one place, a write that leaves a Python, JSON, YAML or TOML file unparseable comes back with the line of the error, and before its final answer the agent is reminded once to run something when it edited code and ran nothing afterwards. On by default (`harness_guard.verify_before_finish`); at most one extra model call per run.
> - 🎓 **Skills the agent learns, uses and retires** — with `skill_evolution.enabled: true`, a long run (8+ tool calls) ends with one reminder to save what it worked out as a skill, or to patch the custom skill it followed; every later load is counted, and agent-written skills nobody loaded for 90 days are switched off (Capability Center → Skills turns them back on, nothing is deleted). Off by default, because each skill write runs a security-scan model call.
> - 📚 **Coding skills from day one** — test-driven development, systematic debugging, pre-commit code review, simplify-code, spikes and subagent-driven development (adapted from Hermes Agent, MIT), plus `git-pr-workflow`: a script that branches, checkpoints, commits (refusing secrets and the default branch), pushes with a read-back and opens a PR exactly once. Bundled in `skills/public/`: a fresh install has them and every update improves them.
> - 🗺️ **A repo map and a three-level change cycle** — `change_cycle.md` runs every change at level 1 (the tests of the features the changed files map to), 2 (the whole app) or 3 (plus a quality review), against [`docs/repo-map/`](docs/repo-map/index.md), a feature-by-feature map of this repository and its tests. The `repo-change-cycle` skill sets up any repository the agent creates the same way, from the bundled setup brief. Nothing to switch on.
> - 🐳 **Full clone-and-debug sandbox runs** — one-command per-thread containers, host-reachable ports, native debuggers (`gdb` / `strace`), and a `repo-runner` skill that encodes clone → install → run → debug.
> - 🖥️ **Hardware-accelerated virtual machines in the sandbox, opt-in** — set `sandbox.devices: [/dev/kvm]` and a QEMU guest the agent starts inside its per-conversation container runs on the host's KVM instead of slow software emulation; the `repo-runner` skill carries the recipe (headless QEMU, a cloud-init seed, SSH on a loopback port). What you would not expect: it is **off by default**, it needs a sandbox image that **already contains QEMU** (none is shipped, and the agent cannot `apt-get` one in), and **it has not been run end to end** — it was written without Docker or KVM at hand. Switching it on costs one config key and a larger attack surface: the host kernel's KVM interface is handed to everything the agent runs.
> - 📜 **Scroll-back that survives a restart** — history is served by the run-event store, which now defaults to `db` rather than process memory. Older messages keep loading after the Gateway restarts, an edited version of a conversation keeps the whole history instead of starting at the last compaction, and a message whose run was stopped before the model answered is kept too. It needs the default SQL database, and history lost before these fixes does not come back.
>
> **Knowing what it costs**
>
> - 💵 **Live cost overview in the chat header** — an estimated cost per conversation, priced per model from `config.yaml`, including the LLM calls that never become a run of their own (memory, suggestions, prompt polish) and the per-turn goal check. Persisted across restarts; hidden entirely if you configure no pricing.
> - 🛑 **Spend caps in real money** — a daily / weekly / monthly limit in your own currency. The agent is warned as it approaches, then refused. Unpriced local models count as $0, so a fully local session is never blocked.
> - 🧾 **Spend page** — where the money went this month, broken down by model, conversation and feature over 7, 30 or 90 days.
> - 📈 **Price graph** — the cost of every step of a conversation, as columns or a running total. A turn on an unpriced local model draws **no** column rather than a zero-height one.
> - 📊 **Input and output apart on the Token usage page** — every total on **Token usage** in the sidebar (the headline, each day's bar, each model, each run) is split into input and output, with the cache-hit part of input marked. A provider that reported only a total shows the gap as **unattributed** instead of quietly counting it as input, so the parts always add up. Nothing to turn on.
> - 🧾 **A reply keeps the price it was billed at** — costs used to be recomputed from today's `config.yaml`, so re-pricing a model rewrote what last month's conversation cost and a retired model made it *cheaper*. Rates are now stamped on each run.
> - 🧮 **A cost estimate that survives a restart and an edit** — interrupted runs count (they spent the tokens), and turns replaced by an edit stay in the total as a **Replaced turns** row instead of quietly vanishing. Editing a message branches the conversation into a second thread, so the total now covers **every** thread of it while the graph shows only the turns you can still see: the number stops dropping when you edit, and the chart stops losing the turns you kept.
> - 🧭 **Cost-aware subagent routing** — a policy that sends delegated subtasks to the cheapest model that can actually do them, never one that lacks the tools, vision or context window. Off until you write a policy.
> - 🧠 **Long-term memory off by default** — the agent no longer learns from or injects your saved memory until you opt in per browser under **Settings → Memory**. When off, the backend skips memory injection, extraction and memory tools entirely.
> - 💡 **Follow-up suggestions off by default** — the follow-up chips cost an extra model call after every answer, so they are opt-in under **Settings → Suggestions**, where you can also pick a cheap model to generate them.
> - ✏️ **Conversation renaming you can switch off** — the shipped default spends **no** model call (the title is your first message, shortened); point it at a cheap model for a real summary, or turn it off entirely. The choice is saved to your account, so **off holds everywhere**: on every device and browser, and for chats started from IM channels, schedules and workflows.
> - 🪄 **Rename a conversation on demand, on a model you pick** — an **Auto rename** button in the chat header: pick a model, press **Run**, and the chat is named from what is actually in it now rather than from the line it opened with. Deliberation between models in an Ultra or Democracy turn is left out, so a panel is named after its conclusion rather than after the argument. One call on the model you chose, counted in the header's total.
>
> **Going further**
>
> - 🏛️ **Democracy — several models answer, then decide together** — pick an organizer and panelists; the organizer researches once, briefs them identically, they review each other anonymously, and it synthesizes one answer reporting the split rather than averaging it away. Extremely token-heavy, and the setup page estimates the multiple before you commit.
> - 🤖 **Generate a custom agent from your history** — point a model at past conversations and let it decide whether a new agent is even worth adding. It is allowed to say **no**, naming the agent that already covers the work. You get an editable **SOUL.md** draft; nothing is saved until you press Create.
> - 🧵 **Sub-agents that respect what your GPU can hold** — local dispatch asks the card instead of using a fixed number, so five sub-agents on a model that fits once run one at a time rather than queueing invisibly inside Ollama. On by default.
> - 🧩 **Per-thread subagent model** — in Ultra mode, route `task` subagents to a cheaper or local model (defaults to "Follow lead").
> - 🪃 **Model fallback chains** — a retryable failure (daemon down, context overflow, no tool support, provider 5xx) degrades to the next model you listed. Cancels, spend caps and guardrail refusals never fall back.
> - 📜 **The system prompt is visible and editable** — Settings → System prompt shows the template in force, an Edit tab, and a Preview with every placeholder filled in. Saved beside your other state, applied with no restart, admin-gated. The built-in prompt answers **overview-first** in every mode — the result, then detail only when you ask — and puts every command in its own copy-pasteable block.
> - 🔃 **A sortable, grouped model picker on every screen that picks a model** — sort by name or price, group by provider, search, with prices as one right-aligned column and a local model's weights and context window under its id. Remembered per browser and shared across all of them.
> - 🎙️ **Dictation that stops shipping your voice to Google** — Chrome's on-device recognition first, then a Whisper-compatible service on **your** machine. The vendor cloud is `voice.allow_cloud_fallback: true`, off by default.
>
> **Keeping it healthy**
>
> - 💾 **Whole-instance backup & restore** — `make backup` snapshots all of `.deer-flow` as one timestamped archive; `make restore` puts it back. Credentials excluded unless you pass `INCLUDE_SECRETS=1`.
> - 🛡️ **Deployment exposure check** — passwordless auth, multi-user-mode-off and a non-loopback `BIND_HOST` are each defensible alone but together decide who can reach your instance and as whom. `make doctor` prints that combined posture. Diagnosis only.
> - 👥 **Multi-user mode toggle** — on by default (each login sees only its own chats). Turn it off to merge every conversation into one shared workspace — handy after going passwordless, when old chats are stranded under different ids.
> - 🔄 **Self-updating browser & search** — Camoufox and the SearXNG image refresh themselves, throttled daily on launch or via a `systemd --user` timer. Opt out with `DEER_FLOW_AUTO_UPDATE=0`.
> - 🧰 **An Update dependencies button** — **Settings → Maintenance** pulls a newer Camoufox and SearXNG image on demand, for when a page fetch or a search just broke and tomorrow's automatic refresh is too late. Reports each component's outcome (including "skipped, no Docker"), refuses a second run while one is in flight, and is admin-only because it runs commands on the host.
> - 🚧 **Search that says when it is blocked** — SearXNG answers `HTTP 200` with an empty list when its engines are rate-limited, which used to read as a successful empty search and got the agent to re-query into the suspension. It is now an error naming the engines and the wait.
> - 🛟 **Search that survives a blocked connection** — `web_search` is a pluggable dispatcher. It ships Tavily-first with self-hosted SearXNG behind it, because a scraping engine inherits your IP's reputation and a VPN or datacenter exit loses every consumer engine at once. SearXNG takes over when Tavily errors, hits its plan limit, or has no key at all — so a fresh clone with no `TAVILY_API_KEY` searches locally and never reports a credentials failure. Swap the two values for local-first.
> - 🥷 **A stealth browser with its stealth actually on** — Camoufox backs `web_fetch`, and was being launched with nothing but `headless`. It now gets `geoip`, `humanize` and `block_webrtc`, all tunable from `config.yaml`. `geoip` is the one that matters behind a VPN: without it the browser reports your timezone and locale while your connection exits in another country, and that mismatch is itself what gets you flagged. A launch that fails with these retries without them, so a rejected option costs stealth rather than the tool.
> - 📦 **A browser that is actually installed, not just present** — the gateway image shipped Camoufox without the system libraries it loads, so every presence check passed until the first fetch failed. The libraries now ship with it.
> - 🎬 **Reduced motion by default** — decorative animations are off by default and honor the OS setting; flip it back per browser.
>
> **What this is:** a fork of [bytedance/deer-flow](https://github.com/bytedance/deer-flow) — a **personal AI you host at home**, close to the Claude Code / Claude.ai experience, running on hardware you own. Point it at a local Ollama model and it costs you electricity; point it at a cloud key and it tells you what each answer cost.
>
> **What this fork is for:** a private, self-hosted assistant you reach over your own network, cheap to run, and yours. The defaults follow from that — passwordless on LAN, Tailscale-ready dev origins, local-first search and fetch, per-conversation model choice, memory and suggestions off, and a live cost readout — so nothing about it is a surprise on your own bill or your own hardware.
>
> See [`FORK.md`](./FORK.md) for details, cost analysis, and disclaimers. Upstream is the source of truth for everything else.

---

English | [中文](README_zh.md) | [日本語](README_ja.md) | [Français](README_fr.md) | [Русский](README_ru.md) | [Português](README_pt.md) | [한국어](README_ko.md)

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<a href="https://trendshift.io/repositories/14699" target="_blank"><img src="https://trendshift.io/api/badge/repositories/14699" alt="bytedance%2Fdeer-flow | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
> On February 28th, 2026, DeerFlow claimed the 🏆 #1 spot on GitHub Trending following the launch of version 2. Thanks a million to our incredible community — you made this happen! 💪🔥

DeerFlow (**D**eep **E**xploration and **E**fficient **R**esearch **Flow**) is an open-source **super agent harness** that orchestrates **sub-agents**, **memory**, and **sandboxes** to do almost anything — powered by **extensible skills**.

https://github.com/user-attachments/assets/a8bcadc4-e040-4cf2-8fda-dd768b999c18

> [!NOTE]
> **DeerFlow 2.0 is a ground-up rewrite.** It shares no code with v1. If you're looking for the original Deep Research framework, it's maintained on the [`1.x` branch](https://github.com/bytedance/deer-flow/tree/main-1.x) — contributions there are still welcome. Active development has moved to 2.0.

## Official Website

Learn more and see **real demos** on our [**official website**](https://deerflow.tech).
The landing-page case studies open as allowlisted, read-only showcases without requiring a sign-in.

## Sister Projects

<img width="446" height="280" alt="image" align="middle" src="https://github.com/user-attachments/assets/077edef4-d560-41af-bb0d-d0a5f14fcc20" />

- [**LLM Space**](https://github.com/deer-flow/llm-space) - Meet our secret weapon behind DeerFlow — one desktop tool to prototype agent ideas, inspect each harness step, replay failures, and benchmark performance.

## Coding Plan from ByteDance Volcengine

- We strongly recommend using Doubao-Seed-2.0-Code, DeepSeek v3.2 and Kimi 2.5 to run DeerFlow
- [Learn more](https://www.byteplus.com/en/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)
- [中国大陆地区的开发者请点击这里](https://www.volcengine.com/activity/codingplan?utm_campaign=deer_flow&utm_content=deer_flow&utm_medium=devrel&utm_source=OWO&utm_term=deer_flow)

## InfoQuest

DeerFlow has newly integrated the intelligent search and crawling toolset independently developed by BytePlus — [InfoQuest (supports free online experience)](https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest)

<a href="https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest" target="_blank">
  <img
    src="https://sf16-sg.tiktokcdn.com/obj/eden-sg/hubseh7bsbps/20251208-160108.png"   alt="InfoQuest_banner"
  />
</a>

---

## Table of Contents

- [Official Website](#official-website)
- [Sister Projects](#sister-projects)
- [Coding Plan from ByteDance Volcengine](#coding-plan-from-bytedance-volcengine)
- [InfoQuest](#infoquest)
- [Table of Contents](#table-of-contents)
- [One-Line Agent Setup](#one-line-agent-setup)
- [Quick Start](#quick-start)
  - [Configuration](#configuration)
    - [Config validation (loud, not silent)](#config-validation-loud-not-silent)
    - [Web fetch: local browser or cloud reader](#web-fetch-local-browser-or-cloud-reader)
    - [Clone-and-run a repo in the sandbox](#clone-and-run-a-repo-in-the-sandbox)
  - [Running the Application](#running-the-application)
    - [Option 1: Docker (Recommended)](#option-1-docker-recommended)
    - [Upgrading an existing checkout](#upgrading-an-existing-checkout)
    - [Option 2: Local Development](#option-2-local-development)
    - [Web Search Service (SearXNG)](#web-search-service-searxng)
    - [Docker Production Deployment](#docker-production-deployment)
  - [Advanced](#advanced)
    - [Containerized sandbox & private GitHub repos](#containerized-sandbox--private-github-repos)
- [From Deep Research to Super Agent Harness](#from-deep-research-to-super-agent-harness)
- [Guides](#guides)
- [Core Features](#core-features)
  - [Subscription Models](#subscription-models)
    - [Grok Features: Imagine, X Search and Voice](#grok-features-imagine-x-search-and-voice)
  - [Token usage dashboard](#token-usage-dashboard)
  - [Local Models Get the Parallelism the GPU Has](#local-models-get-the-parallelism-the-gpu-has)
  - [Democracy — Several Models Answer, Then Decide Together](#democracy--several-models-answer-then-decide-together)
  - [Plus Ultracode and Double Plus Ultracode — The Plan Becomes a Script](#plus-ultracode-and-double-plus-ultracode--the-plan-becomes-a-script)
  - [Run Limits — What Can End a Run Early](#run-limits--what-can-end-a-run-early)
  - [Deviation Monitor — A Second Model Keeps the Run on Your Request](#deviation-monitor--a-second-model-keeps-the-run-on-your-request)
  - [Generating Agents From Your History](#generating-agents-from-your-history)
  - [Coding Agent: Gates, Learned Skills and Git](#coding-agent-gates-learned-skills-and-git)
  - [Sandbox & File System](#sandbox--file-system)
    - [Containerized sandbox as a one-command capability](#containerized-sandbox-as-a-one-command-capability)
    - [Host-run Ollama from inside the sandbox](#host-run-ollama-from-inside-the-sandbox)
    - [Private GitHub repositories](#private-github-repositories)
  - [Files in a Conversation](#files-in-a-conversation)
  - [Shared Folders and Their Edit Log](#shared-folders-and-their-edit-log)
  - [CAD Models in the File Preview](#cad-models-in-the-file-preview)
  - [CAD Design Page](#cad-design-page)
  - [System Prompt](#system-prompt)
  - [Internet Access Switch](#internet-access-switch)
  - [Concurrent Chats](#concurrent-chats)
  - [Folders in the Sidebar](#folders-in-the-sidebar)
  - [Selecting Several Chats at Once](#selecting-several-chats-at-once)
  - [Cleaning Up Your Chats With a Model](#cleaning-up-your-chats-with-a-model)
  - [A Conversation Remembers Its Model](#a-conversation-remembers-its-model)
  - [Automatic Conversation Titles](#automatic-conversation-titles)
  - [Renaming a Conversation on Demand](#renaming-a-conversation-on-demand)
- [Recommended Models](#recommended-models)
- [Backup and Restore](#backup-and-restore)
- [Large Documents and Scanned PDFs](#large-documents-and-scanned-pdfs)
  - [Books That Are Not PDFs](#books-that-are-not-pdfs)
  - [Requests That Would Overflow the Window](#requests-that-would-overflow-the-window)
- [Measuring Mission Drift on a Large Document](#measuring-mission-drift-on-a-large-document)
- [Voice Input](#voice-input)
- [Updating Camoufox and SearXNG](#updating-camoufox-and-searxng)
- [More Documentation](#more-documentation)
- [⚠️ Security Notice](#️-security-notice)
  - [Improper Deployment May Introduce Security Risks](#improper-deployment-may-introduce-security-risks)
  - [Deployment Defaults](#deployment-defaults)
  - [Reach This From Your Phone Over Tailscale](#reach-this-from-your-phone-over-tailscale)
  - [Notifications on Your Phone (PWA + Web Push)](#notifications-on-your-phone-pwa--web-push)
  - [Security Recommendations](#security-recommendations)
- [Contributing](#contributing)
  - [Script workflows (bundled extension)](#script-workflows-bundled-extension)
- [License](#license)
- [Acknowledgments](#acknowledgments)
  - [Key Contributors](#key-contributors)
- [Star History](#star-history)

## One-Line Agent Setup

If you use Claude Code, Codex, Cursor, Windsurf, or another coding agent, you can hand it the setup instructions in one sentence:

```text
Help me clone DeerFlow if needed, then bootstrap it for local development by following https://raw.githubusercontent.com/bytedance/deer-flow/main/Install.md
```

That prompt is intended for coding agents. It tells the agent to clone the repo if needed, choose Docker when available, and stop with the exact next command plus any missing config the user still needs to provide.

## Quick Start

```bash
git clone https://github.com/bytedance/deer-flow.git
cd deer-flow
make setup          # interactive wizard: writes config.yaml and .env (about 2 minutes)
```

Then start DeerFlow with Docker (recommended) or run it locally:

```bash
# Docker
make docker-init    # pull the sandbox image (once, or when the image updates)
make docker-start   # start services
```

```bash
# Local development
make check          # verifies Node.js 22+, pnpm, uv, nginx
make install
make dev
```

The local commands use the pnpm version pinned in `frontend/package.json`. If a
different global pnpm is on `PATH`, they use Corepack when available; otherwise
they report the version mismatch before installing frontend dependencies.

Run `make doctor` after setting model credentials. It reports obvious placeholder
API keys as incomplete configuration; replace them with real keys before testing
model calls.

Open http://localhost:2026.

- All configuration options, providers and manual setup: the [Configuration](docs/guide/configuration.md) guide; this fork's additions are under [Configuration](#configuration) below
- Docker, local development, upgrades, sizing and startup modes: the [Running the Application](docs/guide/deployment.md) guide; this fork's changes are under [Running the Application](#running-the-application) below
- Running on a server or exposing it beyond localhost: read the [Security Notice](#️-security-notice) first

### Configuration

Upstream's configuration reference (the `make setup` wizard and manual `config.yaml` setup, model, search and fetch providers, run-event storage, dotenv selection and blob storage) is the [Configuration](docs/guide/configuration.md) guide; this section keeps only what the fork adds.

Pick **Anthropic** or **OpenRouter** and the wizard enables a whole set of latest models from that one key — Anthropic writes Fable 5.2 / Opus 5.5 / Opus 5 / Sonnet 5.5 / Sonnet 5 / Haiku 5.5, and OpenRouter writes Claude Fable 5.2 and Opus 5.5, GPT-6.2 Astra and GPT-6.2 Sol, plus the xAI / Google flagships and a spread of open alternatives (MiniMax, Mistral, DeepSeek, Kimi, GLM, Qwen). If you configure by hand instead (`make config`), the same ready-to-uncomment blocks are at the top of `config.example.yaml` under `models:` — uncomment the one matching your key.

**Tools out of the box**: the defaults are chosen so the agent has its full toolset from the first launch — web search (SearXNG, key-less), web fetch (Camoufox local browser, key-less), image search, file read/write tools, and bash. When Docker (or Apple Container) is installed, both `make setup` and `make config` default to the **container sandbox** with bash enabled, so git/clone and program runs work immediately; without a container runtime the local sandbox is used and host bash stays off (a security default — enable the container sandbox later with `make sandbox-enable MODE=container`). If an older `config.yaml` is missing default tools (for example the agent reports it has no web_search/web_fetch/bash), `make config-upgrade` backfills the missing entries without touching your existing ones, and `make doctor` names exactly which tools are absent.

#### Config validation (loud, not silent)

This fork turns silent `config.yaml` mistakes into clear startup errors:

- **Duplicate keys are rejected.** A config with, say, two top-level `sandbox:` blocks (e.g. a hand edit plus a regenerated template) used to be silently resolved to the *last* one — reverting you to the local sandbox while your container sat healthy. Now the loader fails fast, naming the key and both line numbers:

  ```
  duplicate top-level key 'sandbox' in config.yaml: first defined at line 12, duplicated at line 87
  ```

  The same check runs in `make dev`'s config regeneration step, so startup refuses before anything can collapse the duplicate.

- **Config regeneration is idempotent.** `make config-upgrade` and the Ollama model sync only write when something actually changes — running them twice leaves `config.yaml` byte-for-byte identical and never appends a section that already exists.

- **Unknown keys are flagged.** Unrecognized keys under `sandbox:` warn with a "did you mean…?" hint, and typo-shaped keys in `models:` entries (e.g. `supports_thinkng`) warn that they look like a typo of a real field — surfacing mistakes that would otherwise only appear as a puzzling runtime error deep in a provider call. `make doctor` reports the same findings.

#### Web fetch: local browser or cloud reader

The `web_fetch` tool has a pluggable backend. The default is **`camoufox`** — a local, key-less, JavaScript-capable browser fetcher (a stealth Firefox) with no external dependency or API key. You can switch to **`jina`** (cloud reader API; works key-less at a lower rate limit):

```yaml
tools:
  - name: web_fetch
    group: web
    use: deerflow.community.web_fetch.tools:web_fetch_tool
    backend: camoufox      # default; or jina (cloud reader API)
    fallback: jina         # optional: try this backend if the primary errors
```

**Anti-detection options.** Camoufox is a stealth browser, and these are the switches that make it one. They default on and are tunable per install:

```yaml
  - name: web_fetch
    backend: camoufox
    camoufox:
      geoip: true            # align timezone/locale/geolocation with the EXIT ip
      humanize: true         # human-like cursor motion (or a float: max seconds)
      block_webrtc: true     # stop WebRTC leaking the real address behind a VPN
      # locale: en-US        # omit to let geoip choose from the exit ip
      # proxy: socks5://127.0.0.1:1080   # browser-only; unrelated to the jina `proxy:` key
```

`geoip` is the one that matters behind a VPN. Without it the browser advertises this host's timezone and locale while the connection exits in whatever country the VPN chose, and that mismatch is a stronger bot signal than anything a fingerprint patch fixes.

Set a key to `null` to hand that decision back to Camoufox. If a launch fails with these options — an unsupported key on an older build, a geoip database that was never downloaded, a proxy refusing connections — the browser is relaunched without them and the Gateway log says so ("retrying without them"). A rejected option costs stealth, never `web_fetch` itself.

To switch to the Jina cloud reader instead (fish):

```fish
make config            # pick "jina" when prompted (or edit config.yaml)
```

Because Camoufox is the default, **every launch path installs it end-to-end automatically** — the `camoufox` package (via the auto-detected uv extra) and the browser binaries (a large one-time download): local `make dev` / `make start`, Docker dev (`make docker-start`), and Docker prod (`make up`, baked into the image at build). `make fetch-browser` remains available to pre-download the browser by hand. The step is idempotent and best-effort: an already-present browser is a no-op, and a failed download (e.g. offline) never blocks startup.

Camoufox reuses a single headless browser across requests, renders JS-heavy pages, and returns readable markdown. If the browser somehow isn't downloaded yet, the tool result tells the agent exactly what to do (`run make fetch-browser`) instead of failing opaquely. A `web_fetch` of a private GitHub URL returns a hint to use git in the sandbox rather than a bare 404.

#### Clone-and-run a repo in the sandbox

To have the agent take a GitHub link, clone it, install its requirements, and run or debug the program away from your host, use the containerized sandbox in **per-thread container mode** (the agent gets its own Docker container per conversation, with `/mnt/user-data` host-backed so files and outputs surface normally). The agent installs a project's dependencies inside the workspace (a venv, `node_modules`, cargo). It does **not** have admin rights by default: the hardened container blocks `sudo`, so `apt-get` works only when the image's shell runs as root, and a system package the project needs otherwise belongs in a custom `sandbox.image`. Earlier versions of this page promised root and `apt`; that was wrong for the pinned image.

```fish
make sandbox-enable MODE=container   # writes an AioSandboxProvider block (no base_url)
```

Then restart the app. For a private repo, set `GITHUB_TOKEN` in `.env` (scoped to the repos you want) and DeerFlow configures git inside the container so plain `git clone https://github.com/owner/repo.git` works without the token ever appearing in URLs or logs. Useful `config.yaml → sandbox` knobs for this workflow:

- `bash_command_timeout` — raise it for long installs and builds (a big `pip install` or `cargo build` no longer stops at the old 600s ceiling). Each command now carries its own bounded request budget, so `request_timeout` no longer has to be raised alongside it; it governs the calls that budget does not reach — session creation and the file/list operations.
- `expose_ports: [8000]` — publish a port so a dev server the agent starts is reachable at `localhost:8000` from your own browser.
- `extra_capabilities: [SYS_PTRACE]` — allow `gdb`/`strace` to attach for native debugging.
- `idle_timeout` — keep a warmed-up debug environment alive longer between the agent's turns. `make config`, `make sandbox-enable MODE=container` and `make setup` all write `idle_timeout: 3600` and `bash_command_timeout: 1800`.
- `devices: [/dev/kvm]` — forward the host's KVM device so a virtual machine inside the sandbox is hardware-accelerated. Off by default; `/dev/kvm` is the only value accepted, anything else fails config validation, and the container is never run `--privileged`. Read the next paragraphs before setting it.
- `image` — a custom sandbox image, built `FROM` the pinned tag, for system packages the agent cannot install at run time (QEMU, for one). Switching to container mode from another mode, `make sandbox-enable MODE=container` writes a fresh sandbox section, so set `devices:` and a custom `image:` again afterwards; when the section is already in container mode it changes only the `image:` line (back to the stock tag, or to the CAD image with `IMAGE=cad`), so `devices:` and your other keys stay and only a custom `image:` has to be set again. The one image this repository ships is the CAD image for the [CAD design page](#cad-design-page): `make sandbox-cad-image` builds it, and `make sandbox-enable MODE=container IMAGE=cad` selects it.

The bundled **`repo-runner` skill** walks the agent through the whole loop (clone → detect toolchain → install in an isolated venv → run/debug → report the exact commands). Invoke it with `/repo-runner <github-url and what to do>`. It checks `id -u` first and carries on as an unprivileged user, skipping `apt-get` and `sudo`; it stops only when the sandbox has host bash disabled.

**Running a virtual machine in the sandbox.** When a project needs a VM (an OS image to boot, a kernel module to test), the skill's *When the project needs a virtual machine* section gives the agent a recipe: probe what the container has, start a headless QEMU guest in the background from files kept under `/mnt/user-data/workspace/vm/`, seed it with cloud-init, reach it over SSH on `127.0.0.1:2222`, and check at the start of each later turn whether it is still running. Three things decide whether that works for you:

- **The image must already contain QEMU.** Whether the stock image ships it was not checked, and the agent cannot install it (no `sudo`). Build your own image `FROM ghcr.io/agent-infra/sandbox:1.11.0` with `qemu-system-x86` (or `qemu-system-arm`), `qemu-utils`, `genisoimage` and `openssh-client`, and name it in `sandbox.image`. A ready-made image and a `make` target for it were proposed and are **not shipped yet**. Without QEMU the skill stops and tells you this.
- **Without `devices: [/dev/kvm]` the guest is software-emulated** (QEMU's TCG): it works with no extra permission and is slow. With it, the guest uses KVM, provided the Docker host has `/dev/kvm` at all — where it does not (Docker Desktop on macOS, a cloud VM without nested virtualization) **every** sandbox start fails with an error naming `sandbox.devices`. On Debian and Ubuntu the device is `0660 root:kvm`, which the sandbox's unprivileged user cannot open until the host has the udev rule quoted beside the key in `config.example.yaml`. Guest memory counts against the container's 2 GB limit; raise `DEER_FLOW_SANDBOX_MEMORY` for a larger guest. The key is ignored, with a warning, on Apple Container and in external or provisioner sandbox mode.
- **The security cost is real.** `/dev/kvm` hands the host kernel's KVM interface to everything the agent runs, in a container that already runs without a seccomp filter, so a KVM bug becomes a way out to the host, and commands run inside the guest are not seen by the bash audit. Leave it off unless you need fast VMs.

**None of this has been run end to end.** The key, the container flags and the recipe's commands are covered by tests, but the change was made on a machine with no Docker daemon, no `/dev/kvm` and no QEMU: whether the pinned image's user can open the forwarded device, which QEMU tools the image ships and whether the recipe boots a guest are unverified. [FORK.md](FORK.md#full-sandbox-runs-clone-a-repo-and-rundebug-it) lists what is unverified and gives one `docker run` command that checks the first of those on a Linux host with KVM.

### Running the Application

The subsections below keep only what this fork changes. Each points to its
upstream counterpart in the [Running the Application](docs/guide/deployment.md)
guide, which also covers deployment sizing, startup modes and LangGraph Studio.

#### Option 1: Docker (Recommended)

Upstream's Docker reference (Compose requirements, development and production commands, image builds, persistence, authentication, proxies and multi-worker recovery) is [Option 1: Docker (Recommended)](docs/guide/deployment.md#option-1-docker-recommended) in the Running the Application guide; the fork's changes follow.

Gateway runs use the top-level `recursion_limit` in `config.yaml` when an API
request does not provide one. **This fork's default is `250`, not upstream's
`100`**: a run's `recursion_limit` caps LangGraph super-steps, and a session that
clones a repo and then iterates over it — many `bash` / `read_file` /
`write_file` / `str_replace` turns, each one a super-step — routinely exceeds a
lower cap and aborts mid-task with `GraphRecursionError`.

`run_events.backend` defaults to `db` and should stay durable alongside a
persistent `database.backend`.
Scrolling back through a long conversation is served by
`GET /api/threads/{thread_id}/messages/page`, which reads the run-event store
and nothing else, so on `run_events.backend: memory` a Gateway restart drops
that history: the conversation still opens and still renders its recent turns
from the checkpoint, then stops loading older messages when you scroll up, with
nothing logged. `db` writes into the configured `database`, so it needs no
extra setup; on `database.backend: memory` the Gateway falls back to the
in-memory event store automatically. Existing installs pick the durable value up
through `make config-upgrade`, and `make doctor` reports the combination
directly — including a config that keeps its checkpoints through the deprecated
`checkpointer` section and has no `database` section, which runs the in-memory
event store and used to be reported as fine.

A durable store keeps only what is written to it, and four paths used to skip
the write. An edited version of a conversation is now seeded from the parent's
whole visible history rather than from the checkpoint, so editing a message in a
long, compacted conversation no longer produces a version that starts at the
compaction point. A message whose run ended before the model was called (Stop
during a long compaction, a sandbox that did not start) is recorded. `/compact`
fills an empty history from the checkpoint before it removes anything. And
message rows are written as they arrive instead of in batches of 20 events, so a
killed Gateway loses at most the row being written. If the first history page
fails to load, the **Load more** button stays as a manual retry. What remains:
history that was never written before these fixes does not come back, an edit
falls back to the checkpoint when the parent's history is empty or unreadable,
and an edit can reach back only 400 checkpoints.

#### Upgrading an existing checkout

Upstream's upgrade steps (keep `config.yaml`, `.env` and `extensions_config.json`, stop, `git pull --ff-only`, start the same mode again; resuming interrupted threads; idempotent rollouts) are in [Upgrading an existing checkout](docs/guide/deployment.md#upgrading-an-existing-checkout); the fork's change follows.

Every launcher runs `make config-upgrade` before it starts, so new configuration (such as a bundled
plugin) arrives on its own. A Docker host with neither `backend/.venv` nor PyYAML
says so instead; install PyYAML (e.g. `python3-yaml`) and run `make config-upgrade`.

#### Option 2: Local Development

Upstream's local-development steps (prerequisites, `make check` / `make install` / `make dev`, ports, startup timeout and Windows notes) are in [Option 2: Local Development](docs/guide/deployment.md#option-2-local-development); the fork's change follows.

If no `config.yaml` exists, the first `make dev` / `make start` seeds one from `config.example.yaml` automatically (the same first-run seeding the Docker launch paths do) and the API-key auto-config enables the model block matching whatever provider key is in your environment / `.env` — so a fresh checkout starts without a separate `make config` step, though `make setup` still gives the best guided setup.

#### Web Search Service (SearXNG)

The default `web_search` tool is backed by a bundled, self-hosted [SearXNG](https://github.com/searxng/searxng) metasearch instance — no API key, and queries go straight from your machine to the upstream engines instead of through a third-party search API.

Every launch path resolves the instance automatically at startup (via `scripts/detect_searxng.py`): if a SearXNG with the JSON API enabled is already running on this machine (checked on ports `8088` and `8080`, or wherever `DEER_FLOW_SEARXNG_BASE_URL` points), the stack reuses it; otherwise it starts the bundled `deer-flow-searxng` container. If `config.yaml` doesn't use the SearXNG provider, nothing is started.

- **Docker stacks** (`make up`, `make docker-start`): an existing host instance is only reused when containers can actually reach it — on Linux it must listen beyond loopback (Docker Desktop proxies loopback through `host.docker.internal`); otherwise the bundled service starts. The Gateway reaches the bundled service in-network at `http://searxng:8080` (wired via `DEER_FLOW_SEARXNG_BASE_URL`), and it is also published on `127.0.0.1:8088` for debugging — loopback only, never on the LAN.
- **Host-run** (`make dev`, `make start`): the launcher reuses a running instance or starts the bundled container itself (requires Docker; without it, a warning explains the options). `make searxng` / `make searxng-stop` remain for manual control; note `make stop` leaves the container running. It serves `http://localhost:8088`, which matches the default `base_url` in `config.yaml`.
- **Instance settings** live in [docker/searxng/settings.yml](docker/searxng/settings.yml): the JSON API is enabled (required by DeerFlow's client) and the bot limiter is disabled for the private in-network instance. Set `SEARXNG_SECRET` in `.env` before exposing the instance beyond localhost.
- **Bring your own instance**: set `DEER_FLOW_SEARXNG_BASE_URL` in `.env` to skip auto-detection and point the Gateway at any reachable SearXNG (its `search.formats` must include `json`).
- **No Docker / prefer zero dependencies?** Swap the active `web_search` entry in `config.yaml` back to the commented DuckDuckGo provider — no local service required.

##### When every engine blocks you at once: the `web_search` fallback

SearXNG scrapes consumer engines, so it inherits your IP's reputation. Behind a commercial VPN or from a datacenter range, Google, DuckDuckGo, Brave and Startpage can all CAPTCHA or drop you at the same time — and a blocked engine is benched for ~180 seconds, so retrying makes it worse. No engine mix survives that, because the block lands at the network tier before a query is ever parsed.

`web_search` therefore goes through a dispatcher with two backends, shipped Tavily-first:

```yaml
  - name: web_search
    group: web
    use: deerflow.community.web_search.tools:web_search_tool
    backend: tavily                   # tavily or searxng
    fallback: searxng                 # covers no-key, over-limit and unreachable
    base_url: http://localhost:8088
    max_results: 5
```

A keyed API is authenticated, so your exit address stops mattering. SearXNG takes over in three cases:

- **No `TAVILY_API_KEY`.** Tavily is skipped entirely — not attempted and failed — and SearXNG runs as the only backend. A fresh clone searches locally and works out of the box, with no credentials error.
- **Tavily over its plan limit**, or erroring for any other reason.
- **Tavily unreachable.**

The SearXNG container is still required in all three, and every launch path still starts it.

**Want local-first instead?** Swap the two values:

```yaml
    backend: searxng
    fallback: tavily
```

The dispatcher is symmetric, with one deliberate asymmetry: a fallback fires only when the primary *raises*, never when it succeeds with zero results. A search that genuinely matched nothing stays wherever it ran and costs no third-party credit.

Set the backend for one run without editing config via `DEER_FLOW_WEB_SEARCH_BACKEND=searxng`.

> **Privacy note.** With the shipped Tavily-first ordering, searches leave your machine by default. That is the trade for search that works from a blocked address. The local-first swap above reverses it.

#### Docker Production Deployment

`./scripts/deploy.sh` supports building and starting separately:

```bash
# One-step (build + start)
./scripts/deploy.sh

# Two-step (build once, start later)
./scripts/deploy.sh build       # build all images
./scripts/deploy.sh start       # start pre-built images

# Stop
./scripts/deploy.sh down
```

> **Applying config-only changes (e.g. `BIND_HOST`, `PORT`):** the bare
> `deploy.sh` (`make up`) rebuilds every image, which is slow and unnecessary
> when you only edited `.env` or `config.yaml`. Prefer `deploy.sh start`
> (`make up-start`) — it restarts the pre-built images with the new environment,
> no rebuild. Only re-run `deploy.sh build` (or `make up`) after a code or
> dependency change.

### Advanced

Upstream's advanced topics are in the [Guides](#guides):
[Sandbox Mode](docs/guide/sandbox.md#sandbox-mode), [MCP Server](docs/guide/mcp.md),
[IM Channels](docs/guide/im-channels.md), [tracing](docs/guide/observability.md)
(request trace correlation, LangSmith, Langfuse, Monocle),
[multiple providers](docs/guide/configuration.md#using-multiple-providers), and
[stream actions and personal access tokens](docs/guide/api-and-client.md).
This fork adds the containerized sandbox below.

#### Containerized sandbox & private GitHub repos

**Why:** the default `LocalSandboxProvider` runs file tools against the host
filesystem and keeps host `bash` disabled (`sandbox.allow_host_bash: false`)
because the host is not an isolation boundary. The containerized **AIO
sandbox** gives the agent a full shell, per conversation, inside an isolated
Docker (or Apple Container) container instead — enable it when you want the
agent to run real commands, e.g. cloning and working on a GitHub repo. The
local default stays unchanged; this mode is strictly opt-in.

**Setup** (Linux with Docker, from a fresh clone):

1. `make check` — Docker is reported as an optional dependency; this mode needs it.
2. `make install` and `make config`
3. In `config.yaml`, comment out the "Option 1" local sandbox block and
   uncomment the "Option 2" AIO sandbox block
   (`use: deerflow.community.aio_sandbox:AioSandboxProvider`), including its
   `environment:` map with `GITHUB_TOKEN: $GITHUB_TOKEN` if you need private
   repos.
4. For private repos: create a **fine-grained personal access token** at
   github.com → Settings → Developer settings → Fine-grained tokens. Restrict
   *Repository access* to just the repos the agent needs. **Contents:
   Read-only** is enough to clone; for the agent to push a branch and open a
   pull request, grant **Contents: Read and write** and **Pull requests: Read
   and write**. Put it in `.env` as `GITHUB_TOKEN=...` (see `.env.example`);
   `GITHUB_PERSONAL_ACCESS_TOKEN=...` works too, and the same token reaches the
   GitHub MCP server under the name it reads. Without a token, GitHub stays
   anonymous (public repos only) and DeerFlow still starts.
   A running sandbox keeps the token it was created with, so restart DeerFlow
   after rotating it.
5. `make dev` — the preflight verifies Docker is usable, pulls the sandbox
   image on first run (it is large), and prints an actionable error with
   fallback instructions when the environment cannot run containers. Sandbox
   containers are then created per conversation on first use and
   health-checked with a 60s timeout.

**How git auth works:** when a sandbox container starts, DeerFlow installs a
git credential helper inside it that reads `GITHUB_TOKEN` from the container
environment at git-invocation time. The agent just runs
`git clone https://github.com/owner/repo.git` — the token never appears in
clone URLs, tool output, shell history, server logs (container-run command
logging redacts environment values), or the clone's `.git/config`. Without a
token, public repos keep working and a private clone fails fast with a hint
explaining what to set, instead of a cryptic username prompt.

**Mounts vs in-container cloning:** prefer letting the agent clone *inside*
the container — isolated, disposable, nothing on the host changes. Use
`sandbox.mounts` to bind host directories into the container only when the
agent must edit an existing host checkout; mounted paths are host files, so
the container boundary does not protect them.

**Security note:** the token is ordinary process environment inside the
sandbox container, so *any code the agent runs there can read it*. That is
inherent to giving the agent authenticated git. Scope the token minimally —
fine-grained, selected repositories, only the permissions the task needs
(Contents read to clone; Contents and Pull requests write to deliver a PR) —
rotate it periodically, and never reuse a classic all-repos PAT here.

## From Deep Research to Super Agent Harness

DeerFlow started as a Deep Research framework — and the community ran with it. Since launch, developers have pushed it far beyond research: building data pipelines, generating slide decks, spinning up dashboards, automating content workflows. Things we never anticipated.

That told us something important: DeerFlow wasn't just a research tool. It was a **harness** — a runtime that gives agents the infrastructure to actually get work done.

So we rebuilt it from scratch.

DeerFlow 2.0 is no longer a framework you wire together. It's a super agent harness — batteries included, fully extensible. Built on LangGraph and LangChain, it ships with everything an agent needs out of the box: a filesystem, memory, skills, sandbox-aware execution, and the ability to plan and spawn sub-agents for complex, multi-step tasks.

Use it as-is. Or tear it apart and make it yours.

## Guides

Each guide is upstream's full reference for its topic. Open the one you need.
Where this fork changes a topic, its section in this README describes the fork's
version; the [Table of Contents](#table-of-contents) lists them.

| Topic | Guide |
| --- | --- |
| Models, providers, `config.yaml`, environment variables | [Configuration](docs/guide/configuration.md) |
| Docker, local development, upgrades, production deployment | [Running the Application](docs/guide/deployment.md) |
| Sandbox modes, file system, uploads and outputs | [Sandbox](docs/guide/sandbox.md) |
| Skills, built-in tools, script workflows, Claude Code integration | [Skills & Tools](docs/guide/skills-and-tools.md) |
| Edit gates, verify-before-finish, the skill learning loop, bundled coding skills, git and PRs | [Coding Agent](docs/guide/coding-agent.md) |
| MCP servers | [MCP Server](docs/guide/mcp.md) |
| Sub-agents and task delegation | [Sub-Agents](docs/guide/subagents.md), [Tool restrictions](docs/guide/subagents.md#tool-restrictions) |
| Long-term memory | [Long-Term Memory](docs/guide/memory.md) |
| Session goals, context compaction, task notes, evidence-based decisions | [Context, Goals and Agent Decisions](docs/guide/context.md) |
| The deviation monitor: turning it on per chat, cadence, what a stop looks like | [Deviation Monitor](docs/guide/deviation-monitor.md) |
| Private knowledge retrieval (RAGFlow) | [Private Knowledge Retrieval](docs/guide/knowledge-retrieval.md) |
| Agentic browser control | [Agentic Browser Control](docs/guide/browser-control.md) |
| Projects, instructions, document shelf | [Projects](docs/guide/projects.md) |
| Scheduled tasks | [Scheduled Tasks](docs/guide/scheduled-tasks.md) |
| Feishu, Slack, Telegram, Discord, DingTalk and other IM channels | [IM Channels](docs/guide/im-channels.md) |
| File attachments, downloads, Office previews and the CAD model preview | [File Previews](docs/guide/file-previews.md) |
| The CAD design page: the CAD container and image, version folders, what the checks mean, limits | [CAD Design Page](docs/guide/cad-design.md) |
| Token usage dashboard, workspace, chat archive | [Workspace UI](docs/guide/workspace.md) |
| Terminal workbench | [Terminal Workbench (TUI)](docs/guide/tui.md) |
| Personal access tokens, stream actions, embedded Python client | [API Access and Python Client](docs/guide/api-and-client.md) |
| Trace correlation, LangSmith, Langfuse, Monocle | [Tracing and Observability](docs/guide/observability.md) |
| Deployment risks, admin model, security recommendations | [Security Notice](docs/guide/security.md) |

## Core Features

Upstream's core features (skills and tools, knowledge retrieval, sub-agents, the
sandbox, context engineering, browser control, long-term memory and the
workspace pages) are documented in the [Guides](#guides). The subsections below
are what this fork adds or changes.

### Subscription Models

Open **Settings → Models → Subscriptions** as an administrator. Connect the
server's subscription once; the provider's available models appear in the existing
model picker immediately, without editing `config.yaml` or restarting DeerFlow.
**These are shared server connections**, like administrator-managed API models:
any user authorized to use a discovered model consumes that connected account's
allowance. One connection is active per provider.

| Provider | Connect in settings | What it uses |
| --- | --- | --- |
| ChatGPT | Continue with ChatGPT → sign in on OpenAI's page → paste the final return URL | Your eligible ChatGPT plan through OpenAI's public Responses API |
| Grok | Sign in to Grok → open the official sign-in page and enter the displayed device code | Subscription access through xAI's documented CLI proxy |
| Kimi Code | Enter your **Kimi Code subscription key** | The coding-plan endpoint, distinct from a Moonshot paid API key |

**ChatGPT sign-in can stay in the browser.** Select **Continue with ChatGPT**,
then open the official sign-in link in the dialog. After authorizing your plan,
OpenAI redirects to an address starting with `http://127.0.0.1:`. On a remote
LAN/Tailscale setup, that tab may show a connection error. Copy its **complete
address from the address bar**, return to DeerFlow, and paste it into the return
URL field to complete sign-in. No Python installation or downloaded script is
needed for this path. Use HTTPS or your trusted Tailscale connection for the
handoff; the URL contains a short-lived authorization code and should stay private.

This manual handoff is DeerFlow's adaptation of OpenAI's loopback authorization
code flow, rather than an OpenAI-documented remote-browser workflow. The server
owns the PKCE verifier and validates the exact return address, one-time state,
nonce and signed grants. OpenAI's public open-source flow still requires a
`127.0.0.1` redirect, so a fully automatic return to your LAN/Tailscale web address
is unavailable without a separately registered OpenAI website integration.

**The local helper remains available as a fallback.** If your browser or provider
does not leave a usable return URL, expand the helper option in the dialog.
Download the helper and run it on the computer with your browser, using Python
3.12+ and
[uv](https://docs.astral.sh/uv/):

```bash
uv run deerflow-chatgpt-login.py
```

It opens the official ChatGPT authorization page, asks permission to use your plan,
and writes `deerflow-chatgpt-connection.json` with owner-only file permissions on
Unix. Import that file in the same settings dialog over HTTPS or your trusted
Tailscale connection, then delete the transfer copy. Keep the helper's protected
local registration directory: later sign-ins reuse the account's issued client ID.
Use `--profile another-account` to register another account/workspace, then import
that account's file to replace the server's active connection. This step requires
a computer that can run the helper; it is not a phone-only sign-in flow.

DeerFlow validates signed ChatGPT identity and plan grants before accepting the
browser handoff or import, preserves a separate host identity for the server, and owns subsequent
refresh-token rotation. The helper and web settings do not reuse Codex's private
endpoint or scrape a browser session. The existing manually configured Codex
provider remains separate. This ChatGPT adapter currently returns the completed
streamed response rather than live text deltas.

Use **Refresh models** to discover additions or remove models the account no
longer offers. A temporary discovery error preserves the previous catalog.
**Disconnect** removes that provider's discovered models and stored credentials
from future calls and attempts to revoke its renewable OAuth session. If remote
revocation cannot be confirmed, settings says so; disconnect the app at the
provider too. ChatGPT keeps its non-secret client registration to reuse on the
next sign-in. To switch ChatGPT accounts, disconnect first, then choose
**Use another ChatGPT account** in the sign-in dialog. Manual YAML and API models
are preserved. Selected subscription
models never silently fall back to separately billed API models.

**Kimi Code is for personal interactive use.** Its third-party path uses a
subscription key, rather than impersonating Kimi CLI's OAuth client. Scheduled,
webhook, and other autonomous runs are refused before contacting Kimi; use a
normal paid API model for unattended work. Client identity stays DeerFlow.

**A plan request that never answers now times out.** Grok and Kimi subscription
models had no network timeout: a request the provider accepted and then left
unanswered showed "Working" indefinitely. They now wait at most 10 seconds to
connect and 240 seconds for each read, retry like any other network error
(three attempts by default), and then show the ordinary error message — up to
about twelve minutes in the worst case. A long answer that
keeps streaming is not affected. There is no setting for it, because these
models come from the discovered catalog rather than `config.yaml`. Grok
reasoning models also show their thinking text while they think, when the
provider sends it. Neither change was tested against the live Grok service.

Provider plans, account eligibility, model capabilities, quotas, and regional
availability still apply. Models come from each account's catalog; listing a
model does not guarantee that its next inference request will be admitted.
Subscription token usage is kept separate from paid API identities, with no
invented per-token price. Credentials are encrypted under the persistent runtime
home's `subscriptions/` directory; back up its local key with the encrypted file,
just as for administrator-managed API models. Tokens never appear in status
responses or model configuration sent to the browser.

Provider references: [OpenAI plan access](https://developers.openai.com/siwc/token-sharing-open-source),
[remote ChatGPT hosts](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms),
[xAI's documented direct access](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-shell/README.md#using-authjson-for-api-access),
and [Kimi Code usage guidelines](https://www.kimi.com/code/docs/en/kimi-code/community-guidelines.html).

#### Grok Features: Imagine, X Search and Voice

A connected Grok subscription can do more than chat. In **Settings → Models →
Subscriptions**, the Grok card lists four **Grok features**, each with a switch:
**image generation and editing** (Grok Imagine), **video generation** (Grok
Imagine), **X search**, and **voice** (read answers aloud, and transcribe the
microphone when no local transcription service is configured). They use the
same sign-in as Grok chat and are paid for by the plan, not by API billing, for
every user of this server — the connection is shared, like the models.

**Every switch starts off**, and turns off again when Grok is reconnected. On
connect and on **Refresh models**, DeerFlow asks xAI what this grant can reach
without generating anything. Each feature then shows **On your plan**, **Not on
your plan** (xAI refused it; the switch stays locked) or **Couldn't check**
(DeerFlow could not tell; you may still switch it on, and a refusal is reported
when it is used). Image and video always show *Couldn't check*: they run on the
subscription's own Imagine quota, the same host Grok chat uses, which the check
cannot see — xAI's public API refuses a subscription for Imagine on billing
grounds even when the plan includes it. Turning a feature off takes effect on the very next request,
including inside a run that is already going.

Once switched on, the agent gets these tools:

| Tool | What it does | Sends to xAI |
| --- | --- | --- |
| `grok_generate_image` | Up to four images from a prompt, with an optional aspect ratio | The prompt |
| `grok_edit_image` | Changes one picture, or combines up to five, from an instruction | The prompt and the images (PNG/JPEG/WebP, up to 20 MB each) |
| `grok_generate_video` | A clip of up to 15 seconds from text, a first-frame still, or reference images | The prompt and any images |
| `x_search` | Answers what people on X are saying, with links to the posts | The query |

Results land in the conversation's outputs and open in the artifact panel, with
a `<name>.request.json` beside each file recording the request (source images
by path, never their contents). **Local generation stays the default**: the
agent is told to prefer the on-machine ComfyUI tools when they are available and
you did not ask for Grok. The Grok tools sit outside the local `media` group, so
**the chat's internet switch removes all of them**. Grok video gets no contact
sheet — DeerFlow cannot decode video yet — so the agent asks you to watch the
clip rather than claiming it did. A plan-quota refusal is reported once and
never retried; xAI does not publish Imagine quotas, and video clips use the
scarcest share.

With **voice** on, answers show a speaker button that reads them aloud through
Grok (up to 12,000 characters; code blocks are skipped), and the microphone
transcribes through Grok when `voice.stt.enabled` is false. **A local
transcription service always wins** when one is configured, and its failures are
never retried against xAI. Both voice paths say that the text or recording goes
to xAI. Grok voice does not depend on `voice.allow_cloud_fallback`, which still
governs only the browser's own cloud recognition.

Grok models that xAI serves only through its newer Responses API also appear in
the picker, but only once the probe shows this grant reaches xAI's public API.

The tool entries ship active in `config.example.yaml` (and are added to an
existing `config.yaml` by the config upgrade); they stay invisible until a
feature is switched on. Optional keys on each entry:

```yaml
tools:
  - name: grok_generate_video
    group: cloud_media
    use: deerflow.community.xai.tools:grok_generate_video_tool
    # model: grok-imagine-video      # default: the account's listed model
    # timeout_seconds: 900           # give up waiting after this long
    # poll_interval_seconds: 5
    # download_hosts: [x.ai]         # where Grok's temporary file links may live
```

Whether a given SuperGrok tier accepts this API access is xAI's decision, and
some subscribers have reported refusals despite an active plan; the per-feature
badges show what your grant actually got. References:
[xAI on Grok subscriptions in third-party agents](https://x.ai/news/grok-hermes),
[Imagine](https://docs.x.ai/developers/model-capabilities/imagine),
[X Search](https://docs.x.ai/developers/tools/x-search),
[text to speech](https://docs.x.ai/developers/model-capabilities/audio/text-to-speech).

### Token usage dashboard

Open **Token usage** in the workspace sidebar (`/workspace/usage`) to review
your recorded tokens over the last 7 or 30 days, daily input/output totals,
cache-hit input tokens by model, and paginated run history with failure filters.

**Every total is split into input and output.** The headline tile lists input
(with how much of it came from the prompt cache) and output beneath the total,
each with its share; each day's bar stacks cached input, the rest of input and
output, with a legend; the model table and every run row carry input and output
columns. Input is the context resent on every call, so a heavy day that is
mostly input points at long conversations or attachments, and one that is
mostly output at long answers. **The parts always add up to the total:** cache
hits are a part of input, never added on top of it, and where a provider
reported a total without its split the difference is shown as its own
**unattributed** part rather than counted as input or output.
Run history covers all dates independently of the selected chart period.
Conversation links use each run's recorded assistant to open the default or
matching custom-agent chat.
Periods with no recorded runs show an empty message without a date axis or
zero-filled daily details; runs with zero reported tokens still show details.

Reporting requires `runs:read` permission and a SQLite or PostgreSQL database;
it is unavailable in the static demo. Counts reflect persisted provider usage,
may be incomplete during active runs or when providers omit usage, and are not
a provider bill. Cache hits are included in input tokens. Daily buckets use the
browser's current UTC offset and attribute a run to its creation date.
The page reuses the existing `/api/console` APIs; their optional cost and currency
fields and server-side pricing configuration remain supported.
See [dashboard behavior and design](frontend/docs/token-usage-dashboard.md).

### Local Models Get the Parallelism the GPU Has

Sub-agent concurrency used to be one number, `subagent_runtime.max_running`, chosen at startup and applied to every model. That is right for a hosted model and wrong for a local one, because the thing that actually limits a local model is your graphics card — and a 4B model and a 120B model on the same card are not the same amount of parallelism.

The symptom was never an error. **Ollama does not refuse an over-dispatch; it hides it.** Ask for three sub-agents on a model that fits your card once and the extra requests queue *inside the daemon*, invisible to the app, while each sub-agent's own timeout counts down against a request that has not started yet. Use Ultra mode to put sub-agents on a *different* local model than the lead and it gets worse: the daemon evicts one model's weights to load the other's, every time the run alternates between them. Both cases look identical from the outside — local sub-agents are slow, and nothing says why.

Now the question is asked per dispatch, against your card. Five sub-agents on a model that fits once run one after another. On a model your card holds twice, two at a time. On models small enough to co-reside, all of them at once — **the feature exists as much to keep real parallelism as to prevent fake parallelism**. A model too big for the card at all still runs; it is offloaded and slow (see the context-window sizing above), so it gets the card to itself rather than being refused.

**The limits that bite.** Two sub-agents sharing one loaded model is governed by `ollama.num_parallel`, which must match your daemon's `OLLAMA_NUM_PARALLEL` — Ollama never loads a second copy of a model it already has resident, so that setting, not your free VRAM, is the ceiling there. The gate only engages when it has real numbers: it needs the GPU memory set, in Settings → Models or as `ollama.vram_gb` (`make setup` detects it) and the per-model sizing that `scripts/sync-ollama-models.py` writes on every launch. **A hosted model, or a local model whose size it does not know, is never gated** — it dispatches exactly as it did before. And it cannot stop a local lead model and a local sub-agent model from evicting each other; that is inherent to choosing two models, and the launch-time VRAM warning already tells you when they do not both fit.

It is **on by default**, and needs no configuration beyond the `ollama:` block `make setup` already writes:

```yaml
subagent_runtime:
  max_running: 3                 # still the process-wide ceiling for every model
  local_model_capacity:
    enabled: true                # on by default; false restores the old behavior
    queue_timeout_seconds: 1800  # how long a sub-agent waits for the GPU before failing

ollama:
  vram_gb: 24        # required for the gate to engage at all
  num_parallel: 1    # must match the daemon's OLLAMA_NUM_PARALLEL
```

`queue_timeout_seconds` here is deliberately much larger than `subagent_runtime.queue_timeout_seconds` (300s): that one bounds a wait for a process slot, this one bounds a wait for work that is *supposed* to be serialized, and the fifth of five sequential sub-agents should not fail just for being fifth. **This does not add waiting** — five sub-agents on a card that holds one take the same total time whether Ollama serializes them invisibly or this does; it just makes the queue visible and tunable. Do keep the total in mind, though: `subagents.timeout_seconds` (30 minutes by default) is measured from the moment a sub-agent is dispatched, so a long serialized batch can lose its last item to that timeout.

### Democracy — Several Models Answer, Then Decide Together

Every other model control in this fork exists to spend *less*. **Democracy**
deliberately spends more, for the one thing a single model cannot give you: a
second opinion that did not come from the same model. One **organizer** model
gathers the facts, puts the identical question to several different **panelist**
models, has them read each other's answers and revise or hold, and then
synthesizes the result — reporting where they agreed, where they split, and who
dissented.

Start it from **Democracy**, directly under *New chat* in the sidebar. It opens a
setup page — a real page, like *New chat*, not a popup — asking how many
panelists you want, which model organizes, which model fills each seat, how the
panelists get graded, and what the task is. **You can attach files to the task**,
not just type it: the organizer reads them once and shares them with the panel
like any other shared fact. Your task then lands in the composer of a fresh chat
rather than being sent automatically, so you get a last look before spending it.

**It stays a panel after the first answer.** Ask a follow-up and the whole panel
runs again — you are not left talking to the organizer alone once the interesting
part is over. Each panelist is re-briefed with its own previous answers, what the
review round argued about, and the answer you were given last time, so it can
build on the discussion instead of starting from scratch. You still see exactly
one answer per question: the organizer's. The panel does not fan out into
separate replies for you to reconcile.

**The organizer also grades the panelists**, if you ask it to. Pick *Score out of
5* or a plain *yes/no* at setup and each answer ends with a short table: how each
model contributed this turn, and why. It grades the **contribution**, not
agreement with the conclusion — a dissent that turned out to be right scores
well, and a panelist that just restated the majority does not, however correct it
happened to be. Over a few turns that is a straight read on which models are
earning their seat. Leave it on *No grading* and answers end where they always
did.

**The organizer does the research once, and nobody double-checks it.** This is
the part that keeps the mode affordable. Asking five models to each look up the
same interest-rate decision costs five times as much *and* gives you five
slightly different datasets — so your panel ends up disagreeing about its inputs
while looking like it disagrees about its judgement. Instead the organizer
collects everything itself, writes one plain factual brief, and hands **the same
brief, word for word**, to every panelist. Facts are then taken as given: sources
are recorded and anything contested is flagged, but the panel is **not** asked to
verify them, because a verification round across five models is exactly the cost
this design refuses to pay. Treat the facts as one model's research, not as five
models' agreement.

**Panelists review each other anonymously.** In the review round each one sees
the others' answers labelled "Panelist A", "Panelist B" — never which model wrote
them. A model told it is arguing with a bigger-name model tends to defer to the
name instead of the argument, which would turn a panel into an expensive way of
asking one model twice.

**The synthesis is asked to stay objective, and specifically not to average.**
The organizer must report the real distribution including a lone dissenter, must
not flatten a 4-1 split into "the panel concluded", must not treat model count as
evidence, and must not favour its own earlier hunch or the panelist that happens
to be the model it likes. A well-argued minority position can be the right one.

**It is extremely token-heavy, and the dialog says so before you commit.** A
panel of N models dispatches up to **N x 2 full model runs** — every panelist
answers, then every panelist reviews — on top of the organizer's own research and
synthesis, **and that is per question**: a standing panel bills again on every
follow-up. The warning box also estimates, from your configured prices, roughly
how many times a single organizer answer the panel's rates come to. That figure
is a **rate multiple, not a bill**: predicting a run's token count would be a
guess dressed up as a number. Local Ollama models count as $0 here as everywhere
else, and are named in the warning so a suspiciously cheap-looking panel explains
itself. Your `spend_budget` caps and the per-step cost chart still apply, so the
real cost shows up per panelist after the run.

**Limits worth knowing.** A panel needs at least 2 and at most 12 models, and
each seat must be a *different* model — the same model twice is one opinion at
twice the price. Panelists actually run concurrently only up to
`subagent_runtime.max_running` (default **3**); a larger panel still runs in full,
it just queues. Raise that value in `config.yaml` and restart if you want the
whole panel in flight at once:

```yaml
subagent_runtime:
  max_running: 5    # default 3 — concurrent panelists, restart required
```

There is nothing to switch on: Democracy needs no config keys and is available as
soon as you have two or more models configured.

### Plus Ultracode and Double Plus Ultracode — The Plan Becomes a Script

**Plus Ultracode** is inspired by Claude Code's *ultracode*. Ultra keeps the
whole plan in the lead agent's head: every subagent result lands in its context,
and it is tuned to delegate sparingly. Plus Ultracode takes the opposite
shape. For a substantive request the agent writes a **workflow script** (plain
JavaScript you can read), the [Script workflows extension](examples/deerflow-extension-workflows/README.md)
runs it in the background across many agents, intermediate results stay in the
script, and only the final answer comes back to the conversation.

**Two modes, one script.** *Plus Ultracode* is that workflow with the usual
tool-call limits still on (wrap up after repeated calls to one tool, then a
forced stop). *Double Plus Ultracode* is the same run — same brief, same agent
count and parallelism — with **the automatic limits lifted**: no step limit (the
1,000-step `max_recursion_limit` ceiling does not apply to it), no loop or
tool-call limits (including the number of `task` subtasks per run), no token
budgets and no workflow time limit, for the lead, every agent the workflow
starts, every `task` subagent it delegates to, and the turn that receives the
result. A follow-up workflow launched from that result keeps the mode.

That is not the same as "nothing stops it". These still end a Double Plus run or
its workflow on their own:

| Still applies | What happens |
| --- | --- |
| **The spend cap, if you set one** | Off by default, so a stock install has no money limit on this mode: set one under **Settings → Run limits** before a large run. Agents that run in parallel each check their own spend, so together they can end somewhat above the cap. |
| **Agents per workflow and at once** | Your **Settings → Subagents** numbers. Calls past the parallel limit wait; a call past the total fails the workflow. |
| **Size limits** | A task (16,000 bytes), an agent's answer (12,000 bytes) and the script's final result (12,000 bytes, about 8,000 characters) are capped, and so are progress lines, phases and the workflow's stored record. Errors name the limit. |
| **A configuration change during the run** | Editing `config.yaml`, or switching a skill or an MCP server on or off in Settings, fails a running workflow at its next agent. |
| **Workflows at once** | Two active per user and four in all by default. With no time limit, two long Double Plus workflows block that user's next launch until one ends. |
| **The model provider** | An answer cut off at the model's output limit, a safety stop, a model call that keeps failing after its retries, or a request that cannot fit the model's window still end a turn. |
| **`/goal`** | Its continuation caps are unchanged. |

**A warning line stays in the composer** for as long as Double Plus Ultracode is
selected ("Token-risky: runs until the task is finished"), so it is visible on a
phone, in a chat that opens already in the mode, and while a run streams. Hover
or focus the option in the mode menu, or the mode button, for the full text. A
chat that already had the old Double Plus Ultracode name keeps Plus Ultracode,
so it does not silently lose its limits. Do not leave Double Plus Ultracode
selected for ordinary chat.

**What a run looks like.** You pick *Plus Ultracode* or *Double Plus Ultracode* in the composer's mode
menu and ask. The agent plans the work in phases (usually understand, change,
verify), launches the script, tells you in a sentence what is running and ends
its turn. When the workflow finishes, its result is **posted into the same chat
automatically** and the agent writes the answer from it. The posted message shows
as a *Posted by Script workflows* card, not as something you typed, and the agent
is told it is untrusted output from other agents. It is posted **exactly once**,
even across retries or a second Gateway. If the chat is busy (a run in progress,
an open question) it waits rather than interrupting. Cancelled workflows post
nothing. After a Gateway restart a pending result is posted the next time you open
**Script workflows** or use any workflow tool.

**What the scripts can do.** Besides `agent()`, `parallel()`, `log()` and
checkpoints, a script can group its work with `phase(title)` (the progress page
shows steps under each phase), fan out over a long list with
`pipeline(items, fn, {concurrency})` (one lazy agent per item, never more than the
window in flight), run each item through several stages with
`pipeline(items, stage1, stage2, ...)` (later stages get the previous result),
require an agent's answer to match a JSON `schema` (a mismatch
is re-asked up to twice, on the same child conversation, under new attempt
identities), and run a step on a different `model`, so a fan-out can use a cheap or
local model while the organizer stays strong. The model choice goes through the
same `model:use` permission check as any other run. `Date` and `Math.random` stay
unavailable, so a recovered workflow replays exactly. A wide fan-out no longer
fails for being wide: `parallel()` takes up to 1,000 calls, and calls beyond the
64 the host holds at once wait their turn.

**Agents use the conversation's model and its internet switch.** A workflow's
agents and the turn that receives the result are runs of their own. They now
start on the model the conversation is on, unless a step names another, and
with web tools off when the conversation's internet switch is off. Before, they
used the server's default model and kept their web tools.

**Inspired by Claude Code's ultracode, not the same thing.** The shape matches:
a script in an isolated worker, a background run, only the final value comes
back. These parts of the original are not here: a script has no `budget` object
to read or divide, it cannot start another workflow with a nested `workflow()`
(the agent can launch a follow-up after reading a result), there is no `meta`
header, the chat shows **no progress tree** while a workflow runs (steps, phases
and logs are on the **Script workflows** page only), and a failed workflow
cannot be resumed or replayed from the chat. What the agent does get for a
failed or oversized run is a tool that reads the output of each step that
finished, so that work is not redone.

**Shared workspaces are opt-in.** By default every agent works in its own empty
workspace. With `shared_workspace: read` in the extension's operator config a step
can ask for `workspace: "snapshot"`: it starts from a copy of the launching chat's
workspace and uploads. With `shared_workspace: write` a step can also ask for
`workspace: "merge"`: when it finishes, its edits to `workspace/` and `outputs/` are
written back, but **only for files the chat still holds unchanged**. A file that
changed meanwhile is reported as a conflict and left alone, deletions are reported
and never applied, and uploads are never written back. So parallel agents can edit
disjoint files of one project. This needs thread data that the sandbox mounts from
the host (the local sandbox, or AIO with `thread_data_mounts`); anything else fails
closed.

**Limits.** Under **Settings → Subagents → Ultracode limits** you set the
most agents one workflow may start, how many run at once and how many minutes the
whole workflow may take. They default to the extension's maximums (256 agents, 16
at once, 240 minutes), because the agent sizes each workflow to its request and a
low default only cut long tasks short. They can only make a run smaller: the
extension clamps each to the operator's `max_calls`, `concurrency` and
`timeout_seconds`, which now ship at those same maximums. An existing install's
untouched values (64, 8 and one hour) are raised on its next update, and a value
you set yourself stays. Workflows that may start more than 25 agents come back
with a size advisory, and the agent is told to name the planned size before
launching one that large.

**One failed agent does not end the workflow.** The agent is told to catch each
agent's failure in its script, so an agent that errors is reported in the result
instead of cancelling the others. Agents are told they run unattended and to keep
their answer under the 12,000-byte limit; an agent that asks a question anyway
fails only its own step. When a workflow still fails or leaves steps unfinished,
the failure message names the unfinished steps and why, and the agent finishes
the rest itself or launches one smaller workflow for just that part, instead of
stopping at a failure report. A launch that is refused (too many active
workflows, a script that is too large) comes back to the agent with the reason,
so it can fix it rather than report a generic error. A result waits up to a day
for a busy chat to finish its turn, or for a spend cap that refused it, before it
falls back to being posted on your next workflow action.

**What it costs.** It is very token-heavy: every agent is a full run. Each agent
runs in its own conversation linked to yours, so the chat header's cost dropdown
shows a **Workflow agents** row with their combined spend. It is kept outside the
chat's own total and chart, because none of it is a turn of this chat. Your
`spend_budget` caps still apply: when a cap refuses a new agent the workflow fails
cleanly ("Spend cap reached; no new agents were started") instead of waiting on a
reconciliation. There is no hard per-workflow money budget, and the cap is not
exact for a workflow: each agent checks its own spend against the total that
stood when it started, so agents started together can each use the remaining
allowance before a later one is refused.

**It is on by default.** The Script workflows extension ships bundled: a locked
snapshot in `backend/extensions/sources/deerflow-extension-workflows` that every
`uv sync` and image build installs (POSIX only; Windows skips it), and an enabled
record in `config.example.yaml`:

```yaml
plugins:
  - name: workflows
    package: deerflow-extension-workflows
    use: deerflow_extension_workflows:install
    enabled: true
    required: false
    config:
      enabled: true
      storage_path: workflows/workflows.sqlite  # relative = under DEER_FLOW_HOME
      agents: [lead_agent]       # Agents a workflow may start
      concurrency: 8             # at once per workflow (ceiling 16)
      global_concurrency: 16     # across all workflows (ceiling 32)
      max_calls: 64              # agents per workflow (ceiling 256)
      timeout_seconds: 3600      # wall time per workflow (ceiling 14400)
      shared_workspace: "off"    # "off" | "read" | "write" (quoted: YAML reads off as false)
      deliver_results: true      # post finished results back into the chat
```

An existing install gets that record from `config_version` 66 on its next start
after `git pull` (every launcher runs `make config-upgrade` first; a record you
already have is left alone). The mode spends nothing until you pick it. To turn
it off, run `make extension-disable NAME=workflows` and restart; if the extension
is disabled or failed to load, a remembered selection falls back to Ultra and
says so.

It works from the web app only: channels, schedules and API tokens have no browser
session to start workflows with, and there the agent says the mode is unavailable
and answers as Ultra. The lead model needs tool support, as in Ultra.

### Run Limits — What Can End a Run Early

**Settings → Run limits** (administrators only) is where you change, or switch
off, every limit that can end a run before its task is done. Before, each one was
a number in `config.yaml`, and the only symptom of hitting it was an agent that
said it "stopped before" the work you asked for:

- **Spend cap** — the daily / weekly / monthly amounts in your pricing currency.
  Leave a window blank for no cap in it; switch it off to stop enforcing it.
- **Tool-call limits** — the agent is told to wrap up after 30 calls to one tool
  and forced to answer after 50, and after 3 and 5 identical calls. Long tasks
  such as an upstream merge make hundreds of `bash` calls, so raise these or
  switch them off for that kind of work. **A value set here applies to every
  tool**, including any tool `config.yaml` gives its own limit.
- **Token budget per run** and **per subagent** — the subagent one is **on by
  default** (one to two million tokens).
- **Steps for background runs** — the step limit for runs that do not choose
  their own: workflow agents, channels and API calls. Chats in the web app always
  get the maximum, `max_recursion_limit`; Double Plus Ultracode runs get no step
  limit at all.

Each limit shows whether it comes from `config.yaml` or was set on the page, and
**Use config.yaml** puts it back. The page never edits `config.yaml`: its values
are stored server-wide beside it (`runtime_settings.json` in the DeerFlow home)
and win until you switch back. A change applies from the next run, with no
restart; runs already going keep the limits they started with. Anyone signed in
can read the effective limits through `GET /api/settings/run-limits`; only an
administrator can change them.

**Double Plus Ultracode ignores all of them except the spend cap**, and the page
says so. It does not ignore what is not on this page: the workflow's own agent
and size limits, a configuration change mid-run, and the model provider's stops
still apply to it (see the table under
[Plus Ultracode and Double Plus Ultracode](#plus-ultracode-and-double-plus-ultracode--the-plan-becomes-a-script)).

### Deviation Monitor — A Second Model Keeps the Run on Your Request

A long run can drift without failing: the agent reads a large file, your request
ages out of its window or is compacted away, and it settles into whatever its
remaining context suggests, usually "summarise this". The **deviation monitor**
is a second model that checks, while the agent works, whether its recent steps
still serve what you asked. Turn it on with the **compass button** in the
message box's tool row: the dialog asks for the monitor's model (the same picker
as everywhere else) and how often to check: **every X steps** (1-50, agent steps
within one reply), **every N turns** (1-20, just before the final answer) or
**every turn**. It applies to that chat only, and a reply resumed after a tool
approval still counts as one. A status bar above the message box shows the
latest report (Watching, Checking… with a steps cadence, On track, Unsure,
Possible drift, Stopped) with the reason behind **Details**, and turns the
monitor off in one click, from your next message. **Settings → Deviation
monitor** sets what new chats start with.

**A confirmed drift stops the run.** A step check judges a response before its
tool calls run, so the drifting actions never happen: the response keeps its
text, loses its tool calls, and ends with a note naming the reason and your
request. No reminder or continuation resumes the run; a goal on the chat
stays active for your next message (stand-down reason `deviation_stopped`)
unless the goal check finds the visible answer already meets it. In a mode with
subagents (Ultra, Democracy, Plus and Double Plus Ultracode) the first
confirmed drift **retries once** instead, telling the agent to return to your
request and split the work across subagents; a second one stops it. Small
judges are noisy, so a "drifting" verdict is asked twice and acts only when
both agree or a mechanical signal backs it (a partial read, a truncated result,
repeated tool failures, a compaction during this run, a full window); **an
unsure verdict, a timeout or an error is shown and never acted on**.

The limits that bite: **the agent waits for each check**, so a check every step
can double a run's time on a local GPU, and a second local model that does not
fit beside the main one makes Ollama swap models on every check. Each check is
billed to the run and counted by the spend caps. The monitor sees your request
verbatim, the goal and to-dos, the last six steps and the compaction summary,
sized to its own model's window; when your request alone does not fit, the
check is skipped as unsure. It is advisory, **not a security boundary**: text
the agent read can steer it too. IM channels, schedules and API callers that do
not send the setting are never monitored.

It is offered by default and off in every chat. The operator block:

```yaml
deviation_monitor:
  enabled: true              # false hides the button and ignores any request
  judge_timeout_seconds: 60  # 5-600; a check that runs out of time is unsure
  max_evidence_chars: 24000  # 4000-200000; the monitor model's window lowers it
```

Details, the API shape and how it is to be measured against
`make drift-eval MODE=agent` are in the
[Deviation Monitor guide](docs/guide/deviation-monitor.md).

### Generating Agents From Your History

Custom agents normally start from a conversation on `/workspace/agents/new`, where the
bootstrap flow interviews you and writes a `SOUL.md`. **Generate from history** is the
second way in: instead of answering questions, you point a model at work you have
already done and let it decide whether a new agent is warranted at all.

The flow lives on `/workspace/agents` behind the **Generate from history** button:

1. Pick the model that runs the analysis (any configured chat model, or the default).
2. Pick the past conversations and/or scheduled tasks the new agent should be shaped around.
3. The model reads digested transcripts of exactly those sources, compares them against
   the custom agents you already have, and returns one of two answers.

**"No new agent needed" is a first-class outcome.** If the selected work is one-off, too
varied to specialize, or already covered by an existing agent, the flow says so — and
names the agent that covers it — rather than inventing one. The prompt is deliberately
biased that way: a roster full of near-duplicate agents is worse than no agent.

When a gap *is* found, you get an editable draft — name, description, and full `SOUL.md` —
and nothing is written until you press **Create agent**. The analysis route itself is
strictly read-only; it can propose an agent but cannot persist one.

**You can also just say what you want.** Above the pickers there is an optional
**What should this agent do?** box — a rough description of what to tune the agent for
("something that drafts my weekly client updates in my voice and flags anything needing a
decision"). It steers which parts of the selected work matter and shapes the draft, but it
does **not** decide the verdict: a stated goal still gets checked against your existing
roster, and the flow can still tell you an agent already covers it. When it does, a
**Generate anyway** button on that screen overrides it — the overlap is then carried onto
the draft as a note rather than a dead end, so you keep seeing what it collides with.

**Drafts are refined in place, not regenerated.** Under the draft is a **Refine this
draft** box: "make it more concise", "focus on the review side". It sends the draft exactly
as it stands in the form — including edits you typed yourself — and only what you asked
about is changed; everything else survives verbatim, and the agent is not renamed.

Transcripts are digested before they are sent: tool-result bodies are dropped (the calling
turn still names the tools), only the most recent turns of each conversation are kept, and
per-message / per-source character caps apply. Every source is ownership-checked against
the caller, so the analysis can only read your own history. The call is billed to the
`agent_generation` category on the Spend page.

It is **on by default** in this fork, together with `agents_api.enabled` (which it
depends on, since the accepted draft is created through the custom-agent API — these
are the same routes the Agents pages already use to create and edit agents). Both
suit the local-trusted, loopback-only deployment this fork ships for; set
`agents_api.enabled: false` before exposing the gateway on an untrusted network, which
also hides this feature. The same section tunes the analysis model and the size caps:

```yaml
agent_generation:
  enabled: true
  model_name: null # null = primary chat model
  max_sources: 10
  max_messages_per_source: 40
  max_chars_per_message: 1500
  max_chars_per_source: 8000
  max_runs_per_task: 5
  max_goal_chars: 2000 # cap on the "what should this agent do?" / refine text
```

### Coding Agent: Gates, Learned Skills and Git

Edit gates and verify-before-finish are on by default; the skill learning loop
is behind `skill_evolution.enabled`; the bundled coding skills (including
`git-pr-workflow` and `repo-change-cycle`) are in `skills/public/`. What each
does, its config keys and what it costs: the
[Coding Agent guide](docs/guide/coding-agent.md).

### Sandbox & File System

Upstream's reference for sandbox paths, uploads and outputs is the
[Sandbox & File System](docs/guide/sandbox.md#sandbox--file-system) guide. This
fork adds the following.

#### Containerized sandbox as a one-command capability

This fork makes the AIO container sandbox a zero-friction, self-managed capability. Instead of DeerFlow spawning a container per conversation, you can run **one** long-lived sandbox container and point DeerFlow at it:

```fish
# 1. Switch config.yaml to the containerized sandbox (rewrites only the
#    sandbox: section, backs up to config.yaml.bak, keeps your environment:)
make sandbox-enable

# 2. Start the container (image is tag-pinned in docker/docker-compose.sandbox.yml,
#    published loopback-only on 127.0.0.1:8091)
make sandbox-up

# 3. Run DeerFlow — `make dev` auto-starts the sandbox if it isn't already
#    reachable, health-polls it, and fails fast with actionable guidance
make dev
```

The resulting `sandbox:` block is:

```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  base_url: http://localhost:8091
  request_timeout: 120.0
  environment:
    GITHUB_TOKEN: $GITHUB_TOKEN
```

`$`-values resolve from the host env / `.env` at load. In this **external** mode DeerFlow never creates or destroys the container — its lifecycle is yours (`make sandbox-up` / `make sandbox-down` / `make sandbox-logs`). `make check` reports whether Docker, the `docker` group, compose, and port 8091 are ready, printing fish-compatible remediation for Arch and Debian. `make sandbox-disable` reverts to the default `LocalSandboxProvider` (host `bash` disabled, guardrail intact). Users who don't run any of this see **zero** behavior change and need no Docker.

> Note: `mounts:` is honored only by `LocalSandboxProvider` and the auto-spawn AIO backend. In external mode, declare volumes in `docker/docker-compose.sandbox.yml` instead — DeerFlow logs a warning if it sees an ignored `mounts:` list.

#### Host-run Ollama from inside the sandbox

Sandbox containers (both the external one above and the per-conversation auto-spawn ones) can reach a host-run Ollama out of the box: they map `host.docker.internal` to the host gateway (Linux Docker daemons don't provide the alias automatically) and set `OLLAMA_HOST=http://host.docker.internal:11434` in the container environment, so agent-run scripts and Ollama clients target your local daemon instead of the container's own loopback. Override the endpoint with `DEER_FLOW_SANDBOX_OLLAMA_HOST` (external mode) or an `OLLAMA_HOST` entry in `sandbox.environment` (auto-spawn mode).

One host-side requirement remains: Ollama's default binding is loopback-only (`127.0.0.1`), which refuses connections arriving from containers. Make it listen on all interfaces (`sudo systemctl edit ollama` → `[Service]` `Environment="OLLAMA_HOST=0.0.0.0"`, or `OLLAMA_HOST=0.0.0.0 ollama serve`). You don't need to remember this — `make dev`'s sandbox preflight detects the loopback-only case and prints that exact fix (advisory only; DeerFlow's own model calls run on the host and are unaffected, and Docker Desktop is exempt because it proxies host loopback).

#### Private GitHub repositories

When `GITHUB_TOKEN` is set in the sandbox `environment:` (the bundled compose file forwards it from your host), DeerFlow installs a git credential helper inside the container so the agent can clone private repos with a **plain** URL:

```fish
git clone https://github.com/owner/repo.git    # works; token never touches .git/config
```

The token never appears in remote URLs, `.git/config`, tool output, logs (container-run env values are redacted), or history. Scope the token to the repos you need (Contents: read).

### Files in a Conversation

Everything a run writes lands in the conversation's sandbox folder,
`/mnt/user-data`: the agent's scratch work in `workspace/`, your attachments in
`uploads/`, and deliverables in `outputs/`. The artifacts panel lists only the
files the agent chose to present. The labelled **Files** button, right after the
token counter in the chat header, opens a **Files** tab on the whole folder: a
tree opened one directory at a time, with sizes and times, where any file
previews or downloads and open folders refresh while a run is working. **Show
files** in a chat's sidebar **⋯** menu opens the same tab.

The explorer is read-only and sees only the conversation's own folder; a link is
shown, never followed. **This folder is deleted with the conversation**, which
the tab and the delete confirmation both say; folders in a writable custom mount
are kept (see [Shared Folders and Their Edit Log](#shared-folders-and-their-edit-log)).
A shared external sandbox container (`make sandbox-up`) keeps the workspace where
the explorer cannot see it. Details:
[Conversation files](docs/guide/workspace.md#conversation-files).

### Shared Folders and Their Edit Log

A directory you map into the sandbox with a writable `sandbox.mounts` entry is
shared by every conversation and user, and outlives them all. For each
**top-level folder** in it, DeerFlow records which conversations created, edited
or inherited it, with an edit log, and a conversation's **Files** tab lists them
under **Shared folders**; another user's conversation is shown without its title.

**Deleting the last conversation that used such a folder offers to delete the
folder; it never deletes it for you.** Nothing is pre-ticked, and only a folder a
conversation was **seen creating** can be deleted, by its creator or an
administrator; a folder that already existed is always kept. Only the agent's
file writes and shell commands that name the folder's path are seen, so a folder
changed from outside DeerFlow can look unused. It needs the default SQL database
and works with the local sandbox and per-conversation containers. No new
configuration keys. Details:
[Shared folders in writable mounts](docs/guide/sandbox.md#shared-folders-in-writable-mounts).

### CAD Models in the File Preview

Select a `.glb` or `.stl` file in the artifact panel, the reader or the
**Files** view and it opens as a model: drag to rotate, scroll or pinch to zoom,
**Fit**, **Reset**, **Top**, **Front** and **Iso** views and an **Edges** toggle,
with `Bounding box X × Y × Z mm` under it along the CAD axes. A file named
`*.failed.glb` carries a banner pointing to the report beside it. **The model
never moves on its own**: it is drawn only when something changes, with no
animation running in between.

Each file is parsed in its own background worker, checked against fixed caps
before anything is allocated (1,000,000 triangles, 1,000,000 vertices, 20,000
primitives or nodes, 15 seconds), and a file past a cap, or past the host's
25 MiB preview limit, says why and offers the download. The original always
downloads unchanged, and nothing is fetched from outside the server. A GLB is
read as metres, glTF's unit, so one written with millimetre vertices and no scale
reads 1000 times too large.

Bundled and on by default, with this record in `config.yaml`; an existing install
gets it from the config upgrade on its next update. Its one key is `enabled`:

```yaml
plugins:
  - name: cad-preview
    package: deerflow-extension-cad-preview
    use: deerflow_extension_cad_preview:install
    enabled: true
    required: false
    config:
      enabled: true
```

Turn it off with `make extension-disable NAME=cad-preview` and a restart, and GLB
and STL files go back to the download fallback. Details:
[CAD model preview](docs/guide/file-previews.md#cad-model-preview-extension).

### CAD Design Page

**Designs** in the sidebar opens a page for working on one part with the
assistant: the conversation and the model picker on the left, and on the right
the design's versions with tabs for **Preview**, **Views**, **Checks**, **Code**
and **Files** (at phone width the conversation becomes one more tab). Describe
the part and the assistant follows the bundled `cad-modeling` skill: it writes
parametric multi-body OpenSCAD, renders each body, checks clashes and gaps in
every pose and through every swing, looks at sections and a shaded render,
checks the print with a slicer and the loads by hand, fixes what failed and
renders again. The conversation follows the run live.

**The model's code runs only in the design's own sandbox container, never in the
Gateway.** Every render writes the next version folder,
`/mnt/user-data/outputs/design/v<N>/`, and the page reads those folders through
the host's thread file routes: the newest is shown by default, each body in its
own colour with a show and hide switch, with the shaded render and sections, a
summary of every check, the read-only `model.scad` and download links. STEP and
3MF are exported when you ask for files. Writing while an older version is
selected tells the assistant which one you are looking at. **Every figure is a
check on the model, not on a print**: the export STEP is faceted (written from the
mesh) unless you ask for an editable one, which the assistant rebuilds in CadQuery and proves against the body, OpenSCAD 2021.01 renders curved booleans slowly, the container has 2 GiB
of memory by default (`DEER_FLOW_SANDBOX_MEMORY=4g` for big STEP exports), and
`text()` has only the DejaVu and Liberation fonts. Designs are per user and stay
out of the chat list; deleted ones go to a Trash in the page, and **Delete
forever** also deletes their conversation and every version. The design
instructions reach design runs only, so ordinary chats and subagents pay no
tokens for them.

It needs Docker, the per-thread container sandbox and the CAD image, a local
build on the pinned AIO sandbox image (over 13 GB) with OpenSCAD, PrusaSlicer,
CadQuery and the mesh libraries added:

```bash
make sandbox-cad-image                        # builds deerflow-sandbox-cad:local
make sandbox-enable MODE=container IMAGE=cad  # selects it in config.yaml
```

Then restart the Gateway. Until then the page shows those commands, and a design
run without a shell tells you the same and stops. The page itself is bundled and
on by default, with this record in `config.yaml`; an existing install got it
from config migration 78, and migration 79 drops its old `max_source_bytes` key:

```yaml
plugins:
  - name: cad-design
    package: deerflow-extension-cad-design
    use: deerflow_extension_cad_design:install
    enabled: true
    required: false
    config:
      enabled: true
      storage_path: cad-design/designs.sqlite  # relative = under DEER_FLOW_HOME (local and Docker alike)
```

Turn it off with `make extension-disable NAME=cad-design` and a restart. Details:
[CAD design page](docs/guide/cad-design.md) and the package's
[README](examples/deerflow-extension-cad-design/README.md).

### System Prompt

Every run starts from a system prompt — roughly 10,000 characters of instructions assembled before your first message ever reaches the model. It sets the agent's role, how it thinks, when it delegates to sub-agents, which skills it can reach for, and what it is allowed to say about itself. In most agent frameworks that text is a constant buried in the source. Here it is a page in the app.

**Settings → System prompt** has two tabs:

- **Edit** — the template in force, in a monospace editor. The twelve placeholders the runtime fills in (`{skills_section}`, `{subagent_section}`, `{soul}`, `{memory_tool_section}`, …) are listed as one-click insert buttons, with a character budget and a *Discard edits* escape hatch.
- **Preview** — the same prompt with every placeholder substituted: the exact text the lead agent receives, not an approximation. A switch toggles the Ultra-mode sub-agent block, which is also where the available sub-agent roster is listed — so this is the one place in the UI that shows which agents `task` can delegate to, including any you defined under `subagents.custom_agents`.

Edits are saved to `SYSTEM_PROMPT.md` beside your other DeerFlow state and re-read on every agent build, so **a change applies from your next run with no restart**. `make backup` carries it along with the rest of your instance. **Reset to default** restores the built-in prompt at any time.

Templates are validated before they are saved, not after: an unknown placeholder is refused with the offending name rather than accepted and then silently ignored. Because saving proves the template renders, anything the editor accepts is guaranteed to work on the next run. Leaving a placeholder *out* is not an error — it is how you remove that section from the prompt, and the page tells you which blocks a given template omits.

Two guardrails worth knowing:

- **A saved prompt can change a run, but never break one.** If the file is hand-edited on disk, restored from an older backup, or written against a placeholder a newer version no longer provides, the agent falls back to the built-in prompt with a warning instead of failing to start.
- **The built-in prompt tells the agent not to disclose its own instructions.** You may remove that section — some people want an agent that can explain itself — and the editor warns you when an edit does, because the effect is invisible until someone asks the agent to recite its prompt.

The routes behind the page (`GET`/`PUT`/`DELETE /api/system-prompt` and `GET /api/system-prompt/preview`) require an admin account, the same bar as skill and MCP management. In the default passwordless local setup, that is you.

### Internet Access Switch

Every conversation has its own internet switch: the globe button in the composer,
between the microphone and the prompt-polish button. Click it and the globe
closes; from the next message on, that conversation runs with **no
internet-reaching tool in it at all** — no `web_search`, no `web_fetch`, no
browser control, no MCP server, no external ACP agent. The agent answers from the
conversation, the files in the thread, and what the model already knows. Click it
again and the tools come back on the next message. It needs no configuration and
no restart.

**The switch belongs to the conversation, not to the app.** Two chats open side
by side can be on opposite settings — one working offline through a private
document while the other researches — for the same reason each chat has its own
model. The choice is remembered per conversation and survives a reload, and a
chat that predates the feature (or that you never touched) simply stays online:
this is an opt-out, so nothing changes until you click.

**Subagents inherit it.** A delegated `task` builds its toolset from the
conversation that dispatched it, so an offline chat cannot get its browsing done
by asking a subagent to do it. This is the property most worth knowing, because
without it the feature would look like it works while being one delegation away
from meaningless.

**What it does not do**, stated plainly, because a switch you cannot trust is
worse than no switch:

- **It governs tools, not the sandbox's network.** The `bash` tool stays — it is
  how the agent runs your code, and whether the shell can reach the internet is a
  property of the container your operator runs, not of this button. The offline
  run is explicitly told not to use the shell as a network workaround, but that
  is an instruction, not a wall. If you need a hard boundary, run the sandbox
  container on an internal Docker network.
- **It cannot unlearn.** A model that memorized a fact will still recite it; what
  changes is that it can no longer *look anything up*, and it is told to say so
  rather than to present recalled facts as freshly verified.
- **It does not stop the chat model call itself.** The conversation still goes to
  whichever model you selected — a cloud model is still a network request. Pair
  the switch with a local Ollama model for a conversation that reaches nothing.

Local tools are deliberately left alone while the switch is off: reading and
writing files, the shell, local media generation, and a
self-hosted knowledge base all keep working, so "offline" means *offline*, not
*idle*. The classification is fail-closed — a tool group DeerFlow does not
recognize as local is treated as internet-reaching and dropped — so a provider
someone adds later is excluded until it is explicitly known to be local.

Non-web callers (IM channels, the TUI, scheduled tasks, the embedded client) have
no composer and send no switch, so they are unaffected and keep whatever
`config.yaml` configured.

### Concurrent Chats

Chats run independently of each other. Ask one conversation for something slow —
a long research pass, a sandbox build — then leave it and prompt a different
conversation while the first is still working. Both answers arrive, and the one
you walked away from is still there, still streaming, when you come back.

**Leaving a running chat now keeps it, rather than ending it.** Two things used
to get in the way. A run is cancelled when its browser stream disconnects
(`on_disconnect` defaults to `cancel` on the Gateway's run API), which is exactly
what leaving a chat does — so the answer you walked away to wait for was killed
on the way out. And even a surviving run went dark, because leaving a chat
unmounted it. Now every run is submitted as "keep going if my stream drops", and
a chat you leave **while it is still answering** stays mounted in the background
until that answer lands. The desktop notification fires for a chat that is
merely off-screen too, not just when the whole window is hidden. Nothing to
configure.

This also means **closing the browser no longer cancels a run** — it finishes on
the server, which is what the "notify me when it's done" push notification
assumed all along, and why a phone that locks its screen mid-run still gets an
answer. The **Stop** button is unaffected: it cancels the run outright, and a
runaway run is still bounded by your spend cap.

Two deliberate limits: a brand-new chat whose thread the backend has not created
yet is not kept alive (a background chat is addressed by thread id, which it does
not have yet), and there is a ceiling of eight background chats, past which the
newest one is not kept. In both cases the run itself still survives on the server
and you rejoin it when you open the chat again. A background chat is released as
soon as its run lands — it is kept alive for the answer, not indefinitely.

Within a **single** conversation, turns still take one at a time — two runs in one
chat would fight over the same conversation state. Concurrency is across chats.

**If your model is local (Ollama), there is one more step.** Everything above is
about DeerFlow; Ollama has its own queue. It answers `OLLAMA_NUM_PARALLEL`
requests **per model** at a time — **1** unless you raise it — and queues the
rest, so a second chat sits at "thinking" until the first one finishes even
though both runs are genuinely live. Raise it on the daemon, and tell DeerFlow
the same number:

```bash
sudo systemctl edit ollama    # add:  [Service]  Environment="OLLAMA_NUM_PARALLEL=2"
sudo systemctl restart ollama
```

```yaml
ollama:
  num_parallel: 2   # must match the daemon's OLLAMA_NUM_PARALLEL (default: 1)
```

The config value does not change the daemon — it tells the model sync what the
daemon is doing. That matters because **Ollama allocates a full KV cache per
slot**: two slots halve the context window each chat can afford, so the
`num_ctx` written for each model on the next launch shrinks to match (see the
VRAM-aware sizing above). Leave it unset and everything is sized exactly as
before. `make doctor` reports how many chats can generate at once under **Local
Models**, with the fix if the answer is one.

### Folders in the Sidebar

The conversation list in the sidebar is a tree. Press **New folder** in the
*Recent chats* header and drag conversations onto it, or use **Move to folder**
in a conversation's **⋯** menu; a folder's own **⋯** menu holds **New
subfolder**, **Move folder to**, **Rename** and **Delete**. Folders nest up to
five levels deep, and the count beside a folder covers everything below it.

**A conversation you file is inside the folder and no longer in the list outside
it**, so a collapsed folder genuinely puts those chats out of the way. **Deleting
a folder never deletes the conversations in it**: they return to the main list,
as does any chat whose folder disappears for another reason.

Folders are stored **per user on the server**, so they follow you to another
browser or device; only which folders are expanded is per browser. At most **50
folders**, and filing a chat never moves it in the recency order. Nothing to
configure. Details: [Chat folders](docs/guide/workspace.md#chat-folders).

### Selecting Several Chats at Once

Press **Select** beside **New folder** in the *Recent chats* header, or
**Select** in a chat's **⋯** menu. Every row gets a checkbox: click to tick,
Shift-click for everything in between, **Select all** for the chats shown, and
**Escape** or **Done** to stop. The toolbar then **moves** the ticked chats into
a folder (or **New folder from selection…**, which creates one and files them
into it), **archives** them with one Undo, **deletes** them, or opens
[clean-up mode](#cleaning-up-your-chats-with-a-model).

**Deleting is permanent**, as it is for one chat: the confirmation names the
chats and their count, and each chat's files go with it. A chat that fails — one
still answering cannot be deleted — stays ticked with its reason and a **Try
again** button; nothing is retried for you. Moving never reorders the list.
Nothing to configure. Details:
[Selecting several chats](docs/guide/workspace.md#selecting-several-chats).

### Cleaning Up Your Chats With a Model

**Clean up…** in the selection toolbar (or **Clean up all…** with nothing
ticked, for your 200 most recent chats) has a model you pick read each
conversation and propose a clearer title and a folder. You choose the model,
whether to rename, and how to file: **Don't file**, **Into my folders** (folders
you tick or name) or **Auto-generate folders** (it proposes folders, reuses
yours when a name matches, and creates at most the number you set).

**Nothing is changed until you have reviewed the plan and pressed Apply.** The
review screen lets you edit each title and folder, untick rows, and rename or
merge proposed folders. Applying creates the new folders in one write, moves and
renames the chats **without reordering the sidebar**, and lists what failed;
nothing is retried on its own, and applying the same plan twice writes nothing.

It costs **one model call per conversation**, plus at most one to group folders
in auto mode, each counted in the conversation's cost under **Chat clean-up** and
stopped by your spend cap. No new configuration keys. Details:
[Chat clean-up](docs/guide/workspace.md#chat-clean-up).

### A Conversation Remembers Its Model

Each chat has its own model, subagent model, mode and reasoning effort — selecting one in an open conversation never changes another. What is new is that the conversation **remembers** it: the selection is recorded on the chat itself, not only in the browser you happened to pick it in.

That matters in three ordinary situations, all of which used to look like the app forgetting:

- **Switching conversations.** Opening a chat now moves the picker to *that* chat's model instead of leaving whatever was selected last. Previously any conversation this browser had not touched had nothing recorded, so it fell back to the app default.
- **A different browser or device.** Your phone reads the same record your laptop wrote, so a chat that has been talking to a local model does not silently switch to a cloud one when you pick it up elsewhere. Same after clearing site data.
- **A brand-new chat.** A new chat is addressed by a placeholder id until you send the first message, at which point the server assigns a real one. The selection used to be stranded under the placeholder, so the chat forgot its model on the very turn it had just answered with it. It now carries across.

In Ultra mode the **subagent** model is remembered alongside the lead model, so a conversation that delegates to a cheap local model keeps doing so.

Nothing to configure, and changing a model never reorders your sidebar — the recency-ordered list treats a model change as what it is, not as activity in the conversation.

### Automatic Conversation Titles

A new conversation is called *New Conversation* until DeerFlow renames it, once,
at the end of the first turn, so the title describes the answer as well as the
question. **Settings → Conversation titles** decides whether that happens and
what it costs: **No model call** (your first message, shortened; free, and **the
shipped default**), a configured model (it reads at most 500 characters of the
first question and of the answer), or **Server default** (whatever `config.yaml`
names).

**The switch is saved to your account and covers every conversation you own**:
the Gateway applies it to each run, so a chat started from another device, an IM
channel, a scheduled task or a workflow follows it too, and off anywhere is off
everywhere. Before this, the setting lived only in the browser and every other
way of starting a chat ignored it. The terminal UI and the embedded Python client
keep using `config.yaml`, whose `title:` block is the operator's master switch;
turning it off there greys out the switch with an explanation:

```yaml
title:
  enabled: true # false disables automatic renaming for everyone
  max_words: 6
  max_chars: 60
  model_name: null # null = no model call (shortened first message)
```

No new configuration keys. Details:
[Conversation titles](docs/guide/workspace.md#conversation-titles).

### Renaming a Conversation on Demand

The automatic rename happens once, so a chat that opened with "quick question
about the build" and turned into a three-hour refactor keeps the quick question
as its title. **Auto rename** in the chat header renames it from what is in it
now: pick a model, press **Run**. It reads the first two exchanges as you saw
them (an Ultra or Democracy panel's deliberation is left out), spends one call
counted in the header's cost under **Chat rename**, and is refused while a run is
in flight. The model you pick is remembered in your account and shared with
**Settings → Conversation titles**. With automatic renaming switched off the
button still renames this one conversation; with `title.enabled: false` in
`config.yaml` it is not shown. No new configuration keys. Details:
[Conversation titles](docs/guide/workspace.md#conversation-titles).

## Recommended Models

DeerFlow is model-agnostic — it works with any LLM that implements the OpenAI-compatible API. That said, it performs best with models that support:

- **Long context windows** (100k+ tokens) for deep research and multi-step tasks
- **Reasoning capabilities** for adaptive planning and complex decomposition
- **Multimodal inputs** for image understanding and video comprehension
- **Strong tool-use** for reliable function calling and structured outputs

## Backup and Restore

A personal instance accumulates months of memory, conversations, pinned tabs and
settings on one machine. `make backup` snapshots all of it as a single
timestamped archive, and `make restore` puts it back.

```bash
make backup                                   # → backups/deerflow-backup-YYYYmmdd-HHMMSS.tar.gz
make backup INCLUDE_SECRETS=1                 # also .env and integration tokens — see below
make restore ARCHIVE=backups/deerflow-….tar.gz
python3 scripts/backup.py inspect <archive>   # what's in it, without extracting
```

The archive carries `config.yaml`, `extensions_config.json`, your DeerFlow home
directory (memory, threads, uploads, folders, runtime settings, the SQLite
database) and `skills/custom`. Public skills and rebuildable caches are left out.
On `database.backend: postgres` a `pg_dump` is written into the archive instead,
and a failed dump aborts the backup rather than handing you a snapshot with no
database in it.

> **Credentials are excluded by default.** `.env` and the per-user integration
> credentials under `users/*/integrations/` are **not** in the archive unless you
> pass `INCLUDE_SECRETS=1`. Those files are `0600`/`0700` on disk for a reason,
> and a backup that quietly copies API keys and OAuth tokens into a tarball in
> your downloads folder is worse than no backup. When you do opt in, the archive
> is created owner-only (`0600`) — treat it as a credential file: don't email it,
> don't drop it in a shared folder, and prefer an encrypted destination.
> Restoring an archive that carries no credentials leaves the ones already on the
> machine untouched.

**Restore refuses while DeerFlow is running.** Writing over a database the
Gateway holds open turns a recovery into a second outage, so `make restore`
checks the Gateway (8001) and nginx (2026) ports and stops with instructions to
`make stop` first. Pass `FORCE=1` only if you are certain nothing is live.

File permissions survive the round trip, so credential directories come back
`0700` rather than world-readable. Ownership is not restored (only root could),
which is deliberate — restoring as your own user is also the fix if a Docker run
has left root-owned files behind.

## Large Documents and Scanned PDFs

A long PDF is the case where a local model stops being a smaller version of a
cloud model and starts being a different thing. A 300-page filing is well past
what a 32K-token window can hold, and the usual answer — let the agent navigate
the document itself with `grep` and `read_file` — is a multi-step tool loop,
which is the first capability a small quantized model loses as its input grows.
So the documents that most need help are the ones where the navigation breaks
down first.

The **`analyze_document`** tool does the navigating instead. Point it at an
upload and ask a question:

> analyze_document(path="/mnt/user-data/uploads/annual-report.pdf", question="What did they say about supply chain risk?")

The document is split into parts, every part is read on its own against your
question, and the notes are combined in a separate pass — so no model call ever
holds more than one part. **The part size follows whichever model is serving the
run**: a 200K-token cloud model reads a chapter at a time, a 32K local model
reads a few pages, from the same code path and with nothing to configure per
model. When the notes themselves grow past the window they are merged in rounds
rather than overflowing it.

**A scanned PDF is no longer summarised into fiction.** `pymupdf4llm` extracts a
PDF's *text layer*; a scan has none, so conversion "succeeds" and produces a file
with nothing in it — which an agent will summarise with total confidence. Empty
extraction is now detected and named, both in the upload list ("this document is
probably image-based (scanned) and needs OCR") and by the tool, which renders
each page to an image and has a vision model transcribe it. Transcription and
summarisation stay separate steps: the vision pass is told to transcribe and
nothing else, because a model asked to summarise while reading is choosing what
to drop before anyone has seen the document. The transcript is cached next to the
upload as `<name>.ocr.md`, so the expensive pass happens once.

The same window-awareness runs underneath the whole agent loop. The truncation
caps on `read_file`, `bash` and `ls`, and the `tool_output` externalization
thresholds, were fixed character counts sized for a 200K cloud model — a single
50,000-character `read_file` result is about 40% of a 32K window, and larger than
an 8K window outright. They are now lowered to fit the serving model. A
configured limit is only ever a **ceiling**: a large window keeps every default
it has today, an unknown window changes nothing at all, and an explicit `0`
("no limit") is never turned back on.

**You are told what a document will cost before you open it.** The size shown
beside an upload is the file on disk, and for a PDF that is the *compressed*
document — 212 KB of PDF here extracts to 1.1 MB of Markdown, around 280,000
tokens. An agent shown "212 KB" has every reason to read it straight through,
and the window is gone before it notices. The upload list now states the
extracted size in characters, pages and approximate tokens, and past
`documents.large_document_chars` (120,000 by default) it says plainly that the
document does not fit and points at `analyze_document`.

**Limits worth knowing.** Answers are capped at `answer_max_chars` before they
re-enter the conversation, and the full per-part notes are always written to
`/mnt/user-data/outputs/document-analysis/` so nothing is lost. A very long
document stops at `max_chunks` parts — and when it does, the answer says which
**pages** it covered and gives you a `start_part` to call again with, because
"nothing in this document says that" and "nothing in the first 40% of it says
that" are different claims. Following that to the end is what makes the first
one true. OCR needs a model with `supports_vision: true`; without one it says so
instead of returning an empty answer.

### Books That Are Not PDFs

A book often arrives as HTML, EPUB, plain text or a zip of those — Project
Gutenberg offers all four. Upload conversion covers PDF and Office files only,
and it is off by default (`uploads.auto_convert_documents`), so a 3.3 MB HTML
cookbook used to reach the agent as a file name and a byte count: no outline, no
size warning, nothing pointing at `analyze_document`. The agent read it straight
through until the window was gone.

Every text-like, HTML, EPUB or zip upload now **states its size in the prompt**,
estimated from the file size or the archive's file listing — **nothing is parsed
or unpacked on the host to produce it** — and past
`documents.large_document_chars` it is routed to `analyze_document` exactly like
a large PDF. A zip also names the documents inside it and how many other files it
skips. `analyze_document` reads HTML and EPUB as Markdown rather than markup —
that cookbook is 53 parts of Markdown against a 32K local model, where its raw
HTML was 79, past the 60-part cap — and reads the text and HTML documents inside
a zip in order, each under its own `## File:` heading.

**Limits.** An archive is checked from its listing before anything inside it is
opened: more than 1,000 files, more than 64 MB unpacked, an encrypted member, a
path that leaves the archive, or another archive inside it, and it is refused
with the reason, which the agent passes on with a request for the document
itself. Images, fonts and PDFs inside a zip are skipped and counted, not read.
HTML and EPUB are converted in memory when `analyze_document` runs, so nothing is
written beside your upload. Nothing to configure.

### Requests That Would Overflow the Window

Ollama does not reject a prompt longer than the model's `num_ctx`: it cuts it to
fit and keeps the most recent part, so the system prompt, the tool rules and your
question are the first things lost — and the model goes on to answer whatever is
left. The per-result caps above leave the *sum* unbounded, and the default
compaction trigger (32,000 tokens) is the whole window of a synced Ollama model.

**Before every model call the whole request is now measured** — system prompt,
tool schemas and conversation — against the window of the model serving it, for
the lead agent and subagents alike. If it does not fit, **the oldest tool results
are dropped from that request**, each replaced by a note telling the model to
work from what it has or use `analyze_document`. Your messages, the instructions
and the results the model is about to read are never touched, and the stored
conversation is unchanged. **If it still does not fit, it is not sent**: the chat
ends with a message naming the model, the room it really has (its window, less
the part kept for the reply, less a 10% margin because the size is estimated) and
how much of the request is the system prompt and tool definitions. When those are
most of it, a new chat would be just as large, so the message says to give the
model a larger `num_ctx`, switch off tools or MCP servers, or pick a model with a
larger window; otherwise it suggests `/compact`.

**On a small window — a local GPU's, up to 64K tokens of prompt — the request is
built to fit from the first message.** Tool definitions go out in short form (the
same tools and parameters, shorter descriptions), skills are listed by name and
read on demand, and MCP tools wait behind `tool_search` until they are needed,
whatever `skills.deferred_discovery` and `tool_search.enabled` say. On a synced
32K Ollama model a new chat's instructions and tools take about 7.4K tokens in
Flash and 11.8K in Double Plus Ultracode, leaving 10–15K for the conversation;
before, Double Plus Ultracode left 74. Compaction also fires earlier: below what
the guard leaves after those fixed tokens — 10,118 tokens on a synced 32K model —
and at half the prompt space on larger ones, with the configured
`summarization.trigger` token count as the ceiling.

**Limits.** The size is estimated, not tokenized: about four characters per token
for English and about one token per character for Chinese or Japanese, with a 10%
margin for JSON-heavy tool schemas. A model whose window is unknown — no
`num_ctx`, no `context_window` in `config.yaml` — behaves exactly as before.
Nothing to configure.

## Measuring Mission Drift on a Large Document

A long document fails in a way that looks like success. The run completes and
the answer is fluent and on-topic — but somewhere in the middle the document
filled the window, the original instruction aged out or was compacted away, and
the model settled into the task its remaining context suggested. Almost always
that task is "summarise this document", in place of the specific question you
asked. Nothing errors, so nothing catches it.

`make drift-eval` measures it. It generates a large PDF with facts planted at
known pages, gives a **primary** model one narrow question about it, then hands
the answer to a **secondary** model that judges whether it still addresses the
question that was asked:

```bash
make drift-eval                                    # 300 pages, offline, the document path
make drift-eval PRIMARY=qwen2.5:7b JUDGE=claude-sonnet-5
make drift-eval MODE=agent                         # the whole agent loop (needs `make dev`)
make drift-eval WINDOW=8192                        # reproduce a small-model failure on any model
```

The planted facts are the part that matters. A judge model asked "did this
drift?" agrees with a confident, fluent answer more often than it should, so a
judged verdict on its own is one model's opinion of another's. Because the facts
sit at known pages, the harness checks the answer mechanically as well — and
when the judge passes a run that missed its planted fact, it says so and blames
the **judge**. Exit status is non-zero on drift, so it can gate a change rather
than only inform one.

The protocol, the flags and the drift categories are in
[`backend/scripts/benchmark/drift_eval/README.md`](backend/scripts/benchmark/drift_eval/README.md).

Both halves are on by default, and OCR only ever runs on a document whose text
layer is actually missing:

```yaml
documents:
  enabled: true                   # exposes the `analyze_document` tool
  model_name: null                # null = the default chat model
  max_chunks: 60                  # ceiling on parts read per call
  max_chunk_chars: 60000          # ceiling on the derived part size
  concurrency: 2
  answer_max_chars: 8000
  ocr:
    enabled: true
    model_name: null              # null = the first model with supports_vision: true
    dpi: 150
    max_pages: 100
    concurrency: 2
```

PDF uploads must be converted for any of this to see them, which is
`uploads.auto_convert_documents: true` (see the PDF/Office note above) — the
tool converts on demand too, but the upload list only shows an outline for files
that were converted at upload time.

## Voice Input

The microphone button in the composer dictates into the message box. What
changed in this fork is where the audio goes.

The browser `SpeechRecognition` API that button used to wrap does **not**
recognize speech locally by default: Chrome streams the audio to Google, Safari
to Apple. That traffic leaves the browser directly, so it never passes through
the Gateway — which means self-hosting, authentication and Tailscale did nothing
for it, and the UI did not say so. Voice input now runs in three tiers, tried in
order:

1. **On-device** — Chrome 139+ recognizes speech locally (`processLocally`),
   downloading the language pack if that is all that is missing. No audio leaves
   the device and no server is involved. Nothing to configure.
2. **Your own server** — the recording is posted to the Gateway, which forwards
   it to a transcription service on your machine. This is the tier that makes
   dictation work on iOS Safari and other browsers with no on-device support.
3. **The vendor cloud** — the old behavior, and **off by default**.

**The surprising part: with no local service configured and no cloud opt-in,
voice input reports itself unavailable rather than falling back to Google.**
That is deliberate — a privacy fork whose microphone quietly uses a cloud
recognizer is worse than one that offers no microphone. When the cloud tier does
run, the composer says so every time.

**Limits that bite.** The microphone needs a **secure context**, which over
Tailscale means the `https://<magicdns>.ts.net` address (`tailscale serve`), not
the plain-HTTP tailnet IP — the same constraint that already gates Web Push, and
the composer says which one you are on. The server tier has **no interim
results**: unlike live recognition, the transcript arrives once, after you stop
recording, and the button shows a spinner while it is on its way. Recordings
above `voice.stt.max_audio_bytes` (25 MiB by default) are refused before any
byte reaches the transcription service.

To enable the server tier, point it at any service speaking the OpenAI
`/v1/audio/transcriptions` shape — faster-whisper-server, speaches,
whisper.cpp's `server`, LocalAI:

```yaml
voice:
  prefer_on_device: true # try the browser's local recognizer first
  allow_cloud_fallback: false # default; true permits Google/Apple as a last resort
  stt:
    enabled: false # default; set true once base_url points at a service
    base_url: http://localhost:8000 # DEER_FLOW_STT_BASE_URL overrides
    model: Systran/faster-whisper-small
    language: null # null auto-detects
    max_audio_bytes: 26214400
```

`voice.stt.enabled` and `voice.allow_cloud_fallback` are both **off by default**;
only the on-device tier works with no configuration at all. If you point
`base_url` at a host that is not this machine or its private network (Tailscale's
`100.64.0.0/10` counts as private), the Gateway logs a warning at startup and the
composer labels the tier — the endpoint is not refused, but you are told your
audio is leaving the house.

## Updating Camoufox and SearXNG

DeerFlow installs two components for itself that do not otherwise self-update: the [Camoufox](https://camoufox.com/) browser behind `web_fetch`, and the bundled SearXNG search image. `camoufox fetch` only re-downloads when the installed browser differs from the one the package expects, and Docker only pulls `searxng:latest` when the image is missing — so a long-running stack keeps whatever it started with.

Both are refreshed automatically, throttled to once a day on launch or via a `systemd --user` timer (`make auto-update-install`; opt out with `DEER_FLOW_AUTO_UPDATE=0`). **Settings → Maintenance → Update now** is the on-demand path for when that throttle is in the way — page fetches started failing, or search stopped returning results, and waiting until tomorrow is not an option. It is the same work `make auto-update` does, without an SSH session on the host.

The refresh takes a few minutes, so the button starts it and the page polls: each component reports its own outcome when it finishes — up to date, skipped (not in use, or you point at your own SearXNG), no Docker available, failed, or timed out. A second run is refused while one is in flight, because two concurrent pulls fight over the same files. The action is **admin-only**: it runs commands on your host.

## More Documentation

- [Install.md](Install.md) - Setup instructions written for coding agents
- [Configuration Reference](backend/docs/CONFIGURATION.md) - Every `config.yaml` option
- [Backend Architecture](backend/README.md) - Backend architecture and API reference
- [Conversation Sharing](docs/guide/sharing.md) - Expiring read-only snapshots, artifact previews and workspace copies
- [Architecture Overview](docs/ARCHITECTURE.md) - How the services fit together
- [Contributing Guide](CONTRIBUTING.md) - Development environment, workflow and tests
- [The Change Cycle](change_cycle.md) - The procedure every change follows, at three levels: map the change to features, test them, PR, merge
- [Repo Map](docs/repo-map/index.md) - What the app does feature by feature, and which files, data and services each feature uses
- [Changelog](CHANGELOG.md) - Release notes

## ⚠️ Security Notice

DeerFlow can execute commands and read and write files. It is designed to run in a local trusted environment, and a Gateway admin account is equivalent to code execution on the host. Before you deploy it on a server or expose it to a network, read the full [Security Notice](docs/guide/security.md) and [SECURITY.md](SECURITY.md).

### Improper Deployment May Introduce Security Risks

DeerFlow has key high-privilege capabilities including **system command execution, resource operations, and business logic invocation**, and is designed by default to be **deployed in a local trusted environment (accessible only via the 127.0.0.1 loopback interface)**. If you deploy the agent in untrusted environments — such as LAN networks, public cloud servers, or other multi-endpoint accessible environments — without strict security measures, it may introduce security risks, including:

- **Unauthorized illegal invocation**: Agent functionality could be discovered by unauthorized third parties or malicious internet scanners, triggering bulk unauthorized requests that execute high-risk operations such as system commands and file read/write, potentially causing serious security consequences.
- **Compliance and legal risks**: If the agent is illegally invoked to conduct cyberattacks, data theft, or other illegal activities, it may result in legal liability and compliance risks.

### Deployment Defaults

The Docker stack publishes its entry port on `127.0.0.1` only, and local
`make dev` / `make start` bind nginx, the Gateway, and the frontend to loopback,
matching the local-trusted-environment model described above. To reach it from
another machine, set `BIND_HOST` in `.env` (e.g. `BIND_HOST=0.0.0.0`) — and only
after putting the security measures below in place. Local runs apply `BIND_HOST`
to nginx on port `2026` only; the Gateway and frontend stay on loopback behind
it.

> **Tailscale + localhost:** the port is published as `${BIND_HOST}:${PORT}:2026`,
> so `BIND_HOST` is a **single bind interface, not an allowlist**. Setting it to
> just your Tailscale IP (e.g. `BIND_HOST=100.x.y.z`) binds *only* that interface
> and drops loopback — the app then works over Tailscale but **not** at
> `http://localhost:2026` on the host itself. Both Docker paths now co-bind
> `127.0.0.1` for you in that case, but you no longer need `BIND_HOST` at all for
> tailnet access — see the next section. After editing `.env`, apply the change
> with `./scripts/deploy.sh start` (or `make up-start`) — a config-only change
> needs no image rebuild.

**Complete first-run setup before the host becomes reachable.** A fresh
instance has no accounts yet, so create the admin account through `/setup`
immediately after starting any deployment that is not loopback-only.

### Reach This From Your Phone Over Tailscale

If the host is on a [tailnet](https://tailscale.com/), both `make up` and
`make docker-start` detect it and make DeerFlow reachable from your other
tailnet devices automatically. **No `.env` edit is required, and it survives
`git pull` and reboots** — detection runs on every start.

What happens on start when `tailscale status` reports a running daemon:

- nginx is published on this host's `100.x` CGNAT address **in addition to**
  `127.0.0.1` (via `docker/docker-compose.tailscale.yaml`). That range is
  routable only inside your tailnet, so this does **not** expose the LAN or the
  internet — unlike `BIND_HOST=0.0.0.0`, which does.
- The tailnet origins are merged into `GATEWAY_CORS_ORIGINS`,
  `DEER_FLOW_TRUSTED_ORIGINS`, and `DEER_FLOW_DEV_ALLOWED_ORIGINS` so the API
  accepts requests from a page loaded at that address. Publishing the port
  without this loads the UI shell and then 403s every API call — half a fix
  looks exactly like a Tailscale problem.
- Your own entries in those variables are kept; the merge only ever adds, and
  re-running a launch script does not grow the list.

Two URLs work, and the start banner prints whichever ones are live:

| URL | When | Notes |
| --- | --- | --- |
| `http://<tailscale-ipv4>:2026` | Always, once detected | What existing bookmarks and phones already use. Plain HTTP — fine inside a tailnet, but **not** a secure origin, so Web Push stays unavailable. |
| `https://<magicdns>.ts.net` | After you configure Tailscale Serve | A real certificate, so it is a secure origin: PWA install and Web Push work. |

To enable the HTTPS URL, run Tailscale Serve on the **host** (it terminates TLS
and forwards to loopback, so it needs no published port of its own):

```bash
tailscale serve --bg --https=443 http://127.0.0.1:2026
```

Serve usually needs elevated rights — either run it with `sudo`, or make
yourself the operator once with `sudo tailscale set --operator=$USER`. Fish
users can paste both commands as-is; neither uses bash-only syntax.

DeerFlow never runs `tailscale serve` for you and never runs
`tailscale serve reset`: Serve configuration is global to the machine and may
carry rules for your other services, so a DeerFlow start or stop must not touch
it. If Serve is not configured, everything else still works over the `100.x`
URL.

> **Do not use `https://100.x.y.z`.** Tailscale issues its certificate for the
> MagicDNS *name*, not the IP, so an HTTPS URL on the bare address is a
> certificate error every time. Use `http://` with the IP, or `https://` with
> the MagicDNS name.

Opt out on a host that is on a tailnet but should not serve DeerFlow to it:

```bash
# .env
DEER_FLOW_TAILSCALE_PUBLISH=0
```

Without Tailscale running, none of this applies: nothing extra is published and
the default remains `127.0.0.1` only.

On a host that starts DeerFlow at boot, let the tailnet publish bind before
Tailscale has brought its address up — otherwise Docker can start nginx first,
fail that bind, and leave `http://localhost` down with it until the next
`make up`. `make up` / `make docker-start` print this while it is missing:

```bash
echo 'net.ipv4.ip_nonlocal_bind = 1' | sudo tee /etc/sysctl.d/99-deerflow-tailnet.conf
sudo sysctl --system
```

### Notifications on Your Phone (PWA + Web Push)

DeerFlow installs to a phone home screen and can push a notification when a
long-running task finishes — with the browser closed, which is the whole point
if you started the run and pocketed the phone.

1. Open DeerFlow over a **secure origin** (see the table below).
2. Add it to your home screen. On iOS this is mandatory, not optional: iOS only
   delivers Web Push to installed web apps.
3. Settings → Notification → **Enable background notifications**, then send the
   test push to confirm the whole chain works.

Enable delivery on the server first — push encryption ships as an optional
dependency, so most installs never carry it:

```bash
cd backend && uv sync --extra webpush
```

**Background notifications need a secure context.** Service workers are only
available on `https://` or `http://localhost`, which means a plain-HTTP LAN
address — the fork's own convenient default — cannot do this at all. The
settings page detects that and says so, with the fix, rather than leaving a
switch that does nothing:

| Where you open DeerFlow | Background notifications |
| --- | --- |
| `http://localhost:2026` on the machine itself | ✅ works |
| `https://<machine>.<tailnet>.ts.net` (Tailscale) | ✅ works — this is the phone case |
| `http://192.168.1.10:2026` (plain LAN) | ❌ browsers disable service workers entirely |

Tailscale issues a real certificate for your machine's name, which is the
simplest way to get HTTPS on a home network:

```bash
tailscale cert <machine>.<tailnet>.ts.net    # once
tailscale serve --bg https / http://127.0.0.1:2026
```

Then open `https://<machine>.<tailnet>.ts.net` from your phone and install it.

Notifications fire only for runs that took longer than 30 seconds — a ping for
a two-second question is noise, and noise is how notifications get turned off.

**Check the effective exposure, not the individual settings.** Who can reach
this instance — and as whom — is decided by `BIND_HOST` *together with*
`DEER_FLOW_AUTH_DISABLED`, `DEER_FLOW_ENV`, multi-user mode, and the sandbox
choice. `make doctor` computes the combination and reports one line per entry
surface, naming every contributing setting and its one-line fix when the
instance is reachable without a login wall. The same summary prints at the end
of `make up` and `make dev`, or on demand:

```bash
python3 scripts/exposure.py --surface docker    # the published Docker port
python3 scripts/exposure.py --surface local     # make dev / make start
```

Two surfaces are reported because they do not share a bind address: `make up`
publishes `${BIND_HOST:-127.0.0.1}:${PORT}`, while `make dev` runs nginx from
`docker/nginx/nginx.local.conf`, whose `listen 2026;` has **no address** — so
the local dev stack is reachable from the network regardless of `BIND_HOST`.
A Tailscale bind is reported as its own tier rather than lumped in with
`0.0.0.0`. The check changes no defaults and never fails; it only tells you
where you stand.

### Security Recommendations

**Note: We strongly recommend deploying DeerFlow in a local trusted network environment.** If you need cross-device or cross-network deployment, you must implement strict security measures, such as:

- **IP allowlist**: Use `iptables`, or deploy hardware firewalls / switches with Access Control Lists (ACL), to **configure IP allowlist rules** and deny access from all other IP addresses.
- **Authentication gateway**: Configure a reverse proxy (e.g., nginx) and **enable strong pre-authentication**, blocking any unauthenticated access.
- **Network isolation**: Where possible, place the agent and trusted devices in the **same dedicated VLAN**, isolated from other network devices.
- **Stay updated**: Continue to follow DeerFlow's security feature updates.

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, workflow, and guidelines.

### Script workflows (bundled extension)

The [script workflows extension](examples/deerflow-extension-workflows/README.md)
adds inspectable JavaScript orchestration through full AgentRuns, background launch,
bounded parallel execution, progress, retained results and cancellation. This fork
bundles it and enables it by default for [Plus Ultracode and Double Plus Ultracode](#plus-ultracode-and-double-plus-ultracode--the-plan-becomes-a-script);
it requires a POSIX Gateway and operator-authorized Agent references. Versioned definitions, retained step outputs, live-process pause/resume
and authenticated human checkpoints support staged inspection reports. Confirmation
binds the exact retained output or captured file version (SHA-256); preview and
downstream reads use the same immutable bytes. Each child retains host-generated
assembly evidence for its resolved instructions, model, tools and Skills.
Cancelling a recoverable workflow continues child cleanup even if the requesting browser disconnects.
After a Gateway restart, sign in and select **Recover workflow** to recover a compatible run using retained results and exact-version approvals. Uncertain child admissions require reconciliation; they are never automatically retried. Recovery requires unchanged runtime/configuration and durable Gateway storage. The optional PostgreSQL mode supports cross-Gateway controls and session-authorized takeover after lease expiry, with fenced child admission and shared limits; see the extension deployment contract. Expired cancellations can be taken over for cleanup even at workflow admission limits. Definitive pre-admission permission/configuration rejection releases child capacity; uncertain admissions retain their reservations. SQLite remains single-Gateway. The [deployed acceptance and delivery boundary](examples/deerflow-extension-workflows/README.md#deployed-acceptance-and-delivery-boundary) documents real two-Gateway fault tests, session-authorized takeover, and the still-open reconciliation API/UI. There is no hard monetary budget. Workflow deadlines and child-observation timeouts are
reported separately from uncertain admission. Accepted launches retain their request
identity across inspection refresh failures, with a separate inspection retry action. A runnable example, installation steps
and QuickJS source-build prerequisites for other Python/CPU combinations are included.

## License

This project is open source and available under the [MIT License](LICENSE).

## Acknowledgments

DeerFlow is built upon the incredible work of the open-source community. We are deeply grateful to all the projects and contributors whose efforts have made DeerFlow possible. Truly, we stand on the shoulders of giants.

We would like to extend our sincere appreciation to the following projects for their invaluable contributions:

- **[LangChain](https://github.com/langchain-ai/langchain)**: Their exceptional framework powers our LLM interactions and chains, enabling seamless integration and functionality.
- **[LangGraph](https://github.com/langchain-ai/langgraph)**: Their innovative approach to multi-agent orchestration has been instrumental in enabling DeerFlow's sophisticated workflows.

These projects exemplify the transformative power of open-source collaboration, and we are proud to build upon their foundations.

### Key Contributors

A heartfelt thank you goes out to the core authors of `DeerFlow`, whose vision, passion, and dedication have brought this project to life:

- **[Daniel Walnut](https://github.com/hetaoBackend/)**
- **[Henry Li](https://github.com/magiccube/)**

Your unwavering commitment and expertise have been the driving force behind DeerFlow's success. We are honored to have you at the helm of this journey.

## Star History

[![Star History Chart](https://star-history.dera.page/svg?repos=bytedance/deer-flow&type=Date)](https://star-history.dera.page/#bytedance/deer-flow&Date)
