> # AI too expensive? Doesn't matter because you can have AI at home!
>
> On top of [upstream](https://github.com/bytedance/deer-flow), it adds — out of the box:
>
> **Getting it running**
>
> - 🔓 **Passwordless on your own network** — `make dev` / `make start` come up with no login wall, so your phone and laptop reach it over the LAN or [Tailscale](https://tailscale.com/) immediately. Opt out with `DEER_FLOW_AUTH_DISABLED=0`; auth stays on in production regardless.
> - 🦙 **Auto-populated Ollama models** — `config.yaml` syncs from your `ollama pull` list on every launch, with capabilities detected and each model's context window sized to your GPU instead of Ollama's 2048-token default. The GPU is detected on its own (an NVIDIA or AMD card beside the daemon). When Ollama runs on another machine, enter its GPU memory in **Settings → Models**: updates and syncs never reset it, and it wins over `ollama.vram_gb`. Local models are **free** — you pay for electricity.
> - 🔑 **API-key model auto-config** — drop a cloud key in `.env` and the matching models uncomment themselves in `config.yaml` on the next launch. Anthropic, OpenAI, xAI, Gemini, DeepSeek, Moonshot, Qwen, Mistral, MiniMax, Z.ai direct, plus a routed set via OpenRouter — one flagship per lab, except Anthropic and OpenAI, whose top tier is really two models a factor of two or more apart in price, so both halves are routed (Fable 5.1 + Opus 5.5, GPT-6 Astra + GPT-6.1 Sol).
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
> - 🗂️ **A file explorer for each conversation** — a **Files** button in the chat header browses the folders the agent created in that chat: its `workspace`, your `uploads` and the `outputs`, as a tree you open folder by folder, with sizes and times. Any file opens in the preview panel or downloads, including the scratch files the agent never presented, and open folders refresh while a run is working. Read-only; nothing to configure.
> - 🧩 **Extensions whose tools produce files** — an installed extension's tool can write a file into the conversation that called it, and the file opens in the artifact panel and the Files view like one from a built-in tool. It works on the default sandbox with no shell, because the Gateway does the writing. **The tool only names a file:** it cannot choose a conversation or a folder, and an existing file is never replaced. Nothing to switch on; `plugin_outputs` in `config.yaml` caps a file at 8 MiB and one tool call at 32 MiB.
> - 🕯️ **Gaslight mode** — edit **either half of a turn**. Edit your own message and it replays from there; edit the assistant's answer and your text simply *becomes* what it said. Both versions are kept behind a `‹ 2/2 ›` switcher, and one conversation stays **one** sidebar entry however many times you edit it.
> - 🌐 **An internet switch on the composer** — a globe takes *this* conversation offline: search, fetching, browser control, MCP and external agents are left out of the run, and subagents inherit it. Per chat, not a global setting.
> - 📄 **PDF / Office uploads that just work** — `pymupdf4llm` is bundled, so PDF / DOCX / PPTX / XLSX uploads are reliably readable by the agent (`uploads.auto_convert_documents: true`).
> - 📚 **Big documents on small models** — `analyze_document` reads a document in parts sized for whichever model is serving, so a 300-page PDF never has to fit in a 32K local model. A **scanned** PDF is detected and transcribed by a vision model rather than summarised into fiction. An upload too large to read in one window now says so in the prompt — with its real extracted size, not the compressed file size — and every answer names the **pages** it came from, so a read that stopped early hands back a `start_part` to continue from instead of quietly answering about the first 40%.
> - 📖 **Books in any format, zipped or not** — an HTML, EPUB, plain-text or zipped book (a Project Gutenberg download, say) now states its size in the prompt and, when it is too big for one window, is routed to `analyze_document`, which reads HTML and EPUB as Markdown and reads the documents inside a zip. **Nothing is parsed or unpacked on the host to size an upload**, and a zip that would unpack past 64 MB, holds over 1,000 files, nests another archive or is encrypted is refused with the reason. Nothing to turn on.
> - 🧱 **No request bigger than the window** — before every model call the whole request (system prompt, tool schemas, conversation) is measured against the serving model's window. If it does not fit, the oldest tool results are dropped from that request — never your messages or the instructions — and if it still does not fit it is **not sent**: the chat says why, instead of Ollama silently cutting off the start of the prompt. On a local model the request is also **built to fit from the first message**: tools are described in short form, skills are listed by name and MCP tools wait behind a search, so a synced 32K Ollama model keeps about 15K tokens for the conversation in Flash mode (it had about 7K). Compaction fires before the window fills, and a refusal states the real limit and what is using it. Nothing to turn on; a model whose window is unknown is left alone.
> - 🎯 **A drift check for long documents** — `make drift-eval` gives a model a large PDF with facts planted at known pages, then has a *second* model judge whether the answer still addresses the question that was asked or quietly became "summarise this document". The planted facts grade the judge too, so a judge that waves through a wrong answer is reported as the judge failing. Runs offline against the document path, or end to end through the running agent with `MODE=agent`.
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
> - ✏️ **Conversation renaming you can switch off** — the shipped default spends **no** model call (the title is your first message, shortened); point it at a cheap model for a real summary, or turn it off entirely.
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
  - [Generating Agents From Your History](#generating-agents-from-your-history)
  - [Sandbox & File System](#sandbox--file-system)
    - [Containerized sandbox as a one-command capability](#containerized-sandbox-as-a-one-command-capability)
    - [Host-run Ollama from inside the sandbox](#host-run-ollama-from-inside-the-sandbox)
    - [Private GitHub repositories](#private-github-repositories)
  - [Files in a Conversation](#files-in-a-conversation)
  - [System Prompt](#system-prompt)
  - [Internet Access Switch](#internet-access-switch)
  - [Concurrent Chats](#concurrent-chats)
  - [Folders in the Sidebar](#folders-in-the-sidebar)
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

Open http://localhost:2026.

- All configuration options, providers and manual setup: [Configuration](#configuration) below; upstream's reference is the [Configuration](docs/guide/configuration.md) guide
- Docker details, upgrades and production deployment: [Running the Application](#running-the-application) below; sizing, startup modes and LangGraph Studio are in the [Running the Application](docs/guide/deployment.md) guide
- Running on a server or exposing it beyond localhost: read the [Security Notice](#️-security-notice) first

### Configuration

Application SQL JSON writes normalize non-finite floats (`NaN`, `Infinity`, `-Infinity`) to `null` on SQLite and PostgreSQL, including DB-backed agent definitions and skill-mutation records. Existing rows are not rewritten.

With `run_events.backend: db`, caller-supplied ISO 8601 event timestamps are normalized to UTC before storage, preserving their instant when SQLite drops timezone information. Timestamps without an offset are treated as UTC. Previously stored timestamps are not rewritten.

Run event streams include `run.terminal` for the owning worker's confirmed final
Run status, while `run.end` continues to describe each root graph completion.
Terminal publication is best effort; event persistence failure does not undo the
Run outcome or prevent stream completion. Recovery with built-in SQL Run and Event stores
sharing an engine uses one pooled connection for each guarded event write, so it
can publish with only one pool slot available. See [Run Event Stream](backend/docs/RUN_EVENT_STREAM.md#authoritative-run-outcome).

PostgreSQL async ORM connections and the offline command accept `postgres://`
and `postgresql://` URLs, including `?sslmode=disable` or `?sslmode=verify-full`.
SSL modes are preserved; conflicting `ssl`/`sslmode` settings are rejected.
Explicit `channel_binding` options are rejected because asyncpg cannot enforce
them. Synchronous psycopg and LangGraph DSNs retain their libpq options.

With a fencing-capable SQL RunStore and `DbRunEventStore`, host-authorized
producer writes validate the persisted Run incarnation, producer epoch and state
even with `run_events.producer_fencing: "off"`. Stale Journal flushes after
takeover or deletion may therefore be rejected in the default configuration.
On PostgreSQL, these writes hold the Thread Fence and RunRow lock through commit.
Checkpoint and branch history imports use a separate host grant bound to a
durable thread-operation reservation and the captured thread identity. Strict
mode permits these imports without treating synthetic turn IDs as admitted Runs;
deletion, reservation revocation or lease expiry invalidates their grant.
Messages preceding the first human input retain their existing synthetic turn 0.

On PostgreSQL, `run_events.producer_fencing: "strict"` additionally enables
database-level authorization checks against raw SQL and unaware legacy writers
after an offline cutover. The `"off"` setting keeps application-level producer
validation active. Before activation, the database INSERT trigger skips its
Thread/RunRow locks and retains a shared cutover lock until each INSERT
transaction ends. This does not remove the application locks above. Off-mode
event INSERTs require `READ COMMITTED` (also accepting PostgreSQL's `READ UNCOMMITTED`);
`REPEATABLE READ` and `SERIALIZABLE` are rejected to prevent stale policy snapshots
from bypassing activation. A write that loses a race with activation rolls back
with SQLSTATE `40001`; retry the entire transaction with strict producer authority.
Activation requires stopping every Gateway and using the offline cutover command;
all restarted Gateways must use the same cutover ID. This does not recover missing
terminal events. To activate:

1. Deploy this version everywhere with `run_events.producer_fencing: "off"`.
   Complete migrations 0049 and 0050 and recover previously active Runs, then
   drain admissions and completion hooks. A terminal Run status alone does not
   prove its producer has drained.
2. Stop every Gateway, Worker and other database client, including checkpointer
   pools and monitoring clients, and keep them stopped during activation.
3. From the repository root, using the installed backend environment, run:

   ```bash
   uv run --no-sync --project backend python backend/scripts/run_producer_fencing.py \
     --config config.yaml --cutover-id deployment-2026-10-27 --all-gateways-stopped
   ```

   The command refuses activation if other database sessions or pending/running
   Runs remain. Use a deployment ID that every Gateway will share.
4. Set `database.backend: postgres`, `run_events.backend: db`,
   `run_events.producer_fencing: strict` and
   `run_events.producer_cutover_id: deployment-2026-10-27` everywhere, then restart.
   Verify a new Run persists its initial event, Journal/Hook, delivery and terminal
   events and closes normally; unaware old writers must receive a database rejection.

Activation is durable: missing or mismatched cutover IDs and downgrades to `"off"`
or unsupported stores fail startup. This release requires controlled downtime;
it does not support a mixed-version rolling cutover. A crashed producer may stay
open until explicitly closed or revoked by authorized takeover/deletion; no
producer-expiry or terminal-reconciliation job is introduced.

Scheduled-task orphan recovery carries the captured Run incarnation and retention
revision when publishing delivery and terminal evidence, including in strict mode.
Unconfirmed publication is logged separately from the committed takeover; it does
not undo the recovered Run or queue a new publication attempt.

Operators can extend lead-agent, subagent, and DeerMem extraction prompts with
literal prepend/append configuration without editing source templates. See
[prompt overlays](backend/docs/CONFIGURATION.md#prompt-overlays).

Optional per-model [`request_admission`](backend/docs/CONFIGURATION.md#model-request-admission)
paces requests to help stay within provider request-per-minute limits.
It is disabled by default; see the linked guide to enable it.
Enabling it disables exposed SDK retries and the Claude and Codex adapters'
internal retry loops so middleware retries pass through request admission again.
Middleware retries also cover HTTP 529 overload responses.
A warning identifies `retry_max_attempts` values overridden by admission.

For Google's official Gemini OpenAI-compatible endpoint, use the
[Gemini reasoning profile](backend/docs/CONFIGURATION.md#gemini-via-googles-openai-compatible-endpoint).

For MindIE XML tool calls, see the
[argument parsing and newline compatibility guide](backend/docs/CONFIGURATION.md#mindie-xml-tool-arguments).
Tool-result recovery treats null and empty call IDs alike — including the
`"None"` and `"missing_tool_call_id"` spellings middleware producers use when a
provider call had no ID — preserving middleware guidance when a result can be
uniquely paired; ambiguous partial results remain rejected.
Both synchronous and asynchronous streams retain this compatibility: tool-enabled
streams simulate chunks from a non-streaming response, while no-tool streams stay native.
Newline compatibility preserves literal escapes inside backtick and tilde code
fences, including unclosed fences, in complete and streamed replies.

1. **Clone the DeerFlow repository**

   ```bash
   git clone https://github.com/bytedance/deer-flow.git
   cd deer-flow
   ```

2. **Run the setup wizard**

   From the project root directory (`deer-flow/`), run:

   ```bash
   make setup
   ```

   This launches an interactive wizard that guides you through choosing an LLM provider, optional web search, and execution/safety preferences such as sandbox mode, bash access, and file-write tools. It generates a minimal `config.yaml` and writes your keys to `.env`. Takes about 2 minutes.

   Pick **Anthropic** or **OpenRouter** and the wizard enables a whole set of latest models from that one key — Anthropic writes Fable 5.1 / Opus 5.5 / Opus 5 / Sonnet 5.5 / Sonnet 5 / Haiku 5.5, and OpenRouter writes Claude Fable 5.1 and Opus 5.5, GPT-6 Astra and GPT-6.1 Sol, plus the xAI / Google flagships and a spread of open alternatives (MiniMax, Mistral, DeepSeek, Kimi, GLM, Qwen). If you configure by hand instead (`make config`), the same ready-to-uncomment blocks are at the top of `config.example.yaml` under `models:` — uncomment the one matching your key.

   The wizard also lets you configure an optional web search provider, or skip it for now.

   **Tools out of the box**: the defaults are chosen so the agent has its full toolset from the first launch — web search (SearXNG, key-less), web fetch (Camoufox local browser, key-less), image search, file read/write tools, and bash. When Docker (or Apple Container) is installed, both `make setup` and `make config` default to the **container sandbox** with bash enabled, so git/clone and program runs work immediately; without a container runtime the local sandbox is used and host bash stays off (a security default — enable the container sandbox later with `make sandbox-enable MODE=container`). If an older `config.yaml` is missing default tools (for example the agent reports it has no web_search/web_fetch/bash), `make config-upgrade` backfills the missing entries without touching your existing ones, and `make doctor` names exactly which tools are absent.

   Brave web search preserves valid entries in mixed result lists. Malformed response containers or lists containing no usable entries return a structured format error; missing, null, or empty results keep the existing "No results found" response. Format errors also log the malformed container's path and type, or the absence of usable result objects, without including search queries, credentials, or payload values.

   Several providers, including You.com, GroundRoute, Webz, InfoQuest and Jsonify, initialize HTTPX clients in a worker thread so synchronous TLS trust loading does not block the agent event loop; requests and session cleanup remain asynchronous.

   GroundRoute web search and fetch contain malformed HTTP-success payloads the same way: a non-object payload, a `results` container that is not a list, or a non-empty list with no object entries returns the provider's format error, while non-object entries in an otherwise valid list are skipped in order. Missing, null, or empty results keep the existing "No results found" response.

   DuckDuckGo web search distinguishes execution failures from empty results: rate limits, timeouts, blocked requests, client-setup failures, SDK errors, and a missing `ddgs` dependency return a structured `DuckDuckGo search failed: ...` error instead of "No results found", while a genuinely empty result set keeps the existing "No results found" response. The structured error text lets the harness classify an outage as transient or a configuration problem instead of a query that matched nothing.
   
   Tavily web search and fetch contain malformed HTTP-success payloads the same way: a non-object payload, or a `results`/`failed_results` container that is not a list, returns the provider's format error, and non-object entries in an otherwise valid list are skipped in order. Missing, null, or empty results keep the existing response (`[]` for search, `Error: No results found` for fetch); missing or null search fields (`title`, `url`, `content`) normalize to empty text, and a non-string fetch `raw_content` is coerced to text before the truncation limit.

   Sofya web search and fetch contain malformed HTTP-success payloads the same way: a non-object payload, a `results` container that is not a list, or a non-empty list with no object entries returns the provider's format error, while non-object entries in an otherwise valid list are skipped in order. Missing, null, or empty results keep the existing "No results found" response.

   Serper web and image search preserve valid entries in mixed result lists. A malformed `organic`/`images` container, or a non-empty list holding no object entries, returns Serper's format error; missing, null, or empty containers keep the existing "No results found" / "No images found" response. Format errors log the container field name only, without queries, credentials, or payload values.

   Unbrowse web fetch preserves the extracted text but prefixes a warning when the target page's HTTP status is 400–599, even when the scraping service itself returns a successful response. Empty-page errors retain that status too. Both messages include up to 500 characters of the reported final URL after removing any username and password; final URLs that cannot be parsed as HTTP(S) URLs with a host are omitted.

   Tencent Cloud WSA web search contains malformed HTTP-success payloads the same way: a `Pages` container that is not a list, or a non-empty container holding no usable page, returns the provider's format error, while malformed page entries in an otherwise valid container are skipped so the valid rows survive. Missing, null, or empty `Pages` keep the existing "No results found" response.

   Serply web search contains malformed HTTP-success payloads the same way in every vertical: a `results`/`entries`/`articles` container that is not a list, or a non-empty list with no object entries, returns the provider's format error, while non-object entries in an otherwise valid list are skipped in order. Missing, null, or empty containers keep the existing "No results found" response.

   SearXNG web search contains malformed HTTP-success payloads the same way: a payload that is not an object, a body that is not JSON, a `results` container that is not a list, or a non-empty list holding no object entries returns the provider's format error, while non-object entries in an otherwise valid page are skipped in order, each skip logged with its entry position, so the valid rows survive and provider-side drift leaves a trace. Missing, null, or empty `results` keep the existing empty result (`[]`). This matters most for a self-hosted instance: one behind a reverse proxy or captive portal answers an HTML or plain-text error page with HTTP 200, and reading that as an empty search ends a research loop as "no hits".

   InfoQuest web and image search contain malformed HTTP-success payloads the same way: a `search_result` envelope that is not an object, or an `organic`/`top_stories.items`/`images_results` container that is not a list or that holds no usable entry, returns the provider's format error, while malformed entries in an otherwise valid payload are skipped so the usable rows survive. Missing, null, or empty containers keep the existing empty result. Format errors log the container or entry position only, without queries or payload values.

   InfoQuest web and image search screen result URLs through the shared public-URL policy and omit rejected rows. Responses without the required `search_result` envelope return a format error instead of exposing the raw provider payload.

   Jina, Browserless, and InfoQuest web fetches resolve relative links and image sources using the requested page URL (or a usable HTML base URL), so returned Markdown includes complete destinations. Link resolution preserves the surrounding HTML source, including malformed-page formatting.

   Direct Python calls to `web_fetch_tool` return `(content, artifact)` so Browserless can keep the target page's HTTP status out of page prose. Callers that previously expected a string should unpack the tuple; Agent tool calls continue to expose content and artifact through LangChain's tool result.

   Browserless fetch and capture accept positive finite request timeouts in seconds. Invalid values fall back to 30 seconds. See [Browserless configuration](backend/docs/CONFIGURATION.md#delegated-fetch-backend-isolation).

   Self-hosted Browserless, Crawl4AI, Firecrawl, and fastCRW fetch backends require outbound isolation from private, loopback, link-local, and cloud-metadata networks before setting `network_isolation_confirmed: true` on each tool. DeerFlow rejects private or unverifiable backends by default because those services handle redirects, DNS resolution, and subresources themselves. `allow_private_addresses` permits intentional internal target URLs and does not bypass the backend check. See [delegated fetch deployment](backend/docs/CONFIGURATION.md#delegated-fetch-backend-isolation); `make doctor` reports backend configurations that would be refused.

   Jina fetches support opt-in bounded retries via `max_retries` (default `0`) and `retry_budget_seconds` (default `30`) in the tool configuration. Valid `Retry-After` hints set a minimum wait for HTTP 429/503; 429 without a valid hint stays terminal. Hints that cannot fit the remaining budget stop retries. Local backoff remains randomized. Retries may increase upstream requests and cost; see [Jina fetch retries](backend/docs/CONFIGURATION.md#jina-fetch-retries).

   At DEBUG level, Jina emits one bounded crawl completion summary with attempts, elapsed/backoff seconds, outcome and stop reason. See [diagnostics](backend/docs/CONFIGURATION.md#jina-crawl-diagnostics) for configuration and correlation.

   Jina also accepts an opt-in `max_response_bytes` tool setting (positive integer; omitted/null disables it). It stops oversized decoded responses before extraction, with no partial success or retry. This leaves the 4096-character output cap unchanged and does not bound HTTPX decompressor allocations or wire bandwidth; see [response budget](backend/docs/CONFIGURATION.md#jina-response-byte-budget).

   Jina can also bound concurrent HTTP attempts and FIFO waiting with the opt-in `request_admission` tool extra. One immutable budget is shared across clients and agent threads in each process; replicas have independent budgets. See [Jina request admission](backend/docs/CONFIGURATION.md#jina-request-admission).

   Run `make doctor` at any time to verify your setup and get actionable fix hints.
   The setup wizard and health check support legacy terminal encodings, including
   Windows cp936, replacing unsupported characters so both commands can finish.
   If you are opening a GitHub issue about a local setup or runtime problem, run
   `make support-bundle`. The command prints reporter next steps, writes a
   `*-issue-summary.md` file to paste into the issue, a `*-issue-draft.md` file
   for AI-assisted issue filing, and an optional evidence zip under
   `.deer-flow/support-bundles/`. If an AI assistant files the issue, start from
   the draft and replace every REQUIRED placeholder instead of inventing missing
   facts. Attach the zip only if a maintainer asks for it, or if the summary
   alone is not enough. Maintainers and AI triage tools can start with
   `triage.json`; the bundle includes redacted diagnostics and file manifests
   only, and does not include `.env`, raw conversation messages, or user file
   contents. Subprocess diagnostics are captured as UTF-8, with Python helpers
   emitting UTF-8 even on non-UTF-8 hosts and escaping unencodable characters.
   Thread manifests follow the local launcher's runtime paths: checkout `.env`
   values override shell exports, and a project-root override alone still uses
   `backend/.deer-flow` first. Simple variable references such as
   `DEER_FLOW_HOME="$PWD/backend/.deer-flow"` use the checkout as `PWD`;
   single-quoted references remain literal. If the checkout `.env` cannot be read or decoded
   as UTF-8, thread diagnostics retain shell exports and default storage paths. For standalone Gateway launches using `backend/.env`
   or `DEER_FLOW_ENV_FILE`, export the effective `DEER_FLOW_HOME` when collecting
   the bundle and ensure the checkout `.env` does not override it.
   Doctor's internal tool probes also decode UTF-8 with replacement for invalid
   bytes so the remaining diagnostic output stays available.

   When a thread manifest is requested, a nonempty `DEER_FLOW_HOME` selects the
   runtime data directory instead of stale checkout data. External data paths
   appear as `{DEER_FLOW_HOME}` in the report; file contents remain excluded.
   Runtime path settings also come from the checkout `.env`, with shell exports
   taking precedence. Relative paths resolve from the checkout as in `make dev`.
   Without an explicit home, a configured `DEER_FLOW_PROJECT_ROOT` selects its
   `.deer-flow` directory; external paths use that variable name in the report.

   > **Advanced / manual configuration**: If you prefer to edit `config.yaml` directly, run `make config` instead to copy the full template. Optional dependency auto-detection accepts UTF-8 configuration files with or without a byte-order mark (BOM). It checks an existing `DEER_FLOW_CONFIG_PATH` first, then `DEER_FLOW_PROJECT_ROOT/config.yaml`, before the checkout's default locations. Local startup also accepts the project-root configuration when the checkout has no `config.yaml`. See `config.example.yaml` for the complete reference including CLI-backed providers (Codex CLI, Claude Code OAuth), OpenRouter, Responses API, subagent runtime caps such as `subagents.max_total_per_run`, and more.

   Optional per-model pricing must use one currency across all priced models.
   DeerFlow disables Console cost estimates when currencies are mixed rather
   than presenting an invalid aggregate.
   For older runs without a per-model usage breakdown, Console attributes the
   recorded total and input token counts to the run's model.

   Administrators can open **Settings → Models** to select a provider and enter
   only its **API Key** and **model ID**. Endpoints, authentication and adapters are
   backend presets for OpenAI, Anthropic, DeepSeek, Alibaba Cloud Bailian/Qwen,
   Volcengine/Doubao, Moonshot/Kimi, Zhipu/Z.AI, MiniMax and StepFun. Region and plan-specific
   entries are explicitly distinguished. Arbitrary model IDs are accepted; internal
   names are generated automatically and remain stable when a model ID changes.
   Newly saved models are enabled and immediately refresh existing chat and Agent
   model selectors, without editing YAML or restarting the Gateway.

   Use **Fetch and add models** to reuse a saved connection or enter a new one,
   search its catalog, and test selected models before adding them. Existing
   entries are retained on retries; individual failures remain available to retry.
   Chat pickers support name/ID search, provider filtering, favorites and the
   eight most recently selected models, scoped to your account in this browser.

   The OpenAI preset routes `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6.1-terra`,
   `gpt-6-sol` and `gpt-6-luna` through the Responses API for tool calling,
   with model-specific thinking and reasoning-effort defaults. Flash mode
   turns off reasoning for GPT-6.1 Terra, GPT-6 Sol and GPT-6 Luna.

   The Moonshot (China) preset recognizes `kimi-k3.1-pro` and
   `kimi-k3.1-pro-highspeed` with required thinking, image input and native
   `low` / `high` / `max` reasoning effort (default `max`). Thinking stays on
   even when a caller requests it off. Requests to the official endpoint omit
   the unsupported thinking switch and fixed sampling parameters. See the
   [model registration reference](backend/docs/CONFIGURATION.md#models-registered-through-the-web)
   for the image-input and parameter constraints.

   **Custom OpenAI-compatible** still supports existing/custom base URLs and
   unauthenticated endpoints. **Advanced settings** retains display name, token
   limits and vision overrides; unknown IDs do not receive invented capabilities.
   Leave the key blank on edit to retain it for the same connection. Switching
   provider or custom endpoint requires a new key, and preset models must be
   disabled before clearing their key. YAML models remain read-only.

   Connection testing uses the same model factory and protocol as chat, sends a
   bounded streaming tool-call request and never saves the draft. It may incur
   provider charges and does not verify every agent, vision or thinking workflow.
   Official DeepSeek custom endpoints retain their existing adapter; a proxy does
   not become DeepSeek merely because of its model ID. See the
   [Web model registration reference](backend/docs/CONFIGURATION.md#models-registered-through-the-web)
   for presets, compatibility, extension instructions and backup requirements.

   DeepSeek regression tests run offline with the normal backend suite. To verify
   the real provider explicitly, set `DEEPSEEK_TEST_API_KEY` in your environment
   and run from `backend/`:

   ```bash
   DEER_FLOW_RUN_LIVE_TESTS=1 uv run --no-sync pytest tests/test_managed_deepseek_live.py -q
   ```

   These opt-in tests send short requests to DeepSeek and may incur charges;
   they use temporary state, never save credentials to the deployment catalog,
   and are skipped in CI. `DEEPSEEK_TEST_MODEL` optionally selects a different
   DeepSeek model ID (default: `deepseek-flash`). The same tests can be run on
   unfixed and fixed revisions; success is always the expected result.

   YAML models remain read-only in this page and take precedence on name conflicts.
   Managed models are appended after YAML models; edits apply to new configuration
   snapshots, while active runs retain their existing snapshot. Disabling a model
   removes it from future selection/resolution, so update any custom-agent or scheduled
   task definitions that explicitly reference it before disabling it.
   Managed models are shared by the deployment, not personal API-key profiles, and
   remain subject to the existing model authorization policy.

   The encrypted catalog and a generated local encryption key are stored in
   `$DEER_FLOW_HOME/managed-models/` (default `.deer-flow/managed-models/`). Persist
   and back up the **whole directory**, restrict filesystem access, and share it
   across Gateway workers/replicas that should use the same catalog. The local key
   is protected by filesystem permissions; encryption does not protect against
   someone who can read both files. Losing the key requires restoring the backup.
   Reads and writes fail if the catalog cannot be decrypted, rather than replacing it.
   This storage is independent of the SQL backend and works with read-only YAML mounts.

   When several models are configured, open either model picker and use the
   star beside a model to favorite it. Favorites appear first in both the main
   chat and Side Chat pickers without changing either chat's selected or
   default model. They are stored for the signed-in user in the current browser,
   so they do not sync to another browser or device and do not require a startup
   setting. The compact favorites picker intentionally omits search and only
   adds favorite ordering to the two-line model list.

   <details>
   <summary>Manual model configuration examples</summary>

   ```yaml
   models:
     - name: gpt-4o
       display_name: GPT-4o
       use: langchain_openai:ChatOpenAI
       model: gpt-4o
       api_key: $OPENAI_API_KEY

     - name: openrouter-gemini-2.5-flash
       display_name: Gemini 2.5 Flash (OpenRouter)
       use: langchain_openai:ChatOpenAI
       model: google/gemini-2.5-flash-preview
       api_key: $OPENROUTER_API_KEY
       base_url: https://openrouter.ai/api/v1

     - name: opper-claude-sonnet-4-6
       display_name: Claude Sonnet 4.6 (Opper)
       use: langchain_openai:ChatOpenAI
       model: claude-sonnet-4-6
       api_key: $OPPER_API_KEY
       base_url: https://api.opper.ai/v3/compat

     - name: api-route-gpt-6.1-sol
       display_name: GPT 6.1 Sol (API Route)
       use: langchain_openai:ChatOpenAI
       model: gpt-6.1-sol
       api_key: $API_ROUTE_API_KEY
       base_url: https://global.api-route.com/v1

     - name: gpt-5-responses
       display_name: GPT-5 (Responses API)
       use: langchain_openai:ChatOpenAI
       model: gpt-5
       api_key: $OPENAI_API_KEY
       use_responses_api: true
       output_version: responses/v1

     - name: qwen3-32b-vllm
       display_name: Qwen3 32B (vLLM)
       use: deerflow.models.vllm_provider:VllmChatModel
       model: Qwen/Qwen3-32B
       api_key: $VLLM_API_KEY
       base_url: http://localhost:8000/v1
       supports_thinking: true
       when_thinking_enabled:
         extra_body:
           chat_template_kwargs:
             enable_thinking: true
   ```

   OpenRouter and similar OpenAI-compatible gateways should be configured with `langchain_openai:ChatOpenAI` plus `base_url`. If you prefer a provider-specific environment variable name, point `api_key` at that variable explicitly (for example `api_key: $OPENROUTER_API_KEY`).

   [API Route](https://www.api-route.com) is also available in the setup wizard. It saves your key as `API_ROUTE_API_KEY` and uses the Chat Completions endpoint above. Model availability depends on your key's group and permissions; check the authenticated `GET https://global.api-route.com/v1/models` catalog before replacing the model in `config.yaml`, and use its returned ID unchanged without an upstream provider prefix.

   The `write_file` tool's output-budget hint uses the active model's effective `max_tokens`. Missing or unusable limits, including YAML `.inf`, `-.inf`, `.nan`, and values too large for the character estimate, omit this hint without failing tool assembly; provider-specific model validation still applies.

   To route OpenAI models through `/v1/responses`, keep using `langchain_openai:ChatOpenAI` and set `use_responses_api: true` with `output_version: responses/v1`.

   The lead agent also recognizes Responses output-token caps (`status: incomplete` with `incomplete_details.reason: max_output_tokens`), including streaming responses. It suppresses tool execution, removes the suppressed calls from later model requests, and preserves text and reasoning. A capped tool-call response includes a visible notice. Text-only output caps preserve the response and end the turn without unfinished-todo retries; other incomplete reasons retain their existing handling.

   When thinking is disabled on a legacy profile, blank `extra_body`, `thinking`, and nested `extra_body.thinking` keys in a `when_thinking_enabled` template are treated as absent during dialect inference. When thinking is enabled, template values are forwarded as configured.

   Models whose provider contract differs from DeerFlow's generic thinking/effort assumptions can declare a per-model mapping-valued `reasoning:` block (thinking `unsupported`/`optional`/`required`, the accepted effort values with aliases and a default, the payload dialect, and the reasoning-history requirement). The setup wizard's Z.AI GLM-5.3-Flash profile uses it: thinking stays on for every foreground and background call, and the effort selector offers the model's own `low`/`high`/`max` levels. Ollama's existing boolean `reasoning: true` remains a native provider setting and is forwarded to ChatOllama. When migrating a profile to a custom effort `path`, remove any old `reasoning_effort` setting from the profile and thinking templates; configuration validation rejects the leftover key. The chat UI drops a remembered provider-specific effort when switching to a legacy model that does not advertise it. Profiles without the block keep their existing provider behavior. See `config.example.yaml` for the shape and the equivalent manual configuration.

   For vLLM 0.19.0, use `deerflow.models.vllm_provider:VllmChatModel`. For Qwen-style reasoning models, DeerFlow toggles reasoning with `extra_body.chat_template_kwargs.enable_thinking` and preserves vLLM's non-standard `reasoning` field across multi-turn tool-call conversations. Legacy `thinking` configs are normalized automatically for backward compatibility, without modifying model defaults or caller-owned `extra_body` dictionaries; a reused dictionary can change the legacy switch between requests. If the endpoint reports a cumulative usage snapshot on every streaming chunk, set `cumulative_stream_usage: true` so DeerFlow converts those snapshots into per-chunk deltas; the option is disabled by default and leaves usage unchanged when a stable completion id is unavailable. Reasoning models may also require the server to be started with `--reasoning-parser ...`. If your local vLLM deployment accepts any non-empty API key, you can still set `VLLM_API_KEY` to a placeholder value.

   When prompt caching is enabled for a model configured with
   `deerflow.models.claude_provider:ClaudeChatModel`, DeerFlow preserves thinking
   and redacted-thinking history without placing cache breakpoints directly on
   those blocks. Extended-thinking tool follow-ups can keep using prompt caching.

   CLI-backed provider examples:

   ```yaml
   models:
     - name: gpt-5.4
       display_name: GPT-5.4 (Codex CLI)
       use: deerflow.models.openai_codex_provider:CodexChatModel
       model: gpt-5.4
       supports_thinking: true
       supports_reasoning_effort: true

     - name: claude-sonnet-4.6
       display_name: Claude Sonnet 4.6 (Claude Code OAuth)
       use: deerflow.models.claude_provider:ClaudeChatModel
       model: claude-sonnet-4-6
       max_tokens: 4096
       supports_thinking: true
   ```

   `ClaudeChatModel` normalizes manual extended-thinking budgets when `auto_thinking_budget: true` (the default). An omitted or null budget gets 80% of `max_tokens`, with a minimum of 1024 tokens. Explicit budgets must be integers of at least 1024 and, for ordinary thinking, strictly below `max_tokens`; output limits of 1024 or less fail locally. For supported manual interleaved thinking, configure tools and `betas: ["interleaved-thinking-2025-05-14"]`: the thinking budget may equal or exceed the positive output limit. See [Anthropic's interleaved-thinking rules](https://platform.claude.com/docs/en/build-with-claude/extended-thinking#interleaved-thinking-in-manual-mode) for supported models. `auto_thinking_budget: false` bypasses this normalization and validation; disabled and adaptive thinking are unchanged.

   - Codex CLI reads `~/.codex/auth.json`
   - Codex async model calls close their HTTP connection when cancelled, including while waiting for a response; retry waits are cancellable too. This releases local resources and does not guarantee that the remote service stops generation or billing.
   - Codex function tools preserve explicit `strict: true` or `strict: false` in wrapped or flat dictionary definitions. Missing or null settings keep the provider default. `bind_tools` applies the same conversion to dictionaries and `BaseTool` schemas.
   - Codex honors `tool_choice` in `bind_tools` and direct calls: `auto`, `none`, `required`, or a function name/selection. `any` and `True` mean `required`; `None` and `False` keep the provider default. Per-call choices override the bound policy. Bound choices are validated when binding; direct calls and overrides are validated before HTTP. `required` needs at least one function tool, and named selections must match a supplied function. `auto` and `none` also work without tools.
   - Completed Codex responses still return their text and tool calls when token usage is null, omitted, or empty; usage metadata remains unavailable.
   - The Codex model provider returns completed responses without waiting for the SSE connection to close. Failed or incomplete responses report the provider's error or reason; partial output is not returned as a successful answer. Non-object error details are reported as text.
   - `ClaudeChatModel` honors integer-second and HTTP-date `Retry-After` hints in its provider retry loop. Dates use UTC; past dates retry immediately, while invalid hints or delays beyond 24 hours retain local backoff.

   - Claude Code accepts `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_CREDENTIALS_PATH`, or `~/.claude/.credentials.json`
   - `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR` accepts a UTF-8 token handoff and reuses it for later model instances in the same process. Undecodable handoffs are skipped so Claude Code can still try its override or default credentials file.
   - CLI credential JSON files accept UTF-8 with or without a BOM, independently of the host locale. `make doctor` accepts the same files when checking CLI authentication. Invalid text encoding is treated as an unreadable source; Claude Code can still try its default file after an invalid override.
   - ACP agent entries are separate from model providers — if you configure `acp_agents.codex`, point it at a Codex ACP adapter such as `npx -y @zed-industries/codex-acp`
   - A bare or absolute ACP agent `command` is resolved before the agent starts, so npm-installed launchers work on Windows too: `npx` or `mcode` is spawned as its `npx.cmd`/`mcode.cmd` shim instead of failing with a command-not-found error, and an absolute path such as `C:\Users\me\AppData\Roaming\npm\mcode` resolves to the `mcode.cmd` shim beside npm's extensionless shell script instead of failing with `WinError 193`. The lookup uses the `PATH` the agent subprocess will actually see (`acp_agents.<name>.env.PATH` when set, otherwise the Gateway's) and hands the spawn an absolute path, so a relative `PATH` entry cannot be re-interpreted inside the agent's own workspace. A relative `command` (for example `bin/mcode`) is used as configured, and a command that cannot be resolved is still reported with the install guidance below.
   - Each ACP agent's `timeout_seconds` (default: 1800) is one shared budget for initialization, session creation, and the prompt, starting after the subprocess launches. On timeout, DeerFlow aborts the invocation and closes the subprocess before returning an error. Workspace/MCP preparation and subprocess cleanup are outside this budget. A `TimeoutError` raised by the SDK before this deadline expires retains its own error message.
   - If an ACP agent exits before answering (for example because it is not authenticated or a configured argument is wrong), DeerFlow reports its exit code within a few seconds instead of waiting for `timeout_seconds`, and records the end of the agent's stderr in the Gateway log. Agent stderr is read continuously, so an agent that logs heavily cannot stall on a full pipe.
   - MiniMax Code speaks ACP directly. Install and authenticate it, then add it as an ACP agent:

   ```bash
   npm install --global @minimax-ai/code
   mcode login
   ```

   ```yaml
   acp_agents:
     mcode:
       command: mcode
       args: ["acp"]
       description: MiniMax Code for implementation, refactoring, debugging, and repository tasks
       auto_approve_permissions: false
   ```

   `mcode` must be on the Gateway process's `PATH`; installing it only on the Docker host does not make it available inside the Gateway container. DeerFlow invokes it through `invoke_acp_agent` in a per-thread ACP workspace and forwards enabled MCP servers. Keep `auto_approve_permissions: false` for untrusted tasks; enable it only when mcode must edit files or run commands and you trust the task.
   - On macOS, export Claude Code auth explicitly if needed:

   ```bash
   eval "$(python3 scripts/export_claude_code_oauth.py --print-export)"
   ```

   The exporter rejects malformed credential containers and non-string or blank access tokens before printing a token, emitting a shell export, or writing a credentials file. Valid tokens are exported unchanged, and file exports preserve the full credential container.

   API keys can also be set manually in `.env` (recommended) or exported in your shell:

   ```bash
   OPENAI_API_KEY=your-openai-api-key
   TAVILY_API_KEY=your-tavily-api-key
   ```

   `make dev` and `make start` read `.env` as data, never as a shell script, so a
   value means what the Gateway reads: `$$`, backticks and `$(...)` stay as
   written, and an unquoted value may contain spaces. `$NAME`, `${NAME}`,
   `${NAME:-default}` and an unquoted leading `~` still expand, and
   single-quoted values stay literal.

   </details>

For an explicit backend dotenv file, export `DEER_FLOW_ENV_FILE` before startup,
alongside `DEER_FLOW_CONFIG_PATH` if needed. For example, from `backend/`:

```bash
DEER_FLOW_ENV_FILE=/srv/deer-flow/stage.env DEER_FLOW_CONFIG_PATH=/srv/deer-flow/stage.yaml make gateway
```

Relative dotenv paths use the backend process working directory; absolute paths
work regardless of that directory. Existing process variables win. An unset
selector preserves default dotenv discovery; a specified empty, missing,
non-file or unreadable path fails startup. Explicit selection also fails when
`PYTHON_DOTENV_DISABLED` disables dotenv loading. Restart after changing the file.
This selects backend dotenv input only: shell launchers, Docker Compose and the
frontend retain their own environment loading. Values they already export win.
It does not select `ENV` profiles or isolate databases, storage or tenants.
See [backend dotenv selection](backend/docs/CONFIGURATION.md#backend-dotenv-selection).

Custom blob storage backends accept `blob_storage.backend: module.Class` or
`module:Class`, including a single `.py` module importable by the Gateway.
The selected class must implement `BlobStore`; backend options go under
`blob_storage.backend_config`. See [blob storage](backend/docs/blob-storage.md).

Viewed-image artifact URLs can use shared blobs when the serving Gateway lacks
the local file. This fallback requires an existing thread record accessible to
the caller; deleting that record revokes access even if checkpoint cleanup fails.
When blob storage is disabled, a missing local file returns 404 without loading
checkpoint state. Shared-store failures also return 404 and emit a warning with
the exception type, without backend error details.

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
- `image` — a custom sandbox image, built `FROM` the pinned tag, for system packages the agent cannot install at run time (QEMU, for one). `make sandbox-enable MODE=container` rewrites the sandbox section and resets `image:` and `devices:`, so set them again afterwards.

The bundled **`repo-runner` skill** walks the agent through the whole loop (clone → detect toolchain → install in an isolated venv → run/debug → report the exact commands). Invoke it with `/repo-runner <github-url and what to do>`. It checks `id -u` first and carries on as an unprivileged user, skipping `apt-get` and `sudo`; it stops only when the sandbox has host bash disabled.

**Running a virtual machine in the sandbox.** When a project needs a VM (an OS image to boot, a kernel module to test), the skill's *When the project needs a virtual machine* section gives the agent a recipe: probe what the container has, start a headless QEMU guest in the background from files kept under `/mnt/user-data/workspace/vm/`, seed it with cloud-init, reach it over SSH on `127.0.0.1:2222`, and check at the start of each later turn whether it is still running. Three things decide whether that works for you:

- **The image must already contain QEMU.** Whether the stock image ships it was not checked, and the agent cannot install it (no `sudo`). Build your own image `FROM ghcr.io/agent-infra/sandbox:1.11.0` with `qemu-system-x86` (or `qemu-system-arm`), `qemu-utils`, `genisoimage` and `openssh-client`, and name it in `sandbox.image`. A ready-made image and a `make` target for it were proposed and are **not shipped yet**. Without QEMU the skill stops and tells you this.
- **Without `devices: [/dev/kvm]` the guest is software-emulated** (QEMU's TCG): it works with no extra permission and is slow. With it, the guest uses KVM, provided the Docker host has `/dev/kvm` at all — where it does not (Docker Desktop on macOS, a cloud VM without nested virtualization) **every** sandbox start fails with an error naming `sandbox.devices`. On Debian and Ubuntu the device is `0660 root:kvm`, which the sandbox's unprivileged user cannot open until the host has the udev rule quoted beside the key in `config.example.yaml`. Guest memory counts against the container's 2 GB limit; raise `DEER_FLOW_SANDBOX_MEMORY` for a larger guest. The key is ignored, with a warning, on Apple Container and in external or provisioner sandbox mode.
- **The security cost is real.** `/dev/kvm` hands the host kernel's KVM interface to everything the agent runs, in a container that already runs without a seccomp filter, so a KVM bug becomes a way out to the host, and commands run inside the guest are not seen by the bash audit. Leave it off unless you need fast VMs.

**None of this has been run end to end.** The key, the container flags and the recipe's commands are covered by tests, but the change was made on a machine with no Docker daemon, no `/dev/kvm` and no QEMU: whether the pinned image's user can open the forwarded device, which QEMU tools the image ships and whether the recipe boots a guest are unverified. [FORK.md](FORK.md#full-sandbox-runs-clone-a-repo-and-rundebug-it) lists what is unverified and gives one `docker run` command that checks the first of those on a Linux host with KVM.

### Running the Application

The subsections below are this fork's versions. Deployment sizing, startup modes
and LangGraph Studio are unchanged from upstream and live in the
[Running the Application](docs/guide/deployment.md) guide.

#### Option 1: Docker (Recommended)

Requires Docker Desktop / Docker Engine and **Docker Compose v2.24+**
(`docker compose version`). Older Compose clients cannot parse the optional
`env_file` syntax in `docker/docker-compose.yaml` and `docker/docker-compose-dev.yaml`.

**Development** (hot-reload, source mounts):

```bash
make docker-init    # Pull sandbox image (only once or when image updates)
make docker-start   # Start services (auto-detects sandbox mode from config.yaml)
make docker-logs    # View logs
```

`make docker-start` starts `provisioner` only when `config.yaml` uses provisioner mode (`sandbox.use: deerflow.community.aio_sandbox:AioSandboxProvider` with `provisioner_url`). Direct Compose users can add `--profile provisioner` to the dev command for the same mode; the default stack does not require Kubernetes.
With `USERDATA_PVC_NAME`, sandbox data, extra mounts and Lark broker credentials share one `user-data` volume with separate `subPath` mounts, avoiding duplicate references to the same claim on NFS CSI drivers.

Docker builds use the upstream `uv` registry by default. The gateway image installs with `uv sync --locked`, and `uv.lock` pins `https://pypi.org/simple`, so `UV_INDEX_URL` has to keep that value: exporting a mirror such as `https://pypi.tuna.tsinghua.edu.cn/simple` fails the build with ``The lockfile at `uv.lock` needs to be updated, but `--locked` was provided`` (reproduce in an already-synced environment with `cd backend && UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple uv sync --locked --check`; if the environment itself is stale, `--check` reports that instead for either index, so use `uv lock --check` to see it without syncing). Installing from a mirror requires regenerating the lock or dropping `--locked`, and both change what the image installs, so keep the default index for a checkout you intend to contribute back. `NPM_REGISTRY=https://registry.npmmirror.com` is independent of this: it applies to the frontend image's `pnpm` install and to the gateway image's Lark CLI install (`@larksuite/cli`, which `backend/Dockerfile` installs with npm).

Local AIO sandbox control traffic is always direct: loopback/private addresses,
single-label cluster hosts, and Docker/Podman internal hostnames do not inherit
`HTTP_PROXY` or `HTTPS_PROXY`. External sandbox FQDNs and public IPs still
honor environment proxy settings.

After native runtime shutdown and MCP teardown, Gateway closes an initialized
sandbox provider, including AIO sandboxes first created by a worker-thread tool call.
It does not start an unused sandbox provider solely for cleanup.

Backend processes automatically pick up `config.yaml` changes on the next config access, so model metadata updates do not require a manual restart during development.

Gateway runs use the top-level `recursion_limit` in `config.yaml` when an API
request does not provide one. **This fork's default is `250`, not upstream's
`100`**: a run's `recursion_limit` caps LangGraph super-steps, and a session that
clones a repo and then iterates over it — many `bash` / `read_file` /
`write_file` / `str_replace` turns, each one a super-step — routinely exceeds a
lower cap and aborts mid-task with `GraphRecursionError`. Valid per-request
values take precedence, and `max_recursion_limit` (default `1000`) caps both.
Changes apply to the next run without restarting the Gateway. This top-level setting
applies to Gateway API and IM channel runs. A `recursion_limit` in an IM
channel's `session.config` takes precedence, and GitHub channel runs keep
their own floor. Embedded `DeerFlowClient` runs retain their own defaults and
per-call override paths. A run that reaches its limit stops with a plain message
that names up to five files it created in `/mnt/user-data/outputs` without
presenting them; send a message to continue. IM channels reply with the same
message.

A custom frontend can add an optional `context.client` to a Gateway run request:
a client name, capabilities such as `artifacts` or `charts`, and display
preferences. DeerFlow sanitizes it and passes the values to the agent as
untrusted, request-scoped hints, so skills can pick an output shape the client
can show. It is never an authorization or identity signal. See
[Create Run](backend/docs/API.md#create-run).
Client hints are omitted from stored run configuration and must be sent again
for each run; later runs, including server-started tasks, do not inherit them.
The checkpoint storage settings `database.checkpoint_channel_mode` and
`database.checkpoint_delta.snapshot_frequency` (default `10`) are exceptions:
both are frozen when the process first builds an agent (including through
`DeerFlowClient`) and require a process restart to change safely.

In delta mode, a run selecting an older checkpoint reports an error before rewriting
state if either the selected checkpoint or the current head has pending tool
execution. For `Command(resume=...)`, other pending graph nodes also prevent the
rewrite, except for the synthetic input entry node. Resume pending work from the
latest checkpoint; to regenerate completed work, submit new input there. Full-mode
resumes and ordinary replay without pending execution keep their existing behavior.

The optional `database.checkpoint_cache` section (delta channel mode only)
caches materialized checkpoint histories: `type` is `memory` (default) or
`redis`, and `max_entries: 0` disables the cache. The `redis` backend is
Gateway/async-only; the sync TUI/embedded path supports `memory` only. The
cache is performance-only — results are identical with it disabled — so it is
never frozen and workers sharing one checkpoint database may safely run
different cache settings. Returned state snapshots have independent nested values,
so editing one cannot change later checkpoint reads. Redis thread cleanup treats a configured `key_prefix`
as literal text, including glob metacharacters, so deletion stays within that
namespace and thread. Redis rejects malformed write records on ingestion; malformed
or wrong-channel cached histories are rebuilt in full from authoritative checkpoints.
Seeds and write values remain opaque to the cache: these checks do not validate
schema-specific state contents.
Checkpoint reads, valid neighboring writes and optional-cache cleanup continue
even if a warning handler fails.

Gateway checkpoint cleanup runs when the next run wins durable same-thread
admission, before its first checkpoint read. It checks only the root head and
its parent, removes at most one metadata-only duration leaf without pending
writes, and preserves explicit checkpoint selections and delta replay state.
See [checkpoint operations](frontend/src/content/en/harness/checkpoints/operations.mdx)
for the retention constraints.

> [!TIP]
> On Linux, if Docker-based commands fail with `permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock`, add your user to the `docker` group and re-login before retrying. See [CONTRIBUTING.md](CONTRIBUTING.md#linux-docker-daemon-permission-denied) for the full fix.

**Production** (builds images locally, mounts runtime config and data):

```bash
make up     # Build images and start all production services
make down   # Stop and remove containers
```

Access: http://localhost:2026

`make up` waits for the Gateway `/health` endpoint before reporting success.
If the Gateway does not become healthy within the startup window, deployment
exits non-zero and prints the container status plus recent Gateway logs. The
production image starts from its already-built environment and never resolves
or installs Python dependencies at container startup.

Images built from a checkout never contain its local configuration:
`.dockerignore` keeps `config.yaml`, `config.yaml.bak`, `extensions_config.json`
and `mcp_config.json` (at the root or in the legacy `backend/` location), `.env`
and `.env*.local` files, local HTTPS keys (`frontend/*.pem`), and the credential
files the extension manager refuses inside `backend/extensions/sources/` out of
the build context. Compose mounts the config and passes the environment at
runtime, so pushing or sharing an image does not publish those credentials.
A locally built frontend image therefore no longer picks up `NEXT_PUBLIC_*`
values from `frontend/.env.local`: `next build` inlines them into the client
bundle, Compose's environment reaches only `next start`, and `frontend/Dockerfile`
takes no build arguments for them. The Docker stack serves the frontend and
Gateway from one nginx origin and needs none of them.

If `make up` reports an unwritable runtime home or an unreadable persisted secret
after `make docker-start`, run the printed `sudo chown -R <uid>:<gid> '<home>'`
recovery command and retry. The check honors secret overrides from the shell or
`.env`, accepts readable read-only secret files, and leaves `make down` available
without reading or generating secrets.

Production Docker commands can select a root dotenv profile with
`DEER_FLOW_COMPOSE_ENV_FILE=/srv/deer-flow/stage.env make up`. The same file
feeds Compose interpolation, Gateway/provisioner variables, and deployment
secret checks. YAML and runtime-state locations remain separate selectors;
see [production env files](backend/docs/CONFIGURATION.md#production-compose-env-files).

For persistent deployments, configure `database.backend` as `sqlite` or
`postgres`. The selected backend is shared by the LangGraph checkpointer,
LangGraph Store, and DeerFlow application data. The deprecated `checkpointer`
section, when present, overrides the first two for backward compatibility.

`run_events.backend` defaults to `db` and should stay durable alongside it.
Scrolling back through a long conversation is served by
`GET /api/threads/{thread_id}/messages/page`, which reads the run-event store
and nothing else, so on `run_events.backend: memory` a Gateway restart drops
that history: the conversation still opens and still renders its recent turns
from the checkpoint, then stops loading older messages when you scroll up, with
nothing logged. `db` writes into the database configured above, so it needs no
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
Gateway startup automatically repairs the missing run-change schema affecting
some existing databases (#5516). The repair preserves run history and existing
change positions; downgrading the repair to its predecessor also retains the
schema and positions required by that version.

For lightweight single-process event persistence, `run_events.backend: jsonl`
keeps Unicode message content intact, including line and paragraph separators.
Existing valid JSONL records remain readable without rewriting the files.

For per-call usage audits, an immediate LLM response replay with populated usage
updates both nested usage and top-level token counters, even if initial usage was absent or zero.
The original request, model, and status metadata stay intact; flushed events are
not rewritten. See the [run event contract](contracts/run_event_stream_contract.json).

The unified nginx endpoint is same-origin by default and does not emit browser CORS headers. If you run a split-origin or port-forwarded browser client, set `GATEWAY_CORS_ORIGINS` to comma-separated exact origins such as `http://localhost:3000`; the Gateway then applies the CORS allowlist and matching CSRF origin checks.

When fine-grained authorization is enabled, Live Browser connections require `threads:write` as well as ownership of the thread, even when only viewing frames: the same connection can control the browser. Permission checks run when connecting. Restart Gateway after upgrading to disconnect sessions admitted by older code.

The bundled Docker, local and Helm nginx configs proxy Live Browser WebSocket upgrades with a 600-second read timeout for quiet streams. Helm uses nginx's default connection and send timeouts for the in-cluster Gateway. Any additional Ingress or reverse proxy must also allow WebSocket upgrades.

Browser login uses `HttpOnly` session cookies. The login page offers a "keep me signed in" option that extends the browser session when the request is HTTPS (including trusted `X-Forwarded-Proto: https`) or localhost HTTP. The localhost exception uses the direct request `Host` and ignores forwarded host headers. Public HTTP deployments, including many temporary sandbox URLs, fall back to session cookies by default. DeerFlow never stores the password in browser storage; the UI may remember only the email address.

If an authentication refresh fails during a temporary network outage, a visible
tab rechecks the unknown session when connectivity returns or on a later tab
switch. Reconnects received in a background tab are remembered until it becomes
visible, without waiting for the tab-switch throttle. Identity is restored only
after a successful auth response; a confirmed expired session or explicit logout
still requires signing in again.

Password forms accept non-ASCII email addresses and trim surrounding email whitespace.
Sign-in requires at least six password characters; creating an account or choosing
a new password requires eight. These checks run before sending a request.
Passwords, including surrounding spaces, are submitted unchanged.

OIDC/SSO authorization endpoints may include provider query parameters such as `?prompt=login`. DeerFlow preserves those parameters when adding the login request, including for configured `authorization_endpoint` overrides.

After an SSO sign-in, DeerFlow returns you to the page that asked you to sign in instead of the default workspace. Opening the login page while already signed in does the same for its `next` target.

Administrators can suspend and restore accounts from **Settings → Users** (admin-only; the section is hidden for ordinary users). The page lists each account's email, role, and status and exposes the same enable/disable operation as `PATCH /api/v1/admin/users/{id}`; the last remaining active admin cannot be disabled, and the Gateway's rejection detail is shown verbatim. A disabled account is rejected by every authentication surface, and its live sessions end on the next request with a login page that states the account has been disabled. Password login for a disabled account deliberately still answers "incorrect email or password" so the state is not disclosed to whoever holds the credentials.

DeerFlow still uses `Forwarded` / `X-Forwarded-*` headers to recover the browser-facing scheme and origin behind a proxy. The bundled nginx sets `X-Forwarded-Proto`, but preserves an upstream HTTPS value and does not overwrite every forwarded header. Configure the outer trusted proxy to replace or strip client-supplied forwarding headers before traffic reaches DeerFlow.

> [!IMPORTANT]
> The Gateway still owns active run tasks in process, so production defaults to a single Gateway worker (`GATEWAY_WORKERS=1`). Multi-worker deployments require Postgres, the Redis stream bridge (`stream_bridge.type: redis`), `run_ownership.heartbeat_enabled: true`, and `run_events.backend: db`; process-local memory/JSONL event stores cannot enforce singleton delivery receipts across workers. Kubernetes replicas run one worker per Pod, which the worker count cannot see: declare them with `deployment.multi_instance: true` (or `DEER_FLOW_MULTI_INSTANCE=1`, which deploy tooling such as a Helm chart can set from its replica count) so the startup gate enforces the same prerequisites instead of staying inert. Declared instances that store credentials (`channel_connections`, or MCP servers using the OAuth `refresh_token` grant, whose rotating tokens they share through the database) must also share one at-rest `DEER_FLOW_CREDENTIALS_KEY` (the Helm chart and `make up` generate it; back it up, see [backend/docs/CONFIGURATION.md](backend/docs/CONFIGURATION.md#credentials-encryption-key-deer_flow_credentials_key)). The bridge shares SSE delivery and bounded `Last-Event-ID` replay across workers. When a trimmed reconnect cursor cannot be verified for complete replay, or a subscriber that already established an empty-stream wait falls behind before its first delivery, Memory and Redis emit a machine-readable SSE `gap` event instead of silently returning a partial replay; the Web UI reloads durable thread/event state and resumes from the retained tail. The Memory bridge can replay without recovery when the cursor is its exact last evicted event: every successor is still retained. Older or unverifiable evicted cursors still trigger recovery. An already-observed Redis stream removed during replay also signals a gap, so slow subscribers reload durable state instead of heartbeating forever after cleanup. Redis also tracks terminal stream producers with a short lease: if a worker dies after committing a terminal run status but before publishing END, SSE and `/wait` finish after the lease expires instead of waiting for the retained stream's TTL. Lease reconciliation marks runs from dead workers as errors, persists their delivery receipts, publishes the terminal stream marker, schedules retained-stream cleanup, and updates the affected thread status. Redis END publication is atomic and idempotent: owner and recovery retries confirm an existing marker without appending another, events cannot be appended once END is the stream tail, and an unowned recovery retry after cleanup does not recreate the stream. Legacy streams with an earlier END followed by late data can still accept data. The Redis compatibility scan (`stream_bridge.legacy_end_scan_enabled: true`) also runs on first END publication; disable it only after old writers stop and all legacy replay buffers expire or are removed, then restart every Gateway to use tail-only END detection. SSE, `/wait`, and internal stream consumers use `stream_bridge.heartbeat_interval_seconds` (default `15`) for idle liveness checks; changing it requires a Gateway restart. Malformed Redis reconnect IDs live-tail new events instead of replaying the retained buffer, and the rolling retained-buffer TTL (`stream_ttl_seconds`) remains a cleanup safety net rather than a run timeout. Failed-login counters and lockouts for `POST /api/v1/auth/login/local` (`auth.local.max_login_attempts` / `lockout_seconds`) are kept in the shared `login_throttle` table whenever the application database is SQLite or Postgres (`auth.local.throttle_storage: auto`, the default), so every replica enforces one lockout per client IP; `memory` keeps the historical per-process counter, which under N replicas hands an attacker N × `max_login_attempts` guesses and logs a startup warning. IM chat-to-thread bindings live in the shared `channel_thread_bindings` table whenever the application database is SQLite or Postgres (an existing `channels/store.json` is imported once at startup and renamed `store.json.migrated`); IM bot credentials entered in the web UI live in the shared `channel_runtime_configs` table, encrypted with `DEER_FLOW_CREDENTIALS_KEY` (an existing `channels/runtime-config.json` is imported once and then deleted), so a save on any instance reaches the provider's connection within one lease renewal; each provider's platform connection is held by one instance through the shared `channel_leases` table — `channels.leader_lease` (default `auto`, on wherever the multi-process signal is) hands it to another instance when the holder dies, and the startup gate refuses `enabled: false` while an IM channel other than GitHub is enabled (see [IM channel leader lease](backend/docs/CONFIGURATION.md#im-channel-leader-lease-channelsleader_lease)); follow-up buffers still need their own multi-worker coordination. To try this topology on one machine, `make dev-multi` starts two Gateways on shared Postgres, Redis and `DEER_FLOW_HOME`, and `make dev-multi-check` runs the cross-instance checks; see the local two-Gateway harness in [backend/docs/CONFIGURATION.md](backend/docs/CONFIGURATION.md#local-two-gateway-harness).
>
> The producer-lease recovery behavior above is gated by `stream_bridge.producer_lease_recovery_enabled`. Keep it disabled while old Gateway binaries or their runs remain; enable it on every instance only after the writer rollout and drain complete.
>
> With run ownership heartbeats enabled, terminal success requires acknowledgment
> from that worker's own durable write. Run creation and replacement serialize
> per conversation: a slow admission does not hold the manager-wide lock needed
> by another conversation's cached run reads or heartbeat snapshots. Their own
> Store I/O can still encounter database or pool contention. New runs remain
> hidden until their initial Store write succeeds. A matching database row alone cannot
> confirm success, and completion metadata cannot retry a rejected terminal
> transition. Each run renews independently, so a stalled store operation does
> not delay other runs. If acknowledgment remains unavailable when the last
> confirmed lease expires, the worker stops conservatively even if its commit
> actually reached the database. Expired leases cannot be renewed.
> Interrupt-and-replace admission acknowledges only the old runs actually claimed
> by its atomic transaction. Rollback keeps renewing its acknowledged interrupted
> row until restoration and the separate final error commit finish. An
> active-only renewal that raced that admission gets one bounded retry after the
> interrupted acknowledgment, without weakening the owner or live-lease checks.
> A failed renewal leaves a local expiry guard armed. Shutdown bounds its wait for orphan
> recovery, but cancellation-resistant storage may still be using its resources.

>
> The local two-Gateway harness disables IM providers under both `channels` and `channel_connections` by default. `DEERFLOW_MI_KEEP_CHANNELS=1` preserves them; `channels.leader_lease` stays as configured.
>
> Cleaning up an in-memory run stream, or closing its bridge, releases retained
> payloads and signals a replay gap to subscribers with unfinished replay. They
> reload durable state instead of waiting on a detached buffer or consuming stale
> history. Established readers that fully consumed a terminal stream retain their
> normal `end` signal. A new reader whose initial attachment loses the race with
> cleanup receives a gap so it can recover the saved result.
>
> In-memory stream events retain the payload as it was published. Reusing a
> producer's data object or editing a received event does not change another
> subscriber's output or reconnect replay.
>
> During SSE replay-gap recovery, the Web UI preserves a reconnect pointer claimed by another run while durable state is loading. An older recovery cannot overwrite that pointer when it rejoins its own stream. Even a stale foreign pointer is preserved, so the next reload may first check that run before active-run recovery rejoins, adding a reconnect cycle.
>
> Store-only SSE and `/wait` consumers can finish after a heartbeat when run-manager
> or scheduled-task reconciliation recovers a dead worker's run, even if no END
> marker was published. Ordinary completions still wait for END to preserve tail events.
>
> In single-process JSONL deployments, cancelling an admitted event-store mutation waits for its background file I/O, rollback, and bookkeeping to settle before releasing the thread write lock. This prevents an older cancelled write from recreating deleted records or rolling back a later successful write. Cancellation can therefore wait on slow storage; it does not stop an in-flight filesystem operation. Callers still waiting to acquire the lock can cancel without starting a mutation. A batch spanning multiple threads drains its current thread group before propagating cancellation; subsequent thread groups do not start.
>
> After a run publishes its terminal stream marker, its process-local `RunRecord` remains available for the existing five-minute grace period before cleanup; durable run history remains available through `RunStore`, while the stream bridge retains its delivery tail on its separate cleanup schedule.
>
> With in-memory run storage, replacing a run snapshot under another thread removes its previous thread membership. Old-thread history and usage queries exclude it, and deleting the old thread preserves the reassigned run.
>
> Run cancellation may land on any Gateway worker. A non-owning worker now persists the interrupt or rollback request for the live owner, which observes it during lease renewal and performs the normal cancellation flow; load-balancer routing alone no longer produces a 409. The first accepted action wins even if a retry lands on the owner, and accepted cancellation competes atomically with owner completion. Dead owners still follow lease takeover and orphan recovery. Cancellation latency is therefore bounded by the lease heartbeat interval.

> Cancelling a model recovery probe, including while it is queued or waiting to retry, lets the next call check whether the provider has recovered. Cancellation does not count as a provider failure or release another call's active recovery probe.
>
> Model retries honor valid provider `Retry-After` hints up to 24 hours, including waits longer than the local backoff cap. Malformed, non-finite, or over-limit hints use normal backoff instead. This applies to numeric and HTTP-date hints in LLM error handling and Codex's retry path, and integer-second hints in Claude's retry path. Codex prioritizes numeric `retry-after-ms` hints; past HTTP-date hints retry immediately.
>
> With lease heartbeat enabled, a transient RunStore renewal error is retried only until the last confirmed lease expires; the stale worker then cancels local execution and suppresses checkpoint, completion-hook, delivery-receipt, and thread-status finalization. A remote tool side effect already in flight may still be outside local cancellation.
>
> Reconciliation uses an atomic takeover claim that re-checks the lease after candidate selection, so a successful owner renewal wins over orphan recovery and only one reconciler can report a run as recovered. When multiple Gateway workers share the Docker/AIO or E2B sandbox backend, also configure `sandbox.ownership.type: redis`; E2B uses the leases during background startup and periodic reconciliation so duplicate/orphan cleanup cannot terminate a live peer's sandbox.

If a completed thread operation (such as a checkpoint, goal, or artifact write,
branch, or deletion) fails to release its database reservation, the same Gateway
worker retries cleanup when it receives a new run or mutation for that thread.
This also works in single-worker deployments with lease heartbeats disabled.
If cleanup fails again, admission returns a busy response. Completed requests
can still replay their saved results by idempotency key.

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed Docker development guide.

#### Upgrading an existing checkout

Keep `config.yaml`, `.env`, and `extensions_config.json`. Stop the services you
currently use, run `git pull --ff-only`, then start the same mode again. Do not run
`make config` or `make docker-init` again for a routine source upgrade. Every launcher
runs `make config-upgrade` before it starts, so new configuration (such as a bundled
plugin) arrives on its own. A Docker host with neither `backend/.venv` nor PyYAML
says so instead; install PyYAML (e.g. `python3-yaml`) and run `make config-upgrade`.
See [Operations and Troubleshooting](frontend/src/content/en/application/operations-and-troubleshooting.mdx#upgrading-an-existing-checkout)
for the commands for each mode.

To continue a thread paused at a static `interrupt_before` or `interrupt_after`
breakpoint, submit `input: null` (or omit `input`) to its `/runs`, `/runs/wait`,
or `/runs/stream` endpoint. This continues pending graph work with the source
turn's knowledge scope from the selected checkpoint (the head by default).
An explicit empty object is new input, not a continuation; dynamic interrupts
still require `command.resume`. In delta mode, historical continuation rejects
rewrites that would discard pending execution; continue at the head instead.
Continuations retain the checkpoint's MCP `background_tasks` projection; only
dictionary input refreshes it from the task repository.
Old null-input runs stored as `{}` cannot safely match a keyed null-input retry
after upgrading and return 409. Check the original run before submitting a new key.

When rolling out the resume-command idempotency fix across multiple Gateway
workers or Pods, route **all keyed resume submissions and retries** (`command.resume`
with `Idempotency-Key`, on thread-scoped `/runs`, `/runs/stream`, or `/runs/wait`)
only to upgraded workers until every worker serving these endpoints is upgraded.
Older workers ignore the private resume identity and compare only `input`: with
`input: null`, retrying `deny` can incorrectly reuse an earlier `approve` run.
If the load balancer cannot isolate upgraded workers, pause keyed resume traffic
until the rollout finishes, or stop all old workers before restarting on the new
version. The additive database migration keeps old run-history readers compatible;
it does not make old workers safe for resume admission. An upgraded worker returns
409 when retrying an identity-less legacy resume run, even for the same decision;
inspect that run and the current thread state before deciding to submit a new
action. See the [run API contract](backend/docs/API.md#create-run).

Custom run stores must explicitly support every supplied idempotency field.
Keyed input and resume requests return HTTP 503 before run admission when the
store cannot guarantee that support. The built-in Memory and SQL stores support
both fields; older custom stores with an explicit `idempotency_key` parameter
continue to accept keyed input requests.

Gateway runs also assign IDs to input messages that omit one before storing the
run record and invoking the graph. This keeps the message visible as one turn
when the Web UI reconnects to an active run started by an API client. During a
rolling upgrade, route keyed runs with ID-less input and their retries to
upgraded workers until all Gateway workers are upgraded; older workers may
reject those retries with 409. See the [run API contract](backend/docs/API.md#create-run).

#### Option 2: Local Development

If you prefer running services locally:

Prerequisite: complete the "Configuration" steps above first (`make setup`). If no `config.yaml` exists, the first `make dev` / `make start` seeds one from `config.example.yaml` automatically (the same first-run seeding the Docker launch paths do) and the API-key auto-config enables the model block matching whatever provider key is in your environment / `.env` — so a fresh checkout starts without a separate `make config` step, though `make setup` still gives the best guided setup. Set `DEER_FLOW_PROJECT_ROOT` to define that root explicitly, or `DEER_FLOW_CONFIG_PATH` to point at a specific config file. Runtime state defaults to `.deer-flow` under the project root and can be moved with `DEER_FLOW_HOME`; skills default to `skills/` under the project root and can be moved with `DEER_FLOW_SKILLS_PATH`. Run `make doctor` to verify your setup before starting.

Configuration checks and agent-storage migrations use the installed backend environment through `uv run --no-sync --project backend` from the repository root. This preserves relative runtime paths and installed optional dependencies; see the [setup checks](backend/docs/SETUP.md#steps) and [agent-storage migration](backend/docs/CONFIGURATION.md#agent-storage).

On Windows, run the local development flow from Git Bash. Native `cmd.exe` and PowerShell shells are not supported for the bash-based service scripts, and WSL is not guaranteed because some scripts rely on Git for Windows utilities such as `cygpath`.

The documented root `make` commands invoke repository `.sh` files through Bash
explicitly. They therefore continue to work from source archives or filesystems
that do not preserve POSIX executable bits. When calling a script directly from
such a checkout, use `bash ./scripts/<name>.sh ...`.

1. **Check prerequisites**:
   ```bash
   make check  # Verifies Node.js 22+, pnpm, uv, nginx
   ```

   The local `make check`, `make install`, `make dev`, and `make start` entry points use a direct `pnpm` executable when available and otherwise fall back to `corepack pnpm`. With native Windows Python, the shared runner checks `pnpm.cmd` before the generic `pnpm` lookup, which follows `PATH`/`PATHEXT` and may select an `.exe` or `.bat` in the same or an earlier PATH directory. The Corepack fallback likewise checks `corepack.cmd` before `corepack`. POSIX Python keeps the generic names first, including when running under MSYS/Cygwin. The runner and diagnostics resolve repository paths absolutely, so these checks work regardless of the caller's current directory. Corepack runs from `frontend/`, so it honors the `packageManager` version pinned in `frontend/package.json`; enabling a global pnpm shim is not required.

   `make check` decodes tool diagnostics as UTF-8 and preserves Unicode pnpm
   errors on non-UTF-8 hosts. Invalid output bytes are replaced so the checker
   can report dependency failures instead of aborting while decoding output.

2. **Install dependencies**:
   ```bash
   make install  # Install backend + frontend dependencies + pre-commit hooks
   ```

   Hook setup calls pre-commit through uv, so uv's tool directory need not be on `PATH`.

3. **(Optional) Pre-pull sandbox image**:
   ```bash
   # Recommended if using Docker/Container-based sandbox
   make setup-sandbox
   ```
   Reads the configured sandbox image from UTF-8 `config.yaml`, with or without a leading BOM, using LF or CRLF line endings.
   On macOS, a successful Apple Container pull completes this step even when Docker is not installed. If Docker is available, its image is also pulled.

4. **Start services**:
   ```bash
   make dev
   ```

   Local nginx writes temporary files under the checkout's `temp/` directory.

5. **Access**: http://localhost:2026

6. **(Optional) Load sample memory data for local review**: open `Settings > Memory`, click **Import memory**, and select `backend/docs/memory-settings-sample.json`. The browser imports into the signed-in user's memory.

   To replace memory for every registered user in a disposable review environment:

   ```bash
   cd backend
   uv run python ../scripts/load_memory_sample.py --all-users
   ```

   Bulk mode supports SQLite/PostgreSQL user registries, creates a distinct timestamped backup directory for every import under `.deer-flow/memory-sample-backups/`, and rejects the non-persistent `database.backend: memory` mode. See [backend/docs/MEMORY_SETTINGS_REVIEW.md](backend/docs/MEMORY_SETTINGS_REVIEW.md) for the complete review flow.

Local services always use their internal ports (`8001`, `3000`, and `2026`).
The root `.env` variable `PORT` configures only the published Docker ingress;
it does not change the Next.js port used by `make dev`.

Local startup waits up to 30 seconds for the Gateway port. On a slow cold start,
set a longer wait without editing the launcher:

```bash
DEER_FLOW_GATEWAY_STARTUP_TIMEOUT=240 make dev
```

The value must be a positive integer in seconds. You can also set it in the
root `.env`, whose value takes precedence over the shell. It applies to local
`make dev`, `make start`, and their daemon variants, not Docker health checks
or LLM request timeouts. Check `logs/gateway.log` for startup errors before
increasing the wait; an expired deadline still stops the services.

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
| MCP servers | [MCP Server](docs/guide/mcp.md) |
| Sub-agents and task delegation | [Sub-Agents](docs/guide/subagents.md), [Tool restrictions](docs/guide/subagents.md#tool-restrictions) |
| Long-term memory | [Long-Term Memory](docs/guide/memory.md) |
| Session goals, context compaction, task notes, evidence-based decisions | [Context, Goals and Agent Decisions](docs/guide/context.md) |
| Private knowledge retrieval (RAGFlow) | [Private Knowledge Retrieval](docs/guide/knowledge-retrieval.md) |
| Agentic browser control | [Agentic Browser Control](docs/guide/browser-control.md) |
| Projects, instructions, document shelf | [Projects](docs/guide/projects.md) |
| Scheduled tasks | [Scheduled Tasks](docs/guide/scheduled-tasks.md) |
| Feishu, Slack, Telegram, Discord, DingTalk and other IM channels | [IM Channels](docs/guide/im-channels.md) |
| File attachments, downloads and Office previews | [File Previews](docs/guide/file-previews.md) |
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
`/mnt/user-data`: the agent's scratch work in `workspace/` (a cloned repository,
a virtual environment, intermediate data), your attachments in `uploads/`, and
deliverables in `outputs/`. The artifacts panel lists only the files the agent
chose to present, so the rest used to be reachable only by asking the agent. The
**Files** button in the chat header opens the same right-hand panel on a
**Files** tab: a tree of that folder, opened one directory at a time, with each
file's size and when it last changed. Select a file to preview it with the
artifacts viewer, or download it. While a run is working, open folders refresh
every few seconds.

- **Read-only, and confined to the conversation.** The listing comes from
  `GET /api/threads/{thread_id}/files?path=…`, which applies the artifacts
  endpoint's owner check and path confinement: nothing outside the
  conversation's own folder is listed, and a symbolic link is shown as a link,
  never followed. Editing stays where it was, for text files in `outputs/`.
- **Large folders say they were cut.** A listing returns at most 500 entries (a
  `node_modules` folder ends with "N more not shown"), and in-flight upload and
  edit temporary files are hidden.
- **The folder has to be on the host.** With the local sandbox and in
  per-conversation container mode it is, so the explorer sees everything. A
  shared external sandbox container (`make sandbox-up`) keeps the workspace
  inside the container, where the explorer, like the artifacts panel, cannot
  see it.

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
*Recent chats* header, give the folder a name, and drag conversations onto it — or use
**Move to folder** in a conversation's **⋯** menu if you would rather not drag.
The arrow beside a folder's name opens and closes it, and its own **⋯** menu
holds **New subfolder**, **Move folder to**, **Rename** and **Delete**, in the
same place as the menu each conversation already has.

**Folders nest.** A folder can go inside a folder — drag one onto another, or
use its **New subfolder** / **Move folder to** entries — up to five levels deep.
A chat filed two levels down is listed there and nowhere else, and the count
beside a folder's name covers everything below it, so a collapsed folder never
reads as empty while holding twenty conversations. Collapsing a folder collapses
its whole branch. Deleting one deletes its subfolders too — but never the
conversations, which come straight back to the main list.

**A conversation you file is inside the folder and no longer in the list outside
it.** That is the point of the feature and the thing that makes a folder worth
having: collapse it and those chats are genuinely out of the way, rather than
listed twice. The number beside a folder's name says how many are in there while
it is closed.

**Deleting a folder never deletes the conversations in it.** They return to the
main list immediately — the folder is a label, not a container the chats live
inside. The same is true if a folder disappears for any other reason (deleted
from another browser, say): a conversation pointing at a folder that no longer
exists is shown in the main list, never hidden. A *folder* whose parent is gone
is treated the same way and reappears at the top level, so no branch of the tree
can take the chats inside it out of sight.

Folder names, their order, and which conversation is in which folder are stored
**per user on the server**, so they follow you to another browser or another
device. Only which folders are
*expanded* is per browser, since that is genuinely a per-screen preference.

Two limits worth knowing: a ceiling of **50 folders** in total, and **five
levels** of nesting (past that the indentation leaves no room for a chat's
title). Filing a conversation deliberately does **not** count as activity, so it
keeps its place in the recency order instead of jumping to the top of the list
the moment you drag it.

Nothing to configure; it is on as soon as you have a conversation to file.

### A Conversation Remembers Its Model

Each chat has its own model, subagent model, mode and reasoning effort — selecting one in an open conversation never changes another. What is new is that the conversation **remembers** it: the selection is recorded on the chat itself, not only in the browser you happened to pick it in.

That matters in three ordinary situations, all of which used to look like the app forgetting:

- **Switching conversations.** Opening a chat now moves the picker to *that* chat's model instead of leaving whatever was selected last. Previously any conversation this browser had not touched had nothing recorded, so it fell back to the app default.
- **A different browser or device.** Your phone reads the same record your laptop wrote, so a chat that has been talking to a local model does not silently switch to a cloud one when you pick it up elsewhere. Same after clearing site data.
- **A brand-new chat.** A new chat is addressed by a placeholder id until you send the first message, at which point the server assigns a real one. The selection used to be stranded under the placeholder, so the chat forgot its model on the very turn it had just answered with it. It now carries across.

In Ultra mode the **subagent** model is remembered alongside the lead model, so a conversation that delegates to a cheap local model keeps doing so.

Nothing to configure, and changing a model never reorders your sidebar — the recency-ordered list treats a model change as what it is, not as activity in the conversation.

### Automatic Conversation Titles

A new conversation is called *New Conversation* until something renames it.
DeerFlow renames it from the first exchange, and **Settings → Conversation
titles** is where you decide whether it does that at all and what it costs. The
switch beside the page heading turns automatic renaming off; a conversation then
keeps whatever you call it yourself, indefinitely.

Under the switch is a **Title model** dropdown with three kinds of answer:

- **No model call** — the title is your first message, shortened. Free,
  instant, and surprisingly good, because a first message is usually a question
  about one thing.
- **A configured model** — that model reads the first question and the answer to
  it and writes a short title. It sees at most 500 characters of each, so even a
  premium model costs a fraction of a cent per conversation; a cheap or local one
  costs nothing worth measuring.
- **Server default** — follow whatever the operator set in `config.yaml`, which
  is what a fresh install does. **The shipped default is no model call**, so
  DeerFlow does not quietly bill you for titles.

**The rename waits for the answer to finish.** This is the part worth knowing:
the Gateway refuses to rename a conversation while a run is in flight (that is
why the **Rename** menu item does nothing mid-answer), so the automatic rename is
deliberately scheduled for the end of the turn — the same moment your own rename
becomes possible again. A side effect is that the title now describes the
*answer* as well as the question, because the answer exists by the time it is
written. A first turn that ends by **asking you** a clarifying question is
renamed too, which it previously never was: it exits the run through a different
path, and the conversation used to stay called *New Conversation* forever, since
only the first turn is ever titled.

The preference lives in your browser (per browser, like the other client
settings). The operator's master switch is `config.yaml`, and turning it off
there greys out the toggle with an explanation rather than silently ignoring it:

```yaml
title:
  enabled: true # false disables automatic renaming for everyone
  max_words: 6
  max_chars: 60
  model_name: null # null = no model call (shortened first message)
```

`max_words` and `max_chars` bound the model's output; the shortened-first-message
path honours `max_chars` too. No new configuration keys — the settings page reads
the block that was already there, and the per-user choice is layered on top of it
at run time.

### Renaming a Conversation on Demand

The automatic rename above happens **once**, at the end of the first turn. That
is the wrong moment often enough to matter: a chat that opened with "quick
question about the build" and turned into a three-hour refactor is still filed
under the quick question.

**Auto rename** in the chat header is the same thing on demand. Press it, pick a
model, press **Run**, and the conversation is renamed from what is in it now.
Because you choose the model per press, the choice can be a different one from
the automatic rename's: that one runs on every new chat and wants something
cheap, while renaming a conversation that turned out to matter can afford a good
model. Leaving the picker on **Server default** uses whatever `config.yaml`
names. A model you pick is remembered, and it is the same preference **Settings →
Conversation titles** reads, so the two screens never disagree about which model
will run.

It reads the first two exchanges — and only what you actually saw. On an Ultra or
Democracy turn the panelists' deliberation is stored with the turn, and it is
routinely far longer than the reply on screen; feeding that to a title model
names the conversation after the models arguing with each other. So tool results,
scaffolding and anything the interface hides are dropped, and the answer for a
turn is the final reply you read.

Two things are worth knowing. The button spends one model call, and it is counted
in the conversation's cost in the header, under **Chat rename** — nothing is
billed to you invisibly. And like every rename, it is refused while a run is in
flight; press it mid-answer and you get that refusal in so many words, not a
silent no-op. A model the operator has removed from `config.yaml` is refused too,
rather than quietly swapped for another one.

The operator's switch covers it: with `title.enabled: false` in `config.yaml`
the button is not shown at all, because a manual rename spends the same kind of
call the switch exists to stop.

No new configuration keys: it reads the same `title:` block as the automatic
rename.

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
- [Architecture Overview](docs/ARCHITECTURE.md) - How the services fit together
- [Contributing Guide](CONTRIBUTING.md) - Development environment, workflow and tests
- [The Code Change Cycle](CHANGE_CYCLE.md) - The procedure every change follows: test, checklist row, full run, docs, PR
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
