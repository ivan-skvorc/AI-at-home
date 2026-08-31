# Model audit log

A dated record of every [model audit](../FORK.md#the-model-bundle-and-its-audit)
pass: what was checked, which providers the network could actually reach, and
what changed. It lives here rather than in FORK.md because FORK.md is
instructions and this is a record — but it is the record you read *first*, since
the audit is deliberately opt-in and "when did anyone last look?" is the question
that decides whether to run one.

Newest first. Append a pass; never rewrite one. A dated line is what tells the
next person whether the roster was checked last week or last year, and *which*
providers that pass could actually reach.

- **2026-08-31 (ComfyUI-on-by-default change) — mechanical half only; no model config touched, no
  figure changed.** Run because the accompanying change set was asked to "run the tests from FORK.md
  including the model audit". The change itself is media/tooling (`config.example.yaml`'s `media`
  tool entries, launch provisioning, a models CLI, a frontend button); it touches **no** `models:`
  entry, `price:` or `discount:` block, so the roster was not in scope on its own merits.

  **Reachability: unchanged and still limited.** `openrouter.ai` is refused at the egress proxy
  (403 at CONNECT), which is the only machine-readable catalog in the bundle — `audit_models.py`
  correctly reports it as *skipped* rather than as drift, so **its "no drift detected" is not
  evidence the OpenRouter roster is current**. Every other provider is documented as having no
  machine-readable catalog and is covered by the manual pass.

  **Mechanical half: clean.** `scripts/audit_models.py` reports no drift (with the skip above); the
  stale-fixture self-test (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still
  surfaces all four drift kinds; the `price_in_display_name` grep over both sources prints nothing;
  `sync-api-key-models.py --dry-run` leaves the file byte-identical on an empty env. The regression
  gate (`test_audit_models.py`, `test_sync_api_key_models.py`, `test_setup_wizard.py`,
  `test_config_integrity.py`) is green at **192 passed**, and the full backend suite at **14684
  passed, 87 skipped**.

  **No tier-1 pass was re-run.** The 2026-08-30 entry below is one day old, covered the same
  reachability, and read all six Claude entries off Anthropic's own page; re-deriving an unchanged
  roster a day later is exactly the cost FORK.md says not to pay. The next pass that has a reason to
  run (drift reported by the weekly job, or a change that touches the bundle) should still start from
  that entry's open items, not from this one.

- **2026-08-30 (upstream sync) — Anthropic re-verified at tier 1; DeepSeek's peak/off-peak split
  settled enough to explain the shipped figure, and the "make the two halves agree" instruction
  retired as wrong; no price or roster change.** Run because it was asked for, alongside the
  upstream merge of 32 commits (which touched `config.example.yaml`'s model section, so the bundle
  was in scope either way).

  **Reachability: unchanged from the last pass.** `platform.claude.com` answers, so all six Claude
  entries were read straight off Anthropic's own pricing page. Every other provider host is refused
  at the egress proxy — `openrouter.ai` (403 at CONNECT, which `audit_models.py` correctly reports
  as *skipped* rather than as drift), plus `www.anthropic.com`, `platform.openai.com`,
  `ai.google.dev`, `api-docs.deepseek.com`, `docs.z.ai`, `docs.x.ai` and `platform.moonshot.ai`.
  General web **search** was available and carried the tier-2 work below; fetching the pages it
  surfaced was itself blocked, so those rest on search results, not on the pages.

  **Mechanical half: clean.** `scripts/audit_models.py` reports **no drift**; the stale-fixture
  self-test (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still surfaces all four
  drift kinds; the `price_in_display_name` grep over both sources prints nothing;
  `sync-api-key-models.py` enables the `anthropic` block on a dry run against a copy and leaves the
  file byte-identical on an empty env. The regression gate (`test_sync_api_key_models.py`,
  `test_setup_wizard.py`, `test_config_integrity.py`, `test_audit_models.py`,
  `test_model_price_fields.py`, `test_pricing.py`) is green at **275 passed**.

  **Anthropic: verified, no change.** All six bundled Claudes match the provider's table exactly —
  Fable 5 `$10/50`, Opus 5 `$5/25`, Opus 4.8 `$5/25`, Sonnet 5 `$2/10`, Sonnet 4.6 `$3/15`, Haiku 4.5
  `$1/5` — as do all six 0.1x cache-read rates. Sonnet 5's `$2/10` is still stated as the standard
  price with the September 1 increase cancelled, which is what the entry's comment already says. The
  roster shape is correct as-is: the page now lists Opus 4.8/4.7/4.6/4.5 and Sonnet 4.6/4.5, and the
  last-4.x rule keeps exactly Opus 4.8 and Sonnet 4.6; Haiku and Fable keep only their latest, and
  Mythos 5 stays out (still limited-availability). Two page changes worth noting and *not* acting on:
  **fast mode** now prices Opus 5 / 4.8 at `$10/50`, and Claude 4.7-and-later use a tokenizer that
  produces ~30% more tokens for the same text. Neither is a per-token rate change — fast mode is an
  opt-in premium the bundle does not request, and a tokenizer shifts token *counts*, which the
  cost totals already measure — so no `price:` block moves.

  **DeepSeek: the open item from 2026-08-29 is half-settled, and no figure changed.** Several
  independent search-tier sources now agree exactly on the structure and both numbers: since
  **2026-08-16 16:00 UTC**, V4-Pro bills `$1.32/3.96` during peak hours (01:00–04:00 and 06:00–10:00
  UTC, weekdays) and `$0.66/1.98` off-peak, with off-peak described everywhere as *half of peak* — so
  peak is the reference rate and off-peak the automatic discount. The home block already ships
  `$1.32/3.96`, i.e. the reference rate, which is what the Grok 4.6 precedent asks for (one `price:`
  field carries the standard rate, never the special band) and what tier 2 permits (a discount is
  never shipped from secondary sources). **So the home block is right as shipped, and now has a
  recorded reason rather than a coincidence.**

  **The instruction the last pass left — "make the two halves of the doubled model agree" — was
  itself wrong, and is retired here.** The OpenRouter twin ships `$0.44/0.87` against the home
  block's `$1.32/3.96`, and the last pass read that as one model with two prices. It is not: the two
  entries bill through two different channels, and FORK.md's own rule is that an OpenRouter entry's
  authoritative page *is* its OpenRouter page, "because OpenRouter's rate is what the entry bills
  at". Two halves of a doubled model are required to name the same *model*, never the same *price*.
  What is genuinely owed is narrower: confirm what OpenRouter bills for `deepseek/deepseek-v4-pro`
  today. Search suggests it still lists the pre-August-16 `$0.435/0.87`, but that is a single
  unverifiable claim about a page tier 1 owns, so **nothing was changed**.

  **No roll-forward due.** A release sweep found nothing newer than the bundle's flagships: the most
  recent releases are GLM-5.3 Flash (2026-08-26, a cheaper sibling, not a flagship — and the same
  model upstream added a *commented* example profile for in this merge), Gemini 3.7 Flash
  (2026-08-13) and DeepSeek's multimodal V4 (2026-08-21). Grok 4.6, Qwen3.8 Max, GLM-5.3 and Mistral
  Medium 3.5 remain current, and remain **corroborated rather than verified** — still owed to the
  next unrestricted pass.

  **All four prose copies no test reads were read by eye and are correct this pass**
  (`providers.py`'s nine home `description=` strings, `config.example.yaml`'s QUICK START, the sync
  script's QUICK START docstring, and the README §2 bullet), as are `.env.example`'s eleven provider
  key lines. Every one matches its block's actual lineup.

  **Structure, unchanged:** 41 bundled paid models, every one carrying a `price:` block; 11 marker
  blocks in the prescribed order (Anthropic → OpenRouter → the nine home blocks); the doubling holds
  for all nine home flagships; all 13 OpenRouter entries carry `(p)` and no direct, home or Ollama
  entry does. The one live discount (`openrouter-minimax-m3`, `$0.24/0.96`) still has no `until` and
  MiniMax's promotions page is unreachable, so it stays as shipped.

  **Still owed to the next unrestricted pass**, in priority order: what OpenRouter actually bills for
  `deepseek/deepseek-v4-pro`; the four corroborated figures (Grok 4.6, Qwen3.8 Max, GLM-5.3, Mistral
  Medium 3.5); the Gemini 3.7 Flash roster decision; MiniMax M3's promo status; and Google's shape
  problem — its OpenRouter double is still Gemini 3.6 Flash, a cheaper sibling, so the "every
  flagship doubled home + OpenRouter" rule does not hold for the one lab whose flagship
  (Gemini 3.1 Pro) is home-only.

- **2026-08-29 — Anthropic re-verified at tier 1; the four corroborated roll-forwards re-checked and
  unchanged; one stale prose copy fixed; no price or roster change.** Run because it was asked for,
  alongside a README edit — not a sync, and not a drift report from the weekly job.

  **Reachability.** `platform.claude.com` answers, so all six Claude entries were read straight off
  Anthropic's own pricing and models pages. Every other provider host is refused at the egress proxy:
  `openrouter.ai` is blocked by name (403 at CONNECT, which is exactly what `audit_models.py` reports
  as *skipped* rather than as drift), and `www.anthropic.com`, `platform.openai.com`, `ai.google.dev`,
  `api-docs.deepseek.com` and `docs.z.ai` all return the same refusal. General web **search** was
  available and was used for the tier-2 re-checks below; fetches of the tracker pages it surfaced were
  themselves blocked, so those re-checks rest on search results rather than on the pages.

  **Mechanical half: clean.** `scripts/audit_models.py` reports **no drift** (display-name/`price:`
  agreement and two-source parity both hold); the stale-fixture self-test
  (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still surfaces all four drift kinds;
  the `price_in_display_name` grep over both sources prints nothing; `sync-api-key-models.py` enables
  the `anthropic` block on a dry run against a copy and leaves the file byte-identical on an empty env.
  `cd backend && make lint && make test` is green (**14032 passed, 80 skipped**) with no `config.yaml`
  on disk, `uv lock --check` is in sync, and frontend `pnpm format` / `pnpm check` / `pnpm test`
  (1367 passed) are green.

  **Anthropic: verified, no change.** All six bundled Claudes still match the provider's table exactly
  — Fable 5 `$10/50`, Opus 5 `$5/25`, Opus 4.8 `$5/25`, Sonnet 5 `$2/10`, Sonnet 4.6 `$3/15`, Haiku 4.5
  `$1/5` — as do the 0.1x cache-read rates each entry carries. The ids are current (`claude-fable-5`,
  `claude-opus-5`, `claude-sonnet-5`, `claude-haiku-4-5`; the dateless `claude-opus-4-8` and
  `claude-sonnet-4-6` are the right form for the 4.6-generation-and-later scheme). Anthropic's page now
  settles the Sonnet 5 question outright: the `$2/10` introductory rate **is** the standard price and
  the September 1 increase to `$3/15` **will not occur** — which is what the entry's comment already
  says, so nothing changed. Roster shape is correct as-is: Opus keeps 4.8 + 5 and Sonnet keeps 4.6 + 5
  (Opus 4.7 / 4.6 / 4.5 and Sonnet 4.5 are all still listed as available and all correctly excluded by
  the last-4.x rule), Haiku and Fable keep only their latest, and Mythos 5 stays out because it is
  still limited-availability.

  **The four 2026-08-20 roll-forwards: re-checked at tier 2, all four agree with what is shipped.**
  Grok 4.6 `$2/6` (the base tier — the 200K long-context band still doubles the whole request, and the
  block carries the base rate on purpose), Qwen3.8 Max `$2/6`, GLM-5.3 `$1.4/4.4` and Mistral Medium 3.5
  `$1.5/7.5`. None could be read off its provider's own page, so all four **stay corroborated, not
  verified**, and remain owed to the next unrestricted pass.

  **One finding, deliberately left alone: the DeepSeek home block and its OpenRouter twin disagree by
  3x.** `deepseek-v4-pro` ships at `$1.32/3.96` on the home block and `$0.44/0.87` on OpenRouter — one
  model, two prices. Two independent search-tier sources agree that DeepSeek's current rate is
  `$0.435/0.87`, but both also report that since **2026-08-16** DeepSeek bills by time of day: peak
  hours (01:00–04:00 and 06:00–10:00 UTC) cost double the off-peak rate, and one puts V4-Pro's peak
  output at exactly the `$3.96` the home block already carries. So the shipped pair looks like the peak
  rate and the OpenRouter pair like the off-peak one, and a single `price:` field cannot be both.
  Which tier the bundle should quote is a judgement (the Grok 4.6 precedent says the base rate) that
  needs the provider's own page, and that page is unreachable — so **nothing was changed**. This is the
  first thing the next unrestricted pass should settle: confirm DeepSeek's peak and off-peak numbers,
  decide which tier one `price:` field carries, and make the two halves of the doubled model agree.

  **One stale prose copy fixed.** `scripts/wizard/providers.py`'s OpenRouter `description=` read *"One
  key: Claude Fable/Opus 5 + …"*, but the OpenRouter bundle carries **only** Fable 5 — every other
  Claude is deliberately direct-only. That string is one of the four copies no test reads, and it is
  what `make setup` prints, so it advertised a model the key does not unlock; it now reads *"One key:
  Claude Fable 5 + …"*. The other three prose copies (`config.example.yaml`'s QUICK START, the sync
  script's docstring, the README §2 bullet) and `.env.example`'s eleven key lines were read by eye and
  are correct.

  **Structure, unchanged:** 41 bundled paid models, every one carrying a `price:` block; 11 marker
  blocks in the prescribed order (Anthropic → OpenRouter → the nine home blocks); the doubling holds
  for all ten home flagships (`minimax/minimax-m3` ↔ `MiniMax-M3` modulo case); all 13 OpenRouter
  entries carry `(p)` and no direct, home or Ollama entry does. The one live discount
  (`openrouter-minimax-m3`, `$0.24/0.96`) still has no `until`, and MiniMax's promotions page is
  unreachable, so it stays as shipped.

- **2026-08-27 (upstream sync) — Anthropic re-verified at tier 1; no drift anywhere the network
  could reach; one stale prose copy fixed; no roster change.** Run as the audit step of the
  post-sync checklist for the `bytedance/deer-flow@main` merge of 7 commits, one day after the
  2026-08-26 pass. A pass this close behind another is deliberately a *re-check*, not a
  re-derivation: the standing rule is that a price nobody could read this pass stays as shipped, so
  the value here is in what changed in a day and in the copies no test reads.

  **Reachability — unchanged from the previous pass.** `platform.claude.com` answers, so all six
  Claude entries were read straight off Anthropic's own pricing table. Every other provider host is
  refused at the egress proxy: `openrouter.ai` is blocked by name, and `developers.openai.com`,
  `x.ai`, `ai.google.dev`, `api-docs.deepseek.com`, `docs.mistral.ai` and `platform.moonshot.ai`
  all return no response at all. `audit_models.py` therefore listed openrouter as **skipped**
  rather than as drift, which is the property that must never be "fixed" into its opposite.
  General web search was available and was used for the corroboration re-checks below.

  **Anthropic: verified, no change.** All six bundled Claudes still match the provider's table
  exactly — Fable 5 `$10/50`, Opus 5 `$5/25`, Opus 4.8 `$5/25`, Sonnet 5 `$2/10`, Sonnet 4.6
  `$3/15`, Haiku 4.5 `$1/5` — each with its 0.1x cache-read rate (`1.0 / 0.5 / 0.5 / 0.2 / 0.3 /
  0.1`). The page still carries the note that Sonnet 5's `$2/10` **is** the standard price and that
  the 2026-09-01 rise to `$3/15` will not happen. That note is worth re-reading every pass until
  that date is behind us: the entry's `price:` comment asserts it in prose, and nothing mechanical
  would catch a reversal. Mythos 5 stays out — the table still marks it limited-availability, so a
  normal `ANTHROPIC_API_KEY` cannot reach it. Roster shape unchanged (Opus/Sonnet keep last-4.x +
  current-5, Haiku/Fable latest only).

  **The one new release is a cheaper sibling, not a flagship, so the roster does not move.** z.ai
  shipped **GLM-5.3-Flash** on 2026-08-26, the day after the previous pass. It stays out for the
  same two reasons the 2026-08-22 pass recorded for Gemini 3.7 Flash: it is a cheaper sibling
  rather than the lab's flagship (bundled `glm-5.3` is z.ai's flagship and GLM-4.5 Air already
  fills the cheap seat), and its launch price is an **introductory** one — `$0.075/0.25` through
  2026-09-09 24:00 UTC+8 against a `$0.15/0.50` standard — which tier 2 may not ship. Checking it
  did re-corroborate the bundled **GLM-5.3 at `$1.40/4.40`**, still quoted unchanged.

  **The two owed discounts are still owed, and still deliberately not shipped.** GPT-5.6 Sol's
  promotional **`$4/20`** (standard `$5/30`, stated as running at least through **2026-11-21**)
  was re-confirmed this pass: OpenAI's own model and pricing pages, its developer-community
  announcement, and independent coverage all quote the same pair with no disagreement. It stays
  unshipped anyway, because `developers.openai.com` cannot be reached and *Where a price may come
  from* bars a **discount** from the corroborated tier however many sources agree — the rule is
  about which page was read, not how strong the agreement is. The Gemini Flash introductory
  `$0.75/3.75` is unchanged in status, including the unresolved 3.6-vs-3.7 ambiguity that is its
  second disqualifier. Both stay top of the owed list.

  **One live discount could not be checked at all, and it is the one that can go wrong quietly.**
  The bundle carries exactly one `discount:` block — `openrouter-minimax-m3` at `$0.24/0.96`, with
  no `until` because the provider announced no end date, which is legitimate and deliberately not a
  finding. Confirming it is still running needs OpenRouter's catalog, which is precisely what is
  unreachable, so the audit's *promotion ended* check is skipped for it. Left alone at tier 3, and
  named here because it is the single bundled entry that would keep advertising a discount nobody
  is getting if that promo has quietly ended.

  **Prose copies: six of the seven were current, one was stale and is fixed.** All seven places
  step 2 names were read by eye. `config.example.yaml`'s `QUICK START` comment, the sync script's
  `QUICK START` docstring, `.env.example`, the README §2 bullet and `providers.py`'s
  `HOME_API_BUNDLES` all match the marker blocks exactly. `providers.py`'s **`mistral`
  `LLMProvider`** still read `description="Mistral Large 3 + Medium 3.5 + Small (direct Mistral
  API)"` — the unversioned *Small* that the 2026-08-26 pass corrected in the other copies and
  missed here. It now reads **Small 3**, matching the `mistral-small-3` entry and the other six
  copies. That string is what `make setup` prints and no test reads it, which is exactly why it
  survived a pass that was looking for it.

  **Bundle unchanged at 41 paid models** — 6 Anthropic + 13 OpenRouter + 22 home.

  Mechanical half green: `scripts/audit_models.py` reports **no drift** (display-name/price
  agreement and two-source parity both hold) and correctly lists openrouter as *skipped*; the
  stale-fixture self-test (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still
  surfaces all four drift kinds and exits 0, so this pass's "no drift" is a real all-clear rather
  than a broken audit; `sync-api-key-models.py --dry-run` leaves a copy byte-identical on an empty
  env; the price-in-a-`display_name` grep prints nothing; and `test_sync_api_key_models.py`,
  `test_setup_wizard.py`, `test_config_integrity.py`, `test_audit_models.py`, `test_pricing.py`
  and `test_model_price_fields.py` are green (285 passed).

- **2026-08-26 (upstream sync) — Anthropic verified at tier 1 again; three bundled slugs that
  do not exist found and replaced; three prices corrected, one of them a 3x under-report.** Run as
  the audit step of the post-sync checklist for the `bytedance/deer-flow@main` merge of 3 commits.
  This was the first pass since the roster was assembled where **general web search was available
  at the same time as a tier-1 Anthropic page**, and it turned up a systematic defect the previous
  six passes could not see.

  **Reachability.** `platform.claude.com` answers, so all six Claude entries were read straight off
  Anthropic's own pricing table and *Model IDs and versioning* page. Every other provider host —
  `openrouter.ai`, `developers.openai.com`, `x.ai` / `docs.x.ai` / `api.x.ai`, `ai.google.dev`,
  `platform.moonshot.ai`, `docs.mistral.ai`, `api-docs.deepseek.com` — is refused at CONNECT
  (`403 Forbidden`), and direct page fetches are blocked too. For those labs, **the web-search tool
  could still read the lab's own models/pricing page and quote it**, which is stronger evidence
  than a tracker but is not the same as reading the page by hand; every figure taken that way is
  named below and is corroborated by at least one independent source that agrees exactly.

  **The systematic defect: a "cheaper sibling" invented from the lab's tier naming.** The bundle's
  header comment says non-flagship siblings "follow each lab's established tier naming" — and three
  of them had been *named by that convention rather than read off a catalog*, so they pointed at
  models that do not exist. Each fails at request time, not at load, which is exactly what step 3
  exists to catch, and each carried a price attached to a model nobody can call:

  | Was | Price it carried | Is now | Why |
  | --- | --- | --- | --- |
  | `gpt-5.6-mini` "GPT-5.6 Mini" | $0.25/2 | `gpt-5.6-terra` **+** `gpt-5.6-luna` | GPT-5.6 went GA 2026-07-09 as **Sol / Terra / Luna**, with no `-mini` or `-nano` member. Terra is the tier that took `mini`'s place; Luna sits below it. |
  | `grok-4.5-fast` "Grok 4.5 Fast" | $0.5/1.5 | `grok-4.3` "Grok 4.3" | xAI's own models table lists `grok-4.6`, `grok-4.5`, `grok-4.3`, the `grok-4.20-0309` pair and `grok-build-0.1` — no `-fast` text model. `grok-4.5` is priced identically to 4.6, so **4.3** ($1.25/2.50, 1M context) is the actual cheaper tier. |
  | `glm-5.2-air` "GLM-5.2 Air" | $0.2/1.1 | `glm-4.5-air` "GLM-4.5 Air" | z.ai's own pricing table ships Air only in the 4.5 generation (GLM-4.5-Air, GLM-4.5-AirX). $0.2/1.1 **is** GLM-4.5-Air's published rate — the price was always right, the id and the name were not. |

  So the price beside a made-up slug is not necessarily made up: it is usually the real price of the
  real model the name was groping for. That is what makes this failure quiet — the numbers look
  plausible and only the request fails. **Step 3's "never from memory" now has to cover the
  sibling as hard as the flagship.**

  **GPT-5.6 Terra and Luna, added.** Terra `$2/12`, Luna `$0.20/1.20`, both the **post-cut** rates:
  OpenAI cut Terra 20% and Luna 80% on **2026-07-30** (from `$2.50/15` and `$1/6`). Figures from
  OpenAI's own model pages (`developers.openai.com/api/docs/models/gpt-5.6-terra` and
  `…/gpt-5.6-luna`, which also give 1.05M context, 128K max output and text+image input),
  corroborated by CNBC, Axios, Reuters and the LLM Gateway changelog stating the same two pairs.
  Both ship `supports_vision: true` and `supports_thinking: true` like the Sol entry beside them;
  Terra takes the block's default 32000 `max_tokens`, Luna the 16000 the old Mini used.

  **DeepSeek re-priced on 2026-08-16 and the bundle was under-reporting by 3x on input and up to 4.5x on output.** DeepSeek
  moved both bundled models onto a **peak / off-peak** schedule (peak 01:00–04:00 and 06:00–10:00
  UTC, Mon–Fri; every other hour, weekends included, is off-peak at half the peak rate) *and*
  raised the underlying rate. The bundle was still carrying the pre-2026-08-16 flat rates:

  | Model | Was (old flat) | Peak | Off-peak |
  | --- | --- | --- | --- |
  | `deepseek-v4-pro` | $0.44/0.87 | **$1.32/3.96** | $0.66/1.98 |
  | `deepseek-v4-flash` | $0.14/0.28 | **$0.44/1.32** | $0.22/0.66 |

  `price:` is a single flat pair, so **both home entries now carry the peak rate**, with the
  off-peak figure in a comment beside each. That is the fork's standing direction of error:
  over-stating cost is corrected by the provider's bill, while under-stating it silently stops a
  `spend_budget:` cap from capping (§10's `TestLocalRunsAreNeverBlocked` has a dark mirror — a cap
  measured against a rate several times too low does not fire). Read off `api-docs.deepseek.com`'s pricing page
  and its change log via search, corroborated exactly by press coverage of the change (TechTimes,
  TechJournal, Zeli) and by independent trackers (pricepertoken, costgoat, aipricing.guru) — all
  quoting the same four pairs and the same peak window. **The OpenRouter copy
  `deepseek/deepseek-v4-pro` was deliberately left at `$0.44/0.87`**: OpenRouter's own rate is what
  that entry bills at, its page is unreachable, and the sources that mention it disagree with each
  other (one quotes `$0.435/0.87` for the bare slug, another `$0.792/2.376`). A disagreement is a
  stop, so it stays and is named below.

  **Kimi K2.6 corrected to `$0.95/4.00`** (was `$1.00/3.00` — output under-reported by 25%).
  Corroborated exactly across Moonshot's own rate card as quoted by several independent trackers
  (Spheron, DeepInfra, pricepertoken, costgoat) with no disagreement.

  **Anthropic: verified, no change.** All six bundled Claudes still match the provider's table
  exactly — Fable 5 `$10/50`, Opus 5 `$5/25`, Opus 4.8 `$5/25`, Sonnet 5 `$2/10`, Sonnet 4.6
  `$3/15`, Haiku 4.5 `$1/5`, each with its 0.1x cache-read rate. The page still carries the note
  that Sonnet 5's `$2/10` is now the standard price and the 2026-09-01 rise to `$3/15` will not
  happen, confirming the 2026-08-25 correction from the other side of that date. All six slugs
  re-checked against *Model IDs and versioning* as well: the 4.6-generation dateless format gives
  `claude-sonnet-4-6` / `claude-opus-4-8` / `claude-sonnet-5` / `claude-opus-5` / `claude-fable-5`
  verbatim, and `claude-haiku-4-5` is the documented short alias for the pre-4.6 snapshot
  `claude-haiku-4-5-20251001`. Roster shape unchanged: Opus 4.7/4.6/4.5 and Sonnet 4.5 are listed
  and deliberately dropped, and Mythos 5 stays out as limited-availability.

  **Three of the four figures owed since 2026-08-20 now agree with their lab's own page:**
  Grok 4.6 `$2/6` (xAI's table, base <200K tier — it doubles to `$4/12` at 200K+, and per the
  standing precedent the block carries the base tier), Qwen3.8 Max `$2/6`, GLM-5.3 `$1.40/4.40`.
  Gemini 3.6 Flash's `$1.50/7.50` standard rate also agrees with Google's page.

  **Two live discounts were found and deliberately *not* shipped.** GPT-5.6 Sol's short-context
  rate was cut to `$4/20` on 2026-08-22, promotional and stated as available at least through
  **2026-11-21** (standard unchanged at `$5/30`); and a Gemini Flash introductory
  `$0.75/3.75` runs through **2026-12-31** against a `$1.50/7.50` standard — though two reads of
  Google's page disagreed about whether that window belongs to **3.6** Flash (the bundled entry) or
  to **3.7** Flash, which is a second reason not to ship it. *Where a price may come from* bars a
  discount that could not be read off the provider's own promotions page **directly**, and neither
  could be, so both entries keep their plain standard rate with no `discount:` block.
  Skipping a discount errs toward over-reporting, which the bill corrects; shipping an unverified
  one under-reports, which nothing corrects. Both are top of the owed list.

  **Everything else: tier 3, left alone.** Mistral Medium 3.5 and Small (sources quote *Medium 3*
  at `$1/3` and several different Small variants — no exact agreement on the bundled entries),
  Qwen3.7 Plus (no tracker publishes a per-token rate), MiniMax M2.7 (sources describe the whole
  M-series sharing one standard tier, which does not reconcile cleanly with the home block carrying
  M3 at list and M2.7 at half), Gemini 3.5 Flash-Lite and 3.1 Pro, and every OpenRouter figure.
  Existence *was* confirmed this pass for `deepseek-v4-flash`, `gpt-5.3-codex`,
  `gemini-3.5-flash-lite`, `mistral-medium-3-5`, `MiniMax-M2.7` and `qwen3.7-plus`, so no bundled
  home slug beyond the three above failed a check — but that is "none found", not "none exist", and
  the thirteen OpenRouter slugs could not be checked at all with the catalog unreachable. Roster currency: the August 2026 releases are Gemini 3.7 Flash
  (2026-08-13) and GLM-5.2 Turbo (2026-08-17); GLM-5.2 Turbo is behind the bundled GLM-5.3, and
  Gemini 3.7 Flash stays out for the two reasons the 2026-08-22 pass recorded — a cheaper sibling
  rather than Google's flagship, on an introductory window tier 2 may not ship.

  **Four prose copies of the roster were stale — two in places step 2 did not name.** The
  2026-08-25 pass fixed `.env.example` and the sync script's `QUICK START` docstring after the
  2026-08-20 roll-forward; it missed the same lineup written twice more. `config.example.yaml`'s
  own `QUICK START` comment at the top of `models:` still advertised **Grok 4.5**, **Qwen3.7 Max**,
  **GLM-5.2** and an unversioned *Mistral Medium / Small*; `providers.py`'s `openai` `LLMProvider`
  carried `description="… + GPT-5.6 Mini"`, which is the string `make setup` prints; and this
  file's own §2 table listed *Mistral Medium / Small* the same way. All four now match
  `config.example.yaml`'s marker blocks, and **step 2 above now names all seven places**, flagging
  the four that are pure prose no test can read.

  **The bundle is 41 paid models** — 6 Anthropic + 13 OpenRouter + 22 home — and every count in
  this file and in `test_sync_api_key_models.py` moved with it.

  Mechanical half green: `scripts/audit_models.py` reports **no drift** before and after the edits
  (display-name/price agreement and two-source parity both hold) and correctly lists openrouter as
  *skipped* rather than as drift; the stale-fixture self-test
  (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still surfaces all four drift kinds
  and exits 0 — the fixture covers only the OpenRouter block, which this pass did not touch, so it
  needed no regeneration; `sync-api-key-models.py` is byte-identical on an empty env and uncomments
  every changed block with the right prices on a per-key copy; the price-in-a-`display_name` grep
  prints nothing; and `check_config_version.sh` is OK at 43 — the edits change list entries and
  values, not keys, so no bump was due.

  **Still owed to the next pass that can reach a provider page directly**, in priority order:
  **GPT-5.6 Sol's `$4/20` window through 2026-11-21** and **Gemini 3.6 Flash's `$0.75/3.75` window
  through 2026-12-31** (both live, both knowingly unshipped); the **OpenRouter DeepSeek V4 Pro**
  figure, where two sources disagree and the routed rate may or may not have followed DeepSeek's
  2026-08-16 rise; MiniMax M3's OpenRouter promo status; Mistral Medium 3.5 / Small 3, Qwen3.7 Plus
  and MiniMax M2.7, all left alone for want of agreeing sources; and Gemini 3.1 Pro's `$2/12`,
  corroborated three times and still never verified.

- **2026-08-25 (upstream sync) — Anthropic verified at tier 1 for the first time in six passes;
  one real price change shipped. Every other provider still unreachable, so unchanged.** Run as the
  audit step of the post-sync checklist for the `bytedance/deer-flow@main` merge of 33 commits.
  **Tier 1 was available for exactly one provider:** this environment's egress proxy reaches
  `platform.claude.com`, so all six Claude entries were read straight off Anthropic's own pricing
  table. `openrouter.ai` still answers `403 Forbidden`, and `docs.x.ai`, `ai.google.dev`,
  `platform.moonshot.ai`, `docs.mistral.ai`, `platform.openai.com` and `api-docs.deepseek.com` are
  all blocked outright, so no other figure could be verified.

  **The change: Claude Sonnet 5's introductory rate became its standard price.** Anthropic's
  pricing page now carries a note that the `$2/10` launch rate, announced as introductory through
  **2026-08-31**, is permanent and the scheduled 2026-09-01 rise to `$3/15` will not happen. The
  bundle was still carrying `$3/15` as the standard rate with a `$2/10` discount expiring in six
  days — which would have quietly re-priced every Sonnet 5 thread **upward by 50%** on 1 September,
  against a rate nobody is charged. Both synced sources now carry `input: 2.0`, `output: 10.0`,
  `cache_hit: 0.2` and **no** `discount:` block. This is the failure mode the expiry mechanism is
  supposed to prevent inverted: the window closed *downward*, and a discount that lapses on its own
  gets that case wrong in the expensive direction. Step 5 of the checklist now says to read the
  provider's *note* as well as its table for exactly this reason.

  Verified unchanged against the same page, all six slugs and every price pair: Fable 5 `$10/50`,
  Opus 5 `$5/25`, Opus 4.8 `$5/25`, Sonnet 4.6 `$3/15`, Haiku 4.5 `$1/5`, each with its 0.1x
  cache-read rate. The roster shape is still correct (Opus/Sonnet keep last-4.x + current-5, Haiku
  and Fable latest only) — the page also lists Opus 4.7 and 4.6, which the rule deliberately drops,
  and Mythos 5, which stays out because it is limited-availability and a normal `ANTHROPIC_API_KEY`
  cannot reach it.

  **Every other provider: tier 3, left alone.** No authoritative page and no attempt at tier-2
  corroboration — nothing indicated movement, and a corroborated figure is a debt the next pass has
  to re-check, so it is not worth taking on speculatively. The four flagships rolled forward from
  corroborated sources on 2026-08-20 (Grok 4.6, Qwen3.8 Max, GLM-5.3, Kimi K3) are **still
  uncorroborated at tier 1** and remain the standing target for the next pass that can reach a
  provider page.

  Mechanical half green: `scripts/audit_models.py` reports **no drift** (display-name/price
  agreement and two-source parity both hold) and correctly lists openrouter as *skipped*; the
  stale-fixture self-test (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still
  surfaces all four drift kinds and exits 0; `sync-api-key-models.py --dry-run` is a clean no-op;
  the price-in-a-name grep prints nothing; and `test_config_integrity.py`, `test_model_price_fields.py`,
  `test_sync_api_key_models.py`, `test_setup_wizard.py`, `test_audit_models.py` and `test_pricing.py`
  are green (273 tests). The bundle stays **40** paid models.

- **2026-08-25 (rule addition, not a sync) — mechanical half clean, tier 1 unavailable for the
  sixth pass running, no roster or price change; three stale *descriptions* of the roster fixed.**
  Run while adding **step 2, First-party key coverage** above — the standing rule that every
  big-name lab gets its own `.env` key with a fuller lineup, flagship doubled on OpenRouter —
  and the `TestFirstPartyKeyCoverage` suite that pins its machine-readable half. **Tier 1 remains
  unreachable:** `openrouter.ai` answers `403 Forbidden` through this environment's proxy and the
  eleven first-party hosts are likewise blocked, so no figure was read off a provider's own page
  and **no price or slug was touched** — the roster is byte-identical to the 2026-08-20 pass.
  What *had* drifted was three places that only **describe** the roster, which is exactly the
  failure the new step exists to catch: `.env.example` and `sync-api-key-models.py`'s `QUICK START`
  docstring still advertised **Grok 4.5**, **Qwen3.7 Max** and **GLM-5.2** after the 2026-08-20
  roll-forward to **Grok 4.6 / Qwen3.8 Max / GLM-5.3**, and the README's §2 bullet listed only the
  Anthropic and OpenRouter keys — the nine first-party home keys were undocumented for users.
  All three now match `config.example.yaml`; `MINIMAX_API_KEY` also moved out of the generic
  "OpenAI-compatible" list into the model-provider key section where the other ten live.
  Mechanical half green: `scripts/audit_models.py` reports **no drift** (display-name/price
  agreement and two-source parity both hold) and correctly lists openrouter as *skipped* rather
  than as drift; `sync-api-key-models.py --dry-run` is a clean no-op; and
  `tests/test_sync_api_key_models.py` (47, including the four new ones),
  `test_setup_wizard.py`, `test_config_integrity.py`, `test_audit_models.py` are green.
  Each new test was also confirmed to *fail* on the drift it guards — a key dropped from
  `.env.example`, and a home block removed — so the step is enforced, not merely written down.

- **2026-08-24 (feature PR, not a sync) — mechanical half clean, tier 1 unavailable for the
  fifth pass running, no roster or price change.** Run as the audit step of the checklist while
  adding §21 (concurrent chats), not after an upstream merge. **Tier 1 remains unreachable:** the
  egress proxy still refuses `openrouter.ai` at CONNECT (`Tunnel connection failed: 403
  Forbidden`), and `audit_models.py` listed openrouter as *skipped* rather than as drift — the
  property that keeps this job from becoming a weekly red tick. The other eleven providers have
  no machine-readable catalog and are covered by the manual pass, which needs the same blocked
  pages. **No figure was corroborated this pass either**, because general web search was not
  reachable from this environment; nothing was edited, which is the correct outcome — a price
  written from memory is wrong with confidence and silences the next audit.

  Mechanical half green throughout: `scripts/audit_models.py` reports **no drift** (both offline
  checks hold — every entry's display-name price agrees with its own block, and the two synced
  sources agree with each other); the stale-fixture self-test
  (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still surfaces all four drift
  kinds with suggested diffs and still exits 0 on findings; `sync-api-key-models.py --dry-run` is
  a clean no-op on an empty env; the `display_name`-carries-a-price gate prints nothing; and the
  six model/pricing suites are green (269 passed).

  **Discount review, no change.** Claude Sonnet 5's `$2/10` intro window through **2026-08-31**
  is still open and expires on its own. MiniMax M3's OpenRouter promo still carries no `until` —
  legitimate and deliberately not a finding, and still resolvable only by a reachable promotions
  page.

  **Still owed to the next unrestricted pass**, unchanged from 2026-08-23: Gemini 3.1 Pro's
  `$2/12` (corroborated twice, never verified), the Gemini 3.7 Flash roster decision, the four
  figures in the 2026-08-22 table (Grok 4.6, Qwen3.8 Max, GLM-5.3, Mistral Medium 3.5), and
  MiniMax M3's promo status.

- **2026-08-23 (feature PR, not a sync) — mechanical half clean, tier 1 unavailable again, one
  figure re-corroborated, no roster or price change.** Run as the audit step while adding §20,
  not after an upstream merge. **Tier 1 was unavailable for the fourth pass running:** the egress
  proxy refuses every provider host tried (`openrouter.ai`, `www.anthropic.com`, `api.x.ai`,
  `platform.openai.com`, `z.ai`, `api-docs.deepseek.com`, `ai.google.dev` — all fail at CONNECT),
  and `audit_models.py` correctly listed openrouter as *skipped* rather than as drift. General
  web search **was** reachable, so tier 2 could run.

  Mechanical half green throughout: `scripts/audit_models.py` reports **no drift**; the
  stale-fixture self-test (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still
  surfaces all four drift kinds and still exits 0 on findings; `sync-api-key-models.py --dry-run`
  is a clean no-op on an empty env; the `display_name`-carries-a-price gate prints nothing; and
  the six model/pricing suites are green (269 passed).

  **Gemini 3.1 Pro re-corroborates at the corrected `$2/12`.** That was the single figure the
  2026-08-22 pass changed, so it was the highest-risk entry in the bundle and the one worth
  re-reading first. Independent trackers agree exactly on $2.00 in / $12.00 out for the standard
  tier (≤200K prompts; above that Google bills 2x input / 1.5x output, and per the Grok 4.6
  precedent the `price:` block carries the base tier). Still **corroborated, not verified** — it
  stays top of the owed list.

  **Roster checked for currency, nothing to roll forward.** The August 2026 releases visible from
  tier 2 are Grok 4.6, Qwen3.8-Max, GPT-5.6, Claude Fable 5, Gemini 3.7 Flash, GLM-5.2 Turbo, and
  DeepSeek V4-Pro-0813 GA. Every flagship among them is already bundled; DeepSeek's GA is the
  same `deepseek-v4-pro` id reaching general availability, not a new slug; GLM-5.2 Turbo is behind
  the bundled GLM-5.3; and Gemini 3.7 Flash remains deliberately out for the two reasons the last
  pass recorded (it is a cheaper sibling, not Google's flagship, and its current price is an
  introductory window that tier 2 may not ship). **No entry was edited this pass.**

  **Still owed to the next unrestricted pass**, unchanged in priority from 2026-08-22 minus the
  re-check above: Gemini 3.1 Pro's `$2/12` (now corroborated twice, still never verified), the
  Gemini 3.7 Flash roster decision, the four figures in the 2026-08-22 table (Grok 4.6, Qwen3.8
  Max, GLM-5.3, Mistral Medium 3.5), and MiniMax M3's promo status — a discount never qualifies
  for corroboration, so only a reachable OpenRouter promotions page can resolve it. Claude Sonnet
  5's `$2/10` intro window through **2026-08-31** is still open and expires on its own.

  **One checklist gate caught a real defect in the PR this pass ran alongside.** `config.example.yaml`
  gained an `agent_generation:` section and `config_version` was bumped 40 → 41, but the chart's two
  copies (`deploy/helm/deer-flow/values.yaml` and that chart's `README.md`) were left at 40 —
  exactly the "nothing outside CI reads it" trap the gate exists for. `scripts/check_config_version.sh`
  failed, both copies were bumped, and delivery was then verified end to end on a copy of the
  pre-change example: `config_upgrade.py` reports `+ agent_generation` and stamps 41.

- **2026-08-22 (second pass, upstream sync `f1f4af9`) — corroborated; one price corrected,
  and the four figures the last pass left owed are now cleared.** Provider pages were
  *still* unreachable — `openrouter.ai` and every first-party host answer 403 on CONNECT,
  so **tier 1 was unavailable again and nothing here is verified**. What was different this
  time is that general web search *was* reachable, so tier 2 could actually run instead of
  falling straight through to tier 3. Mechanical half clean, exactly as before:
  `scripts/audit_models.py` reports **no drift**, the stale-fixture self-test
  (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still surfaces all four
  drift kinds, `sync-api-key-models.py --dry-run` is a clean no-op on an empty env, and the
  six model/pricing suites are green (269 passed).

  **The four still-owed figures from 2026-08-20 all corroborate at the shipped numbers** —
  each read off several independent trackers that agree exactly on *both* numbers, none of
  them reprinting a single launch post. No edit was needed for any of them:

  | Model | Shipped | Corroborated | Verdict |
  | --- | --- | --- | --- |
  | Grok 4.6 | $2/6 | $2/6 (base tier; 200K+ prompts bill the whole request at $4/12) | confirmed |
  | Qwen3.8 Max | $2/6 | $2/6 | confirmed |
  | GLM-5.3 | $1.4/4.4 | $1.4/4.4 (z.ai list; resellers quote 10% off the same list) | confirmed |
  | Mistral Medium 3.5 | $1.5/7.5 | $1.5/7.5 | confirmed |

  GLM-5.3 was called out last pass as the most provisional of the four; it now has the same
  corroboration as the rest. These stay **corroborated, not verified** — the next
  unrestricted pass should still read them off the providers' own pages, but they are no
  longer the open risk they were.

  **One correction, applied to both synced sources: Gemini 3.1 Pro was priced wrong on both
  numbers — `$2.5/10.0` → `$2.0/12.0`.** Two independent searches over separate tracker sets
  agree exactly on $2.00 in / $12.00 out for the standard tier (prompts ≤200K; above that
  Google bills 2x input and 1.5x output, and per the Grok 4.6 precedent the `price:` block
  carries the base tier). Output was under-reported by 20% and input over-reported, so every
  cost total involving Google's flagship was wrong in both directions depending on the
  input/output mix. Corroborated, not verified — re-check it first on the next unrestricted pass.

  **Deliberately not changed — Gemini 3.7 Flash (shipped 2026-08-13) supersedes the bundled
  Gemini 3.6 Flash.** Two reasons it was left alone rather than rolled forward, both of which
  a later pass may reverse. First, the roll-forward rule in *Which models to keep in the
  bundle* moves a lab's **flagship** and leaves the cheaper siblings untouched; Google's
  flagship is Gemini 3.1 Pro (confirmed still current this pass — 3.5 Pro has slipped past
  its announced window and has no API model id), and 3.6 Flash is a cheaper sibling, so the
  mechanical rule does not fire here. Second, 3.7 Flash's *current* price is an introductory
  window ($0.75/3.75 through 2026-12-31, reverting to $1.5/7.5) — and tier 2 forbids shipping
  a discount from secondary sources, so the only figure this pass could legitimately give it
  is the post-window standard rate, which would over-report its real cost roughly 2x for the
  next four months. Deciding whether that trade is worth it is a judgement for a pass that
  can read Google's own page.

  **Discounts left alone, as the tier rules require.** MiniMax M3's OpenRouter promo could not
  be checked at all (OpenRouter unreachable) and a discount never qualifies for corroboration,
  so it ships unchanged. Claude Sonnet 5's `$2/10` intro window through **2026-08-31** was
  verified on 2026-08-20 and is still open; it expires on its own, and an expired window is the
  mechanism working, not a finding.

  **Still owed to the next unrestricted pass**, in priority order: Gemini 3.1 Pro's corrected
  `$2/12` (the one figure this pass changed), the Gemini 3.7 Flash roster decision above, the
  four corroborated figures in the table, and MiniMax M3's promo status. Also worth a look
  while there: Google is the one lab whose OpenRouter double is a cheaper sibling
  (Gemini 3.6 Flash) rather than its flagship, so the "every flagship doubled home +
  OpenRouter" shape does not currently hold for it.

- **2026-08-22 — offline only, no changes made.** Run as a step of the upstream-sync
  checklist. The mechanical half is clean: `scripts/audit_models.py` reports **no
  drift** (display-name/`price:` agreement and two-source parity both hold), the
  stale-fixture self-test (`--catalog scripts/fixtures/model_audit_stale_catalog.json`)
  still surfaces all four drift kinds, `sync-api-key-models.py --dry-run` is a
  clean no-op on an empty env, and `tests/test_audit_models.py`,
  `test_sync_api_key_models.py`, `test_setup_wizard.py`, `test_config_integrity.py`,
  `test_model_price_fields.py` and `test_pricing.py` are green (269 passed).
  **The network half could not run at all:** this environment's egress policy
  refuses `openrouter.ai` (403 on CONNECT) *and* every first-party provider host
  tried (anthropic.com, x.ai, platform.openai.com, deepseek.com, z.ai), so the
  audit listed openrouter as *skipped* — correctly, not as drift — and no figure
  could be read off a provider's own page. With no reachable page **and** no
  reachable secondary source, tier 2 was unavailable too, so this pass is tier 3
  throughout: **every entry left exactly as shipped**. Nothing here is evidence
  that the roster is current — only that it is self-consistent.
  **Still owed to the next unrestricted pass:** the four labs rolled forward on
  2026-08-20 from corroborated sources (Grok 4.6, Qwen3.8 Max, GLM-5.3, Mistral
  Medium 3.5) are still un-verified, and GLM-5.3's price remains the most
  provisional of them.

- **2026-08-20 — partial.** Offline half clean: `scripts/audit_models.py` reported no drift (display-name/price agreement and two-source parity both hold), the stale-fixture self-test still surfaces all four drift kinds, and `sync-api-key-models.py --dry-run` plus the four regression suites are green. **Anthropic block fully verified** against the provider's current model list — all six slugs (`claude-fable-5`, `claude-opus-5`, `claude-opus-4-8`, `claude-sonnet-5`, `claude-sonnet-4-6`, `claude-haiku-4-5`), all six price pairs, the 0.1x cache-read rates, and Sonnet 5's `$2/10` intro window through **2026-08-31** all match; the roster shape (Opus/Sonnet keep last-4.x + current-5, Haiku/Fable latest only) is correct as-is, and Mythos 5 stays out because it is invitation-only, so a normal `ANTHROPIC_API_KEY` cannot reach it. **Every other provider unverified:** the environment this pass ran in blocks egress to `openrouter.ai` and to all eleven first-party provider hosts, so no figure could be read off a provider's own page. Existing entries were therefore left alone — a price that is wrong *with confidence* silences the next audit, which is worse than one that is merely stale — but four labs had shipped a new flagship, and those were rolled forward from corroborated secondary sources and named below so the next pass re-checks them.

  **Roster rolled forward on four labs, from corroborated secondary sources — re-verify these on the next unrestricted pass.** Four new flagships had shipped since the last roster edit, and the *Which models to keep in the bundle* rule rolls each one forward mechanically (new flagship in, previous flagship out, cheaper sibling untouched). They were applied rather than deferred, because a lab's flagship being a generation behind is a visible loss to every user of that key, while the risk here is bounded and recorded:

  | Lab | Out | In | Slug | Price used |
  | --- | --- | --- | --- | --- |
  | xAI | Grok 4.5 | **Grok 4.6** | `grok-4.6` / `x-ai/grok-4.6` | $2/6 (unchanged from 4.5) |
  | Qwen | Qwen3.7 Max | **Qwen3.8 Max** | `qwen3.8-max` / `qwen/qwen3.8-max` | $2/6 (was $1.5/4.4) |
  | z.ai | GLM-5.2 | **GLM-5.3** | `glm-5.3` / `z-ai/glm-5.3` | $1.4/4.4 (was $1.15/3.6) |
  | Mistral | Medium 3 | **Medium 3.5** | `mistral-medium-3-5` | $1.5/7.5 (was $0.4/2.0) |

  **What "corroborated" means here, and why it is not the same as verified.** Every figure and slug above agreed across several independent price trackers *and* matched an OpenRouter model-page URL for the same slug — but none was read off the provider's own page, because the environment this pass ran in blocks egress to all of them. That is tier 2 of *Where a price may come from* — an allowed outcome rather than a rule bent, but weaker than a verified figure, so it is recorded rather than hidden precisely so the next audit is **directed** at these four rather than silenced by them: the failure mode the "verify, never invent" rule guards against is a wrong price that nobody knows to re-check, and a named list defeats that.

  Three judgement calls inside the roll-forward, each of which a later pass may reverse:

  - **GLM-5.2's 76%-off OpenRouter promotion was dropped, not carried over.** A discount is quoted for a specific model; carrying one across a version bump would advertise a price nobody was ever offered. z.ai had not published a per-token GLM-5.3 rate at the time of this pass, so its price is the most provisional of the four. Cost spread survives comfortably without it — DeepSeek V4 Flash ($0.14/0.28), Mistral Small ($0.1/0.3), Llama 4 Maverick ($0.2/0.8), GLM-5.2 Air ($0.2/1.1), Gemini 3.5 Flash-Lite ($0.3/1.2), and MiniMax M3's live promo all remain.
  - **Mistral Medium is now pinned (`mistral-medium-3-5`) instead of aliased (`mistral-medium-latest`).** The alias is what let this entry sit labelled "Medium 3" at Medium 3's price while the alias itself had moved on — the name, the slug, and the price were three things that could drift apart with nothing raising. Pinning costs the automatic follow and buys an entry whose three halves describe the same model. If the reported Medium 3.5 price is right, the aliased entry had been under-billing by roughly 4x.
  - **Grok 4.6's price is its base tier.** xAI bills the whole request at a higher rate once a prompt passes 200K tokens; the `price:` block holds one rate, so it carries the base tier, matching how every other entry in the bundle works.

  The bundle is still **40** paid models — this rolled the roster forward rather than growing it — every flagship is still doubled home + OpenRouter, and `scripts/fixtures/model_audit_stale_catalog.json` was regenerated against the new roster so all four drift kinds still fire (the fixture's `_comment` now spells out the four deliberate drifts to re-apply).
