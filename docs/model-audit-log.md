# Model audit log

A dated record of every [model audit](../FORK.md#the-model-bundle-and-its-audit)
pass: what was checked, which providers the network could actually reach, and
what changed. It lives here rather than in FORK.md because FORK.md is
instructions and this is a record — but it is the record you read _first_, since
the audit is deliberately opt-in and "when did anyone last look?" is the question
that decides whether to run one.

Newest first. Append a pass; never rewrite one. A dated line is what tells the
next person whether the roster was checked last week or last year, and _which_
providers that pass could actually reach.

- **2026-09-05 (third pass, requested on its own) — Anthropic re-verified at tier 1; no roster
  or price change, but three documentation drifts found and fixed, one of them a real one.**
  Run because it was asked for. The two earlier passes today both concentrated on prices; this
  one worked the *offline* steps properly — roster and order (step 1), first-party key coverage
  (step 3), slugs (step 4) and the privacy marker (step 7) — which is where the findings were,
  because those steps need no network and had been the ones deferred whenever the egress proxy
  blocked a pass.

  **Reachability unchanged.** `docs.claude.com` serves; `openrouter.ai`, `platform.openai.com`,
  `api.x.ai`, `ai.google.dev`, `api-docs.deepseek.com`, `mistral.ai`, `platform.moonshot.ai`,
  `platform.minimaxi.com`, `docs.z.ai` and `www.alibabacloud.com` are all refused at the proxy.
  Anthropic verified at tier 1, every other lab **tier 3: left alone, logged unreachable**. No
  tier-2 corroboration was possible either — that needs two independent reachable sources and
  there were none.

  **Anthropic — all six entries still match, re-read today.** Fable 5.1 `$10/$50` (cache read
  `$0.25`), Opus 5 `$5/$25` (`$0.50`), Opus 4.8 `$5/$25` (`$0.50`), Sonnet 5 `$2/$10` (`$0.20`),
  Sonnet 4.6 `$3/$15` (`$0.30`), Haiku 4.5 `$1/$5` (`$0.10`), parsed from the provider's own
  table and compared field by field against both synced sources. Fable 5.1's `0.025x` cache-read
  exception and Sonnet 5's now-permanent `$2/10` both still hold.

  **Structural steps, all clean.** Provider order is Anthropic → OpenRouter → OpenAI, xAI,
  Google, DeepSeek, Mistral, Moonshot, Qwen, MiniMax, z-ai, exactly as step 1 requires. Every
  home flagship is doubled on OpenRouter (`minimax/minimax-m3` ↔ `MiniMax-M3` modulo case, as
  allowed). All 13 OpenRouter entries carry `(p)` and no direct or home entry does. The machine
  half reports no drift and no price in any `display_name`.

  **Three drifts in the prose, found by reading the seven coverage places against the roster.**

  1. **`.env.example` advertised a model the fork does not carry.** Its `MISTRAL_API_KEY` line
     read *Large 3 / Medium 3.5 / **Small 3***, while the bundle carries `mistral-small-2603`
     as **Mistral Small 4** — and `config.example.yaml`, `providers.py`, the sync script's
     docstring and the README all say Small 4. The 2026-08-20 roll-forward updated four places
     and missed the fifth. Nothing failed: the key worked, the block uncommented, and the only
     symptom was a user reading a name that does not exist here. **Now pinned** —
     `TestFirstPartyKeyCoverage::test_env_example_names_the_models_each_home_key_actually_enables`
     compares every home key's comment against the display names that key enables, allowing only
     a lab prefix every model in the block repeats to be abbreviated away.
  2. **The OpenRouter legend documented a display-name price marker that §17 deleted.** It
     described `($A/B → $C/D*)` as a marker on these names and told the reader the starred pair
     is the discounted price — but prices left display names entirely, which is what the machine
     audit's `price_in_display_name` check now enforces. A reader following that legend goes
     looking for a number that is not there. Replaced with a pointer to the `price:` /
     `discount:` blocks that actually carry it.
  3. **The same legend advertised a 76%-off promotion on a model that is no longer bundled.** It
     named *GLM-5.2 ($1.15/3.6 → $0.28/0.87\*, 76% off) as of 2026-08* — but the 2026-08-20 pass
     rolled GLM-5.2 out for GLM-5.3 and deliberately did **not** carry the discount across, since
     a promotion is quoted for a specific model. So the file promised a discount on a model it
     does not ship. The legend now names the one live promo in the bundle, MiniMax M3
     (`$0.6/2.4` standard, `$0.24/0.96` discounted), and says an ended promo means deleting the
     `discount:` block rather than editing a name.

  A fourth was noted and **left alone**: the Volcengine Coding Plan *example* block still shows
  `glm-5.2`. It is an illustration of configuring a third-party gateway rather than a bundled
  entry, and whether that plan now serves GLM-5.3 cannot be checked from here — changing it
  would be inventing a fact, which is the one thing this pass is not allowed to do.

  **Still outstanding for the next unrestricted pass**, unchanged from this morning: tier-1
  verification for the four labs rolled forward on 2026-08-20 from corroborated sources (xAI
  Grok 4.6, Qwen3.8 Max, GLM-5.3, Mistral Medium 3.5), discovery for every non-Anthropic lab,
  and — newly — **whether MiniMax M3's OpenRouter promotion is still running**. It carries no
  `until:` because none was announced, so nothing expires it on its own; if it has ended, the
  bundle is advertising a price nobody is being offered, which is the exact failure the other
  two legend drifts were.

  **Regression gate green.** `python3 scripts/sync-api-key-models.py --dry-run` uncomments
  cleanly and `tests/test_sync_api_key_models.py tests/test_setup_wizard.py
  tests/test_config_integrity.py tests/test_audit_models.py` pass. The bundle is unchanged at
  **40** paid models; no price, slug, or roster entry moved.

- **2026-09-05 (second pass, requested with the upstream sync of 14 commits) — Anthropic re-verified at tier 1; no drift, no roster change.**
  Run because it was asked for, not because anything reported drift. The sync it rides with
  touches no model block, no `price:`, and no `discount:`, so it is not itself evidence about
  the roster; this pass exists to answer the request, and it re-read the one provider the
  network can reach rather than quoting the earlier line of the same day.

  **Machine half clean.** `python3 scripts/audit_models.py` reports **no drift**: every bundled
  slug still resolves, the two synced sources agree with each other, and no price has crept back
  into a `display_name`. Ten providers are listed as *skipped, no machine-readable catalog*
  (covered by the manual steps), and `openrouter` as *catalog unreachable* — reported as skipped,
  not as drift, exactly as the job is meant to.

  **Reachability — one authoritative page, everything else refused.** `docs.claude.com` resolves
  and serves; every other host tested is refused at the egress proxy with `CONNECT tunnel failed,
  response 403` (`openrouter.ai`, `www.anthropic.com`, `api.openai.com`, `platform.openai.com`,
  `ai.google.dev`, `api-docs.deepseek.com`, `api.x.ai`, `mistral.ai`, `qwen.ai`, `z.ai`,
  `www.deepseek.com`, plus `huggingface.co` and `api.together.xyz` as would-be secondary
  sources). So **tier 2 was not available either** — corroboration needs two independent
  reachable sources and there were none — and every lab but Anthropic is **tier 3: left alone,
  logged unreachable**. No price was carried from memory.

  **Anthropic — all six bundled entries match the provider's own table, in both synced sources.**
  Read from <https://docs.claude.com/en/docs/about-claude/pricing> on 2026-09-05: Fable 5.1
  `$10/$50` (cache read `$0.25`), Opus 5 `$5/$25` (`$0.50`), Opus 4.8 `$5/$25` (`$0.50`),
  Sonnet 5 `$2/$10` (`$0.20`), Sonnet 4.6 `$3/$15` (`$0.30`), Haiku 4.5 `$1/$5` (`$0.10`).
  `config.example.yaml` and `scripts/wizard/providers.py::MODEL_PRICES` agree with the page and
  with each other on all six pairs and all six cache rates, including Fable 5.1's documented
  `0.025x` cache-read exception. Sonnet 5 still carries a plain `$2/10` with no `discount:`
  block, which is right: the page shows the introductory rate as the standing price.

  **Discovery (step 2) — nothing to add, and one deliberate omission re-confirmed.** The page's
  Claude line-up is Fable 5.1 / Mythos 5.1 / Fable 5 / Opus 5 / Opus 4.8 / 4.7 / 4.6 / 4.5 /
  Sonnet 5 / 4.6 / 4.5 / Haiku 4.5 / 3.5. The bundle already carries the newest of each family
  plus the last 4.x of Opus and Sonnet, which is the roster shape the rule asks for. **Mythos 5.1
  stays out** for the same reason Mythos 5 did — the page marks it *limited availability*, so an
  ordinary `ANTHROPIC_API_KEY` cannot reach it, and bundling a model a user's key is refused for
  is worse than omitting it. No other lab could be checked for new flagships, so **discovery is
  outstanding for every non-Anthropic lab** and is what the next unrestricted pass should start
  from — including the four labs rolled forward from corroborated sources on 2026-08-20
  (xAI Grok 4.6, Qwen3.8 Max, GLM-5.3, Mistral Medium 3.5), which remain un-verified at tier 1.

  **Regression gate green.** `python3 scripts/sync-api-key-models.py --dry-run` uncomments
  cleanly, and `tests/test_sync_api_key_models.py tests/test_setup_wizard.py
  tests/test_config_integrity.py tests/test_audit_models.py` pass (213 tests). The bundle is
  unchanged at **40** paid models.

- **2026-09-05 (requested with the run-pricing-snapshot change) — Anthropic re-verified at tier 1; no drift, no roster change.**
  Run because it was asked for. The change shipped alongside it persists each run's prices
  (FORK.md §17) and **adds no model entry and changes no price**, so it is not itself evidence
  about the roster — but it does raise the cost of a *wrong* bundled price, since a price is now
  captured onto every run that uses it and stops being correctable by editing `config.yaml`
  after the fact. That is the reason this pass verified rather than deferring to the day's
  earlier line.

  **Reachability — one authoritative provider, the rest blocked.** `docs.claude.com` is
  reachable, so **Anthropic was verified at tier 1** off its own pricing page. Everything else
  is refused at the egress proxy (`openrouter.ai`, `www.anthropic.com`, `api.openai.com`,
  `platform.openai.com`, `api.deepseek.com`, `api.x.ai` all fail to connect), so every other
  lab is **tier 3: left alone, logged unreachable**. No price was carried from memory and no
  corroborated (tier 2) figure was accepted this pass.

  **Anthropic — all six bundled entries match the provider's own table, in both synced sources.**
  Read from <https://docs.claude.com/en/docs/about-claude/pricing> on 2026-09-05:
  Fable 5.1 `$10/$50` (cache read `$0.25`), Opus 5 `$5/$25` (`$0.50`), Opus 4.8 `$5/$25`
  (`$0.50`), Sonnet 5 `$2/$10` (`$0.20`), Sonnet 4.6 `$3/$15` (`$0.30`), Haiku 4.5 `$1/$5`
  (`$0.10`). `config.example.yaml` and `scripts/wizard/providers.py::MODEL_PRICES` agree with
  each of those and with each other. Two things specifically re-checked because they are the
  ones that rot: **Fable 5.1's cache-read rate is `0.025x` its input price, not the usual
  `0.1x`** — the page carries a footnote saying so, and the bundle's `cache_hit: 0.25` is
  correct with a comment naming the exception; and the **Sonnet 5 introductory window**, which
  the page confirms was made permanent (the scheduled 2026-09-01 rise to `$3/$15` "will not
  occur"), matching the bundle's plain `$2/10` with no `discount:` block.

  **Slugs verified at tier 1 too.** All six bundled ids appear as **Active** on
  <https://docs.claude.com/en/docs/about-claude/model-deprecations>: `claude-fable-5-1`,
  `claude-opus-5`, `claude-opus-4-8`, `claude-sonnet-5`, `claude-sonnet-4-6`,
  `claude-haiku-4-5`. Note that `claude-opus-4-8` and `claude-sonnet-4-6` are **not** on the
  models-overview page — that page lists the current generation only — so the deprecations
  table is the right surface to check a retained previous-generation pin against; reading the
  overview alone would look like two retired slugs.

  **Mechanical half: clean.** `python3 scripts/audit_models.py` reports **no drift**, with the
  ten catalog-less labs and `openrouter` listed as skipped. `openrouter` is skipped because its
  catalog is unreachable (`Tunnel connection failed: 403 Forbidden`), so its silence is **not**
  evidence that the routed roster is current — unchanged from the earlier pass, and the reason
  no OpenRouter entry was touched.

- **2026-09-05 (requested with the sidebar scroll fix) — mechanical half only; no model config touched, no roster change.**
  Run because it was asked for. The change shipped alongside it (FORK.md §35, the sidebar chat
  list's `scrollMargin`, plus the folder create-and-file path) is entirely frontend and **adds no
  model entry and no price**, so it is no evidence at all about the roster. Nothing here supersedes
  the 2026-09-04 tier-1 pass below; this line exists so the next reader has a date rather than an
  inference.

  **Reachability — worse than 2026-09-04.** `openrouter.ai` is refused at the egress proxy
  (`Tunnel connection failed: 403 Forbidden`), so the audit lists it as *skipped* rather than
  reporting every routed slug retired — the property `TestUnreachableProvider` exists to protect.
  No tier-1 verification was attempted for any lab: with no model or price touched, re-deriving an
  unchanged roster through a blocked proxy buys nothing the previous day's pass does not already
  say.

  **Mechanical half: clean.** `python3 scripts/audit_models.py` reports **no drift** — every
  bundled slug still in its provider's catalog and every configured price matching, with the ten
  catalog-less labs and `openrouter` listed as skipped. Because `openrouter` is skipped, its
  silence is **not** evidence that the OpenRouter roster is current. The audit's own regression
  test still works: `--catalog scripts/fixtures/model_audit_stale_catalog.json` surfaces all four
  drift kinds (retired slug, moved list price, ended promo, started promo) with a suggested diff
  for each, and `cd backend && uv run pytest tests/test_audit_models.py` is green (67 passed with
  the guidance checker alongside it).

- **2026-09-04 (requested with the local-subagent-parallelism change) — Anthropic re-verified at tier 1; no drift, no roster change.**
  Run because it was asked for, not because anything moved: the change shipped alongside it
  (FORK.md §34, GPU-residency admission for local subagents) touches `subagent_runtime` and the
  Ollama sync and **adds no model entry and no price**, so it is not itself evidence about the
  roster. The previous pass was the day before; this one exists to say so with a date rather than
  to re-derive it.

  **Reachability — unchanged from 2026-09-03.** `platform.claude.com` answers (200), so Anthropic's
  own pricing and model-overview pages were read directly — **tier 1**. Everything else is still
  refused at the egress proxy: `openrouter.ai` (403 at CONNECT, and the audit job's catalog fetch
  fails the same way), `platform.openai.com`, `api.x.ai`, `mistral.ai`, `ai.google.dev`, `z.ai`,
  `api.deepseek.com` and `www.anthropic.com` all return 000. No blocked lab's price was touched.

  **Mechanical half: clean.** `scripts/audit_models.py` reports **no drift**, with `openrouter`
  listed as *skipped* (catalog unreachable) — so, again, its silence is **not** evidence the
  OpenRouter roster is current. The stale-fixture self-test
  (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still surfaces all four drift kinds
  (retired slug, moved list price, ended promo, started promo), so the audit itself is still
  working. `sync-api-key-models.py --dry-run` is a clean no-op.

  **Tier 1 — Anthropic, read off `platform.claude.com`, and it had not moved.** All six bundled
  entries match the provider's own table exactly: Fable 5.1 ($10/$50, cache $0.25), Opus 5 and
  Opus 4.8 ($5/$25, cache $0.50), Sonnet 5 ($2/$10, cache $0.20), Sonnet 4.6 ($3/$15, cache $0.30),
  Haiku 4.5 ($1/$5, cache $0.10). All six slugs (`claude-fable-5-1`, `claude-opus-5`,
  `claude-opus-4-8`, `claude-sonnet-5`, `claude-sonnet-4-6`, `claude-haiku-4-5`) are present on the
  models-overview page. The roster shape also still holds: Opus and Sonnet each carry their last
  4.x beside the current 5, Haiku and Fable carry only the latest, and the page shows nothing newer
  than what is bundled (Opus 4.7/4.6/4.5 and Fable 5 are all *older* than what is carried).

  **Discovery (step 2) — one pointer, deliberately not acted on.** OpenRouter's trending and
  ranking boards are the required source and are blocked, so this half was a web-search sweep only.
  It surfaced nothing new for a bundled lab — GPT-5.6 Sol, MiniMax-M3 and GLM-5.3-Flash are all
  already carried (the last as `glm-5.3-flash` in the Coding Plan block) — and one lab the bundle
  does not carry at all: **Poolside**, whose *Laguna XS 2.1* (33B-A3B coding agent, 256K context)
  appeared in a cost-efficiency collection. A collection listing is not the trending board and a
  search summary is not sustained third-party usage, so per *What "critically acclaimed" means
  here* this is **a pointer, not an entry**. Re-check it against the ranking surfaces on the first
  pass that can reach `openrouter.ai`.

- **2026-09-03 (upstream sync) — Anthropic re-verified at tier 1; no drift, no roster change.**
  Run as the model-audit step of an upstream sync (53 upstream commits merged). The merge
  itself touched no model config — `config.example.yaml`'s only change was prose comments on
  `context_window` and the summarization fraction trigger — so this pass is evidence about the
  roster only through what the network could reach today, not through the sync.

  **Reachability.** `platform.claude.com` answers (200; `docs.claude.com` 301→it), so Anthropic's
  own pricing page was read directly — **tier 1**. Everything else is still refused at the egress
  proxy: `openrouter.ai` (403 at CONNECT, `EGRESS_BLOCKED` through WebFetch), and `api.x.ai`,
  `platform.openai.com`, `www.anthropic.com`, `docs.anthropic.com`, `mistral.ai`, `ai.google.dev`,
  `z.ai`, `deepseek.com` all return 000. Web **search** is available but was used only for the
  discovery sweep below; no blocked lab's price was changed on it this pass.

  **Mechanical half: clean.** `scripts/audit_models.py` reports **no drift** (openrouter correctly
  _skipped_ as unreachable, so its silence is again **not** evidence the OpenRouter roster is
  current); the stale-fixture self-test (`--catalog scripts/fixtures/model_audit_stale_catalog.json`)
  still surfaces all four drift kinds (retired slug, moved price, ended promo, started promo);
  no entry carries a price in its `display_name`; the two synced sources still agree;
  `sync-api-key-models.py --dry-run` is a clean no-op. Bundle is still **41** paid models, each
  priced.

  **Tier 1 — Anthropic, read off `platform.claude.com`, and it had not moved.** All six bundled
  entries match the provider's own table exactly, slugs and cache rates included: Fable 5.1
  ($10/$50, cache $0.25), Opus 5 and Opus 4.8 ($5/$25, cache $0.50), Sonnet 5 ($2/$10, cache
  $0.20), Sonnet 4.6 ($3/$15, cache $0.30), Haiku 4.5 ($1/$5, cache $0.10). The page confirms
  Sonnet 5's $2/$10 launch-introductory rate is now the **standard** price (the scheduled
  1 Sep rise to $3/$15 will not happen) — the config already ships it as standard with the
  "introductory rate is now the standard price" note, so nothing to change. The Opus/Sonnet
  "last 4.x + current 5" shape still holds (Opus 4.7/4.6/4.5 exist but stay out; Sonnet 4.5/4
  retired). Mythos 5.1 is limited-availability (glasswing) and Fable 5 is the older sibling —
  neither belongs in a general bundle.

  **Discovery — noted, not added.** Web search flagged two Sept-2026 releases from labs the
  bundle already carries: **Gemini 3.8 Flash** (2026-09-02, newer than the bundled
  `gemini-3.6-flash`) and a **Qwen3.8** refresh. Both are candidates a proper discovery diff
  would raise, but adding either needs a verified slug (step 4) and a tier-1/tier-2 price, and
  Google's and Qwen's own pages plus the OpenRouter catalog are all egress-blocked this pass.
  Left out deliberately; owed to the next unrestricted pass.

  **Still owed to the next unrestricted pass**, in priority order: the OpenRouter roster and every
  promo/discount on it (catalog unreachable all pass), the Gemini 3.8 Flash / Qwen3.8 discovery
  decisions above, and the corroborated non-Anthropic figures from prior passes that no tier-1
  page has confirmed since.

- **2026-09-02 — process change, not a roster pass. No model, price or slug was touched.**
  The audit gained a **discovery** step (FORK.md, *Auditing the model list*, step 2) and a
  definition of *critically acclaimed* (OpenRouter's own rankings and trending surfaces, named
  and dated here; a cloaked codename like `ox-alpha` is a pointer to watch, never an entry).
  `scripts/audit_models.py` gained the matching `new_candidate` finding: newer than the lab's
  newest bundled entry, non-variant, three per lab, expiring 60 days after release so a declined
  candidate cannot become an un-closable weekly issue.

  **The discovery half could not be exercised live.** This environment's proxy refuses
  `openrouter.ai` (403 on CONNECT), so the audit reported openrouter as _skipped_ — correctly —
  and no candidate could be raised. Discovery is therefore covered only by `TestNewCandidates`,
  which injects its own clock. **Owed to the next unrestricted pass:** run
  `python3 scripts/audit_models.py` with the catalog reachable and work whatever `new_candidate`
  findings it raises; that is the first real test of the check, and the first chance to see
  whether the three-per-lab cap and the 60-day window are the right numbers. The offline half was
  clean (no price in any display name, the two synced sources agree), and the stale fixture still
  produces all four drift kinds.

- **2026-09-02 — requested pass. Anthropic verified at tier 1 and it had moved; three tier-2
  corrections elsewhere.** Run because the user asked for an audit. This is the first pass since
  2026-08-20 with **any** authoritative page reachable, and the first ever with a working
  secondary-source channel, so tier 1 and tier 2 were both open — unlike the two previous passes,
  which were tier 3 throughout.

  **Reachability.** `docs.claude.com` / `platform.claude.com` answer (200), so Anthropic's own
  pricing and model-overview pages were read directly — tier 1. Everything else is still refused
  at the egress proxy: `openrouter.ai` (403 at CONNECT, and `EGRESS_BLOCKED` through WebFetch),
  `api.x.ai`, `platform.openai.com`, `www.anthropic.com`, `docs.mistral.ai`, `ai.google.dev`,
  `docs.z.ai`, `platform.deepseek.com`, `platform.moonshot.cn`, `www.alibabacloud.com`, and the
  trackers `artificialanalysis.ai` / `llmpricecheck.com` all return 000. Web **search** was
  available, so figures for the blocked labs could be corroborated across independent sites —
  tier 2 — rather than left untouched.

  **Mechanical half: clean.** `scripts/audit_models.py` reports no drift (openrouter correctly
  _skipped_, so its silence is again **not** evidence the OpenRouter roster is current); the
  stale-fixture self-test still surfaces all four drift kinds; no entry carries a price in its
  `display_name`; `sync-api-key-models.py --dry-run` leaves `config.example.yaml` byte-identical
  (md5 unchanged). The gate (`test_sync_api_key_models.py`, `test_setup_wizard.py`,
  `test_config_integrity.py`, `test_audit_models.py`) is green at **192 passed**, plus
  **185 passed** across `test_model_price_fields.py`, `test_pricing.py`, `test_model_ids.py`
  and `test_model_factory.py`. The bundle is still **41** paid models, every one priced.

  **Tier 1 — Anthropic, read off the provider's own page, and the roster moved.**
  Opus 5 / Opus 4.8 ($5/$25, cache $0.50), Sonnet 5 ($2/$10, cache $0.20), Sonnet 4.6 ($3/$15,
  cache $0.30) and Haiku 4.5 ($1/$5, cache $0.10) all match what is shipped, slugs included, and
  the Opus/Sonnet "last 4.x + current 5" shape still holds (Opus 4.7 exists but is the
  third-oldest, so it stays out). Two things changed:

  - **Claude Fable 5 → Claude Fable 5.1** (`claude-fable-5` → `claude-fable-5-1`, direct **and**
    its OpenRouter twin). The _Fable keeps only the latest_ rule fires mechanically: 5.1 is the
    current model, 5 is listed under "Legacy models (still available)". Price is unchanged at
    $10/$50, thinking is still **adaptive, always on** (so the `when_thinking_disabled` branch
    must stay on adaptive — an explicit `type: disabled` still 400s), and max output is 128K, so
    `max_tokens: 32000` is unaffected.
  - **Fable's cache-read rate is no longer 0.1x.** Anthropic's pricing page states cache hits and
    refreshes on Fable 5.1 and Mythos 5.1 are priced at **0.025x** the base input price — $0.25/MTok,
    not the $1.00 the 0.1x multiplier every other Claude uses would give. `cache_hit` was corrected
    from `1.0` to `0.25` in both synced sources. This is the kind of drift no test can see: the old
    value was well-formed and 4x too high.

  **Sonnet 5's introductory window closed by becoming permanent**, which is the second of the two
  endings FORK.md step 5 warns about. The page's own note now reads that the $2/$10 rate announced
  as introductory through 2026-08-31 *is* the standard price and the scheduled increase to $3/$15
  will not occur. The bundle already carried $2/$10 with no `discount:` block, so nothing changed —
  recording it so the next pass does not go looking for an expiry that no longer exists.

  **`anthropic/claude-fable-5-1` is the one slug in this change set that could not be verified.**
  OpenRouter is unreachable, so the routed twin's id was derived by the documented rule
  (`provider/` + the tier-1-verified Claude API id), the same mapping `anthropic/claude-fable-5`
  already followed. The home block is the verified half; **re-check the routed half first on the
  next unrestricted pass.** Leaving the twin on Fable 5 was the alternative and was rejected: it
  breaks the doubling rule and `TestFirstPartyKeyCoverage` with it, and would ship the flagship a
  generation behind to exactly the users who hold only an `OPENROUTER_API_KEY`.

  **Tier 2 — three corrections, corroborated across independent sources.** Each was read from
  several sites that had to look separately and that agree exactly on both numbers; none was read
  off the lab's own page, so all three are named here for the next pass to verify.

  | Entry                   | Was                             | Now                              | What agreed                                                                 |
  | ----------------------- | ------------------------------- | -------------------------------- | --------------------------------------------------------------------------- |
  | `mistral-small-latest`  | "Mistral Small 3", $0.10/$0.30  | `mistral-small-2603`, "Mistral Small 4", $0.15/$0.60 | Artificial Analysis, Gate.AI, TokenCost, Design for Online, AI Pricing Guru, CloudZero |
  | `qwen3.7-plus`          | $0.40/**$1.20**                 | $0.40/**$1.60**                  | VentureBeat's launch figure, genbuzz, MLQ, Alibaba Model Studio doc listings   |
  | `gemini-3.5-flash-lite` | $0.30/**$1.20**                 | $0.30/**$2.50**                  | Artificial Analysis, eesel, BenchLM, costgoat — agreeing across two separate searches |

  **The Mistral Small entry was the alias trap firing a second time**, in the same file, on the
  same lab. `mistral-small-latest` had moved on to **Mistral Small 4** (shipped 2026-03-16) while
  the entry's name still said "Small 3" and its price still said $0.10/$0.30 — the name, the slug
  and the price describing three different things, which is precisely why the 2026-08-20 pass
  pinned `mistral-medium-latest` to `mistral-medium-3-5`. It is now pinned to `mistral-small-2603`
  (the OpenRouter slug minus its prefix, matching the `mistral-large-2512` convention already in
  the bundle) and priced at Small 4's rate, which is 1.5x the old input and **2x** the old output.
  **No `*-latest` alias remains in the bundle.** Any future entry that reaches for one is
  re-introducing a drift this fork has now had to fix twice.

  **The four labs rolled forward on 2026-08-20 from corroborated sources are still not verified,
  but all four re-corroborated cleanly** against a different set of sources this pass: Grok 4.6
  $2/$6, Qwen3.8 Max $2/$6, GLM-5.3 $1.40/$4.40, Mistral Medium 3.5 $1.50/$7.50 — every figure
  matching what is shipped. Also re-corroborated and unchanged: GPT-5.6 Sol $5/$30, Terra $2/$12,
  Luna $0.20/$1.20, GPT-5.3 Codex $1.75/$14, Kimi K3 $3/$15, Kimi K2.6 $0.95/$4.00, Grok 4.3
  $1.25/$2.50, Mistral Large 3 $0.50/$1.50, Gemini 3.1 Pro $2/$12, MiniMax M3 list $0.60/$2.40,
  MiniMax M2.7 $0.30/$1.20, Nemotron 3 Ultra $0.50/$2.20. No lab had shipped a new flagship since
  the last roster edit — GPT-5.6 Sol, Grok 4.6, Kimi K3 and DeepSeek V4 Pro are all current.

  **DeepSeek's home prices are right, and the reason is worth writing down.** DeepSeek introduced
  peak/off-peak pricing at 16:00 UTC on 2026-08-16, off-peak being half of peak. The bundle's
  `deepseek-v4-pro` $1.32/$3.96 and `deepseek-v4-flash` $0.44/$1.32 are the **peak** rates — the
  conservative upper bound FORK.md step 5 asks for — with off-peak at $0.66/$1.98 and $0.22/$0.66.
  A pass that finds the lower pair quoted somewhere should not "correct" the entry down.

  **Tier 3 — left exactly as shipped, and why.** Each of these is a suspicion, not a figure:
  no authoritative page, and no two independent sources agreeing exactly.

  - **`deepseek/deepseek-v4-pro` on OpenRouter ($0.44/$0.87) is the likeliest stale price in the
    bundle, and it is the top item owed.** That pair is DeepSeek's *pre-2026-08-16* rate
    ($0.435/$0.87) to the cent, and the lab has since raised list by roughly 1.5x–2.3x. But an
    OpenRouter entry bills at **OpenRouter's** rate, OpenRouter sets its own margins, and its page
    is exactly what cannot be reached — so the figure is unknown rather than wrong, and guessing it
    would be the wrong-with-confidence failure the rule exists to prevent.
  - **MiniMax M3's OpenRouter discount** still ships at $0.24/$0.96. Search results describe the
    live promo as $0.30/$1.20 ("permanent 50% off" the $0.60/$2.40 list, which does match the
    configured `price:`). A **discount never qualifies for tier 2**, so it was not touched — but if
    that reading is right, the header is advertising a promo price nobody gets, which is the exact
    symptom FORK.md calls out. Re-read OpenRouter's promotions page first thing next pass and
    either correct it or delete the block.
  - **Llama 4 Maverick** output: shipped $0.80, one source reported $0.696. Single source, and
    OpenRouter's routed output price varies by upstream provider. Left alone.
  - **GLM-4.5 Air**: shipped $0.20/$1.10, one aggregator reported "from $0.13"/$0.85 — a
    cheapest-provider figure, not a list price. Left alone.

  **Roster judgements deferred again, deliberately.** Both were deferred on 2026-09-01 for reasons
  that still hold, and neither is a price question:

  - **Gemini 3.7 Flash still supersedes the bundled Gemini 3.6 Flash.** The roll-forward rule moves
    a lab's *flagship*; Google's flagship is Gemini 3.1 Pro (still current), and 3.6 Flash is a
    cheaper sibling, so the rule does not fire. And 3.6 Flash's shipped $1.50/$7.50 is confirmed as
    the correct **standard** rate — the $0.75/$3.75 both Flash models bill at today is an
    introductory window through 2026-12-31, and an intro rate is a discount, so it cannot be
    shipped from secondary sources. A pass that can read Google's own page should decide whether to
    roll 3.6 → 3.7 and add the `until: 2026-12-31` discount block that would then expire itself.
  - **Google is still the one lab whose OpenRouter double is a cheaper sibling** (Gemini 3.6 Flash)
    rather than its flagship, so "every flagship doubled home + OpenRouter" does not hold for it.
    `TestFirstPartyKeyCoverage` passes because it only requires *some* home model to be doubled.
  - **`glm-4.5-air` is two generations behind its own block's flagship** (GLM-5.3), and z.ai now
    ships a **GLM-5.3-Flash** at roughly $0.15/$0.50 that would be the better cheap pick. Not
    changed: the sibling slug could not be enumerated off z.ai's own model list, and FORK.md is
    explicit that a sibling id must be read off the lab's list rather than derived — which is how
    `glm-5.2-air` got invented in the first place.

  **Step 2's seven copies were read by eye and all seven now agree.** The three machine-checked
  ones (`config.example.yaml` marker blocks, `HOME_API_BUNDLES`, `PROVIDERS`) and the four no test
  parses (`providers.py`'s `description=` strings, `config.example.yaml`'s `QUICK START` comment,
  `sync-api-key-models.py`'s `QUICK START` docstring, the README §2 bullet) were each updated for
  Fable 5.1 and Mistral Small 4. Every key is still documented in `.env.example`, no home block is
  a lone flagship, and Meta Llama + NVIDIA Nemotron remain the only routed-only labs.

  **Still owed to the next unrestricted pass**, in priority order: the OpenRouter slug
  `anthropic/claude-fable-5-1`; `deepseek/deepseek-v4-pro`'s routed price; MiniMax M3's promo; the
  three tier-2 corrections above; the four labs carried since 2026-08-20; and the two Google
  roster judgements.

- **2026-09-01 (conversation scroll-back change) — mechanical half green; tier-1 verification
  impossible this pass, so no figure was touched.** Run because the user asked for a full audit
  alongside a frontend-only change set (message-list scroll ownership, and carrying a
  conversation's per-thread model onto an edit fork). That change touches **no** `models:` entry,
  `price:` or `discount:` block, so the roster was not in scope on its own merits.

  **Reachability: worse than the previous passes — nothing was reachable.** `openrouter.ai` is
  still refused at the egress proxy (403 at CONNECT), and this time so is every provider page
  tried directly, `docs.anthropic.com` and `platform.openai.com` included (blocked by the egress
  proxy; `curl` returns 000, `WebFetch` returns `EGRESS_BLOCKED`). So **tier 1 was not available
  for any provider**, and the previous passes' habit of at least re-reading Anthropic's own page
  could not be repeated. Nothing in the roster was re-priced or re-slugged: FORK.md's rule is
  verify or corroborate, never recall, and neither tier was open.

  **Mechanical half: clean.** `scripts/audit_models.py` reports no drift (openrouter correctly
  _skipped_, not drift — so its silence is **not** evidence the OpenRouter roster is current); the
  stale-fixture self-test still surfaces all four drift kinds (retired slug, moved list price,
  promo ended, promo started); the `price_in_display_name` grep over both sources prints nothing;
  `sync-api-key-models.py --dry-run` leaves `config.example.yaml` byte-identical (md5 unchanged).
  The regression gate (`test_sync_api_key_models.py`, `test_setup_wizard.py`,
  `test_config_integrity.py`, `test_audit_models.py`) is green at **192 passed**, and the full
  backend suite at **14735 passed, 86 skipped**.

  **Step 2's seven copies were read by eye, and all seven agree.** The four that no test parses —
  `scripts/wizard/providers.py`'s `description=` strings, `config.example.yaml`'s `QUICK START`
  comment, `sync-api-key-models.py`'s `QUICK START` docstring, and the README §2 bullet — plus the
  three machine-checked ones (`config.example.yaml` marker blocks, `HOME_API_BUNDLES`,
  `.env.example`) all name the same lineups: six Claudes direct; thirteen routed; and nine home
  blocks (OpenAI 4, xAI 2, Google 3, DeepSeek 2, Mistral 3, Moonshot 2, Qwen 2, MiniMax 2, z-ai 2)
  with Meta Llama and NVIDIA Nemotron left routed-only. **No prose drift found this pass** — unlike
  2026-08-26, which found the QUICK START comment three roster rolls behind.

  **One lead for the next pass that has network, deliberately not applied.** Web _search_ works in
  this environment even though page fetches do not, and its results for **MiniMax M3 on
  OpenRouter** disagree both with the bundle and with each other: the bundle carries `$0.6/2.4`
  list with a 60%-off `discount:` of `$0.24/0.96`, while search results variously report a
  permanent **50%** discount (`$0.30/1.20` against the same `$0.60/2.40` list), a current
  `$0.23/0.96`, and a cheapest-provider `$0.255`. The list price corroborates; the _discount_ does
  not, and FORK.md is explicit that a discount never qualifies for the corroboration fallback —
  only a standard rate does. Sources that contradict each other would not clear that bar anyway.
  **Re-read OpenRouter's promotions page for `minimax/minimax-m3` first** on the next pass that can
  reach it; if the discount really is 50%, both synced sources need the new figures.

- **2026-08-31 (ComfyUI-on-by-default change) — mechanical half only; no model config touched, no
  figure changed.** Run because the accompanying change set was asked to "run the tests from FORK.md
  including the model audit". The change itself is media/tooling (`config.example.yaml`'s `media`
  tool entries, launch provisioning, a models CLI, a frontend button); it touches **no** `models:`
  entry, `price:` or `discount:` block, so the roster was not in scope on its own merits.

  **Reachability: unchanged and still limited.** `openrouter.ai` is refused at the egress proxy
  (403 at CONNECT), which is the only machine-readable catalog in the bundle — `audit_models.py`
  correctly reports it as _skipped_ rather than as drift, so **its "no drift detected" is not
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
  as _skipped_ rather than as drift), plus `www.anthropic.com`, `platform.openai.com`,
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
  Mythos 5 stays out (still limited-availability). Two page changes worth noting and _not_ acting on:
  **fast mode** now prices Opus 5 / 4.8 at `$10/50`, and Claude 4.7-and-later use a tokenizer that
  produces ~30% more tokens for the same text. Neither is a per-token rate change — fast mode is an
  opt-in premium the bundle does not request, and a tokenizer shifts token _counts_, which the
  cost totals already measure — so no `price:` block moves.

  **DeepSeek: the open item from 2026-08-29 is half-settled, and no figure changed.** Several
  independent search-tier sources now agree exactly on the structure and both numbers: since
  **2026-08-16 16:00 UTC**, V4-Pro bills `$1.32/3.96` during peak hours (01:00–04:00 and 06:00–10:00
  UTC, weekdays) and `$0.66/1.98` off-peak, with off-peak described everywhere as _half of peak_ — so
  peak is the reference rate and off-peak the automatic discount. The home block already ships
  `$1.32/3.96`, i.e. the reference rate, which is what the Grok 4.6 precedent asks for (one `price:`
  field carries the standard rate, never the special band) and what tier 2 permits (a discount is
  never shipped from secondary sources). **So the home block is right as shipped, and now has a
  recorded reason rather than a coincidence.**

  **The instruction the last pass left — "make the two halves of the doubled model agree" — was
  itself wrong, and is retired here.** The OpenRouter twin ships `$0.44/0.87` against the home
  block's `$1.32/3.96`, and the last pass read that as one model with two prices. It is not: the two
  entries bill through two different channels, and FORK.md's own rule is that an OpenRouter entry's
  authoritative page _is_ its OpenRouter page, "because OpenRouter's rate is what the entry bills
  at". Two halves of a doubled model are required to name the same _model_, never the same _price_.
  What is genuinely owed is narrower: confirm what OpenRouter bills for `deepseek/deepseek-v4-pro`
  today. Search suggests it still lists the pre-August-16 `$0.435/0.87`, but that is a single
  unverifiable claim about a page tier 1 owns, so **nothing was changed**.

  **No roll-forward due.** A release sweep found nothing newer than the bundle's flagships: the most
  recent releases are GLM-5.3 Flash (2026-08-26, a cheaper sibling, not a flagship — and the same
  model upstream added a _commented_ example profile for in this merge), Gemini 3.7 Flash
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
  as _skipped_ rather than as drift), and `www.anthropic.com`, `platform.openai.com`, `ai.google.dev`,
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

  **One stale prose copy fixed.** `scripts/wizard/providers.py`'s OpenRouter `description=` read _"One
  key: Claude Fable/Opus 5 + …"_, but the OpenRouter bundle carries **only** Fable 5 — every other
  Claude is deliberately direct-only. That string is one of the four copies no test reads, and it is
  what `make setup` prints, so it advertised a model the key does not unlock; it now reads _"One key:
  Claude Fable 5 + …"_. The other three prose copies (`config.example.yaml`'s QUICK START, the sync
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
  2026-08-26 pass. A pass this close behind another is deliberately a _re-check_, not a
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
  unshipped anyway, because `developers.openai.com` cannot be reached and _Where a price may come
  from_ bars a **discount** from the corroborated tier however many sources agree — the rule is
  about which page was read, not how strong the agreement is. The Gemini Flash introductory
  `$0.75/3.75` is unchanged in status, including the unresolved 3.6-vs-3.7 ambiguity that is its
  second disqualifier. Both stay top of the owed list.

  **One live discount could not be checked at all, and it is the one that can go wrong quietly.**
  The bundle carries exactly one `discount:` block — `openrouter-minimax-m3` at `$0.24/0.96`, with
  no `until` because the provider announced no end date, which is legitimate and deliberately not a
  finding. Confirming it is still running needs OpenRouter's catalog, which is precisely what is
  unreachable, so the audit's _promotion ended_ check is skipped for it. Left alone at tier 3, and
  named here because it is the single bundled entry that would keep advertising a discount nobody
  is getting if that promo has quietly ended.

  **Prose copies: six of the seven were current, one was stale and is fixed.** All seven places
  step 2 names were read by eye. `config.example.yaml`'s `QUICK START` comment, the sync script's
  `QUICK START` docstring, `.env.example`, the README §2 bullet and `providers.py`'s
  `HOME_API_BUNDLES` all match the marker blocks exactly. `providers.py`'s **`mistral`
  `LLMProvider`** still read `description="Mistral Large 3 + Medium 3.5 + Small (direct Mistral
API)"` — the unversioned _Small_ that the 2026-08-26 pass corrected in the other copies and
  missed here. It now reads **Small 3**, matching the `mistral-small-3` entry and the other six
  copies. That string is what `make setup` prints and no test reads it, which is exactly why it
  survived a pass that was looking for it.

  **Bundle unchanged at 41 paid models** — 6 Anthropic + 13 OpenRouter + 22 home.

  Mechanical half green: `scripts/audit_models.py` reports **no drift** (display-name/price
  agreement and two-source parity both hold) and correctly lists openrouter as _skipped_; the
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
  Anthropic's own pricing table and _Model IDs and versioning_ page. Every other provider host —
  `openrouter.ai`, `developers.openai.com`, `x.ai` / `docs.x.ai` / `api.x.ai`, `ai.google.dev`,
  `platform.moonshot.ai`, `docs.mistral.ai`, `api-docs.deepseek.com` — is refused at CONNECT
  (`403 Forbidden`), and direct page fetches are blocked too. For those labs, **the web-search tool
  could still read the lab's own models/pricing page and quote it**, which is stronger evidence
  than a tracker but is not the same as reading the page by hand; every figure taken that way is
  named below and is corroborated by at least one independent source that agrees exactly.

  **The systematic defect: a "cheaper sibling" invented from the lab's tier naming.** The bundle's
  header comment says non-flagship siblings "follow each lab's established tier naming" — and three
  of them had been _named by that convention rather than read off a catalog_, so they pointed at
  models that do not exist. Each fails at request time, not at load, which is exactly what step 3
  exists to catch, and each carried a price attached to a model nobody can call:

  | Was                             | Price it carried | Is now                               | Why                                                                                                                                                                                                                                               |
  | ------------------------------- | ---------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
  | `gpt-5.6-mini` "GPT-5.6 Mini"   | $0.25/2          | `gpt-5.6-terra` **+** `gpt-5.6-luna` | GPT-5.6 went GA 2026-07-09 as **Sol / Terra / Luna**, with no `-mini` or `-nano` member. Terra is the tier that took `mini`'s place; Luna sits below it.                                                                                          |
  | `grok-4.5-fast` "Grok 4.5 Fast" | $0.5/1.5         | `grok-4.3` "Grok 4.3"                | xAI's own models table lists `grok-4.6`, `grok-4.5`, `grok-4.3`, the `grok-4.20-0309` pair and `grok-build-0.1` — no `-fast` text model. `grok-4.5` is priced identically to 4.6, so **4.3** ($1.25/2.50, 1M context) is the actual cheaper tier. |
  | `glm-5.2-air` "GLM-5.2 Air"     | $0.2/1.1         | `glm-4.5-air` "GLM-4.5 Air"          | z.ai's own pricing table ships Air only in the 4.5 generation (GLM-4.5-Air, GLM-4.5-AirX). $0.2/1.1 **is** GLM-4.5-Air's published rate — the price was always right, the id and the name were not.                                               |

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
  UTC, Mon–Fri; every other hour, weekends included, is off-peak at half the peak rate) _and_
  raised the underlying rate. The bundle was still carrying the pre-2026-08-16 flat rates:

  | Model               | Was (old flat) | Peak           | Off-peak   |
  | ------------------- | -------------- | -------------- | ---------- |
  | `deepseek-v4-pro`   | $0.44/0.87     | **$1.32/3.96** | $0.66/1.98 |
  | `deepseek-v4-flash` | $0.14/0.28     | **$0.44/1.32** | $0.22/0.66 |

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
  re-checked against _Model IDs and versioning_ as well: the 4.6-generation dateless format gives
  `claude-sonnet-4-6` / `claude-opus-4-8` / `claude-sonnet-5` / `claude-opus-5` / `claude-fable-5`
  verbatim, and `claude-haiku-4-5` is the documented short alias for the pre-4.6 snapshot
  `claude-haiku-4-5-20251001`. Roster shape unchanged: Opus 4.7/4.6/4.5 and Sonnet 4.5 are listed
  and deliberately dropped, and Mythos 5 stays out as limited-availability.

  **Three of the four figures owed since 2026-08-20 now agree with their lab's own page:**
  Grok 4.6 `$2/6` (xAI's table, base <200K tier — it doubles to `$4/12` at 200K+, and per the
  standing precedent the block carries the base tier), Qwen3.8 Max `$2/6`, GLM-5.3 `$1.40/4.40`.
  Gemini 3.6 Flash's `$1.50/7.50` standard rate also agrees with Google's page.

  **Two live discounts were found and deliberately _not_ shipped.** GPT-5.6 Sol's short-context
  rate was cut to `$4/20` on 2026-08-22, promotional and stated as available at least through
  **2026-11-21** (standard unchanged at `$5/30`); and a Gemini Flash introductory
  `$0.75/3.75` runs through **2026-12-31** against a `$1.50/7.50` standard — though two reads of
  Google's page disagreed about whether that window belongs to **3.6** Flash (the bundled entry) or
  to **3.7** Flash, which is a second reason not to ship it. _Where a price may come from_ bars a
  discount that could not be read off the provider's own promotions page **directly**, and neither
  could be, so both entries keep their plain standard rate with no `discount:` block.
  Skipping a discount errs toward over-reporting, which the bill corrects; shipping an unverified
  one under-reports, which nothing corrects. Both are top of the owed list.

  **Everything else: tier 3, left alone.** Mistral Medium 3.5 and Small (sources quote _Medium 3_
  at `$1/3` and several different Small variants — no exact agreement on the bundled entries),
  Qwen3.7 Plus (no tracker publishes a per-token rate), MiniMax M2.7 (sources describe the whole
  M-series sharing one standard tier, which does not reconcile cleanly with the home block carrying
  M3 at list and M2.7 at half), Gemini 3.5 Flash-Lite and 3.1 Pro, and every OpenRouter figure.
  Existence _was_ confirmed this pass for `deepseek-v4-flash`, `gpt-5.3-codex`,
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
  **GLM-5.2** and an unversioned _Mistral Medium / Small_; `providers.py`'s `openai` `LLMProvider`
  carried `description="… + GPT-5.6 Mini"`, which is the string `make setup` prints; and this
  file's own §2 table listed _Mistral Medium / Small_ the same way. All four now match
  `config.example.yaml`'s marker blocks, and **step 2 above now names all seven places**, flagging
  the four that are pure prose no test can read.

  **The bundle is 41 paid models** — 6 Anthropic + 13 OpenRouter + 22 home — and every count in
  this file and in `test_sync_api_key_models.py` moved with it.

  Mechanical half green: `scripts/audit_models.py` reports **no drift** before and after the edits
  (display-name/price agreement and two-source parity both hold) and correctly lists openrouter as
  _skipped_ rather than as drift; the stale-fixture self-test
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
  supposed to prevent inverted: the window closed _downward_, and a discount that lapses on its own
  gets that case wrong in the expensive direction. Step 5 of the checklist now says to read the
  provider's _note_ as well as its table for exactly this reason.

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
  agreement and two-source parity both hold) and correctly lists openrouter as _skipped_; the
  stale-fixture self-test (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still
  surfaces all four drift kinds and exits 0; `sync-api-key-models.py --dry-run` is a clean no-op;
  the price-in-a-name grep prints nothing; and `test_config_integrity.py`, `test_model_price_fields.py`,
  `test_sync_api_key_models.py`, `test_setup_wizard.py`, `test_audit_models.py` and `test_pricing.py`
  are green (273 tests). The bundle stays **40** paid models.

- **2026-08-25 (rule addition, not a sync) — mechanical half clean, tier 1 unavailable for the
  sixth pass running, no roster or price change; three stale _descriptions_ of the roster fixed.**
  Run while adding **step 2, First-party key coverage** above — the standing rule that every
  big-name lab gets its own `.env` key with a fuller lineup, flagship doubled on OpenRouter —
  and the `TestFirstPartyKeyCoverage` suite that pins its machine-readable half. **Tier 1 remains
  unreachable:** `openrouter.ai` answers `403 Forbidden` through this environment's proxy and the
  eleven first-party hosts are likewise blocked, so no figure was read off a provider's own page
  and **no price or slug was touched** — the roster is byte-identical to the 2026-08-20 pass.
  What _had_ drifted was three places that only **describe** the roster, which is exactly the
  failure the new step exists to catch: `.env.example` and `sync-api-key-models.py`'s `QUICK START`
  docstring still advertised **Grok 4.5**, **Qwen3.7 Max** and **GLM-5.2** after the 2026-08-20
  roll-forward to **Grok 4.6 / Qwen3.8 Max / GLM-5.3**, and the README's §2 bullet listed only the
  Anthropic and OpenRouter keys — the nine first-party home keys were undocumented for users.
  All three now match `config.example.yaml`; `MINIMAX_API_KEY` also moved out of the generic
  "OpenAI-compatible" list into the model-provider key section where the other ten live.
  Mechanical half green: `scripts/audit_models.py` reports **no drift** (display-name/price
  agreement and two-source parity both hold) and correctly lists openrouter as _skipped_ rather
  than as drift; `sync-api-key-models.py --dry-run` is a clean no-op; and
  `tests/test_sync_api_key_models.py` (47, including the four new ones),
  `test_setup_wizard.py`, `test_config_integrity.py`, `test_audit_models.py` are green.
  Each new test was also confirmed to _fail_ on the drift it guards — a key dropped from
  `.env.example`, and a home block removed — so the step is enforced, not merely written down.

- **2026-08-24 (feature PR, not a sync) — mechanical half clean, tier 1 unavailable for the
  fifth pass running, no roster or price change.** Run as the audit step of the checklist while
  adding §21 (concurrent chats), not after an upstream merge. **Tier 1 remains unreachable:** the
  egress proxy still refuses `openrouter.ai` at CONNECT (`Tunnel connection failed: 403
Forbidden`), and `audit_models.py` listed openrouter as _skipped_ rather than as drift — the
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
  and `audit_models.py` correctly listed openrouter as _skipped_ rather than as drift. General
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
  _still_ unreachable — `openrouter.ai` and every first-party host answer 403 on CONNECT,
  so **tier 1 was unavailable again and nothing here is verified**. What was different this
  time is that general web search _was_ reachable, so tier 2 could actually run instead of
  falling straight through to tier 3. Mechanical half clean, exactly as before:
  `scripts/audit_models.py` reports **no drift**, the stale-fixture self-test
  (`--catalog scripts/fixtures/model_audit_stale_catalog.json`) still surfaces all four
  drift kinds, `sync-api-key-models.py --dry-run` is a clean no-op on an empty env, and the
  six model/pricing suites are green (269 passed).

  **The four still-owed figures from 2026-08-20 all corroborate at the shipped numbers** —
  each read off several independent trackers that agree exactly on _both_ numbers, none of
  them reprinting a single launch post. No edit was needed for any of them:

  | Model              | Shipped  | Corroborated                                                    | Verdict   |
  | ------------------ | -------- | --------------------------------------------------------------- | --------- |
  | Grok 4.6           | $2/6     | $2/6 (base tier; 200K+ prompts bill the whole request at $4/12) | confirmed |
  | Qwen3.8 Max        | $2/6     | $2/6                                                            | confirmed |
  | GLM-5.3            | $1.4/4.4 | $1.4/4.4 (z.ai list; resellers quote 10% off the same list)     | confirmed |
  | Mistral Medium 3.5 | $1.5/7.5 | $1.5/7.5                                                        | confirmed |

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
  a later pass may reverse. First, the roll-forward rule in _Which models to keep in the
  bundle_ moves a lab's **flagship** and leaves the cheaper siblings untouched; Google's
  flagship is Gemini 3.1 Pro (confirmed still current this pass — 3.5 Pro has slipped past
  its announced window and has no API model id), and 3.6 Flash is a cheaper sibling, so the
  mechanical rule does not fire here. Second, 3.7 Flash's _current_ price is an introductory
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
  refuses `openrouter.ai` (403 on CONNECT) _and_ every first-party provider host
  tried (anthropic.com, x.ai, platform.openai.com, deepseek.com, z.ai), so the
  audit listed openrouter as _skipped_ — correctly, not as drift — and no figure
  could be read off a provider's own page. With no reachable page **and** no
  reachable secondary source, tier 2 was unavailable too, so this pass is tier 3
  throughout: **every entry left exactly as shipped**. Nothing here is evidence
  that the roster is current — only that it is self-consistent.
  **Still owed to the next unrestricted pass:** the four labs rolled forward on
  2026-08-20 from corroborated sources (Grok 4.6, Qwen3.8 Max, GLM-5.3, Mistral
  Medium 3.5) are still un-verified, and GLM-5.3's price remains the most
  provisional of them.

- **2026-08-20 — partial.** Offline half clean: `scripts/audit_models.py` reported no drift (display-name/price agreement and two-source parity both hold), the stale-fixture self-test still surfaces all four drift kinds, and `sync-api-key-models.py --dry-run` plus the four regression suites are green. **Anthropic block fully verified** against the provider's current model list — all six slugs (`claude-fable-5`, `claude-opus-5`, `claude-opus-4-8`, `claude-sonnet-5`, `claude-sonnet-4-6`, `claude-haiku-4-5`), all six price pairs, the 0.1x cache-read rates, and Sonnet 5's `$2/10` intro window through **2026-08-31** all match; the roster shape (Opus/Sonnet keep last-4.x + current-5, Haiku/Fable latest only) is correct as-is, and Mythos 5 stays out because it is invitation-only, so a normal `ANTHROPIC_API_KEY` cannot reach it. **Every other provider unverified:** the environment this pass ran in blocks egress to `openrouter.ai` and to all eleven first-party provider hosts, so no figure could be read off a provider's own page. Existing entries were therefore left alone — a price that is wrong _with confidence_ silences the next audit, which is worse than one that is merely stale — but four labs had shipped a new flagship, and those were rolled forward from corroborated secondary sources and named below so the next pass re-checks them.

  **Roster rolled forward on four labs, from corroborated secondary sources — re-verify these on the next unrestricted pass.** Four new flagships had shipped since the last roster edit, and the _Which models to keep in the bundle_ rule rolls each one forward mechanically (new flagship in, previous flagship out, cheaper sibling untouched). They were applied rather than deferred, because a lab's flagship being a generation behind is a visible loss to every user of that key, while the risk here is bounded and recorded:

  | Lab     | Out         | In              | Slug                               | Price used                |
  | ------- | ----------- | --------------- | ---------------------------------- | ------------------------- |
  | xAI     | Grok 4.5    | **Grok 4.6**    | `grok-4.6` / `x-ai/grok-4.6`       | $2/6 (unchanged from 4.5) |
  | Qwen    | Qwen3.7 Max | **Qwen3.8 Max** | `qwen3.8-max` / `qwen/qwen3.8-max` | $2/6 (was $1.5/4.4)       |
  | z.ai    | GLM-5.2     | **GLM-5.3**     | `glm-5.3` / `z-ai/glm-5.3`         | $1.4/4.4 (was $1.15/3.6)  |
  | Mistral | Medium 3    | **Medium 3.5**  | `mistral-medium-3-5`               | $1.5/7.5 (was $0.4/2.0)   |

  **What "corroborated" means here, and why it is not the same as verified.** Every figure and slug above agreed across several independent price trackers _and_ matched an OpenRouter model-page URL for the same slug — but none was read off the provider's own page, because the environment this pass ran in blocks egress to all of them. That is tier 2 of _Where a price may come from_ — an allowed outcome rather than a rule bent, but weaker than a verified figure, so it is recorded rather than hidden precisely so the next audit is **directed** at these four rather than silenced by them: the failure mode the "verify, never invent" rule guards against is a wrong price that nobody knows to re-check, and a named list defeats that.

  Three judgement calls inside the roll-forward, each of which a later pass may reverse:
  - **GLM-5.2's 76%-off OpenRouter promotion was dropped, not carried over.** A discount is quoted for a specific model; carrying one across a version bump would advertise a price nobody was ever offered. z.ai had not published a per-token GLM-5.3 rate at the time of this pass, so its price is the most provisional of the four. Cost spread survives comfortably without it — DeepSeek V4 Flash ($0.14/0.28), Mistral Small ($0.1/0.3), Llama 4 Maverick ($0.2/0.8), GLM-5.2 Air ($0.2/1.1), Gemini 3.5 Flash-Lite ($0.3/1.2), and MiniMax M3's live promo all remain.
  - **Mistral Medium is now pinned (`mistral-medium-3-5`) instead of aliased (`mistral-medium-latest`).** The alias is what let this entry sit labelled "Medium 3" at Medium 3's price while the alias itself had moved on — the name, the slug, and the price were three things that could drift apart with nothing raising. Pinning costs the automatic follow and buys an entry whose three halves describe the same model. If the reported Medium 3.5 price is right, the aliased entry had been under-billing by roughly 4x.
  - **Grok 4.6's price is its base tier.** xAI bills the whole request at a higher rate once a prompt passes 200K tokens; the `price:` block holds one rate, so it carries the base tier, matching how every other entry in the bundle works.

  The bundle is still **40** paid models — this rolled the roster forward rather than growing it — every flagship is still doubled home + OpenRouter, and `scripts/fixtures/model_audit_stale_catalog.json` was regenerated against the new roster so all four drift kinds still fire (the fixture's `_comment` now spells out the four deliberate drifts to re-apply).
