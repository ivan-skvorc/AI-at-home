> **This is a fork of [bytedance/deer-flow](https://github.com/bytedance/deer-flow).**
>
> It's meant to be a **personal AI you host at home** — a private, self-run alternative to the big assistants that you reach over [Tailscale](https://tailscale.com/) from your phone or laptop anywhere, with no login wall on your own network. Point it at local [Ollama](https://ollama.com/) models for a **free** experience (you only pay for electricity), mix in a cheap cloud key when you want more muscle, and run **several conversations at once — each pinned to its own model**, so a free local chat and a cloud-powered one stay fully independent. You get something close to the Claude Code / Claude.ai experience — sub-agents, memory, sandboxed tool use, a chat UI, and custom agents it can draft for you from your own past conversations — running on hardware you already own and control. The fork's defaults (passwordless-on-LAN, Tailscale-ready dev origins, local-first search/fetch, independent per-conversation model selection, suggestions & memory off by default, and a live cost overview) are all in service of that goal: keep it private, keep it cheap, keep it yours.
>
> On top of upstream, it adds — out of the box:
>
> - 🦙 **Auto-populated Ollama models** — `config.yaml`'s `models:` list is synced from your local `ollama pull` list on every launch. Capabilities (thinking / vision / tools) are detected and mapped to DeerFlow's `supports_*` flags, and each model gets a VRAM-aware context window instead of Ollama's tiny 2048-token default. The daemon itself is managed too: set `ollama.keep_alive` so a model stays loaded between turns instead of paying a cold start on every subagent call, `ollama.preload: true` to warm your default model at launch, and — when you've told it your VRAM budget — a launch-time warning with real numbers if a local lead and a local subagent can't both fit in memory.
> - 🔑 **API-key model auto-config** — on every launch, `scripts/sync-api-key-models.py` reads your `.env` and uncomments the matching cloud-model block in `config.yaml`, so the right models are enabled on first start with no manual editing. It only ever uncomments (never re-comments), skips a block whose models are already active, and no-ops when the key is absent. The auto-enabled models and their conditions:
>   - **`ANTHROPIC_API_KEY` present** → Claude **Fable 5**, **Opus 5**, **Opus 4.8**, **Sonnet 5**, **Sonnet 4.6**, **Haiku 4.5** (direct Anthropic API). Opus and Sonnet each ship their last 4.x alongside 5; Haiku and Fable ship only the latest.
>   - **`OPENROUTER_API_KEY` present** → Claude **Fable 5** (the flagship, for OpenRouter-only users — every other Claude is on the direct Anthropic block above), **Grok 4.6**, **GPT-5.6 Sol**, **GPT-5.3 Codex**, **Gemini 3.6 Flash**, **Llama 4 Maverick**, **MiniMax M3**, **Qwen3.8 Max**, **Kimi K3**, **Mistral Large 3**, **DeepSeek V4 Pro**, **GLM-5.3**, **Nemotron 3 Ultra** (all via OpenRouter). One flagship per big-name lab (a second only when the smaller model is acclaimed on its own — e.g. GPT-5.3 Codex).
>   - **A big name's own key present** → that lab's **fuller lineup on its own API**, exactly as `ANTHROPIC_API_KEY` does for Claude — so the flagship you can reach through OpenRouter is *also* reachable direct, with its cheaper siblings alongside it and no middleman: `OPENAI_API_KEY` → **GPT-5.6 Sol / GPT-5.3 Codex / GPT-5.6 Mini**, `XAI_API_KEY` → **Grok 4.6 / Grok 4.5 Fast**, `GEMINI_API_KEY` → **Gemini 3.6 Flash / 3.5 Flash-Lite / 3.1 Pro**, `DEEPSEEK_API_KEY` → **DeepSeek V4 Pro / V4 Flash**, `MOONSHOT_API_KEY` → **Kimi K3 / K2.6**, `DASHSCOPE_API_KEY` → **Qwen3.8 Max / Qwen3.7 Plus**, `MISTRAL_API_KEY` → **Mistral Large 3 / Medium 3.5 / Small 3**, `MINIMAX_API_KEY` → **MiniMax M3 / M2.7**, `ZAI_API_KEY` → **GLM-5.3 / GLM-5.2 Air**. Set both a lab's key and `OPENROUTER_API_KEY` and you get both copies, side by side and separately named. Only **Meta Llama** and **NVIDIA Nemotron** stay OpenRouter-only — neither ships a first-party consumer API.
> - 🔀 **Independent model per conversation** — every chat remembers its **own** model (and subagent model, mode, and reasoning effort), stored per-thread instead of in one shared setting. Run a free local Ollama model in one conversation and a cloud model in another, side by side — switching the model in one no longer flips the model in the others. Previously every chat that hadn't been explicitly pinned followed the last model picked *anywhere* (even across browser tabs, via the shared settings sync), which made running local and cloud models simultaneously impossible; now each conversation is isolated and new chats simply start from the configured default model.
> - 🗂️ **Browser-style keep-alive chat tabs** — drag conversations up into a tab strip and they stay **mounted and running in the background**: a tab you switch away from keeps streaming and keeps its scroll position, artifacts, and browser panel, instead of upstream's single pane that tears the previous chat down on every switch. The tab set is saved server-side per user, so it survives a browser restart — and even reopening the app on a different address (`localhost` vs. your LAN / Tailscale name).
> - 🚦 **Concurrent chats** — ask one conversation something slow, leave it, and prompt another one; both keep going. Leaving a chat used to **cancel** its run (the Gateway cancels a run when the browser disconnects unless told otherwise), so walking away from a long answer to write the next prompt killed the answer you walked away to wait for. Now a chat you leave *while it is still answering* is kept as a keep-alive tab and goes on streaming in the background, with a pulsing dot on its tab and a notification when it lands. With a **local Ollama model** the queue moves into the daemon: it answers `OLLAMA_NUM_PARALLEL` requests per model at a time (**1** by default), so raise it and set `ollama.num_parallel` to match — `make doctor` tells you where you stand.
> - 🕯️ **Gaslight mode** — edit **either half of a turn** and the conversation carries on as if those had always been the words. Edit your own message and it replays from there with the new wording; edit **the assistant's answer** and your text simply *becomes* what it said — nothing is re-generated, and whatever you send next is answered with those words standing in the history. The version you were reading is kept either way, and a `‹ 2/2 ›` switcher appears **on the edited message** to move between them. Upstream's **Branch** button forked each attempt into a *separate* chat, so trying three phrasings of one question left four entries in the sidebar with no clue which was which; here the alternatives are hidden threads and **one conversation stays one sidebar entry**, however many times you edit it — and the entry follows whichever version you are actually reading. Editing the very first message has nothing to fork from, so it simply starts a fresh version.
> - 🤖 **Generate a custom agent from your history** — instead of hand-writing a persona, point a model at past conversations or scheduled tasks and let it decide whether a *new* agent is even worth adding. It is allowed to say **no** — naming the existing agent that already covers the work — so your roster doesn't fill up with near-duplicates. When it does propose one you get an editable **SOUL.md** draft, and nothing is saved until you press **Create**; the analysis itself never writes an agent. An optional *what should this agent do?* box steers it toward a goal, and a **Refine** box adjusts the draft in place without regenerating it. On by default alongside the custom-agent API (**Agents → Generate from history**).
> - 🪃 **Model fallback chains** — when a model call fails for a reason worth retrying (the Ollama daemon is down, the context overflowed, the model turns out not to support tool calls, or the provider returns a 5xx), the turn degrades to the next model you listed instead of failing. Deliberate stops — you hit cancel, a spend cap fired, a guardrail refused — never fall back, and tokens are billed to whichever model actually answered, so your cost figures stay honest. Off until you configure a chain.
> - 🧭 **Cost-aware subagent routing** — a policy that sends delegated subtasks to the cheapest model that can actually do them, so the saving is the default instead of something you remember to set every session. A tool-free extraction can run on a local model for free while the lead stays on a frontier model. It never picks a model that can't do the job (no tool support, no vision, context window too small), your explicit per-conversation subagent choice always wins, and the subagent card shows which rule decided. Off until you write a policy.
> - 📱 **Installable on your phone, with notifications that arrive after you close it** — DeerFlow now ships a web app manifest and a service worker, so you can add it to your home screen and get a Web Push notification when a long run finishes, even with the browser closed. Background notifications need a secure origin (`localhost`, or your Tailscale HTTPS name); on a plain-HTTP LAN address the settings page says exactly that and tells you how to fix it, instead of silently doing nothing.
> - 🧩 **Per-thread subagent model dropdown** — in **Ultra mode**, a second model picker lets you route `task` subagents to a cheaper or local model instead of the lead model (defaults to "Follow lead").
> - 🔃 **Sortable, grouped model picker** — with a couple of dozen bundled models across premium-cloud, cheap-cloud, and local tiers, the flat list is hard to scan, so the dropdown can **sort by name or price** and **group by provider** in one click (each row's price is coloured; a discounted model shows list vs. promo). Remembered per browser, and the default stays config order so nothing moves until you opt in.
> - 💡 **Follow-up suggestions off by default** — the clickable follow-up-question chips make an extra model call after every answer, so they now default **off** to save cost. Turn them back on per-browser under **Settings → Suggestions**, where a dropdown also lets you pick which model generates them ("Follow workflow selection" by default, or any configured model — pick a cheap one to keep it cheap).
> - 📜 **The system prompt is visible and editable (Settings → System prompt)** — the instructions every run starts from are no longer a black box. The page shows the template in force, an **Edit** tab for changing it, and a **Preview** tab that renders it with every placeholder filled in — the exact text the lead agent receives, with a toggle for the Ultra-mode subagent block. Placeholders like `{skills_section}` are one-click insertable and validated on save, so a typo is refused with the offending name instead of breaking your next run; drop one deliberately and that section simply disappears from the prompt. Saved to `SYSTEM_PROMPT.md` beside your other DeerFlow state, applied on the next run with no restart, and **Reset to default** puts the built-in prompt back. Admin-gated (in the passwordless local setup, that is you).
> - 🧠 **Long-term memory off by default** — the agent no longer learns from or injects your saved memory until you opt in. Turn it on per-browser under **Settings → Memory** (the operator can still hard-disable it with `memory.enabled: false` in `config.yaml`, which greys out the toggle). When off, each run sends `memory_enabled: false` and the backend skips memory injection, extraction, and memory tools.
> - 💵 **Live cost overview in the conversation header** — the token counter next to a chat now shows an estimated **dollar (or other currency) cost**, priced from each model's `pricing:` block in `config.yaml`. It's **model-aware**: each run's per-model token split is billed at that model's own rate, so subagents on a cheaper or local model are costed correctly — hover the **?** for the note that models without a configured price (like local Ollama) count as $0, ignoring electricity. When the **memory** or **suggestions** features are on, their extra LLM calls get their own separate counters in the dropdown so you can see what each is quietly costing — and those two counters are **persisted** (a small `aux_usage.sqlite3` beside your other DeerFlow state), so they survive restarting the stack instead of resetting to zero. No pricing configured → the cost line simply hides.
> - 📈 **Price graph — what each step cost** — the same dropdown also plots the cost of every step of the conversation (a step = one user message and the answer to it), with a toggle between **each step** (columns) and the **running total** (a line). The headline figure says what the conversation has cost; the graph says *which turn* cost it — the question a thread that switches models mid-way actually raises. It is priced through the same code as the total, so the last cumulative point always equals the number printed right above it, and the y axis is anchored at zero so near-identical turns look near-identical. A turn run on an unpriced local model draws **no** column rather than a zero-height one — "nothing could price this turn" is a different claim from "this turn was free".
> - 🛑 **Spend caps in real money** — set `spend_budget` in `config.yaml` to a daily / weekly / monthly limit in your pricing currency and DeerFlow warns the agent as you approach it, then wraps the run up and refuses new ones once it is spent. Costed per model, so a premium lead with cheap or local subagents is billed correctly — and **unpriced local models count as $0, so a fully local session is never blocked**. The chat header shows what is left.
> - 🧾 **Spend page** — a **Spend** entry in the sidebar answers "where did my money go this month", broken down by model, by conversation, and by feature (conversation / memory / suggestions) over the last 7, 30, or 90 days.
> - 🔓 **Passwordless by default (local)** — the local stack (`make dev` / `make start`) starts with no login wall: every request resolves to the built-in `default` admin, so the app — and other devices on your LAN — reach it with no username/password. It's opt-out (`DEER_FLOW_AUTH_DISABLED=0` in `.env` restores the email/password login) and self-disabling in production (`DEER_FLOW_ENV`/`ENVIRONMENT` = `prod` keeps auth on regardless).
> - 🛡️ **Deployment exposure check** — passwordless auth, multi-user-mode-off, and a non-loopback `BIND_HOST` are each defensible alone but together decide who can reach your instance and as whom. `make doctor` (and the end of `make up` / `make dev`) computes and prints that combined posture, so you learn you've exposed a passwordless instance from your own tooling rather than from a stranger. Diagnosis only — it changes no default.
> - 🎬 **Reduced motion by default** — decorative and continuous animations are disabled by default (and honor the OS `prefers-reduced-motion` setting); it's a per-browser preference you can flip back on.
> - 👥 **Multi-user mode toggle (Settings → Account)** — on by default (each login only sees its own conversations). Turn it off — after a confirmation — to combine every conversation into one shared workspace, so all histories are visible no matter which login or device created them (handy after going passwordless, when old per-account chats are stranded under different ids). Server-wide, admin-only, and reversible; while off, anyone who can reach the server sees all conversations, so keep it to a trusted machine.
> - 🦊 **Camoufox as the default `web_fetch`** — a local, key-less, JavaScript-capable browser backend replaces the Jina cloud reader as the default. The package and its browser install automatically on every launch path (no API key).
> - 🔎 **Self-hosted SearXNG as the default `web_search`** — a bundled metasearch backend, auto-provisioned at startup (an existing reachable instance is reused, otherwise the bundled container starts). No search API key required.
> - 🔄 **Self-updating browser & search** — the two things the repo installs for itself, the Camoufox browser and the bundled SearXNG image, refresh themselves instead of silently rotting after first install: throttled once-a-day on launch (opt out with `DEER_FLOW_AUTO_UPDATE=0`), or via a `systemd --user` timer (`make auto-update-install`) that also fires on boot so a machine that was off at the daily slot catches up. `make auto-update` runs it on demand; every path is idempotent and best-effort.
> - 📄 **PDF / Office uploads that just work** — `pymupdf4llm` is bundled and converted files are written under both name conventions, so PDF / DOCX / PPTX / XLSX uploads are reliably readable by the agent (enable with `uploads.auto_convert_documents: true`).
> - 🐳 **Full clone-and-debug sandbox runs** — one-command per-thread containers, host-reachable ports, native debuggers (`gdb` / `strace`), longer command timeouts, and a `repo-runner` skill that encodes clone → install → run → debug.
> - 💾 **Whole-instance backup & restore** — `make backup` snapshots all of `.deer-flow` as one timestamped archive (memory, threads, chat tabs, settings, uploads, databases, custom skills) and `make restore` puts it back (refusing while the stack is running). Credentials are excluded unless you pass `INCLUDE_SECRETS=1`. A personal AI accumulates months of state on one machine with no redundancy — this is the redundancy.
> - 🩹 **Arch / CachyOS fixes** — an nginx temp-path patch and bundled `langchain-ollama` so `make dev` works for non-root users out of the box.
>
> See [`FORK.md`](./FORK.md) for details, cost analysis, and disclaimers. Upstream is the source of truth for everything else.

---

# 🦌 DeerFlow - 2.0

English | [中文](./README_zh.md) | [日本語](./README_ja.md) | [Français](./README_fr.md) | [Русский](./README_ru.md)

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](./backend/pyproject.toml)
[![Node.js](https://img.shields.io/badge/Node.js-22%2B-339933?logo=node.js&logoColor=white)](./Makefile)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

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

DeerFlow has newly integrated the intelligent search and crawling toolset independently developed by BytePlus--[InfoQuest (supports free online experience)](https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest)

<a href="https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest" target="_blank">
  <img
    src="https://sf16-sg.tiktokcdn.com/obj/eden-sg/hubseh7bsbps/20251208-160108.png"   alt="InfoQuest_banner"
  />
</a>

---

## Table of Contents

- [🦌 DeerFlow - 2.0](#-deerflow---20)
  - [Official Website](#official-website)
  - [Coding Plan from ByteDance Volcengine](#coding-plan-from-bytedance-volcengine)
  - [InfoQuest](#infoquest)
  - [Table of Contents](#table-of-contents)
  - [One-Line Agent Setup](#one-line-agent-setup)
  - [Quick Start](#quick-start)
    - [Configuration](#configuration)
    - [Running the Application](#running-the-application)
      - [Deployment Sizing](#deployment-sizing)
      - [Option 1: Docker (Recommended)](#option-1-docker-recommended)
      - [Option 2: Local Development](#option-2-local-development)
    - [Advanced](#advanced)
      - [Sandbox Mode](#sandbox-mode)
      - [MCP Server](#mcp-server)
      - [IM Channels](#im-channels)
      - [LangSmith Tracing](#langsmith-tracing)
      - [Langfuse Tracing](#langfuse-tracing)
      - [Monocle Tracing](#monocle-tracing)
      - [Using Multiple Providers](#using-multiple-providers)
  - [From Deep Research to Super Agent Harness](#from-deep-research-to-super-agent-harness)
  - [Core Features](#core-features)
    - [Skills \& Tools](#skills--tools)
      - [Claude Code Integration](#claude-code-integration)
    - [Session Goals](#session-goals)
    - [Manual Context Compaction](#manual-context-compaction)
    - [Sub-Agents](#sub-agents)
    - [Generating Agents From Your History](#generating-agents-from-your-history)
    - [Sandbox \& File System](#sandbox--file-system)
    - [Context Engineering](#context-engineering)
    - [System Prompt](#system-prompt)
    - [Long-Term Memory](#long-term-memory)
    - [Concurrent Chats](#concurrent-chats)
  - [Recommended Models](#recommended-models)
  - [Embedded Python Client](#embedded-python-client)
  - [Scheduled Tasks](#scheduled-tasks)
  - [Terminal Workbench (TUI)](#terminal-workbench-tui)
  - [Documentation](#documentation)
  - [⚠️ Security Notice](#️-security-notice)
    - [Improper Deployment May Introduce Security Risks](#improper-deployment-may-introduce-security-risks)
    - [Security Recommendations](#security-recommendations)
  - [Contributing](#contributing)
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

### Configuration

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

   Pick **Anthropic** or **OpenRouter** and the wizard enables a whole set of latest models from that one key — Anthropic writes Fable 5 / Opus 5 / Opus 4.8 / Sonnet 5 / Sonnet 4.6 / Haiku 4.5, and OpenRouter writes Claude Fable 5 plus the xAI / OpenAI / Google flagships and a spread of open alternatives (MiniMax, Mistral, DeepSeek, Kimi, GLM, Qwen). If you configure by hand instead (`make config`), the same ready-to-uncomment blocks are at the top of `config.example.yaml` under `models:` — uncomment the one matching your key.

   The wizard also lets you configure an optional web search provider, or skip it for now.

   **Tools out of the box**: the defaults are chosen so the agent has its full toolset from the first launch — web search (SearXNG, key-less), web fetch (Camoufox local browser, key-less), image search, file read/write tools, and bash. When Docker (or Apple Container) is installed, both `make setup` and `make config` default to the **container sandbox** with bash enabled, so git/clone and program runs work immediately; without a container runtime the local sandbox is used and host bash stays off (a security default — enable the container sandbox later with `make sandbox-enable MODE=container`). If an older `config.yaml` is missing default tools (for example the agent reports it has no web_search/web_fetch/bash), `make config-upgrade` backfills the missing entries without touching your existing ones, and `make doctor` names exactly which tools are absent.

   Run `make doctor` at any time to verify your setup and get actionable fix hints.
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
   contents.

   > **Advanced / manual configuration**: If you prefer to edit `config.yaml` directly, run `make config` instead to copy the full template. See `config.example.yaml` for the complete reference including CLI-backed providers (Codex CLI, Claude Code OAuth), OpenRouter, Responses API, subagent runtime caps such as `subagents.max_total_per_run`, and more.

   Optional per-model pricing must use one currency across all priced models.
   DeerFlow disables Console cost estimates when currencies are mixed rather
   than presenting an invalid aggregate.

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

   To route OpenAI models through `/v1/responses`, keep using `langchain_openai:ChatOpenAI` and set `use_responses_api: true` with `output_version: responses/v1`.

   For vLLM 0.19.0, use `deerflow.models.vllm_provider:VllmChatModel`. For Qwen-style reasoning models, DeerFlow toggles reasoning with `extra_body.chat_template_kwargs.enable_thinking` and preserves vLLM's non-standard `reasoning` field across multi-turn tool-call conversations. Legacy `thinking` configs are normalized automatically for backward compatibility. If the endpoint reports a cumulative usage snapshot on every streaming chunk, set `cumulative_stream_usage: true` so DeerFlow converts those snapshots into per-chunk deltas; the option is disabled by default and leaves usage unchanged when a stable completion id is unavailable. Reasoning models may also require the server to be started with `--reasoning-parser ...`. If your local vLLM deployment accepts any non-empty API key, you can still set `VLLM_API_KEY` to a placeholder value.

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

   - Codex CLI reads `~/.codex/auth.json`
   - Claude Code accepts `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_CREDENTIALS_PATH`, or `~/.claude/.credentials.json`
   - ACP agent entries are separate from model providers — if you configure `acp_agents.codex`, point it at a Codex ACP adapter such as `npx -y @zed-industries/codex-acp`
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

   `mcode` must be on the Gateway process's `PATH`; installing it only on the Docker host does not make it available inside the Gateway container. DeerFlow invokes it through `invoke_acp_agent` in a per-thread ACP workspace and forwards enabled MCP servers. Keep `auto_approve_permissions: false` for untrusted tasks; enable it only when MCode must edit files or run commands and you trust the task.
   - On macOS, export Claude Code auth explicitly if needed:

   ```bash
   eval "$(python3 scripts/export_claude_code_oauth.py --print-export)"
   ```

   API keys can also be set manually in `.env` (recommended) or exported in your shell:

   ```bash
   OPENAI_API_KEY=your-openai-api-key
   TAVILY_API_KEY=your-tavily-api-key
   ```

   </details>

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

To switch to the Jina cloud reader instead (fish):

```fish
make config            # pick "jina" when prompted (or edit config.yaml)
```

Because Camoufox is the default, **every launch path installs it end-to-end automatically** — the `camoufox` package (via the auto-detected uv extra) and the browser binaries (a large one-time download): local `make dev` / `make start`, Docker dev (`make docker-start`), and Docker prod (`make up`, baked into the image at build). `make fetch-browser` remains available to pre-download the browser by hand. The step is idempotent and best-effort: an already-present browser is a no-op, and a failed download (e.g. offline) never blocks startup.

Camoufox reuses a single headless browser across requests, renders JS-heavy pages, and returns readable markdown. If the browser somehow isn't downloaded yet, the tool result tells the agent exactly what to do (`run make fetch-browser`) instead of failing opaquely. A `web_fetch` of a private GitHub URL returns a hint to use git in the sandbox rather than a bare 404.

#### Clone-and-run a repo in the sandbox

To have the agent take a GitHub link, clone it, install its requirements, and run or debug the program with admin rights, use the containerized sandbox in **per-thread container mode** (the agent runs as root inside a Docker container per conversation, with `/mnt/user-data` host-backed so files and outputs surface normally):

```fish
make sandbox-enable MODE=container   # writes an AioSandboxProvider block (no base_url)
```

Then restart the app. For a private repo, set `GITHUB_TOKEN` in `.env` (scoped to the repos you want) and DeerFlow configures git inside the container so plain `git clone https://github.com/owner/repo.git` works without the token ever appearing in URLs or logs. Useful `config.yaml → sandbox` knobs for this workflow:

- `bash_command_timeout` / `request_timeout` — raise both together for long installs and builds (a big `pip install` or `cargo build` no longer stops at the old 600s ceiling).
- `expose_ports: [8000]` — publish a port so a dev server the agent starts is reachable at `localhost:8000` from your own browser.
- `extra_capabilities: [SYS_PTRACE]` — allow `gdb`/`strace` to attach for native debugging.
- `idle_timeout` — keep a warmed-up debug environment alive longer between the agent's turns.

The bundled **`repo-runner` skill** walks the agent through the whole loop (clone → detect toolchain → install in an isolated venv → run/debug → report the exact commands). Invoke it with `/repo-runner <github-url and what to do>`.

### Running the Application

#### Deployment Sizing

Use the table below as a practical starting point when choosing how to run DeerFlow:

| Deployment target | Starting point | Recommended | Notes |
|---------|-----------|------------|-------|
| Local evaluation / `make dev` | 4 vCPU, 8 GB RAM, 20 GB free SSD | 8 vCPU, 16 GB RAM | Good for one developer or one light session with hosted model APIs. `2 vCPU / 4 GB` is usually not enough. |
| Docker development / `make docker-start` | 4 vCPU, 8 GB RAM, 25 GB free SSD | 8 vCPU, 16 GB RAM | Image builds, bind mounts, and sandbox containers need more headroom than pure local dev. |
| Long-running server / `make up` | 8 vCPU, 16 GB RAM, 40 GB free SSD | 16 vCPU, 32 GB RAM | Preferred for shared use, multi-agent runs, report generation, or heavier sandbox workloads. |

- These numbers cover DeerFlow itself. If you also host a local LLM, size that service separately.
- Linux plus Docker is the recommended deployment target for a persistent server. macOS and Windows are best treated as development or evaluation environments.
- If CPU or memory usage stays pinned, reduce concurrent runs first, then move to the next sizing tier.

#### Option 1: Docker (Recommended)

**Development** (hot-reload, source mounts):

```bash
make docker-init    # Pull sandbox image (only once or when image updates)
make docker-start   # Start services (auto-detects sandbox mode from config.yaml)
make docker-logs    # View logs
```

`make docker-start` starts `provisioner` only when `config.yaml` uses provisioner mode (`sandbox.use: deerflow.community.aio_sandbox:AioSandboxProvider` with `provisioner_url`).

Docker builds use the upstream `uv` registry by default. If you need faster mirrors in restricted networks, export `UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` and `NPM_REGISTRY=https://registry.npmmirror.com` before running `make docker-init` or `make docker-start`.

Local AIO sandbox control traffic is always direct: loopback/private addresses,
single-label cluster hosts, and Docker/Podman internal hostnames do not inherit
`HTTP_PROXY` or `HTTPS_PROXY`. External sandbox FQDNs and public IPs still
honor environment proxy settings.

Backend processes automatically pick up `config.yaml` changes on the next config access, so model metadata updates do not require a manual restart during development.
The checkpoint storage settings `database.checkpoint_channel_mode` and
`database.checkpoint_delta.snapshot_frequency` (default `10`) are exceptions:
both are frozen when the process first builds an agent (including through
`DeerFlowClient`) and require a process restart to change safely.

The optional `database.checkpoint_cache` section (delta channel mode only)
caches materialized checkpoint histories: `type` is `memory` (default) or
`redis`, and `max_entries: 0` disables the cache. The `redis` backend is
Gateway/async-only; the sync TUI/embedded path supports `memory` only. The
cache is performance-only — results are identical with it disabled — so it is
never frozen and workers sharing one checkpoint database may safely run
different cache settings.

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

For persistent deployments, configure `database.backend` as `sqlite` or
`postgres`. The selected backend is shared by the LangGraph checkpointer,
LangGraph Store, and DeerFlow application data. The deprecated `checkpointer`
section, when present, overrides the first two for backward compatibility.

The unified nginx endpoint is same-origin by default and does not emit browser CORS headers. If you run a split-origin or port-forwarded browser client, set `GATEWAY_CORS_ORIGINS` to comma-separated exact origins such as `http://localhost:3000`; the Gateway then applies the CORS allowlist and matching CSRF origin checks.

Browser login uses `HttpOnly` session cookies. The login page offers a "keep me signed in" option that extends the browser session when the request is HTTPS (including trusted `X-Forwarded-Proto: https`) or localhost HTTP. The localhost exception uses the direct request `Host` and ignores forwarded host headers. Public HTTP deployments, including many temporary sandbox URLs, fall back to session cookies by default. DeerFlow never stores the password in browser storage; the UI may remember only the email address.

DeerFlow still uses `Forwarded` / `X-Forwarded-*` headers to recover the browser-facing scheme and origin behind a proxy. The bundled nginx sets `X-Forwarded-Proto`, but preserves an upstream HTTPS value and does not overwrite every forwarded header. Configure the outer trusted proxy to replace or strip client-supplied forwarding headers before traffic reaches DeerFlow.

> [!IMPORTANT]
> The Gateway still owns active run tasks in process, so production defaults to a single Gateway worker (`GATEWAY_WORKERS=1`). Multi-worker deployments require Postgres, the Redis stream bridge (`stream_bridge.type: redis`), `run_ownership.heartbeat_enabled: true`, and `run_events.backend: db`; process-local memory/JSONL event stores cannot enforce singleton delivery receipts across workers. The bridge shares SSE delivery and bounded `Last-Event-ID` replay across workers. When a valid reconnect cursor has been trimmed, or a subscriber that already established an empty-stream wait falls behind before its first delivery, Memory and Redis emit a machine-readable SSE `gap` event instead of silently returning a partial replay; the Web UI reloads durable thread/event state and resumes from the retained tail. Lease reconciliation marks runs from dead workers as errors, persists their delivery receipts, publishes the terminal stream marker, schedules retained-stream cleanup, and updates the affected thread status. SSE and `/wait` consumers also refresh durable status on heartbeats as a fallback if terminal publication fails. Malformed Redis reconnect IDs live-tail new events instead of replaying the retained buffer, and the rolling retained-buffer TTL (`stream_ttl_seconds`) remains a cleanup safety net rather than a run timeout. IM channel state and other process-local services still need their own multi-worker coordination.
>
> Run cancellation may land on any Gateway worker. A non-owning worker now persists the interrupt or rollback request for the live owner, which observes it during lease renewal and performs the normal cancellation flow; load-balancer routing alone no longer produces a 409. The first accepted action wins even if a retry lands on the owner, and accepted cancellation competes atomically with owner completion. Dead owners still follow lease takeover and orphan recovery. Cancellation latency is therefore bounded by the lease heartbeat interval.
>
> With lease heartbeat enabled, a transient RunStore renewal error is retried only until the last confirmed lease expires; the stale worker then cancels local execution and suppresses checkpoint, completion-hook, delivery-receipt, and thread-status finalization. A remote tool side effect already in flight may still be outside local cancellation.
>
> Reconciliation uses an atomic takeover claim that re-checks the lease after candidate selection, so a successful owner renewal wins over orphan recovery and only one reconciler can report a run as recovered. When multiple Gateway workers share the Docker/AIO or E2B sandbox backend, also configure `sandbox.ownership.type: redis`; E2B uses the leases during background startup and periodic reconciliation so duplicate/orphan cleanup cannot terminate a live peer's sandbox.

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed Docker development guide.

#### Option 2: Local Development

If you prefer running services locally:

Prerequisite: complete the "Configuration" steps above first (`make setup`). If no `config.yaml` exists, the first `make dev` / `make start` seeds one from `config.example.yaml` automatically (the same first-run seeding the Docker launch paths do) and the API-key auto-config enables the model block matching whatever provider key is in your environment / `.env` — so a fresh checkout starts without a separate `make config` step, though `make setup` still gives the best guided setup. Set `DEER_FLOW_PROJECT_ROOT` to define that root explicitly, or `DEER_FLOW_CONFIG_PATH` to point at a specific config file. Runtime state defaults to `.deer-flow` under the project root and can be moved with `DEER_FLOW_HOME`; skills default to `skills/` under the project root and can be moved with `DEER_FLOW_SKILLS_PATH`. Run `make doctor` to verify your setup before starting.
On Windows, run the local development flow from Git Bash. Native `cmd.exe` and PowerShell shells are not supported for the bash-based service scripts, and WSL is not guaranteed because some scripts rely on Git for Windows utilities such as `cygpath`.

1. **Check prerequisites**:
   ```bash
   make check  # Verifies Node.js 22+, pnpm, uv, nginx
   ```

   The local `make check`, `make install`, `make dev`, and `make start` entry points use a direct `pnpm`/`pnpm.cmd` executable when available and otherwise fall back to `corepack pnpm`. The shared runner and diagnostics resolve repository paths absolutely, so these checks work regardless of the caller's current directory. Corepack runs from `frontend/`, so it honors the `packageManager` version pinned in `frontend/package.json`; enabling a global pnpm shim is not required.

2. **Install dependencies**:
   ```bash
   make install  # Install backend + frontend dependencies + pre-commit hooks
   ```

3. **(Optional) Pre-pull sandbox image**:
   ```bash
   # Recommended if using Docker/Container-based sandbox
   make setup-sandbox
   ```

4. **(Optional) Load sample memory data for local review**:
   ```bash
   python scripts/load_memory_sample.py
   ```
   This copies the sample fixture into the default local runtime memory file so reviewers can immediately test `Settings > Memory`.
   See [backend/docs/MEMORY_SETTINGS_REVIEW.md](backend/docs/MEMORY_SETTINGS_REVIEW.md) for the shortest review flow.

5. **Start services**:
   ```bash
   make dev
   ```

6. **Access**: http://localhost:2026

Local services always use their internal ports (`8001`, `3000`, and `2026`).
The root `.env` variable `PORT` configures only the published Docker ingress;
it does not change the Next.js port used by `make dev`.

#### Startup Modes

DeerFlow runs the agent runtime inside the Gateway API. Development mode enables hot-reload; production mode uses a pre-built frontend.

| | **Local Foreground** | **Local Daemon** | **Docker Dev** | **Docker Prod** |
|---|---|---|---|---|
| **Dev** | `./scripts/serve.sh --dev`<br/>`make dev` | `./scripts/serve.sh --dev --daemon`<br/>`make dev-daemon` | `./scripts/docker.sh start`<br/>`make docker-start` | — |
| **Prod** | `./scripts/serve.sh --prod`<br/>`make start` | `./scripts/serve.sh --prod --daemon`<br/>`make start-daemon` | — | `./scripts/deploy.sh`<br/>`make up` |

| Action | Local | Docker Dev | Docker Prod |
|---|---|---|---|
| **Stop** | `./scripts/serve.sh --stop`<br/>`make stop` | `./scripts/docker.sh stop`<br/>`make docker-stop` | `./scripts/deploy.sh down`<br/>`make down` |
| **Restart** | `./scripts/serve.sh --restart [flags]` | `./scripts/docker.sh restart` | — |

Gateway owns `/api/langgraph/*` and translates those public LangGraph-compatible paths to its native `/api/*` routers behind nginx.

#### LangGraph Studio (Optional)

The default `make dev` topology uses DeerFlow's Gateway-embedded runtime and
does not require LangGraph Studio. To inspect and test the registered lead-agent
graph with the standalone development server, run the command from `backend/`
so the CLI discovers `langgraph.json`:

```bash
cd backend
uv run langgraph dev --allow-blocking
```

The command prints the local API and Studio UI URLs. This in-memory server is
for development and testing only. The flag permits DeerFlow's synchronous
configuration and graph-factory setup during local Studio requests; it must not
be treated as a production-server setting. Local Studio authentication is
handled automatically, so the connection does not require custom headers. Use
DeerFlow's documented production startup modes or a supported LangSmith
deployment for production workloads. Assistant ownership and provenance in this
standalone mode are server-owned: Studio can discover registered graphs and the
assistants it creates, and normal assistant-version selection remains available.
Before the locked local runtime loads its persisted development store, DeerFlow
repairs legacy assistant rows and version history so historical client metadata
cannot restore server privileges or be discarded by the runtime's startup
cleanup. Keep the backend dependencies synchronized with `uv sync`; this
compatibility path requires the declared LangGraph runtime versions and logs a
warning if the persisted-store contract no longer matches its expectations.
The documented command uses LangGraph's file-based custom-app loader, which is
also covered directly by DeerFlow's regression tests.

For workflows that invoke `backend/langgraph.json` through LangGraph Studio or
a direct LangGraph Server, DeerFlow consumes the authenticated identity
published by that runtime and uses it for custom-agent configuration/SOUL, user
skills and skill policy, uploads, thread data, and memory reads/writes. This
keeps authenticated runs out of the shared `default` filesystem bucket, and the
server-owned identity takes precedence over ordinary client-supplied `user_id`
values. External identities such as email addresses are mapped to stable,
collision-resistant directory-safe user IDs before accessing DeerFlow storage.
The default DeerFlow service topology remains the Gateway-embedded runtime
described above.

Gateway runs automatically enforce native delivery for artifacts created or modified under `/mnt/user-data/outputs`: `present_files` must present at least one output produced by the current run, and the terminal `run.delivery` receipt must be durably recorded. Virtual artifact paths are resolved within the same authenticated user and thread scope that produced the output before the output-directory boundary is validated. Runs that do not produce output artifacts keep ordinary conversational behavior.

DeerFlow's built-in custom events are available through both LangGraph streaming interfaces: native clients can continue subscribing to `stream_mode="custom"`, while callback-based integrations can consume the same payloads as `on_custom_event` records from `astream_events(version="v2")`. The callback event name matches the payload's `type` field.

#### Web Search Service (SearXNG)

The default `web_search` tool is backed by a bundled, self-hosted [SearXNG](https://github.com/searxng/searxng) metasearch instance — no API key, and queries go straight from your machine to the upstream engines instead of through a third-party search API.

Every launch path resolves the instance automatically at startup (via `scripts/detect_searxng.py`): if a SearXNG with the JSON API enabled is already running on this machine (checked on ports `8088` and `8080`, or wherever `DEER_FLOW_SEARXNG_BASE_URL` points), the stack reuses it; otherwise it starts the bundled `deer-flow-searxng` container. If `config.yaml` doesn't use the SearXNG provider, nothing is started.

- **Docker stacks** (`make up`, `make docker-start`): an existing host instance is only reused when containers can actually reach it — on Linux it must listen beyond loopback (Docker Desktop proxies loopback through `host.docker.internal`); otherwise the bundled service starts. The Gateway reaches the bundled service in-network at `http://searxng:8080` (wired via `DEER_FLOW_SEARXNG_BASE_URL`), and it is also published on `127.0.0.1:8088` for debugging — loopback only, never on the LAN.
- **Host-run** (`make dev`, `make start`): the launcher reuses a running instance or starts the bundled container itself (requires Docker; without it, a warning explains the options). `make searxng` / `make searxng-stop` remain for manual control; note `make stop` leaves the container running. It serves `http://localhost:8088`, which matches the default `base_url` in `config.yaml`.
- **Instance settings** live in [docker/searxng/settings.yml](docker/searxng/settings.yml): the JSON API is enabled (required by DeerFlow's client) and the bot limiter is disabled for the private in-network instance. Set `SEARXNG_SECRET` in `.env` before exposing the instance beyond localhost.
- **Bring your own instance**: set `DEER_FLOW_SEARXNG_BASE_URL` in `.env` to skip auto-detection and point the Gateway at any reachable SearXNG (its `search.formats` must include `json`).
- **No Docker / prefer zero dependencies?** Swap the active `web_search` entry in `config.yaml` back to the commented DuckDuckGo provider — no local service required.

#### Docker Production Deployment

`deploy.sh` supports building and starting separately:

```bash
# One-step (build + start)
deploy.sh

# Two-step (build once, start later)
deploy.sh build              # build all images
deploy.sh start              # start pre-built images

# Stop
deploy.sh down
```

> **Applying config-only changes (e.g. `BIND_HOST`, `PORT`):** the bare
> `deploy.sh` (`make up`) rebuilds every image, which is slow and unnecessary
> when you only edited `.env` or `config.yaml`. Prefer `deploy.sh start`
> (`make up-start`) — it restarts the pre-built images with the new environment,
> no rebuild. Only re-run `deploy.sh build` (or `make up`) after a code or
> dependency change.

### Advanced
#### Sandbox Mode

DeerFlow supports multiple sandbox execution modes:
- **Local Execution** (runs sandbox code directly on the host machine)
- **Docker Execution** (runs sandbox code in isolated Docker containers)
- **Docker Execution with Kubernetes** (runs sandbox code in Kubernetes pods via provisioner service)

For Docker development, service startup follows `config.yaml` sandbox mode. In Local/Docker modes, `provisioner` is not started.

See the [Sandbox Configuration Guide](backend/docs/CONFIGURATION.md#sandbox) to configure your preferred mode.

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
   *Repository access* to just the repos the agent needs and grant only the
   **Contents** repository permission (read-only unless the agent must push).
   Put it in `.env` as `GITHUB_TOKEN=...` (see `.env.example`).
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
fine-grained, selected repositories, Contents permission only — rotate it
periodically, and never reuse a classic all-repos PAT here.

#### MCP Server

DeerFlow supports configurable MCP servers and skills to extend its capabilities.
For HTTP/SSE MCP servers, OAuth token flows are supported (`client_credentials`, `refresh_token`).
For stdio MCP servers, per-tool call timeouts can be configured with `tool_call_timeout`; durable background-task calls honor the same setting for HTTP/SSE servers as well.
MCP tool names are prefixed with `<server_name>_` by default to prevent collisions across servers. If a server already namespaces its own tools, set `tool_name_prefix: false` on that server in `extensions_config.json` to keep the original names. Disable the prefix only when the resulting names remain unique across all enabled servers.
Settings > Tools updates one MCP server at a time: an invalid stdio command on one server no longer blocks toggling another, while enabling that invalid server remains protected by the command allowlist and surfaces the backend validation message in the UI.
Targeted updates accept both DeerFlow's `type` field and the MCP-spec `transport` field for SSE/HTTP servers.
Runtime MCP and skill updates replace `extensions_config.json` atomically, so an interrupted write cannot leave the shared configuration truncated or partially written.
MCP routing hints can also prefer a specific MCP tool for matching requests without forbidding other tools. When `tool_search` defers MCP schemas, matching routing metadata can auto-promote up to `tool_search.auto_promote_top_k` deferred schemas before the model call.

OpenViking users can register the official Streamable HTTP endpoint at `/mcp`
with an owner-bound USER API key. The native `forget` tool is exposed for
capability parity; deletion is irreversible, so it should be called only after
explicit user confirmation. DeerFlow does not enforce that confirmation. This
explicit, model-selected MCP tool path can run alongside the separate automatic
OpenViking memory backend; it does not replace automatic turn capture or recall. See the
[OpenViking MCP tools configuration](backend/docs/MCP_SERVER.md#openviking-mcp-tools).

The Gateway can adapt an MCP server's ordinary `submit` / `status` / `cancel` tools into durable background tasks. The Agent sees only the configured submit tool and a DeerFlow-local task ID; remote IDs are persisted before the submit call returns, while status and cancel stay internal to the runtime. Polling uses cross-worker leases, exponential retry backoff, scoped MCP sessions, bounded result storage, and restart recovery. A status-tool `isError` is retained as a bounded diagnostic and retried; servers report a permanent remote-task outcome through a normal structured result with `status: "failed"`. Remote poll hints are finite positive numbers capped at 24 hours, artifact-reference JSON is limited to 64 KiB, and task/server identifiers are validated against their durable SQL column limits before persistence. Input-required and terminal updates wake the current chat through idempotent Agent runs, while `list_background_tasks` and `cancel_background_task` let the Agent manage tasks without asking users for remote handles. Current-thread tasks are available through `GET /api/threads/{thread_id}/mcp-tasks`, its detail endpoint, and `POST /api/threads/{thread_id}/mcp-tasks/{task_id}/cancel`; when the task runtime actually starts, the Web UI exposes the same safe local view from the chat header with live status refresh, cancellation, and on-demand result, artifact, input-request, status-error, and cancellation-retry details. Default-disabled and memory-backend deployments hide that UI and do not poll the task endpoints. A failed remote cancellation remains queued with backoff, and its latest bounded error and attempt count stay visible in the expanded task card. Enable `mcp_tasks` in `config.yaml`, configure `task_toolsets` with exact raw tool names in `extensions_config.json`, and use a SQL database backend (`sqlite` or `postgres`). Task-enabled server connection, authentication, interceptor, timeout, or binding changes require a Gateway restart so Agent tool discovery and background calls cannot use different configuration versions. `input_required` is notification-only for now: DeerFlow can display the request but cannot yet submit the user's answer back to the remote task.

Notification launch and failed Agent-run deliveries use capped exponential backoff with a visible attempt count and stop after five failed attempts. A permanently rejected target such as a deleted chat is dead-lettered immediately instead of retried forever or recreated. Cancellation endpoints return after durably recording the request; the background service owns the potentially slow remote MCP call and its retry schedule.

Notification runs keep their trusted delivery instruction separate from the framed, untrusted remote event payload. The process-started task runtime—not a hot config read—controls whether the task-management tools are exposed, so changing `mcp_tasks` requires a Gateway restart. When a skill's `allowed-tools` policy is active, `list_background_tasks` and `cancel_background_task` must be declared explicitly like other business tools.
See the [MCP Server Guide](backend/docs/MCP_SERVER.md) for detailed instructions.

Security: pass per-request MCP credentials only through `config.context.secrets`;
credentials must never be placed in either run metadata surface
(`metadata.auth_token` or `config.metadata.auth_token`). See [MCP credential migration and cleanup](backend/docs/MCP_SERVER.md#migrating-legacy-mcp-credentials)
for the supported interceptor flow and the required rotation and retained-copy
cleanup when migrating from legacy metadata credentials.

#### IM Channels

DeerFlow supports receiving tasks from messaging apps. Channels auto-start when configured — no public IP required for any of them.

DeerFlow can also expose user-owned IM channel connections in the workspace UI. When `channel_connections` is enabled, logged-in users can bind Telegram, Slack, Discord, Feishu/Lark, DingTalk, WeChat, WeCom, or Buzz from the sidebar / Settings > Channels. It reuses the existing outbound `channels.*` transports, so no public IP or provider callback URL is required. Incoming IM messages then run under the connected DeerFlow user account. See [IM Channel Connections](backend/docs/IM_CHANNEL_CONNECTIONS.md) for setup and security notes.

| Channel | Transport | Difficulty |
|---------|-----------|------------|
| Telegram | Bot API (long-polling) | Easy |
| Slack | Socket Mode | Moderate |
| Feishu / Lark | WebSocket | Moderate |
| WeChat | Tencent iLink (long-polling) | Moderate |
| WeCom | WebSocket | Moderate |
| DingTalk | Stream Push (WebSocket) | Moderate |
| Buzz | Nostr relay (WebSocket, NIP-42) | Moderate |

**Configuration in `config.yaml`:**

```yaml
channels:
  # LangGraph-compatible Gateway API base URL (default: http://localhost:8001/api)
  langgraph_url: http://localhost:8001/api
  # Gateway API URL (default: http://localhost:8001)
  gateway_url: http://localhost:8001

  # Maximum queued or provider-reserved inbound messages (default: 1000)
  inbound_queue_maxsize: 1000
  # Fixed number of long-lived inbound handler workers (default: 5)
  max_concurrency: 5
  # Seconds to drain accepted work before cancelling active handlers (default: 3)
  shutdown_grace_period_seconds: 3

  # Optional: global session defaults for all mobile channels
  session:
    assistant_id: lead_agent  # or a custom agent name; custom agents are routed via lead_agent + agent_name
    config:
      recursion_limit: 100
    context:
      thinking_enabled: true
      is_plan_mode: false
      subagent_enabled: false

  feishu:
    enabled: true
    app_id: $FEISHU_APP_ID
    app_secret: $FEISHU_APP_SECRET
    # domain: https://open.feishu.cn       # China (default)
    # domain: https://open.larksuite.com   # International

  wecom:
    enabled: true
    bot_id: $WECOM_BOT_ID
    bot_secret: $WECOM_BOT_SECRET

  slack:
    enabled: true
    bot_token: $SLACK_BOT_TOKEN     # xoxb-...
    app_token: $SLACK_APP_TOKEN     # xapp-... (Socket Mode)
    allowed_users: []               # empty = allow all

  telegram:
    enabled: true
    bot_token: $TELEGRAM_BOT_TOKEN
    # Optional: render final Markdown replies as Telegram Rich Messages.
    rich_messages: false
    allowed_users: []               # empty = allow all

  wechat:
    enabled: false
    bot_token: $WECHAT_BOT_TOKEN
    ilink_bot_id: $WECHAT_ILINK_BOT_ID
    qrcode_login_enabled: true      # optional: allow first-time QR bootstrap when bot_token is absent
    allowed_users: []               # empty = allow all
    polling_timeout: 35             # timing values must be positive finite seconds
    polling_retry_delay: 5
    qrcode_poll_interval: 2
    qrcode_poll_timeout: 180
    state_dir: ./.deer-flow/wechat/state
    max_inbound_image_bytes: 20971520
    max_outbound_image_bytes: 20971520
    max_inbound_file_bytes: 52428800
    max_outbound_file_bytes: 52428800

    # Optional: per-channel / per-user session settings
    session:
      assistant_id: mobile-agent  # custom agent names are also supported here
      context:
        thinking_enabled: false
      users:
        "123456789":
          assistant_id: vip-agent
          config:
            recursion_limit: 150
          context:
            thinking_enabled: true
            subagent_enabled: true

  dingtalk:
    enabled: true
    client_id: $DINGTALK_CLIENT_ID             # Client ID of your DingTalk application
    client_secret: $DINGTALK_CLIENT_SECRET     # Client Secret of your DingTalk application
    allowed_users: []                          # empty = allow all
    card_template_id: ""                       # Optional: AI Card template ID for streaming typewriter effect
```

Notes:
- `assistant_id: lead_agent` calls the default LangGraph assistant directly.
- If `assistant_id` is set to a custom agent name, DeerFlow still routes through `lead_agent` and injects that value as `agent_name`, so the custom agent's SOUL/config takes effect for IM channels.
- IM channel workers call Gateway's LangGraph-compatible API internally and automatically attach process-local internal auth plus the CSRF cookie/header pair required for thread and run creation.
- Inbound work is bounded to `inbound_queue_maxsize` pending messages plus `max_concurrency` active workers. When capacity is exhausted, socket/polling providers drop new messages before sending DeerFlow's working acknowledgment and emit a rate-limited warning. Buzz leaves its replay cursor unchanged and reconnects for relay replay; GitHub webhooks return `503`, marking the delivery failed for manual/API redelivery. Shutdown closes admission immediately, keeps channel transports available while accepted messages drain for up to `shutdown_grace_period_seconds`, then cancels and awaits active handlers before closing provider resources; the Gateway's outer timeout can cancel an incomplete shutdown without detaching those resources.
- Feishu/Lark now queues rapid follow-up messages per mapped DeerFlow `thread_id` instead of immediately surfacing the generic busy reply, and topic replies keep a per-message card with a compact source-message preview across queued/running/final patches.

Set the corresponding API keys in your `.env` file:

```bash
# Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

# Feishu / Lark
FEISHU_APP_ID=cli_xxxx
FEISHU_APP_SECRET=your_app_secret

# WeChat iLink
WECHAT_BOT_TOKEN=your_ilink_bot_token
WECHAT_ILINK_BOT_ID=your_ilink_bot_id

# WeCom
WECOM_BOT_ID=your_bot_id
WECOM_BOT_SECRET=your_bot_secret

# DingTalk
DINGTALK_CLIENT_ID=your_client_id
DINGTALK_CLIENT_SECRET=your_client_secret
```

**Telegram Setup**

1. Chat with [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the HTTP API token.
2. Set `TELEGRAM_BOT_TOKEN` in `.env` and enable the channel in `config.yaml`.
3. The bot accepts inbound text, photos, and documents (with or without captions). Hosted Bot API downloads are limited to 20 MB per attachment.

**Slack Setup**

1. Create a Slack App at [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch.
2. Under **OAuth & Permissions**, add Bot Token Scopes: `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`, `files:write`.
3. Enable **Socket Mode** → generate an App-Level Token (`xapp-…`) with `connections:write` scope.
4. Under **Event Subscriptions**, subscribe to bot events: `app_mention`, `message.im`.
5. Set `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in `.env` and enable the channel in `config.yaml`.

**Feishu / Lark Setup**

1. Create an app on [Feishu Open Platform](https://open.feishu.cn/) → enable **Bot** capability.
2. Add permissions: `im:message`, `im:message.p2p_msg:readonly`, `im:resource`.
3. Under **Events**, subscribe to `im.message.receive_v1` and select **Long Connection** mode.
4. Copy the App ID and App Secret. Set `FEISHU_APP_ID` and `FEISHU_APP_SECRET` in `.env` and enable the channel in `config.yaml`.

**WeChat Setup**

1. Enable the `wechat` channel in `config.yaml`.
2. Either set `WECHAT_BOT_TOKEN` in `.env`, or set `qrcode_login_enabled: true` for first-time QR bootstrap.
3. When `bot_token` is absent and QR bootstrap is enabled, watch backend logs for the QR content returned by iLink and complete the binding flow.
4. After the QR flow succeeds, DeerFlow persists the acquired token under `state_dir` for later restarts.
5. For Docker Compose deployments, keep `state_dir` on a persistent volume so the `get_updates_buf` cursor and saved auth state survive restarts.

**WeCom Setup**

1. Create a bot on the WeCom AI Bot platform and obtain the `bot_id` and `bot_secret`.
2. Enable `channels.wecom` in `config.yaml` and fill in `bot_id` / `bot_secret`.
3. Set `WECOM_BOT_ID` and `WECOM_BOT_SECRET` in `.env`.
4. Make sure backend dependencies include `wecom-aibot-python-sdk`. The channel uses a WebSocket long connection and does not require a public callback URL.
5. The current integration supports inbound text, image, and file messages. Final images/files generated by the agent are also sent back to the WeCom conversation.

**DingTalk Setup**

1. Create a DingTalk application in the [DingTalk Developer Console](https://open.dingtalk.com/) and enable **Robot** capability.
2. Set the message receiving mode to **Stream Mode** in the robot configuration page.
3. Copy the `Client ID` and `Client Secret`, set `DINGTALK_CLIENT_ID` and `DINGTALK_CLIENT_SECRET` in `.env`, and enable the channel in `config.yaml`.
4. *(Optional)* To enable streaming AI Card replies (typewriter effect), create an **AI Card** template on the [DingTalk Card Platform](https://open.dingtalk.com/document/dingstart/typewriter-effect-streaming-ai-card), then set `card_template_id` in `config.yaml` to the template ID. You also need to apply for the `Card.Streaming.Write` and `Card.Instance.Write` permissions.


When DeerFlow runs in Docker Compose, IM channels execute inside the `gateway` container. In that case, do not point `channels.langgraph_url` or `channels.gateway_url` at `localhost`; use container service names such as `http://gateway:8001/api` and `http://gateway:8001`, or set `DEER_FLOW_CHANNELS_LANGGRAPH_URL` and `DEER_FLOW_CHANNELS_GATEWAY_URL`.

**Commands**

Once a channel is connected, you can interact with DeerFlow directly from the chat:

| Command | Description |
|---------|-------------|
| `/new` | Start a new conversation |
| `/status` | Show current thread info |
| `/models` | List available models |
| `/memory` | View memory |
| `/help` | Show help |

> Messages without a command prefix are treated as regular chat — DeerFlow creates a thread and responds conversationally.

#### Request Trace Correlation

Gateway request trace correlation is disabled by default so existing HTTP responses and log formats stay unchanged. To enable it, set:

```yaml
logging:
  enhance:
    enabled: true
    format: text
```

When enabled, every Gateway HTTP response includes `X-Trace-Id`, logs include `trace_id`, and Langfuse traces created by that request include `metadata.deerflow_trace_id` with the same value.

Gateway run history also records one terminal `run.delivery` receipt per run,
including zero-output and crash-recovered runs. The receipt is persisted before
the durable terminal run status during normal execution. Orphan recovery first
atomically claims an expired lease and then idempotently backfills the receipt,
so a stale recovery scan cannot overwrite a live run's detailed delivery facts.
Receipt persistence remains best-effort during an event-store outage. Runs that
fail checkpoint preflight (or are cancelled while waiting for prior
finalization) keep the existing completion-data behavior: they receive the
zero-delivery receipt but do not overwrite RunStore completion fields with an
empty snapshot.

#### LangSmith Tracing

DeerFlow has built-in [LangSmith](https://smith.langchain.com) integration for observability. When enabled, all LLM calls, agent runs, and tool executions are traced and visible in the LangSmith dashboard.

Add the following to your `.env` file:

```bash
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxxxxxx
LANGSMITH_PROJECT=xxx
```

#### Langfuse Tracing

DeerFlow also supports [Langfuse](https://langfuse.com) observability for LangChain-compatible runs.

Add the following to your `.env` file:

```bash
LANGFUSE_TRACING=true
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxxxxxxxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxxxxxxxxxx
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

If you are using a self-hosted Langfuse instance, set `LANGFUSE_BASE_URL` to your deployment URL.

**Trace correlation fields.** Every agent run is annotated with Langfuse's reserved trace attributes so the Sessions and Users pages light up automatically:

- `session_id` = LangGraph `thread_id` — groups every trace of the same conversation
- `user_id` = effective user from `get_effective_user_id()` (falls back to `default` in no-auth mode)
- `trace_name` = assistant id (defaults to `lead-agent`)
- `tags` = `[env:<DEER_FLOW_ENV>, model:<model_name>]` (omitted when not set)
- `metadata.deerflow_trace_id` = DeerFlow request correlation id, matching `X-Trace-Id` when request trace correlation is enabled

These are injected into `RunnableConfig.metadata` at the graph invocation root for both the gateway path (`runtime/runs/worker.py::run_agent`) and the embedded path (`client.py::DeerFlowClient.stream`), so any LangChain-compatible callback can read them. Set `DEER_FLOW_ENV` (or `ENVIRONMENT`) to tag traces by deployment environment.

#### Monocle Tracing

DeerFlow also supports [Monocle](https://github.com/monocle2ai/monocle), an OpenTelemetry-based tracer for agentic applications. It records each run end-to-end: LLM calls, agent steps, and tool and MCP invocations, with their inputs, outputs, timings, and token counts.

Add the following to your `.env` file:

```bash
MONOCLE_TRACING=true
MONOCLE_EXPORTERS=file          # file, console, okahu, s3, blob, gcs (default: file)
OKAHU_API_KEY=okh_xxxxxxxx      # required only for the `okahu` exporter
```

Each run writes one trace file to `.monocle/`; open it in the [Monocle VS Code extension](https://marketplace.visualstudio.com/items?itemName=OkahuAI.monocle-apptrace) to inspect the span timeline and token counts. Connect to [Okahu](https://www.okahu.ai), an agent-observability platform, to analyze traces across runs and run trace-based and agentic evaluations (via the `okahu` exporter).

Traces capture span inputs and outputs verbatim — prompts, tool arguments, and model responses — plus token usage and timings. The `file` exporter keeps them on local disk and never rotates or cleans them up, so prune `.monocle/` periodically; the remote exporters (`okahu`, `s3`, `blob`, `gcs`) send that same data off-box, so enable only destinations you trust. Monocle is initialized once at Gateway startup: a configuration error (unknown exporter, missing `OKAHU_API_KEY`) is logged there and tracing stays off until the Gateway restarts.

#### Using Multiple Providers

LangSmith and Langfuse attach as LangChain callbacks, so you can enable both and DeerFlow reports each run to both. If an enabled provider is missing required credentials or fails to initialize, DeerFlow fails fast and names it. Monocle uses a global OpenTelemetry provider rather than a callback; Langfuse shares that provider, so all three can run together. Because both span processors sit on the same shared provider, Monocle's exporters also see Langfuse's spans when both are enabled.

For Docker deployments, tracing is disabled by default. Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` in your `.env` to enable it.

## From Deep Research to Super Agent Harness

DeerFlow started as a Deep Research framework — and the community ran with it. Since launch, developers have pushed it far beyond research: building data pipelines, generating slide decks, spinning up dashboards, automating content workflows. Things we never anticipated.

That told us something important: DeerFlow wasn't just a research tool. It was a **harness** — a runtime that gives agents the infrastructure to actually get work done.

So we rebuilt it from scratch.

DeerFlow 2.0 is no longer a framework you wire together. It's a super agent harness — batteries included, fully extensible. Built on LangGraph and LangChain, it ships with everything an agent needs out of the box: a filesystem, memory, skills, sandbox-aware execution, and the ability to plan and spawn sub-agents for complex, multi-step tasks.

Use it as-is. Or tear it apart and make it yours.

## Core Features

### Skills & Tools

Skills are what make DeerFlow do *almost anything*.

A standard Agent Skill is a structured capability module — a Markdown file that defines a workflow, best practices, and references to supporting resources. DeerFlow ships with built-in skills for research, report generation, slide creation, web pages, image and video generation, and more. But the real power is extensibility: add your own skills, replace the built-in ones, or combine them into compound workflows.

Skills are loaded progressively — only when the task needs them, not all at once. This keeps the context window lean and makes DeerFlow work well even with token-sensitive models.

A skill directory is a package boundary: once DeerFlow finds its `SKILL.md`, nested `SKILL.md` files under that package (for example evaluation fixtures) remain supporting data and are not registered as runtime skills. Namespace directories without their own `SKILL.md` can still group nested skills.

Users can explicitly activate an enabled skill for a single turn by starting the request with `/skill-name`, for example `/data-analysis analyze uploads/foo.csv`. DeerFlow loads that skill's `SKILL.md` as hidden current-turn context while leaving the base prompt limited to skill metadata. Slash activation respects disabled skills, custom-agent skill whitelists, and existing channel commands such as `/new` and `/help`.

An enabled skill's `allowed-tools` policy applies only after that skill is explicitly slash-activated or captured in the agent's active skill context after a `read_file` load. Merely enabling, advertising, or listing a skill in a custom agent or subagent `skills` allowlist does not reduce that agent's normal toolset; subagents use the same progressive discovery and activation policy as the lead agent. During a slash-activated run, that explicit skill's policy is authoritative: reading another `SKILL.md` may provide instructions but cannot widen the slash skill's tools. Without slash activation, policies from skills actually loaded into active context retain their union semantics. Once active, the policy filters both model-visible tool schemas and tool execution. Framework discovery tools (`tool_search` and `describe_skill`) remain available so an allowed deferred tool or installed skill can still be discovered, but discovery and promotion never grant permission to execute a business tool omitted from `allowed-tools`. `task` is not framework-exempt; a restrictive skill must list it explicitly to delegate to a subagent. Per-step policy decisions are internal runtime context and are removed from observable or persisted context copies. Registry failures and an active set with no remaining valid skill fail closed to framework-safe tools; individual stale paths are ignored only when another valid active skill remains. This is best-effort behavioral scoping, not a hard security boundary: loading skill instructions through another tool is not captured, and active-skill entries can be evicted from bounded context.

When you install `.skill` archives through the Gateway, DeerFlow accepts standard optional frontmatter metadata such as `version`, `author`, and `compatibility` instead of rejecting otherwise valid external skills.

Disabling a skill also removes it from the sandbox filesystem view, so shell commands and structured file tools follow the same enabled state. Local, Docker/AIO, hostPath provisioner, and newly created E2B sandboxes source `/mnt/skills` from enabled-only projections that update when public, custom, legacy, or managed integration skills are toggled, edited, created, deleted, or installed. Structured `read_file` calls (including line ranges and read-before-write checks) use the sandbox provider's mount mapping, so the user identity captured when the sandbox was acquired remains authoritative. Managed integration packages remain shared, while their projected filesystem visibility follows each user's enabled state. Multi-worker Gateways re-read on-disk enable state while rebuilding user projections, so a toggle handled by one worker is honored by another worker's next sandbox acquire. Existing E2B sandboxes retain their creation-time snapshot until they are recreated. PVC-backed provisioner skills keep their configured PVC snapshot/layout for now; dynamic PVC materialization is tracked separately.

Managed integrations install shared read-only skill packs without mixing them
into custom skills. The Lark/Feishu CLI integration is available under
`Settings → Integrations → Lark / Feishu CLI`; an administrator installs or
upgrades the official `lark-*` pack once under
`{DEER_FLOW_HOME}/integrations/skills/lark-cli`, and every user discovers that
same pack with an independent enabled state. Each user's app configuration and
OAuth data remain isolated under
`{DEER_FLOW_HOME}/users/{user_id}/integrations/lark-cli/{config,data}`. These
secret directories are restricted to `0700`, regular credential files to
`0600`, and symlinks are rejected.

After installation, users can click **Connect Lark** to open a browser
authorization link; no terminal authorization is required. The same UI can
request additional permission domains such as Calendar, Docs, or Drive, or a
specific OAuth scope reported by `lark-cli`. A cheap status refresh only
inspects the local credential tree, so the UI reports **Credentials configured
(not live-verified)** until an explicit browser completion performs live token
verification. The action then remains **Reconnect Lark** so users can replace
or extend authorization. If an agent hits missing Lark authorization during a
conversation, the managed `lark-shared` guidance points the user back to the
same settings entry with `?settings=integrations`.

Once configured, **Change Lark app** lets a user point their DeerFlow account at
a different Lark/Feishu app without a reinstall — either by pasting an existing
app's App ID / App Secret or by re-registering an app in the browser. Switching
is per-user (it never touches another user's credentials), validates the new
credentials through the official CLI's live tenant-token probe before replacing
the active app, and revokes/removes the previous app's OAuth tokens. A rejected
credential change does not supersede an in-progress setup or authorization flow.
DeerFlow then immediately opens browser authorization for the newly bound app so
the switch ends in a usable connection.

Installing the Lark skill pack resolves the latest official `larksuite/cli`
release from GitHub and downloads that version's skills at install time, so the
Gateway needs outbound internet access for that step (it falls back to a
bottom-line pinned version if the release lookup fails). The settings page shows
the installed version and, when available, the newest published version so an
admin can reinstall to upgrade. Air-gapped deployments can pre-stage the archive
and point `DEER_FLOW_LARK_CLI_SKILLS_ARCHIVE` at the local file. Integrity does
not depend on a pinned archive byte hash (GitHub does not guarantee stable
source-archive bytes); instead the download is restricted to the official GitHub
host, every archive member passes structural safety guards, and a content hash
of the effective installed skill tree (including DeerFlow's injected shared
guidance) is recorded so content changes are auditable across reinstalls.

When `sandbox.use` selects the AIO provider, the same install also downloads the
official Linux amd64 and arm64 CLI release archives, verifies their published
SHA-256 checksums, safely extracts one executable per architecture, and mounts
the resulting runtime read-only at `/mnt/integrations/lark-cli/runtime`. An
architecture-selecting launcher in that mount makes `lark-cli` available in the
sandbox `PATH`. Air-gapped AIO deployments can pre-stage a symlink-free runtime
tree containing `bin/lark-cli` plus both `linux-{amd64,arm64}/lark-cli` files and
set `DEER_FLOW_LARK_CLI_SANDBOX_RUNTIME_DIR` to that directory.

> **Sandbox trust boundary:** the browser never receives the Lark app secret, but
> agent conversations run `lark-cli` inside the sandbox, so the per-user
> credential directories are mounted into it: `config` (holding the long-lived
> `appSecret`) is mounted **read-only**, its otherwise empty `config/locks`
> subdirectory is over-mounted writable for `lark-cli` coordination files, and
> `data` (refreshable OAuth tokens) is writable. The credential-bearing config
> and data mounts remain *readable* by any process the agent runs there, so code
> reached via prompt injection in a tool result could read them. Treat the
> sandbox as inside the Lark credential trust boundary until the sidecar
> credential-broker follow-up removes these mounts from sandbox execution.

For remote/Kubernetes deployments (the provisioner backend), the sandbox
`lark-cli` runtime can instead be supplied by an optional init container that
copies the binaries into a shared `emptyDir` — no install-time GitHub download and
no hostPath/PVC runtime mount. Publish the image under
[`docker/lark-cli-init`](docker/lark-cli-init/README.md) and set
`LARK_CLI_INIT_IMAGE` on the provisioner; it stays off (legacy behavior) when
unset. The Lark integration status (`GET /api/integrations/lark/status`) reports
`sandbox_runtime_mode` and `sandbox_runtime_ready` so the Settings UI shows
whether `lark-cli` will actually be present in the sandbox at chat time, rather
than a green status hiding a later `command not found`.

If a trusted operator manages the configured skills directory through an external mount such as MinIO, NFS, or CSI, an administrator can call `POST /api/skills/reload` after changing files. This invalidates skill prompt caches for the current Gateway process and waits up to the bounded refresh timeout so subsequent runs rescan the latest files; running tasks are unchanged. A loader-level filesystem failure returns a generic server error and preserves the last successfully loaded process cache rather than publishing an empty catalog. Uvicorn workers and Kubernetes Pods must each be targeted separately. Direct mount writes bypass the validation, SkillScan, and history applied by DeerFlow's install/edit APIs, so only operator-controlled systems should have write access.

Skill installs and agent-managed skill edits run through **SkillScan**, a native deterministic safety scanner before the LLM-based skill scanner. Phase 1 runs offline with no Semgrep/OpenGrep dependency, blocks high-confidence `CRITICAL` findings such as private keys or shell execution, and passes warning findings to the LLM scanner for contextual review. Python instance-client exfiltration checks follow a minimal same-scope evidence chain: a simple name bound to a known client constructor, optional name-to-name aliases, and an actual outbound method or context-manager use supported by that constructor. Constructor roots must be proven imports; bare canonical-looking names are not inferred as modules. Nested scopes do not inherit client handles and inherit only constructor import aliases that are never rebound in the enclosing scope. Comprehensions, walrus-bearing statements, annotations, complex binding targets, unsupported operations, and ambiguous branch flows produce no finding from this signal; skipped constructs conservatively invalidate every name they may bind so stale client state cannot create a finding. A deterministic work budget or recursion limit reached by this best-effort analysis does not discard findings already collected for the file. Set `skill_scan.enabled: false` in `config.yaml` to disable only the deterministic analyzers; safe archive extraction and the LLM scanner still run.

DeerFlow also ships with **skill-reviewer**, a public skill for read-only skill quality review. It uses the built-in `review_skill_package` tool to inspect installed skills, local packages, archives, or pasted `SKILL.md` content without activating the target skill, binding its secrets, executing its scripts, or installing it. The tool returns a compact, tag-neutralized JSON payload to the model context and keeps the full raw review payload in the tool artifact for programmatic consumers. The deterministic review core reuses DeerFlow parsing and SkillScan facts, emits versioned JSON contracts under `contracts/skill_review/`, and can be run from the backend CLI:

```bash
cd backend
uv run python -m deerflow.skills.review.cli ../skills/public/data-analysis --format text --fail-on error --fail-on-incomplete
```

Tools follow the same philosophy. DeerFlow comes with a core toolset — web search, web fetch, rendered web capture, file operations, bash execution — and supports custom tools via MCP servers and Python functions. Swap anything. Add anything.

Advanced deployments can enable pluggable authorization with `authorization.enabled` in `config.yaml`. A configured `AuthorizationProvider` filters denied tools before they reach the model or deferred-tool catalog, then the same provider is checked again before every business-tool execution through the existing guardrail middleware. Gateway `threads:*` and `runs:*` route permissions are derived from the same provider, while existing owner checks and admin-only management gates remain in force. A generated `tool_search` may bypass the second tool check only when it fronts the current build's already-filtered deferred catalog. The built-in RBAC provider supports per-role `tools` and `routes` allow/deny policies and validates that `default_role` names a configured role; authorization is disabled by default. See `config.example.yaml` and the [authorization RFC](docs/plans/2026-07-10-pluggable-authorization-rfc.md).

Advanced deployments can also extend the agent runtime itself by declaring zero-argument `AgentMiddleware` classes under `extensions.middlewares` in `config.yaml` or `extensions_config.json`. DeerFlow loads the same configured class list into the lead-agent and subagent pipelines after their built-in runtime middlewares and loop/token guards, but before the terminal-response/safety/clarification tail, so enterprise forks can add domain guardrails, tool-call governance, or observability hooks without patching the built-in middleware builders. Missing packages, invalid classes, and broken modules fail loudly at agent creation. Treat `config.yaml` and `extensions_config.json` as trusted operator-controlled files: middleware paths are code execution, just like custom tool, model, sandbox, guardrail, MCP server, and MCP interceptor declarations. Gateway skill/MCP toggle endpoints preserve this field but do not expose an API write path for `extensions.middlewares`. Per-context parameterization and separate lead-only/subagent-only middleware lists are not supported yet.

For packaged and configurable runtime integrations, use DeerFlow's extension manager.
It accepts a Python package requirement, a public HTTPS Git URL, or a local directory, installs the
package into the backend's dedicated `extensions` dependency group, updates
`backend/uv.lock`, and adds an enabled entry to the startup-only top-level `plugins:` list
in `config.yaml`:

```bash
# PyPI — pin a version for a reproducible deployment
make extension-install SOURCE="deerflow-extension-acme==1.2.3"

# Public HTTPS Git — pin an immutable commit
make extension-install \
  SOURCE="git+https://github.com/acme/deerflow-extension-acme.git@0123456789abcdef0123456789abcdef01234567"

# Local package — an absolute path avoids Make's backend-relative working directory
make extension-install SOURCE="$PWD/examples/deerflow-extension-example"

make extension-list
make extension-disable NAME=acme
make extension-enable NAME=acme
make extension-remove NAME=acme
```

Installation is interactive because package installation can execute Python build hooks,
and the loaded extension later runs with Gateway privileges. For an already-reviewed
source, automation can acknowledge that boundary explicitly with
`cd backend && uv run --frozen --no-group extensions deerflow extensions install <source> --yes`.
The manager requires uv 0.8.0 or newer; the provided Docker images pin uv 0.11.1.
The other direct
commands are `deerflow extensions list`, `enable NAME`, `disable NAME`, and `remove NAME`;
`NAME` may be the extension name, Python distribution, or `module:install` value. Do not
put credentials in a source URL — a URL carrying embedded userinfo or a credential-looking
query parameter is rejected before uv runs. Remote Git sources must use public HTTPS; SSH
Git URLs are rejected because the stock Docker builder does not forward host SSH
credentials. Installing from a loopback URL is allowed for local tooling but warns, because
`127.0.0.1` recorded in the lock is a different machine inside the Docker builder.

A managed package declares exactly one standard PEP 621 entry point:

```toml
[project.entry-points."deerflow.extensions"]
acme = "acme_deerflow_extension:install"
```

That callable uses the standalone `deerflow-extension-api` contract and can register five
contribution kinds: isolated middleware at semantic lead/subagent model or tool positions,
lead and subagent task-lifecycle hooks, observers for DeerFlow-owned model calls that are
not wrapped by middleware model-call hooks (goal, memory, title, and summarization),
Gateway-lifetime services, and eager FastAPI HTTP routers. The contract package has no
framework dependencies; extensions must declare FastAPI, LangChain, LangGraph, or other
libraries they import.

DeerFlow allocates a task-scoped extension store only for middleware, lifecycle, or
system-model observation. Services receive app-scoped runtime dependencies after Gateway
persistence is ready and stop in reverse order after active runs drain. Extension HTTP
routers are mounted after every host route; definite shadows and routes entering the
host's authentication- or CSRF-exempt paths are rejected with attributed diagnostics,
while unrelated routers continue to load. Because the host's public paths are a reserved
prefix list that extensions cannot enter, **every contributed endpoint requires an
authenticated session** — there is currently no way for an extension to expose an
unauthenticated route, so inbound provider webhooks and public status endpoints are out of
scope for this release. Router startup/shutdown hooks, custom lifespans,
Mounts, and WebSocket routes are not accepted; lifetime resources belong in
`ExtensionService`, and WebSocket contributions require a future host-owned
authentication/Origin wrapper. Lifecycle and system-model callbacks use the Gateway's
canonical notification loop, including subagents on isolated loops.
Plugin order is deterministic, per-plugin configuration is passed to `install()`, and
`required: true` makes load failure abort startup; otherwise failures are reported and
skipped. `enabled: false` skips resolution and import. The manager preserves the extension's
private `config` when toggling it and writes `name`, `package`, `use`, `enabled`, and
`required` metadata for managed installs. Installs are recorded `required: false` so a
later broken extension is reported rather than blocking Gateway startup; pass
`extensions install <source> --required` when the package's absence should abort startup
instead. Plugins load once when the Gateway app is
constructed, so install, enable, disable, remove, and manual `plugins:` edits all require a
Gateway restart. Because this imports Python code, `plugins:` is intentionally unavailable
through the API-writable `extensions_config.json`.

Management commands bootstrap the checkout environment without the extension group via
`uv run --frozen --no-group extensions`. Frozen mode lets `disable` and `remove` start even
when an installed extension's remote source or managed snapshot has become unavailable,
while a fresh checkout can still create the non-extension environment from the existing lock. The
manager itself owns the subsequent locked dependency transaction.
Mutations for one checkout are serialized through a process lock. The initial manager
surface is create/remove rather than in-place upgrade: to change an installed source, save
its private `plugins[].config`, remove it, reinstall the new pin, and restore that config.

Local-directory installs are copied into
`backend/extensions/sources/<normalized-distribution>/`; this deployable snapshot, rather
than the original directory, is recorded in the lock. Git metadata, virtual environments,
bytecode caches, symbolic links, and likely credential files are not accepted as snapshot
content. Review what you install anyway: filtering accidental files does not sandbox an
extension, its build backend, or its runtime code.

Local `make dev`/`make start`, Docker development, and the production Gateway image all
consume the same `backend/pyproject.toml` and `backend/uv.lock`. Local and Docker-dev
launchers perform a locked sync before starting; the production image performs that sync
during its build and includes managed local snapshots in the build context. Gateway runtime
commands then use the already-created environment without resolving or installing packages.
Local and Docker-development pre-start syncs may download missing locked artifacts. A
production deployment instead downloads them only during the explicit install or image
build; starting the resulting production Gateway container never resolves or installs
extensions from the network. A local wheel or `file://` Git URL is rejected because it
would not exist in the Docker build context; pass a source directory to create a managed
snapshot instead. Because environment configuration (such as a `UV_FIND_LINKS` wheelhouse)
can still resolve a plain package name to a local wheel, the manager audits every new lock
before enabling the extension: any local reference the stock image build cannot reproduce
rolls back the entire install or removal.
Rebuild with `make up` after changing the managed extension set. See
`config.example.yaml` and the
[reference extension](examples/deerflow-extension-example/) for a complete example.

Gateway-generated follow-up suggestions now normalize both plain-string model output and block/list-style rich content before parsing the JSON array response, so provider-specific content wrappers do not silently drop suggestions.

The Web UI composer can polish draft input before sending. The rewrite runs as a short Gateway LLM request using the `input_polish` model configuration, keeps slash skill prefixes such as `/data-analysis`, and only replaces the local draft after the user clicks the polish button; it does not create a thread run or persist a message.

When the agent asks for clarification, the Web UI shows the structured response card but keeps the normal composer available. Users can complete the card or send a free-form chat message to bypass it; that message closes the latest pending clarification and becomes the agent's next input.

Unsent Web UI composer drafts survive page reloads and switching between conversations within the same browser tab. Drafts are isolated by user, agent, and conversation, include a selected slash skill when present, and are cleared once a send is accepted. Attachments and quoted conversation context are intentionally not persisted.

The Web UI composer also supports browser-based voice dictation when the browser exposes the Web Speech API. The microphone button transcribes speech into the local draft only; DeerFlow receives only the transcribed text, while audio handling is delegated to the browser or operating system speech-recognition service according to that environment's policy. Users can review or edit the text before sending.

The Web UI displays a localized AI-generated-content disclaimer below the composer in both standard and custom-agent conversations, reminding users to verify important
information.

Interrupted first-turn runs still persist a fallback conversation title, so stopping a streaming response does not leave the thread as "Untitled" after refresh.

Streaming Markdown responses animate only newly arrived words; text that is already visible is not faded out and replayed when the next chunk extends the same block.

In the Web UI, completed assistant turns can be branched into a new main conversation. The new thread starts from that turn's checkpoint and keeps the preceding replay checkpoint, so the branched response can be regenerated immediately. The latest response can also be regenerated after an interruption, even when its streamed partial text never reached a checkpoint. Regenerating the latest response preserves the thread's current title, including a title you renamed manually after the original response. Legacy or imported histories without checkpoint parent links use a bounded chronological fallback; if no earlier replay checkpoint exists, branching still succeeds with the legacy single-checkpoint shape, while regeneration remains unavailable for that inherited response. Existing single-checkpoint branches are left unchanged rather than attempting an unsafe checkpoint copy. Because workspace files are not checkpointed, the branch only receives a best-effort copy of the current workspace when you branch from the latest turn; branching from an older turn keeps just the restored message history so the branch never inherits files that were created in a later part of the conversation.

The Web UI reports completed task time once per run. This is total wall-clock time—including model reasoning, tool calls, and waiting—not a per-step or model-only thinking duration. Reasoning content remains available through its own separate disclosure.

In the Web UI, the latest completed user turn can also be edited and rerun from the message toolbar. DeerFlow restores the conversation checkpoint before that user message, submits the edited text as a new user message, and hides the superseded turn once the replay is in progress or succeeds. This is a conversation-state replay only: files, memory updates, and external tool side effects are not undone.

Web UI chat links percent-encode custom thread identifiers before placing them in route segments, so reserved URL characters such as `#` and `?` do not change which conversation is opened.

```
# Paths inside the sandbox container
/mnt/skills/public
├── research/SKILL.md
├── report-generation/SKILL.md
├── slide-creation/SKILL.md
├── web-page/SKILL.md
└── image-generation/SKILL.md

/mnt/skills/custom
└── your-custom-skill/SKILL.md      ← yours

/mnt/skills/integrations
└── lark-cli/lark-doc/SKILL.md      ← managed, read-only
```

#### Claude Code Integration

The `claude-to-deerflow` skill lets you interact with a running DeerFlow instance directly from [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Send research tasks, check status, manage threads — all without leaving the terminal.

**Install the skill**:

```bash
npx skills add https://github.com/bytedance/deer-flow --skill claude-to-deerflow
```

Then make sure DeerFlow is running (default at `http://localhost:2026`) and use the `/claude-to-deerflow` command in Claude Code.

**What you can do**:
- Send messages to DeerFlow and get streaming responses
- Choose execution modes: flash (fast), standard, pro (planning), ultra (sub-agents)
- Check DeerFlow health, list models/skills/agents
- Manage threads and conversation history
- Upload files for analysis

**Environment variables** (optional, for custom endpoints):

```bash
DEERFLOW_URL=http://localhost:2026            # Unified proxy base URL
DEERFLOW_GATEWAY_URL=http://localhost:2026    # Gateway API
DEERFLOW_LANGGRAPH_URL=http://localhost:2026/api/langgraph  # LangGraph API
```

See [`skills/public/claude-to-deerflow/SKILL.md`](skills/public/claude-to-deerflow/SKILL.md) for the full API reference.

### Session Goals

Use `/goal <completion condition>` to attach one active completion condition to the current thread. The goal is thread-scoped state, not a skill activation, so it stays active across turns until DeerFlow determines it has been satisfied or you clear it.

Supported commands:

```text
/goal finish the implementation and make all tests pass
/goal              # show the active goal
/goal clear        # clear it
```

After each Gateway-backed run, DeerFlow evaluates the visible conversation against the active goal with a non-thinking evaluator model. The evaluator must return a typed blocker (`missing_evidence`, `needs_user_input`, `run_failed`, `external_wait`, or `goal_not_met_yet`) plus visible evidence. DeerFlow only injects a hidden continuation when the latest assistant turn is durably checkpointed, the blocker is `goal_not_met_yet`, the thread did not change during evaluation, and the no-progress breaker has not fired. The safety cap defaults to 8 hidden continuations, and repeated identical non-progress evaluations stop after 2 attempts. `/goal clear` and any user-authored new input win over queued continuations. When the goal is satisfied, DeerFlow clears it automatically and publishes the updated thread state.

The Web UI shows the active goal above the composer. The same command is available from the TUI and supported IM channels. In the Web UI and supported IM channels, setting `/goal <completion condition>` also starts a run with the condition as the task; status and clear commands only manage goal state. Setting or clearing a goal is rejected while that thread has a run in flight, including a run owned by another Gateway worker, so the goal checkpoint cannot branch away from an active run's checkpoint lineage.

### Manual Context Compaction

Use `/compact` in the Web UI composer to summarize older context for the current thread. DeerFlow keeps the full chat visible, but future model calls use the compacted summary plus recent messages. The command is ignored when there is not enough history to compact, and it is blocked while the thread has a run in flight, including when that run is owned by another Gateway worker. If a multi-worker reservation loses its lease, DeerFlow cancels the checkpoint writer before the replacing run proceeds and returns a retryable conflict after cleanup. Thread-title edits are serialized through the same state-write boundary and show a conflict without closing the rename dialog when a run is active.

The chat header also shows a context-window gauge when the selected model has a positive `context_window` configured. It estimates the latest materialized checkpoint's message tokens and keeps the previous same-thread percentage visible while data refetches, independently of the cumulative token-usage setting.

### Sub-Agents

Sub-agents are an optimization, not the default response to a complex request.

The lead agent can spawn sub-agents on the fly — each with its own scoped context, tools, and termination conditions — when delegation has clear net benefit from real parallel latency, specialist capability, or context isolation. It keeps interdependent scopes and overlapping side effects out of parallel dispatch; a bounded sequential chain can still run in one sub-agent when specialist or context-isolation benefit clearly wins. The lead uses the fewest useful sub-agents and re-evaluates later batches instead of fanning out solely because a task is large or multi-step. Sub-agents report back structured results, and the lead agent verifies and synthesizes them into a coherent output. Their configured skills are resolved from the same user-scoped catalog as the lead agent, so user-owned custom skills remain available without exposing another user's version. Their internal AI and tool messages stay scoped to the delegated graph instead of entering the parent chat stream. Reloaded thread history enforces the same boundary: callback-captured sub-agent AI responses remain available in run-event diagnostics but are excluded from the parent transcript, while the parent `task` result remains attached to its subtask card. Long-running sub-agents compact older history when summarization is enabled and re-inject the summary as guarded, hidden durable context before continuing, so recent assistant/tool activity remains grounded in the task. Provider/model request failures are reported as failed sub-agent tasks rather than successful results, so the lead agent and Web UI can react to them correctly. Concurrent parent runs also receive independent server-side sub-agent execution IDs, so a provider that reuses a tool-call ID cannot make one run poll, cancel, or clean up another run's background task. Collapsed sub-agent cards show the effective model and, when the provider returns usage metadata, a cumulative token total that updates after each completed sub-agent LLM call and persists after a reload. When token usage tracking is enabled, completed sub-agent usage is attributed back to the dispatching step from that run's terminal tool-message metadata rather than a process-global provider-ID cache.

For example, independent read-only research can run concurrently when the wall-clock savings outweigh duplicated discovery and synthesis cost, while a repository refactor with shared files and sequential test feedback remains with the lead agent. When `max_concurrent_subagents` is `1`, parallel and multi-batch routing guidance is disabled; delegation remains available only for material specialist or context-isolation benefit.

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

`E2BSandboxProvider` uses `wait` as its default overflow policy. It waits for
`acquire_timeout`, then fails the agent turn. DeerFlow does not retry the turn
automatically. Clients can use the structured error to schedule a retry.

Use `burst` with `burst_limit` to permit bounded extra VMs. The `wait` and
`reject` policies use only `replicas`. The `reject` policy can remove one warm
VM before it returns an error.

With in-memory ownership, `replicas` limits one Gateway process. With Redis
ownership, E2B shares one capacity Hash between workers using the same
`sandbox.ownership.key_prefix`; `replicas` (plus a configured burst) is then a
deployment-wide hard limit. Use one unique prefix and the same effective limit
per deployment. To change the limit, stop its Gateways, delete the capacity
Hash, and restart; mismatched workers fail closed.

The Hash counts remote VMs and in-flight creates, repairs interrupted creates
from E2B metadata, grace-protects stale inventory omissions, and blocks new
creates while Redis or initial inventory is unavailable. Run Redis with persistence, non-evicting memory, and HA.

E2B acquisition uses a bounded executor. Waiting acquisitions do not use the
default asyncio executor.

Each E2B mount upload pass accepts at most 512 MiB and 2,000 files. The pass
also has a cooperative 120-second deadline. Skill projections and configured
mounts share these limits. The provider checks the deadline before each mount
and during directory preflight. The deadline stops new file uploads after it
expires. It does not interrupt active filesystem or E2B SDK calls.

An E2B VM keeps its slot until E2B confirms destruction. This rule covers
create and reclaim operations. Discovery can find a VM from another Gateway.
Shutdown closes an unowned discovery client without destroying its VM.
Release stops counting a transition when the VM enters the warm pool.
Shutdown races retry remote cleanup after a transient kill failure.
Reset destroys tracked active and warm E2B VMs. The old provider instance
cannot accept new acquisitions.

DeerFlow doesn't just *talk* about doing things. It has its own computer.

Each task gets its own execution environment with a full filesystem view — skills, workspace, uploads, outputs. The agent reads, writes, and edits files. It can view images and, when configured safely, execute shell commands.

The built-in `grep` tool searches either one text file or all matching text files below a directory, so an agent can search an uploaded document directly without first broadening the request to the entire uploads directory.

Image bytes loaded for a vision-model call are transient: DeerFlow removes the hidden base64 message after the model consumes it so later checkpoints do not keep duplicating that payload.

After each run, DeerFlow records a workspace change summary for the run-owned `workspace` and `outputs` directories. The Web UI shows a compact "files changed" badge on the assistant turn; opening it reveals created, modified, and deleted files with text diffs when safe to display. Uploads are excluded because they are user inputs, not agent-generated changes, and stdio MCP temporary/debug files under the DeerFlow-owned `.mcp/` namespace are excluded because they are process-internal state (like `.git/` and `node_modules/`, any directory named `.mcp` is excluded at any depth). Large, binary, or sensitive-looking files are shown as metadata only.

Files presented through `present_files` remain part of the thread's artifact state, and the Web UI restores the artifact panel and selected document after a page refresh. The currently selected formal artifact is refreshed once when the run finishes so edits become visible without a manual reload. Existing UTF-8 text artifacts under `/mnt/user-data/outputs` can also be edited and explicitly saved from the panel on Unix and Windows while the thread is idle; saves use content revisions to prevent overwriting agent changes.

Text artifacts are streamed with HTTP byte-range support. The Web UI initially
loads at most 1 MiB, shows the preview size when a file is larger, and waits for
an explicit **Load full file** action before fetching the remainder or mounting
the full code editor. Active HTML, XHTML, and SVG artifacts remain forced
downloads at the Gateway boundary.

With `AioSandboxProvider`, shell execution runs inside isolated containers. With `LocalSandboxProvider`, file tools still map to per-thread directories on the host, but host `bash` is disabled by default because it is not a secure isolation boundary. Re-enable host bash only for fully trusted local workflows. Host bash commands have a wall-clock timeout, and long-lived processes should be started in the background with output redirected to a workspace log.

`AioSandboxProvider` normally detects thread-data mounts from its backend: local
containers use the mounted gateway directories, while remote/provisioner
sandboxes receive uploaded files through explicit synchronization. Deployments
where both sides are guaranteed to share the same thread user-data directories
can set `sandbox.thread_data_mounts: true` to skip that per-upload sandbox
acquire and sync. Leave the field unset for automatic detection; setting it
incorrectly can make uploaded files unavailable inside the sandbox.

This is the difference between a chatbot with tool access and an agent with an actual execution environment.

```
# Paths inside the sandbox container
/mnt/user-data/
├── uploads/          ← your files
├── workspace/        ← agents' working directory
└── outputs/          ← final deliverables
```

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

### Agentic Browser Control

Reading a page is not the same as *using* one. Alongside the read-only `web_fetch` and `web_capture` tools, DeerFlow ships an optional agentic browser tool group that keeps a live, per-conversation browser session so the agent can actually operate a page — navigate, read the interactive elements, click, type, submit forms, and follow multi-step flows on JavaScript-heavy sites.

Each action returns a fresh snapshot of the page's interactive elements, each addressed by a stable `[ref]` number, so the agent acts on what it just observed instead of guessing selectors. Outbound URLs are SSRF-screened by default. It is powered by Playwright and shipped as an optional extra so the core install stays lean:

```bash
cd backend
uv sync --extra browser
uv run playwright install chromium
```

Then uncomment the `group: browser` tool entries in `config.yaml` (`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_get_text`, `browser_back`, `browser_screenshot`, `browser_close`). `make dev` / Docker startup detects an enabled `browser_navigate` tool and preserves the `browser` extra on dependency syncs. The Gateway fails startup if browser control is configured but Playwright is missing, and `/api/features` hides the Browser UI unless the backend can actually serve it. Keep `headless: true` and `allow_private_addresses: false` for anything but local, trusted debugging. Attaching to an existing Chrome with `cdp_url` cannot enforce DeerFlow's subresource/redirect SSRF guard and therefore fails closed unless `allow_unguarded_cdp: true` explicitly acknowledges that risk; use it only with a trusted local browser. Browser sessions are process-local; keep `GATEWAY_WORKERS=1` while this tool group is enabled because ordinary uvicorn worker dispatch does not provide thread affinity.

Existing, non-mock Custom Agent chats expose the same Browser Live controls when browser control is available and the agent either leaves `tool_groups` unrestricted or includes the `browser` group. An explicit tool-group allowlist without `browser` keeps those controls hidden.

The workspace Browser Live client negotiates binary JPEG WebSocket frames,
keeps only the newest pending frame per display refresh, and revokes replaced
object URLs. Gateway control messages remain JSON, and clients that do not
request the binary capability retain the legacy JSON/base64 frame protocol.

### Context Engineering

**Isolated Sub-Agent Context**: Each sub-agent runs in its own isolated context. This means that the sub-agent will not be able to see the context of the main agent or other sub-agents. This is important to ensure that the sub-agent is able to focus on the task at hand and not be distracted by the context of the main agent or other sub-agents.

**Summarization**: Within a session, DeerFlow manages context aggressively — summarizing completed sub-tasks, offloading intermediate results to the filesystem, compressing what's no longer immediately relevant. This lets it stay sharp across long, multi-step tasks without blowing the context window.

**Strict Tool-Call Recovery**: When a provider or middleware interrupts a tool-call loop, DeerFlow now strips provider-level raw tool-call metadata on forced-stop assistant messages and injects placeholder tool results for dangling calls before the next model invocation. This keeps OpenAI-compatible reasoning models that strictly validate `tool_call_id` sequences from failing with malformed history errors.

**Visible Tool-Run Completion**: For interactive turns, DeerFlow retries an empty post-tool final response once, then surfaces a visible error instead of reporting a silent successful run.

### System Prompt

Every run starts from a system prompt — roughly 12,000 characters of instructions assembled before your first message ever reaches the model. It sets the agent's role, how it thinks, when it delegates to sub-agents, which skills it can reach for, and what it is allowed to say about itself. In most agent frameworks that text is a constant buried in the source. Here it is a page in the app.

**Settings → System prompt** has two tabs:

- **Edit** — the template in force, in a monospace editor. The twelve placeholders the runtime fills in (`{skills_section}`, `{subagent_section}`, `{soul}`, `{memory_tool_section}`, …) are listed as one-click insert buttons, with a character budget and a *Discard edits* escape hatch.
- **Preview** — the same prompt with every placeholder substituted: the exact text the lead agent receives, not an approximation. A switch toggles the Ultra-mode sub-agent block, which is also where the available sub-agent roster is listed — so this is the one place in the UI that shows which agents `task` can delegate to, including any you defined under `subagents.custom_agents`.

Edits are saved to `SYSTEM_PROMPT.md` beside your other DeerFlow state and re-read on every agent build, so **a change applies from your next run with no restart**. `make backup` carries it along with the rest of your instance. **Reset to default** restores the built-in prompt at any time.

Templates are validated before they are saved, not after: an unknown placeholder is refused with the offending name rather than accepted and then silently ignored. Because saving proves the template renders, anything the editor accepts is guaranteed to work on the next run. Leaving a placeholder *out* is not an error — it is how you remove that section from the prompt, and the page tells you which blocks a given template omits.

Two guardrails worth knowing:

- **A saved prompt can change a run, but never break one.** If the file is hand-edited on disk, restored from an older backup, or written against a placeholder a newer version no longer provides, the agent falls back to the built-in prompt with a warning instead of failing to start.
- **The built-in prompt tells the agent not to disclose its own instructions.** You may remove that section — some people want an agent that can explain itself — and the editor warns you when an edit does, because the effect is invisible until someone asks the agent to recite its prompt.

The routes behind the page (`GET`/`PUT`/`DELETE /api/system-prompt` and `GET /api/system-prompt/preview`) require an admin account, the same bar as skill and MCP management. In the default passwordless local setup, that is you.

### Long-Term Memory

Most agents forget everything the moment a conversation ends. DeerFlow remembers.

DeerFlow also includes an optional `openviking` memory backend. It uses the
official `langchain-openviking` package to capture completed turns into stable
OpenViking Sessions and recall memory for prompt injection while leaving
DeerMem as the default. The initial integration supports one DeerFlow user with
one credential-bound OpenViking USER API key in `memory.mode: middleware` and
does not inherit arbitrary HTTP headers from `ovcli.conf`.
See [OpenViking memory backend](docs/OPENVIKING.md) for its configuration,
behavior, and current boundaries.

Across sessions, DeerFlow builds a persistent memory of your profile, preferences, and accumulated knowledge. The more you use it, the better it knows you — your writing style, your technical stack, your recurring workflows. Memory is stored locally and stays under your control.

DeerMem remains the default local backend. An opt-in `mem0` backend is also
available for the hosted mem0 Platform API or API-compatible self-hosted
servers. Its token-bearing `base_url` must use HTTPS by default; plaintext HTTP
requires an explicit local-development opt-in. See the
[mem0 backend guide](backend/packages/harness/deerflow/agents/memory/backends/mem0/README.md).

An opt-in `honcho` backend is available for self-hosted or hosted Honcho (v3
API). It builds user-model memory — long-term preferences and a cross-session
working representation — on Honcho's server side, so the backend makes no LLM
calls locally. Each user gets an isolated workspace derived from `user_id`; a
missing user id fails closed instead of falling back to a shared workspace.
Fact CRUD and Settings-page fact editing are not available for this backend. See
the [Honcho backend guide](backend/packages/harness/deerflow/agents/memory/backends/honcho/README.md).

Memory updates now skip duplicate fact entries at apply time, so repeated preferences and context do not accumulate endlessly across sessions.

In the default DeerMem `middleware` mode, automatic extraction now classifies every proposed fact by scope, durability, and authority before a deterministic write gate accepts it. Only durable, descriptive user-level facts are stored; current-thread or project constraints and one-time action permissions stay in conversation state. User-global summaries require both user scope and descriptive authority, contradiction removals are scope-gated, and a replacement-dependent removal is applied only when its replacement actually survives validation and storage. These classification labels are extraction-only metadata, add no extra LLM call, and are not written into the fact files. The explicit CRUD tools in `memory.mode: tool` remain a separate, model-directed path. Deployments that override the bundled DeerMem prompts via `memory.backend_config.prompts_dir` must add the new classification fields to their custom templates (the `memory_update` fact/summary/removal formats and the `consolidation` consolidated-fact schema): the write gate fails closed, so an un-migrated template stops every extraction-driven fact, summary, and removal write, surfacing only through the `rejected_by_scope_gate` metrics and the high-rejection-rate warning.

When a fact scope reaches `max_facts`, DeerMem still uses the historical confidence-only eviction order by default. Operators can opt in to `memory.backend_config.fact_eviction_policy: hybrid-v1`, which combines bounded confidence (65%), explicit-confirmation freshness (25%), and query-driven access heat (10%). Hybrid signal metadata is collected only while hybrid-v1 or shadow mode is enabled. Explicit confirmation is returned as `factsToReinforce` by the existing memory-update LLM call and is accepted only when deterministic message processing also detects a user reinforcement signal; it also resets the fact's staleness-review clock. This deterministic gate is batch-level: it establishes only that a human message among the last six filtered messages in the current extraction batch matched a reinforcement pattern. The LLM-selected `factsToReinforce` ID supplies the fact binding; DeerMem does not independently verify a signal-to-fact correspondence. Repeated extraction or automatic injection never confirms a fact. Custom `memory_update` prompts should add the optional `factsToReinforce` array to participate in confirmation freshness. Access heat is stored in a separate decaying sidecar and increases only when `memory_search` actually returns the fact, so reads do not rewrite canonical Markdown or its `updatedAt`. Hybrid mode also reserves a bounded minimum of correction slots (10% of the cap, at most 10; unused slots return to normal competition). Capacity deletion remains physical, but a bounded metadata-only audit records fact IDs, categories, policy scores, and reasons without copying fact content. `fact_eviction_shadow_enabled: true` evaluates hybrid-v1 alongside the default policy without changing actual retention. This feature adds no LLM invocation and can be rolled back by selecting `confidence`.

File-backed memory now separates global user context from agent facts. Each user has one `memory.json` containing only the project-independent `user` and `history` summaries; every fact is a canonical Markdown file below `agents/{agent_name}/facts/`. Existing lead-agent middleware, API, Settings, import/export, and embedded-client calls that omit `agent_name` resolve inside DeerMem to the reserved `__default__` bucket. That bucket is outside the valid custom-agent name grammar, so a real custom agent named `lead-agent` has a separate fact repository and deleting a custom agent cannot delete a memory-only directory without `config.yaml`. Public agent identifiers are case-insensitive and canonicalized to lowercase. Runtime/API readers still receive a compatibility `facts` array for the selected/default agent, so the frontend does not read agent facts from `memory.json`; structured Markdown `source` metadata is projected to the historical string field at the MemoryManager boundary. An unscoped Clear All first migrates facts from unread legacy per-agent JSON without adopting its soon-to-be-cleared summaries, then removes shared summaries and facts from every agent bucket while preserving agent configuration files, so a later read cannot resurrect skipped legacy facts; an explicitly agent-scoped clear removes only that agent's facts. On first normal read, old facts embedded in the user JSON are migrated automatically to `__default__`; facts written to the earlier implicit `lead-agent` bucket are also moved when that directory is not a real custom agent. Migration and normal writes notify the configured retrieval adapter only after durable storage locks are released. DeerMem uses a scope-aware SQLite FTS5/BM25 adapter by default, stores only rebuildable derived index data under `.retrieval/`, and rebuilds it in the background during Gateway startup or lazily on the first scoped search. A corrupt derived index is recreated automatically. Set `memory.backend_config.retrieval_adapter` to an empty string to disable it and use the local substring fallback. Chinese tokenization is optional; install the backend `memory-zh` extra (`uv sync --extra memory-zh`) for jieba-assisted sub-phrase search. Journaled writes, a shared user lock, and optimistic user-memory revisions prevent silent lost updates.

Memory injection follows the configured operation mode. In `middleware` mode, DeerMem injects the user-global summaries and the selected agent's facts. Custom-agent bootstrap conversations use that agent's fact bucket as well, so setup details do not leak into the default agent's memory. In `tool` mode, the automatic `<memory>` block contains only the global `user` and `history` summaries; agent facts are retrieved explicitly through `memory_search`, avoiding duplicate automatic and tool-returned fact context. Setting `memory.injection_enabled: false` still disables the entire block in either mode.

Single-fact repository operations are genuinely incremental: an upsert/delete reads, journals, writes, and re-indexes only the addressed fact files, and returns an explicit incomplete delta rather than a cache-dependent fake full document. Summary change sets merge the supplied `user`/`history` child keys over the persisted sections so a partial update cannot erase omitted siblings; full imports normalize both sections to the complete compatibility schema before applying replacement values. Manager/API compatibility methods materialize a fresh full document only when their public response contract requires one. Fact-level point operations use separate expected user-memory and fact revisions and may explicitly rebase when every addressed fact precondition still holds. Snapshot-derived operations such as scoped clear, capped create, consolidation, and trimming never replay stale delete/trim sets: a manifest conflict reloads the complete document and recomputes the operation, with a bounded retry. Fact paths use the first two hexadecimal characters of `SHA-256(fact_id)` so generated `fact_*` IDs distribute across shards. The cache token combines the shared JSON's nanosecond mtime, size, and persisted revision; this prevents coarse-mtime same-size writes from returning stale data without scanning fact files. Direct out-of-band Markdown edits require an explicit reload. Storage-specific conflicts and corruption are translated at the MemoryManager boundary; the Gateway returns conflict as HTTP 409 and a stable, non-sensitive corruption error as HTTP 500. Full-document `save()` remains a compatibility API and computes a diff before writing; malformed or missing `facts` can no longer silently erase an agent's Markdown files. Legacy migration preserves non-empty `user`/`history` before deleting an agent `memory.json`; conflicting summaries keep the legacy file and fail loudly instead of choosing a winner.

Legacy facts in `memory.json` migrate automatically into the reserved `__default__` Markdown bucket on the user's first normal memory read. Operators who prefer to audit or complete the migration before serving traffic can run the optional idempotent CLI from `backend/`:

```bash
PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users --dry-run
PYTHONPATH=. python scripts/migrate_memory_markdown.py --all-users
# A custom DeerMem root or original non-directory-safe identity can be explicit:
PYTHONPATH=. python scripts/migrate_memory_markdown.py --storage-path /path/to/deerflow-home --user-id 'test@example.com'
```

The v1-to-v2 storage migration is one-way for a running application: pre-PR code does not read Markdown facts. Before upgrading a persistent deployment, stop DeerFlow and take a filesystem snapshot or full backup of the configured memory storage root. The migration also durably retains each destructive JSON source beside the original path as `{manifest_filename}.v1.bak` before writing v2 data; an existing mismatched backup or a backup-write failure stops migration without modifying the v1 source. This local backup preserves pre-migration data but is not a substitute for a full snapshot and does not contain facts created after the upgrade.

`--user-id` may be repeated. `--all-users` discovers the existing directory-safe buckets below the selected storage root; standalone integrations that passed raw IDs containing characters such as `@` should use the original value with `--user-id`. A failed user's migration is reported without hiding the rest of the audit, and the command exits non-zero when any user fails. The automatic first-read path remains enabled, so running this CLI is not required for startup.

### Concurrent Chats

Chats run independently of each other. Ask one conversation for something slow —
a long research pass, a sandbox build — then leave it and prompt a different
conversation while the first is still working. Both answers arrive, and the one
you walked away from is still there, still streaming, when you come back.

**Leaving a running chat now keeps it, rather than ending it.** Two things used
to get in the way. A run is cancelled when its browser stream disconnects
(`on_disconnect` defaults to `cancel` on the Gateway's run API), which is exactly
what leaving a chat does — so the answer you walked away to wait for was killed
on the way out. And even a surviving run went dark, because only chats you have
explicitly pinned to the tab strip stay mounted. Now every run is submitted as
"keep going if my stream drops", and a chat you leave **while it is still
answering** is automatically kept as a keep-alive tab: it keeps streaming in the
background with a pulsing dot on its tab chip, and the dot disappearing is how
you know it finished. The desktop notification fires for a chat that is merely
off-screen too, not just when the whole window is hidden. Nothing to configure.

This also means **closing the browser no longer cancels a run** — it finishes on
the server, which is what the "notify me when it's done" push notification
assumed all along, and why a phone that locks its screen mid-run still gets an
answer. The **Stop** button is unaffected: it cancels the run outright, and a
runaway run is still bounded by your spend cap.

Two deliberate limits: a brand-new chat whose thread the backend has not created
yet is not kept as a tab (a tab is addressed by thread id), and a full tab strip
declines rather than evicting a tab you chose. In both cases the run itself still
survives on the server and you rejoin it when you open the chat again.

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

## Recommended Models

DeerFlow is model-agnostic — it works with any LLM that implements the OpenAI-compatible API. That said, it performs best with models that support:

- **Long context windows** (100k+ tokens) for deep research and multi-step tasks
- **Reasoning capabilities** for adaptive planning and complex decomposition
- **Multimodal inputs** for image understanding and video comprehension
- **Strong tool-use** for reliable function calling and structured outputs

## Embedded Python Client

DeerFlow can be used as an embedded Python library without running the full HTTP services. The `DeerFlowClient` provides direct in-process access to all agent and Gateway capabilities, returning the same response schemas as the HTTP Gateway API. The HTTP Gateway also exposes `DELETE /api/threads/{thread_id}` to remove DeerFlow-managed local thread data after the LangGraph thread itself has been deleted:

Thread IDs may be supplied by callers and do not have to be UUIDs. Explicit
IDs must contain 1–64 ASCII letters, digits, hyphens, or underscores
(`^[A-Za-z0-9_-]{1,64}$`). DeerFlow generates a UUID only when `thread_id` is
omitted or `None`; an explicitly supplied empty string is invalid.
Existing route-addressable threads created under older, looser rules remain
readable and deletable, but cannot start new runs or create new filesystem or
sandbox state. Legacy deletion skips local path cleanup when the ID is not
safe under the canonical contract. For canonical legacy threads whose
conversation exists only in LangGraph checkpoints, DeerFlow seeds an empty
run-event feed from the checkpoint before the first new run so
`/messages/page` keeps both the old and new turns.

```python
from deerflow.client import DeerFlowClient

client = DeerFlowClient()

# Chat
response = client.chat("Analyze this paper for me", thread_id="my-thread")

# Streaming (LangGraph SSE protocol: values, messages-tuple, end)
for event in client.stream("hello"):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data["content"])
    elif event.type == "messages-tuple" and event.data.get("type") == "tool" and "artifact" in event.data:
        # Structured tool artifacts (for example, ask_clarification cards)
        # are preserved when the ToolMessage provides one.
        print(event.data["artifact"])

# Configuration & management — returns Gateway-aligned dicts
models = client.list_models()        # {"models": [...]}
skills = client.list_skills()        # {"skills": [...]}
client.update_skill("web-search", enabled=True)
client.upload_files("thread-1", ["./report.pdf"])  # {"success": True, "files": [...]}
client.set_goal("thread-1", "finish the implementation and make all tests pass")
client.get_goal("thread-1")       # {"goal": {...}} or {"goal": None}
client.clear_goal("thread-1")
```

The HTTP Gateway accepts `values`, `messages-tuple`, `updates`, `debug`, `tasks`, `checkpoints`, and `custom` stream modes. Unsupported modes such as `messages` and `events`, unsupported non-default run options such as webhooks, delayed execution, or `multitask_strategy="enqueue"`, and undeclared SDK options such as checkpoint durability overrides return `422` before execution instead of being silently ignored or downgraded.

All dict-returning methods are validated against Gateway Pydantic response models in CI (`TestGatewayConformance`), ensuring the embedded client stays in sync with the HTTP API schemas. See `backend/packages/harness/deerflow/client.py` for full API documentation.

## Scheduled Tasks

DeerFlow now includes a first-class scheduled-task MVP in the workspace.

Current MVP capabilities:

- Manage tasks at `/workspace/scheduled-tasks`
- Choose whether each scheduled task reuses a thread or creates a fresh thread per run
- Support `once` and `cron` schedules
- Run background scheduled executions as non-interactive DeerFlow runs (`ask_clarification` is not exposed there)
- Use `skip` overlap behavior for due cron executions that collide with an active run on the same reused thread
- Pause, resume, trigger, inspect history, and delete tasks
- Execute scheduled work through the normal DeerFlow run lifecycle

Current MVP limits:

- No conversation-created `schedule_task` tool yet
- No text-only notification jobs
- No channel or GitHub dispatch targets
- No `interval` schedule type in this first cut

Enable background polling with `config.yaml -> scheduler.enabled`. Manual trigger uses the same scheduled-task resource and execution path.

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
directory (memory, threads, uploads, chat tabs, runtime settings, the SQLite
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
The background scheduler is single-instance by default. For a multi-pod deployment, set `scheduler.multi_instance: true` and use shared Postgres, `run_ownership.heartbeat_enabled: true`, and `run_events.backend: db`; startup and periodic recovery then preserve live peer runs, atomically take over only expired leases, and fence stale post-launch writes. `max_concurrent_runs` is a shared global cap across Pods, including short-lived dispatch reservations. Without those settings, enable the scheduler on exactly one Gateway pod. These scheduler fields are startup-only; restart all Gateway Pods together when changing them.

### Upgrade Notes

- Before upgrading a deployment with `GATEWAY_WORKERS > 1` and `scheduler.enabled: true`, either keep the scheduler on exactly one Gateway worker or configure `scheduler.multi_instance: true` with shared Postgres, `run_ownership.heartbeat_enabled: true`, and `run_events.backend: db`. The upgraded Gateway rejects the unsafe combination at startup instead of starting silently.
- In multi-instance mode, `scheduler.max_concurrent_runs` is a cluster-wide cap, not a per-Pod cap. It includes active scheduled runs and short-lived dispatch reservations, so capacity does not multiply with the number of replicas.
- `scheduler.multi_instance` and the related scheduler, ownership, and run-event settings are startup-only. Apply changes with a coordinated restart of all Gateway Pods; changing the ConfigMap alone does not activate multi-instance recovery.

## Terminal Workbench (TUI)

`deerflow` is a terminal-native workbench for people who live in the shell. It runs **embedded** over `DeerFlowClient` — no Gateway, frontend, nginx, or Docker required — while honoring the same `config.yaml`, checkpointer, skills, memory, MCP, and sandbox settings as the rest of DeerFlow.

![DeerFlow TUI](docs/tui/tui-preview.svg)

```bash
uv pip install 'deerflow-harness[tui]'        # optional 'textual' dependency

deerflow                                      # launch the terminal UI (TTY required)
deerflow --tui-transparent                    # use the terminal's default background
deerflow --continue                           # resume the most recent thread
deerflow --resume THREAD                      # resume a thread by id
deerflow --print "summarize this repo"        # headless one-shot answer to stdout
deerflow --json  "hello"                       # headless newline-delimited StreamEvents
deerflow --recursion-limit 250 --print "task" # override the headless agent-loop limit
```

A keyboard-driven chat surface with a streaming transcript (Markdown-rendered answers), compact tool-activity cards, a `/` slash-command palette, display-only `/clear`, `/goal` goal management, `/model` and `/threads` pickers, input history, and `Esc` / `Ctrl+C` interrupt. `/clear` removes rows from the current terminal display without deleting the thread or its persisted conversation; `/new` and `/clear` ask you to wait during an active run instead of resetting in-flight display state. Sessions opened in the TUI also appear in the Web UI sidebar — it writes the shared thread store under the local default user, so terminal and web stay in sync **without running the Gateway**.

See [backend/docs/TUI.md](backend/docs/TUI.md) for the full guide.

## Documentation

- [Contributing Guide](CONTRIBUTING.md) - Development environment setup and workflow
- [Configuration Guide](backend/docs/CONFIGURATION.md) - Setup and configuration instructions
- [Architecture Overview](backend/CLAUDE.md) - Technical architecture details
- [Backend Architecture](backend/README.md) - Backend architecture and API reference

## ⚠️ Security Notice

### Improper Deployment May Introduce Security Risks

DeerFlow has key high-privilege capabilities including **system command execution, resource operations, and business logic invocation**, and is designed by default to be **deployed in a local trusted environment (accessible only via the 127.0.0.1 loopback interface)**. If you deploy the agent in untrusted environments — such as LAN networks, public cloud servers, or other multi-endpoint accessible environments — without strict security measures, it may introduce security risks, including:

- **Unauthorized illegal invocation**: Agent functionality could be discovered by unauthorized third parties or malicious internet scanners, triggering bulk unauthorized requests that execute high-risk operations such as system commands and file read/write, potentially causing serious security consequences.
- **Compliance and legal risks**: If the agent is illegally invoked to conduct cyberattacks, data theft, or other illegal activities, it may result in legal liability and compliance risks.

### Gateway Admin Is Equivalent to Code Execution

An admin can register stdio MCP servers, which run commands inside the Gateway
container. The API restricts them to an allowlist (`npx`, `uvx` by default,
extended via `DEER_FLOW_MCP_STDIO_COMMAND_ALLOWLIST`) and rejects arguments and
environment variables that would evaluate arbitrary code. That is defense in
depth, not a boundary: these launchers exist to fetch and run remote packages,
so **treat Gateway admin as equivalent to code execution on the host** and grant
it accordingly.

### Deployment Defaults

The Docker stack publishes its entry port on `127.0.0.1` only, matching the
local-trusted-environment model described above. To reach it from another
machine, set `BIND_HOST` in `.env` (e.g. `BIND_HOST=0.0.0.0`) — and only after
putting the security measures below in place.

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

Backend `make test` is offline by default and excludes live external-API
coverage. Maintainers can explicitly run the real `DeerFlowClient` integration
suite with `cd backend && make test-live` after providing a valid root
`config.yaml` and API credentials; this may incur API costs and create local
sandboxes, artifacts, or files. Direct pytest runs additionally require
`DEER_FLOW_RUN_LIVE_TESTS=1`.

Regression coverage includes Docker sandbox mode detection and provisioner kubeconfig-path handling tests in `backend/tests/`.
Backend blocking-IO diagnostics are available from the repository root with
`make detect-blocking-io`: it statically scans backend business code for
blocking IO that may run on the backend event loop, prints a concise summary,
and writes complete JSON findings to `.deer-flow/blocking-io-findings.json`.
The JSON includes compact review records with `priority`, `location`,
`blocking_call`, `event_loop_exposure`, `reason`, and `code`.
Gateway artifact serving now forces active web content types (`text/html`, `application/xhtml+xml`, `image/svg+xml`) to download as attachments instead of inline rendering, reducing XSS risk for generated artifacts.

Frontend route asset budgets can be checked with `cd frontend && pnpm
perf:check`. The command measures `/login` from a normal production build, then
performs a production static-demo build for the fixture-backed workspace routes.
It measures the unique JavaScript and CSS referenced by representative routes
and writes the detailed result to `.next/performance-results.json`.

## License

This project is open source and available under the [MIT License](./LICENSE).

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
