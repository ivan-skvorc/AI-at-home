# Companion apps — StocktonRich and FrontalRobotomy

The design behind roadmap items 40–42. Read this before dispatching any of them.
The items are the units of work; this file is the contract they share, including
the look, so two agents don't invent two themes.

Nothing here is built yet. StocktonRich and FrontalRobotomy stay their own
repositories and their own processes. This fork does not absorb their code, and
it does not start training models. That last point is already a decision — see
[roadmap.md](../roadmap.md), *Deliberately not on this roadmap*, "Fine-tuning or
LoRA training on the host". Items 40–42 do not reverse it.

## What is being united

| App | Repo | What it is | How you open it today |
| --- | --- | --- | --- |
| **AI-at-home** | this fork of [bytedance/deer-flow](https://github.com/bytedance/deer-flow) | The chat, the agents, the model list, the Grok sign-in | Nginx on port 2026, over Tailscale |
| **StocktonRich** | [ivan-skvorc/StocktonRich](https://github.com/ivan-skvorc/StocktonRich) (private) | newsdesk, the newsroom and stock-picking assistant, plus insider, the bills and lobbying ledger, in the same image | newsdesk on `127.0.0.1:2028`, insider on `127.0.0.1:2029` (Tailscale Serve on 8029). Glance reads newsdesk's status bar |
| **FrontalRobotomy** | [ivan-skvorc/FrontalRobotomy](https://github.com/ivan-skvorc/FrontalRobotomy) (private) | Tunes small open models into coding specialists. The page scores and trains; a real GPU run through it is still ahead | Loopback `127.0.0.1:8742`. `compose.yaml` is the page on the home server |

insider is not a third splash button. It already lives inside the StocktonRich
stack and already shares newsdesk's look. One Stockton button opens newsdesk;
insider stays a page in that app.

## Where it runs

Two machines, and they are not interchangeable.

**The home server** is the always-on box StocktonRich's compose already targets:
stacks under `/srv/docker/`, Tailscale Serve, Glance, the 05:30 image updater,
egress through NordVPN. It serves pages. It does not hold the GPU.

**The daily PC** is where Ollama and training run: an i9-12900K, 64 GB of RAM,
and an RTX 3090 (24 GB). newsdesk's example config already points Ollama at
that PC over the tailnet, sizes windows against `ollama.vram_gb: 24`, and
keeps `num_parallel: 1` because the card serves one model at a time. The big
local model in that example is `gpt-oss:120b` and the small one is
`gemma4:26b`. A 120B does not fit in 24 GB, so it offloads; the 64 GB of system
RAM is what makes that offload possible. Don't move those jobs onto the home
server to "simplify".

Because the Ollama daemon is on another machine, this fork cannot see the card.
`detect_dedicated_vram_gb` only measures a daemon on loopback (FORK.md, the
context-sizing section). The 24 GiB budget has to be set — `ollama.vram_gb`, or
Settings → Models → *Local GPU memory* — or every local window falls back to
the flat clamp. Item 42's setup step is that setting, not a new detector.

**vast.ai** is a third place, and only for a training step that does not fit
the 3090. FrontalRobotomy [roadmap item 13](https://github.com/ivan-skvorc/FrontalRobotomy/blob/main/ROADMAP.md)
already specifies it: the training step only, a spending cap, the instance
destroyed when the run ends, nothing from `.env` copied onto the rented
machine. It stays last there. Don't build a second vast.ai client here.

**APIs** are for inference. A cloud or subscription model answering a chat, a
newsdesk job, or (later) FrontalRobotomy's orchestrator is the model plane in
item 40. Training data does not go out to an API.

## What is already shared, and what only looks shared

newsdesk already *reads* this fork, it does not *use* it:

- Cloud names, ids and prices come from the **published** `config.example.yaml`
  (`models.catalog_url` in newsdesk's example config), parsed out of the
  `auto-model-config` blocks by `newsdesk/llm/catalog.py`. A model that exists
  only in the live `config.yaml`, a subscription model, or a block the sync
  uncommented locally is invisible until somebody ports it.
- Each provider's address is pinned again in newsdesk, on purpose, so a hostile
  catalog can't redirect a key. Keep that property.
- The call itself is a second client: `newsdesk/llm/ollama.py`,
  `openai_compat.py`, `responses.py` (`use_responses_api`), `claude.py`, and
  `subscriptions.py`. The subscription endpoints, client ids and scopes are
  copied from FORK.md §41, and the Grok Responses-only path from §43. They
  drift; newsdesk's model audit exists to notice.
- Grok sign-in is a second grant, in `state/secrets/subscriptions.json`. This
  fork's grant lives in its own subscription store
  (`deerflow/models/subscriptions.py`). Two sign-ins lapse on different days.
- Keys can be pasted on newsdesk's Settings page into
  `state/secrets/api_keys.env`. This fork's keys live in `.env` and
  `config.yaml`. Two copies.

FrontalRobotomy shares less. It talks to Ollama through
`frontalrobotomy/ollama/client.py` and has no `config.yaml`, no API keys and no
Grok sign-in. Its teacher is an Ollama model. The big model that will one day
conduct the specialists is FrontalRobotomy roadmap item 12, and it is not built.
When it is, it should be a name from this fork's list, not a third client.

## Item 40 — one model plane

The satellites name a model. This fork performs the call. They never see a key
or a subscription token.

**The transports that already exist, and that the call must keep choosing
from the model entry rather than from the caller:**

| `use` | When |
| --- | --- |
| `langchain_openai:ChatOpenAI` | OpenAI-compatible chat completions, including xAI's API and OpenRouter |
| the same, with `use_responses_api: true` and `output_version: responses/v1` | GPT-6, whose tools 400 on `/v1/chat/completions` (`deerflow/models/factory.py`) |
| `langchain_anthropic:ChatAnthropic` | Claude |
| `langchain_google_genai:ChatGoogleGenerativeAI` | Gemini's native SDK |
| `langchain_ollama:ChatOllama` | The PC. `num_ctx` is the window the sync already sized |
| `deerflow.models.subscription_providers:GrokSubscriptionChatModel` | The Grok plan, through the plan's proxy, with the proxy's routing headers |
| `…:GrokResponsesSubscriptionChatModel` | A Grok model whose `apiBackend` is `responses`. Only once the grant has been shown to reach `api.x.ai`. The proxy's routing headers do not go there |
| the ChatGPT and Kimi Code subscription classes beside those | The other two sign-ins Settings already offers |

A caller that picks the transport itself will get the split newsdesk has now:
chat completions for a model that only answers on the Responses API, or a Grok
model that only exists on xAI's own API and never appears.

**The call the satellites actually need** is not a raw prompt. newsdesk's
router (`newsdesk/llm/router.py`) sends messages, optional tools, and a JSON
schema it checks itself, with one retry that includes the validation error; chat
streams; portfolio import needs vision. FrontalRobotomy's scorer sends a task
and reads the answer. Budgets, fallbacks, "the PC is off, skip the step", and
which role uses which model stay in newsdesk — they are product policy, not
transport. Prices, so those budgets mean anything, come back with the model.

**Secrets.** One `.env`, one subscription store, one Grok device sign-in, on
this fork's Settings page. newsdesk stops accepting pasted provider keys and
stops offering its own ChatGPT / Grok / Kimi sign-in once it can call through.
Until that cutover, do not delete the second grant; a half-migrated night run
should still have a model.

**The endpoint** is loopback-only, on the Gateway, and it is not a public
completion API. The satellites are the only callers, over the home server's
docker network or over localhost, with a credential that is not an API key and
is not the user's Tailscale header. A model name that isn't in the resolved
list is a 404, not a pass-through to a URL the caller supplies. Provider
addresses stay pinned inside this fork exactly as they are pinned now.

**Do not** mount `config.yaml` into the other containers so they can read the
keys. That is a second copy with a shorter path, and it throws away the "pinned
address" guarantee the moment a satellite parses `base_url` and calls it.

## Item 41 — the welcome screen, and one look

### Where the buttons go

The splash is the empty chat: `Welcome` in
`frontend/src/components/workspace/welcome.tsx`, rendered from
`frontend/src/components/workspace/chats/chat-instance.tsx` while
`isWelcomeMode` is set. Opening the app lands on `/workspace/chats/new`, which
is that screen. Two buttons under the greeting: **Stockton** and **Frontal
Robotomy**. Absent when their URLs are not configured, so an upstream-shaped
install shows nothing.

Not the marketing page at `frontend/src/app/page.tsx`. That page is forced dark
(`ThemeProvider` sets `forcedTheme` when `pathname === "/"`) and it is upstream's
landing, with the galaxy hero. A personal launcher there is a merge conflict
every sync, and it cannot follow the light theme because the theme is forced.

On a phone (roadmap item 18's 390px), the buttons sit with the greeting, wrap,
and do not cover the input. They open in a new tab. Replacing the chat with a
training page is not a launcher.

### How the other app is reached

Prefer a path on this fork's own origin, proxied by nginx
(`docker/nginx/nginx.conf` and `nginx.local.conf`, and the dev config beside
them): `/apps/newsdesk/` and `/apps/frontal/`. One origin means one Tailscale
certificate and a theme the button can actually hand over.

newsdesk refuses every page except `/healthz` without a `Tailscale-User-Login`
header, and it checks the origin of every POST. The proxy must forward that
header, and must not "fix" newsdesk by turning the check off. If the proxy
strips the header, the button opens a login wall and the integration has
failed. insider is not proxied separately; it stays on its own Serve port,
linked from newsdesk as it is today.

FrontalRobotomy binds loopback and has no login. Proxying it is what keeps it
off the LAN. Do not publish `8742` to do this.

The URLs are operator config in `config.yaml` (where the other things that
cause code to run already live — not in `extensions_config.json`). Empty means
the button is absent.

### Light and dark

This fork's appearance setting is `system`, `light` or `dark`, stored by
`next-themes` (`frontend/src/components/theme-provider.tsx`,
`attribute="class"`, `enableSystem`). The class `.dark` is what
`frontend/src/styles/globals.css` keys off. The choice is explicit. Following
the operating system only is the *system* option, not the whole feature.

Both satellites follow the operating system only, via
`prefers-color-scheme`. newsdesk's tokens are in
`newsdesk/web/static/app.css`. FrontalRobotomy's are in
`frontalrobotomy/app/static/style.css`. Neither can see this fork's
`localStorage`, and they won't be able to even after the proxy unless they
read a signal the welcome button writes.

**The signal.** The welcome button (and this fork's existing theme toggle)
writes a cookie, `deerflow-theme=light|dark|system`, on the home server's host.
Cookies ignore port, so a page that is still opened on `:2028` during the
cutover still sees it. `system` means honour `prefers-color-scheme`. A stored
`light` or `dark` wins over the operating system, including when they disagree.
Each satellite also gets a small theme control that writes the same cookie, so
changing it inside Stockton changes the next empty chat, and the reverse.

**Do not** import Tailwind, shadcn, or `globals.css` into the Python apps. Copy
the values. The fonts already agree: this fork's `--font-sans` is
`ui-sans-serif, system-ui, sans-serif`, and both satellites already use
`system-ui`. Leave it.

Tokens to share, taken from `:root` and `.dark` in `globals.css`. The oklch
values are the source; the hex is only so a stylesheet without oklch can match
them. Re-read the oklch before copying, and don't invent a third pair.

| Role | Light | Dark | Satellite variable |
| --- | --- | --- | --- |
| Page | `oklch(0.9855 0.0098 87.47)` warm paper | `oklch(0.24 0.0036 106.64)` warm charcoal | `--bg` |
| Text | `oklch(0.145 0 0)` | `oklch(0.985 0 0)` | `--fg` |
| Card | `oklch(1 0.0098 87.47)` | `oklch(0.238 0.0036 106.64)` | `--card` (newsdesk uses the page today; give cards the card) |
| Muted text | `oklch(0.556 0 0)` | `oklch(0.708 0 0)` | `--muted` |
| Line / border | `oklch(0.922 0.0098 87.47)` | `oklch(1 0 0 / 10%)` | `--line` |
| Button fill | black (`--primary`) | white | the primary action |
| Button text | white | near-black `oklch(0.205 0 0)` | on that button |
| Focus ring | `oklch(0.58 0.18 255)` | `oklch(0.74 0.16 255)` | focus only, not a brand colour |

Radius for chrome (header buttons, fields, cards) is `--radius: 0.625rem`.
newsdesk is squarer (2–4px) and FrontalRobotomy is `0.375rem` / `0.5rem`. Move
the chrome to `0.625rem`. Don't round the charts to match.

**What does not change:**

- newsdesk's status colours (`--green`, `--amber`, `--red`) and the eight
  dataviz series `--s1`…`--s8`. Those were checked for contrast on both
  backgrounds (`app.css` says so). Remapping them onto `--chart-1`…`--chart-5`
  would throw that check away. Sit them on the new background and re-check
  contrast; don't recolour them for fashion.
- FrontalRobotomy's semantic `--ok`, `--warn`, `--bad`, `--skip`. Same rule.
- FrontalRobotomy's indigo accent (`#4338ca` / `#a5b4fc`) goes. This fork's
  primary is black in the light theme and white in the dark, not a brand hue.
  A second accent is how the apps drift back apart.
- The marketing landing stays forced dark. Out of scope.
- Don't add the aurora, the wave, or the galaxy to either satellite. This
  fork already switches those off under reduced motion; the satellites should
  not grow motion to look related.

Header shape, so they read as the same family: a bottom border in `--line`,
the wordmark at weight 600, the current page an underline (newsdesk) or weight
600 (FrontalRobotomy) — pick the underline, it's already the quieter of the
two. Muted links for the utility pages (Runs, Settings, doctor). No new
illustration.

## Item 42 — one card, one turn

Three locks exist and none of them sees the others.

| Lock | Where it lives | What it stops |
| --- | --- | --- |
| newsdesk and insider `ollama.gpu_lock_file` (a flock on `/shared/gpu.lock` inside the server containers) | The home server's disk | newsdesk and insider using the PC at the same moment |
| This fork's GPU arbiter (`community/comfyui/arbiter.py`) and the local-model residency gate (`deerflow/subagents/local_residency.py`) | In the Gateway process | ComfyUI and a local subagent sharing a card **this process can see** |
| `frontalrobotomy/gpu.py` | Inside that one process | Two of its own jobs. Training also unloads Ollama on the PC before it starts |

A training run is Unsloth in Docker **on the PC**, for hours. The server-side
flock is not on that machine, so it does not stop the run, and the run does
not stop a chat. Both then sit on the 3090. That is the failure item 42
closes.

The lock has to be on the PC, because that is where the card is. Holders:

- every Ollama call, whoever started it (this fork, newsdesk, insider,
  FrontalRobotomy's scorer and teacher);
- a training or conversion container FrontalRobotomy starts there;
- ComfyUI, if it is running on that same card. If ComfyUI stays on the home
  server it is not part of this lock, and it also has no GPU, so don't leave
  it there and expect pictures.

A chat waits, and says it is waiting. It does not time out into a second copy
of the model and it does not unload a training run to get an answer. Training
already waits on its own lock; it must also wait on this one, and it must take
the lock before it unloads Ollama, not after. The kernel releases the lock if
the holder dies — newsdesk already relies on that, keep it.

`OLLAMA_NUM_PARALLEL` stays 1. A lock that serializes callers and a daemon that
loads two models is the same bug with extra steps.

vast.ai does not take this lock: the rented card is not the 3090. An API call
does not take it either.

## What not to do

- Don't vendor either repository into this one, and don't rewrite either app
  in Next.js to "make the integration real".
- Don't add a third model list, a third Grok login, or a `base_url` the
  satellite gets to choose.
- Don't put the buttons on `/`.
- Don't publish a new port. The home server's rule, in both stacks, is
  loopback plus Tailscale.
- Don't send training data, newsdesk's database, or subscription tokens to
  vast.ai or to a cloud model.
- Don't treat item 12 of FrontalRobotomy (the orchestrator) or item 13 (vast.ai)
  as cancelled. Item 40 is how the orchestrator gets its big model. Item 13
  stays the rented-GPU plan.
