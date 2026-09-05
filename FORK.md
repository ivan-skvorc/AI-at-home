# Fork Notes — `deer-flow-2-local`

> **Vibe-coded disclaimer.** This fork was put together with heavy LLM assistance and only light human review. The two added features have been smoke-tested but not stress-tested. Treat this as a personal-use scratchpad, not production-grade work. Upstream is the source of truth for everything else: <https://github.com/bytedance/deer-flow>.

## How to use this file

**Making a change? Run the procedure in [`CHANGE_CYCLE.md`](CHANGE_CYCLE.md).**
That file is the *order of operations* — implement, decide whether a new test is
owed, add or retire the checklist rows below, run the list, decide on the audit,
open the PR — and it reads this file's two lists rather than copying them.
"Run the code change cycle from CHANGE_CYCLE.md" is the whole instruction. This
file stays the *material*: the checks themselves, and why each one exists.

**This file is the fork's checklist, not its brochure.** Two things are asked of
anyone — human or coding agent — who adds a feature, changes one, or merges
upstream into this fork, and both live in the two sections directly below. The
first is always due; the second is a **decision**, and usually the answer is no:

1. **Run the checks.** [Post-sync feature checklist](#post-sync-feature-checklist)
   is the list: the mechanical gates first, then one row per fork feature naming
   the exact command that proves that feature survived. Run the whole thing on
   every upstream merge; on a feature PR, run the rows your change touches. What
   a _new_ feature has to ship alongside its code — README section, checklist
   row, `AGENTS.md` entry, changelog line, tests — is spelled out in
   [Adding a new fork feature](#adding-a-new-fork-feature--what-to-write-and-where).
2. **Run the model audit only when it is asked for.**
   [The model bundle and its audit](#the-model-bundle-and-its-audit) keeps the
   shipped roster honest — no retired or invented slugs, settings that match the
   model family, prices that match the provider's own page, the two-ways-in
   shape — but it is **opt-in, not part of a sync**. The manual pass means
   reading a dozen provider pages, and a roster nothing has happened to comes
   back identical, so running it by reflex spends real time and tokens to
   confirm what the last pass already said. Run it when the user asks for one,
   when the weekly `model-audit` job reports actual drift, or when you changed
   the bundle yourself. Otherwise check
   [`docs/model-audit-log.md`](docs/model-audit-log.md) for when it last ran,
   say so, and move on.

**The checklist is only true if you maintain it.** A feature that ships without a
row is a feature the next sync cannot verify, and a row whose test no longer
exists is worse than no row at all — it reads green and checks nothing. So:
**adding a feature means adding its row in the same change set, and removing a
feature means removing its row.** If a check stops being the right one, replace
it; if it stops being needed, delete it. Treat the table as code that happens to
be prose.

**Where the depth goes.** The row itself stays in this file:
`scripts/upstream_sync.py` parses that table into every auto-generated sync PR, so
a row that moves elsewhere silently disappears from the list meant to prove the
fork still works. Everything _behind_ the row can move. Keep a row to the
feature's name, the command, and the one or two asserts that are silent when
broken; when it needs more than that, put the depth in its own file — or in the
nearest `AGENTS.md`, for what an agent needs before editing the code — and link
it from the row. There is a hard budget forcing this rather than a preference:
the rendered PR body is ~63 KB against GitHub's 65,536-character limit, and
`test_the_body_stays_within_github_limits` fails when it stops fitting.

**Everything after the audit is reference.** [What this fork adds](#what-this-fork-adds)
(§1–§23) records _why_ each feature is shaped the way it is and which properties
a refactor must not "simplify" away; the sections after it cover setup, cost,
Tailscale, and troubleshooting. Read them when a check fails and you need to know
what the check was defending.

## Upstream sync

Pull upstream changes into this fork with:

```bash
git fetch upstream
git merge upstream/main      # merge, not rebase — see below
```

The fork's added files (`scripts/sync-ollama-models.py`, `scripts/sync-api-key-models.py`, `scripts/ensure_camoufox.py`, the input-box dropdown JSX, the `suggestions-settings-page.tsx` + its `settings-dialog.tsx` section, the task_tool.py override) are unlikely to conflict with upstream changes since they're either new files or additive blocks on stable anchors. The launch-script hooks (Ollama sync + API-key model auto-config + Camoufox fetch in `scripts/serve.sh`, `scripts/docker.sh`, `scripts/deploy.sh`, `docker/dev-entrypoint.sh`, `backend/Dockerfile`) are additive blocks on stable anchors. The auto-config's model definitions live in `config.example.yaml` (the `auto-model-config` marker blocks) and `scripts/wizard/providers.py`; if upstream restructures `task_tool.py`, `input-box.tsx`, or those launch scripts, expect a small merge.

**Merge, not rebase.** This is a long-lived, published fork whose `main` carries its own merge commits and merged PRs, so a sync is a `git merge upstream/main` — never a rebase, which would rewrite that public history, orphan the merged-PR refs, and force every overlapping-file conflict to be re-resolved commit-by-commit. Merge resolves each conflict once and keeps a clean "fork vs. upstream" audit trail.

**It also runs itself weekly.** `.github/workflows/upstream-sync.yml` fetches
upstream every Monday, merges (never rebases) onto a dated
`upstream-sync/<date>` branch, runs the mechanical gates below, and opens a PR
whose body is the checklist that follows — generated from this file by
`scripts/upstream_sync.py`, not copied into the workflow, so it stays current as
the fork grows. Nothing to sync means no PR.

Two behaviors are deliberate. **A conflicted merge still opens a PR**, flagged in
the title and listing every conflicted path, because a conflict is exactly when a
human is most needed and most needs to know early; the gates report as _skipped_
rather than passing, since a conflicted tree has nothing coherent to test, and
the body says not to merge it as-is. And **the job never force-pushes** — a
rejected push is reported as a warning and left alone, because the branch may
carry someone's in-progress resolution. The PR is a starting point: the feature
verification below is still a human pass, which is the whole reason the body is
a checklist rather than a green tick.

One known limitation: `GITHUB_TOKEN` may not push changes to files under
`.github/workflows/`, and upstream regularly changes theirs. When a merge touches
them the push is rejected; the PR body calls out the affected paths so the sync
can be finished locally with a personal access token.

### Post-sync feature checklist

After every upstream merge, run this checklist before pushing — passing unit tests do not prove the fork's _UI wiring_ or _launch-time scripts_ survived a large merge. Root commands run from the repo root; backend commands from `backend/`.

First, the mechanical gates:

- [ ] No leftover conflict markers: `git grep -nE '^(<{7}|={7}|>{7})( |$)'` returns nothing.
- [ ] Backend: `make lint && make test` (CI enforces `ruff format --check`). **One failure is environmental, not yours:** `test_browser_automation.py::test_real_playwright_navigate_click_type` launches a real headless Chromium, and its only guard is `pytest.importorskip("playwright.async_api")` — which checks the _Python package_, not the _browser binary_. So on any machine whose pre-baked Playwright browsers are older than the pinned `playwright` (1.60.0 wants build `1223`; a sandbox image shipping `chromium_headless_shell-1194` is the common case), it fails with `Executable doesn't exist at …/chromium_headless_shell-<build>/…` while the other 49 tests in that file pass. It is deterministic, not a flake, and it is not a regression — confirm with `git diff HEAD@{1} HEAD -- backend/tests/test_browser_automation.py backend/packages/harness/deerflow/community/browser_automation/`, which is empty on a sync that did not touch them. Don't skip or quarantine the test, and don't run `playwright install` in an agent sandbox that pre-bakes its browsers; just note it and read the rest of the suite.
- [ ] **Upstream pinned a list the fork extends, or read from disk in a path the fork keeps disk-free.** Two shapes of the same collision, both seen on the 2026-09-02 sync, and both invisible until the suite runs. (1) An upstream test asserting an _exact_ schema — `test_task_tool_description_is_optional_but_discoverable` pins `task`'s full property list, which the fork's per-call `model=` (§22) legitimately extends; re-assert the fork's list rather than loosening the check to a subset, so a future upstream change that drops the parameter still fails loudly. (2) An upstream feature adding a config read inside a path the fork guarantees is config-free — upstream's custom-agent store put `get_app_config()` under `apply_prompt_template`, which §19's `TestConfigIndependence` requires to touch no disk because `config.yaml` is gitignored and absent in CI. The fix is to thread the already-resolved `app_config` down (`get_agent_soul` → `load_agent_soul` → `get_agent_store`), never to relax the guard: it was written strict precisely because "does it work without the file" passes while the fallback is still there, silently reading a developer's own `config.yaml`.
- [ ] **VPN-hostile defaults** (§31): `cd backend && uv run pytest tests/test_searxng_client.py tests/test_ensure_camoufox.py tests/test_camoufox_runtime_deps.py tests/test_search_fetch_defaults.py -q`. Four independent regressions, each silent: `TestCamoufoxRuntimeLibraries::test_the_libraries_are_installed_beside_the_browser_copy` (a browser copied into a runtime stage that cannot run it — every presence check still passes); `TestFetchEnvironment::test_the_fetch_call_site_actually_uses_the_scrubbed_environment` (the *call site*, not the helper — the helper tests pass against a module that cannot resolve `os`); `TestUnresponsiveEngines::test_all_engines_blocked_raises_rather_than_returning_empty` **together with** `test_a_genuinely_empty_result_set_is_still_a_success` (both directions — collapsing them into "empty means error" breaks a legitimate no-match search in silence); and `TestSearxngEngineMix` (the VPN-tolerant engines, and that the json/limiter deltas survived the edit). A sync that drops the apt block from `backend/Dockerfile`, or restores `data.get("results", [])` without the `unresponsive_engines` branch, is green everywhere else.
- [ ] **Offloaded-model context sizing** (§30): `cd backend && uv run pytest tests/test_sync_ollama_models.py tests/test_setup_wizard.py -q`. Bounded on **both** sides, and each side is a different silent failure. `TestVramNumCtxLimitUnderOffload::test_a_model_bigger_than_vram_gets_a_window_the_agent_can_run_in` catches the 4096-token floor that makes a 128K model unusable; `test_it_does_not_hand_the_whole_card_to_the_kv_cache` catches the opposite — Ollama pays for context in GPU layers ([#9750](https://github.com/ollama/ollama/issues/9750)), so an unbounded window evicts the weights and the model merely crawls instead of failing. `test_a_model_that_fits_still_takes_all_the_spare_vram` pins that the fits-in-VRAM path did not move. Do not "simplify" the two branches into one: they are opposite policies for opposite regimes.
- [ ] **Local-model subagent parallelism** (§34): `cd backend && uv run pytest tests/test_subagent_local_residency.py tests/test_subagent_executor.py -k "residency or capacity" -q`. Everything this defends is silent: Ollama answers an over-dispatch by queueing inside the daemon or evicting a model, never by failing. `TestGate::test_a_model_that_fits_the_card_once_runs_one_subagent_at_a_time` and `test_a_model_the_card_holds_twice_runs_two_at_a_time` are the feature; `test_models_that_co_reside_run_in_parallel` is the half a "just serialize local models" simplification would delete. `test_a_small_model_does_not_jump_the_queue_ahead_of_a_waiting_large_one` pins strict FIFO (throughput here is bought with starvation), `test_a_model_bigger_than_the_card_runs_alone_rather_than_never` pins that an offloaded model is slow, not barred, and `test_an_unknown_model_is_not_gated_at_all` pins that a hosted model or an unsized entry dispatches exactly as before. `test_aexecute_holds_gpu_residency_for_a_local_model_for_the_whole_run` is the wiring: the gate is nested inside the process capacity slot and wraps the model call, and it goes red if either is undone.
- [ ] **Sidebar chat folders** (§32): `cd frontend && pnpm test chat-folders` and `cd backend && uv run pytest tests/test_user_ui_state.py tests/test_chat_folders_settings_router.py tests/test_threads_router.py -k "folder or pin or ui_state or chat_folders" -q`. Three independent silent failures. `groupThreadsByFolder > lists a filed chat inside its folder and NOT at the root` **together with** `falls back to the root for a folder that no longer exists` — both directions of the same partition: a merge that "helpfully" keeps filed chats in the root list duplicates every conversation, and one that drops threads pointing at a deleted folder makes them vanish with no error anywhere. `test_patch_thread_folder_move_preserves_updated_at` **together with** `test_patch_thread_folder_with_a_wrong_typed_value_still_bumps_updated_at` — the no-touch exemption is shape-guarded per key; collapsing it to "the key is present" is green everywhere else and hands any client a way to edit metadata without touching recency. And `test_folders_and_tabs_do_not_clobber_each_other`, because both keys share one `ui_state.json` and a writer that replaces instead of merging silently eats the other feature's state. Also run `cd frontend && pnpm test:e2e sidebar-chat-folders` when the sidebar itself was touched.
- [ ] **Sidebar list scroll margin** (§35): `cd frontend && pnpm test thread-list-scroll-margin thread-list-virtualizer`. The sidebar's chat lists virtualize inside a scroll container they do not own, so each one carries its own offset into it, and a stale offset selects the wrong rows while positioning them correctly — the reader gets an empty band and no error anywhere. Three signals keep it honest and **each covers a hole the others do not**: `re-measures on a re-render, which is how an expanding folder reports` (the layout effect deliberately has no dependency list — restoring one is green against every other test here), `re-measures when a section above the list grows` **together with** `re-measures and re-observes when a section mounts after the list` (the ResizeObserver/MutationObserver pair; a sibling growing never re-renders this component, and the sidebar's sections are conditional, so watching a fixed set at mount is not enough), and `still corrects itself on scroll when nothing else reported` (the backstop — dropping it is invisible until a layout change resizes no box). `keeps the offset scroll-invariant` pins the property that makes re-measuring during a scroll safe at all. Also run `cd frontend && pnpm test:e2e sidebar-long-chat-list sidebar-chat-folders` when the sidebar or the virtualizer was touched — a real layout engine is the only thing that can say the rows the reader is looking at are the rows that are there.
- [ ] **Automatic conversation renaming** (§33): `cd backend && uv run pytest tests/test_auto_title_preference.py tests/test_title_middleware_core_logic.py -q` and `cd frontend && pnpm test auto-title`. Three silent failures, and none of them makes a title stop appearing. `test_the_title_is_written_from_after_agent_not_after_model` compares the bound hooks against `AgentMiddleware`'s own — the same predicate LangChain's factory uses to place the node — because a merge that restores the `after_model` spelling still produces titles, just back inside the run window where the Gateway refuses the user's own rename with a 409. `test_a_client_cannot_switch_renaming_on_when_the_operator_disabled_it` **together with** `test_an_unconfigured_model_is_dropped_rather_than_dialled`: both are the boundary direction, and both are green if you drop the check and simply honor whatever the browser sent. And `distinguishes 'server default' from 'no model call'` — the absent key and the empty string are opposite instructions to the backend, so collapsing them either starts spending a model call the user declined or ignores the model the operator configured. Also confirm `_ensure_interrupted_title` in `runtime/runs/worker.py` still runs on **every** terminal status: narrowed back to `interrupted`, a first turn that ends in `ask_clarification` is never named, and never can be. Run `cd frontend && pnpm test:e2e auto-title-settings` too when the settings dialog itself was touched — a merge that reorders or renames the nav rows breaks the page's only click-through coverage without failing a unit test.
- [ ] **Scroll-back history survives a restart** (§28): `cd backend && uv run pytest tests/test_run_history_durability.py tests/test_config_upgrade_script.py tests/test_doctor.py -q`. The failure this defends is silent in every log: with `run_events.backend: memory` the page endpoint's store is process state, so after a Gateway restart a long conversation still opens and still renders its recent turns from the checkpoint, and merely stops loading older messages when the reader scrolls up. `test_older_messages_still_page_backwards_after_a_restart` is the claim, across a real engine teardown and rebuild; `test_the_memory_store_is_what_loses_it` is the other direction, so the file goes red if durability gets "fixed" in the memory store instead of the default. **All three default sources must survive a sync independently** — `test_the_schema_default_persists_run_events` (a `config.yaml` with no `run_events:` section, and the Helm chart), `test_the_shipped_example_persists_run_events` (fresh installs copy the example verbatim, so upstream restoring `memory` there overrides the schema default), and migration 50 in `test_run_events_memory_is_migrated_but_other_memory_backends_are_not` (existing installs, which keep whatever value they were created with). An upstream merge that reverts any one of them re-breaks a different population and nothing else notices. `TestCheckRunEventsDurable` keeps `make doctor` reporting the combination for installs that never run `make config-upgrade`.
- [ ] **A reply keeps the price it was billed at** (§17): `cd backend && uv run pytest tests/test_run_pricing_snapshot.py tests/test_thread_token_usage.py tests/test_run_repository.py -q`. Cost is read from `runs.pricing_snapshot`, not recomputed from the live config, and every way that can regress is silent. `test_a_model_dropped_from_the_roster_keeps_its_cost` is the motivating case and asserts **both** directions in one test — with the snapshot the spend survives, without it the run prices to `None` — so deleting the snapshot path fails loudly instead of just making conversations cheaper; note that the audit's own roster roll-forwards are what produce this, so it is a routine event, not an edge case. `test_a_later_price_change_does_not_rewrite_an_old_run` is the other half. Three guards exist because each is a way the fix could be worse than the bug: `test_a_currency_switch_re_prices_rather_than_summing_two_currencies`, `test_a_snapshot_cannot_switch_cost_reporting_back_on`, and `test_a_discount_is_not_re_expired_on_replay`. `TestSnapshotPersistence` is the plumbing — a snapshot computed correctly and then dropped by the store looks exactly like no snapshot at all, and every pricing assertion still passes — so it round-trips the SQL store, the memory store, and `_with_pricing_snapshot`, and pins that a completion **retry** without one does not erase the stored value. Keep `test_the_headers_stated_relation_still_holds_across_an_edit` too: `sum(steps) + superseded_cost == total_cost` is what the cost dropdown tells the reader, and per-run pricing is what makes it an identity. A store with no `by_run` must still price its `by_model` aggregate (`tests/test_thread_token_usage.py` covers it) — that fallback was broken once during this change and only the existing suite caught it.
- [ ] **CI's pnpm bootstrap stays retried and pinned**: `cd backend && uv run pytest tests/test_ci_pnpm_bootstrap.py -q`. Every frontend job begins by having corepack fetch the pinned pnpm from the npm registry, and a transient abort there does **not** look like a network error — it crashes Node's bundled undici parser with `AssertionError: assert(!this.paused)`, kills the job before a single test runs, and reads like a Node bug or a broken branch. Observed on PR #106: `frontend-unit-tests` died that way while `lint-frontend` downloaded the same tarball successfully **in the same run**, and the previous commit on the same branch had passed. The cost of that is not the re-run, it is the twenty minutes spent reading a diff that had nothing to do with it. `test_the_pnpm_download_is_retried` asserts the retry on the step's *shape*, so it can be rewritten but not removed, across every workflow that prepares pnpm (four today); `test_there_is_a_pnpm_bootstrap_to_check` exists because a renamed step would otherwise leave that parametrized test iterating an empty list and passing green. `test_every_workflow_prepares_the_version_the_repo_pins` is the drift guard: the version lives in five places (`frontend/package.json`'s `packageManager` plus one `corepack prepare` per workflow) and moves out of one at a time, and a mismatch means CI silently exercises a different pnpm than contributors run. Bumping pnpm is one change that touches all five.
- [ ] Frontend: `pnpm check && pnpm test`. **`pnpm check` now includes the formatting gate** (`prettier --check .`, then eslint, then `tsc --noEmit`) — it used to be eslint + tsc only, which meant the command every guide tells you to run before committing was not the command CI gates on, and an eslint/type-clean change could still fail `lint-frontend` on formatting alone. That discrepancy was documented right here and was still walked into twice, so it was removed instead of re-warned about (see the Prettier row below). `pnpm format:write` fixes what the check reports; `eslint --fix` normalizes imports and optional-chains but not Prettier whitespace.
- [ ] **Changed a shared UI control? Run the whole e2e suite, not the one spec you thought of.** `pnpm test:e2e` with no filter. A control's _specs_ are not the specs in the file you edited: they are every spec that clicks that control anywhere in the app, and nothing in `pnpm check` or `pnpm test` knows the difference. Observed live on the model-picker unification — the composer's picker was swapped into five screens, the Democracy spec was found and fixed by hand, and `suggestions-settings.spec.ts` was missed entirely because it drives the _same control_ from a different page. It failed only in CI. Two rules fell out of it, both now pinned by `frontend/tests/unit/components/workspace/model-picker-sites.test.ts`: a spec must locate a shared control by that control's **own** `data-slot`, never by the ARIA role of the primitive underneath (swap the primitive and the locator silently matches nothing), and a fast unit test should assert the contract so a six-minute e2e job is not the thing that tells you.

  ```bash
  # every spec, not just the feature you touched
  cd frontend && pnpm test:e2e
  # ...and the source-level guards that fail in milliseconds instead
  cd frontend && pnpm test model-picker-sites lazy-panels
  ```

  In an agent sandbox the pre-baked Playwright browsers are usually older than the pinned `playwright`, so the run dies with `Executable doesn't exist at .../chromium_headless_shell-<build>`. Do **not** run `playwright install` (see the backend note below for why). Point Playwright at the browser the image _does_ have, via a local config that is never committed:

  ```bash
  ls /opt/pw-browsers   # find the build that is actually present
  # then a throwaway config setting use.launchOptions.executablePath to
  # /opt/pw-browsers/chromium-<build>/chrome-linux/chrome
  ```

  A handful of specs (artifact streaming, the Lark integration, reasoning order) are **flaky** on an older browser build and vary run to run. `subtask-card.spec.ts`'s two *running*-state cases (`truncates a running task title with the shimmer inline`, `keeps a running card inside the row on a 375px viewport`) are the same class but **deterministic** on `chromium-1194` — they fail every run there, on an untouched `origin/main` as readily as on a feature branch. Confirm against CI on the same commit before calling one a regression, or reproduce on `origin/main` in the same sandbox: a spec CI passes and the sandbox fails is the browser, not your change. And check that your local `main` is not stale before using it as the baseline — a spec added upstream since your last fetch simply does not exist there, so it "passes" by not running, which reads exactly like your branch broke it.

  **A flake with a cause is fixed, not retried.** `thread-history.spec.ts`'s follow-up assertions were the other kind: the message list is virtualized, so a message is only in the DOM while it is inside the window around the current scroll position, and asserting immediately after a submit raced the history-page refetch that re-renders that window. It failed about half of local runs and lost all three CI attempts on 2026-09-01, on a PR that had not touched it. `expectMessageAtBottom` re-scrolls to the bottom and retries, which keeps what the assertion is for. If those assertions start flaking again the race is back — find it rather than widening the timeout. §28 fixes the scroll-ownership half of that race and explains why it still cannot be pinned by a red-then-green e2e.

  **An upstream e2e can assume upstream's mount lifecycle, which the fork has changed.** Seen live on the 2026-09-03 sync: upstream PR #5045 added `thread-title-sync.spec.ts`, whose "a stale metadata response cannot restore the old title after rename" case produces its racing in-flight metadata request by navigating away to the chat list and back — relying on the thread page **remounting** to refetch. Upstream has no keep-alive chat tabs (§9); this fork keeps the thread's `<ChatInstance>` and its `useThreadMetadata` query mounted across that navigation (`syncRoute` re-selects the same slot without a remount), so no refetch fired, the test's `staleMetadataRequestStarted` gate never resolved, and it hung to a 30 000 ms timeout — green on upstream CI, red only once merged here. It is invisible to `pnpm check`/`pnpm test` and, being a title race, does not surface in the one spec file you would think to run. The fix was **not** to touch the test (loosening it would drop the invariant) but to close the real gap the fork's feature opened: a kept-alive thread never refreshed its metadata after first load, so an externally-changed title/goal stayed frozen until a full reload. `chat-instance.tsx` now background-refetches metadata when a slot returns to the foreground (`isActive` false→true), which restores the classic remount's freshness while preserving keep-alive's no-remount, keeps the cached value visible during revalidation (so `canonicalTitle` still drives the header), and makes the upstream spec pass **as written**. Pinned by `thread-title-sync.spec.ts` going green under keep-alive; the no-remount guarantee it rides on is pinned by `chat-tabs.spec.ts` ("opening chats as tabs keeps both mounted").

- [ ] **The backend suite passes with no `config.yaml` on disk.** `config.yaml` is gitignored: it exists on any machine that has run `make config` and on none of CI's runners. `make test` therefore tests a _different_ repository state locally than in CI, and the gap is silent in the direction that matters — a test that reaches for ambient config is green here and red there. Observed live: PR #71's `apply_prompt_template` render tests called it with `app_config=None`, which falls back to `AppConfig.from_file()`; four store tests and three router tests passed locally and failed CI with `FileNotFoundError: config.yaml file not found`. The rule for new tests is to **inject the config** (`AppConfig(sandbox=SandboxConfig(use="test"))`, or `app.dependency_overrides[get_config]` for a route) rather than letting a `None` default find the developer's file. Verify the way CI sees it before pushing:

  ```bash
  mv config.yaml /tmp/config.yaml.aside      # CI has no config.yaml
  cd backend && make test
  mv /tmp/config.yaml.aside ../config.yaml   # put it back — make dev needs it
  ```

  Pinned for the prompt feature by `backend/tests/test_system_prompt_store.py::TestConfigIndependence`; the same trap applies to anything that resolves config, paths, skills, or models through a `None` default.

- [ ] **`AGENTS.md` byte budgets — two different checks, and the second is the one that bites.** `backend/tests/test_agent_guidance_check.py` asserts every guidance file against its **own** soft budget (root 16 KiB, module 28 KiB, local 40 KiB), as a hard assert rather than a warning; the standalone CI job (`scripts/check_agent_guidance.py`, run without `--strict-warnings`) only _warns_ below the per-file hard limits (20/32/48 KiB). For those, `make test` is the stricter gate. **The `agent-guidance` job is stricter about one thing: the effective chain.** A leaf inherits root + module + every guide down to it, and that sum has budgets of its own (80 KiB soft, **96 KiB hard**) — the hard one is a job _error_, not a warning, and so fails CI on its own. Most real chains sit above the soft limit already, so warnings there are normal and only the hard limit is a gate. The root file runs close to the line (69 bytes of headroom at the time of writing; `backend/AGENTS.md` had 97), so _documenting a feature can fail CI on its own_.

  When a section does not fit, push the depth down to a guide that **sits beside the code and has no children** — a leaf directory's own `AGENTS.md` (40 KiB budget) or, failing that, a plain reference doc outside the guidance tree — and leave a one-line pointer behind. **A directory with subdirectories is not a leaf**, and parking depth there is the trap: it costs the chain of _every_ package underneath. Observed live on the 2026-08-30 sync — the fork's editable-system-prompt notes sat in `agents/AGENTS.md`, one level above the code they describe, so every sibling package inherited them and `agents/middlewares/AGENTS.md` (pure upstream, untouched by the fork) reached 99508 bytes against the 98304 hard limit. Moving them into `agents/lead_agent/AGENTS.md`, beside `prompt.py`, took them out of three sibling chains at once.

  **It has now happened twice.** The second time (2026-08-31, the ComfyUI-on-by-default change) was not a sync at all: a **six-line service-topology row** added to the root file put `agents/middlewares/AGENTS.md` 564 bytes over the hard limit and failed both the `agent-guidance` job and `make test`, on a module the change never touched. The row was rewritten to one line pointing at FORK.md §26, which is where the depth belonged anyway. Note what did _not_ save it: the full backend suite had been run — before the documentation edits, which is exactly how a doc-and-code change is normally written. **A commit that touches any `AGENTS.md` now runs the checker through pre-commit** (`.pre-commit-config.yaml`, hook `agent-guidance`, repo-wide with `pass_filenames: false`, exiting 1 on errors and letting the soft-budget warnings through), so this is caught at the commit rather than in CI. That hook is pinned by `test_editing_guidance_is_gated_locally_before_ci_sees_it`; if it disappears, the trap is CI's problem again.

  **It has now happened three times.** The 2026-09-05 sync (14 upstream commits) added one middleware entry and put the same chain 635 bytes over, while upstream's new upload-state paragraph put `subagents/AGENTS.md` 537 over its own soft budget. Both were paid for the way this note predicted: the root file's compose/`BIND_HOST` prose went to a pointer at _Reaching the stack over Tailscale_ (the root is an ancestor of _every_ chain, so bytes out of it relieve all 29 at once), plus four more root paragraphs whose depth already lived in FORK.md or further down the same file; the leaf's 11.7 KB `acceptance_checks.py` paragraph moved beside the code as `subagents/ACCEPTANCE_CHECKS.md` with a summary and a pointer.

  **Current headroom is 329 bytes on the worst chain** (`agents/middlewares/`, 97975 of 98304) and 10474 on `subagents/AGENTS.md`. Upstream's own files account for most of the chain, so a sync of ordinary size will land here again and the fork is still the only side that can give ground. Next candidates, in order: the root's repository-map comments, then `backend/AGENTS.md` (28299 bytes, the chain's largest fork-editable file). Check before pushing:

  ```bash
  # per-file soft budgets *and* the real repository's chains, in one run
  cd backend && uv run pytest tests/test_agent_guidance_check.py -q
  # what the agent-guidance job actually runs — chain errors show up here
  # (also wired as the `agent-guidance` pre-commit hook, on any AGENTS.md edit)
  python3 scripts/check_agent_guidance.py
  ```

  Run them **after** the documentation edits, not before. Both read the worktree,
  so a suite that ran while the prose was still being written proves nothing about
  the prose — which is how this was missed the second time.

  Run **both**. `test_repository_guidance_has_no_checker_errors` puts the real
  worktree through the same `analyze()` the job calls and fails on any error it
  reports, so `make test` now catches a chain overflow too. It was added because
  nothing did: the file's other chain tests build synthetic files in a `tmp_path`,
  which proves the _checker_ works and says nothing about this repository — so the
  2026-08-30 sync went green locally and red in CI. Keep the standalone command in
  the loop anyway: it is the job verbatim, and it prints the warnings pytest
  deliberately does not fail on.

- [ ] **Prettier checks `frontend/`'s Markdown too — `frontend/src/AGENTS.md` included.** The
      `lint-frontend` job runs `cd frontend && pnpm format`, which is `prettier --check .` over the
      **whole directory**: every file type prettier has a parser for, minus `.prettierignore`. That
      takes in `frontend/AGENTS.md`, `frontend/CLAUDE.md` and `frontend/src/AGENTS.md` — the module
      guide the documentation-update policy sends you to on nearly every frontend change. Prettier's
      Markdown normalisation is invisible to read past: it rewrites `*emphasis*` to `_emphasis_`,
      which is what failed CI on 2026-08-31 (the image-generation prompt-mode change) — one italic,
      in a file its author did not think of as code.

  What makes this row worth reading is that **the warning already existed** (it was the second
  half of the frontend sync row above) and was walked into anyway, for the same reason as the
  `AGENTS.md` budget trap: `pnpm format` was run, and _then_ the prose was written. A third
  warning would have been the third thing to not read, so both halves were closed mechanically
  instead:
  - **`pnpm check` runs the format check first.** Every guide already said to run `pnpm check`
    before committing (`AGENTS.md`, `frontend/AGENTS.md`, `frontend/README.md`); it just was not
    true that this covered what CI gates. Now it is, and the instruction people already follow is
    the sufficient one.
  - **The pre-commit hook covers what prettier covers.** `frontend-prettier` carried
    `types_or: [javascript, tsx, ts, json, css]` — a second, hand-maintained definition of "what
    prettier formats" that had drifted from the job's, so a Markdown edit passed locally and
    failed in CI on a file the hook never opened. It now runs `--ignore-unknown` with **no type
    list at all**, letting prettier decide what it can parse (the one definition that cannot
    drift) while `.prettierignore` still applies to the paths pre-commit hands it.

  Both are pinned by `backend/tests/test_precommit_frontend_format.py`: if `check` loses the
  format step or the hook regains an extension allowlist, the gap is a test failure rather than a
  surprise in CI.

- [ ] `backend/uv.lock` reconciled: `cd backend && uv lock` (must include every fork extra — `camoufox`, `ollama`, `pymupdf` — alongside upstream's).
- [ ] Config schema in step: if the merge (or your own change) touched `config.example.yaml`'s **shape**, `config_version` is bumped, **the chart's copy is bumped with it** (`deploy/helm/deer-flow/values.yaml` _and_ that chart's `README.md` — `scripts/check_config_version.sh` fails the `validate-chart` job otherwise, and it is easy to miss because nothing outside CI reads it), and `make config-upgrade` merges the new keys into an existing `config.yaml` without clobbering hand edits. An existing install never gets a new section otherwise — the same delivery trap the pricing blocks hit (see the cost-overview row below). Verify on a copy: `python3 scripts/config_upgrade.py <copy-of-an-older-config> config.example.yaml` must report the new field and leave the rest alone.
- [ ] **Upstream added a config section — bump `config_version` yourself.** This is not a rare case, it is the _expected_ one on any sync that touches `config.example.yaml`, and it fails silently. Upstream's `config_version` sits **behind** the fork's (the fork bumps for its own sections, upstream never sees them), so upstream adding a top-level key does **not** move a version number the fork compares against. `config_upgrade.py` gates delivery on that version, so at equal versions an existing install keeps a config permanently missing the new upstream section. Observed live: the `bytedance/deer-flow@main` sync of 2026-08-12 added `mcp_tasks:` while leaving upstream's `config_version` at 33; the fork was at 36, so the upgrade was a no-op until the fork bumped to 37.

  It no longer fails _silently_: `config_upgrade.py` now compares the **shape** as well as the version, and a config that is stamped current but missing a shipped section is named on stdout with the fix. It still does not auto-deliver, and that is deliberate — the script runs on every launch path and the merge branch rewrites through `yaml.dump`, so auto-delivering would silently strip every comment from a user's config (see the limitation below). Warning loudly and leaving the file byte-identical is the trade; the version bump stays the explicit gate. Pinned by `backend/tests/test_config_upgrade_script.py::TestUpstreamSectionDelivery`. Detect it mechanically before trusting the gate above:

  ```bash
  # top-level keys upstream added that the fork's previous example did not have
  diff <(git show HEAD:config.example.yaml   | grep -oE '^[a-z_]+:') \
       <(git show upstream/main:config.example.yaml | grep -oE '^[a-z_]+:')
  ```

  Any line the merge introduces means **bump `config_version`** (plus both chart copies) even though upstream did not, then re-run the delivery check above and confirm the new key actually appears in the upgraded copy. **Known limitation, deliberately not fixed here — and it bites exactly when this gate fires.** The two upgrade paths behave differently: a _version-stamp-only_ upgrade (no missing keys) is text surgery and preserves comments, pinned by `test_comments_survive_a_version_stamp_upgrade`. But the _merge_ path — the one that runs precisely because a new section had to be delivered — rewrites through `yaml.dump` and drops **every comment** in the user's `config.yaml` (~3300 lines of inline documentation; measured on the `mcp_tasks` delivery above). Hand-edited _values_ survive; a `.bak` is written beside the file. So the sync that finally delivers a new upstream section is also the one that strips a user's config of its documentation. Say so in the release note, and keep the `.bak` until the result has been re-read.

- [ ] **Upstream re-implemented something the fork already forked.** The fork does not only _edit_ upstream files, it sometimes _replaces_ one with its own module. When upstream later extracts or rewrites the same code into a **new** file, git reports no conflict — both sides "added" different files — and the fork silently ends up with two parallel implementations, only one of which is wired up. The dead copy then absorbs upstream's future improvements forever, invisibly. Observed live: upstream #4765 extracted the chat body into `frontend/src/components/workspace/chats/chat-page.tsx`, which duplicates the fork's `chat-instance.tsx` (the keep-alive tab renderer) but **lacks the fork's cost header**. Resolution taken: keep `chat-instance.tsx` as the single renderer, delete upstream's copy, and let the next sync raise a loud modify/delete conflict that forces a port. After every merge, list the files upstream added and check none of them shadows a fork module:

  ```bash
  git diff --diff-filter=A --name-only HEAD@{1}...upstream/main -- frontend/src backend/packages
  ```

  For each hit, confirm it is actually imported. An added upstream file that nothing references is the signature of this failure, not tidy dead code.

- [ ] **No price has crept back into a `display_name`, and every discount that _can_ have an `until` has one.** The price is data in `price:`; a copy in the name is what used to drift, and it is what makes a discount unable to end without a human editing a string.

  ```bash
  # must print nothing: a bundled name carrying a price
  grep -nE 'display_name:.*\(\$[0-9]' config.example.yaml scripts/wizard/providers.py
  # review each discount and whether the provider has announced an end date
  grep -n -A 6 '^\s*#\?\s*discount:' config.example.yaml
  ```

  The first command is a hard gate — `test_no_bundled_model_carries_its_price_in_the_display_name` and the audit's `price_in_display_name` finding both enforce it. The second is a **review, not a gate**: several providers run open-ended promotions with no announced end date, so a missing `until` is legitimate and is deliberately _not_ an audit finding (a weekly issue nobody can close is how that job becomes one people ignore). Add an `until` when the provider announces one.

  An expiry that has already passed is _not_ a failure — that is the mechanism working, and the entry is inert until someone refreshes it. Removing the stale block is tidying, not a fix. Note the two fail-closed cases while you are here, because both look like "the discount vanished": an `until` that cannot be parsed, and a run where the current time is unavailable, are both treated as expired rather than eternal. Pinned by `backend/tests/test_model_price_fields.py::TestDiscountExpiry`.

- [ ] **Model audit — decide, don't default.** A sync does not earn a model-list pass on its own: the roster drifts on the providers' schedule, so a merge that touched no model config is no evidence about it, and re-deriving an unchanged roster costs a dozen page reads for the same answer. Run the **[Auditing the model list](#auditing-the-model-list-settings--pricing)** pass **only when asked** (CHANGE_CYCLE.md step 6); a drift report or a bundle-touching merge earns a line recommending one, not a pass nobody requested. Otherwise quote the last dated line in [`docs/model-audit-log.md`](docs/model-audit-log.md) and tick this. When you _do_ run it, read each slug/price off the **provider's own page** — or, when it cannot be reached, off several independent sources that agree exactly, logged as corroborated (_Where a price may come from_) (`scripts/sync-api-key-models.py --dry-run` and the model-format tests below do **not** catch a stale-but-well-formed price or a since-renamed slug, because both pass against any syntactically valid entry). Regression-gate whatever you change with `python3 scripts/sync-api-key-models.py --dry-run` + `cd backend && uv run pytest tests/test_sync_api_key_models.py tests/test_setup_wizard.py tests/test_config_integrity.py`.

Then confirm each fork feature end-to-end:

| Fork feature                                                                                            | How to verify it survived the merge                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Ollama auto-populate** (§1)                                                                           | `python3 scripts/sync-ollama-models.py --dry-run --verbose` — proposes entries when the daemon is up, prints `unreachable; skipping (no changes)` and exits 0 when it's down. Reconciliation logic is pinned by `backend/tests/test_sync_ollama_models.py`. That file's `TestWeightSizeReachesTheEntry` is the one that is **silent when broken**: it drives `main()` with a stubbed `/api/tags` and asserts the reported `size` lands in the entry as `size_bytes`, because dropping it leaves every entry valid, the sync idempotent, and the picker simply showing no size for any model — indistinguishable from a daemon that never reported one. Model tuples grew a 5th field (`size_bytes`) read positionally, same back-compatibility rule as `keep_alive`. The key must also stay in the model factory's exclude set (`backend/tests/test_model_factory.py::test_weight_size_never_reaches_the_provider_client`) and be returned by `/api/models` (`backend/tests/test_model_picker_metadata.py`) — un-exclude it and _only_ local models break, which reads as "Ollama is broken" rather than as a config bug.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **Ollama daemon lifecycle** (§1)                                                                        | `cd backend && uv run pytest tests/test_ollama_lifecycle.py` covers the `keep_alive` settings parse (including the nested `keep_alive_overrides` map, whose children must **not** leak into the flat `ollama.*` settings), the resolution precedence, the rendered entry, the VRAM-contention warning, `default_local_model`, preload, and the doctor rows. Wiring: `parse_ollama_settings` / `resolve_keep_alive` / `vram_contention_warning` / `default_local_model` / `preload_model` in `scripts/sync-ollama-models.py`; the `--preload-only` **backgrounded** call in `scripts/serve.sh` right after the sync; `scripts/doctor.py::check_ollama_readiness` in the new **Local Models** section; the documented keys in `config.example.yaml`'s `ollama:` block. Model tuples grew a 4th field (`keep_alive`) — `sync()` reads the tail positionally so 2- and 3-tuple callers still work; keep that back-compatibility if the shape changes again. Preload must stay backgrounded in `serve.sh`: it blocks until the weights are loaded. Manual: set `ollama.keep_alive: 30m`, relaunch, and confirm the regenerated marker block carries `keep_alive: 30m` on every entry.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **API-key model auto-config** (§2)                                                                      | On a _copy_ of `config.example.yaml`: `ANTHROPIC_API_KEY=sk-ant-… python3 scripts/sync-api-key-models.py --config <copy> --dry-run --verbose` logs `enabled 'anthropic' model block`; with an empty env the file stays byte-identical. Pinned by `backend/tests/test_sync_api_key_models.py`. All eleven `# === BEGIN/END auto-model-config: <provider> ===` marker blocks (anthropic, openrouter, and the nine first-party home blocks: openai, xai, google, deepseek, mistral, moonshot, qwen, minimax, zai) must still be present in `config.example.yaml`, each in sync with its `*_BUNDLE_MODELS` list in `scripts/wizard/providers.py` (`HOME_API_BUNDLES` registry) and its `PROVIDERS` entry in `scripts/sync-api-key-models.py`. **The big-name shape is a rule, not a coincidence** — every lab with a public API gets its own `.env` key enabling a fuller lineup (never a lone flagship), with that flagship _also_ on OpenRouter, exactly as `ANTHROPIC_API_KEY` gives six Claudes while only Fable 5.1 is routed. `TestFirstPartyKeyCoverage` fails if a key stops being documented in `.env.example`, a home block is trimmed to one model, a home flagship loses its OpenRouter twin, or a lab beyond Meta/NVIDIA is left routed-only. The two things no test can read — the script's `QUICK START` docstring and the README bullet advertising the keys — are step 3 of the [model audit](#auditing-the-model-list-settings--pricing).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **Democracy panels** (§22)                                                                              | `cd backend && uv run pytest tests/test_democracy_panel.py` covers the properties that fail _silently_: a per-call `task(model=...)` beating both the per-thread subagent dropdown and the routing policy, an unknown model failing that delegation instead of falling back, the roster being filtered to configured models with a sub-quorum panel rendering **no** organizer section, the collect-facts-once / do-not-verify / report-dissent rules, the **standing-panel** re-briefing (all four items a follow-up dispatch must carry, and the per-turn budget line), and **grading** (contribution-not-agreement, per-turn, the two scales rendering their own wording, and an unrecognized scale meaning _no_ grading rather than a default). Also asserts `democracy_participants` and `democracy_grading` are in `_CONTEXT_CONFIGURABLE_KEYS` — drop either and every panel degrades to a plain Ultra turn with no error anywhere. `cd frontend && pnpm test democracy` covers the launch spec (quorum, duplicate rejection, count clamping), the **delegation budget** (`max_total_subagents` must exceed participants x 2, or the panel is truncated mid-run and the organizer synthesizes from whoever fit), grading round-tripping through the stash with `"off"` sent as _absent_, the file carrier being one-shot and not leaking into the next panel, the rate-multiple estimate incl. unpriced models counting as zero _and being named_, and `deriveModeContext` leaving the other four modes byte-identical. `pnpm test:e2e democracy-panel` clicks the real flow: sidebar → **its own route** (asserts no `dialog` role) → cost warning visible before _Start panel_ is enabled → a complete panel with a grading scale seeds the composer and flips the thread to Democracy → **a file attached at setup arrives staged on the chat composer** → a duplicate panelist is refused. **Two asserts are the ones that are silent when broken.** First, precedence: a routing rule that wins over `model=` still produces a confident synthesized answer, it is just several "independent" opinions from one model — verify by neutralizing the `subagent_model_override = requested_model` line and watching three `TestPerCallModel` tests go red. Second, composer seeding: the task is handed to `InputBox` as `initialValue`, **never** via `setInput`, because the textarea is uncontrolled and the draft-hydration effect runs after mount and overwrites anything written during it. That bug is invisible from the same route (the launch arrives by event, after hydration) and only appears when launching from the setup page, which is now the only way in — if the e2e seeding assertions fail, check that `initialValue` is still wired through `chat-instance.tsx`. **Manual:** open the setup page with a mixed cloud+Ollama roster and confirm the local model is named in the "no price configured" line rather than silently lowering the multiple; then ask a **follow-up** in a finished panel thread and confirm the panel runs again (subagent cards reappear) instead of the organizer answering alone — that is the standing-panel guarantee, and it lives only in the prompt.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **Per-thread subagent model override** (§3, Ultra mode)                                                 | `input-box.tsx` renders the second "Subagent" `ModelSelector` only under `context.mode === "ultra"`, defaulting to "Follow lead", dimming `lacksToolSupport` models. It sets `subagent_model_name` in thread context; `_CONTEXT_CONFIGURABLE_KEYS` (`app/gateway/services.py`) forwards it; `task_tool.py` applies it as `model_override` and passes it to `SubagentExecutor`. Backend plumbing pinned by `backend/tests/test_task_tool_core_logic.py::test_task_tool_uses_subagent_model_override_for_tool_loading`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **Generate an agent from history** (§20)                                                                | `cd backend && uv run pytest tests/test_agent_generation.py tests/test_agent_generation_router.py` — the pure layer (digestion, caps, `<source>` delimiter escaping, name normalization, verdict parsing) and the route (feature switches, per-source ownership, dedupe/cap, verdicts, model selection, 502 paths, aux accounting). Wiring: `app/gateway/routers/agent_generation.py` registered in `app/gateway/app.py`; `packages/harness/deerflow/agents/generation/`; `config/agent_generation_config.py` wired into `AppConfig`; frontend `core/agent-generation/` + `components/workspace/agents/agent-generator.tsx` + the **Generate from history** button in `agent-gallery.tsx`. **Five asserts must not be 'simplified' away:** `test_analyze_never_creates_the_agent_itself` (the route stays read-only — a draft must never become an agent unattended), `test_build_system_instruction_biases_toward_no_gap` (a prompt edit must not drop the bias against proposing), `test_goal_alone_does_not_remove_the_no_gap_option` (a stated goal steers the analysis but must not decide the verdict), `test_force_proposal_rejects_a_no_gap_reply` (an override the model ignores is a failure, not an answer), and the delimiter-escaping tests (a transcript, goal, or draft containing `</source>`, `</goal>`, or `</draft>` must not break out of its block). Ownership survives both overrides — `test_revision_still_checks_source_ownership` and `test_forced_draft_still_checks_source_ownership` pin that skipping the verdict never skips the authorization. `<source>`, `<goal>`, and `<draft>` are classified in `test_input_sanitization_middleware.py::_EXEMPT_BLOCK_TAGS` with the reason — that guard will fail if a future block tag is added without a decision. Also note `backend/AGENTS.md` carries only a pointer: the depth lives in `packages/harness/deerflow/agents/generation/AGENTS.md`, registered in `test_agent_guidance_check.py`'s approved list. Frontend: `cd frontend && pnpm rstest run agent-generation` covers the selection and goal-cap helpers. Manual: enable both `agent_generation.enabled` and `agents_api.enabled`, pick two conversations, and confirm a `no_gap` verdict renders as a result rather than an error; then press **Generate anyway** and confirm the overlapping agent is still named on the draft, and that a **Refine** round keeps a hand edit you made to the SOUL.md before refining.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Editable system prompt** (§19)                                                                        | Settings → System prompt must render both tabs: **Edit** (template + one-click placeholder buttons) and **Preview** (placeholders substituted; the subagent switch changes the output). Wiring: `system-prompt-settings-page.tsx` registered in `settings-dialog.tsx` as a `dynamic()` import — `frontend/tests/unit/components/workspace/lazy-panels.test.ts` counts those imports, so adding or removing a settings page must bump that number; `core/system-prompt/{api,hooks,types}.ts`; `app/gateway/routers/system_prompt.py` registered in `app/gateway/app.py`. Backend pinned by `backend/tests/test_system_prompt_store.py` (validation, persistence, render fallback, config independence) and `backend/tests/test_system_prompt_router.py` (routes + admin gate). Run both **with `config.yaml` moved aside** — the render paths reach for it through a `None` default otherwise, which is how these first passed locally and failed CI. The full list of what a prompt change must be tested with is in §19. Manual: save an override, confirm `~/.deer-flow/SYSTEM_PROMPT.md` appears and the **next** run uses it with no restart; then hand-edit that file to `{bogus}` and confirm the run still works on the built-in prompt.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **Follow-up suggestions off by default + model picker** (§4)                                            | `core/settings/local.ts` defaults `suggestions.enabled=false`; Settings → Suggestions page writes `suggestions.{enabled,modelName}`; `input-box.tsx` gates on `suggestionsConfig?.enabled && localSettings.suggestions.enabled` and sends `n: maxFollowupSuggestions`, `model_name: suggestionsModelName ?? context.model_name`. The backend endpoint's `model_name` override is pinned by `backend/tests/test_suggestions_router.py`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **Memory toggle (off by default)**                                                                      | `core/settings/local.ts` defaults `memory.enabled=false`; Settings → Memory page writes it; `core/threads/hooks.ts` sends `memory_enabled` in run context; `agents/lead_agent/agent.py::_apply_memory_preference` consumes it (operator `memory.enabled: false` still wins). Frontend defaults pinned by `frontend/tests/unit/core/settings/local.test.ts`; the backend `_apply_memory_preference` behavior (override-false disables injection/extraction/tools; operator config still wins) by `backend/tests/test_lead_agent_memory_toggle.py`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **Camoufox default `web_fetch`**                                                                        | `config.example.yaml` web_fetch entry has `backend: camoufox`; `scripts/detect_uv_extras.py` emits `--extra camoufox` for it (pinned by `test_detect_uv_extras.py`). The dispatcher's code-level default — a `web_fetch` entry with no `backend:` key still routes to camoufox — is pinned by `backend/tests/test_web_fetch_dispatcher.py`; the browser auto-install by `backend/tests/test_ensure_camoufox.py` + `test_camoufox_fetch.py`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **SearXNG default `web_search`**                                                                        | active `web_search` tool uses `deerflow.community.searxng.tools:web_search_tool`; `scripts/detect_searxng.py` still resolves it (resolution pinned by `backend/tests/test_detect_searxng.py`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **Camoufox + SearXNG auto-update** (see _Automatic updates_)                                            | `scripts/update_camoufox_searxng.py` refreshes both; `scripts/searxng.sh` has an `update` subcommand (pull + recreate-if-running); `scripts/serve.sh` runs the updater `--if-stale 24` in the background (opt out `DEER_FLOW_AUTO_UPDATE=0`); `scripts/install_auto_update.py` + `make auto-update{,-install,-uninstall}` manage the daily `systemd --user` timer. Pinned by `backend/tests/test_update_camoufox_searxng.py`, `test_install_auto_update.py`, `test_searxng_update_script.py`. If upstream restructures `scripts/serve.sh`, re-add the throttled background `--if-stale` hook after the SearXNG block.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **PDF/Office conversion**                                                                               | `pymupdf` extra (`pymupdf4llm`) present in `backend/packages/harness/pyproject.toml`. The feature stays off by default, and the converted-Markdown companion write (distinct names for multiple convertibles, never clobbering a same-request user `.md`) is pinned by `backend/tests/test_uploads_router.py` (`test_upload_files_does_not_auto_convert_documents_by_default`, `test_upload_files_two_convertibles_get_distinct_markdown_companions`, `test_upload_files_converted_markdown_does_not_overwrite_user_markdown`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **Large documents + scanned-PDF OCR** (§25)                                                             | `cd backend && uv run pytest tests/test_context_budget.py tests/test_context_aware_tool_output.py tests/test_document_extraction.py tests/test_document_chunking.py tests/test_document_ocr.py tests/test_document_analysis.py tests/test_analyze_document_tool.py` — the asserts that are silent when broken: `test_cloud_window_keeps_every_configured_value` and `test_unknown_budget_is_a_no_op` (a configured limit is a ceiling the window may lower, never a floor it raises — break this and every existing install silently changes behaviour); `test_an_explicit_disable_is_never_turned_back_on` (`0` means no limit, in both the sandbox and `tool_output` configs); `test_the_published_budget_does_not_leak_past_the_tool_call` (the ContextVar is scoped to one tool call, so a budget cannot outlive the model that produced it); `test_summarising_happens_after_transcription_not_during_it` and `test_the_instruction_forbids_summarising` (the two passes stay separate — folding them is the cheaper implementation and the one that loses content); `test_anchors_do_not_count_towards_the_character_total` (else a 200-page blank scan reads as 4KB of content and never trips the sparse check); `test_a_fully_failed_document_is_not_cached` (caching an all-failed transcript makes the failure permanent); `test_notes_that_overflow_are_merged_in_rounds` (the reduce is hierarchical, or a long document just moves the overflow downstream); `test_the_ceiling_bounds_a_large_window` (`max_chunk_chars` reaches the chunker — it was documented and unread once, and a dead ceiling hands a 128K-window model ~55K tokens per map call); `test_context_window_mirrors_num_ctx` in `test_sync_ollama_models.py` (without it the routing guard short-circuits on `None` for every local model). Wiring: `documents:` in `config.example.yaml` (`config_version` 46) + the chart's copy; `analyze_document` registered in `tools/tools.py` behind `documents.enabled`; `_context_clamped` at the three `sandbox/tools.py` truncation sites; `_extraction_warning` in `uploads_middleware.py`. Manual: upload a scanned PDF with `uploads.auto_convert_documents: true` and confirm `<current_uploads>` flags it as image-based instead of showing an empty outline.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **Reduce animations (default on)**                                                                      | `core/appearance` (`useReducedMotion`) + `components/reduce-motion-effect.tsx`; default pinned by `local.test.ts`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **Full sandbox runs**                                                                                   | `skills/public/repo-runner/`; `sandbox.expose_ports` / `extra_capabilities` in `config.example.yaml`, honored by `LocalContainerBackend`. Container default (any Docker/Apple Container runtime, even non-interactively) + per-thread mode: `backend/tests/test_configure_script.py` + `test_docker_sandbox_mode_detection.py`; toggle: `test_sandbox_toggle.py`; forwarded `bash_command_timeout`: `test_local_sandbox_command_timeout.py`; `expose_ports`: loopback bind, and no host publish at all when the API port is unpublished (upstream's restricted-network mode) — `test_aio_sandbox_local_backend.py -k expose_ports`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **First-run config seeding**                                                                            | `scripts/serve.sh::seed_missing_config` (and the equivalents in `deploy.sh` / `docker.sh`). Pinned by `backend/tests/test_serve_config_seed.py` (seeds `config.yaml` + companion config files on first run).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **Passwordless by default** (§5)                                                                        | `scripts/serve.sh::apply_default_auth_mode` exports `DEER_FLOW_AUTH_DISABLED="${DEER_FLOW_AUTH_DISABLED:-1}"` after loading `.env` (pinned by `backend/tests/test_serve_auth_default.py`); both `.env.example` files document the `=0` opt-out. Backend honors it via `auth_disabled.py`, frontend via `core/auth/auth-disabled-user.ts` (both ignore it when `DEER_FLOW_ENV`/`ENVIRONMENT` is prod).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **Dev-origin defaults (§5, LAN/Tailscale)**                                                             | `frontend/src/dev-origins.js::getAllowedDevOrigins()` returns `DEFAULT_DEV_ORIGIN_PATTERNS` (private-LAN + Tailscale) merged with `DEER_FLOW_DEV_ALLOWED_ORIGINS`, unless `DEER_FLOW_DEV_ALLOWED_ORIGINS_STRICT`; wired in `next.config.js`. Pinned by `frontend/tests/unit/dev-origins.test.ts` (runs the defaults through Next's real `isCsrfOriginAllowed` matcher).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **Multi-user mode toggle** (§6)                                                                         | `deerflow/config/runtime_settings.py` (`is_multi_user_mode_enabled` / `set_multi_user_mode` / `resolve_owner_scope`, default ON) gates `thread_meta` `search`/`get`/`check_access` and run-store read helpers (writes keep the real owner); `GET`/`PUT /api/settings/multi-user-mode` (`app/gateway/routers/settings.py`, PUT admin-gated). Frontend toggle + confirm dialog in `account-settings-page.tsx` via `core/settings/multi-user-mode.ts`. Pinned by `backend/tests/test_multi_user_mode.py` + `frontend/tests/unit/core/settings/multi-user-mode.test.ts`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **Cost overview + aux counters** (§7)                                                                   | Shared `app/gateway/pricing.py` (console + thread endpoint import it); `GET /api/threads/{id}/token-usage` returns `total_cost`/`promo_total_cost`/`currency`/per-model `cost`/`aux`; store aggregation carries the input/output/cache-read split (`new_by_model_usage_entry`); `deerflow/runtime/aux_usage.py` records all four per-conversation sinks named in `CHAT_AUX_CATEGORIES` — memory (`agents/memory/manager.py::_host_default_extraction_callback`), suggestions and prompt polish (`utils/oneshot_llm.py::run_oneshot_llm_with_usage` from `routers/suggestions.py` and `routers/input_polish.py`), and the goal check (`runtime/goal.py::evaluate_goal_completion`) — **write-through to the durable `deerflow/runtime/aux_usage_store.py`** (`<DeerFlow home>/aux_usage.sqlite3`, kill switch `DEER_FLOW_AUX_USAGE_DB=0`). **A fifth failure mode is the quietest: a non-graph LLM call that takes a `thread_id` and is never given a category.** It does not render `—` and does not warn; the header just prints a total lower than the money spent. `input_polish` shipped that way while being `enabled: true` by default, and `goal` while firing once per turn on any thread with an active goal. If upstream (or a fork feature) adds another such call, it needs a `CHAT_AUX_CATEGORIES` entry and a `record_aux_usage_metadata` call in the same change set — pinned by `test_aux_usage_wiring.py`, whose new-sink tests are the only ones that go red when a recording call is dropped. Frontend `token-usage-indicator.tsx` + `core/threads/token-usage.ts`. Pinned by `backend/tests/test_pricing.py`, `test_model_ids.py`, `test_aux_usage.py`, `test_aux_usage_wiring.py`, `test_thread_token_usage.py`, `test_thread_cost_robustness.py`, `test_input_polish_router.py`, `tests/blocking_io/test_aux_usage.py` + `frontend/tests/unit/core/threads/token-usage.test.ts`. **`test_thread_cost_robustness.py` is the one to run for any change to pricing, the run stores, or the token-usage endpoint** — it holds the three properties that are silent when broken: spend survives a restart (the aggregation counts every status that spent tokens, via `COUNTED_RUN_STATUSES` — narrowing it back to `success`/`error` makes a restart delete money from the header while the spend cap keeps charging for it), a mid-thread model switch is priced per turn at the model that ran it, and an edited message keeps its replaced turns inside `total_cost` while excluding them from `steps[]` as `superseded_*`. **The aux registry's store is a local file, so its sync API blocks.** If upstream (or a refactor) re-points the suggestions route or the `token-usage` endpoint at `record_aux_usage` / `get_thread_aux_usage` instead of the `a*` wrappers, the strict Blockbuster anchor fails — do not "fix" it by marking the anchor `allow_blocking_io`; restore the offload. Equally, do not make the memory path async: it runs on the memory updater's loop-less debounce thread, which is the whole reason the durable store is a dedicated SQLite file rather than the async runs engine. **Three things make this render `—`, and none of them raises an error.** (1) The provider-id resolution (`pricing.py::_pricing_lookup_candidates`): buckets are keyed by the _provider-reported_ model id, not the `config.yaml` id, so exact-only matching nulls every cost — pinned by `test_thread_token_usage.py::test_thread_token_usage_prices_provider_reported_model_ids`. (2) A bundled model with no `price:` block contributes nothing, so a run on unpriced models reports no cost — pinned by `test_config_integrity.py::TestBundledModelPricing`, which fails if any bundled model loses its price or the two synced sources disagree. (3) The reported id can be _doubled_: LangChain merges a streamed response with `merge_dicts`, which concatenates equal `response_metadata` strings, and `langchain_openai` writes `model_name` on every chunk carrying a `finish_reason` — so a provider that sends more than one such chunk yields `deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro` (its `finish_reason` reads `stopstop`), which matches nothing and prices at zero. Collapsed by `deerflow/model_ids.py::normalize_reported_model_name` where a reported id is read, pinned by `test_model_ids.py` for the rule and `test_thread_token_usage.py::test_a_stream_duplicated_model_id_still_prices_and_is_named_once` end to end. A bug report quoting a nonexistent model id is this one — the unpriced note prints whatever the bucket is keyed on, so a corrupted id shows up _as_ the explanation. **The second one has a delivery trap:** fixing `config.example.yaml` does **not** fix an existing install. `sync-api-key-models.py` skips already-active provider blocks and `config_upgrade.py`'s `merge_missing` cannot add a key inside a list entry, so a config written before a price shipped keeps that model active and unpriced forever. That is why `pricing.py` still derives the price from the `($in/out)` pair in `display_name` when nothing is configured — the legacy path for every install written before §17, pinned by `test_model_price_fields.py::TestBackwardCompatibility` — and why `TestBundledModelPricing::test_every_bundled_model_is_priced` requires a `price:` block on every bundled model so a _new_ install never depends on it. **Any change to the bundled model blocks must answer: does this reach a config that already exists?** `make doctor`'s `model pricing` check is the user-facing version — it warns, with the `—` symptom named, when nothing configured can be priced. **A fourth failure is silent rather than visible:** an _expired_ promo. Since §17 a discount has one spelling — the entry's `discount:` block — so the old name/block drift is gone, but a promotion the provider has stopped still advertises a price nobody is getting until someone edits it. `TestBundledModelPricing::test_discounts_are_real_discounts_and_parse_their_expiry` pins that a bundled discount is below list and its `until:` parses (an unreadable one reads as _expired_, silently switching the discount off); `test_no_bundled_model_carries_its_price_in_the_display_name` pins that no copy comes back into a name. Neither knows whether the discount is still running: re-verify live promos as step 6 of the [model audit](#auditing-the-model-list-settings--pricing), and add an `until:` as soon as one is announced so the next expiry needs no edit. Cost is **per model everywhere**, including the promo: run buckets, and the memory/suggestions `aux` sinks, are each priced at their own model's rate, so an Ultra run with a discounted subagent and a full-price lead discounts only the subagent's tokens (`test_promo_total_is_model_aware_across_lead_subagent_and_aux`). Manual: run a turn (ideally Ultra mode, so a subagent model is involved) and confirm the header shows a **green** dollar amount; on a discounted model the dropdown shows the green promo total beside the red standard one; if it shows `—`, the dropdown now names the unpriced model. |
| **Explicit `price:` / `discount:` fields** (§17)                                                        | `cd backend && uv run pytest tests/test_model_price_fields.py tests/test_config_integrity.py tests/test_pricing.py tests/test_audit_models.py` and `cd frontend && pnpm test sorting`. Covers: the field precedence (`price:` > legacy `pricing:` > a `($in/out)` pair in `display_name`), the additive discount, every expiry rule, that **no bundled model carries a price in its name**, that the two synced sources ship the same price, and that the dropdown renders the price from the field. Wiring: `deerflow/pricing.py` (`parse_discount_expiry`, `_raw_from_price_fields`, `_resolve_discount_window`), the `price`/`discount` fields on `ModelConfig`, the **factory exclude set** in `models/factory.py`, `ModelPriceResponse` on `GET /api/models`, `wizard/providers.py::MODEL_PRICES`, and `core/models/sorting.ts` (`resolveModelPrice`, `modelNameSegments`). **Four properties must not be "fixed" into their opposites:** (1) an expired discount is dropped in `build_pricing_map`, so it never reaches a `ModelPricing` and no consumer re-checks the window — do not add a second expiry check downstream; (2) an unparseable `until` and an unavailable clock both mean _expired_, never _eternal_; (3) `price`/`discount` must stay in the factory's exclude set, because `ModelConfig` is `extra="allow"` and an unexcluded key is forwarded into the provider client and from there into the completion request payload; (4) the display-name price **parser stays**, as the legacy path — `config_upgrade.py` cannot add a key inside an existing list entry, so every install written before this change is priced by that parser and nothing else. Manual: set a `discount:` with `until:` in the past and confirm the header and the dropdown both show only the standard rate; confirm the dropdown still shows a price at all.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Model dropdown sorting/grouping** (§8)                                                                | `cd frontend && pnpm test sorting` exercises the parse/sort/group logic (`frontend/tests/unit/core/models/sorting.test.ts`). Wiring: `core/models/sorting.ts` (`parseModelPrice` promo-aware, `parseModelProvider`, `sortModels`, `groupModelsByProvider`, `demoteLast`); preference `modelPicker` in `core/settings/local.ts`; shared UI `components/workspace/model-picker-controls.tsx` (`ModelPickerControls` + `ModelPickerList` + `ModelDisplayName`) used by the lead + subagent pickers in `input-box.tsx` and the sidecar picker in `sidecar/sidecar-panel.tsx`; **`components/workspace/model-select.tsx` (`ModelSelect`) is the same picker packaged for every other site** — `democracy-setup.tsx`, `settings/suggestions-settings-page.tsx`, `settings/subagent-settings-page.tsx`, `agents/agent-generator.tsx`, `agents/agent-settings-dialog.tsx` — pinned by `frontend/tests/unit/components/workspace/model-select.dom.test.tsx` and, structurally, `model-picker-sites.test.ts`. **Tests locate a picker by its own `data-slot="model-select"`, never by `getByRole("combobox")`** — that role belongs to whichever primitive is underneath, so it vanished when the primitive was swapped and took `suggestions-settings.spec.ts` down with a 30s timeout while the product itself was fine. `model-picker-sites.test.ts` fails in milliseconds on both halves of that (a dropped `data-slot`, or any spec driving a model picker by the combobox role); i18n keys in `core/i18n/locales/{en-US,zh-CN}.ts`. **Row layout** (provider first, price pinned to the right edge, weights + window on the second line) is `modelRowParts` + `ModelPickerRow`, pinned by `sorting.test.ts` (`parseModelProviderLabel`, `formatModelSize`, `formatContextWindow`, `modelRowParts` — including the legacy name whose price group must be removed _whole_ rather than leaving `GLM-5.2 ( → )`), by `model-select.dom.test.tsx` (the provider leads the row, the price span carries `ml-auto`, a local model's `id · GiB · K ctx` line, and grouped mode dropping the per-row provider), and structurally by `model-picker-sites.test.ts`, which fails any component driving `ModelPickerList` without `ModelPickerRow`. Manual: open the model dropdown → Sort (Default/Name/Price) + direction toggle + Group-by-provider switch appear and reorder/group the list; every row's price renders green **against the right edge**, and the one discounted entry (MiniMax M3) shows its red list price beside the green promo. If a whole model name turns green or a price stays uncoloured, `modelNameSegments` has drifted from the `price:` field (or its legacy `splitModelNamePriceSegments` fallback from the name format) — the reassembly test is the fast check. Then **close** the dropdown on a discounted model and confirm the collapsed trigger still shows both prices at a narrow window width; if it clips, the `w-full` on the three `ModelSelectorName` triggers has been dropped (see §8 — without it the span is `fit-content` inside a `flex-col items-start` and overflows the capped button instead of truncating). This half is CSS with no unit test, so it needs the manual look. **Then check a screen that is not the chat** — Democracy setup, Settings → Suggestions, Settings → Subagents, the agent generator, a custom agent's dialog — and confirm each shows the same dropdown with the sort already applied. A plain grey list on any of them means a site was added (or reverted) without `ModelSelect`, which is exactly the state this feature existed to end.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **Durable chat tabs** (§9)                                                                              | `cd backend && uv run pytest tests/test_user_ui_state.py tests/test_chat_tabs_settings_router.py` covers the per-user store (`deerflow/config/user_ui_state.py`, `{base_dir}/users/{user_id}/ui_state.json`) and `GET`/`PUT /api/settings/chat-tabs` (caller-scoped, **no admin gate** — unlike the multi-user-mode routes in the same router). `frontend/tests/unit/core/threads/chat-tabs-persistence.dom.test.tsx` covers the provider's boot path. If upstream restructures `workspace/layout.tsx`'s gateway-offline branch, re-check that an unreachable gateway still **keeps** the local cache instead of blanking the strip (`fetchChatTabs` returns `null` for "unknown", never `[]`), and that a server with no stored set still adopts and seeds from the local cache — that is the upgrade path for tabs pinned before server persistence existed. Manual: pin a tab, restart the stack, hard-reload with site data cleared, and confirm the tabs come back.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **Concurrent chats** (§21)                                                                              | `cd backend && uv run pytest tests/test_concurrent_thread_runs.py` pins that two threads stream at once (the cross-thread test rendezvouses, so a process-global run lock times out instead of passing) and that two runs in one thread still serialize. `cd frontend && pnpm test run-disconnect chat-tabs-busy` covers the two frontend halves: every `thread.submit` sends `onDisconnect: "continue"` (the Gateway's default is `"cancel"`, and the SDK's own default is derived from the `streamResumable` flag `sanitizeRunStreamOptions` strips — so this must stay explicit), and `syncRoute` pins the slot it is leaving while that slot is streaming instead of dropping it (not pinned when the slot has no real thread id yet; a full strip declines). `pnpm test:e2e concurrent-chats` is the whole user story in one run: prompt chat A with its SSE response withheld, navigate to chat B, assert A became a keep-alive tab with `chat-tab-busy` visible and both `[data-slot-key]` instances mounted, send in B and get its answer while A is still unanswered, then release A and see its answer land in the background tab. Ollama half: `cd backend && uv run pytest tests/test_ollama_lifecycle.py -k "Parallel or concurrency"` — `ollama.num_parallel` parsing, CLI-over-config precedence, N slots dividing the sized `num_ctx`, slots counted in the contention warning, and the `make doctor` line.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **Keep-alive chat tabs** (§9)                                                                           | `cd frontend && pnpm test chat-tabs` exercises the pure model (`frontend/tests/unit/core/threads/chat-tabs.test.ts`); `pnpm test:e2e chat-tabs` (`frontend/tests/e2e/chat-tabs.spec.ts`) covers drag-from-sidebar onto the empty strip / drag-reorder between chips / open-as-tab / keep-alive switch (both instances stay mounted) / close / reload persistence. Wiring: the live chat is `components/workspace/chats/chat-instance.tsx` (**fully controlled**, own provider stack via `chat-providers.tsx` with a per-instance `storageScope`); `keep-alive-chat-viewport.tsx` is mounted in `workspace-content.tsx` **above** the route inside `ChatTabsProvider` and renders one instance per slot (only the active shown, the rest `display:none`); the tab strip is `chat-tabs-bar.tsx`, which **always renders as a drop zone on chat routes** (an empty-state hint `chatTabs.dropHint` when there are no tabs yet but threads exist, so there is somewhere to drag onto — returning `null` here is the "tabs don't work" bug); `[thread_id]/page.tsx` is a thin registrar in app builds and the classic inline `<ChatInstance>` in static-demo; pure model + persistence in `core/threads/chat-tabs.ts`, state in `chat-tabs-context.tsx`; sidebar drag + **Open in tab** in `recent-chat-list.tsx`; `ChatBox` panel ids keyed by thread id (not pathname). **If upstream restructures `[thread_id]/page.tsx`,** re-extract its body onto `chat-instance.tsx` and keep the registrar/classic split; watch for a barrel (`components/workspace/chats/index.ts`) import of the client viewport into the server `workspace-content.tsx` (import the file directly to keep the `"use client"` boundary). **Upstream may also extract the same body into a _new_ file rather than restructuring the route** — #4765 added `chats/chat-page.tsx`, a slot-less duplicate of `chat-instance.tsx` missing the fork's cost header. That is an _add/add_, so git reports no conflict and the duplicate silently becomes the file upstream's future chat work lands in. `chat-page.tsx` is therefore **deliberately deleted in this fork**; if a sync reintroduces it, port the delta into `chat-instance.tsx` and delete it again rather than wiring any route to it.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **Currency spend caps** (§10)                                                                           | `cd backend && uv run pytest tests/test_spend_budget_config.py tests/test_spend_budget.py tests/test_spend_budget_middleware.py` covers the config/window math, the window aggregation (runs + auxiliary counters, owner-scoped), and the in-run warn / hard stop. Wiring: `deerflow/config/spend_budget_config.py` + the `spend_budget:` block in `config.example.yaml`; `deerflow/runtime/spend_window.py`; `app/gateway/spend_budget.py`; the **HTTP 402** admission refusal and the `__spend_budget` baseline injection in `app/gateway/services.py::start_run`; `SpendBudgetMiddleware` appended in `agents/lead_agent/agent.py` after `TokenBudgetMiddleware`; `RunJournal.current_token_usage_by_model()`; `scripts/doctor.py::check_spend_budget`; the header line via `GET /api/threads/{id}/token-usage -> spend_budget` and `core/threads/token-usage.ts::threadTokenUsageToSpendBudget`. **The pricing module moved into the harness** (`deerflow/pricing.py`) because the in-graph middleware may not import `app.*`; `app/gateway/pricing.py` is a re-export shim, and `test_pricing.py::test_gateway_shim_re_exports_the_canonical_helpers` fails if it rots. **Three invariants that are easy to break and silent when broken:** (1) an unpriced model must contribute **0**, so a fully local run is never blocked — pinned by `TestLocalModelsAreFree` and `TestLocalRunsAreNeverBlocked`; (2) in-run spend must come from the journal's **per-model** accumulator, or a cheap subagent gets billed at the lead's rate and the cap fires early on exactly the setup this fork recommends (`test_a_cheap_subagent_is_billed_at_its_own_rate`); (3) with nothing priced the feature must **self-disable with a reason**, not enforce against a permanent zero (`TestSelfDisabling`). Invariant (1) has a dark mirror: a model whose _reported_ id arrived doubled (see the cost-overview row) also prices at zero, so the cap silently stops capping on exactly the provider whose stream is affected — `_message_model_name` normalizes it through `deerflow/model_ids.py`, pinned by `test_spend_budget_middleware.py::test_a_stream_duplicated_model_id_still_counts_against_the_cap`. If upstream restructures `services.py::start_run`, re-add the admission check before `create_or_reject` and the baseline injection after `inject_authenticated_user_context` — the baseline key is `__`-prefixed precisely so `build_run_config` strips a caller-supplied copy. Manual: set a tiny `daily_limit`, run a turn on a priced model (header **Budget left** goes red, the next message 402s), then repeat on a local model and confirm it is never blocked.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Automated upstream sync** (see _[Upstream sync](#upstream-sync)_)                                     | `cd backend && uv run pytest tests/test_upstream_sync.py` covers parsing this checklist out of FORK.md, the PR body for clean and conflicted merges, gate rendering (pass / fail / **skip**, which must stay distinguishable — a skipped gate reading as green is how a conflicted sync looks mergeable), the 65536-character GitHub body limit — the rendered body is ~63 KB today, so a new feature row has roughly 2 KB of room; trim an existing row before adding a long one — and workflow invariants. Wiring: `scripts/upstream_sync.py`; `.github/workflows/upstream-sync.yml` (weekly + `workflow_dispatch`). **The body is generated from this section, never copied** — a copy is correct exactly once, and every fork feature added afterwards would be missing from the list meant to prove the fork still works. So the two parsers here are load-bearing: the mechanical gates come from the `- [ ]` lines and the features from the table rows below; renaming this heading or restructuring the table silently empties the PR body (`test_the_real_fork_md_parses` is the guard). Workflow invariants pinned by tests: `git merge` and never `git rebase`, no `--force` in any form, and the PR step runs under `if: always()` so a conflicted merge still surfaces. Manual: `python3 scripts/upstream_sync.py --upstream-sha abc --commit-count 1` and read the rendered body.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Tailnet publish + origins** (see _Reaching the stack over Tailscale_)                                 | `cd backend && uv run pytest tests/test_detect_tailscale.py tests/test_docker_dev_tailnet.py`. Wiring: `scripts/detect_tailscale.py`, `scripts/tailscale_lib.sh` (sourced by **both** `scripts/docker.sh` and `scripts/deploy.sh`), `docker/docker-compose.tailscale.yaml`. **Three properties must not be "fixed" into their opposites:** `scripts/docker.sh` must keep passing an **absolute** `--env-file $PROJECT_ROOT/.env` (it `cd`s into `docker/`, so without it the root `.env` stops reaching `ports:` — silently); the overlay's `${DEER_FLOW_TAILSCALE_IPV4:?…}` must keep no default (an empty value would collapse the mapping to a `0.0.0.0` wildcard); and no launch path may run `tailscale serve` or `tailscale serve reset` (Serve config is global to the machine and may hold the user's other rules). Manual: with Tailscale up, `make docker-start` prints a `📱 Tailnet:` line and the URL answers from another tailnet device; with Tailscale down, nothing extra is published.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **Per-step cost chart** (§7)                                                                            | `cd backend && uv run pytest tests/test_thread_step_costs.py` (per-run aggregation ordering, per-model step pricing, the promo basis, memory/SQL parity) + `cd frontend && pnpm test cost-chart && pnpm test cost-per-step-chart`. Wiring: `by_run` in `aggregate_tokens_by_thread` (both stores, via `new_per_run_usage_entry`/`add_per_run_model_usage` in `runs/store/base.py`); `steps[]` on `GET /api/threads/{id}/token-usage`; `core/threads/cost-chart.ts` geometry; `components/workspace/cost-per-step-chart.tsx`. **Two properties must not be "fixed" into their opposites:** an unpriced step stays `null` (a zero draws a column on the floor that reads as "this turn was free"), and the y axis stays anchored at zero (a non-zero baseline exaggerates the gap between turns — the standard way a spend chart misleads). The last cumulative point must equal the headline total; if a change makes those two disagree, the chart is contradicting the number printed directly above it. The single exception is a thread whose turns an edit or regeneration **replaced**: those runs leave `steps[]` (they are no longer turns of the conversation) but stay in `total_cost` (the money was spent), so there the identity is _chart + `superseded_cost` = total_ and the header prints the replaced figure between the two. Putting superseded runs back into the series is the regression to watch for — it silently makes the chart show more steps than the thread has turns. Pinned by `tests/test_thread_cost_robustness.py::TestEditingAnEarlierMessage`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **Deterministic cleanup of an abandoned embedded stream** (fork patch in an upstream file) | `cd backend && uv run pytest tests/test_client_stream_cleanup.py tests/test_client_langfuse_metadata.py` — `DeerFlowClient._stream_turn` holds its `_stream_with_sandbox_lease_cleanup` wrapper in a `with closing(...)` instead of leaving it as the `for` loop's anonymous iterator. **The fix is one line wide and 120 lines tall (the loop body re-indents), so a sync will conflict here; re-apply it rather than taking upstream's side.** Left unwrapped, the wrapper is finalized by refcount during frame teardown — *after* `stream()`'s `finally` has run `reset_trace_id`, and only at GC for a caller that drops the generator without closing it. Two things ride on that timing and neither raises: the **sandbox execution lease** stays held past the end of the turn, and the agent's own cleanup logs and callbacks correlate with **no trace id**. The assertion that actually pins it is `test_closing_the_stream_releases_the_lease_inside_the_turns_trace_binding` — checking merely *that* the lease came back passes on the broken code too, because frame teardown releases it either way; only the trace id bound *at release time* separates them. Upstream carries the trace half as `test_stream_abandoned_generator_cleanup_stays_inside_trace_binding`, which was red on `upstream/main` itself when this was found. **If a later sync brings an upstream fix, delete this row and the fork test with it** — do not keep two mechanisms. |
| **Model & pricing audit** (see _[Auditing the model list](#auditing-the-model-list-settings--pricing)_) | `cd backend && uv run pytest tests/test_audit_models.py` covers marker-block parsing, the wizard-bundle load, each drift kind, **new-candidate discovery** (newer than the lab's newest bundled entry, non-variant, inside the 60-day window, capped per lab), internal consistency, source parity, the report, and the CLI exit codes. Wiring: `scripts/audit_models.py`; `.github/workflows/model-audit.yml` (weekly + `workflow_dispatch`); `scripts/fixtures/model_audit_stale_catalog.json`. **The fixture is the audit's own regression test** — the workflow's first step asserts it still produces findings, because a broken audit reports "no drift" forever and every clean run afterwards is a false all-clear. Regenerate it if the bundled roster changes (the generator is described in the fixture's `_comment`). **Three properties must not be "fixed" into their opposites:** an unreachable provider yields _zero_ findings, never "every slug retired"; the job must keep exiting 0 on findings (the issue is the signal, not a red tick); and a `new_candidate` must keep expiring after 60 days, or a model the maintainer declined becomes a weekly issue that can never be closed. **The fixture deliberately covers four drift kinds, not five:** a `new_candidate` is judged against a 60-day window, so a committed fixture would stop producing one the moment its dates aged out — discovery is pinned by `TestNewCandidates` with an injected clock instead, and the fixture stays time-independent. Manual: `python3 scripts/audit_models.py --catalog scripts/fixtures/model_audit_stale_catalog.json` and confirm all four drift kinds appear with a suggested diff.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **PWA + push notifications** (§16)                                                                      | `cd backend && uv run pytest tests/test_web_push.py` plus `cd frontend && pnpm test push` cover VAPID key reuse and file mode, subscription storage (dedupe, cap, https-only), pruning a dead subscription, the run-duration threshold, and the browser-support detection. Wiring: `frontend/public/{manifest.webmanifest,sw.js,icons/}`; `metadata`/`viewport` in `src/app/layout.tsx`; `core/notification/push.ts`; `app/gateway/{web_push.py,routers/push.py,run_notifications.py}` (router registered in `app.py`, delivery composed into `deps.py::_build_run_completion_hook` **after** the scheduled-task hook); the push helpers + shared `_write_state` in `deerflow/config/user_ui_state.py`; the `webpush` extra in `packages/harness/pyproject.toml`. **Four invariants that are silent when broken:** (1) VAPID keys must be reused — regenerating invalidates every subscription with no error anywhere; (2) `vapid.json` is opened `0600`, not chmod'ed after; (3) the insecure-context branch must stay **first** in `detectPushSupport`, or a plain-HTTP LAN user is told service workers are unavailable and goes looking for a browser setting that does not exist; (4) `notify_run_completed` must never raise — it runs on the run-completion path. The service worker deliberately caches nothing; do not add asset caching without a version/cleanup strategy. Manual: open over `https://…ts.net` from a phone, install to the home screen, enable background notifications, send the test push, then run something long with the app closed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **Cost-aware subagent routing** (§15)                                                                   | `cd backend && uv run pytest tests/test_model_routing.py` plus `cd frontend && pnpm test lifecycle` cover requirement derivation, capability filtering, rule ordering, the precedence rule, config validation, and the card plumbing. Wiring: `deerflow/subagents/routing.py`; `deerflow/config/model_routing_config.py` + `AppConfig.model_routing`; `task_tool.py::apply_routing_policy` (called after the per-thread override is read, before the executor is built, and it also sets `model_override` so the executor's own re-resolution cannot discard the route); the `routing` key on `task_started`; `core/tasks/lifecycle.ts::normalizeRouting`. **Three invariants that are silent when broken:** (1) an explicit per-thread selection must short-circuit _before_ the policy runs — "considering" it is not the same as standing down; (2) requirement derivation must stay free of any model call, or the decision becomes non-deterministic and costs money; (3) capability filtering must stay inside the preference loop, or a cheap model with `supports_tools: false` gets routed a tool-using subtask and the turn fails. `task_tool` resolves the config defensively (an unreadable `config.yaml` means "no policy", never a failed delegation) — `test_task_tool_core_logic.py` runs without a config and will catch a regression here. Manual: configure a `needs_tools: false` rule, run an Ultra-mode turn that delegates an extraction subtask, and confirm the card shows `(via <rule>)` with the reason in its tooltip.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **Model fallback chains** (§14)                                                                         | `cd backend && uv run pytest tests/test_model_fallback.py` covers the failure/decision classification, chain resolution, the wrapper (sync + async, `bind_tools` across members), and the factory wiring. Wiring: `deerflow/models/fallback.py`; `ModelConfig.fallback` (and its entry in the factory's **exclude** set — `ModelConfig` is `extra="allow"`, so an unexcluded key is forwarded into the provider constructor and then the request payload); `deerflow/config/model_fallback_config.py` + `AppConfig.model_fallback`; `models/factory.py::_wrap_with_fallbacks`. **Four invariants that are silent when broken:** (1) unrecognized errors must keep returning `False` from `should_fall_back` — defaulting to retry doubles the cost of every bug; (2) intentional stops (interrupt, budget, guardrail, 401/403) must never fall back, or a spend cap becomes a spend multiplier; (3) chain members must keep being built with `_is_fallback_member=True`, which is what makes cycles inexpressible rather than merely unlikely; (4) the wrapper must return the serving model's result untouched, or `token_usage_by_model` bills a cloud fallback at the local model's rate of zero. Manual: point a local model's `fallback:` at a cloud model, stop the Ollama daemon mid-session, and confirm the turn completes on the fallback and the header attributes its cost to the cloud model.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **Backup / restore** (§13)                                                                              | `cd backend && uv run pytest tests/test_backup.py` covers what goes in, the secrets exclusion and the owner-only opt-in archive, the postgres dump abort, the running-stack refusal, archive-path safety, and the mode-preserving round trip. Wiring: `scripts/backup.py`; `backup` / `restore` targets in the root `Makefile`; `/backups/` in `.gitignore`. **Three invariants that are silent when broken:** (1) credentials stay excluded by default — if `SECRET_PATTERNS` stops matching `users/*/integrations/` or `.env`, every backup starts shipping API keys; (2) the archive is opened `0600` via `os.open`, not chmod'ed afterwards, or it is briefly world-readable while being written; (3) extraction must keep `filter="tar"` — the `data` filter strips the permission bits this feature exists to preserve, so `0700` credential dirs would come back `0755`. A failed `pg_dump` must keep aborting: a backup with no database in it fails at restore time, when it is too late. Manual: `make backup`, `python3 scripts/backup.py inspect <archive>`, then restore into an empty directory and confirm threads/memory/tabs are there.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **Deployment exposure check** (§12)                                                                     | `cd backend && uv run pytest tests/test_exposure.py` covers the bind classification, the fact resolution (`.env` vs. process env precedence, `runtime_settings.json`, sandbox mode), every tier, and the doctor rows. Wiring: `scripts/exposure.py`; `scripts/doctor.py::check_deployment_exposure` in the new **Deployment** section; the `--surface docker` call at the end of `scripts/deploy.sh` and `--surface local` at the end of `scripts/serve.sh`. **Two things are easy to break silently:** (1) the local surface must stay pinned to the wildcard — it reads `docker/nginx/nginx.local.conf`'s address-less `listen 2026;`, so if upstream gives that config an explicit address, update `LOCAL_BIND_SOURCE`/`resolve_facts` or the check will report a bind the stack does not use; (2) `classify_bind_host` must test the Tailscale ranges **before** `is_private`, because Python classifies CGNAT (100.64.0.0/10) as private and the two tiers are deliberately different. The check must never return `fail` — a deliberately exposed home lab is not a broken install. Manual: `python3 scripts/exposure.py --surface docker`, then set `BIND_HOST=0.0.0.0` in `.env` and confirm the tier moves to `open-network` and names each contributing setting.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **Spend history page** (§11)                                                                            | `cd backend && uv run pytest tests/test_console_router.py -k ConsoleSpend` covers `GET /api/console/spend`: the three groupings (model / thread / feature) agreeing with the total, unpriced models named and sorted last, the window boundary, the no-pricing state, and the 503 on the memory backend. Wiring: `ConsoleSpendResponse` in `app/gateway/routers/console.py`; `AuxUsageStore.aggregate()`; `frontend/src/core/spend/*`; `frontend/src/app/workspace/spend/page.tsx`; the sidebar entry in `components/workspace/workspace-nav-chat-list.tsx`; i18n `spend.*` in both locales. The page must keep reusing `pricing.py` rather than recomputing cost — a second formula is how the page and the chat header start disagreeing about the same run. Manual: open **Spend** in the sidebar and confirm the tables' totals match the summary tile for the same window.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **Gaslight mode — edit into a hidden version** (§18)                                                    | `cd backend && uv run pytest tests/test_threads_router.py -k answer` covers the answer half end to end: the branch rewrites only the edited assistant message, the run-event seed carries the replacement (the feed reads events, not the checkpoint), a branch without the pair is byte-unchanged, and every half-specified or out-of-turn rewrite is refused. `cd frontend && pnpm test edit-version-answer && pnpm test edit-versions && pnpm test pending-edit-send && pnpm test "core/messages/utils"` covers the version model (group keying on the base message id, lineage resolution, a descendant inheriting its ancestor's position, the malformed-entry guards), the session-storage hand-off (read consumes it, so an edit is never replayed twice), and the per-turn edit anchors. `pnpm test:e2e edit-message-versions` drives the whole flow: edit a middle turn, land on the version with the earlier history and without the replaced answer, one sidebar entry pointing at the version, `2/2` on the edited message, switch back to `1/2`. Wiring: `core/threads/edit-versions.ts` (model + metadata keys); `core/threads/pending-edit-send.ts`; `useCreateEditVersion` / `useSetActiveEditVersion` in `core/threads/hooks.ts`; `createThread` in `core/threads/api.ts`; `components/workspace/chats/use-edit-versions.ts`; `components/workspace/messages/message-version-switcher.tsx`; the `onEditMessage` / `editVersionSwitchers` props on `MessageList`; the `deerflow_edit_version` filter in `core/threads/thread-search-query.ts`; the active-version hop in `pathOfThread` (`core/threads/utils.ts`). **Five things are silent when broken:** (0a) an **answer** edit must not park a pending send — the branch already carries the rewritten answer, so parking one replays the assistant's words back as the user's next message; (0b) answer groups must stay namespaced (`answer:<id>`) — editing the answer of turn _k_ and the prompt of turn _k+1_ branch from the same message, so a shared key renders both sets of versions on both messages; (1) groups must stay keyed on the **base message id** — keying on the turn index merges lineages that only share an ordinal; (2) `pathOfThread` must keep honouring `deerflow_edit_active_version`, or the one sidebar entry reopens version 1 forever and the edit reads as lost; (3) `takePendingEditSend` must keep _removing_ on read — a non-consuming read replays the edited turn on every remount. If upstream restores a Branch button on the assistant action row, decide deliberately: this fork removed it on purpose, and two buttons that both fork the conversation is the confusing state the feature replaced. Manual: edit the first message of a chat (the no-branch path) and confirm the switcher appears, then reload from the sidebar and confirm you land back on the edited version.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **Local image generation** (§23)                                                                        | `cd backend && uv run pytest tests/test_comfyui_tools.py tests/test_detect_comfyui.py` covers the template contract (typed parameters only, an unbound parameter refused rather than ignored, no path traversal in a template name, and a patched graph that cannot leak back into the cached template), validation against `/object_info` naming the node that moved _before_ anything is submitted, checkpoint resolution from the loader node's own enum (request → config → first installed) and the "not installed" message that lists what is, the SSRF guard being **used** with its documented `allow_private_addresses` opt-out rather than bypassed, the submit → poll → fetch loop against a mock transport including its wall-clock timeout, and the detector reusing an already-running ComfyUI instead of starting a second one. **Silent when broken:** the saved `<name>.workflow.json` must equal the graph that actually ran and must not carry binding metadata (otherwise "reproducible by hand" quietly stops being true); the reported seed must be the seed that reached the graph (otherwise every iteration is a fresh random draw and critique is noise); the active tool entries in `config.example.yaml` and the launch-time provisioning are **one decision** and must move together (§26 — the detector reads that file to decide whether to bother, so commenting the entries out switches the whole feature off, and active entries with nothing provisioning them fail at chat time on a fresh machine); and the compose port must stay loopback-bound — the ComfyUI API has no authentication and can read and write host files. Manual: `make dev` on a GPU machine with no ComfyUI running, confirm the bundled container comes up on its own, ask for a picture, confirm the PNG opens in the artifact panel and that the sidecar workflow file loads in ComfyUI and reproduces it.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **GPU residency arbiter** (§23)                                                                         | `cd backend && uv run pytest tests/test_gpu_arbiter.py` plus `tests/test_doctor.py -k Media`. Covers the computed policy (a small card resolves to `exclusive`, a bigger one to `shared` **on its own**, an unknown estimate or unknown budget falls back to exclusive and names why), eviction on acquire _and_ self-eviction on release, residency re-read from the services on every acquire, the `nvidia-smi` tiebreak that evicts when VRAM is held while no tenant claims it, serialization of two concurrent generations, the honest timeout instead of an unbounded queue, and the doctor row for VRAM held while idle. **Silent when broken:** Ollama's unload must stay a **per-request** `keep_alive: 0` — writing it globally reintroduces the subagent cold starts `ollama.keep_alive` exists to prevent; a cloud tenant must remain not-resident rather than gaining a branch of its own; and dropping the release-time self-eviction leaves the diffusion weights on the card, which does not fail, it just makes the next chat turn several times slower. Manual: with a local lead configured, generate twice in a row and confirm `nvidia-smi` shows an empty card between generations.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **Refine loop and local video** (§23)                                                                   | `cd backend && uv run pytest tests/test_refine_session.py tests/test_comfyui_video.py` covers the frozen rubric (3–6 checkable criteria, a verdict that may not judge anything outside them, every criterion judged each round), the **server-held** counter and wall-clock budget refusing iteration N+1 with a reportable message — asserted at the tool boundary, not just in the model layer — the one-named-change rule on a retry, the session JSON audit trail, evenly spaced still selection with both endpoints included, the contact sheet, and the video tool's own timeout. **Silent when broken:** the video budget must stay a separate config value (sharing the image timeout abandons working clips; inheriting `sandbox.bash_command_timeout` abandons them sooner); a contact-sheet failure must never lose the clip that took minutes to render; and the skill's instruction text is asserted too — the seed discipline, "only view the newest result each round", the `view_image` vision constraint, and the refusal to open a second session to get around the cap are load-bearing sentences, not prose. Manual: ask for a deliberately vague image and confirm it converges within the cap; ask for an impossible one and confirm it abandons instead of spinning.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **ComfyUI on by default, models, and the generation button** (§26)                                      | `cd backend && uv run pytest tests/test_detect_comfyui.py tests/test_comfyui_models.py tests/test_comfyui_tools.py tests/test_doctor.py -k "Media or comfyui or Autostart or CLI"` plus `python3 scripts/pnpm.py rstest run image-generation`. Covers the provisioning gate (Docker **and** a GPU start it; no GPU holds and names the override; no Docker holds even when forced; `DEER_FLOW_COMFYUI_AUTOSTART=0` is honoured on a machine that could run it; a detector that raises is "no GPU" rather than a crash), the exact CLI words the launch scripts branch on (`bundled start` / `bundled hold` / `external <url>`), the models-directory resolution for both integrations (bundled bind mount, `DEER_FLOW_COMFYUI_EXTERNAL_MODELS`, the host side of a container's own `…/models` mount, well-known paths, and the **refusal** when none of them answers), the install contract (no partial file survives a failed download or a checksum mismatch, an existing model is not silently replaced, a name that is a path is refused), and the button's handoff (stash consumed exactly once, malformed stash discarded, the seeded text carrying the pixel size and the fallback sentence, the prompt mode reaching the seed as either a verbatim-prompt instruction or a write-both-halves brief, the negative prompt dropped for a checkpoint that samples at CFG 1, and an entered resolution snapped to the latent grid, capped per kind and refused rather than replaced when it is cleared). **Silent when broken:** the active tool entries and the launch-time provisioning must move together — the detector reads `config.yaml` to decide whether to bother, so commenting the entries out switches the feature off and active entries with nothing provisioning them fail at chat time; the tools must stay **bound** on a machine with no ComfyUI (that is what makes the agent fall back to the cloud skill instead of insisting), and `make doctor` must **skip** rather than warn there; the bundled container must stay out of the main compose project, or `up --remove-orphans` deletes it during an unrelated restart; `comfyui_models.py` must never fall back to the bundled directory for an external instance — that download succeeds and the model never loads; a `direct` prompt must reach the seed **verbatim** rather than paraphrased (a seed that describes it invites exactly the rewrite the mode exists to forbid); and the size the preview states must be the snapped size that runs, or the resolution field is only a suggestion. Manual: `make comfy-models` against a running instance, `make comfy-model-add SOURCE=<url> TYPE=checkpoints`, then the sidebar's third entry → a prompt → confirm the composer is seeded (not sent) and the run produces a PNG.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **Internet switch on the conversation** (§27)                                                           | `cd backend && uv run pytest tests/test_internet_toggle.py` plus `python3 scripts/pnpm.py rstest run internet-toggle`. The asserts that are silent when broken: **absent is not off** (only an explicit `False` opts out, so IM/TUI/scheduler callers keep their tools), the group classification is an **allowlist** (an unclassified group is dropped — a blocklist of `web`/`browser` passes everything else and ships the next provider group), **MCP and ACP tools go too**, a **subagent inherits** the switch from the parent run context, and the offline notice is appended to the _rendered_ prompt rather than a template placeholder an operator's saved `SYSTEM_PROMPT.md` would not have. UI wiring: `pnpm test:e2e internet-toggle` drives the composer control by its own `data-slot="internet-toggle"` — and because the composer is shared, a change to it means the **whole** `pnpm test:e2e`, not that one spec.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **Tiered voice input** (§24)                                                                            | `cd backend && uv run pytest tests/test_voice_stt.py` plus `python3 scripts/pnpm.py rstest run voice-input`. The asserts that are silent when broken: `voice.allow_cloud_fallback` and `voice.stt.enabled` both default **false** and `resolveVoiceInputTier` returns `null` rather than `"cloud"` when neither local tier is available; `DEFAULT_VOICE_SERVER_CONFIG` keeps cloud off when `/api/voice/config` errors or is unreachable (fail closed, not open); `is_local_endpoint` treats Tailscale CGNAT `100.64.0.0/10` as local, so a tailnet STT service is not mislabelled as off-machine; the upload size cap refuses **before** the STT service is called; error text never echoes the service body (a transcript is speech); and `recorder.test.ts` proves the microphone track is stopped on all four exits — success, recorder error, failed construction, and abandonment. A regression in the first two reads as "voice still works" while audio goes back to the vendor.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

**Integration points that tend to need a hand** (where upstream refactors collide with fork additions — check these first when tests fail): the AIO sandbox provider (upstream's cross-instance ownership store adds instance attributes that minimal test fixtures built via `__new__` must seed), the skills tool-policy path (upstream's dynamic `SkillToolPolicyMiddleware` vs. any fork static filtering — reconcile onto the middleware and drop dead build-time filters), `scripts/check.py`'s Docker diagnostics (any upstream test that mocks `run_command` with a strict dict must tolerate the extra `docker` calls), and the `task_tool.py` / `input-box.tsx` model-override plumbing.

For environments that cannot reach `github.com/bytedance/deer-flow` directly (e.g. network-restricted CI or sandboxed agents), the **Mirror Upstream** workflow (`.github/workflows/mirror-upstream.yml`, manual `workflow_dispatch`) fetches upstream `main` on a GitHub runner and publishes the delta as a git bundle on the `upstream-sync-data` branch of this fork. Fetch that branch, extract the bundle parts (`cat upstream-delta.bundle.part.* > upstream.bundle`), and `git fetch <bundle> upstream-main-mirror` to get full upstream history locally. (The workflow cannot push the mirrored branch directly: `GITHUB_TOKEN` is not allowed to create or update workflow files, and upstream regularly changes theirs.)

## The model bundle and its audit

**The shape the bundle must keep: every big name is reachable two ways.** That
is the whole design, and the audit below exists to keep both halves true.

- **Through OpenRouter, on a single key.** Each lab's critically acclaimed
  flagship carries an OpenRouter entry — Claude Fable 5.1, Grok, GPT-5.6 Sol,
  Gemini, Kimi K3, DeepSeek, Qwen, MiniMax, Mistral Large, GLM, Llama, Nemotron
  — so a user holding nothing but an `OPENROUTER_API_KEY` still reaches all of
  them.
- **Through each lab's own API, with a fuller lineup.** That same flagship
  appears again in the lab's **home block**, this time beside its siblings:
  `ANTHROPIC_API_KEY` brings Fable 5.1, Opus 5, Opus 4.8, Sonnet 5, Sonnet 4.6 and
  Haiku 4.5, and `OPENAI_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`,
  `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `MOONSHOT_API_KEY`, `MISTRAL_API_KEY`,
  `MINIMAX_API_KEY` and `ZAI_API_KEY` do the same for their families. Holding a
  lab's own key is what buys the depth; the routed flagship covers everyone else.

**`config.yaml` is generated from whichever keys are in `.env`.**
`scripts/sync-api-key-models.py` runs on every launch path, reads the
environment, and uncomments exactly the `auto-model-config` marker blocks whose
key is present — one key produces one block, eight keys produce eight, and
neither case needs a hand edit. That is why a home block trimmed to a lone
flagship, or a home flagship with no OpenRouter twin, is a **finding** rather
than a matter of taste: it silently narrows what a given `.env` can produce.
`TestFirstPartyKeyCoverage` in `backend/tests/test_sync_api_key_models.py` pins
the machine-readable half of the rule; the prose copies it cannot read are step 3
of the audit.

**The bundled model list is a living list — keep it current.** Providers ship, rename, retire, and re-price models faster than upstream DeerFlow moves, so treat the roster as something to revisit periodically, not a one-time setup. Three things stay honest on each pass — _which_ models are bundled, their _format/settings_, and their _pricing_ — and each has its own criteria below, gathered into a single periodic checklist in _Auditing the model list_.

### Which models to keep in the bundle

The shipped set is deliberately a curated "big names" list, not a catalog dump. When refreshing it, keep to this exact shape:

- **Anthropic (direct key) — the Claude lineup, by family generation:**
  - **Opus** and **Sonnet** each keep their **last 4.x _and_ the current 5** — i.e. Opus 4.8 + Opus 5, Sonnet 4.6 + Sonnet 5. These are the tiers people pin threads to, so the outgoing 4.x stays alongside its 5 successor rather than being dropped the day 5 ships.
  - **Haiku** and **Fable** keep **only the latest** — Haiku 4.5, Fable 5. The small/cheap tier and the top "most capable" tier each only need their current model; nobody pins an old Haiku or an old Fable.
  - When a new generation ships (say Opus 6), the rule rolls forward mechanically: the new model joins, the now-second-newest Opus stays as the "last 4.x-equivalent" pin, and the third-oldest drops.
- **Fable also via OpenRouter.** Fable 5.1 is the one Claude that also gets an OpenRouter entry, for users who only hold an `OPENROUTER_API_KEY` and still want the flagship. Every **other** Claude lives **only** on the direct Anthropic block — routing an already-direct Claude through OpenRouter just adds the `(p)` privacy caveat and a middleman for no benefit.
- **First-party "home" block per big-name lab.** Every lab that ships its own API gets a direct block, gated by that lab's own key, carrying that lab's lineup on its native/OpenAI-compatible endpoint — the same shape as the Anthropic block above. Currently: **OpenAI** (`OPENAI_API_KEY`), **xAI** (`XAI_API_KEY`), **Google** (`GEMINI_API_KEY`, native SDK), **DeepSeek** (`DEEPSEEK_API_KEY`), **Mistral** (`MISTRAL_API_KEY`), **Moonshot** (`MOONSHOT_API_KEY`), **Qwen/Alibaba** (`DASHSCOPE_API_KEY`), **MiniMax** (`MINIMAX_API_KEY`), **Zhipu/z.ai** (`ZAI_API_KEY`). Two open-weight labs are deliberately **OpenRouter-only** — **Meta Llama** and **NVIDIA Nemotron** have no clean first-party consumer chat API, so they keep just their routed flagship. Each home block carries the flagship (**doubled** with the OpenRouter entry) **plus a small fuller family** — the same "a lab's direct key deserves its real lineup" logic that gives the Anthropic block six Claudes. Keep the home families tight (flagship + 1–2 acclaimed/cheaper siblings, like OpenAI's Sol + Codex + Mini); the trim-aggressively rule below still applies. Home entries carry the lab's own name suffix (`(OpenAI)`, `(xAI)`, …), **never** `(p)` (they're direct), and use the lab's own list price (no OpenRouter promo star).
- **OpenRouter — the "big names," one main model each.** One flagship entry per major lab: **xAI** (Grok), **OpenAI/ChatGPT** (GPT), **Google** (Gemini), **DeepSeek**, **Moonshot/Kimi**, **Qwen**, **Mistral**, plus the other strong open models that make sense (**Zhipu/GLM**, **MiniMax**, Meta **Llama**, NVIDIA **Nemotron**). **Mostly just the main model per lab** — add a _second, smaller_ model only when that smaller one is itself **critically acclaimed** in its own right (the shipped example is OpenAI: GPT-5.6 Sol as the flagship **and** GPT-5.3 Codex, the widely-praised agentic-coding variant). Don't list every size a lab offers. This trim set is kept **as-is** even though the labs now also have home blocks — the doubled flagship is the point, and the Sol + Codex double stays.
- **A previous generation stays only where people are still choosing it.** The Anthropic rule above — Opus and Sonnet keep the outgoing 4.x beside the current 5 — is a shape, not an Anthropic privilege. Any lab's previous flagship earns the same second slot when it is _independently_ still in demand: the acclaim signal below, showing the old version holding its own share after the successor shipped. Absent that evidence the default is the mechanical roll-forward (new flagship in, previous one out), which is what happened to Grok 4.5, Qwen3.7 Max and GLM-5.2. Two generations of one tier is the ceiling; a third is never kept, and the cheap/small tiers (Haiku, Fable, the Flash/Lite/Mini picks) keep only their latest either way — nobody pins an old one.
- **Cost spread.** Keep at least one genuinely cheap option live (Haiku, Gemini Flash, GLM/MiniMax) so the mixed-model cost story in this doc holds in practice.

#### What "critically acclaimed" means here, and where to read it

The phrase decides two things above — whether a **second, smaller sibling** joins its flagship, and whether a **previous generation** keeps its slot — so it needs a source rather than a feeling. Everything else in this section is verified against a page; this was the one criterion that wasn't, which is how it came to mean "the agent had heard of it".

**The signal is OpenRouter's own popularity surfaces**: the rankings and trending boards, the weekly token-share movers, and whatever "new & noteworthy" shelf the site is currently running. A model climbing those was chosen by people _after_ trying it, on the same marketplace the bundle already treats as authoritative for routed prices — which is the closest thing to acclaim that can be read off a page and dated. Read it the way a price is read (_Where a price may come from_): name the surface and the date in [the audit log](docs/model-audit-log.md), so the next pass can tell a model that is still rising from one that had a good week eighteen months ago.

Two things that look like acclaim and aren't: a **launch post** (the lab wrote it) and a **benchmark table** (the lab chose the benchmarks). Sustained third-party usage is the evidence; the rest is the announcement.

**A rising star is a pointer, not an entry.** `ox-alpha` is the shape worth remembering: a cloaked model appears on OpenRouter under a codename, tops the trending board for a week or two, and then turns out to be some lab's next flagship wearing a mask. The codename is an alias by another route, so bundling one breaks the same rule as `*-latest` — it moves while the entry's name and `price:` stay where a human left them, and at unmasking it stops resolving at all. So **note it and wait**: when the model is named and priced under its real slug, bundle _that_, and the trending run is the evidence that earned it the entry.

Rule of thumb: the full Opus/Sonnet-4.x-plus-5 Claude set on the Anthropic key; a tight first-party home block (flagship + 1–2 siblings) for every lab that has its own API; Fable and each lab's flagship also on OpenRouter; one recognizable flagship per big-name lab on OpenRouter (a second only if the smaller model is acclaimed on its own); and nothing that isn't a flagship or a deliberate budget pick. Trim aggressively — a long list dilutes the picker and the auto-config.

### Keep the model format current, and free of deprecated fields

Provider APIs change model IDs and request-shape rules faster than upstream DeerFlow does, so a refresh must re-validate the _format_, not just swap names. Before committing a model-block change:

- **Model IDs / slugs** — confirm each `model:` is the exact current id (Anthropic bare ids like `claude-opus-5`; OpenRouter `provider/model` slugs). A wrong or unreleased id fails at request time, not at load. When unsure of a live slug, verify against the provider's / OpenRouter's catalog rather than guessing.
- **Thinking config matches the model family** — the adaptive Claude models (Fable 5.1, Opus 5, Opus 4.8, Sonnet 5, Sonnet 4.6) reject the old `thinking: {type: enabled, budget_tokens: N}` form with a 400; use `type: adaptive`. Only pre-adaptive models (Haiku 4.5 and older) still take `budget_tokens` (min 1024, `< max_tokens`). Fable 5.1 additionally rejects `type: disabled`, so its disabled state must stay on adaptive. Sampling params (`temperature`/`top_p`/`top_k`) are rejected on the newest Claude models — don't add them to those entries.
- **No deprecated fields** — drop anything the provider has removed (e.g. `budget_tokens` on adaptive models, `output_format` in favour of `output_config.format`, retired tool-version strings). If a `supports_*` flag no longer maps to a real capability, remove it.
- **`supports_thinking: true` is load-bearing** — without it DeerFlow silently runs the model in non-thinking mode even with the UI toggle on.
- **Pricing uses one currency** — the console cost display sums across models, so every priced entry must share a currency; mixed currencies disable the feature. Write the price as `price:` (`input` / `output`, optional `cache_hit`, optional `currency`) with an optional `discount:` beside it (§17); the older `pricing:` block (`input_per_million` / `output_per_million` / `input_cache_hit_per_million`) is still read for configs written before that. Prices are per 1M tokens either way. `TestBundledModelPricing::test_price_blocks_are_well_formed_and_single_currency` pins the rule across the whole bundle.
- **Regression-test the change** — `python3 scripts/sync-api-key-models.py --dry-run` must still uncomment the block cleanly, and `cd backend && uv run pytest tests/test_sync_api_key_models.py tests/test_config_integrity.py` must stay green.

### The legacy `pricing:` block — the pre-§17 spelling, still read

**A new entry takes `price:` / `discount:` (§17), not this block.** What follows is the older spelling — a `pricing:` block on the model entry — which the loader still reads so every `config.yaml` written before §17 keeps pricing itself, and which every rule in this subsection describes. An explicit `price:` wins wherever both are present, and no bundled entry ships a `pricing:` block any more. Read this when you meet one in an existing config; do not write a new one:

```yaml
models:
  - name: Claude Opus 4.8 ($5/25) (Anthropic)
    use: langchain_anthropic:ChatAnthropic
    model: claude-opus-4-8
    max_tokens: 8192
    supports_thinking: true
    # ...other per-model settings...
    pricing: # optional; powers the console real-cost display
      currency: USD # ISO code (USD, CNY, ...); see the one-currency rule below
      input_per_million: 5.0 # price per 1M input tokens (cache MISS)
      output_per_million: 25.0 # price per 1M output tokens
      input_cache_hit_per_million: 0.5 # optional; prompt-cache reads ≈ 0.1x input
      promo_input_per_million: 2.5 # optional; a live discount — see below
      promo_output_per_million: 12.5
      promo_input_cache_hit_per_million: 0.25
```

The logic that block feeds, and the rules for writing it:

- **Prices are per 1,000,000 tokens**, in the stated `currency`. `input_per_million` is the cache-_miss_ input price; `output_per_million` is the output price.
- **`promo_*_per_million` is an optional live discount, and it is strictly additive.** When a provider is currently discounting a model (an OpenRouter promotion, an Anthropic introductory window — see _Display-name conventions_ below), the promo rate goes here **beside** the standard one, never instead of it. Cost is still **billed at the standard rate**, because a promo can end at any time and a silently-too-low estimate is worse than a slightly-high one; the promo exists so the chat header can show what the conversation costs _today_ (green) next to what it costs once the discount lapses (red). Both directions are required — a half-specified promo, a non-positive one, or one **above** the list price is a config error and the loader drops the whole promo with a warning rather than honouring part of it. `promo_input_cache_hit_per_million` follows the same optional/fallback rule as its standard counterpart.
- **`input_cache_hit_per_million` is optional.** Prompt-cache-hit input tokens are billed at this rate; **omit it and cache hits fall back to the miss price** (`input_per_million`) — a deliberate conservative upper bound. For Anthropic, cache reads run ≈ 0.1× the input price, so `input/10` is the right figure. The console is cache-aware: it reads each run's `token_usage_by_model` input/output split plus accumulated `cache_read` tokens and prices them separately.
- **One currency across every priced model.** The console sums cost across models, so a mix of currencies is meaningless — if two priced models declare different `currency` values, cost reporting is **disabled entirely** (the cost/currency fields go null) rather than producing an invalid total. Pick one currency and price every `pricing:` block in it.
- **The display-name parser is the legacy path, and it must stay.** Every _bundled_ model now ships a structured `price:` block and no price in its name (§17), but a `config.yaml` written before that change carries the old `($<in>/<out>)` names and nothing else — so when a model entry has neither `price:` nor a `pricing:` block, `app/gateway/pricing.py::derive_pricing_from_display_name` still reads that pair (and any starred promo) straight out of `display_name`. **This is what makes the feature work on an existing install, and it is not a convenience.** Shipping blocks in `config.example.yaml` only ever reaches a _brand-new_ `config.yaml`: `sync-api-key-models.py` skips a provider block whose models are already active (correct — it must not duplicate them) and `config_upgrade.py`'s `merge_missing` is dict-based, so it cannot add a key inside an existing list entry. Anyone who ran DeerFlow before a price shipped therefore keeps that model active and **unpriced forever**, and their chat header stays on `—` no matter how many times the example is corrected. Reproduced end to end: an upgraded config with 13 active models and 0 `pricing:` blocks produced `no changes` from both launch-path regenerators. An explicit block always wins over the derived one, and a malformed explicit block is _not_ silently replaced by the name's price — that is an operator error worth surfacing. Pinned by `test_model_price_fields.py::TestBackwardCompatibility` (`test_display_name_derivation_still_works`, `test_a_legacy_pricing_block_still_prices`) and `TestExplicitPriceField::test_price_wins_over_the_display_name` — deleting the parser to "simplify" the pricing loader silently un-prices every install written before §17.
- **Pricing is optional and additive.** A model with no `pricing:` block yields `cost: null` (it just doesn't contribute to the total); when _no_ model is priced, the console omits cost columns. `ModelConfig` is `extra="allow"`, so adding the block needs no schema change.
- **What ships priced: everything.** All **41** bundled paid models across all eleven marker blocks carry a `price:` block, in both synced sources. This is load-bearing, not a nicety — a model without one contributes nothing to the total, so a conversation run entirely on unpriced models reports **no cost at all**. Shipping only the Anthropic block priced is exactly what made the chat header render `—` for anyone using another provider. Only Ollama (populated at runtime, genuinely free) stays unpriced. The price is **data, in one place**: `config.example.yaml` carries the block literally and `scripts/wizard/providers.py::MODEL_PRICES` holds the same figures for the wizard, with `test_config_integrity.py::TestBundledModelPricing::test_the_wizard_bundles_and_the_example_agree` asserting the two agree. It is deliberately **not** derived from the display name any more — see §17. `cache_hit` is set only on the Anthropic entries (0.1x input, their published cache-read rate); other providers differ or do not publish one, so their blocks omit it and cache hits fall back to the full input price, the documented conservative upper bound. Exactly one entry is currently discounted — **MiniMax M3 on OpenRouter** — and it alone carries a `discount:` block; that promotion is open-ended, so it has no `until:`. Claude Sonnet 5 used to be the second: it launched on a `$2/10` introductory rate against a `$3/15` list, and on 2026-08-10 Anthropic made that rate **permanent** (the scheduled 2026-09-01 increase will not happen), so the discount was removed and `$2/10` is now its plain standard price — the intro window ending _upward_ into a list price is the case the mechanism was built for, and it ending _downward_ into the list price is the case it also has to survive. GLM-5.2's 76%-off promotion left with the entry when the roster rolled forward to GLM-5.3 — a discount belongs to the model it was quoted for, so it is not carried across a version bump. Pinned by `backend/tests/test_config_integrity.py::TestBundledModelPricing` (every model priced, no price in any name, well-formed, single-currency, discounts below list with a readable expiry, and the two sources agree).
- **Keep it current with the roster.** The `pricing:` block is part of the same living bundle as the model list — refresh it on the same cadence as slugs and thinking config (see _Auditing the model list_ below), reading each figure off the provider's own model page — or, when that page is unreachable, off several independent sources that agree (_Where a price may come from_) — never from memory.

### Display-name conventions (label, source suffix, privacy marker)

Bundled `display_name`s are labels: the model, its source suffix — `(Anthropic)` for the direct Anthropic API or `(OpenRouter)` for OpenRouter-routed models — and any trailing `(p)` marker. E.g. `Kimi K3 (OpenRouter) (p)`, `Claude Sonnet 4.6 (Anthropic)`. The price is **not** in the name; it lives in the model's `price:` block (§17), and the model dropdown renders it from there, so the figure in the picker is the same one the cost overview bills against rather than a second copy that can drift.

A **discount** is not in the name either — it is the entry's own `discount:` block (§17), and the dropdown and the chat header render the pair from there (list red, promo green). Two sources of discount qualify, and both are written the same way:

- **OpenRouter promotions.** As of 2026-08: **MiniMax M3** (`$0.6/2.4` list, `$0.24/0.96` discounted, 60% off — the one bundled entry currently carrying a `discount:`, and open-ended, so it has no `until:`). (**GLM-5.2** ran 76% off until the roster rolled forward to GLM-5.3; its discount was dropped with the entry rather than carried over.) Derive the list price from the promo page's discounted figure and its stated discount (`list = discounted / (1 − discount)`), so both numbers stay internally consistent.
- **Anthropic introductory pricing.** A newly launched Claude can ship at an intro rate below its standard list price for a fixed window. **Claude Sonnet 5** was the worked example: it launched at `$2/10` against a `$3/15` list, through 2026-08-31. An intro window can end in _either_ direction, and the 2026-08-25 audit caught the second: on 2026-08-10 Anthropic made the `$2/10` rate permanent and cancelled the 2026-09-01 rise, so the right edit was to delete the `discount:` block **and** lower `price:` to `$2/10` — not to let the window lapse back up to a `$3/15` nobody is charged. When an intro window simply expires, delete the `discount:` block and leave `price:` at the list rate.

  An `until:` is what lets a discount end without anyone editing anything, so add one the moment a provider announces an end date; an open-ended promotion legitimately has none. Two asserts hold this shape: `TestBundledModelPricing::test_discounts_are_real_discounts_and_parse_their_expiry` fails if a bundled discount is not below its list price, or if its `until:` cannot be parsed — an unparseable one resolves to _expired_, so it would otherwise switch the discount off in silence — and `test_no_bundled_model_carries_its_price_in_the_display_name` fails if any price, discounted or list, is put back into a name.

The privacy marker rides only on the OpenRouter entries:

- **`(p)` — privacy caveat (zero-data-retention not guaranteed).** OpenRouter routes each request to a third-party provider that may log or retain prompts, unlike the direct Anthropic entries (or local Ollama). Every OpenRouter entry carries `(p)`; the direct Anthropic bundle and Ollama models do not. It flags "don't put sensitive data through this one" at a glance — steer private work to the direct Anthropic or local models. This is a routing property, so `(p)` stays on an OpenRouter entry regardless of which underlying lab it points at (the Fable-via-OpenRouter entry carries it too).

Rules for keeping it honest:

- **A price is a rough figure, not billing truth.** Round to a clean pair; prompt-cache discounts and provider-variant routing shift the real number. There is only one copy to keep exact — the entry's `price:` block — because the model dropdown, the chat header, the spend page and the budget caps all render from it. "Rough" therefore means _choose_ a clean number once; it never means a second, approximate copy somewhere else.
- **Verify, never invent — and corroborate when you cannot verify.** When adding or re-pricing a model, read the current figure off the provider's / OpenRouter's own model page (and its promotions/discounts page for a discount). When that page cannot be reached, _Where a price may come from_ permits a figure that **several independent sources state identically**, recorded as corroborated in [the audit log](docs/model-audit-log.md) so the next pass re-checks it; a discount never qualifies. Do not carry a price from memory for a model past your knowledge cutoff — that is what neither tier allows.
- **Refresh `price:` when you re-slug or re-tier a model, and `discount:` when a promo starts or ends**, the same way you re-check the slug and thinking config above — a stale price is worse than none. When a promo ends, delete the `discount:` block; when one starts, add it, with an `until:` if the provider announced an end date. Never put either figure back into `display_name`.
- **Keep both model sources in sync.** A model's price lives in two places that must match: the `price:`/`discount:` blocks in `config.example.yaml`'s marker blocks (the auto-config path) and `scripts/wizard/providers.py::MODEL_PRICES` (`make setup`). Edit both, or a user gets a priced model on one path and an unpriced one on the other — `test_the_wizard_bundles_and_the_example_agree` fails if they diverge. The `(p)` marker lives in the same two places; keep it in sync too.

### Auditing the model list (settings + pricing)

**The trigger for this pass is the weekly audit job, not the calendar.**
`.github/workflows/model-audit.yml` runs `scripts/audit_models.py` every Monday:
it reads both synced sources and diffs them against the live OpenRouter catalog,
then opens (or updates) a single `model-audit`-labelled issue listing retired or
renamed slugs, list prices that moved, promotions that started or ended, and
**newer models from labs the bundle already carries** (`new_candidate`) — with a
suggested diff. It **never commits a price**: a price is confirmed against the
provider's own page, or — when that page cannot be reached — against several
independent sources that agree, and recorded as such (_Where a price may come
from_, below). Both are judgements a person makes and writes down; a wrong
automated price is worse than a stale one because it is wrong with confidence and
silences the next audit. An unreachable provider is reported as _skipped_, never as drift,
so the job does not become a weekly red tick people learn to ignore. The issue
closes itself when a later run comes back clean.

Two things the job checks without any network, so they hold for every provider:
that no entry has had a price put back into its `display_name` (the
`price_in_display_name` finding — a second copy of a number that is already
data, which is the drift §17 removed), and that the two synced sources still
agree with each other. Providers without a machine-readable
catalog are listed as skipped in the issue — for those, the manual steps below
are still the whole audit. Run it yourself any time with
`python3 scripts/audit_models.py`, or against the deliberately stale fixture
(`--catalog scripts/fixtures/model_audit_stale_catalog.json`) to confirm the
audit itself still detects drift.

Run this pass **when that issue reports drift, when someone asks for an audit, or when you change the bundle yourself** — and not otherwise. Inside [the change cycle](CHANGE_CYCLE.md) the rule is narrower still: step 6 runs it **only when the request asks for one in words**, and turns the other two reasons into a line in the report recommending an audit rather than a pass nobody asked for. That is deliberate — an audit run as a reflex at the end of an unrelated change is the one most likely to be hurried, and a hurried price is wrong with confidence. It is deliberately **not** a standing step of every upstream merge: models, prices and promos shift on the providers' schedule rather than upstream's, so a sync is evidence about upstream and no evidence at all about the roster. The cheap half is already automatic — the weekly job diffs the catalog for free and stays quiet when nothing moved. The expensive half is this one, a human or agent reading provider pages one at a time, and spending it on a roster nothing has happened to buys a re-derivation of the previous answer. When it is warranted it keeps the enabled models, their per-model settings, and their prices honest. Everything below lives in the **two synced sources** — the `config.example.yaml` marker blocks and `scripts/wizard/providers.py` — so apply every change to both.

1. **Roster & order.** The bundle stays grouped by provider in this order: **Anthropic** (direct) → **OpenRouter** → the **first-party "home" blocks** (OpenAI, xAI, Google, DeepSeek, Mistral, Moonshot, Qwen, MiniMax, z-ai — in `config.example.yaml`'s FIRST-PARTY HOME API BLOCKS section) → **Ollama** (populated at runtime by `scripts/sync-ollama-models.py`, so it lands after the static blocks). Keep the "one flagship per big-name lab + a couple of cheaper picks" shape from _Which models to keep in the bundle_ above, and keep each lab's flagship **doubled** (home + OpenRouter).
2. **Discovery — what belongs in the roster and isn't in it yet.** Every other step in this pass keeps the models already bundled honest; this is the only one that can **grow** the list, and it is the one the fork kept skipping. Every automated check asks about entries the config already carries, so a lab shipping a new flagship is invisible to all of them: the 2026-08-20 pass found **four** labs a generation behind at once, caught by eye rather than by any gate. Start from the **OpenRouter catalog** (`https://openrouter.ai/api/v1/models`, no key required) rather than from memory, and work three questions:
   - **A newer model from a lab already bundled.** `scripts/audit_models.py` does this half for you: it groups the catalog by lab prefix and raises a **`new_candidate`** finding for any non-variant slug whose `created` date is newer than the newest entry that lab has in the bundle (three per lab, newest first). Treat it as a prompt, never an instruction — the finding says only _this exists_; _Which models to keep in the bundle_ decides whether it belongs. A candidate is reported for **60 days** from its release and then stops (`NEW_CANDIDATE_WINDOW_DAYS`), so one you deliberately declined ages out on its own instead of becoming a weekly issue nobody can close — the same reason an open-ended discount is not a finding. Write the decline in [the audit log](docs/model-audit-log.md) so the next pass doesn't re-litigate it.
   - **A smaller sibling that has become acclaimed in its own right.** GPT-5.3 Codex beside Sol is the precedent, and the rule for judging it is _What "critically acclaimed" means here_ above: OpenRouter's own trending and ranking surfaces, named and dated in the log — not a launch post, not a benchmark table.
   - **A lab that isn't in the bundle at all.** A name you don't carry sitting near the top of those same surfaces is the trigger for a new OpenRouter entry; if that lab also ships a public consumer API, it earns a **home block**, which is exactly how step 3 says the list grows. A cloaked codename (`ox-alpha`) is a pointer to watch, not an entry to add — bundle the model once it is unmasked, named and priced.

   Nothing found here skips the rest of the pass: a new entry still needs a verified slug (step 4), settings that match its family (step 5), a price with a source (step 6), a `(p)` or lab suffix (step 7), and **both** synced sources edited (step 1).
3. **First-party key coverage — every big name gets its own `.env` key.** Every big-name lab that ships a public API must be reachable **two ways**: a **home block gated by that lab's own key**, carrying a fuller lineup, _and_ its flagship on **OpenRouter**, for users who hold only an `OPENROUTER_API_KEY`. This is the Anthropic shape generalised — `ANTHROPIC_API_KEY` lights up six Claudes while only Fable 5.1 is _also_ routed — so `XAI_API_KEY` → Grok, `OPENAI_API_KEY` → ChatGPT/GPT, `GEMINI_API_KEY` → Gemini, `DASHSCOPE_API_KEY` → Qwen, `MOONSHOT_API_KEY` → Kimi, `DEEPSEEK_API_KEY` → DeepSeek, and the remaining home labs all behave the same way. A key drifts out of exactly one place at a time, and there are **seven** of them, so check all seven:
   - **`config.example.yaml`** — an `auto-model-config: <provider>` marker block gated on that key, holding **more than the flagship**: flagship + 1–2 acclaimed or cheaper siblings. A home block that is a lone flagship is itself a finding — the fuller lineup _is_ the reason to hold the lab's own key, and the routed flagship already covers the other case. **Then re-read the `QUICK START` comment at the top of `models:` in the same file** — it lists every key → lineup a second time, in prose no test parses, and it is the copy a user actually reads while editing the file. It had drifted three roster rolls behind (Grok 4.5, Qwen3.7 Max, GLM-5.2) by 2026-08-26.
   - **`scripts/wizard/providers.py`** — the same lineup in `HOME_API_BUNDLES`, so `make setup` and the launch-path sync enable an identical set. Its `LLMProvider(...)` entry for the lab also carries a prose `description=` that names the models; that string is what `make setup` prints, and no test reads it either.
   - **`scripts/sync-api-key-models.py`** — the `(slug, ENV_VAR)` pair in `PROVIDERS`, **and** the key → lineup line in its `QUICK START` docstring. That docstring is one of the four entries no test reads, so it is where a roster roll-forward silently leaves a stale model name behind.
   - **`.env.example`** — a commented `# <LAB>_API_KEY=your-…-api-key` line in the **Model provider API keys** section (not down in the generic OpenAI-compatible list), naming the models it unlocks and, where the key is not obvious to obtain, the console that issues it. A key nobody knows to set enables nothing.
   - **`README.md`** — the §2 leading bullet's _A big name's own key present_ line, which is where a user actually learns the option exists. The other six are wiring; this one is the advertisement, and a lab missing from it is a feature nobody uses.

   Four of the seven are prose that **no test can read** — `providers.py`'s `description=`, `config.example.yaml`'s `QUICK START` comment, the sync script's `QUICK START` docstring, and the README bullet. Those are where a roll-forward goes stale unnoticed; read all four by eye every pass. **`.env.example` used to be a fifth and is now pinned**: `test_env_example_names_the_models_each_home_key_actually_enables` compares each home key's trailing comment against the display names that key enables, after the 2026-09-05 pass found it still advertising Mistral Small 3 three weeks after the roll-forward updated the other four. It allows only a lab prefix every model in the block repeats to be abbreviated away, so "Large 3 / Medium 3.5 / Small 4" passes and a stale version does not. The remaining four are prose in free-form sentences and are not mechanisable the same way — the eye is still the only check.

   Then confirm the **doubling** still holds: each home flagship's bare id appears in the OpenRouter block as `<provider>/<same id>` (modulo case — `minimax/minimax-m3` ↔ MiniMax's own `MiniMax-M3`). `TestFirstPartyKeyCoverage` in `backend/tests/test_sync_api_key_models.py` pins the machine-readable half of this — every registered key documented in `.env.example`'s provider section, no home block trimmed to a lone flagship, every home flagship doubled, and **exactly** `meta-llama` + `nvidia` left routed-only — so that half needs no network. The four prose copies above are the ones it cannot read for you. **When a lab that was OpenRouter-only ships a first-party consumer API, give it a home block**; that is how the list grows. OpenRouter-only is reserved for labs with no such API — currently **Meta Llama** and **NVIDIA Nemotron**, whose flagships stay routed and alone.

4. **Slugs.** Confirm each `model:` is the exact current id (bare Anthropic ids like `claude-opus-5`; OpenRouter `provider/model` slugs; **home** blocks use each lab's own bare id — the OpenRouter slug minus its `provider/` prefix, e.g. `openai/gpt-5.6-sol` → `gpt-5.6-sol`, `z-ai/glm-5.3` → `glm-5.3`). A wrong/unreleased id fails at request time, not at load — verify against the provider's / OpenRouter's catalog, never from memory. **The cheaper siblings need this more than the flagships do**, because a lab's tier naming invites you to _derive_ the sibling's id instead of reading it, and the derived one looks right: the 2026-08-26 pass found three bundled entries — `gpt-5.6-mini`, `grok-4.5-fast`, `glm-5.2-air` — that were named that way and pointed at models no lab ever shipped. Two of the three carried a _plausible_ price, because the price had been taken from the real model the name was groping for, so nothing about the entry looked wrong until a request failed. Enumerate the lab's model list and pick the sibling **off it**; never spell one out of the flagship's name. **Never bundle a `*-latest` alias, either.** An alias moves on its own while the entry's name and `price:` stay where a human left them, so the three halves silently come to describe three different models and nothing raises — `mistral-medium-latest` was found sitting at Medium 3's price on 2026-08-20, and `mistral-small-latest` did the identical thing on 2026-09-02, still labelled "Small 3" at $0.10/$0.30 while serving Small 4 at $0.15/$0.60. Pin the dated/versioned id (`mistral-small-2603`, `mistral-medium-3-5`) and let the audit roll it forward deliberately; the automatic follow is not worth an entry that cannot be wrong out loud.
5. **Per-model settings.** Sanity-check `max_tokens`, `supports_vision`, `supports_thinking`, `temperature`, and the thinking config against the model family (adaptive Claude vs. Haiku budget vs. OpenAI-compatible `extra_body` toggles — see _Keep the model format current_ above). `supports_thinking: true` is load-bearing; drop deprecated fields. Confirm each home block's `base_url`/`api_base` and env var match the lab (e.g. `https://api.x.ai/v1` + `XAI_API_KEY`); Google's home block uses the native `ChatGoogleGenerativeAI` SDK with `gemini_api_key` and no thinking toggle.
6. **Pricing.** Read each price off the provider's / OpenRouter's own model page — or, when that page cannot be reached, off several independent sources that agree exactly, logged as corroborated (_Where a price may come from_, below). Refresh the model's `price:` block (all 41 bundled paid models carry one; `config.example.yaml` holds them literally and `scripts/wizard/providers.py::MODEL_PRICES` holds the same figures for the wizard, and `TestBundledModelPricing::test_the_wizard_bundles_and_the_example_agree` fails if the two ever disagree). Then add a `discount:` block — never a price in the name — for **any** currently discounted model, sourced from OpenRouter's **promotions/discounts page** (derive list as `list = discounted / (1 − discount)`) **or** an Anthropic **introductory-pricing** window (a newly launched Claude below its standard rate for a fixed window). Re-read the provider's note as well as its table: an intro window can end by lapsing _up_ to the list price **or** by the lab making the intro rate permanent, and the second means lowering `price:` and deleting `discount:` (what happened to Sonnet 5 on 2026-08-10). Delete the `discount:` block in **both** synced sources when a promo or intro window ends, or the header keeps advertising a discount nobody is getting; give it an `until:` the moment the provider announces an end date, and let that expire it instead. **Home entries use the lab's own list price with no discount** (the OpenRouter promo is a routing property that stays on the OpenRouter copy). Keep `price:` exact: `input`/`output` stay the **standard** rate — the conservative upper bound, which cost is billed against even while a discount is live — and `discount:` carries the reduced figures beside it.
7. **Privacy marker.** Every OpenRouter entry carries `(p)` (zero-data-retention not guaranteed); the direct Anthropic, first-party **home**, and Ollama entries do not (they hit the lab directly, no middleman). Add `(p)` to any new OpenRouter entry, and the lab's own name suffix (`(OpenAI)`, `(xAI)`, …) to any new home entry.
8. **Regression-test.** `python3 scripts/sync-api-key-models.py --dry-run` must still uncomment the blocks cleanly, and `cd backend && uv run pytest tests/test_sync_api_key_models.py tests/test_setup_wizard.py tests/test_config_integrity.py` must stay green.

#### Where a price may come from: verified, corroborated, or left alone

A price is only worth shipping if you can say where it came from. Three tiers, in
order of preference — use the first one that is actually available on the day:

1. **Verified — the provider's own page.** The lab's own pricing or model page
   (and its promotions page for a discount). For an **OpenRouter** entry, that
   model's OpenRouter page _is_ the authoritative page, because OpenRouter's
   rate is what the entry bills at. This is the standard, and the only tier that
   needs no note.
2. **Corroborated — several independent sources that state the same figure.**
   When the authoritative page cannot be reached — an egress-restricted
   environment, a provider behind a login, a page that is simply down — a price
   **may** be taken from **two or more independent sources that agree exactly**.
   This is an allowed outcome, not a rule being bent: leaving a lab's current
   flagship out of the bundle, or shipping it with **no** `price:` block, is
   worse, because an unpriced model contributes _nothing_ to every cost total
   (§17) and so under-reports spend silently. Conditions, all of them:
   - **Independent means independent.** Two sites reprinting one launch post, a
     tracker and its own API, or an aggregator and the mirror that scraped it,
     are **one** source. Prefer sources that had to look separately: a routing
     marketplace's model page, a comparison site that dates its figures, the
     lab's own docs when its pricing page is what is unreachable.
   - **They must agree exactly, on both numbers.** Input _and_ output. A
     disagreement is a **stop**, not an input to a judgement call — never
     average, never take the lower or the higher, never round the gap away. Two
     sources that differ mean the price is unknown; fall to tier 3.
   - **Standard rate only, never a discount.** A promotion or intro window is
     the most volatile figure on the page and the one whose absence costs
     nothing, since spend is billed at the standard rate either way (§17). A
     discount that cannot be read off the provider's own promotions page is not
     shipped, and a discount is never carried across a version bump.
   - **Record it in [the audit log](docs/model-audit-log.md).** Name the model, the figure, and that it was
     corroborated. This is the whole point of allowing the tier: a corroborated
     price nobody knows to re-check is precisely the wrong-with-confidence
     failure the verify rule exists to prevent, and a named list defeats that by
     **directing** the next pass instead of being silenced by it.
3. **Neither — leave the entry alone.** No authoritative page and no agreeing
   sources means the price is unknown. Keep what is already shipped, log the
   provider as unreachable, move on. **Never carry a price from memory**, and
   never let a model past your knowledge cutoff keep a figure you have not seen
   this pass — that is the one thing no tier permits.

The same three tiers cover a **slug** when the catalogs behind step 4 cannot be
reached; a wrong slug fails loudly at request time, so it is the less dangerous
of the two, but it gets logged the same way.

**The automated job stays at tier 1.** `scripts/audit_models.py` still never
commits a price. Corroboration is a judgement someone makes and writes down —
naming what they read and what agreed — not something a weekly cron can assert
on its own.

#### Audit log

Each pass is recorded in **[`docs/model-audit-log.md`](docs/model-audit-log.md)**
— what was checked, which providers were reachable, and what changed. Read it
before deciding whether to run an audit at all: a dated line saying the roster was
verified last week is usually the whole answer, and it is cheaper than re-deriving
it. Append a pass when you run one; never rewrite an old entry.

## What this fork adds

Convenience features on top of upstream, designed around running DeerFlow locally with mixed cloud + local models (more are covered in the sections further down):

### Adding a new fork feature — what to write, and where

A feature that only exists in code is a feature the next person deletes by accident. Every fork addition lands the same documents — and its own tests — in the **same change set** as the code, and the two guidance files below are byte-budgeted, so where the depth goes is a decision, not a preference.

- **`README.md` — the user-facing half.** Add a `###` subsection under **Core Features** (or a top-level `##` if the feature is not a core-agent behavior, the way _Scheduled Tasks_ and _Backup and Restore_ sit on their own). Write it for someone deciding whether to turn the feature on, not for someone maintaining it. Cover, in this order and in prose rather than a bare list:
  - **What it is, in one paragraph**, naming the UI entry point (the page and the button) so the reader can find it. If it replaces or sits beside an existing flow, say which and how they differ.
  - **The interesting behavior**, especially any outcome a user would not expect — a feature that is allowed to say "no", a step that is deliberately read-only, a default that is off. Bold the surprising part; that sentence is what makes the section worth reading.
  - **The limits that bite**: size caps, ownership scoping, anything digested or truncated before a model sees it. Users hit these and file bugs otherwise.
  - **How to turn it on**, with the literal `config.yaml` block, every key that matters, and any _other_ switch it depends on. State the default explicitly — "off by default" is not implied by an example that shows `enabled: true`.
  - **Add the anchor to the Table of Contents** in the same edit. The TOC is hand-maintained; a section missing from it is a section nobody browses to.
  - **Add a bullet to the leading list** in the blockquote at the top of the file ("On top of upstream, it adds — out of the box:"). That list is the fork's shop window and is meant to be **exhaustive** — every fork upgrade gets a line, with its own emoji, in the same change set that adds the feature. It is not a summary of the section below it: write two or three sentences that lead with what a user _gets_, name the surprising behavior, and say what it costs to turn on (a config key, a daemon setting, nothing). A feature that is documented everywhere except here is a feature nobody discovers, because this list is as far as most readers get.
- **`FORK.md` — this file, the maintainer's half.** Add a numbered `### N.` section under _What this fork adds_ covering the reasoning the README deliberately omits: why the design is shaped this way, which properties are load-bearing, and what a future refactor must not "simplify" away. Then add a row to the [Post-sync feature checklist](#post-sync-feature-checklist) naming **the exact command that verifies it** and the specific asserts that are silent when broken — that row is what a sync 18 months from now actually runs, and `scripts/upstream_sync.py` renders it into every auto-generated sync PR. The rule runs both ways: **a feature that is removed takes its row with it**, and a check that is replaced is replaced in the row too — see [How to use this file](#how-to-use-this-file) for why a stale row is worse than a missing one, and for when the depth behind a row belongs in its own file.
- **The nearest `AGENTS.md` — the agent's half.** Invariants an AI coding agent needs _before_ editing the code go beside the code, in the module-local guide. **Do not grow the root or module files**: `backend/tests/test_agent_guidance_check.py` is a hard assert (soft budgets: root 16 KiB, module 28 KiB, local 40 KiB), the root file runs within a few dozen bytes of its budget, and _documenting a feature can fail CI on its own_. Put the depth in a local `AGENTS.md` next to the code, leave a one-line pointer in the module file, and register the new path in that test's approved-guidance list.
- **The checks themselves — write them, don't just cite them.** The FORK.md row above names a command; this is the work of making that command exist and mean something. A fork feature ships with **new** tests, not a note that the existing suite still passes: the pure model or helper in a unit test, the wiring in whatever layer owns it (`backend/tests/` for Python — TDD is mandatory there — `frontend/tests/unit/` for logic and hooks, `frontend/tests/e2e/` for anything a user clicks through), and a launch-time script in the test that already covers that script. Two rules make the difference between a test and a decoration:
  - **Prove the test fails without the change.** Revert the behavior (or neutralize the one line that implements it), watch the new test go red, put it back. A test that passes both ways pins nothing, and the fork is full of invariants — a per-thread lock, a stripped request option, a default that must stay off — where the broken state is _silent_ and every other test stays green.
  - **Pin the property, not the implementation.** Name the thing that would be quietly "simplified" away and assert on that: the option that must reach the wire, the lock that must stay scoped, the branch that must decline rather than evict. Then say so in the row and in the local `AGENTS.md`, so the next person reads why before they refactor.
- **`CHANGELOG.md` — the release half.** One `### Added` bullet under `## [Unreleased]`, written from the user's perspective and leading with what changed for them, not with the module you touched. Name the config key and its default in the same bullet.
- **Config, if the feature has any.** **Any** new key means bumping `config_version` **and both chart copies** (`deploy/helm/deer-flow/values.yaml` and that chart's `README.md`) — `scripts/check_config_version.sh` is CI's `validate-chart` job, and nothing outside CI reads those copies. It is tempting to assume a single leaf key inside an existing section is exempt; it is not. `config_upgrade.py` compares the **shape**, nested keys included, and at equal versions it _warns and writes nothing_, so an existing install keeps a config permanently missing the key while every launch path prints the warning. Don't reason about it — prove it, on a copy of the previous example:

  ```bash
  git show HEAD:config.example.yaml > /tmp/prev-config.yaml
  python3 scripts/config_upgrade.py /tmp/prev-config.yaml config.example.yaml
  ```

  It must print `+ <your key>` and stamp the new version. If it instead says _stamped current but is missing N field(s)_, the bump is missing.

### 1. Auto-synced Ollama models in `config.yaml`

`scripts/sync-ollama-models.py` queries the local Ollama daemon (or remote, via `OLLAMA_HOST`) and reconciles `config.yaml`'s `models:` section with whatever you have installed via `ollama pull`. Capabilities (`thinking`, `vision`, `tools`) are detected via `/api/show` and translated into DeerFlow's `supports_*` flags.

**Context window (`num_ctx`).** Ollama defaults `num_ctx` to just **2048 tokens** regardless of what a model actually supports — small enough to silently truncate the agent's context (system prompt + tools + skills + memory + conversation), and smaller than the 8192-token `num_predict` output budget the entries request. The sync therefore reads each model's **native context length** from `/api/show` (`model_info.<arch>.context_length`) and writes an explicit `num_ctx`, clamped to **32768** so a 128K-native model doesn't allocate an OOM-sized KV cache on a typical local GPU. Override the clamp with `--num-ctx-cap N` (or `--num-ctx-cap 0` for each model's full native length). `num_predict` is kept at or below half the window so there's always room for the prompt.

**VRAM-aware sizing.** Tell DeerFlow how much GPU memory you have and the flat 32768 clamp is replaced by a **per-model estimate**: the largest window whose KV cache fits next to that model's weights in your budget. The math uses each model's attention geometry from `/api/show` (layers × KV heads × head dims, so GQA models are costed correctly) and its weights size from `/api/tags`, minus a conservative overhead reserve; the result is floored to 2048-token steps and never below 4096. A 3B model on a 24 GB card gets its full native window; a 32B model on the same card gets what actually fits. Configure it via `make setup` (which auto-detects VRAM via `nvidia-smi` / `rocm-smi` / Apple unified memory) or by hand in `config.yaml`:

```yaml
ollama:
  vram_gb: 16 # GPU memory budget in GiB
  kv_cache_type: q8_0 # optional; must match the daemon's OLLAMA_KV_CACHE_TYPE
```

`kv_cache_type: q8_0` sizes for a quantized KV cache — near-lossless, roughly half the per-token memory, so roughly **double the affordable window**. It only _assumes_ the setting: KV-cache quantization is a server-side Ollama env var that DeerFlow can't set per request, so enable it on the daemon (`sudo systemctl edit ollama` → `Environment="OLLAMA_KV_CACHE_TYPE=q8_0"`; older Ollama also needs `OLLAMA_FLASH_ATTENTION=1`). Models without flash-attention support silently fall back to f16 on the server — worst case the estimate is optimistic and Ollama offloads a few layers to CPU (slower, not fatal). An explicit `--num-ctx-cap` still applies as a hard ceiling, and models whose geometry can't be read keep the flat-cap behavior. `--vram-gb` / `--kv-cache-type` override the config per run.

**Weight size (`size_bytes`).** The sizing math above already reads each model's on-disk size from `/api/tags` to decide how much KV cache fits beside it; that number is now also _written_ into the entry as `size_bytes`, and the model picker renders it next to the context window (`qwen3:8b · 5.2 GiB · 32K ctx`). It answers the question the window alone cannot: a 20 GiB model and a 32K window do not both fit on a 24 GiB card, and the way you used to find that out was to select the model and notice the daemon had quietly offloaded layers to CPU. It is presentation metadata only — like `price:` and `context_window` it must stay in the model factory's exclude set (§17's trap), because `ModelConfig` is `extra="allow"` and an unexcluded key is forwarded into the provider client's completion request. A daemon that reports no size writes no key.

The script is **idempotent and bounded** — it only owns content between its `BEGIN ollama-sync` / `END ollama-sync` markers. Anything you've hand-edited outside that block (cloud models, custom Ollama overrides) is never touched.

It is hooked into **every launch path**, so however you start DeerFlow your Ollama list is refreshed automatically. If the daemon is unreachable, the script no-ops with no changes:

| Path                                  | Where it runs                                        | `base_url` written into entries          |
| ------------------------------------- | ---------------------------------------------------- | ---------------------------------------- |
| `make dev` / `make start` (+ daemons) | `scripts/serve.sh`                                   | `http://localhost:11434` (local runtime) |
| `make docker-start` (Docker dev)      | `scripts/docker.sh`, on the host before `compose up` | `http://host.docker.internal:11434`      |
| `make up` (Docker prod)               | `scripts/deploy.sh`, on the host before `compose up` | `http://host.docker.internal:11434`      |

**Why the base_url differs on the Docker paths.** The sync always _queries_ the host's Ollama over loopback, but inside a container `localhost` is the container itself, not the host where Ollama listens. So for the Docker paths the sync writes `http://host.docker.internal:11434` (the `--container` flag; `host.docker.internal` is mapped to the host gateway via `extra_hosts` in the compose files, and is already in the gateway's `NO_PROXY`). `config.yaml` is edited on the host **before** the containers mount it, so this works even though the gateway mounts `config.yaml` read-only. A genuinely remote `OLLAMA_HOST` (a non-loopback host) is recorded verbatim on every path, since it is reachable from both host and container.

> **Host-run Ollama + Docker:** for `host.docker.internal` to reach it, Ollama must listen on all interfaces (`OLLAMA_HOST=0.0.0.0 ollama serve`), not just `127.0.0.1` (its default). Otherwise the container can resolve the host but the connection is refused. The Docker launch paths now detect this: when the sync writes `host.docker.internal` entries but the host's Ollama doesn't answer on the Docker bridge gateway, it prints the exact fix (advisory only; Docker Desktop, which proxies host loopback, is exempt). The AIO sandbox containers additionally map the alias themselves and default `OLLAMA_HOST=http://host.docker.internal:11434` into the container env, so agent-run Ollama clients inside the sandbox target the host daemon out of the box — `make dev`'s sandbox preflight prints the same advisory when the host daemon is loopback-bound.

```bash
# Manual run (local runtime — base_url localhost)
python3 scripts/sync-ollama-models.py --verbose

# Manual run for a containerized runtime (base_url host.docker.internal)
python3 scripts/sync-ollama-models.py --container --verbose

# Dry-run (prints proposed config to stdout, doesn't write)
python3 scripts/sync-ollama-models.py --dry-run

# Remote Ollama (queried and written verbatim on every path)
OLLAMA_HOST=http://server.lan:11434 python3 scripts/sync-ollama-models.py

# Explicit base_url override (wins over --container)
python3 scripts/sync-ollama-models.py --base-url http://ollama:11434

# Use each model's full native context window (no 32768 clamp)
python3 scripts/sync-ollama-models.py --num-ctx-cap 0
```

**Daemon lifecycle (`keep_alive`, preload, contention).** The sizing above stops
at the config file; the daemon itself was unmanaged, and three things followed
from that.

_Every subagent call paid a cold start._ Ollama unloads a model ~5 minutes after
its last call. In a turn where the lead thinks for a while and then delegates,
the local subagent's weights have already been evicted and get reloaded from
disk before it can answer — the cost landing on exactly the local-subagent
configuration this fork recommends. `ollama.keep_alive` is now written into
every synced entry (and forwarded by `ChatOllama` to the daemon), with
`ollama.keep_alive_overrides` for per-model values:

```yaml
ollama:
  keep_alive: 30m # "1h", a bare number of seconds, or -1 to never unload
  preload: true # warm models[0] at launch
  keep_alive_overrides:
    qwen3:8b: 1h
```

Unset leaves the daemon's own default, which is the prior behavior — pinning
weights in VRAM is a decision about the whole machine, so the sync does not
assume it.

_The first message of a session was always slow._ `ollama.preload: true` loads
`models[0]` (which is what `models/factory.py` resolves an unspecified model to)
into VRAM at launch, via `/api/generate` with an empty prompt — the load-only
request, no tokens generated. `scripts/serve.sh` runs it **backgrounded**:
loading weights can take tens of seconds and must never sit in front of the
stack starting. It is best-effort in both directions — a busy or absent daemon
is a no-op, and a cloud `models[0]` means there is nothing local to warm.

_Two local models could not both be resident, silently._ A local lead with a
local subagent means two sets of weights in VRAM at once. Ollama does not fail
there — it evicts one to load the other, so every delegation pays a full reload
and the run just crawls. When `vram_gb` is set, the sync now warns at launch
with the real numbers, reusing the same geometry math as the context sizing:

```
[ollama-sync] VRAM contention: qwen3:32b (19.9 GiB) + qwen3:14b (8.9 GiB) need
~30.3 GiB resident together (weights + a 4096-token KV cache each + 1.5 GiB
overhead), but the configured budget is 24 GiB. …
```

A warning, and only a warning: it never silently reassigns the user's model
choice. `make doctor` gained a matching **Local Models** section — daemon
reachable, configured models actually pulled (naming the `ollama pull` for any
that are not), and whether `keep_alive` is set. All warn-only; a deliberately
stopped daemon is not a broken install.

### 2. API-key model auto-config in `config.yaml`

A companion to the Ollama sync for **cloud** models. `scripts/sync-api-key-models.py` runs on every launch, reads the provider API keys in your `.env` (falling back to the process environment), and **uncomments** the matching ready-to-use model block in `config.yaml` — so the right models are enabled on first start with no manual editing.

| `.env` key present   | Models enabled                                                                                                                                                                                                                              | Provider / `use`                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `ANTHROPIC_API_KEY`  | Claude **Fable 5.1**, **Opus 5**, **Opus 4.8**, **Sonnet 5**, **Sonnet 4.6**, **Haiku 4.5**                                                                                                                                                   | direct Anthropic API (`langchain_anthropic:ChatAnthropic`)                   |
| `OPENROUTER_API_KEY` | Claude **Fable 5.1**, **Grok 4.6**, **GPT-5.6 Sol**, **GPT-5.3 Codex**, **Gemini 3.6 Flash**, **Llama 4 Maverick**, **MiniMax M3**, **Qwen3.8 Max**, **Kimi K3**, **Mistral Large 3**, **DeepSeek V4 Pro**, **GLM-5.3**, **Nemotron 3 Ultra** | OpenRouter (`langchain_openai:ChatOpenAI` + `base_url`)                      |
| `OPENAI_API_KEY`     | **GPT-5.6 Sol**, **GPT-5.3 Codex**, **GPT-5.6 Terra**, **GPT-5.6 Luna**                                                                                                                                                                     | direct OpenAI API (`langchain_openai:ChatOpenAI`)                            |
| `XAI_API_KEY`        | **Grok 4.6**, **Grok 4.3**                                                                                                                                                                                                                  | direct xAI API (`langchain_openai:ChatOpenAI` + `base_url`)                  |
| `GEMINI_API_KEY`     | **Gemini 3.6 Flash**, **3.5 Flash-Lite**, **3.1 Pro**                                                                                                                                                                                       | native Gemini SDK (`langchain_google_genai:ChatGoogleGenerativeAI`)          |
| `DEEPSEEK_API_KEY`   | **DeepSeek V4 Pro**, **V4 Flash**                                                                                                                                                                                                           | direct DeepSeek API (`deerflow.models.patched_deepseek:PatchedChatDeepSeek`) |
| `MISTRAL_API_KEY`    | **Mistral Large 3**, **Medium 3.5**, **Small 4**                                                                                                                                                                                            | direct Mistral API (`langchain_openai:ChatOpenAI` + `base_url`)              |
| `MOONSHOT_API_KEY`   | **Kimi K3**, **Kimi K2.6**                                                                                                                                                                                                                  | direct Moonshot API (`deerflow.models.patched_deepseek:PatchedChatDeepSeek`) |
| `DASHSCOPE_API_KEY`  | **Qwen3.8 Max**, **Qwen3.7 Plus**                                                                                                                                                                                                           | Alibaba DashScope (`langchain_openai:ChatOpenAI` + `base_url`)               |
| `MINIMAX_API_KEY`    | **MiniMax M3**, **MiniMax M2.7**                                                                                                                                                                                                            | direct MiniMax API (`langchain_openai:ChatOpenAI` + `base_url`)              |
| `ZAI_API_KEY`        | **GLM-5.3**, **GLM-4.5 Air**                                                                                                                                                                                                                | direct z.ai API (`langchain_openai:ChatOpenAI` + `base_url`)                 |

The first two rows are the aggregators; the rest are **first-party "home" API blocks**, one per big-name lab that ships its own API. This mirrors how Anthropic is handled — a lab's full lineup lives on the lab's own key, and the flagship is _doubled_: it's reachable through both its home API AND OpenRouter (the direct copy carries no `(p)` privacy caveat). So with a lab's own key set, its cheaper siblings light up on the home API only, while its flagship exists on both. OpenRouter keeps its trim "one flagship per lab" set unchanged — including the GPT **Sol + Codex** double.

Every block is independent: each key present enables its own block, and blocks never collide because their `name:`s are provider-prefixed (`openai-gpt-5.6-sol` on the direct block vs. `openrouter-gpt-5.6-sol` on the routed one, just as **Fable 5.1** appears once direct and once via OpenRouter). The adaptive Claude models (Fable 5.1, Opus 5, Opus 4.8, Sonnet 5, Sonnet 4.6) use adaptive thinking (Haiku takes an explicit budget); DeepSeek and Moonshot home entries ship the OpenAI-compatible `extra_body` thinking toggle, and every thinking-capable entry ships `supports_thinking: true` so DeerFlow's thinking toggle actually engages. (Gemini's home entries go through the native SDK, which has no thinking toggle here — use the OpenRouter Gemini entry or a `gemini_openai_gateway` for Gemini thinking; Mistral Large is not a reasoning model, matching its OpenRouter entry.)

**Bounded and idempotent — safe on a hand-edited config.** The script owns only the model entries between a provider's `# === BEGIN auto-model-config: <provider> ===` / `# === END … ===` markers in `config.yaml` (shipped in `config.example.yaml`, so `make config` copies them in). It:

- **only ever uncomments**, never re-comments — a model you enabled by hand is never turned back off;
- **skips a block whose models are already active**, so a config written by `make setup` (or by hand) is never duplicated;
- **no-ops when the key is missing** or is still a placeholder (`your-…`, empty, or an unresolved `$VAR`);
- **no-ops when the markers are absent** (an older `config.yaml` predating this feature) — nothing to uncomment;
- refuses to run against a config with duplicate top-level keys (same guard as the Ollama sync).

It is hooked into **every launch path**, right after the Ollama sync, so however you start DeerFlow the block is enabled once your key is in place:

| Path                                  | Where it runs                                            |
| ------------------------------------- | -------------------------------------------------------- |
| `make dev` / `make start` (+ daemons) | `scripts/serve.sh` (reads the `.env` it already sourced) |
| `make docker-start` (Docker dev)      | `scripts/docker.sh`, on the host before `compose up`     |
| `make up` (Docker prod)               | `scripts/deploy.sh`, on the host before `compose up`     |

On the Docker paths `config.yaml` is edited on the host **before** the containers mount it (read-only), same as the Ollama sync. `make setup` still enables the identical sets interactively (`scripts/wizard/providers.py` is the shared source of truth for the model definitions).

```bash
# Manual run (reads repo-root .env and config.yaml)
python3 scripts/sync-api-key-models.py --verbose

# Preview without writing
python3 scripts/sync-api-key-models.py --dry-run

# Point at a specific config / env file
python3 scripts/sync-api-key-models.py --config config.yaml --env-file .env --verbose
```

Model ids current as of 2026-07 — edit the block in `config.example.yaml` (or `config.yaml` after it is enabled) to add, drop, or re-slug models.

The roster this script enables — which models are bundled, how their settings and
prices are kept current, and the periodic audit that checks all three — is its own
section: [The model bundle and its audit](#the-model-bundle-and-its-audit).

### 3. Per-thread subagent model override (Ultra mode)

A second model selector appears next to the lead-model picker when **Ultra mode** (subagents enabled) is active. Default is "Follow lead" (subagents inherit the lead model, identical to upstream behavior). Pick anything else and `task` tool delegations route to that model instead.

Backend reads `subagent_model_name` from the LangGraph thread context in `task_tool.py` and overrides the resolved subagent model. Frontend stores the choice in `AgentThreadContext` only — **ephemeral per thread**, no localStorage. Switch threads and it resets to "Follow lead".

Models flagged `supports_tools: false` (only Ollama models that don't report the tools capability) appear at the bottom of the list, dimmed, with a "(no tool support)" annotation. Still selectable in case the flag is wrong; tool-using subagents will simply fail at runtime.

### 4. Follow-up suggestions off by default (+ model picker)

Upstream generates the clickable follow-up-question chips after every answer via an extra one-shot LLM call. That is real per-turn cost you may not want, so this fork defaults it **off** and makes it a first-class, per-user preference.

- **Default off.** The client-side setting `suggestions.enabled` defaults to `false` (`frontend/src/core/settings/local.ts`), so a fresh browser makes no suggestion calls. The frontend only requests suggestions when the server master switch (`config.yaml → suggestions.enabled`, unchanged) **and** the per-user toggle are both on.
- **Toggle in settings.** A new **Settings → Suggestions** page (`suggestions-settings-page.tsx`) exposes the toggle. If the operator has disabled suggestions server-side, the toggle is greyed with an explanatory hint.
- **Model picker.** Under the toggle, a dropdown chooses which model writes the questions. The first option, **"Follow workflow selection"** (`modelName: undefined`), reuses the thread's current model — identical to the previous behavior. Pick any configured model instead (e.g. a cheap one) and it is sent as the suggestions request's `model_name`; the backend endpoint already accepts that override, so no backend change was needed.

The preference lives in `localStorage` (`deerflow.local-settings`) alongside the other client settings — per-browser, not per-thread. The goal is purely cost control: leave it off, or point it at a cheap model, and the suggestion feature stops being a silent tax on every turn.

### 5. Passwordless by default (local use)

Upstream ships a full email/password (plus optional SSO) login wall: on first run you create an admin through `/initialize`, and every browser then has to log in. For a personal machine — and especially for reaching the app from another device on your LAN — that wall is pure friction. This fork **defaults the local stack to no login at all**.

The mechanism is upstream's own `DEER_FLOW_AUTH_DISABLED` switch, which both the Gateway (`backend/app/gateway/auth_disabled.py`) and the Next.js SSR auth check (`frontend/src/core/auth/auth-disabled-user.ts`) already honor: when set, every request resolves to the built-in `default` admin user, the login/setup pages are skipped, and there is no password to manage. The fork just turns it **on by default** at launch:

- **Where it's wired.** `scripts/serve.sh` exports `DEER_FLOW_AUTH_DISABLED="${DEER_FLOW_AUTH_DISABLED:-1}"` (in the `apply_default_auth_mode` helper) right after loading `.env`, before the gateway and frontend are launched, so **both** child processes inherit it. This covers every local path: `make dev`, `make start`, and their `--daemon` variants. The Docker **prod** path (`make up` / `scripts/deploy.sh`) has a matching `apply_default_auth_mode` helper that resolves the value from `.env` (via `read_dotenv_value`, which honors an already-exported shell var first) and defaults it to `1`, then exports it; `make up` prints a warning line when auth ends up off. Because `deploy.sh` doesn't source `.env` into the shell and the frontend container reads only `frontend/.env`, `docker-compose.yaml` forwards `DEER_FLOW_AUTH_DISABLED` **and** the production markers `DEER_FLOW_ENV` / `ENVIRONMENT` to **both** the gateway and frontend `environment:` blocks — otherwise the two containers could disagree on whether auth is on. (Before this fix, `make up` was _not_ wired with the default, so a home-lab Docker deploy hit the login wall unexpectedly — see "Troubleshooting: nginx 502 after `make up`" below.)
- **Opt-out, not forced.** Set `DEER_FLOW_AUTH_DISABLED=0` in `.env` to restore the normal email/password login. Any explicit value you set (0 or 1) is preserved — the default only fills in the unset case. Both `.env.example` files document the toggle.
- **Self-disabling in production.** The flag is ignored whenever `DEER_FLOW_ENV` / `ENVIRONMENT` is `prod`/`production` (enforced in both `auth_disabled.py` and `auth-disabled-user.ts`), so a real deployment that sets that variable keeps authentication on regardless of this default. The Docker stack also publishes its entry port on `127.0.0.1` (loopback) by default (`BIND_HOST`), so the default surface is local-only.
- **LAN note.** Because there's no login, any device that can reach the server (e.g. `http://<your-ip>:2026`) is in — that's the point, but it also means anyone on your network is too. Keep it to trusted networks, or flip `DEER_FLOW_AUTH_DISABLED=0` and use the login.
- **Dev-server access from other devices works out of the box too.** Next.js gates its dev resources (`/_next/*`, fonts, HMR) with `allowedDevOrigins` — an unlisted host 403s the client bundles, so the page renders but never hydrates (visible shell, dead buttons, no input box). To match the passwordless-for-LAN default, `frontend/src/dev-origins.js` now **defaults that allowlist to the private-LAN and Tailscale ranges** (`10.*`, `172.*`, `192.168.*`, `100.*` Tailscale CGNAT, `**.ts.net` MagicDNS, `*.local`), so `make dev` reached from a phone on the network or over Tailscale hydrates without extra config. `DEER_FLOW_DEV_ALLOWED_ORIGINS` still adds hosts the defaults miss (a custom domain, an IPv6 literal); `DEER_FLOW_DEV_ALLOWED_ORIGINS_STRICT=1` drops the built-in defaults for upstream's stricter behavior. Dev-only — production builds ignore `allowedDevOrigins`. Pinned by `frontend/tests/unit/dev-origins.test.ts` (which runs the defaults through Next's real matcher).

`config.yaml` is unchanged; this is purely an environment default, so it ships in the fork (via `serve.sh` / `deploy.sh` + the `.env.example` docs) rather than per-install. Pinned by `backend/tests/test_serve_auth_default.py` (local launcher) and `backend/tests/test_deploy_auth_default.py` (Docker prod launcher opt-out precedence + the compose forwarding of `DEER_FLOW_AUTH_DISABLED` / `DEER_FLOW_ENV` / `ENVIRONMENT` to both containers).

### 6. Multi-user mode toggle (combine or isolate histories)

Upstream scopes every conversation to an owner `user_id`, so each login only sees its own threads. That's right for a shared deployment, but it has a sharp edge on a personal fork: once you go passwordless (§5) the effective user is always `default`, yet any conversations created back when login was on live under real account ids — so they're "stranded", invisible under `default`, and the phone and PC appear to have separate histories. **Multi-user mode** is a toggle for exactly this.

- **What it does.** ON (default) = upstream behavior, per-login thread isolation. OFF = one shared workspace: thread listing and per-thread access ignore the owner filter, so **every conversation is visible regardless of which login or device created it** — including the stranded pre-passwordless ones.
- **Where it lives.** Settings → Account, as a switch (admin-only; in passwordless mode the built-in `default` user is admin). Turning it OFF pops a confirmation explaining it will combine all histories; turning it back ON is immediate and restores isolation. It is a **server-wide** setting (not a per-browser preference) — that's what makes it actually merge phone + PC — persisted as JSON under the DeerFlow home dir (`runtime_settings.json`), read hot (no restart), never touching the operator's `config.yaml`.
- **How it's wired.** `deerflow/config/runtime_settings.py` owns the setting plus `resolve_owner_scope()` — a read/access resolver that returns `None` (no owner filter) when the mode is OFF and otherwise defers to the normal `resolve_user_id`. The thread-metadata store (`search`/`get`/`check_access`) and run-store read helpers use it, so the sidebar lists everything and any thread can be opened/continued; `check_access` returning True covers every `owner_check` route guard in one place. **Writes still stamp the real owner**, so re-enabling isolation cleanly restores each login's own view. Gateway `GET`/`PUT /api/settings/multi-user-mode` reads/toggles it (PUT admin-gated).
- **Security.** With it OFF, anyone who can reach the server sees all conversations — the same trust model as passwordless. Leave it ON on any shared/public deployment.

Pinned by `backend/tests/test_multi_user_mode.py` (setting round-trip, owner-scope bypass, thread isolation ON vs OFF, admin-gated API) and `frontend/tests/unit/core/settings/multi-user-mode.test.ts`.

### 7. Live cost overview in the conversation header (model-aware) + memory/suggestions counters

The conversation header already showed a token counter (input / output / total for the whole thread). This fork adds a **real-cost estimate** next to it, and — because a personal deployment mixes premium, cheap, and free-local models on purpose (§"Why mix local and cloud" below) — makes it **model-aware** so the number reflects what you actually spent, not a single headline rate.

- **Where the price comes from.** Each model's `price:` block in `config.yaml` (`currency`, `input`, `output`, optional `cache_hit`) plus an optional `discount:` beside it — the fields §17 introduced; the legacy `pricing:` block (`input_per_million`, `promo_*_per_million`, …) and the price-in-the-name parser are still read for configs written before that, in that order of precedence. **All 41 bundled paid models ship priced** on both the auto-config and `make setup` paths, so the estimate works out of the box whichever provider you use; only unpriced local Ollama models contribute nothing. No price anywhere → the cost line simply hides (token counts still show).
- **The cost is green, and a live discount shows both prices.** The figure reads as money rather than as another token counter, so it is rendered in green (`text-emerald-500`) in both the header pill and the dropdown. When any model in the thread is currently discounted, the dropdown shows **two** totals side by side — the green one is what the conversation costs at today's promo rate, the red one (`text-red-500`) is the same thread billed at the standard rate it reverts to when the promo ends — with a `promo rate now` / `standard rate` legend beneath. Both totals cover the **whole** thread: an undiscounted model contributes its ordinary cost to each, so the pair is directly comparable rather than being a discounted subtotal beside a full total. The header pill stays a single number (what you actually pay now); there is no room there to label a pair. `promo_total_cost` is null — and the UI falls back to one green figure — when nothing in the thread is discounted, or when the promo total happens to equal the standard one, because printing the same number twice in two colours claims a discount that does not exist.
- **A missing price explains itself.** A model that burned tokens with no price configured is reported in the endpoint's `unpriced_models`, and the header names it: _"No cost shown: no price is configured for `<model>`"_ when nothing was priceable, or _"Excludes `<model>` — no price configured, so the real cost is higher"_ when the total covers only some of the run. Without this a hand-added model silently renders a bare `—` (or a quietly low total), which is indistinguishable from the feature being broken — the exact failure that hid the two bugs above.
- **Model-aware, so subagents are billed correctly.** The cost is summed from each run's **per-model** `token_usage_by_model` split, not a flat rate on the thread total. A run whose lead was Opus and whose subagents ran on Haiku or a local Ollama model is priced Opus-for-Opus and Haiku-for-Haiku — the lever this fork exposes (§3, the per-thread subagent model dropdown) shows up directly in the number. Prompt-cache hits are billed at the cache-hit rate when configured (a conservative upper bound otherwise), reusing the exact same cache-aware math as the ops console.
- **Provider-reported model ids are resolved back to your config entry.** `token_usage_by_model` buckets are keyed by what the _provider_ reported (`response_metadata.model_name`), which is routinely **not** the id in `config.yaml`: LangChain records the API-resolved model, so Anthropic hands back the dated snapshot its alias resolved to (`claude-opus-5` → `claude-opus-5-20260115`), OpenAI does the same, OpenRouter appends `:variant` routing tags, and a routed slug carries a `vendor/` prefix. Exact-string matching therefore found **no** price for any bucket, so every per-model `cost` was null and `total_cost` stayed null while `currency` was set — which is exactly the `—` the header rendered from the day this feature shipped. `lookup_pricing` now tries a small ordered set of normalized forms by **exact** lookup (never a prefix scan, so a normalization can only ever hit a model the operator actually configured): the reported id, then with the `vendor/` prefix peeled, the `:variant` tag dropped, and a terminal date stamp (`-20260115`, `-2026-01-15`, `@20260115`) removed. Most-specific-first, so a configured OpenRouter copy is still billed at its own routed price rather than the direct entry its slug reduces to; the date pattern is deliberately narrow, so a genuinely different sibling (`claude-opus-5-turbo`) stays unpriced instead of inheriting a neighbour's rate. Ollama tags (`qwen3:8b`) match exactly first and are unaffected.
- **A streamed model id can arrive doubled, and is collapsed before anything prices it.** The reported id is not always _reported_: for a streamed response LangChain assembles it chunk by chunk with `merge_dicts`, which **concatenates** two equal strings under the same `response_metadata` key. `langchain_openai` writes `model_name` on every chunk carrying a `finish_reason`, and some OpenAI-compatible providers (OpenRouter among them) send more than one such chunk — so the assembled message says `deepseek/deepseek-v4-prodeepseek/deepseek-v4-pro`, and its `finish_reason` says `stopstop`. Nothing raises: the id simply matches no configured model, so every token it burned counted as unpriced and the header fell back to `—` while the unpriced note named a model that does not exist. `deerflow.model_ids.normalize_reported_model_name` collapses a whole id repeated end to end, applied where a reported id is read — the run journal's per-model buckets (the single write path for every cost consumer), the subagent token collector, the one-shot LLM used by the memory/suggestions counters, and `SpendBudgetMiddleware`'s message fallback, where an unrecognized model prices at **zero** and would leave a capped account uncapped on exactly that provider. The rule is deliberately narrow — **only** an exact whole-string repetition, never a mismatched pair (`claude-opus-5claude-haiku-4-5`) or a partial one (`claude-opus-5claude-opus-5-20260115`), because guessing which half is real would bill one model at another's rate, and that is worse than showing no cost. Runs already persisted with the doubled key need no migration: `lookup_pricing` tries the collapsed form as one of its candidates, and the two store aggregations plus the console's spend/usage reports normalize on read, so an old bucket merges into the model it names instead of standing as a second, unpriced row. Pinned by `backend/tests/test_model_ids.py` and cases in `test_pricing.py`, `test_token_usage_by_model.py`, `test_thread_token_usage.py`, `test_console_router.py` and `test_spend_budget_middleware.py`.
- **Ollama / unpriced = $0.** A model with no `pricing:` block contributes nothing to the cost — local inference is treated as free even though it burns electricity. The header's **?** tooltip says exactly this so the number is never mistaken for a billing statement.
- **Everything the conversation spends is counted, not just its runs.** Four LLM calls never become a graph run, so none of their tokens reach the thread's run totals: background **memory** extraction (§"Long-term memory off by default"), follow-up **suggestions** (§4), the composer's **prompt polish** rewrite, and the per-turn **goal** completion check. Each is tracked in a small **durable** per-thread registry and shown as its **own** priced counter in the header dropdown when non-zero, so you can see what each costs on top of the conversation itself. The registry survives a Gateway restart — see _Durable auxiliary counters_ below.
- **The rule, because it is what makes the number trustworthy: an unrecorded sink is not free, it is invisible.** A missing counter does not show a warning or a `—`; the header simply prints a total _lower_ than the money that left the account, and nothing on screen distinguishes that from a cheap conversation. Two sinks shipped that way and were found by this audit rather than by a bug report:
  - **`input_polish`** is the one that mattered most, because `input_polish.enabled` is **`true` out of the box** — it is the only auxiliary sink a user pays for without having opted into anything. Every press of the composer's polish button was a real provider call charged to nobody.
  - **`goal`** fires once per turn for as long as a goal is active on the thread, and again for every hidden continuation, from the run worker _after_ the graph run has finished — which is exactly why its tokens have no run left to attach to. On a long-running goal it is not a rounding error.
    So the rule now stated in `deerflow/runtime/aux_usage.py`: **a new non-graph LLM call that takes a `thread_id` gets a category in `CHAT_AUX_CATEGORIES` in the same change set that adds it.** The one deliberate exception is `agent_generation`, which reads several conversations and belongs to none of them; it is billed to a synthetic thread id so it appears on the spend page's feature table rather than in one chat's header.
- **One unpacking of `usage_metadata`, not one per call site.** Every sink reads the same response shape — `input_tokens` / `output_tokens` / `total_tokens` plus a cache-hit count nested under `input_token_details.cache_read`. That nesting is the part a hand-written fifth copy drops, and a dropped cache-read count bills a cached prompt at the full input rate. `aux_usage.usage_metadata_kwargs` owns it, and `record_aux_usage_metadata` / `arecord_aux_usage_metadata` are what the sinks call. The routers keep their own `try/except` **on top of** the helper's: "a broken counter never breaks the feature it is counting" has to hold when a layer _beneath_ the call site changes, not only when the store is down.

**Where it's wired.**

| Piece                                                                                                                  | Location                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Shared pricing math (build map, provider-id resolution, per-token cost, per-run cost, one-currency guard, promo rates) | `backend/app/gateway/pricing.py` — extracted from `routers/console.py` so the console and the thread endpoint price identically. `_pricing_lookup_candidates` owns the provider-reported-id normalization, so the console, the thread endpoint, and the memory/suggestions aux counters all resolve ids the same way. `_parse_promo_rates` validates a discount (both directions, positive, at or below list) and `ModelPricing.promo()` hands it back as an ordinary `ModelPricing`, so `token_cost` prices a promo through the same formula as a standard rate rather than a second one that could drift                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| Bundled model prices                                                                                                   | All 41 paid entries carry a `price:` block in `config.example.yaml`'s marker blocks, mirrored by `scripts/wizard/providers.py::MODEL_PRICES`; a test asserts the two agree, and no price may appear in a `display_name` (§17)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| Thread cost endpoint                                                                                                   | `GET /api/threads/{id}/token-usage` (`routers/thread_runs.py`) now returns `total_cost`, `promo_total_cost` (the same whole-thread total at live discount rates, null when nothing is discounted), `currency`, `unpriced_models` (models that spent tokens with no configured price), per-model `cost`/`input`/`output`/`cache_read`, `superseded_cost`/`superseded_promo_cost`/`superseded_tokens`/`superseded_runs` (spend on turns an edit or regeneration replaced — inside the total, outside the chart), and an `aux` map (memory/suggestions tokens+cost). The store aggregation (`runs/store/memory.py`, `persistence/run/sql.py`, shared `new_by_model_usage_entry()`) now carries the per-model input/output/cache-read split the pricing needs                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| Auxiliary-usage registry                                                                                               | `backend/packages/harness/deerflow/runtime/aux_usage.py` — thread-safe, bounded (LRU over 4096 threads), and **durable**: a write-through cache over `runtime/aux_usage_store.py`, a small dedicated SQLite file at `<DeerFlow home>/aux_usage.sqlite3`. `CHAT_AUX_CATEGORIES` names the four per-conversation sinks. Memory records via `_host_default_extraction_callback` (`agents/memory/manager.py`, the **synchronous** API — it runs on a loop-less debounce thread); suggestions via `run_oneshot_llm_with_usage` (`utils/oneshot_llm.py`) from `routers/suggestions.py`; prompt polish the same way from `routers/input_polish.py`; the goal check from `runtime/goal.py::evaluate_goal_completion`, which reads the served model off `response_metadata` (the evaluator usually runs on the configured default, so the requested name is `None`) and normalizes it through `deerflow.model_ids` like every other reader of a provider-reported id. Async callers go through `arecord_aux_usage_metadata` / `aget_thread_aux_usage`, which offload the file IO |
| Frontend                                                                                                               | `token-usage-indicator.tsx` renders the green cost (plus the red standard rate and its legend while a promo is live) + `?` tooltip + aux rows + the unpriced-model note; `core/threads/token-usage.ts` (`threadTokenUsageToCostSummary`, `formatCost`); both chat pages pass the summary; i18n `tokenUsage.cost` / `costHint` / `unpricedOnly` / `unpricedPartial` / `promoRate` / `standardRate` / `memory` / `suggestions`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

**Cost per step — which turn got expensive.** The totals answer "what has this conversation cost". They structurally cannot answer _which turn_ cost it, which is the question a thread that switches models mid-conversation actually raises. A small chart in the cost dropdown does, with a toggle between the two readings:

- **x axis = steps.** One step is one completed run — a user message and the answer to it — numbered from 1 in the order the conversation happened, not in whatever order a store returned the rows. A resumed or replayed run can land in the thread index out of order, so both stores sort by `created_at` explicitly (pinned by `test_runs_recorded_out_of_order_are_still_chronological`).
- **Two modes, and the form changes with them, because the job does.** _Each step_ is a magnitude comparison across discrete turns → **columns**. _Running total_ is a trend → a **line with an area wash**. Drawing a running total as columns would imply each bar is an independent quantity; drawing discrete turns as a line would imply the cost moved continuously between them. The last cumulative point equals the headline total by construction — pinned by `test_steps_sum_to_the_thread_total` (backend) and `the last cumulative value equals the thread total` (frontend), because a chart that disagrees with the number printed directly above it is worse than no chart. The one thread where those two numbers legitimately differ is one whose turns have been **replaced** by an edit; there the identity becomes _chart + replaced = total_, and the header prints the replaced figure between them so the difference is named rather than discovered (see _Three things a real conversation does to the estimate_ below).
- **A step is priced exactly the way the thread is** — each model in that run at its own rate, through the same `lookup_pricing` / `token_cost` helpers. An Ultra-mode step whose subagent ran on a cheap model is not billed at the lead's rate, and the promo basis follows the same rule as `promo_total_cost`: null when nothing in the step is discounted, so the UI never prints the same number twice in two colours.
- **An unpriced step is a gap, not a zero.** A local Ollama turn draws no column at all. A bar on the floor reads as "this turn was free", which is a different claim from "nothing could price this turn". The _cumulative_ series treats it as contributing nothing, so the running total stays flat across it — matching the thread total, which also skips unpriced models.
- **The y axis always starts at zero.** A non-zero baseline exaggerates the difference between turns, which is the standard way a spend chart misleads. Pinned by `the y scale starts at zero so near-identical turns look near-identical`.
- **No charting dependency.** The chart is hand-rolled inline SVG: the repo enforces route asset budgets (`pnpm perf:check`), and pulling in a charting library for one 64px sparkline would spend that budget badly. The geometry lives in `core/threads/cost-chart.ts`, separate from the component, so the maths is unit-testable — an off-by-one in a scale is invisible at that size but makes the chart lie about money.
- **One series, so no legend; one direct label, not a number on every point.** Per-step labels the most expensive turn, cumulative labels where the total ended. The series colour is emerald-600 (`#059669`) rather than the emerald-500 used for the cost text: 600 is the step that passes the lightness band, chroma floor, and 3:1 contrast against **both** the light and dark chart surfaces, so one validated step serves both themes with no theme-conditional colour.

**Three things a real conversation does to the estimate.** A cost number is only worth showing if it still tells the truth after the conversation has been lived in. Three ordinary events break a naive implementation, and each one is now pinned by `backend/tests/test_thread_cost_robustness.py`:

- **The Gateway restarts, or you press stop, or a run times out.** Those tokens were already sent to the provider and already persisted — the journal flushes a per-model progress snapshot while the run is alive, and the worker writes the final one whatever status the run ends in. But the aggregation counted only `success` and `error`, so a restart **deleted money from the header**: `RunManager.shutdown` marks every in-flight run `interrupted`, and an interrupted run's spend simply stopped existing. Worse, it stopped existing _only there_ — `resolve_spend_budget_status` and the spend console price every run row in the window regardless of status, so the same tokens kept counting against the currency cap shown two lines below the total that had just forgotten them. The counted set is now one shared constant, `runs/store/base.py::COUNTED_RUN_STATUSES` (`success`, `error`, `timeout`, `interrupted`), used by both stores; `pending` stays out because a queued run that never reached a model has nothing to count, and `running` stays opt-in behind `include_active`. Two tests keep the set honest as the lifecycle grows: one asserts every `RunStatus` member is either counted, active, or explicitly `pending` — a new status cannot join the enum and silently fall out of the bill — and one asserts every terminal status the spend cap charges for also reaches the header.
- **The model changes mid-conversation**, which is the entire point of a deployment that mixes premium, cheap, and local models. This already worked — each run carries its own `token_usage_by_model` split and each turn is priced at the rate of the model that ran it — and is now pinned per-turn as well as per-thread, together with the realistic way a historical thread loses its price: a model **removed from `config.yaml`** later on. That turn draws no column (a gap, not a zero), the total keeps every turn it can still price, and `unpriced_models` names the one it cannot.
- **You edit an earlier message.** Editing supersedes the turns that followed it, and the transcript stops showing them — but the money was spent, and a total that shrank when you edited a message would be a lie about the bill. So the spend **stays in `total_cost`**, and what changes is where it is drawn: those runs are no longer turns of the conversation, so they are no longer steps of the chart. Leaving them in was the actual defect — the chart showed more steps than the thread had turns, and "step 3" was not the third thing the user asked, silently, with no way to tell replaced work from real. The endpoint now asks the same visibility rules the message history uses (`_default_history_hidden_run_ids`: edit sources, failed edit attempts, superseded regenerations), drops those runs from `steps[]`, renumbers what is left so step _n_ is the _n_th visible turn, and reports the discarded spend once as `superseded_cost` / `superseded_promo_cost` / `superseded_tokens` / `superseded_runs`. The header renders it as a **Replaced turns** row between the total and the chart — the two numbers it reconciles — with a tooltip saying why it is inside one and outside the other. `null`, not `0.0`, when nothing was replaced, so an unedited conversation gets no row rather than a permanent "$0.00 replaced". The lookup is wrapped: a run manager that is missing or throwing degrades to charting every run, because a broken counter must never take down the counter it is counting.

**Where the per-step data comes from.** `aggregate_tokens_by_thread` gained a `by_run` list beside `by_model` — one entry per completed run, oldest first, each keeping its own per-model split. Both stores build it through the shared `new_per_run_usage_entry` / `add_per_run_model_usage` helpers in `runs/store/base.py` so the memory and SQL aggregations cannot drift (pinned by `test_memory_and_sql_stores_agree_on_by_run`). The endpoint turns that into `steps[]`; a store that predates the field degrades to an empty chart rather than an error.

**Verify it works.** The pricing math and the endpoint are both offline-testable, so the backend tests are the fast gate:

```bash
cd backend && uv run pytest tests/test_pricing.py tests/test_thread_token_usage.py tests/test_aux_usage.py tests/test_aux_usage_wiring.py
cd backend && uv run pytest tests/test_thread_step_costs.py   # per-step costs: ordering, per-model pricing, promo basis, store parity
cd backend && uv run pytest tests/test_thread_cost_robustness.py  # RUN THIS FOR ANY PRICING/RUN-STORE CHANGE: restart, mid-thread model switch, edited message
cd backend && uv run pytest tests/test_input_polish_router.py tests/test_suggestions_router.py   # the two composer sinks' routes
cd backend && uv run pytest tests/blocking_io/test_aux_usage.py   # the durable aux store's IO stays off the event loop
make doctor      # 'model pricing' names the symptom when nothing configured can be priced
cd backend && uv run pytest tests/test_config_integrity.py -k BundledModelPricing   # every model priced; name pair == pricing block; promo pair == promo block
cd frontend && pnpm test token-usage                                                 # cost summary incl. promo + aux promo collapse + replaced-turn spend
cd frontend && pnpm test cost-chart && pnpm test cost-per-step-chart                  # chart geometry + the per-step/cumulative toggle
```

Then in the browser (`make dev` → open a chat that has run at least one turn): the header pill shows a **green** dollar amount; opening it shows **Estimated cost** in green, the **Cost per step** chart beneath it (switch the toggle and confirm the columns give way to a rising line whose end label matches the total above), and — if any model in the thread is currently discounted — a red standard total beside it with the `promo rate now` / `standard rate` legend. Run an **Ultra-mode** turn with the subagent set to a discounted model (MiniMax M3 is the only one currently discounted) and a full-price lead: the gap between the two totals should equal the subagent's saving only. Memory/suggestions rows are green and priced per their own model. Press the composer's **polish** button once and confirm a **Prompt polish** row appears (it is on by default, so this is the row most installs will actually see), and set a goal on the thread to get a **Goal check** row. **Then restart the Gateway** (`make stop && make dev`) and reopen the same thread: every auxiliary row must come back with the same totals — that is the durability half, and it is the one thing a unit test cannot show you end to end. `<DeerFlow home>/aux_usage.sqlite3` is the file behind them.

**Durable auxiliary counters.** The memory and suggestions counters used to be process-local and reset on every Gateway restart. That was fine for a display counter and a bad foundation for a budget or a spend report, so they are now persisted.

- **Where.** `runtime/aux_usage_store.py`, a small dedicated SQLite file at `<DeerFlow home>/aux_usage.sqlite3` (default `backend/.deer-flow/`). Set `DEER_FLOW_AUX_USAGE_DB=<path>` to move it, or `DEER_FLOW_AUX_USAGE_DB=0` to go back to the old process-local counter.
- **Why a dedicated store and not the runs DB.** Memory usage is recorded from the memory updater's debounce worker — an ordinary `threading.Timer` thread with **no event loop** — and the application database is an async SQLAlchemy engine bound to the Gateway's loop. Reaching it would need a queue drained by that loop, which only works while a Gateway is running and loses whatever has not drained at shutdown. A plain `sqlite3` connection is usable from any thread, so one code path serves the Gateway, the embedded client, and the TUI; it commits where the call happens (nothing to lose on a hard crash); it needs no synchronous Postgres driver and no alembic revision; and aux usage has no foreign key into `runs`, so co-locating it buys nothing.
- **The in-memory registry is still there, as a write-through cache**, hydrated from the store on a thread's first touch — so the header keeps reading from memory. The LRU cap (4096 threads) now evicts _cache entries_ rather than data: an evicted thread re-hydrates on its next touch.
- **Rows are append-only events with a `recorded_at`**, so a later spend window or attribution report can slice by date without a schema migration.
- **It is best-effort.** A store that cannot be opened or written logs one warning and the counter falls back to process-local for that run; memory extraction and chat responses are never disturbed.
- **Blocking IO.** The store is a local file, so `record_aux_usage` / `get_thread_aux_usage` touch the disk. They are safe from any thread (that is the point) but not from the event loop; async callers use `arecord_aux_usage` / `aget_thread_aux_usage`, pinned by `backend/tests/blocking_io/test_aux_usage.py`.
- **Multi-worker caveat.** The cache is per process, so with several Gateway workers one worker's header can lag a sibling's aux writes until that thread re-hydrates (restart or LRU eviction). The persisted totals are always complete; only a cached view can be behind. The fork's target is a single-process personal deployment.

**Caveats (deliberate).** Cost reflects **persisted runs only** (in-flight stream deltas aren't priced until the run completes). All priced models must share one currency (mixed currencies disable cost, same rule as the console).

**Tests (does it calculate correctly?).**

- `backend/tests/test_pricing.py` — the pricing math end-to-end: per-million pricing, cache-hit vs miss, the multi-model (subagent) run cost, unpriced/zero-priced skipping, and the mixed-currency guard. Also pins the **provider-reported id resolution** that made the header show `—`: Anthropic dated snapshots, OpenAI dashed-date and Vertex `@date` suffixes, OpenRouter `:variant` tags, a routed slug falling back to a direct entry, a configured routed copy still winning over that direct entry, sibling models never inheriting each other's rate (`claude-opus-4-8-…` vs `claude-opus-5`), an unconfigured/local id still resolving to `None`, and candidate ordering. `TestPricingDerivedFromDisplayName` covers the fallback that reaches existing installs — derivation from the name, the promo pair and Anthropic cache rate carried through, an explicit block always winning, a malformed explicit block _not_ falling back, an unpriced name (Ollama, bare version numbers) staying unpriced, and a cross-check that the derived figures equal what `providers.py` generates for every bundled shape. `TestPromoPricing` covers the additive discount: promo rates exposed as a standalone `ModelPricing`, promo cache-hit accounting, `run_cost` still billing the standard rate, and every way an invalid promo (half-specified, malformed, zero/negative, above list) is dropped **whole** while the standard price survives.
- `backend/tests/test_aux_usage.py` — the registry: accumulation, category/model/thread isolation, deep-copy reads, the LRU cap, and thread-safety under concurrent writers. Plus **durability**: totals identical across a simulated restart (`reset_aux_usage_cache()` drops the cache and store handle, keeps the file), a post-restart write extending the hydrated totals instead of replaying them, a read miss never taking an LRU slot, an evicted thread re-hydrating rather than losing data, a second reader of the same file seeing the same totals, the `DEER_FLOW_AUX_USAGE_DB=0` kill switch restoring the old process-local behaviour, an unusable store degrading to the cache with exactly one warning, path resolution (default/disabled/explicit), the SQLite store's own aggregation, and the async wrappers.
- `backend/tests/test_aux_usage_wiring.py` — every sink actually records into the registry: memory (`_host_default_extraction_callback`), suggestions (`_record_suggestions_usage`), **prompt polish** (driven through the real `polish_input` route, asserting the bucket is keyed on the _provider-reported_ id rather than the configured override, that a draft polished before the thread exists records nothing, and that a broken counter still returns the rewrite the user has already paid for), and the **goal** check (through the real `evaluate_goal_completion`, including a stream-doubled reported id being collapsed before it can price at zero). Then all four through one simulated restart. The two new sinks' tests are the ones that go red if their `arecord_aux_usage_metadata` call is removed, while every other test in the suite stays green — which is the failure mode being pinned: silent under-counting, not an error. Plus the shared `usage_metadata_kwargs`: the nested `input_token_details.cache_read` survives, a non-mapping `usage` means "nothing to record" rather than a crash, and a missing details block reads as zero.
- `backend/tests/blocking_io/test_aux_usage.py` — the strict Blockbuster anchor: `arecord_aux_usage` / `aget_thread_aux_usage` must offload the store's SQLite IO, so pointing the suggestions route or the `token-usage` endpoint back at the synchronous registry API fails CI instead of quietly stalling the event loop on every answer.
- `backend/tests/test_thread_token_usage.py` — the endpoint computes model-aware `total_cost`, per-model cost, and priced/unpriced `aux` counters (a worked example: Opus lead + cheap subagent + memory-on-unpriced + suggestions-on-priced), and nulls everything when no pricing is configured. `test_every_chat_aux_sink_is_priced_at_its_own_model` is the whole "what has this chat cost me" picture in one thread — lead, a subagent on a different model, and all four auxiliary sinks — asserting each is billed at the rate of the model that actually served it, which is what makes the _"point `input_polish.model_name` at your cheapest model"_ advice visible as a saving rather than smeared across the lead's rate. `test_aux_sinks_survive_a_gateway_restart_at_the_endpoint` drives durability through the **real endpoint**; note that it has to set `DEER_FLOW_AUX_USAGE_DB` to a per-test file, because `conftest` points the store at `0` (durability off) to keep the rest of the suite off the disk — without that override the test passes for the wrong reason, an empty registry equalling an empty registry. `test_cost_tracks_model_switching_across_turns` pins the **"as the conversation goes on" property**: three turns on three different priced models (Opus → Sonnet → Haiku) drive the _real_ cross-run per-model store aggregation through the _real_ pricing helpers, asserting the cumulative cost is the sum of each turn billed at the model that actually ran it — no turn's tokens cross-attributed to another model's rate. `test_thread_token_usage_prices_provider_reported_model_ids` is the end-to-end regression for the `—` bug: it drives the **real endpoint** over the ids providers actually report (dated Anthropic snapshots plus an OpenRouter `:variant` slug) across a mid-conversation model switch and asserts a non-null cumulative cost — so a regression in the id resolution fails at the endpoint, not only in the pricing unit tests. Five further tests pin `promo_total_cost`: a mixed thread (one discounted model + one full-price) where the promo total bills the undiscounted model at its ordinary rate; null on both the no-promo and no-pricing-at-all paths; `test_promo_total_is_model_aware_across_lead_subagent_and_aux`, the Ultra-mode shape — full-price lead (dated Anthropic snapshot) + **discounted subagent** (OpenRouter `:variant` slug) + memory on the discounted model + suggestions on the full-price one, asserting the saving equals the subagent's alone rather than being smeared across the lead's tokens; and `test_unpriced_subagent_model_does_not_break_the_promo_total`, where a local Ollama subagent contributes 0 to both totals and is still named in `unpriced_models`.
- `backend/tests/test_token_usage_by_model.py`, `test_run_repository.py`, `test_persistence_scaffold.py` — updated for the enriched `by_model` shape (now carrying the input/output/cache-read split). `test_token_usage_by_model.py` also pins the store's cross-run merge when the lead model changes between turns, and memory/SQL-store parity (`test_memory_and_sql_stores_agree`).
- `backend/tests/test_thread_cost_robustness.py` — **the file to run and to extend whenever anything touching pricing, the run stores, or the token-usage endpoint changes.** It is organised as the three events above, and each section fails for a distinct reason: (1) an `interrupted` or `timeout` run keeps its spend in the total and is priced like any other turn, a `pending` run adds nothing, the SQL and memory stores agree on all of it, every `RunStatus` is deliberately counted or excluded, and the counted set covers everything the spend cap charges for; (2) a mid-thread model switch prices each turn at the model that ran it, and a model later dropped from `config.yaml` is named in `unpriced_models` while the rest of the total survives; (3) a replaced turn stays in `total_cost`, leaves `steps[]`, renumbers the survivors, and is reported as `superseded_cost` — with `sum(steps) + superseded_cost == total_cost` asserted directly, failed edit attempts and superseded regenerations both counted as replaced, an unedited thread reporting `null` rather than `0.0`, and both degradation paths (no run manager, and a visibility lookup that throws) charting every step instead of failing the request.
- `frontend/tests/unit/core/threads/token-usage.test.ts` — `threadTokenUsageToCostSummary` (null without currency, drops zero-token aux rows, carries `promoTotalCost` and nulls it when absent **or** equal to the standard total), the replaced-turn fields (the summary carries them beside the total, `charted + replaced == total`, an unedited thread reports null, and a replaced-turn promo equal to its standard rate collapses to null like every other pair), and `formatCost` (sub-cent precision, malformed-currency fallback).

### 8. Sortable / groupable model dropdown

The model picker can be **sorted by name or by price**, ascending or descending, and optionally **grouped by provider** (Anthropic / OpenRouter / Ollama). With a couple of dozen bundled models across premium cloud, cheap cloud, and local tiers (§2), the flat config-ordered list is hard to scan — this lets you line the models up by cost or name, or collapse them into provider sections, in one click.

- **Where the data comes from.** Price is a structured field on `/api/models` (§17): the server resolves it through `deerflow/pricing.py` and returns it with any discount already expiry-filtered, so the picker cannot advertise a promotion that has ended. `core/models/sorting.ts::resolveModelPrice` prefers that field and `modelNameSegments` renders it as the same coloured pair the old embedded text produced. Provider is still parsed from the `(Anthropic)`/`(OpenRouter)`/`(Ollama)` suffix by `parseModelProvider`. The display-name price parser (`parseModelPrice`) is retained as the fallback for a config written before prices moved into their own field, and for hand-added models that follow the old convention; an unpriced model sorts last and an unknown suffix groups under "Other", so the parse still degrades gracefully rather than throwing.
- **The price is coloured in the list.** `modelNameSegments` composes the name and the entry's `price:` field (§17) into text and price runs so `ModelDisplayName` can paint the price green (`text-emerald-500`) — the money in a wall of model ids, matching the header's cost figure. A discounted entry gets both halves coloured: the **promo** green (what you pay now) and the **list** price red (`text-red-500`, what it reverts to), the same green/red pairing the cost overview uses in §7. `splitModelNamePriceSegments` remains underneath as the **legacy** path, splitting the pair out of a `display_name` for configs written before §17 (and stripping an embedded copy when a model has both, so the price is never rendered twice). It is purely presentational and total: a model with no resolvable price renders verbatim as one text segment, and the segments always rejoin to the original string, so no model can lose characters to the split. Used by all three pickers (lead, subagent, sidecar) in both the trigger label and the list row.
- **The collapsed trigger keeps the price, not the provider.** The composer's model button is capped at `max-w-40` / `sm:max-w-56`, and the price sits in the _middle_ of a bundled name, so the promo half — the number you most want — was the first thing lost. Two changes fix it, and both are needed. (1) `compactModelDisplayName` drops trailing non-price groups (`(OpenRouter)`, `(Anthropic)`, and each lab's own home suffix) while keeping the `(p)` privacy marker, which is worth more at a glance than the provider and was previously truncated away first; the full name stays on hover via `title` and in the open list. (2) `ModelDisplayName variant="compact"` lays the segments out so only the **leading model name** may ellipsize — the price pair and `(p)` are `shrink-0`. **The host `ModelSelectorName` must carry `w-full`**, which is the actual pre-existing bug: it sits in a `flex-col items-start` container where its own `flex-1` sizes the _cross_ axis (height), so it defaulted to `fit-content`, rendered **past** the capped button, and its `truncate` never fired at all. Measured in Chromium: a bundled promo name is 315px inside a 160px button; with `w-full` it is bounded to 142px and both prices stay visible at `max-w-40` and `sm:max-w-56` alike. If a trigger ever shows a clipped price again, check that `w-full` is still on all three `ModelSelectorName` triggers before touching the segment logic.
- **A row is three columns, not one string: provider, name, price at the edge.** The row used to render one `display_name` — `Claude Sonnet 5 (Anthropic) ($3/15)` — so the one number worth comparing across two dozen models landed wherever each name happened to end, and no two rows lined up. `modelRowParts` splits what `modelNameSegments` joins: the provider leads (as the **literal** suffix, so `(xAI)` reads "xAI" rather than being collapsed into the four-way sort bucket's "Other"), the name follows, and the price is pinned with `ml-auto`. Only the **name** may ellipsize — provider and price are `shrink-0`, the same rule the compact trigger follows, because a truncated price is worse than a truncated name. The splitter is total in the same way the segment splitter is: `name` is the display name minus exactly the provider group and exactly the price group that were _recognized_, so an unrecognized format is rendered verbatim rather than half-swallowed into `GLM-5.2 ( → )`. Grouped mode drops the per-row provider, which the section heading already carries. The trigger button keeps `modelNameSegments` — one flowing string is the right answer inside 160px.
- **The second line carries what a local model costs you in GPU.** Beside the model id: the weights on disk and the context window the entry was sized for (`qwen3:8b · 5.2 GiB · 32K ctx`), from `size_bytes` (§1) and `context_window` on `/api/models`. Those two are one question — a 20 GiB model and a 32K window do not both fit on a 24 GiB card — and a hosted model, which has neither, shows the id alone rather than empty slots. Sizes are **GiB, not GB**: the number only matters next to `ollama.vram_gb`, which is read as GiB, and quoting the weights base-10 would put the two figures ~7% apart in the one comparison the number exists for.
- **Every picker renders rows through `ModelPickerRow`.** Four sites drew that markup by hand (the composer's two pickers, the sidecar, and `ModelSelect`), which is the same silent drift as the flat-list bug below one level down: a hand-rolled row is not an error, it just lines up with nothing and drops the local model's size on that one screen. `model-picker-sites.test.ts` fails any component that drives `ModelPickerList` without it.
- **What the controls do.** Sort key `Default` (config order, the out-of-the-box default so nothing changes until you opt in) / `Name` / `Price`; a direction toggle (disabled for `Default`); and a **Group by provider** switch. Price sorts on the current **output** price (the dominant cost driver); unpriced models always sink to the bottom in both directions. The subagent picker additionally keeps tool-incapable models last (§3's `(no tool support)` rule) via the sorter's `demoteLast` option, and its "Follow lead" entry stays pinned at the top. While you type in the search box, `cmdk` orders by match relevance (the sort governs the browse order).
- **Where it lives.** The preference (`{ sortKey, sortDir, groupByProvider }`) is persisted **per browser** in `deerflow.local-settings` (`core/settings/local.ts`, `modelPicker`) — shared across threads _and across screens_, unlike the per-thread model selection. Shared UI in `components/workspace/model-picker-controls.tsx` (`ModelPickerControls` + `ModelPickerList` + `ModelDisplayName`). i18n keys live in `core/i18n/locales/{en-US,zh-CN}.ts`.
- **It is the picker _everywhere_ a model is chosen, which it was not at first.** The composer's picker got all of the above; every other screen that selects a model kept a bare Radix `<Select>` listing `config.yaml` order with the price as undifferentiated grey text — democracy mode's panelist and organizer rows, the follow-up **suggestions** model, the **subagent** default in Settings, the **agent generator**, and a custom agent's own model in its settings dialog. That is the difference between picking a model and hunting for one, and **the inconsistency was itself the bug**: the same roster behaved differently depending on which screen you opened it from, and a sort chosen in the chat did nothing in Settings. `components/workspace/model-select.tsx` (`ModelSelect`) is that picker extracted — same `ModelPickerControls`, same `ModelPickerList`, same `ModelDisplayName`, same `modelPicker` preference — and all five sites now use it. **Anything that selects a model uses `ModelSelect`; mapping `models` into `SelectItem`s is how the two behaviours drift apart again.**
  - It is built on `ModelSelector` (a Radix Dialog + a cmdk `Command`), the same primitive as the composer's picker — which is what makes them visually identical, and what lets it nest inside the settings dialog and the agent dialog, both of which already stack dialogs. A `Popover` would have needed a new `@radix-ui` dependency against the route asset budgets `pnpm perf:check` enforces.
  - `options` carries the pinned pseudo-rows every picker has — "Follow lead", "Use the default model", "Inherit". They stay **above** the models under any sort or grouping, because each is the _absence_ of a choice; sorting one in among the models by name or price would be meaningless.
  - Democracy's panelist list previously pre-sorted through `sortModelsByToolSupport`. A pre-sorted array is silently discarded by a picker that re-sorts what it is handed, so that ordering is now `demoteLast={lacksToolSupport}` — the same option the composer's subagent picker uses. `sortModelsByToolSupport` had no remaining caller and was deleted along with its tests.
  - The literal `(no tool support)` annotation was hardcoded in two places in `input-box.tsx`; it is now `t.inputBox.noToolSupport`, so all three tool-aware pickers annotate identically and the string is translated.
- **A picker is found in a test by `data-slot="model-select"`, never by an ARIA role.** This one was learned the expensive way. The e2e specs located these pickers with `getByRole("combobox")` — the role of whatever primitive happened to be underneath, which was Radix `Select`. Replacing that primitive with the dialog + cmdk picker deleted the role, and `suggestions-settings.spec.ts` died on a 30-second timeout against a locator matching nothing. **Nothing in the product was broken**: the spec was coupled to an implementation detail of a component it did not own, and it went red only in CI, after review. `ModelSelect` therefore publishes its own contract — a `data-slot` that is present regardless of what the picker is built from — and every spec targets that. Democracy's _grading_ dropdown is still a real `<Select>` and legitimately still uses the `combobox` role; the rule is about model pickers.
  - `frontend/tests/unit/components/workspace/model-picker-sites.test.ts` is the guard, and it is deliberately a **unit** test: it fails in milliseconds where the e2e job takes six minutes to report the same thing. It pins both directions — the `data-slot` contract cannot be dropped from the component, no e2e spec may drive a model picker by the `combobox` role, each of the five converted sites still imports `ModelSelect`, and no component anywhere under `src/components` may map `models` into `SelectItem`s. Verified by breaking each: removing the `data-slot` fails one test, reverting the suggestions page to a flat `<Select>` fails two.

Pinned by `frontend/tests/unit/core/models/sorting.test.ts` (price/provider parsing incl. the promo pair and bare-version-number guard, name/price/default sorting, unpriced-last, `demoteLast`, provider grouping, `splitModelNamePriceSegments` — single vs. promo pair, the exact-reassembly property, no-price and empty names, and no shared regex state between calls — and `compactModelDisplayName` — provider suffix dropped, `(p)` kept, the price group never stripped, first-party home suffixes handled without a hardcoded list, a name that would compact to nothing returned whole, and the promo pair surviving in all three legacy-format names it is fed — those strings are pre-§17 fixtures for the display-name path, not the current bundle, where only MiniMax M3 is discounted and no name carries a price at all). The _layout_ half (does the price actually stay on screen?) is CSS, so no unit test covers it — it was verified by measuring the real cascade in Chromium, and the `w-full` note above is the regression guard.

**Verify it works.** The parsing/sorting/grouping is pure logic, so the unit test is the fast gate:

```bash
cd frontend && pnpm test sorting              # sorting.test.ts: parse price/provider, sort, group, demoteLast, price-segment split, compact trigger name
cd frontend && pnpm test model-select         # model-select.dom.test.tsx: the shared picker renders the controls, honours the shared preference, pins pseudo-options, colours the price
cd frontend && pnpm test model-picker-sites   # the structural guard: the data-slot contract, no combobox-role locators, every site on ModelSelect and ModelPickerRow, no flat lists
cd frontend && pnpm test:e2e suggestions-settings democracy-panel   # the two specs that actually click a converted picker
```

Then check the wiring end-to-end in the browser (`make dev` → open a chat): the model dropdown shows a **Sort** toggle (`Default` / `Name` / `Price`), a direction button (disabled on `Default`), and a **Group by provider** switch. `Price` orders by the current (promo-aware) output price with local/unpriced models last; `Group by provider` splits the list into Anthropic / OpenRouter / Ollama sections. Each row's price is green, and a discounted model (MiniMax M3, Claude Sonnet 5) shows its list price red beside the green promo. **Select one of those three and close the dropdown**: the collapsed button must still show both prices (the provider suffix is dropped to make room; hover for the full name). Check it at a narrow window width too — that is where it used to clip. Read a row left to right: the provider, then the name, then the price **against the right edge** — scan down and the prices form a column. With a local model installed, its row's second line reads `<id> · <weights> · <window> ctx`; a cloud model's shows the id alone. Turn **Group by provider** on and the per-row provider disappears (the heading says it). The choice persists across reloads and threads (`deerflow.local-settings → modelPicker`). Confirm the same controls appear in the **Ultra-mode subagent** picker (no-tool models still sink to the bottom, "Follow lead" stays pinned) and the **sidecar** picker.

**Then leave the chat**, because that is the half that used to be missing. With a sort still selected, open each of these and confirm the _same_ dropdown — search box, Sort toggle, Group-by-provider switch, coloured prices, and the sort you just picked already applied: **Democracy** setup (both the organizer row and each panelist row; a no-tool model must sink to the bottom of a panelist list), **Settings → Suggestions** ("Follow the workflow's model" pinned at the top), **Settings → Subagents** → edit a subagent ("Inherit" pinned, no-tool models demoted and annotated), **Agents → Generate from history**, and a custom agent's **settings dialog** (both pin "Use the default model"). A bare grey list on any of them means that site was added without `ModelSelect`. Full frontend gate: `pnpm check && pnpm test`.

### 9. Browser-style keep-alive chat tabs

Upstream shows one live chat at a time: the sidebar lists your conversations, and clicking one navigates the single content pane — switching away tears the previous chat down (its stream, scroll position, and artifact panel are gone until you come back and reload). This fork adds a **browser-style tab strip** above the chat: drag a few conversations from the sidebar onto it (or use a row's **Open in tab** menu, or the strip's pin button) and they become **keep-alive tabs** that stay mounted and running as you switch between them — a background tab keeps streaming, keeps its scroll, and keeps its artifacts/browser panels.

- **What "keep-alive" means here.** The live chat was lifted out of the route into a persistent, workspace-level viewport (`keep-alive-chat-viewport.tsx`) mounted **above** the Next route, so navigating between chats never unmounts them. It renders one chat instance per pinned tab plus one for the current unpinned chat, and only the active one is shown — `display:none` on the rest keeps React state, DOM scroll position, and the SDK stream alive. Pinned tabs survive navigating to other workspace pages too (the whole viewport is just hidden). Switching tabs uses `history.replaceState`, not the Next router — the same reason the chat page already avoids the router on new→real, so nothing remounts.
- **Curated, reorderable, persisted.** Tabs are an explicit set you build by dragging from the sidebar (native HTML5 drag-and-drop) or the row's **Open in tab** action, reorder by dragging chips, and close with a chip's ✕. The current unpinned chat shows as a dashed "preview" chip with a pin button.
- **Persisted server-side, per user — the tab set survives a machine restart.** `localStorage` alone was not enough and lost people's tabs: it is scoped to one browser _and_ one origin, so the set disappeared whenever the browser cleared site data on exit, evicted storage for an insecure-origin site (a plain-HTTP LAN deployment — the setup this fork documents), or the app was reopened on a different origin than the one that pinned them (`localhost` vs. a LAN/Tailscale address both reach the same server, with entirely separate stores). The durable store is `{base_dir}/users/{user_id}/ui_state.json` — a small per-user JSON bag beside the server-wide `runtime_settings.json`, written atomically, merged rather than replaced (so later per-user UI state can join it), and cached on the file's `(mtime, size)` so a sibling worker's write is picked up without a restart. It is exposed as `GET`/`PUT /api/settings/chat-tabs`, scoped to the calling user; unlike the multi-user-mode routes beside it there is **no admin gate**, because this is per-user UI state rather than a server-wide setting. The store validates, dedupes and caps the list exactly as the frontend model does, since the API is untrusted input.
- **`localStorage` is now a first-paint cache, not the source of truth.** The provider renders from it immediately, then reconciles: an unreachable gateway — the normal state right after a machine restart, when the browser reopens the app before the backend is up — **keeps the cache** rather than blanking the strip, and a server with no stored set **adopts the local one and seeds the server** (the upgrade path for tabs pinned before this existed). Writes back are coalesced and flushed on teardown/`pagehide`, so a browser tab closed right after a pin still records it. The local cache additionally refuses to write an empty set over a stored one unless a user action produced it: on the gateway-offline boot the provider starts on the `…anonymous` key (SSR has no user) and flips to the real one when the offline banner's probe resolves, and because the hydrate and persist effects run in the same commit the persist effect can still observe the pre-hydration `[]`.
- **The strip is always a drop target (even empty).** The whole point is to drag chats _up_ onto the strip, so it must be visible before the first tab exists — otherwise there is nowhere to drop. On a brand-new chat with no tabs yet the strip therefore renders an **empty drop zone** with a hint ("Drag a chat here to keep it open as a tab") instead of collapsing to nothing; dragging a sidebar chat onto it pins the first tab and the hint disappears. The strip hides only when there is nothing to drag at all (a fresh install with no chat history) and, like the pinned instances, on non-chat workspace pages. This was the bug behind "the tabs don't work": the empty strip used to return `null`, so a user landing on the default new-chat page had no visible place to drag onto.
- **The single chat is now a reusable, controlled component.** `[thread_id]/page.tsx`'s body became `chat-instance.tsx` — **fully controlled** (the owner owns `threadId`/`isNewThread`; the instance reports its new→real promotion up) and wrapping its own provider stack with a per-instance `storageScope` so several artifacts panels never collide on one pathname. In app builds the route page is a thin **registrar** that reports the route to the tab strip and renders nothing; in **static-demo** builds the feature is off and the page renders the classic inline chat (the demo pre-renders these pages and enforces route asset budgets). Custom-agent chats keep the classic single-chat rendering.
- **Metadata revalidates on foreground, because nothing remounts to do it.** The classic single pane refetched a thread's metadata (`useThreadMetadata` — title, goal) every time you navigated back to it, because the page remounted. Keep-alive keeps the instance and its query mounted, so that free refresh disappeared: a kept-alive thread's title/goal would freeze at first-load and only a full reload picked up a change made elsewhere (a rename in another tab, another client). `chat-instance.tsx` restores it explicitly — a background refetch fired when a slot returns to the foreground (`isActive` transitions false→true, skipping the first mount, which the query already fetches). It is a background revalidation, so the cached value stays on screen while it runs (the header's `canonicalTitle` never blanks). This is also what makes the upstream title-sync race spec pass under keep-alive — see the post-sync checklist's e2e-collision note.

**Where it's wired.**

| Piece                                                                                 | Location                                                                                                                                                                                                                   |
| ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pure tab model (pin/close/reorder/promote, local-cache serialization, DnD MIME types) | `frontend/src/core/threads/chat-tabs.ts`                                                                                                                                                                                   |
| Durable per-user store + API                                                          | `backend/packages/harness/deerflow/config/user_ui_state.py` (`get_chat_tabs` / `set_chat_tabs` / `normalize_chat_tabs`, `ui_state.json`); `GET`/`PUT /api/settings/chat-tabs` in `backend/app/gateway/routers/settings.py` |
| Durable-store client                                                                  | `frontend/src/core/threads/chat-tabs-api.ts` (`fetchChatTabs` returns `null` for "unknown" — distinct from "no tabs" — so an unreachable gateway never blanks the strip)                                                   |
| Tab state + active-slot coordination + server reconciliation                          | `frontend/src/core/threads/chat-tabs-context.tsx` (`ChatTabsProvider` / `useChatTabs`)                                                                                                                                     |
| Persistent viewport + tab strip                                                       | `frontend/src/components/workspace/chats/keep-alive-chat-viewport.tsx`, `chat-tabs-bar.tsx`                                                                                                                                |
| Extracted controlled chat + its providers                                             | `frontend/src/components/workspace/chats/chat-instance.tsx`, `chat-providers.tsx`                                                                                                                                          |
| Route registrar / classic fallback                                                    | `frontend/src/app/workspace/chats/[thread_id]/page.tsx`                                                                                                                                                                    |
| Shell mount + sidebar drag/menu                                                       | `frontend/src/app/workspace/workspace-content.tsx`, `components/workspace/recent-chat-list.tsx`                                                                                                                            |
| i18n                                                                                  | `core/i18n/locales/{en-US,zh-CN}.ts` (`chatTabs.*`)                                                                                                                                                                        |

Pinned by `frontend/tests/unit/core/threads/chat-tabs.test.ts` (the pure model) and `frontend/tests/e2e/chat-tabs.spec.ts` (drag-from-sidebar onto the empty strip, drag-reorder between chips, open-as-tab via the row menu, keep-alive switch with both instances left mounted, close, reload persistence). The two drag tests drive native HTML5 drag-and-drop directly (`html5DragAndDrop` shares one `DataTransfer` across the source's `dragstart` and the target's `dragover`/`drop`), since Playwright's mouse-based `dragTo` does not fire the HTML5 DnD events the handlers listen for.

Durability is pinned separately, because the pure model cannot see it:

- `backend/tests/test_user_ui_state.py` — the store: round-trip across a **cold cache** (the "survives a restart" property), per-user isolation, an explicit empty set persisting, malformed/duplicate/oversized input degrading rather than raising, a corrupt file degrading to empty, unrelated keys preserved on write, atomic write leaving no temp file, and an out-of-band edit being picked up.
- `backend/tests/test_chat_tabs_settings_router.py` — the routes: round-trip, normalization/caps as the authoritative post-write state, explicit clear, per-user scoping, and an email-shaped identity not breaking per-user path resolution.
- `frontend/tests/unit/core/threads/chat-tabs-persistence.dom.test.tsx` — the provider's boot path: the gateway-offline boot and the `…anonymous → …default` storage-key flip never blanking the stored set, adopt-from-server on an empty browser, **unreachable gateway keeping the local cache**, seed-the-server from a local cache when the server has none, and mutations being pushed (including an explicit clear) with the debounced write flushed on teardown.

**Verify it works.**

```bash
cd frontend && pnpm test chat-tabs        # pure model + the boot-path/durability DOM tests
cd frontend && pnpm test:e2e chat-tabs    # real DnD from the sidebar + reorder + keep-alive + persistence
cd backend && uv run pytest tests/test_user_ui_state.py tests/test_chat_tabs_settings_router.py
```

Then end-to-end (`make dev` → land on a new chat): the empty tab strip with its drop hint is already visible; drag a sidebar conversation onto it (or use its **Open in tab** menu) → it becomes a tab and the hint disappears; open a second; switch between them and confirm the background chat keeps its scroll and stream (both instances stay in the DOM, only the active one is visible); drag one chip onto another to reorder; close a chip; reload and confirm the tabs come back. Full frontend gate: `pnpm format && pnpm check && pnpm test`.

### 10. Currency spend caps (`spend_budget`)

§7 made cost **visible**. This makes it **bounded**: a cap in real money over a
day, week, or month, in whatever single currency your `models[*].pricing` blocks
use.

Upstream's `token_budget` does not fill this hole. It is per-run and counted in
tokens, and in a fork whose premise is mixing Opus, Haiku and free local Ollama
in one session a token is not a unit of cost — 200k tokens is $5 or $0 depending
on which model burned them. So `spend_budget` mirrors `token_budget`'s shape
(`enabled`, limits, `warn_threshold`, `hard_stop_threshold`) and changes the
unit:

```yaml
spend_budget:
  enabled: true
  daily_limit: 5.00 # in the pricing currency
  weekly_limit: 25.00
  monthly_limit: 80.00
  window: rolling # or `calendar` (since local midnight / Monday / the 1st)
  tz_offset_minutes: 0 # local offset for `calendar` boundaries
  warn_threshold: 0.8
  hard_stop_threshold: 1.0
```

- **Two enforcement points, one number.** At **run admission** the Gateway sums
  the window and refuses a new run with **HTTP 402** when a cap is already spent
  (`Spend budget exhausted: the daily cap of 5 USD is already at 5.12 USD…`).
  **During a run**, `SpendBudgetMiddleware` — modelled directly on
  `TokenBudgetMiddleware` — injects an in-context warning at `warn_threshold` and
  at `hard_stop_threshold` strips tool calls so the agent produces a final answer
  from what it has. It never raises; a budget stop is an orderly wrap-up. The
  admission check also hands the run its window **baseline**, and the middleware
  adds the live run's own spend on top, so one long run cannot blow through a cap
  it started just under.
- **Billed per model, so the fork's own lever shows up.** In-run spend is read
  from the `RunJournal`'s live per-model accumulator (a new
  `current_token_usage_by_model()`), which already folds subagent usage in by
  model. A premium lead with Haiku or local subagents is therefore billed
  Opus-for-Opus and Haiku-for-Haiku, exactly like the header. Without that, a
  cheap subagent would be billed at the lead's rate and a cap would fire early on
  precisely the configuration this fork recommends.
- **Unpriced models cost 0, so a local run is never blocked.** This is a hard
  requirement, not a side effect of a sparse pricing map: the whole point of
  local models is that they are free, and a spend cap that stops a fully local
  session would break the fork's central promise.
- **What counts.** Persisted run costs **plus** the durable memory/suggestions
  counters from §7 — those are real money and would otherwise be invisible to a
  budget. Both are priced through the one shared pricing module.
- **It self-disables rather than guessing.** With **no model priced**, a currency
  budget has nothing to measure, so the feature turns itself off with a reason
  instead of enforcing a cap against a permanent `0` (which would never fire) or
  against nothing (which would block everything). Same for
  `database.backend: memory`, which keeps no spend history to measure a window
  against. `make doctor`'s **`spend budget`** check names whichever applies, and
  the agent build logs a warning. `enabled: true` with no limit set is a config
  error and fails loudly at load — turning the feature on and configuring nothing
  to enforce is a mistake, not a preference.
- **Where it shows.** The header cost dropdown gains a **Budget left** line for
  the window with the least headroom (green → amber past the warn threshold →
  red once spent), plus an explicit note when the cap is reached. Only the
  tightest window is shown; three rows of headroom is noise.

**Where it's wired.**

| Piece                  | Location                                                                                                                                                                                                                                           |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Config                 | `deerflow/config/spend_budget_config.py` (`SpendBudgetConfig`, `SpendLimit`), `spend_budget:` block in `config.example.yaml`, `AppConfig.spend_budget`                                                                                             |
| Window math            | `deerflow/runtime/spend_window.py` (`resolve_window_start`, rolling vs. calendar)                                                                                                                                                                  |
| Accounting + admission | `backend/app/gateway/spend_budget.py` (`resolve_spend_budget_status`, `SpendBudgetStatus`, `exhausted_message`); the 402 and the baseline injection live in `app/gateway/services.py::start_run`                                                   |
| In-run enforcement     | `deerflow/agents/middlewares/spend_budget_middleware.py`, appended in `agents/lead_agent/agent.py` after `TokenBudgetMiddleware`                                                                                                                   |
| Live per-model usage   | `deerflow/runtime/journal.py::RunJournal.current_token_usage_by_model()`                                                                                                                                                                           |
| Pricing                | `deerflow/pricing.py` — **moved out of `app/gateway/pricing.py`** so the in-graph middleware can price without importing `app.*` (the harness boundary). `app/gateway/pricing.py` is now a re-export shim, so every existing importer is unchanged |
| Header line            | `GET /api/threads/{id}/token-usage` → `spend_budget`; `core/threads/token-usage.ts::threadTokenUsageToSpendBudget`; `components/workspace/token-usage-indicator.tsx`                                                                               |
| Diagnostic             | `scripts/doctor.py::check_spend_budget`                                                                                                                                                                                                            |

**Verify it works.**

```bash
cd backend && uv run pytest tests/test_spend_budget_config.py tests/test_spend_budget.py tests/test_spend_budget_middleware.py
cd backend && uv run pytest tests/blocking_io/test_aux_usage.py   # the window read stays off the event loop
cd backend && uv run pytest tests/test_doctor.py -k TestCheckSpendBudget
cd frontend && pnpm test token-usage                               # the header's budget line
make doctor                                                        # 'spend budget' names why a cap is not enforced
```

Then in the browser (`make dev`): set `spend_budget.enabled: true` with a
deliberately tiny `daily_limit` (say `0.01`), run a turn on a **priced** model,
and the header dropdown's **Budget left** goes red; the next message is refused
with the 402 message. Set the limit back, switch the thread to a **local Ollama**
model, and confirm the same tiny cap never blocks it — that is the rule the whole
feature is built around.

### 11. Spend history and attribution (`/workspace/spend`)

The header answers "what is this conversation costing". This answers the question
a person actually asks at the end of a month. A new workspace page beside
`/workspace/scheduled-tasks` reports one window three ways:

- **By feature** — conversation vs. memory vs. suggestions, so the two
  off-by-default background features from §7 are finally accountable in a
  cross-thread view rather than only per thread.
- **By model** — most expensive first, with unpriced models sorted **last** and
  labelled, never as if they were the cheapest.
- **By conversation** — with thread titles, so an expensive chat is identifiable.

Windows are 7 / 30 / 90 days. The three groupings are derived from the same
priced rows, so their totals agree — pinned by a test that asserts exactly that.

- **No second cost calculation.** The endpoint reuses `pricing.py` end to end
  (`run_cost` for runs, `token_cost` for the auxiliary sinks), so a model can
  never be billed differently here than in the chat header.
- **Unpriced models are named.** When nothing is priced the page says so and why;
  when only some models are, it names the ones missing a price and warns that the
  real cost is higher — the same rule the header follows, for the same reason (a
  quietly low total is indistinguishable from a broken feature).
- **Token counts work before pricing does**, so the page is useful on a config
  with no `pricing:` blocks at all.

**Where it's wired.**

| Piece                | Location                                                                                                                                                                       |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Endpoint             | `GET /api/console/spend?days=N` in `backend/app/gateway/routers/console.py` (`ConsoleSpendResponse`)                                                                           |
| Auxiliary range read | `deerflow/runtime/aux_usage_store.py::AuxUsageStore.aggregate(since, until, thread_ids)` — the time-sliceable read the append-only `recorded_at` row shape was added for in §7 |
| Frontend client      | `frontend/src/core/spend/{api,hooks,types}.ts`                                                                                                                                 |
| Page + nav           | `frontend/src/app/workspace/spend/page.tsx`, entry in `components/workspace/workspace-nav-chat-list.tsx`, i18n `spend.*`                                                       |

**Verify it works.**

```bash
cd backend && uv run pytest tests/test_console_router.py -k ConsoleSpend
cd frontend && pnpm check && pnpm test
```

Then in the browser (`make dev`): open **Spend** in the sidebar. With pricing
configured the three tables agree with the summary total; switch the window and
the figures move. On a config with no prices the tables still show tokens and the
page explains why there is no cost.

### 12. Effective deployment exposure check

Passwordless auth, multi-user mode off, and a non-loopback `BIND_HOST` are
simultaneously this fork's happy path and its worst-case security posture. Each
setting is individually documented and individually defensible. The
_combination_ is what decides who can reach the instance and as whom — and until
now nothing computed it, so the operator had to hold three settings in three
different files in their head at once.

`scripts/exposure.py` computes it. `make doctor` reports it, and the same
assessment prints at the end of `make up` and `make dev`, where it is actually
read.

**It changes no default.** This is diagnosis only — the defaults are the fork's
deliberate choice, and the check never returns a `fail`, so a home lab that is
exposed on purpose does not make `make doctor` exit non-zero.

**Two entry surfaces, and they do not share a bind address.** This is the part
that is easy to get wrong by reading `.env` alone:

| Entry                             | Bind address              | Set by                                                                                                    |
| --------------------------------- | ------------------------- | --------------------------------------------------------------------------------------------------------- |
| `make up` (Docker)                | `${BIND_HOST:-127.0.0.1}` | `.env` → the published compose port; **loopback by default**                                              |
| `make dev` / `make start` (local) | every interface           | `docker/nginx/nginx.local.conf`'s `listen 2026;` has **no address**, so `BIND_HOST` does not apply at all |

So the local dev stack is on the LAN even when `.env` says `BIND_HOST=127.0.0.1`.
That is not a regression — it is what the local nginx config has always done —
but it was invisible. `make doctor` now prints one row per entry.

**Tiers.**

| Tier              | When                                                                      | Reported as                                                                                               |
| ----------------- | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `local-only`      | the bind is loopback                                                      | ✓ ok, one line, no nagging — every other setting is irrelevant if nobody outside this machine can connect |
| `trusted-network` | reachable, but either auth is on, or the reach is a tailnet / private LAN | ⚠ warn                                                                                                    |
| `open-network`    | no login wall **and** a wildcard / public / unclassifiable bind           | ⚠ warn, naming every contributing setting                                                                 |

A Tailscale bind is deliberately not the same as `0.0.0.0`: 100.64.0.0/10 and
`fd7a:115c:a1e0::/48` are classified as `tailscale`, not `private`, because a
tailnet is a device-authenticated overlay. (Python's own `is_private` reports
CGNAT as private, so the ordering in `classify_bind_host` is load-bearing.)
`should_cobind_loopback` in `deploy.sh` already treats the two differently; this
matches it.

**Contributing settings are only named when they can matter.** Multi-user mode
off on a loopback-only box is the documented personal-server default, not a
finding — it is reported as contributing only once the instance is reachable
_and_ passwordless. Same for `allow_host_bash`, which becomes "anyone on this
network gets host code execution" only under those same two conditions. A
`DEER_FLOW_AUTH_DISABLED=1` that is neutralized by `DEER_FLOW_ENV=production`
is credited as such rather than counted against the deployment.

| Piece            | Where                                                                               |
| ---------------- | ----------------------------------------------------------------------------------- |
| Assessment       | `scripts/exposure.py` (`classify_bind_host`, `resolve_facts`, `assess`)             |
| Doctor check     | `scripts/doctor.py::check_deployment_exposure` (one row per entry surface)          |
| Launch summaries | `scripts/deploy.sh` (after the bind line), `scripts/serve.sh` (after the logs line) |
| Tests            | `backend/tests/test_exposure.py`                                                    |

**Verify it works.**

```bash
cd backend && uv run pytest tests/test_exposure.py
python3 scripts/exposure.py --surface docker      # or --surface local, --format json
```

### 13. Whole-instance backup and restore (`make backup` / `make restore`)

There is per-feature memory import/export, but nothing snapshotted `.deer-flow`
**as a unit**: memory, threads, chat tabs, runtime settings, uploads, the
databases. A personal AI accumulates months of that on one machine with no
redundancy, which is exactly the deployment shape this fork targets.

```bash
make backup                              # → backups/deerflow-backup-YYYYmmdd-HHMMSS.tar.gz
make backup INCLUDE_SECRETS=1            # also .env + integration tokens (see below)
make restore ARCHIVE=backups/….tar.gz    # refuses while a stack is running
python3 scripts/backup.py inspect <file> # read the manifest without extracting
```

**What is in it.** `config.yaml`, `extensions_config.json`, the DeerFlow home
tree (`backend/.deer-flow` and a repo-root `.deer-flow`), and `skills/custom`.
Public skills are deliberately out — they are committed, so a restore onto a
clean checkout already has them. Rebuildable caches are out too (`skills_view`,
`.retrieval`, `__pycache__`, browser frames, staged `.upload-*.part` files).

**The secrets decision, stated rather than defaulted.** Credentials are
**excluded** unless you ask for them. Integration credentials under
`users/{user_id}/integrations/` are `0700`/`0600` for a reason and `.env` holds
every API key; copying them into a world-readable tarball in `~/Downloads` turns
a durability feature into a credential-exfiltration feature nobody asked for.
`--include-secrets` (`INCLUDE_SECRETS=1`) opts in, and then:

- the archive is created `0600` **from the first byte** — opened with an explicit
  mode rather than chmod'ed afterwards, because an archive that is briefly
  world-readable while it is written is world-readable;
- the manifest records `includes_secrets`, so a restore can say what it is about
  to write;
- restoring a secret-_free_ archive leaves the target's existing credentials in
  place rather than deleting what the backup does not carry.

**Databases are handled explicitly, not hoped for.** With
`database.backend: sqlite` the file is inside the home tree and comes along.
With `postgres`, `pg_dump --no-owner --no-privileges` runs into the archive, and
a failed dump **aborts the backup** — a snapshot with no database in it is worse
than an error, because you only find out at restore time. Restore writes the
dump beside the config and tells you to load it; it never touches a live
database on your behalf.

**Restore refuses to run underneath a live stack.** Writing over SQLite that a
Gateway holds open, and over thread directories an active run is using, is how a
recovery becomes a second outage. `restore` probes the Gateway (8001) and nginx
(2026) ports and stops with the list of what is up and the `make stop` fix;
`--force` / `FORCE=1` is the deliberate override.

**Permissions survive; ownership is documented, not faked.** Extraction uses
`tarfile`'s `filter="tar"`, which keeps the recorded mode bits (so `0700`
credential directories come back `0700`) while still rejecting absolute paths
and traversal. The `data` filter would have stripped exactly the modes this
feature exists to preserve. Ownership can only be restored as root, so it is not
attempted — which also makes this the recovery path for the root-owned-files
problem in the Arch / DooD section: restore as your own user and the tree comes
back owned by you.

**Archive safety is enforced on the way in.** Every member must live under
`deerflow-backup/`, with no absolute path and no `..` component, and the archive
must carry a readable DeerFlow manifest — an arbitrary tarball is refused rather
than extracted over your instance.

| Piece   | Where                                                                                                |
| ------- | ---------------------------------------------------------------------------------------------------- |
| Script  | `scripts/backup.py` (`create_backup`, `restore_backup`, `inspect_backup`, `detect_running_services`) |
| Targets | `make backup` / `make restore` in the root `Makefile`                                                |
| Tests   | `backend/tests/test_backup.py`                                                                       |

### 14. Model fallback chains

§3 above notes that models flagged `supports_tools: false` stay selectable and
"tool-using subagents will simply fail at runtime". That is one instance of a
general problem: running local models means absorbing local-model failure modes
— daemon down, OOM, context overflow, no tool support — and the user was
absorbing them by hand, one lost turn at a time. This is the reliability cost of
the fork's central bet, and paying it is what makes a cost-aware routing policy
safe to turn on.

```yaml
models:
  - name: qwen3:8b
    fallback: [claude-haiku-5] # per-model, wins over the global chain

model_fallback: # default for models that declare none
  enabled: false # off by default
  chain: [claude-haiku-5]
```

**A failure falls back; a decision does not.** That distinction is the whole
design. A provider that is down, overloaded, or handed too many tokens has
failed, and trying the next model beats losing the turn. A user interrupt, a
spend cap (§10), and a guardrail refusal are things the system _meant_ to do —
retrying those on another model would defeat them **and spend money doing it**.
A 401/403 is a third case: a bad key is a config error you need to see, not
something to paper over until the bill arrives.

| Falls back                                   | Does not                                               |
| -------------------------------------------- | ------------------------------------------------------ |
| connection failure / timeout to the provider | user interrupt (`CancelledError`, LangGraph interrupt) |
| context-length rejection                     | spend or token cap                                     |
| unsupported tool calls                       | guardrail / moderation refusal                         |
| provider 5xx                                 | 401 / 403, and any plain 4xx that is not context/tools |

Anything unrecognized also does **not** fall back: defaulting to "retry on
another model" would double the cost of every bug and bury the original error
behind a second, unrelated one.

**Cycles are not detected, they are inexpressible.** A chain member is built
_without_ its own chain, so `a → b → a` is not a shape the config can produce;
`MAX_CHAIN` (3) bounds the rest. A member that cannot be constructed — missing
key, bad class path — is dropped with a warning rather than taking down the
model the user actually selected: degrading to "no fallback" always beats
degrading to "no model".

**Cost stays correct for free, and that is load-bearing.** The wrapper returns
the serving model's result untouched, so the `response_metadata.model_name` that
`RunJournal` keys `token_usage_by_model` on already names whichever model ran.
Rewriting it to the primary's name would bill a cloud fallback at a local
model's rate of zero — silently wrong in the direction of the spend cap (§10)
and the spend report (§11).

| Piece                    | Where                                                                                     |
| ------------------------ | ----------------------------------------------------------------------------------------- |
| Classification + wrapper | `backend/packages/harness/deerflow/models/fallback.py`                                    |
| Config                   | `ModelConfig.fallback`, `deerflow/config/model_fallback_config.py`, `config.example.yaml` |
| Wiring                   | `models/factory.py::_wrap_with_fallbacks`                                                 |
| Tests                    | `backend/tests/test_model_fallback.py`                                                    |

### 15. Cost-aware subagent routing

The fork exposes the cost lever — a per-thread lead model and a per-thread
subagent override (§3) — but the user has to pull it every session. The worked
example in _Cost story_ below puts Sonnet-lead / Haiku-subagents at **~63%
cheaper** than all-Sonnet, and Sonnet-lead / local-subagents at **~95%**. A
policy turns that UI affordance into a standing saving.

```yaml
model_routing:
  enabled: false # off by default
  rules:
    - name: tool-free-to-local
      when:
        needs_tools: false # unset conditions are wildcards
        max_context: 24000 # estimated prompt + overhead, in tokens
      prefer: [qwen3:8b, claude-haiku-5]
    - name: everything-else-cheap
      prefer: [claude-haiku-5]
```

**No LLM classifies the task.** Requirements are read from facts already on the
table: whether the subagent was given business tools, whether it can view images
(`view_image` is only bound to a vision-capable model, so its presence is a real
capability signal), and the size of the prompt. Adding a classification call
would spend money to decide how to save money, and would make the routing
decision non-deterministic — two identical delegations could route differently.

**The explicit selection always wins, and it wins by standing the policy down
entirely** rather than by "outranking" it: `apply_routing_policy` returns the
override before the policy is consulted at all. The policy only ever fills the
default that would otherwise be inherited from the lead.

**A model is only chosen if it can do the job.** Capability filtering is applied
_to_ the preference order, not merely alongside it: a candidate with
`supports_tools: false` is skipped for a tool-using subtask, one without vision
is skipped for an image subtask, and one whose `context_window` is below the
estimate is skipped too. Trading a cost saving for a failed turn is not a trade.
A rule that matches but offers nothing capable falls through to the next rule
rather than failing the delegation.

**The decision is inspectable.** The subagent card shows `(via <rule>)` beside
the model name, and the tooltip carries the full reason — including which
candidates were skipped and why. A routing decision nobody can inspect is a
routing decision nobody trusts, and "why did this _not_ route?" is the first
question an operator asks, so a reason is produced even when nothing was routed.

| Piece                     | Where                                                                                              |
| ------------------------- | -------------------------------------------------------------------------------------------------- |
| Policy config             | `deerflow/config/model_routing_config.py`, `model_routing:` in `config.example.yaml`               |
| Requirements + resolution | `deerflow/subagents/routing.py`                                                                    |
| Precedence                | `tools/builtins/task_tool.py::apply_routing_policy`                                                |
| Card                      | `core/tasks/lifecycle.ts`, `core/tasks/types.ts`, `components/workspace/messages/subtask-card.tsx` |
| Tests                     | `backend/tests/test_model_routing.py`, `frontend/tests/unit/core/tasks/lifecycle.test.ts`          |

### 16. Installable PWA + push notifications that survive a closed browser

This was the biggest gap relative to the fork's own stated goal. There was a
notification settings page, but it used the plain browser `Notification` API
with **no service worker and no manifest** — so a notification only fired while
the tab was open, and iOS Safari would not deliver at all. The use case the fork
is built around ("start a sandbox run from my phone over Tailscale, pocket it,
get pinged when it's done") did not work on the device it is designed for.

**Installable.** `frontend/public/manifest.webmanifest` plus icons, linked from
the root layout's `metadata`, with `appleWebApp` set — on iOS, Add to Home Screen
is not a nicety, it is the _precondition_ for receiving push at all.

**The service worker is deliberately push-only.** It handles `push` and
`notificationclick` and caches nothing. DeerFlow is a live, server-driven app —
SSE streams, per-thread state, an API that moves with every backend release — so
a stale cached shell served after an upgrade produces bugs that look like backend
faults and are miserable to diagnose. That is a far worse trade than offline
support nobody asked for.

**Web Push, end to end.** VAPID keys are minted on first use and kept
(`<DeerFlow home>/vapid.json`, mode `0600` from the first byte — regenerating
them silently invalidates every existing subscription). Subscriptions are stored
per user in the same `ui_state.json` bag as the pinned chat tabs, deduped by
endpoint so re-subscribing replaces rather than accumulates. `pywebpush` is an
**optional extra** (`uv sync --extra webpush`): push encryption is not something
to hand-roll, and most installs never turn this on, so the feature reports itself
unavailable with the install hint instead of making everyone carry it.

**A dead subscription deletes itself.** A push service answers 404/410 for a
subscription the browser discarded, and nothing else ever prunes those, so a user
who reinstalls their browser would otherwise accumulate undeliverable endpoints
forever.

**Only runs worth interrupting for.** A notification fires when a run finishes
_and_ took longer than 30 seconds — by then the user has almost certainly
switched away, which is exactly when a push is useful. A notification for a
two-second question is noise, and noise is how a user turns notifications off for
good. An unknown duration is treated as short: a missed notification costs less
than a stream of unwanted ones. The whole path swallows its own failures — a push
service outage must never turn a successful run into a failed one.

#### The secure-context problem, said out loud

Service workers require a **secure context**: `https://…` or `http://localhost`.
The fork's documented deployment — a plain-HTTP LAN address like
`http://192.168.1.10:2026` — is not one, so on exactly the device this feature
targets, the browser API is simply **absent**.

Silently doing nothing there is the worst possible behavior: the user flips a
switch and has no way to find out why nothing happened. So each unsupported case
is detected separately and rendered with its own explanation and fix. The
insecure-origin case is checked **first**, because it makes every other API
absent too and "service workers are unavailable" would send the user hunting for
a browser setting that does not exist.

| Where you open DeerFlow                        | Push works?                                         |
| ---------------------------------------------- | --------------------------------------------------- |
| `http://localhost:2026` on the machine itself  | ✅ localhost is a secure context by definition      |
| `https://<host>.ts.net` (Tailscale, see below) | ✅ and this is the phone case the fork is built for |
| `http://192.168.1.10:2026` (plain LAN)         | ❌ explained in the UI, with the fix                |

Tailscale issues a real certificate for your machine's `*.ts.net` name:

```bash
tailscale cert <your-machine>.<your-tailnet>.ts.net   # once
tailscale serve --bg https / http://127.0.0.1:2026    # proxy HTTPS to DeerFlow
```

Then open `https://<your-machine>.<your-tailnet>.ts.net` from the phone, install
it to the home screen, and enable background notifications in Settings.

| Piece                 | Where                                                                                                                                |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Manifest + icons + SW | `frontend/public/manifest.webmanifest`, `frontend/public/icons/`, `frontend/public/sw.js`, `src/app/layout.tsx`                      |
| Browser side          | `frontend/src/core/notification/push.ts`, the background-notification block in `settings/notification-settings-page.tsx`             |
| Server side           | `backend/app/gateway/web_push.py`, `routers/push.py`, `run_notifications.py`, the push helpers in `deerflow/config/user_ui_state.py` |
| Tests                 | `backend/tests/test_web_push.py`, `frontend/tests/unit/core/notification/push.test.ts`                                               |

**Known gap, stated rather than papered over:** the mobile chat layout audit that
was scoped alongside this is _not_ done. The keep-alive tab strip and the
artifact panel are still desktop-shaped on a narrow viewport. The PWA shell,
push delivery, and the install path are complete and usable; the responsive
pass on those two components remains open work.

### Note: the "older messages disappear in long conversations" investigation

The request that shipped this cost feature also asked to fix messages vanishing from long conversations. Findings, so the next pass has a head start:

- **Trigger.** `summarization.enabled: true` is the default. In a long thread, context summarization periodically compacts older turns out of the model's _active context_ with `RemoveMessage(ALL)` + a hidden summary + a retained tail. That compaction is what makes older turns flicker out of the live view.
- **Why it's not (usually) permanent.** The _visible_ transcript is not the checkpoint's `messages` channel — it is the run-event feed, read back by `GET /api/threads/{id}/messages/page`. Summarization rewrites the checkpoint, not the run-event feed, so the full history is still there and a page reload (or scrolling up, which cursor-paginates all the way back) reloads it. The backend page scan is well-guarded (it raises rather than silently stopping on a non-advancing cursor).
- **The existing mitigation.** During a live session, before the run-event refetch catches up, the frontend keeps a **transient history bridge** + a **rendered-message ledger** (`core/threads/hooks.ts`, issue #3825 and follow-ups #4380/#4458/#4531) that overlay the just-removed turns so they don't blink out. This is exactly the anti-loss machinery, and it has been iterated on many times.
- **Why this pass did not change it.** Without a concrete reproduction, editing that resolver — some of the most intricate, most-fixed code in the repo — risks regressing prior fixes for more than it would gain. The safe, honest call was to diagnose rather than speculatively rewrite. If loss persists **after a reload** (i.e. it is not just the transient live glitch), that points at the run-event feed itself and is a different, higher-severity bug worth capturing a reproduction for (thread id + roughly when the turns vanished).

### 17. The price is a field, not part of the name

A bundled model used to state its price twice: as `($3/15)` inside its
`display_name`, and again in a machine-readable block. One number, two places —
and they drifted the way that always drifts. A promotion could only "end" by a
human editing a string, so an expired discount kept being advertised; and a
model whose name had no pair, or whose block was missing, simply showed `—` in
the chat header with no explanation.

The price is now data, in one place:

```yaml
- name: openrouter-minimax-m3
  display_name: MiniMax M3 (OpenRouter) (p) # a label, nothing more
  model: minimax/minimax-m3
  price:
    currency: USD # optional, defaults to USD
    input: 0.6 # per 1M input tokens
    output: 2.4 # per 1M output tokens
    cache_hit: 0.03 # optional
  discount:
    input: 0.24
    output: 0.96
    until: 2026-08-31 # optional; inclusive, "through the 31st"
```

`price:` is the single source of truth for the chat-header cost, the spend page,
the budget caps, **and** the price shown in the model dropdown — so the number a
user reads is the number they are billed against, by construction rather than by
discipline. `wizard/providers.py::MODEL_PRICES` holds the same data for the
setup wizard, and a test asserts the two synced sources agree.

**The discount is additive and never billed against.** Spend is estimated at the
standard rate and the discount shown beside it, because a promotion can end at
any time and an under-estimate is worse than a slightly high one.

**Expiry is enforced once, at the bottom.** An expired discount is dropped in
`build_pricing_map`, so it never reaches a `ModelPricing`. Every consumer is
correct without repeating the check, and there is no second place for the two to
disagree. Do not add a downstream expiry check; that is how they drift.

**Two unknowns resolve to "expired", deliberately:** an `until` that cannot be
parsed, and a run where the current time is unavailable. The alternative —
assume it is still valid — reintroduces the bug the field removes. Over-stating
cost is corrected by the provider's bill; the other direction is silent. A
discount with no `until` is unaffected by an unknown clock, so the common case is
not punished for a problem it does not have. Not every promotion has an
announced end date, and an open-ended one is legitimate; it is a review item in
the post-sync checklist, not an audit finding, because a weekly issue nobody can
close is how that job becomes one people ignore.

**The UI is unchanged.** `core/models/sorting.ts::modelNameSegments` composes the
name and the price into the same coloured segments the embedded pair produced —
green for what you pay, red for the list price beside a live promo — now from
`GET /api/models`, which returns the resolved price with the discount already
expiry-filtered. A client therefore cannot advertise a promotion that has ended
by forgetting to compare dates.

**Nothing needs migrating.** The display-name parser is kept as the legacy path,
because `config_upgrade.py` cannot add a key inside an existing list entry: every
`config.yaml` written before this change still carries the old names and is
priced by that parser alone. Removing it would silently un-price every
pre-existing install. When a model has both, the embedded copy is stripped from
the rendered name so the price is not shown twice.

One trap worth restating: `ModelConfig` is `extra="allow"`, so `price` and
`discount` **must** stay in the model factory's exclude set. An unexcluded key is
forwarded into the provider client and from there into the completion request
payload — a cost annotation would become a malformed API call.

**A reply keeps the price it was billed at.** Everything above is about where
the price *lives*; this is about *when* it is read. Cost used to be recomputed
from the live `config.yaml` on every read, which quietly made a historical
figure a statement about today's roster rather than about what the run cost.
Two failures fell out of that, and neither logs anything:

- **A price moves and every old total moves with it.** Re-pricing an entry
  rewrites what last month's conversation reports it cost.
- **A model leaves the roster and its spend goes to zero.** `lookup_pricing`
  stops resolving the old id, so those runs contribute *nothing* and the
  conversation gets **cheaper**, while the model shows up in `unpriced_models`
  as if the operator had forgotten to price it. This is not hypothetical — the
  audit above *routinely* rolls entries forward (Grok 4.5 → 4.6, a `*-latest`
  alias pinned to a dated id), so the roster is expected to move out from under
  runs that already happened.

`runs.pricing_snapshot` (migration `0019`) records the per-model rates in effect
when a run finished, taken from the config that run actually executed under
(`ctx.app_config`), keyed the same way as `token_usage_by_model`. The read path
prefers it per model and falls back to the live config for anything it does not
cover — which is what prices every run written before the column existed, so
there is no backfill and no migration of old data. Deliberately **not**
backfilled, either: writing today's prices onto older runs would assert, with
false confidence, that they were billed at rates nobody checked.

Four rules ride along, each of which is a way the fix could be worse than the
bug:

- **A snapshot never re-expires its discount.** `build_pricing_map` drops an
  expired discount so a *live* config cannot advertise a promotion that ended.
  A snapshot is the opposite statement — what was in effect at the time — and
  re-expiring it would reintroduce exactly the retroactive rewriting the column
  exists to stop.
- **A currency switch re-prices instead of summing.** A snapshot entry whose
  currency disagrees with the display currency is dropped and that model goes
  back on today's price. Visibly re-priced beats invisibly mis-added.
- **A snapshot cannot switch cost reporting back on.** An empty live pricing map
  is the operator's current answer, and there is no display currency to render a
  figure in.
- **A completion retry without a snapshot leaves the stored one alone.** The
  recovery paths re-run `update_run_completion`; a retry that could not rebuild
  the snapshot must not blank the run's price.

The thread endpoint now sums **every** cost figure from the per-run buckets
rather than from the thread-level `by_model` aggregate, because two runs on one
model at two different prices cannot be represented by a single per-model rate.
That also makes the header's stated relation — `sum(steps) + superseded_cost ==
total_cost` — an identity rather than two calculations that happen to agree. A
store that reports no `by_run` at all (it predates the per-run aggregation, and
so has no snapshots either) still prices its `by_model` aggregate at today's
rates, which is both the old behaviour and the only one available.

### 18. Gaslight mode — edit a message into a hidden conversation version

Upstream's per-turn action was **Branch**: it forked the conversation from a
completed turn into a _separate chat_, which then sat in the sidebar next to the
original as "Branch of …". That is the right primitive and the wrong surface —
trying three phrasings of the same question left four entries in the sidebar and
no indication of which was which.

This fork replaces that button with **Edit**, on **either half of a turn** — the
feature is **gaslight mode**, because the conversation carries on as though the
words had always been what you just made them. The version you were reading is
kept, and a `‹ 2/2 ›` switcher appears **on the edited message** to move between
them. One conversation stays one entry in the sidebar, however many times it is
edited. The per-message button stays labelled **Edit** — "gaslight mode" is the
name of the behaviour, in this file and in the README, not a string in the UI.

**Two halves, one mechanism, and the difference is what happens after the fork:**

- **Edit a prompt** — the conversation replays from that turn with the new
  wording, and the model answers the new question. The branch is taken at turn
  _k-1_'s terminal assistant message, so the new thread stops short of the turn
  being replaced, and the edited text is _sent_ into it.
- **Edit an answer** — the branch is taken at that turn's **own** assistant
  message, so the new thread carries the question _and_ its answer, and the
  Gateway writes your words in place of what the model said. **Nothing is
  re-generated**: there is no run to make, because the edited text is the answer.
  Whatever you send next is answered with those words standing in the history.
  This is the half the feature is named for.

The asymmetry is not an oversight. Re-running the turn after an answer edit would
discard the edit — the model's fresh reply would replace the words you just
wrote — so an answer edit that "regenerates" cannot keep what it was asked to
keep. The one that does nothing afterwards is the one that works.

**It is the branch endpoint underneath.** The prompt half changed nothing about
`POST /api/threads/{id}/branches`; the answer half adds one optional pair to it
(`replacement_assistant_message_id` + `replacement_assistant_text`), applied to
the copied checkpoint messages **and** to the seeded run events, because the
thread feed reads the latter — seeding it from the originals would show the old
answer the moment the feed refreshed, and the edit would read as silently
reverted. The pair is all-or-nothing, and the id must be one of the assistant
messages the branch is taken from: a half-specified or out-of-turn rewrite is
refused rather than branching without the edit that was asked for. The rest of
the fork is in how the result is presented:

1. Editing the **prompt** at turn _k_ branches the thread at the terminal
   assistant message of turn _k-1_, so the new thread carries the history up to
   (but not including) the edited turn. Editing the **first** message has nothing
   to branch from, so it creates an empty thread (`POST /api/threads`) instead;
   that is the only case with no branch call, and it is the common one. Editing
   an **answer** always has something to branch from — its own turn — so it
   always takes the branch path.
2. The new thread is stamped `deerflow_edit_version: true` and is filtered out of
   every primary thread list (`filterThreadSearchResults`), so it never appears
   in the sidebar, the chats page, or the tab strip.
3. The family's **root** thread records the group in `deerflow_edit_version_groups`
   and the reader's current choice in `deerflow_edit_active_version`.
4. A **prompt** edit parks its text in session storage, replayed by whichever
   chat instance mounts the new thread — the click site navigates away, so it
   cannot send the message itself. An **answer** edit parks nothing: the branch
   already contains the rewritten answer, so a parked send would post the
   assistant's own words back as the user's next message.

**Three design points are load-bearing and easy to "fix" into bugs.**

_An answer edit must not park a pending send._ The prompt half hands its text to
the next mount through session storage (point 4 below); the answer half must not,
because the branch already contains the edited answer — parking it would post the
assistant's own words back as the user's next message. Pinned by
`edit-version-answer.dom.test.tsx`.

_The two halves need different group keys._ Editing the answer of turn _k_ and
editing the prompt of turn _k+1_ branch from the **same** assistant message, so a
bare message id would merge two unrelated sets of versions into one switcher
rendered on both messages. Answer groups are namespaced (`answer:<id>`); prompt
groups keep the bare id, so every group written before answer edits existed keeps
resolving unchanged.

_Groups are keyed on the assistant message they branch from, not on the turn
number._ Turn 4 of the original and turn 4 of a version that diverged at turn 2
are different conversations that happen to share an ordinal; keying on the base
message id makes them different groups automatically, because a version only
shares a base message id with threads whose history up to that point is the same
copied history. The turn index is stored alongside for display only.

_The single sidebar entry follows the reader._ `pathOfThread()` routes the root's
entry to `deerflow_edit_active_version`, and the switcher writes that key before
navigating. Without it the sidebar keeps reopening version 1 forever, which reads
as the edit having been lost — the exact failure the feature exists to avoid.

Known limits, deliberately: a turn whose predecessor ended in tool calls or a
clarification has no settled assistant message to fork from, so its **prompt**
shows no edit button (the first turn is always editable); only a turn's
**terminal** assistant message is editable, because rewriting an intermediate
tool-calling message would leave the turn describing work that never happened;
an answer still streaming is not editable, since there is nothing settled to
rewrite; deleting the root does not delete its hidden versions, which stay as
unreferenced threads; and the older latest-turn-only _in-place_ edit
(`/runs/edit-regenerate/prepare`) is still implemented on both sides but is no
longer wired to any button.

### 19. The system prompt is a text box, not a black box

Every run starts from a system prompt the user never saw. It is assembled in
`backend/packages/harness/deerflow/agents/lead_agent/prompt.py` from a template
plus twelve substituted sections (soul, skills, subagents, deferred tools, ACP,
mounts, …), and nothing in the UI or the HTTP API exposed either the template or
the rendered result. Changing it meant editing Python and restarting the
Gateway.

**Settings → System prompt** puts it on screen and makes it editable:

- **Edit** shows the template in force — the built-in one, or your override —
  in a monospace editor, with the twelve placeholders listed as one-click
  insert buttons.
- **Preview** shows the _rendered_ prompt: every placeholder substituted, i.e.
  the exact text the lead agent receives, with a switch for the Ultra-mode
  subagent block (which is where the available subagent roster is listed, so
  this is also the only place in the UI that names `general-purpose` / `bash`
  and any `subagents.custom_agents` you configured).
- **Reset to default** discards the override.

The override is a single Markdown file, `{base_dir}/SYSTEM_PROMPT.md`, written
atomically beside `USER.md`. `apply_prompt_template()` re-reads it on every
agent build, so a save applies from the next run with no Gateway restart, and
`make backup` picks it up with the rest of the instance state.

Three design points worth keeping if this is ever refactored:

- **The allowed placeholder set is derived from the built-in template, never
  duplicated.** `SYSTEM_PROMPT_PLACEHOLDERS` is
  `extract_placeholders(SYSTEM_PROMPT_TEMPLATE)`, so adding a `{new_section}`
  to the template automatically permits it in an override and lists it in the
  editor. A hardcoded second list would silently rot.
- **A saved prompt can change a run but must never break one.** Validation runs
  on save _and_ again on every read, and `apply_prompt_template` still wraps the
  `.format()` call: an override that is hand-edited on disk, restored from an
  old backup, or written against a placeholder this version no longer supplies
  degrades to the built-in template with a warning instead of raising inside the
  agent build. Pinned by
  `backend/tests/test_system_prompt_store.py::TestApplyPromptTemplate`.
- **Omitting a placeholder is a feature, not an error.** Dropping
  `{skills_section}` is how you strip that block from the prompt, so the API
  reports `missing_placeholders` for the UI to note rather than refusing the
  save. What _is_ refused: an unknown name (`KeyError` at render), a positional
  field (`IndexError` — the renderer passes keywords only), and dotted or
  indexed access like `{soul.__class__}` (renders object internals into the
  prompt).

**What a change to the prompt needs to be tested with.** The prompt is now two
things — a template _and_ a stored override — so a change to either has a wider
blast radius than editing a string used to have. Anything touching
`prompt.py`'s template, `apply_prompt_template()`, or `system_prompt_store.py`
should carry:

- **A placeholder round-trip.** Adding or removing a `{placeholder}` changes the
  contract an existing saved override was written against. Adding one is safe by
  construction (the allowed set is derived), but _removing_ one silently
  invalidates every override that used it — those fall back to the built-in
  template, which is the designed behaviour and must stay covered by
  `TestResolution::test_an_invalid_override_on_disk_falls_back_to_the_builtin`.
  Say so in the release note too: the user's saved prompt stops applying.
- **A render that passes `app_config` explicitly.** See the config gate in the
  mechanical checklist above — a `None` default reads the gitignored root
  `config.yaml` and splits local from CI.
- **A validation case per rejection class.** `validate_system_prompt_template`
  refuses unknown names, positional fields, dotted/indexed access, nested format
  specs, empty, and oversized. Each is a distinct failure mode at render time, so
  each keeps its own test; the nested-spec one exists specifically because field
  names alone do not prove renderability.
- **The admin gate on every route.** `TestAuthorization` covers all four. A new
  route on this router without a `require_admin_user` call is a way to read the
  prompt (and the skills roster it renders) unauthenticated.
- **The settings-page count.** `frontend/tests/unit/components/workspace/lazy-panels.test.ts`
  asserts the exact number of `dynamic()` imports in `settings-dialog.tsx`. Adding
  or removing any settings page — not just this one — must bump it.

The routes (`GET`/`PUT`/`DELETE /api/system-prompt`, `GET
/api/system-prompt/preview`) are admin-gated with the same
`require_admin_user` helper as skill and MCP management — writing the prompt has
that blast radius, and reading it returns context the prompt itself tells the
agent not to disclose. Under §5 (passwordless by default) the local user _is_
the admin, so the page works out of the box; no new `config.yaml` section was
added for it. The editor warns — but does not block — when an edit drops the
built-in **System-Context Confidentiality** section, because the consequence
(the agent will happily recite your prompt) is invisible until someone asks.

### 20. Generate an agent from work you have already done

Creating a custom agent used to mean answering an interview on
`/workspace/agents/new`. That works when you already know what agent you want —
but the best evidence for _which_ agent you need is the work already sitting in
your history, and nothing read it. **Generate from history** (a button beside
**New Agent** on `/workspace/agents`) is the second way in: pick the model that
runs the analysis, pick the past conversations and/or scheduled tasks the agent
should be shaped around, and let it decide.

**Deciding "no" is the point, not a failure mode.** The verdict is one of two,
and `no_gap` — the work is one-off, too varied to specialize, or already covered
by an agent you have, named — is a first-class success. The system prompt says
out loud that this is the safe answer, because the obvious failure of a feature
like this is an eager one that proposes an agent for every selection until the
roster is five near-duplicates nobody maintains. That bias is load-bearing
enough to have its own test
(`test_build_system_instruction_biases_toward_no_gap`), so a later prompt edit
cannot quietly drop it.

When a gap _is_ found you get an editable draft — name, description, full
`SOUL.md` — and **nothing is written until you press Create agent.**
`POST /api/agent-generation/analyze` is strictly read-only; creation stays on the
existing `POST /api/agents` behind an explicit click. That split is deliberate:
this is the one feature in the fork where a model's output would otherwise become
a persistent, privileged object (an agent with its own prompt and tool access)
with no human between the two.

Three properties carry the feature, and each is silent when broken:

- **Read-only analysis.** Pinned by
  `test_analyze_never_creates_the_agent_itself`, which asserts the agent store's
  `create`/`update` are never called on a `propose` verdict. Without it, a
  refactor that "helpfully" persisted the draft would look like a working feature.
- **Per-source ownership.** `require_permission`'s `owner_check` can only see a
  single `thread_id` path parameter, so it cannot cover a _list_ of sources —
  this route checks each thread with
  `ThreadMetaStore.check_access(..., require_existing=True)` and each task through
  `ScheduledTaskRepo.get(..., user_id=…)`, and passes `user_id` into
  `list_messages` so the event store applies its own isolation too. Under §6
  (multi-user mode) this is what stops one user's analysis from reading another's
  conversations. Adding a new source kind means adding its ownership check —
  there is no decorator doing it for you.
- **Bounded prompt.** Threads here routinely run to hundreds of turns with
  multi-megabyte tool payloads, so sources are digested before concatenation:
  tool-result _bodies_ are dropped (the calling assistant turn still names the
  tools it reached for, which is the signal without the bytes), only the most
  recent turns survive, and per-message / per-source character caps apply. The row
  fetch deliberately asks for _more_ rows than the message cap, because digestion
  discards some — fetching exactly the cap leaves a busy conversation nearly empty.

**One injection surface, closed at the source.** Each digest is wrapped in a
`<source …>` block whose body is the user's own text, so a conversation
containing `</source>` could close the block early and have whatever followed
read as prompt structure. `transcript.py::neutralize_block_delimiters` escapes
that shape — for every tag in `BLOCK_TAG_NAMES` (`source`, `goal`, `draft`), with
the same whitespace/attribute tolerance as the production blocked-tag pattern —
before it is embedded. Adding a block tag to a prompt means adding it there too.
This cannot be delegated to `InputSanitizationMiddleware`: that middleware only
rewrites the _lead agent's_ `ModelRequest` and never sees a one-shot
`run_oneshot_llm` call — the same reason the summarizer and memory-updater
blocks are exempted in its anti-drift guard, where `<source>` is now classified
with that reasoning. Only the delimiter shape is escaped, never every angle
bracket: transcripts carry code, and mangling all of it would cost the analysis
the signal it is reading for.

The parse layer coerces a model-authored name ("Weekly Report Writer") to
`^[A-Za-z0-9-]+$` and then suffixes it (`-2`, `-3`…) against your existing
agents, so a draft can never 409 on the create route it is destined for. A
`propose` verdict carrying an empty `SOUL.md` is rejected exactly as
`setup_agent` rejects one (#3549) — an agent without a soul is unusable, and
failing loudly lets you retry instead of leaving a broken draft on screen.

**The optional goal box, and why it does not decide the verdict.** Above the
pickers is a free-text _What should this agent do?_ field. It is deliberately
**optional**: the feature's original value is "read my history and tell me", and
requiring an intent statement would replace discovery with a worse version of the
bootstrap chat. When present it rides in its own `<goal>` block _before_ the
transcripts — a one-line instruction buried under several thousand characters of
transcript is one the model ignores — and the system prompt gains a clause telling
it to weigh the goal as the primary signal of intent while still grounding every
claim in the sources. That clause explicitly forbids restating the goal back as
the `SOUL.md`, because an agent whose soul is the user's own sentence echoed at
them is exactly what `/workspace/agents/new` already does, better.

Crucially, **a goal does not remove the `no_gap` verdict.** Stating what you want
steers the analysis; it does not settle whether the agent should exist. Losing that
would cost the feature its best property, so `test_goal_alone_does_not_remove_the_no_gap_option`
pins that the two-verdict menu survives a stated goal.

**Overriding is a separate, explicit act.** A `no_gap` screen carries a _Generate
anyway_ button, which re-runs with `force_proposal`. That mode **removes** the
`no_gap` option from the prompt rather than merely discouraging it — the user has
already been shown the overlap and decided, so re-offering the verdict would let
the model silently overrule a decision that is no longer its to make. For the same
reason `parse_analysis(require_proposal=True)` treats a `no_gap` reply as a
retryable failure rather than an answer to render. The overlapping agent is still
named and shown on the resulting draft: overriding the verdict must not mean hiding
what it collided with.

**Refining edits the draft; it does not regenerate one.** The result screen carries
a _Refine this draft_ box whose guidance is sent alongside the draft **as it stands
in the form**, hand edits included, in a `<draft>` block. The revision prompt is a
separate, narrower instruction: apply the guidance and change nothing else, do not
re-litigate whether the agent should exist, do not rename it. A revision that
quietly rewrites the untouched half is indistinguishable from a regeneration and
throws away edits the user already made — which is also why a revision keeps the
draft's own name instead of re-uniquifying it against the roster, an operation that
would rename the agent out from under someone mid-edit
(`test_revision_keeps_the_drafts_own_name`). Refining with an empty box is a 422:
"make it shorter" needs something to be shorter _than_.

All three inputs are user-typed text embedded in a prompt, so `<goal>` and
`<draft>` join `<source>` in `transcript.py::BLOCK_TAG_NAMES` and are escaped by
the one shared `neutralize_block_delimiters`; both are classified in the
`test_input_sanitization_middleware.py` anti-drift guard for the same reason
`<source>` is. The goal is capped by `agent_generation.max_goal_chars` (default
2000), enforced in the route rather than as a Pydantic `max_length` so raising the
cap does not need a schema change, and mirrored in the UI so the limit is visible
while typing instead of after a round trip.

On by default via `agent_generation.enabled`, alongside `agents_api.enabled`
(§ the custom-agent API), since that is the route the accepted draft is created
through — the config endpoint reports `enabled` only when **both** are on, so the
UI never offers a draft you cannot save. Both defaulting on matches the fork's
local-trusted, passwordless posture (§5), where the local user is the admin;
`agents_api` still carries admin-equivalent write access to agent SOUL.md / config,
so a deployment that leaves the loopback model behind it should turn it back off.
The Pydantic defaults stay `false` (`agents_api_config.py`,
`agent_generation_config.py`): a config that omits the section entirely still
fails safe, and `config_upgrade.py` never overwrites a value an existing install
has already set — so this flips only what a _fresh_ `make config` writes, not
anyone's hand-set choice. The
analysis call is billed to a new `agent_generation` aux-usage category (§7),
under a dedicated pseudo-thread id: one analysis spans several conversations, so
billing it to any single one would misattribute the cost, and a dedicated bucket
gives it its own row on `/workspace/spend`.

### 21. Concurrent chats — a second prompt without waiting for the first answer

§9 made a background chat _stay mounted_. This makes a background chat _keep
working_: start something slow in one conversation, leave it, and ask a second
conversation something else while the first is still thinking. Both answers
arrive.

Three things had to be true at once, and only the first was.

- **The backend already runs chats in parallel — keep it that way.** The run
  lock is scoped to one thread (`_checkpoint_thread_lock(thread_id)` in
  `runtime/runs/worker.py`), so two chats stream concurrently while two runs in
  _one_ chat still take turns — which they must, since they mutate the same
  checkpoint. Nothing in the suite noticed the difference: a lock widened to a
  process-global one would have passed every existing test and quietly turned
  concurrent chats back into a queue. `backend/tests/test_concurrent_thread_runs.py`
  now pins both directions, the cross-thread case through a rendezvous that
  deadlocks (and times out) the moment the two runs are serialized.

- **Leaving a chat cancelled its run.** `on_disconnect` defaults to `"cancel"`
  (`app/gateway/run_models.py`), and leaving a chat that is not pinned as a tab
  tears its SSE stream down — so walking away from a slow answer to write the
  next prompt killed the answer you walked away to wait for. The submit paths in
  `core/threads/hooks.ts` now send `onDisconnect: "continue"` **explicitly**.
  They arguably did already: the SDK derives that value from `streamResumable`,
  which the fork passes — but `sanitizeRunStreamOptions` **strips
  `streamResumable` before the request** (the Gateway rejects it), so the
  survival of every backgrounded run rested on an SDK default keyed off a flag
  the Gateway never sees. One upstream change to that default and every
  backgrounded chat dies silently. It is asserted now, in
  `frontend/tests/unit/core/threads/run-disconnect.test.ts`, which fails if the
  option is dropped. Coming back to the chat rejoins the live run through the
  existing `reconnectOnMount` path. **This also changes what closing the browser
  does**: a run now finishes on the server instead of dying with the page —
  which is what §16's "get pinged when it's done" push notification always
  assumed, and it is the only reason a phone that locks its screen mid-run still
  gets an answer. The explicit **Stop** button is unaffected: it cancels the run
  through the cancel API, not by dropping the stream, and a runaway run is still
  bounded by the spend cap (§10).

- **Leaving a running chat dropped its live view.** Only _pinned_ tabs are
  keep-alive; the current unpinned slot is replaced on navigation by design. So
  the run survived, but the chat you left went dark until you came back. Now
  `syncRoute` pins a slot it is leaving **while that slot reports a run in
  flight**, reusing the slot key so the mounted instance — stream, scroll,
  panels — is never torn down. Instances report their state through
  `reportBusy(slotKey, isStreaming)`; the strip renders a pulsing dot on a tab
  that is still answering, which is the only signal that a background chat is
  working, and its disappearance is the signal that it is done. Deliberate
  limits: a slot that has **not been promoted to a real thread id** is not
  pinned (a tab is addressed by thread id, and a brand-new chat's id is a
  client-side placeholder until the backend creates the thread), and a **full
  strip declines** rather than evicting a tab someone chose — in both cases the
  run still survives server-side and is rejoined on return. The completion
  notification also fires for a chat that is merely _not the visible slot_, not
  only for a hidden/unfocused document: a background tab is exactly the case
  where the user cannot see the run finish.

**Ollama is the part that needs a hand.** Everything above is about DeerFlow;
with a local model the queue moves into the daemon. Ollama serves
`OLLAMA_NUM_PARALLEL` requests per model at a time — **1** unless raised — and
queues the rest, so the second chat sits at "thinking" until the first finishes
even though both runs are genuinely live. Raising it is a daemon-side setting
(`systemctl edit ollama` → `Environment="OLLAMA_NUM_PARALLEL=2"`), and it has a
cost the sizing has to know about: Ollama allocates a **full KV cache per slot**
(`opts.NumCtx * numParallel` in its scheduler), so N slots divide the affordable
per-chat `num_ctx` by N. `ollama.num_parallel` in `config.yaml` is what tells
`scripts/sync-ollama-models.py` about it — it does not change the daemon, and
the two must be set to match. Set it and each model's synced `num_ctx` shrinks
accordingly, and the VRAM-contention warning (§1) counts the slots too; leave it
unset and the sizing is exactly what it was. `make doctor` reports the effective
number under **Local Models** with the fix, alongside the existing `keep_alive`
advisory — as an `ok`, not a warning, because one slot is a perfectly reasonable
choice on a small GPU.

### 22. Democracy — several models answer, review each other, and one organizes

The fork's other model levers are about spending _less_: a cheap subagent (§3), a
routing policy (§15), a fallback chain (§14). This one deliberately spends more,
for the one thing a single model cannot give you — **a second opinion that did
not come from the same model.** A Democracy run is one **organizer** that gathers
the shared facts once and then puts the identical question to several
deliberately different **panelist** models, has them review each other
anonymously, and synthesizes what came back including where they disagreed.

It is started from **Democracy**, directly under _New chat_ in the sidebar,
which navigates to a setup page of its own at `/workspace/democracy/new`: pick
how many panelists, pick the organizer, pick each panelist's model, choose how
they get graded, write the task and attach any files. Not a mode-dropdown entry —
a panel means nothing without a roster, and setup is the only moment at which the
cost can be shown _before_ it is spent. **A page, not a modal**, for the same
reason _New chat_ is a page: this is the start of a conversation rather than a
preference being adjusted, a roster can run to a dozen rows, and a dialog that
scrolls internally buries the cost warning, which is the one part the user is
meant to read.

**The organizer collects the facts once, and the panel is not asked to check
them.** This is the design decision that makes the mode affordable at all. The
naive reading of "ask five models" has five models each fetch the same Fed rate
decision: five times the retrieval cost, and — worse — five slightly different
datasets, so the panel ends up disagreeing about its inputs while appearing to
disagree about its judgement. The organizer therefore does all retrieval itself,
condenses it into one plain factual brief, and hands **that identical brief** to
every panelist. Facts are then taken as given: sources are recorded so the reader
can judge them and anything known to be contested is flagged, but a verification
round across the panel is exactly the cost this design refuses to pay.

**Every panelist gets the same words.** Varying the brief between panelists
measures your prompts, not their judgement, so the organizer is told at length to
reuse it verbatim. Phase 3 then shows each panelist the others' answers
**anonymized** — a model told it is arguing with a bigger-name model defers to the
name rather than to the argument.

**The synthesis is where a panel goes wrong, so most of the prompt is about it.**
The organizer must report the actual distribution including a lone dissenter,
must not flatten 4-1 into "the panel concluded", must not hold a vote as though
model count were evidence, and must not privilege either its own Phase 1 hunch or
the panelist that happens to be the model it would have picked. A panel that
launders a real disagreement into false confidence is _worse_ than one model,
because it charges five times as much for a more confident wrong answer.

**Files are handed to the composer, not uploaded at setup.** Uploads are
per-thread (`POST /api/threads/{id}/uploads`) and setup has no thread yet, so
there is nothing to upload _against_. The attachments therefore ride a
module-level carrier to the chat the setup page opens and are added to that
chat's composer, where the ordinary upload path takes them on send. They are
deliberately **not** in the localStorage stash beside the rest of the launch: a
`File` is a handle to browser-held bytes and does not survive `JSON.stringify`,
and base64-ing them into localStorage would blow the quota on the first PDF. The
cost is bounded and honest — a hard reload between setup and chat loses the
attachments while the text half of the launch survives, which degrades to a panel
with no files rather than a broken one.

**The panel is standing, and that is a prompt-level guarantee.** Every follow-up
question re-runs the same roster; the user asks one question and gets one
synthesized answer, and the conversation continues from there rather than
branching into per-panelist replies. Subagents get a fresh `ThreadState` per call
and remember _nothing_, so continuity exists only because the organizer carries
it into each dispatch. The section therefore requires every follow-up brief to a
panelist to carry four things: the new question, **that panelist's own previous
answers in its own words**, what the review round argued about, and the previous
final answer. Drop the second and a panelist contradicts itself across turns
without knowing it; drop the last two and the panel re-litigates a point it
already settled, which the user pays for twice. `max_total_per_run` is a **per
run** ledger and each user message is its own run, so the budget refreshes every
turn — the prompt says so explicitly, because an organizer that believed it had
one allowance for the whole conversation would ration a panel that does not need
rationing.

**Grading scores the contribution, never agreement.** The organizer decides the
answer, so it is also the only participant that can say what each panelist was
worth; the scale (`five_point`, `boolean`, or off) is chosen at setup and
forwarded as `democracy_grading`. The criteria are the whole design: did the
panelist engage the shared facts, was its reasoning checkable, did it move for a
stated reason, did it add something nobody else did. **A dissent that turned out
to be right is a high grade and restating the majority view is not**, because
grading proximity-to-my-conclusion would reward the echo and punish the signal —
which is precisely the panelist worth paying for. Grades are per turn, so a
panelist cannot coast on a previous turn's contribution. An unrecognized or
absent scale means _no grading_ rather than a default one: a user who did not ask
for a scoreboard should not find one appended to every answer.

**The load-bearing primitive is one new `task` argument.** `task(model=...)` runs
a single delegation on a named configured model. Its precedence is the whole
feature and is deliberately absolute: it outranks the per-thread subagent
dropdown (§3) and it stands the cost-aware routing policy (§15) **down entirely**,
the same way an explicit per-thread selection does. Either of those winning would
quietly run several panelists on one cheap model, and the run would then report N
independent opinions that came from one model — a wrong answer wearing the
costume of a right one. For the same reason an **unknown model name fails that
one delegation** rather than falling back to the inherited model: a loud failure
leaves the rest of the panel intact and tells the organizer what to fix, while a
silent substitution is undetectable in the output.

**The roster is filtered, never trusted.** `normalize_democracy_participants`
drops names that are not configured models and returns _no panel_ when fewer than
two distinct models survive — a "panel" of one model asked twice is one opinion at
twice the price. A thread whose `config.yaml` changed underneath it therefore
degrades to an ordinary Ultra run rather than dispatching panelists onto models
that no longer exist.

**The delegation budget travels with the panel.** `subagents.max_total_per_run`
defaults to **6**; a three-model panel needs 6 for its happy path alone, and
`task` calls beyond the ledger are _discarded with their work lost_. So the
frontend — the only layer that knows the panel size — sends `max_total_subagents`
sized at participants x 2 phases plus headroom for a retry. Without it the panel
is silently truncated partway through phase two and the organizer synthesizes
from whichever panelists happened to fit. Real _concurrency_ is still capped by
the startup-frozen `subagent_runtime.max_running` (default 3), so a five-model
panel queues rather than over-subscribing; raise it in `config.yaml` and restart
if you want the whole panel in flight at once.

**The organizer section rides `{subagent_section}`, not a placeholder of its
own.** An operator who saved a custom `SYSTEM_PROMPT.md` (§19) before this feature
existed has no `{democracy_section}` in their template, and a missing placeholder
is silently dropped by `str.format` — they would have got a panel with no
organizer rules at all. A panel is dispatched entirely through `task`, so any
template that can run one already carries the subagent block; appending there
means the rules cannot go missing from a working configuration.

**`<democracy_panel>` is a framework authority block, so it is denylisted.** The
section tells the lead which models the panel runs on and how to weigh their
answers, which makes a counterfeit copy in user input a way to re-roster or bias
a panel from inside the message. It is therefore registered in
`InputSanitizationMiddleware._BLOCKED_TAG_NAMES` alongside `<subagent_system>`
and the rest. `tests/test_input_sanitization_middleware.py::test_denylist_covers_framework_authority_blocks`
scans the harness for paired tags and fails on any that is neither blocked nor
explicitly exempted — so this is enforced for the next such block too, not just
this one.

**Warnings, and what they can honestly say.** The dialog states the number of
full model runs the panel will dispatch and — computed from the `price:` blocks
already on `/api/models` — roughly how many times a single organizer answer the
panel's _rates_ come to. Deliberately a **rate multiple, not a currency figure**:
predicting a run's token count would be a guess dressed as a number, and this
fork's cost surfaces (§7) only ever report money actually spent. Unpriced local
models contribute zero, exactly as everywhere else, and are **named** so that a
suspiciously low multiple explains itself instead of reading as a bug. The
existing controls still apply on top: `spend_budget` (§10) refuses a run at
admission with HTTP 402, and the per-step cost chart (§7) prices a Democracy turn
per model, so the panel's real cost shows up per panelist afterwards. The warning
also says the charge is **per question**, since a standing panel bills again on
every follow-up — a figure the user reads as a one-off would understate the
conversation by however many turns it runs.

**No new config keys.** The whole feature is per-run context, so there is nothing
to add to `config.yaml`, no `config_version` bump, and no Helm chart copies to
keep in step. The two existing knobs that matter to it —
`subagents.max_total_per_run` and `subagent_runtime.max_running` — already exist.

| Piece                                                   | Where                                                                                                                                                                           |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Per-call model + precedence                             | `tools/builtins/task_tool.py` (`resolve_requested_subagent_model`, the `model` argument, and the block that writes `subagent_model_override` **before** `apply_routing_policy`) |
| Roster + organizer prompt                               | `agents/lead_agent/democracy.py` (`normalize_democracy_participants`, `build_democracy_section`, `DEMOCRACY_SECTION_TEMPLATE`)                                                  |
| Prompt wiring                                           | `agents/lead_agent/prompt.py` (`apply_prompt_template(democracy_participants=...)`, appended to `subagent_section`); roster resolved in `agents/lead_agent/agent.py`            |
| Context forwarding                                      | `app/gateway/services.py::_CONTEXT_CONFIGURABLE_KEYS` (`democracy_participants`)                                                                                                |
| Prompt-injection denylist                               | `agents/middlewares/input_sanitization_middleware.py::_BLOCKED_TAG_NAMES` (`democracy_panel`)                                                                                   |
| Launch spec, grading scale, cost estimate, file carrier | `core/threads/democracy.ts`                                                                                                                                                     |
| Mode → run context                                      | `core/threads/run-context.ts` (`deriveModeContext`, shared by the submit and regenerate paths)                                                                                  |
| Setup page + entry point                                | `app/workspace/democracy/new/page.tsx`, `components/workspace/democracy-setup.tsx`, `workspace-header.tsx`; handoff in `chats/use-democracy-launch.ts`                          |
| Tests                                                   | `backend/tests/test_democracy_panel.py`, `frontend/tests/unit/core/threads/democracy.{test,dom.test}.ts`, `frontend/tests/e2e/democracy-panel.spec.ts`                          |

### 23. Local image and video generation (ComfyUI, a GPU arbiter, and a refine loop)

The fork's central move, applied to a second modality. Text inference already has
a free local tier — Ollama, auto-synced, priced at zero (§1). Images and video did
not: both bundled media skills call MiniMax or Gemini over HTTPS, so every picture
cost money and every prompt left the house, which is exactly the pair of properties
this fork replaced for chat. Roadmap items 12–15 in one change set.

**Why a Gateway-side tool and not a skill script.** The two cloud media skills are
Python scripts that run _inside the sandbox_. Following that shape here would tie
the feature to the sandbox mode: a remote AIO container cannot reach a host GPU,
a local container can only reach it through a bind mount, and the host-local
sandbox is a different filesystem again. The tool runs in the Gateway process and
writes straight to the thread's host-side outputs directory — the same path
`present_files` normalizes against — so it is correct under _every_ sandbox mode,
including the per-thread container one. It also puts the process-wide GPU
semaphore on the same side of the wall as the code that generates, which a
subprocess could not do.

**ComfyUI, not a simpler HTTP wrapper.** The deciding feature is `/object_info`:
the enum on `CheckpointLoaderSimple.ckpt_name` _is_ the list of installed
checkpoints, and the same is true for unets, VAEs, text encoders, samplers and
schedulers. That single endpoint is what lets one sentence pick a model, keeps
model names out of the code entirely, and makes a fresh install with exactly one
checkpoint work with no configuration. It is also what makes template validation
possible.

**Templates plus typed parameters — the model never authors graph JSON.** A model
that can emit arbitrary node graphs can also load arbitrary files and run arbitrary
custom nodes on the machine holding the GPU and the data. So the graphs are files
an operator can read (`templates/*.json`, ComfyUI's API format), the model passes
`prompt`/`seed`/`steps`/`cfg`/dimensions/checkpoint, and a parameter the template
does not bind is an **error** rather than a silent no-op — a dropped seed is what
turns an iteration loop into a slot machine. Each template file wraps the
submittable graph in binding metadata so that metadata never reaches ComfyUI, and
the submitted graph alone is saved beside every output as `<name>.workflow.json`:
it opens in ComfyUI's own editor and reproduces the result by hand, which is the
whole of the "inspect how the nodes are set up" requirement.

**Validation names the node that moved.** API-format graphs address nodes by
numeric id, so a custom-node update or a renamed input silently invalidates a
template and ComfyUI's native complaint is a validation dump. `validate_template`
compares the graph against `/object_info` and returns sentences naming node and
input. It runs at _first use per (base_url, template)_, cached for the process —
**not** at Gateway startup, because ComfyUI is usually not running when the
Gateway boots and a startup check that cannot reach the service checks nothing.
`make doctor` runs the reachable version of the same idea.

**The URL guard is used, not bypassed.** A loopback ComfyUI is the textbook
intentional-internal-target case, so it goes through the shared
`validate_public_http_url` with the documented `allow_private_addresses` opt-out —
defaulted to `true` for this tool, unlike the web tools. Bypassing the guard for
"it's just localhost" would make the setting dead, and the day someone points
`base_url` at a public host there would be nothing to turn on.

#### The GPU arbiter (roadmap 13)

A language model and a diffusion model both want the whole card, and on a 24 GB
consumer GPU they do not both fit. **The failure is silent, which is the entire
reason this exists:** Ollama does not error when weights do not fit, it offloads
layers to system RAM and answers several times slower. Five properties are
load-bearing:

1. **Eviction happens inside the tool call.** An agent turn is a chain of model
   calls, so the lead model reloads the moment a tool returns; a swap sequenced at
   the plan level therefore puts both tenants on the card at once. `generate_image`
   evicts, generates, evicts itself, and returns an empty card. The agent never
   needs to know VRAM exists.
2. **Tenants, not special cases.** Each declares `location: local | cloud`. A cloud
   tenant is never resident, so every eviction against it is a no-op _without a
   branch of its own_ — switch the lead to a cloud model and the swapping stops.
3. **Verify, never assume.** Residency is re-read per acquire (Ollama `/api/ps`,
   ComfyUI `/system_stats`, `nvidia-smi` as tiebreak) rather than trusted from
   in-process bookkeeping. A Gateway that died mid-generation leaves the card held;
   the tiebreak — VRAM in use while no tenant claims it — is what recovers that on
   the next acquire instead of on the next restart.
4. **The policy is computed and logged.** `auto` derives exclusive vs. shared from
   `budget_gb - reserve_gb` against the sum of local tenant estimates, with the
   reasoning in the log line. That is what makes a later GPU upgrade a config
   outcome rather than a code change: a bigger card resolves to `shared` on its own
   and the swapping stops. `budget_gb: auto` reuses
   `scripts/wizard/steps/ollama.py::detect_vram_gb` — do not write a second
   detector.
5. **Ollama's eviction is per request.** `keep_alive: 0` is passed on the eviction
   call only; the global `ollama.keep_alive` exists to stop subagent cold starts
   and keeps its value for ordinary chat. A global override would reintroduce
   exactly the problem it was added to fix.

One depth-1 semaphore, per event loop, serializes _tenants_ rather than callers —
two threads generating at once would otherwise thrash with neither finishing — and
a caller that waits is told it is waiting.

#### The refine loop (roadmap 14)

Local generation is free at the margin, which changes what is worth doing: four
attempts on a metered API cost four times as much, on your own GPU they cost
electricity. First-attempt diffusion quality is genuinely poor, and iteration is
how good results are actually produced.

**The agent owns the loop; there is no loop engine.** `skills/public/image-refine/`
instructs generate → view → judge → adjust → repeat. Building the loop inside a
tool that calls the model itself would bypass the run journal's per-model token
accounting, hide the reasoning from the transcript, and break streaming.

What the server holds is exactly what a model cannot be trusted with:

- **The rubric is frozen before iteration 1** — 3–6 checkable criteria, and a
  verdict may not judge anything outside them. An open-ended "is this good?"
  either accepts immediately or never converges, because the standard drifts with
  each look.
- **The counter is at the tool boundary.** The tool returns a `session_id`, the
  server counts, and iteration N+1 is _refused_ with a message written to be
  reported verbatim. Models lose count; this is the classic way these loops run
  away. Same for the wall-clock budget, which is what makes video safe to iterate
  on. A failed generation still consumes its iteration — otherwise a loop that
  fails every time never stops.
- **One named change per retry**, rejected when it reads as several. One change
  per iteration is what makes the loop diagnosable.
- **Seed discipline is instructed, not enforced** — hold the seed when changing
  wording or weights so the delta is attributable; changing the seed is itself the
  one change, for an unlucky composition. It cannot be enforced without deciding
  for the model _which_ change it is making.

The session JSON beside the outputs (criteria, and per iteration the params, seed,
verdict and filename) is the audit trail — it is what makes "target achieved"
reviewable rather than asserted. And the skill says out loud that a text-only local
lead has no judging step at all, because `view_image` is only bound when the model
reports vision support: better a documented refusal than a loop that quietly
degrades to the model guessing at its own output.

#### Video (roadmap 15)

Two constraints shape it. **No model can watch an MP4** — `view_image` takes
png/jpg/webp/gif only, capped at 20 MB — so the template saves the decoded frames
alongside the assembled clip and the tool writes evenly spaced stills _and_ one
tiled contact sheet. The sheet is the better critic input for two independent
reasons: one `view_image` call instead of six (vision tokens are billed per image,
every round, on a cloud lead), and temporal faults — flicker, morphing, identity
drift — read far more clearly side by side than frame by frame. `select_indices`
includes both endpoints deliberately: drift shows up at the ends, and a sheet
sampled from the middle hides the fault the critic is looking for. Pillow is
imported lazily and a missing Pillow degrades to "no contact sheet" with a named
error — it must never lose a clip that took minutes to render.

**Minutes per clip** is why `video_timeout` is its own config value rather than the
image budget or an inherited default: one shared timeout either abandons working
clips or lets a wedged image run hold the GPU for half an hour. Being a
Gateway-side tool, it is also not bound by `sandbox.bash_command_timeout`.

The shipped default template stays on core ComfyUI nodes so a stock install
validates; `txt2video-gguf` is offered alongside it and the config comments say
why GGUF is preferred over fp8 on a 24 GB card — Ampere and older have **no FP8
tensor cores**, so fp8 saves memory but runs the matmuls by emulation. That is a
stated trade-off in the comments, not a silent choice.

#### Service, not sandbox tenant

ComfyUI is a long-lived service holding weights between requests, so it follows the
SearXNG pattern: a compose file (`docker/docker-compose.comfyui.yml`), a
loopback-only published port (the ComfyUI API has no authentication at all and can
read and write files on the machine holding the GPU), `make comfy-up` /
`comfy-down` / `comfy-logs`, and a `DEER_FLOW_COMFYUI_BASE_URL` override
documented in `.env.example` — named without `KEY`/`TOKEN`/`SECRET` so
`env_policy.build_sandbox_env` does not scrub it from skill subprocesses.

`scripts/detect_comfyui.py` reuses first and provisions second, exactly like its
SearXNG sibling — an instance you already run is found and exported (the point:
two ComfyUIs on one card is how a GPU ends up thrashing), and only when nothing
answers is the bundled container started. It carries one gate SearXNG does not
need, because the surprise it used to avoid is real: a multi-gigabyte GPU
container has preconditions a metasearch container does not. See §26 for that
gate and why the two halves of "on by default" are one decision.

**Not vendored: the image.** ComfyUI publishes no official container image, so the
compose file names a community build behind `DEER_FLOW_COMFYUI_IMAGE` and the
comments tell the operator to pin the dated tag their driver needs. Models are
never baked in or downloaded automatically — that is roadmap item 16's problem, and
it is deliberately still open.

**Not declared: Pillow.** `uv lock` cannot currently be re-run in this repo at all —
the pre-existing `tenki` extra's `tenki-sandbox` 404s on PyPI, so any `pyproject.toml`
change makes every `uv run` fail to resolve. Pillow arrives transitively via
`markitdown[all]`; the import is lazy and names itself in the error. When the
`tenki` dependency is fixed, add `comfyui = ["pillow>=11.0"]` as an extra and map
`generate_video` to it in `scripts/detect_uv_extras.py`.

| Piece                                                              | Where                                                                                                                                                                                                                                                                                                                                                               |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| HTTP transport (submit/poll/view/object_info/free/system_stats)    | `community/comfyui/client.py`                                                                                                                                                                                                                                                                                                                                       |
| Templates + validation + patching                                  | `community/comfyui/templates.py`, `community/comfyui/templates/*.json`                                                                                                                                                                                                                                                                                              |
| Config/env resolution, URL guard, model resolution, output writing | `community/comfyui/service.py`                                                                                                                                                                                                                                                                                                                                      |
| GPU residency arbiter                                              | `community/comfyui/arbiter.py`                                                                                                                                                                                                                                                                                                                                      |
| Refine sessions (frozen rubric, counter, budget, verdicts)         | `community/comfyui/sessions.py`                                                                                                                                                                                                                                                                                                                                     |
| Stills + contact sheet                                             | `community/comfyui/frames.py`                                                                                                                                                                                                                                                                                                                                       |
| Agent tools                                                        | `community/comfyui/tools.py` (`generate_image`, `generate_video`, `list_media_models`, `refine_start`, `refine_verdict`)                                                                                                                                                                                                                                            |
| The loop itself                                                    | `skills/public/image-refine/SKILL.md`                                                                                                                                                                                                                                                                                                                               |
| Config                                                             | `config.example.yaml` → `media:` (`config_version` 44), `deploy/helm/deer-flow/{values.yaml,README.md}`                                                                                                                                                                                                                                                             |
| Service                                                            | `docker/docker-compose.comfyui.yml`, `scripts/detect_comfyui.py`, `scripts/comfyui.sh`, `Makefile` (`comfy-up`/`comfy-down`/`comfy-logs`), launch wiring in `scripts/{serve,docker,deploy}.sh`                                                                                                                                                                      |
| Model files                                                        | `scripts/comfyui_models.py`, `Makefile` (`comfy-models`/`comfy-model-add`) — see §26                                                                                                                                                                                                                                                                                |
| The button                                                         | `frontend/src/core/threads/image-generation.ts`, `components/workspace/image-generation-setup.tsx`, `app/workspace/image/new/page.tsx`, `components/workspace/chats/use-image-launch.ts`, the sidebar entry in `components/workspace/workspace-header.tsx` — see §26                                                                                                |
| Doctor                                                             | `scripts/doctor.py::check_media_generation` (service reachable + VRAM held while idle)                                                                                                                                                                                                                                                                              |
| Invariants for agents                                              | `backend/packages/harness/deerflow/community/comfyui/AGENTS.md`                                                                                                                                                                                                                                                                                                     |
| Tests                                                              | `backend/tests/test_comfyui_tools.py`, `test_gpu_arbiter.py`, `test_refine_session.py`, `test_comfyui_video.py`, `test_detect_comfyui.py`, `test_comfyui_models.py`, `test_doctor.py::TestCheckMediaGeneration`, `frontend/tests/unit/core/threads/image-generation{,.dom}.test.ts`, `frontend/tests/unit/components/workspace/image-generation-setup.dom.test.tsx` |

### 24. Tiered voice input — on-device, then your own server, then nobody

The composer had a microphone button before this change, and it was the single
place where the fork's privacy claim was false in a way nothing surfaced.

`SpeechRecognition` does not recognize speech in the browser. Chrome's
implementation streams the audio to Google, Safari's to Apple — and it does so
**from the browser directly**, over the public internet, never touching the
Gateway. So none of the work that makes this fork private applied to it: not the
self-hosting, not the auth, not the tailnet. A user who chose this fork
specifically to keep their data home was shipping their voice to a model vendor
by pressing the obvious button, and the tooltip said "audio is handled by your
browser or system speech service", which is true and completely misleading.

**Four properties are load-bearing; a refactor must not "simplify" any away.**

**1. The order of the tiers, and the fact that the last one is off.**
`resolveVoiceInputTier` tries on-device, then the server, then the vendor cloud,
and `voice.allow_cloud_fallback` defaults to false. An install with neither of
the first two reports voice as _unavailable_. That is the feature working. The
tempting "fix" — restore the old behavior as a silent last resort so the button
always does something — is precisely the bug, and it is invisible once made:
everything keeps working, and the audio goes back to Google.

**2. Both sides default closed.** The frontend's `DEFAULT_VOICE_SERVER_CONFIG`
repeats the server's defaults rather than assuming an answer, so a Gateway that
is slow, erroring, or unreachable produces "no cloud" rather than "cloud". A
capability probe that fails open is a privacy switch that turns itself off under
load.

**3. Tailscale's CGNAT range counts as local.** CPython classifies
`100.64.0.0/10` as neither `is_private` nor `is_global`, so the shared
`url_safety.is_blocked_address` predicate reads a tailnet peer as a public host.
Reaching the stack over Tailscale is this fork's documented access path, so
without the explicit CGNAT check in `is_local_endpoint`, a user's own home server
would be labelled as sending their audio off the machine. **Do not fix this by
widening `is_blocked_address`** — that predicate governs what the _web_ tools may
fetch, and adding CGNAT there would newly refuse tailnet URLs to all of them. The
two questions look identical and point opposite ways: the shared guard stops the
Gateway reaching _into_ private space; this feature's risk is an endpoint that
sends audio _out_. Neither subsumes the other.

**4. The microphone is always released.** Every exit from `startRecording` —
success, recorder error, a container the browser refuses to construct, a thread
switch mid-recording — stops the `MediaStreamTrack`. A live track keeps the
browser's recording indicator lit, which on a phone reads as an app that is
still listening. This is the one property with no server-side symptom at all: it
is silent in every log and every test that only checks transcripts, which is why
`recorder.test.ts` asserts on track release in each of those four paths
specifically.

Two smaller decisions worth not re-litigating. The size cap is enforced _while_
reading the upload rather than after, because the point is never to hold an
arbitrary body in memory — a length check on a completed `read()` passes the same
tests and defeats the purpose. And error strings never echo the transcription
service's response body: a transcript is speech, and speech in a log file
outlives the conversation it came from.

The engine is deliberately unnamed. The client speaks the OpenAI
`/v1/audio/transcriptions` shape, which faster-whisper-server, speaches,
whisper.cpp's `server` and LocalAI all implement, so the operator picks a backend
and the fork stays out of the argument — the same reasoning that keeps ComfyUI a
service rather than an in-process dependency (§23).

Depth for agents editing this lives in
[`backend/packages/harness/deerflow/community/speech/AGENTS.md`](backend/packages/harness/deerflow/community/speech/AGENTS.md).

### 25. Documents bigger than the window, and PDFs with nothing in them

Two failures sit behind "the local model is bad at PDFs", and they are not the
same failure. Separating them is most of the design.

**The window.** A 300-page filing is well past a 32K-token model. Upstream's
shape was already right — the agent gets a heading outline and is told to
`read_file` ranges and `grep`, never the document body — but the sizes around it
were fixed character constants calibrated for a 200K cloud model:
`read_file_output_max_chars: 50000` is ~12.5K tokens in **one** tool result, about
40% of a 32K window and larger than an 8K window outright, and
`summarization.trigger: 32000` equals the entire window of a synced Ollama entry,
so compaction fires only after the window has already overflowed. Worse, the
navigation itself is a multi-step tool loop, and instruction-following on long
input is the first thing 4-bit quantization costs you (arXiv 2505.20276: up to
59% on long-context tasks, >10% on IFEval, against ~0.8% for 8-bit). The
documents that most need help are the ones where the loop breaks down first.

**The text layer.** `pymupdf4llm` extracts a PDF's _text layer_. A scan has none,
so conversion returns success and a near-empty file, and the MarkItDown fallback
does not OCR either. Nothing downstream could tell that apart from a genuinely
short document, so the agent summarised an empty file with total confidence. This
is the worse of the two failures precisely because it is indistinguishable from a
bad answer.

**What the fix is shaped like.** One resolver
(`deerflow/utils/context_budget.py`) reads the serving model's usable window —
Ollama's `num_ctx`, a config entry's `context_window`, or the provider profile —
and subtracts the output reservation, because `num_ctx` covers prompt _and_
generation: `num_ctx: 32768` with `num_predict: 8192` is 24576 tokens of prompt
space, not 32768. Everything else is derived from that: the sandbox truncation
caps, the `tool_output` thresholds, and the chunk size for
`analyze_document`. `ToolOutputBudgetMiddleware` is where it lives, because it is
the only place in the loop holding both the serving model and the tool results;
it publishes the resolved budget in a ContextVar for the duration of each tool
call, which is how the sandbox tools — which have no model reference and take no
new argument — participate.

Four properties are load-bearing, and each is the one a refactor would remove:

- **A configured limit is a ceiling, never a floor.** `clamp_to_context` only
  lowers. An unknown window is a no-op, so a provider that declares nothing
  behaves byte-for-byte as before, and an explicit `0` ("no limit") is never
  turned back on. Without this the feature is a behaviour change for every
  existing install rather than a fix for small models.
- **Transcribe and summarise are separate passes.** The vision model is told to
  transcribe and nothing else (`TRANSCRIBE_PROMPT`), and the map-reduce runs over
  the transcript afterwards. Folding them together is the cheaper implementation
  and the one that silently loses content: a model asked to summarise while
  reading chooses what to drop before anyone has seen the document.
- **Coverage is reported, not implied.** `AnalysisResult.coverage_line()` states
  how many parts were read, how many contributed, how many could not be read, and
  whether `max_chunks` stopped it early — and that line goes into the string the
  agent gets back. A partial read that reads as complete is worse than a refusal.
- **The reduce is hierarchical.** Notes that outgrow the window are merged in
  rounds. Without it a long document just moves the overflow from the map stage
  to the reduce stage, which is the failure this feature exists to remove.

Two smaller decisions worth not re-litigating. Page anchors (`<!-- page: 12 -->`,
from pymupdf4llm's `page_chunks=True`) are HTML comments so they survive every
Markdown consumer while rendering as nothing, and `assess_extraction` excludes
them from its character count — otherwise a scan of 200 blank pages looks like
4KB of content and never trips the sparse check. And an all-failed OCR run is
deliberately **not** cached: caching it would make the failure permanent.

One upstream-shape rule to keep: `_do_convert(file_path, pdf_converter) -> str`
stays the single string-returning conversion seam. It is what the existing tests
patch and what a sync will touch; the quality report is computed by the caller
from the converted text instead, which is why `ExtractionQuality` takes a page
count rather than a converter handle.

This also closes a gap the audit turned up on the way past:
`scripts/sync-ollama-models.py` wrote `num_ctx` but never `context_window`, so
`subagents/routing.py`'s guard (`if context_window and estimated > context_window`)
short-circuited on `None` for every local model — cost-aware routing could send a
large-document subagent to a model whose window could not hold the prompt, which
is exactly the trade `config.example.yaml` says it refuses to make.

Depth for agents editing this lives in
[`backend/packages/harness/deerflow/documents/AGENTS.md`](backend/packages/harness/deerflow/documents/AGENTS.md).

### 26. Image generation that is already on — provisioned, stocked, and one click away

§23 built the local media tier and then left three things between a fresh
checkout and a picture: five commented-out tool entries, a `make comfy-up`
nobody runs unprompted, and a models directory the user has to find. Each was
defensible on its own; together they meant the feature existed and almost nobody
had it. This closes all three.

**"On by default" is one decision with two halves, not two features.** The tool
entries in `config.example.yaml` are active _because_ every launch path now
resolves-or-provisions the service; provisioning is worth doing _because_ the
entries are active. Break either half and the other becomes wrong in a way
nothing reports: `scripts/detect_comfyui.py` reads `config.yaml` to decide
whether to bother, so re-commenting the entries silently switches the whole
feature off, and active entries with nothing behind them fail at chat time on a
fresh machine. `test_config_example_ships_the_tools_enabled` and the detector's
own `config_uses_comfyui` tests pin the pair.

**Provisioning is gated, because the gate is what makes "on by default" safe.**
The bundled image is gigabytes and its compose service _reserves an NVIDIA
device_, so starting it on a laptop with no GPU does not degrade — it fails at
`compose up`, in the middle of an unrelated `make dev`. `autostart_decision()`
therefore answers a different question from `resolve()`: not "which endpoint"
(a pure function of the probes) but "may we provision one here", which depends
on Docker **and** a detected GPU (reusing `detect_vram_gb`, the same detector the
arbiter uses for `budget_gb: auto` — there is still only one). Both wrong answers
are quiet, so every branch carries a reason and the reason is printed:
provisioning where it cannot work produces a confusing compose error, and
declining where it _would_ work leaves the user with tool errors and no hint that
one command fixes them. `DEER_FLOW_COMFYUI_AUTOSTART` overrides in both
directions — `0` never starts one, `1` starts it where the detector cannot see
the passthrough (WSL, a rented box).

On a machine that fails the gate the tools stay **bound**, and that is
deliberate: they answer with a message naming the unreachable endpoint, which is
what lets the agent fall back to the cloud `image-generation` skill. Unbinding
them would have made the fallback a config edit instead of a sentence. `make
doctor` follows the same rule — it _skips_ with the reason rather than warning,
because a warning on every GPU-less laptop is how a real warning stops being
read.

**The bundled container stays out of the stack's compose project.** It is
started by `scripts/comfyui.sh` under its own project (`deer-flow-comfyui`) and,
in the Docker paths, attached to the stack network afterwards, so the gateway
resolves it as `http://deer-flow-comfyui:8188`. Making it a service of the main
project would have been less code and one silent hazard: `deploy.sh` runs
`up --remove-orphans`, which deletes containers the compose files do not
mention — so a ComfyUI started by any other path would be torn down, GPU and all,
by an unrelated restart. `up` is also idempotent by inspection rather than by
compose (`docker inspect` first): a container that is already running is left
alone, because recreating it evicts the weights it is holding.

**Weights are never provisioned — models directories are found.** A checkpoint
is gigabytes and its licence is the user's to accept, so `make comfy-model-add`
installs one _you_ name, into whichever ComfyUI is in use. That last part is the
whole difficulty: for the bundled container the directory is a bind mount we
own, but for an instance you already run it is wherever you installed it, and a
perfectly successful 6 GB download into the _other_ ComfyUI looks exactly like
success. Resolution is therefore explicit and reported — `--models-dir`, then
`DEER_FLOW_COMFYUI_EXTERNAL_MODELS`, then the host side of that container's own
`…/models` mount (read from `docker inspect`, the only place the mapping is
written down), then well-known install paths — and it **refuses** rather than
falling back to the bundled directory. Downloads land on a `.part` file and are
renamed only once complete and checksum-verified, because ComfyUI lists whatever
is in the folder: a truncated checkpoint fails _inside_ a generation, where it
reads as a broken template rather than a broken file. The model name reaches the
filesystem and its usual source is a URL, so a name carrying a separator or a
parent reference is refused outright rather than sanitized. Afterwards the
loader's own enum is re-read, because a file in the wrong folder installs fine
and never loads.

**A button, for the same reason Democracy has one.** Generating is the start of a
conversation, and a few decisions belong before the first model call rather than
in it: image or clip, what shape, which checkpoint, whether to iterate. So it is
a sidebar entry and a page (`/workspace/image/new`), not a modal and not a hidden
mode flag. The page **seeds the composer instead of sending** — a clip is minutes
per attempt, and the request is worth one last look — and it seeds an ordinary
instruction rather than calling a tool, which is what keeps every path reachable
from one button: the local tools, the cloud skill when no instance is reachable,
and the refine loop when the box is ticked. The pixel size is written into the
seed because a model asked for "landscape" picks its own numbers, and the ones it
picks for a clip are the ones that run out of VRAM several minutes in. The
handoff itself is the Democracy handoff, including its trap: the setup page has
no thread id to write to, so the launch is stashed and claimed on mount _and_ on
the launch event — navigating to `/workspace/chats/new` from a chat already on
`/new` does not remount, and a mount-only claim would silently do nothing.

**Who writes the prompt is a setting, not a guess.** The page began with one text
box that had to mean two incompatible things. Someone pasting a prompt they
already have — weights, tags, a seed they are holding — needs it submitted
_unchanged_, and an assistant that helpfully expands it has quietly run a
different experiment; someone describing a picture in ordinary words needs
exactly that expansion, because "a rainy Tokyo street" is not prompt vocabulary.
So the mode is an explicit toggle and it travels **in the seed**: `direct` puts
the prompt in verbatim and forbids the rewrite in as many words, `assisted` asks
for a positive _and_ a negative prompt and requires both to be shown before
anything is generated — a negative prompt the model invented and never displayed
cannot be corrected, and reads afterwards as an unexplained result.

**The negative prompt is offered, written, or explained away — never silently
absent.** Guidance- and step-distilled checkpoints (Flux, turbo, lightning, LCM,
Hyper) sample at CFG 1, where the negative branch is never evaluated: the prompt
is not rejected, it is ignored, and a field that accepts text the sampler will
never read is the worst of the three outcomes. `supportsNegativePrompt` reads the
model _name_ — whole words plus glued version digits, so `flux1-dev` matches and
`hyperrealism_v3` does not — because the page deliberately does not call the
tools and so cannot ask ComfyUI what the file is. That makes the rule a
heuristic, so it errs toward **offering** the field: a wrongly hidden one removes
a capability outright, while a wrongly offered one is caught downstream, by the
agent that does have `list_media_models` and is asked in the assisted seed to say
so and fold the exclusions into the positive prompt instead.

**A shape is not a resolution.** The four aspect names covered the sizes a 24 GB
card runs and nothing else, so anyone with a target size — a print, a wallpaper,
a thumbnail sheet — had no way to ask for one. Width and height are numbers now,
with the presets _seeding_ them rather than standing in for them. Two guards keep
that freedom from turning into a slower failure. A value is snapped to the latent
grid (ComfyUI's latent is pixels / 8, so an unsnapped number renders at a size
nobody asked for) and the **snapped** number is what the preview states, so what
runs is what is on screen. And the upper bound is per-kind for the same reason
the presets are: an oversized image fails in seconds and costs nothing, while an
oversized clip fails after minutes of rendering. A cleared box is refused rather
than quietly restored to the preset it just replaced — falling back there would
generate at the size the user had just deleted.

**Delivery to configs that already exist.** `config_version` moves to 47, and
`config_upgrade.py::backfill_missing_default_tools` appends tool entries missing
by name — so an existing `config.yaml` gains the five media tools on the next
`make config-upgrade` rather than staying quietly without them. This is the same
question §17 raises about prices, and it has the same answer: a change to
`config.example.yaml` reaches a fresh install for free and an existing one only
through the upgrade path.

| Piece                 | Where                                                                                                                                                                                                                                                                                                        |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Provisioning decision | `scripts/detect_comfyui.py` (`autostart_decision`, `gpu_present`, `bundled start` / `bundled hold`)                                                                                                                                                                                                          |
| Service control       | `scripts/comfyui.sh` (`up`/`stop`/`down`/`logs`/`attach`), launch wiring in `scripts/{serve,docker,deploy}.sh`                                                                                                                                                                                               |
| Model install         | `scripts/comfyui_models.py`, `Makefile` (`comfy-models`, `comfy-model-add`)                                                                                                                                                                                                                                  |
| Config                | `config.example.yaml` (active `media` tool entries, `config_version: 47`), `deploy/helm/deer-flow/values.yaml`                                                                                                                                                                                               |
| Env                   | `.env.example` (`DEER_FLOW_COMFYUI_AUTOSTART`, `DEER_FLOW_COMFYUI_EXTERNAL_MODELS`)                                                                                                                                                                                                                          |
| Button                | `frontend/src/core/threads/image-generation.ts` (prompt mode, negative-prompt rule, resolution), `components/workspace/image-generation-setup.tsx`, `components/workspace/chats/use-image-launch.ts`, `app/workspace/image/new/page.tsx`, `components/workspace/workspace-header.tsx`, `core/i18n/locales/*` |
| Doctor                | `scripts/doctor.py::check_media_generation` (skips with a reason where nothing would be provisioned)                                                                                                                                                                                                         |
| Tests                 | `backend/tests/test_detect_comfyui.py`, `test_comfyui_models.py`, `test_comfyui_tools.py::TestServiceWiring`, `test_doctor.py::TestCheckMediaGeneration`, `frontend/tests/unit/core/threads/image-generation{,.dom}.test.ts`, `frontend/tests/unit/components/workspace/image-generation-setup.dom.test.tsx` |

### 27. An internet switch on the conversation

The globe in the composer, between the microphone and the prompt-polish button.
Off means this conversation's runs are assembled with **no internet-reaching tool
in them**: the `web` and `browser` tool groups, every MCP tool, and the ACP agent
tool are left out of the catalog before the agent is built. Lead agent and
subagents alike. It is per conversation, needs no config key, and is an opt-out —
absent means on.

Four properties are load-bearing. Each one is **silent** when broken: the chat
keeps answering, it has just quietly got its web tools back.

**1. It is a capability filter, not a request-time veto.** The filtering happens
inside `get_available_tools`, before anything downstream sees a catalog — so
deferred tool search cannot promote a dropped tool back, a skill's
`allowed-tools` cannot re-admit one, and the model is never shown a schema for a
tool it may not call. Enforcement in a middleware would have been easier to write
and one exemption away from being bypassed; the authorization layer already
learned that lesson (its Layer 1 capability filter exists for the same reason).
Do not "simplify" this into a `GuardrailProvider` that denies at call time.

**2. Absent is not "off".** Only an explicit boolean `False` opts out
(`internet_access_enabled`). IM channels, the TUI, the scheduler and the embedded
client have no composer and send no key; reading a missing key as "offline" would
take web search away from every non-web caller on the day this ships. `"false"`
and `0` are _not_ opt-outs either — the frontend normalizes to a real boolean
before sending (`resolveInternetEnabled`), so anything else is a caller with no
opinion.

**3. The classification fails closed.** `OFFLINE_ALLOWED_TOOL_GROUPS` is an
allowlist of groups that cannot reach the internet (`file:read`, `file:write`,
`bash`, `media`, `knowledge`); a group that is not on it is dropped. Rewriting
this as a blocklist of `{"web", "browser"}` passes every test that names a
shipped group and silently ships the next provider group anyone adds — which, in
a repo that merges upstream weekly, is a matter of time.

**4. Delegation is not an escape hatch.** `task_tool` reads the switch from the
_parent's_ run context and passes it into the subagent's tool assembly, and the
lead-agent factory writes the value it resolved back into both `context` and
`configurable` so there is one authoritative answer. Without this the feature is
one `task` call away from meaningless.

**Why the offline notice is appended rather than templated.** The system prompt
is operator-editable (§19). A `{internet_section}` placeholder would simply not
exist in a saved `SYSTEM_PROMPT.md`, so the notice would vanish for exactly the
people who customized their prompt — the same trap the Democracy section avoids
by riding `{subagent_section}` (§22). Here there is no suitable existing
placeholder, so `append_offline_notice` appends to the _rendered_ prompt instead,
which works for any template. It is also why the switch does not fragment the
prompt prefix cache for online runs: nothing is added at all when the switch is
on.

**The two limits, stated in the README as well as here.** The switch governs the
model's _tools_. It does not sever the sandbox's own network — `bash` stays,
because it is how the agent runs your code and because the shell's network is a
property of the operator's container, not of a per-chat button; the offline
notice tells the model not to use it as a workaround, which is an instruction and
not a wall (the hard fix is running the sandbox container on an internal Docker
network). And it does not stop the chat model call itself: a cloud model is still
a network request, so a conversation that reaches nothing is this switch _plus_ a
local model. Both limits are in the README section on purpose — a switch a user
cannot trust is worse than no switch.

| Piece                     | Where                                                                                                                                                                                                                                            |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Decision + classification | `backend/packages/harness/deerflow/tools/internet_access.py`                                                                                                                                                                                     |
| Catalog filter            | `tools/tools.py::get_available_tools(internet_enabled=...)`                                                                                                                                                                                      |
| Lead agent                | `agents/lead_agent/agent.py` (resolve, write back, append the notice, publish in `effective_policies`)                                                                                                                                           |
| Subagents                 | `tools/builtins/task_tool.py` (inherits from the parent run context)                                                                                                                                                                             |
| Gateway                   | `app/gateway/services.py` (`internet_enabled` in `_CONTEXT_CONFIGURABLE_KEYS`)                                                                                                                                                                   |
| Composer                  | `frontend/src/components/workspace/input-box.tsx` (`InternetToggleButton`, `data-slot="internet-toggle"`), `core/threads/run-context.ts::resolveInternetEnabled`, `core/settings/local.ts` (`THREAD_SCOPED_CONTEXT_KEYS`), `core/i18n/locales/*` |
| Tests                     | `backend/tests/test_internet_toggle.py`, `frontend/tests/unit/core/threads/internet-toggle.test.ts`, `frontend/tests/unit/core/settings/internet-toggle-persistence.dom.test.ts`, `frontend/tests/e2e/internet-toggle.spec.ts`                   |

## Why mix local and cloud

Each tier of model has a job it's good at. Mixing them is how you get most of the quality of frontier models at a fraction of the cost:

- **Lead agent (cloud, premium):** plans, decomposes, judges. The lead writes the prompts that everything else executes. Worth spending tokens here — bad planning wastes downstream compute regardless of subagent quality.
- **Subagents (cheap, parallelizable):** classification, extraction, file edits, web fetches, repetitive code patches. Often called dozens of times per lead turn. This is where cost compounds.
- **Local (Ollama):** zero marginal cost, full data privacy. Slower than cloud and weaker on long-horizon reasoning, but excellent for bulk subagent fan-out on a workstation that's already turned on.

Anthropic's own framing ([Haiku 4.5 announcement](https://www.anthropic.com/news/claude-haiku-4-5)): _"Sonnet can break down a complex problem into multi-step plans, then orchestrate a team of multiple Haikus to complete subtasks in parallel."_ This fork makes that pattern (and the local-model variant) selectable from the UI.

## Cost story

Anthropic API pricing as of May 2026 (per million tokens, input / output):

| Model          | Input | Output |
| -------------- | ----- | ------ |
| Opus 4.7       | $5.00 | $25.00 |
| Sonnet 4.6     | $3.00 | $15.00 |
| Haiku 4.5      | $1.00 | $5.00  |
| Local (Ollama) | $0    | $0     |

Subagent fan-out is where mixing models pays off. A typical research/coding task spends a large share of its token budget in `task` delegations — easily 60–80% of total tokens.

**Worked example** — assume 100M input + 20M output tokens of total work in a session, with 70% in subagents:

| Configuration                        | Lead cost          | Subagent cost | Total     |
| ------------------------------------ | ------------------ | ------------- | --------- |
| All Sonnet 4.6                       | $0.40 (lead share) | $7.10         | **$7.50** |
| Sonnet lead + Haiku subagents        | $0.40              | $2.37         | **$2.77** |
| Sonnet lead + local Ollama subagents | $0.40              | $0            | **$0.40** |
| All local                            | $0                 | $0            | **$0**    |

Mixed Sonnet/Haiku saves ~63% over pure Sonnet. Sonnet/local saves ~95% — at the cost of subagent quality you should benchmark on your actual tasks.

> Numbers are illustrative. Real ratios depend on prompt cache hit rate, batch API usage, and the share of the prompt that's static system context. The point is that the **cost surface is highly elastic in the subagent model choice**, and that's the lever this fork exposes in one click.

## Setup notes (Arch / CachyOS specifics)

- **nginx temp paths.** Arch packages nginx with `/var/lib/nginx` (root-owned) compiled in as default temp paths, which makes upstream's `make dev` fail for non-root users. This fork patches `docker/nginx/nginx.local.conf` to use relative `.deer-flow/nginx-tmp/` paths, and the `dev:` target creates that directory. No action needed.

- **`langchain-ollama`.** Required for synced Ollama entries to actually load. This fork adds it to `backend/pyproject.toml`. If you clone fresh, `make install` picks it up automatically.

- **Pre-commit hook.** Upstream installs a `pre-commit` hook that lives in `backend/.venv/bin/pre-commit`. If you commit from outside the venv, it fails with `pre-commit not found`. Fix once:

  ```fish
  mkdir -p ~/.local/bin
  ln -sf /home/<you>/deer-flow/backend/.venv/bin/pre-commit ~/.local/bin/pre-commit
  fish_add_path ~/.local/bin
  ```

- **Root-owned files from the DooD sandbox.** In Docker DooD mode the gateway container is host-root-equivalent and writes into host-mounted dirs **as root**. Over time `backend/.deer-flow/` (per-user integrations/uploads/backups) and, if a container ever created it, `backend/.venv/` end up owned by `root`, which then breaks host-side commands run as your normal user. Two symptoms and their fixes:
  - **`make config-upgrade` / `make sandbox-enable` fail** with `Failed to query Python interpreter … failed to canonicalize path backend/.venv/bin/python3: Permission denied (os error 13)`. The venv is root-owned. Fix: `sudo chown -R "$USER":"$USER" backend/.venv` (or delete it and let `make install` rebuild it).
  - **`make docker-start` fails during "load build context"** with `error from sender: open …/backend/.deer-flow/…: permission denied`. The build context sender can't read the root-owned runtime tree. This is now prevented at the source — the repo-root `.dockerignore` excludes `.deer-flow/` (and `**/.deer-flow/`), so the build never reads it (pinned by `backend/tests/test_dockerignore_deer_flow.py`). If you still hit it on an older checkout, either add those patterns or `sudo chown -R "$USER":"$USER" backend/.deer-flow`.
  - General remedy for either: `sudo chown -R "$USER":"$USER" .deer-flow backend/.deer-flow backend/.venv`. Running the local (non-Docker) `make dev` avoids creating root-owned files in the first place.

## PDF and Office document support

Upstream supports converting PDF, DOCX, PPTX, and XLSX uploads to Markdown so the agent can read them, but the dependency (`pymupdf4llm`) is not bundled and the feature is off by default. This fork:

- Adds `pymupdf4llm` as a backend dependency so PDFs convert out of the box.
- Writes the converted Markdown under **two filenames** — `<original>.md` (upstream behavior) **and** `<original>.<ext>.md` (e.g. `report.pdf.md`). Agents tend to hallucinate one convention or the other; writing both eliminates the "file not found" failure mode. Cleanup on delete handles both names.

To turn the feature on, set `uploads.auto_convert_documents: true` in your `config.yaml`. `config.yaml` is gitignored, so the toggle ships per-install rather than in the fork.

## Local Camoufox `web_fetch` backend

Upstream's `web_fetch` tool defaults to the `jina` cloud reader. This fork adds a pluggable dispatcher and a **local, key-less, JavaScript-capable** backend built on [Camoufox](https://github.com/daijro/camoufox) (a stealth Firefox), and **makes it the default** — the shipped `config.example.yaml` sets `backend: camoufox` under the `web_fetch` tool, and the dispatcher's code-level default is camoufox too, so a `web_fetch` entry that omits `backend` gets the local browser as well. Switch to the cloud reader with an explicit `backend: jina` (or `make config`).

Camoufox needs two things: the `camoufox` Python package **and** its browser binaries (a large one-time download). Because it is the default backend, both install **automatically on every launch path** — you never have to run `make fetch-browser` by hand:

- **Local** (`make dev` / `make start`, foreground or daemon): `scripts/serve.sh` auto-detects the `camoufox` uv extra from `config.yaml`, installs it, then runs `scripts/ensure_camoufox.py` to fetch the browser.
- **Docker dev** (`make docker-start`): `docker/dev-entrypoint.sh` runs the same `ensure_camoufox.py` after `uv sync`; the download persists in the `gateway-camoufox` volume across container recreation.
- **Docker prod** (`make up`): the browser is **baked into the image** at build time (`backend/Dockerfile` builder stage runs `camoufox fetch` when the extra is present) and copied into the runtime stage, so no runtime download is needed.

Every path is **idempotent and best-effort**: an already-present browser is a no-op (checked via camoufox's `version.json`), and a failed download (e.g. offline) never blocks startup — the tool then returns an actionable install hint at call time. `make fetch-browser` still works for a manual pre-download.

**The shared browser is liveness-checked, not trusted forever.** One headless Camoufox is launched on first use and reused across every `web_fetch` — cold-starting a browser per fetch is far too slow. But a long-lived browser can die mid-session (OOM kill, crash, a wedged navigation, the subprocess reaped by the OS), and the manager used to cache that handle unconditionally, so a browser that died once made **every** subsequent fetch fail identically until the Gateway restarted — the "`web_fetch` worked, then quietly stopped" symptom. `_BrowserManager.get_browser` now probes the cached browser with Playwright's synchronous `is_connected()` on every call (double-checked under the launch lock) and, when it has gone away, tears the dead handle **and** its context manager down before relaunching, rather than reusing a closed object. The probe fails open: a browser object exposing no `is_connected` is assumed alive and launched anyway (same "classify on failure, never block on an unresolvable probe" rule as `_camoufox_browser_present`). Pinned by `test_camoufox_fetch.py::TestBrowserReuse` (`test_live_browser_is_not_relaunched`, `test_dead_browser_is_torn_down_and_relaunched`).

**The shipped `config.example.yaml` now chains `fallback: jina`.** A local-browser failure (a page Camoufox cannot render, the browser mid-relaunch) retries once through the key-less cloud reader so a fetch **degrades** instead of failing hard, which is the other half of the intermittent-fetch fix. It is set in the example only, **not** as a code-level default: camoufox is the fork's *local/private* backend, and silently routing an existing install's failed fetches to a third-party cloud is a privacy-relevant behavior change, so an operator opts into it (or comments it out to keep every fetch strictly local). Fresh installs (`make config`) get the resilient default; existing `config.yaml`s are untouched. The dispatcher's fallback chain itself is pinned by `test_web_fetch_dispatcher.py`.

## Automatic updates (Camoufox + SearXNG)

The two components this repo installs _for itself_ — the Camoufox browser binaries and the bundled SearXNG Docker image — did not self-update after their first install:

- **Camoufox** only ever _fetched when absent_. `scripts/ensure_camoufox.py` short-circuits the moment camoufox's `version.json` exists, so a newer browser build (for an updated `camoufox` package, or a re-published build for the pinned one) was never pulled after the first download.
- **SearXNG** runs `docker.io/searxng/searxng:latest`, but Docker only pulls `:latest` when the image is missing locally, so a long-running stack keeps whatever image it started with indefinitely — never picking up upstream SearXNG fixes.

This fork adds a single **daily auto-update loop** that closes both gaps.

**The updater** — `scripts/update_camoufox_searxng.py` (`make auto-update`):

- **Camoufox:** runs `camoufox fetch` _unconditionally_ (not the ensure-only guard). `fetch` is itself version-aware — it compares the installed browser to the expected version and re-downloads only when they differ — so running it is the update, and a no-op when already current. Skipped entirely when the `camoufox` extra isn't installed (the web_fetch backend wasn't selected).
- **SearXNG:** `scripts/searxng.sh update` runs `docker compose pull searxng` (fetch the newest `:latest`) and then `up -d searxng` **only if the bundled container is currently running** (a live stack rolls onto the new image; an idle checkout just pre-fetches it for its next `up`). It only ever touches the repo's own `deer-flow-searxng` container — it's skipped when the `web_search` provider isn't SearXNG, when Docker is unavailable, or when `DEER_FLOW_SEARXNG_BASE_URL` points at a foreign instance you manage yourself.

Everything is **idempotent and best-effort**: an already-current component is a no-op, and any failure is logged, never raised, so a scheduled or launch-time run never wedges. Flags: `--dry-run`, `--verbose`, `--camoufox-only`, `--searxng-only`.

**Two ways it runs automatically:**

1. **On launch, throttled (zero setup).** `scripts/serve.sh` runs the updater with `--if-stale 24` in the **background** after starting services, so `make dev` / `make start` refresh both components at most once a day without ever blocking startup. A stamp file (`.deer-flow/auto-update.stamp`) enforces the once-a-day throttle. Opt out with `DEER_FLOW_AUTO_UPDATE=0`.
2. **A `systemd --user` timer (runs even when the app isn't launched — daily _and_ on boot).** `make auto-update-install` writes `~/.config/systemd/user/deer-flow-auto-update.{service,timer}` and enables a timer that fires both once a day (`OnCalendar=daily`) and shortly after the machine boots (`OnBootSec=2min`), with `RandomizedDelaySec=1h` (spreads a fleet out so a shared reboot / power-outage recovery doesn't hammer the registries at once) and `Persistent=true` (a missed daily run catches up after downtime). The boot trigger is what makes it "run when the PC starts up": a machine that's powered off at the daily slot refreshes both components on its next boot instead of skipping a day. systemd is the idiomatic scheduler on this fork's Arch/CachyOS target, and a _user_ timer needs no root. `make auto-update-uninstall` removes it. On a machine without `systemd --user` (macOS, non-systemd Linux), the installer prints the equivalent `cron` lines instead — a daily entry plus a `@reboot` entry for the on-boot run.

```bash
make auto-update             # update both now (idempotent; no-op when current)
make auto-update-install     # install + enable the systemd --user timer (daily + on boot)
make auto-update-uninstall   # stop + disable + remove the timer
systemctl --user list-timers deer-flow-auto-update.timer   # inspect it
# `loginctl enable-linger` runs the boot + daily timer even while you're logged out.
```

Pinned by `backend/tests/test_update_camoufox_searxng.py` (camoufox present/absent, the SearXNG ownership decision matrix, docker-unavailable, dry-run, the `--if-stale` throttle, and `main()` wiring), `backend/tests/test_install_auto_update.py` (the systemd unit / cron content), and `backend/tests/test_searxng_update_script.py` (the `searxng.sh update` pull + recreate-if-running shell path).

## Full sandbox runs (clone a repo and run/debug it)

This fork rounds out the containerized AIO sandbox into a first-class "hand it a GitHub link, watch it clone, install, and debug the program" workflow. Everything here builds on upstream's `AioSandboxProvider` (root inside the container, private-repo clone via a forwarded `GITHUB_TOKEN`); the fork adds the ergonomics that were missing:

- **One-command per-thread container mode.** `make sandbox-enable MODE=container` writes an `AioSandboxProvider` block **without** a `base_url`, so DeerFlow spawns one container per thread and mounts that thread's user-data dirs. Unlike the shared external container (`make sandbox-up`), `/mnt/user-data` is host-backed, so uploads, outputs, and `present_files` all work. `make sandbox-enable` (no MODE) still writes the external block. The container block pins `image: ghcr.io/agent-infra/sandbox:1.11.0` — the same working image `docker/docker-compose.sandbox.yml` uses — so per-thread mode does not fall back to the provider's broken `:latest` default (which lacks the `/v1/bash/*` routes); `make config` (`scripts/configure.py`) and `make setup` write the same pinned block.
- **AIO is the default install when Docker is present.** `make config` (`scripts/configure.py`) and `make setup` both default to this container sandbox whenever a Docker/Apple Container runtime is detected — non-interactively too — falling back to the local sandbox only when no runtime exists. So a fresh clone with Docker installed lands on the containerized AIO sandbox out of the box; `make sandbox-disable` reverts to the local sandbox in one command.
- **Timeouts that survive real installs.** `sandbox.bash_command_timeout` is now forwarded to the AIO sandbox per command (idle timeout on the shell path, wall-clock hard timeout on the env-bearing path), not just to the host-local sandbox. A long `pip install`/`cargo build` no longer dies at the old fixed 600s. DeerFlow warns once if you set it above `request_timeout` (the HTTP client would abort first) — raise both together.
- **Reach the program under debug from your browser.** `sandbox.expose_ports: [8000]` publishes container ports 1:1 to the host loopback in local container mode, so a dev server the agent starts is reachable at `localhost:8000`. With a non-loopback `DEER_FLOW_SANDBOX_HOST` (the Docker-outside-of-Docker case) the port follows the sandbox API's own bind — the address that host resolves to — rather than `0.0.0.0`; upstream hardened that path because the API port beside it is an unauthenticated shell endpoint. `DEER_FLOW_SANDBOX_BIND_HOST=0.0.0.0` restores the broad bind, and wants a firewall in front of it. Upstream's controlled-egress mode (`sandbox.network`) is the one place `expose_ports` publishes nothing at all: it puts the container on an internal network reached only through a relay proxy and leaves the sandbox API port unpublished, so a debug port published to the host there would be a silent hole in the isolation that mode exists to provide — debugging with `expose_ports` means leaving `network.mode` open.
- **Native debuggers.** `sandbox.extra_capabilities: [SYS_PTRACE]` adds `--cap-add` flags (Docker only) so `gdb`/`strace` can attach.
- **A `repo-runner` public skill** (`skills/public/repo-runner/`) that encodes the whole loop: clone into the workspace → detect the toolchain → install deps in an isolated venv/`node_modules` → run (backgrounding servers) → iterate on failures → report reproducible commands.

The `expose_ports` / `extra_capabilities` keys are local-container-mode only; in external/provisioner mode they are warned-as-ignored (declare `ports:` / `cap_add:` in `docker/docker-compose.sandbox.yml` instead). Packages installed outside the mounted workspace (apt, global pip) are still lost when a container is recycled, so keep a project's dependencies in a workspace-local venv — the skill does this by default. Raise `sandbox.idle_timeout` to keep a warmed-up debug environment alive longer between turns.

## Troubleshooting: nginx 502 after `make up`

**Symptom.** After a `git pull` + `make up` (Docker prod, containerized AiO sandbox), `http://localhost:2026` returned a bare nginx **502 Bad Gateway**. nginx was up on `:2026`, but the upstream gateway was not healthy, so nginx had nothing to proxy to. A stack that had previously worked passwordless suddenly wanted a login, and even the login/health routes 502'd.

**What actually happened.** Two independent problems stacked into one opaque failure:

1. **The gateway hard-crashed on config load.** `AppConfig.resolve_env_variables` raised `ValueError: Environment variable … not found` for **any** `$VAR` in `config.yaml` that wasn't set in the environment — _even when the block that referenced it was `enabled: false`_. A leftover `channels.slack` / `channels.telegram` block with `bot_token: $SLACK_BOT_TOKEN` and no token in `.env` was enough to take the whole gateway down. Because the crash happened at startup, the only external symptom was nginx's generic 502 — no hint about the missing variable.
2. **`make up` was silently re-enabling auth.** The fork's passwordless default was wired only into the local launchers (`serve.sh`); the Docker prod path (`deploy.sh`) left `DEER_FLOW_AUTH_DISABLED` unset, so `make up` came up with the login wall on. A home-lab user who expected "no login on my own network" got one, with no obvious escape hatch.

**The immediate workaround** (what unblocked the box):

```fish
# .env
DEER_FLOW_AUTH_DISABLED=1
# make sure DEER_FLOW_ENV / ENVIRONMENT are not prod/production (that forces auth back on)

# config.yaml: don't leave a live $SLACK_BOT_TOKEN etc. for a channel you haven't set up
make sandbox-enable MODE=container
make config-upgrade
make down && make up
```

**The in-repo fixes so it can't recur:**

- **A disabled section no longer crashes the gateway on a missing `$VAR`.** `AppConfig.resolve_env_variables` now propagates a "lenient" flag through the subtree of any `enabled: false` section: a missing `$VAR` there resolves to an empty string with a `WARNING` instead of raising. **Active** config stays strict — a missing API key for an _enabled_ model still fails loudly at startup, which is the behavior you want. So a leftover placeholder for a channel you never turned on is tolerated, while a real misconfiguration still surfaces. Pinned by `backend/tests/test_config_env_resolution.py`.
- **`make doctor` lists referenced-but-missing `$VARS` before you start.** A new check (`scripts/doctor.py::check_env_placeholders`) scans `config.yaml`, and for any `$VAR` that isn't set it reports: a **failure** ("The Gateway crashes on load (bare nginx 502) if an active section references an unset `$VAR`") when the section is active, or an informational **note** ("unset but tolerated (enabled: false)") when it's disabled. `make doctor` is the recommended one-liner after a `git pull` and before `make up`. Pinned by `backend/tests/test_doctor.py::TestCheckEnvPlaceholders`.
- **`make up` is passwordless by default** (see §5). `deploy.sh` now defaults `DEER_FLOW_AUTH_DISABLED=1` (opt-out via `.env`), forwards it plus the production markers to both containers, and prints a warning when auth is off — so the home-lab Docker path matches `make dev` / `make start` instead of surprising you with a login wall. Production (`DEER_FLOW_ENV`/`ENVIRONMENT=production`) still forces auth on.

**Recommended post-update flow:**

```bash
git pull
make config-upgrade   # merge any new config fields; never leaves live placeholders for disabled features
make doctor           # catches missing $VARS + reports the auth posture, before the stack starts
make up
```

`make config-upgrade` only ever _adds missing keys_ from `config.example.yaml` (whose channel blocks ship fully commented out), so it never injects a live `$PLACEHOLDER` for a feature you haven't enabled; combined with the lenient-resolution fix above, an uncommented-but-disabled block is now harmless.

## Troubleshooting: after an update — container name conflict, then localhost refused

Two more things that can bite right after `git pull` + `make up`, in the order they tend to appear.

### Container name conflict on `make up`

**Symptom.** `make up` fails with `Error response from daemon: Conflict. The container name "/deer-flow-gateway" (or -nginx / -frontend / -searxng) is already in use by container …`.

**Why.** The prod stack pins fixed `container_name:`s (`deer-flow-gateway`, etc.). If a container with that name is left behind — a previous stack that wasn't brought down cleanly, a crashed run, or a container created outside the current Compose project (e.g. a different `-p` project name, or the Docker **dev** stack sharing a name) — `docker compose up` refuses to clobber it and errors instead of recreating it.

**Fix.** Bring the old stack down first, which removes the named containers, then bring it up:

```bash
make down    # removes the named containers for the deer-flow project
make up
```

If a stray container survives `make down` (created outside the project), remove it by name: `docker rm -f deer-flow-gateway` (repeat for `-nginx` / `-frontend` / `-searxng`), then `make up`. **Look out for this when you change `container_name:` or add a service in `docker/docker-compose.yaml`** — a rename leaves the old name orphaned, and any host with the previous name still present will conflict until it is removed.

### `localhost` refused on the host, but it works over Tailscale from another device

**Symptom.** After `make up`, `http://localhost:2026` on the machine running the stack returns **connection refused**, yet the app is reachable from your phone over Tailscale (or another device on the LAN). Nothing is wrong with the app — it's the bind.

**Why.** `BIND_HOST` is a **single bind interface, not an allowlist**. The entry port is published as `${BIND_HOST}:${PORT}:2026`, so setting `BIND_HOST` to your Tailscale IP (e.g. `100.x.y.z`) to reach the app from your phone binds **only** that interface. The host's own `localhost` is a different interface (loopback), so nothing is listening there and the connection is refused. (`BIND_HOST=0.0.0.0` binds _all_ interfaces including loopback, which is why the all-interfaces case doesn't hit this.)

**Fix (now automatic).** `scripts/deploy.sh` detects when `BIND_HOST` is a single specific interface — set, but not loopback (`127.0.0.1`/`::1`/`localhost`) and not a wildcard (`0.0.0.0`/`::`) — via `should_cobind_loopback`, and appends `docker/docker-compose.loopback.yaml`, which **also** publishes the entry port on `127.0.0.1`. So with `BIND_HOST=100.x.y.z` the port is now bound on **both** the Tailscale interface and loopback: the phone reaches it over Tailscale _and_ `http://localhost:2026` works on the host. Loopback is host-only, so this never widens the external surface. `make up` prints a `✓ Co-binding 127.0.0.1 …` line when it's active. Compose concatenates the two `ports` entries (verified with `docker compose config`), so the base external mapping is untouched. Pinned by `backend/tests/test_deploy_loopback_cobind.py` (the decision function + the overlay's shape).

**Look out for this when you touch the port/bind wiring** — `docker/docker-compose.yaml`'s `nginx.ports`, the `should_cobind_loopback` predicate, or the overlay. If you make the base compose publish a wildcard by default, or add another loopback mapping, you can double-bind `127.0.0.1:${PORT}` and collide on the port (`bind: address already in use`); the predicate deliberately skips the overlay for loopback and wildcard binds for exactly that reason. The still-simplest way to reach the app from both the host and the network without any of this is `BIND_HOST=0.0.0.0` (behind your own firewall/TLS).

## Reaching the stack over Tailscale (both Docker paths)

The fork's whole point is a personal AI you reach from your phone, so tailnet access is a supported mode rather than something you re-derive after every upgrade. Both `make docker-start` and `make up` detect Tailscale on start and make the stack reachable from your other tailnet devices, with **no `.env` edit and nothing to redo after a `git pull`**.

**What broke, and why it was two bugs wearing one symptom.** The security change that made nginx loopback-only (`${BIND_HOST:-127.0.0.1}:${PORT:-2026}:2026`) is correct for LAN/WAN and silently ended tailnet access. The documented escape hatch — set `BIND_HOST` in the repo-root `.env` — then turned out not to work at all on the Docker-dev path:

- **Root `.env` never reached port interpolation.** `scripts/docker.sh` built its compose command with no `--env-file` and then `cd docker/`, so Compose resolved `${BIND_HOST}` / `${PORT}` against `docker/.env` — a file that does not exist. `env_file: ../.env` on a service only populates that _container's_ environment; it has no effect on **interpolation**, which is what a `ports:` entry uses. So the setting was read, appeared to work, and changed nothing. `make up` / `scripts/deploy.sh` was already correct here (it passes `--env-file "$ENV_FILE"`), which is exactly why the two paths disagreed.
- **`BIND_HOST` is one interface, not an allowlist.** Pointing it at the tailnet IP publishes _only_ that address and refuses the host's own `localhost` (the section below covers that footgun on its own).

**The fix: publish an extra port, never widen the bind.** `scripts/detect_tailscale.py` reads `tailscale status --json` and reduces it to this machine's tailnet IPv4 and MagicDNS name. When it finds one, the launch scripts append `docker/docker-compose.tailscale.yaml`, which publishes nginx on `<tailscale-ipv4>:${PORT}:2026` **in addition to** the loopback default. `100.64.0.0/10` is CGNAT — routable only inside your tailnet — so this does not expose the LAN or the internet the way `0.0.0.0` would. Compose concatenates `ports` across `-f` files, so the base mapping is untouched.

**Publishing the port is only half the fix, and the missing half is the one that looks like a Tailscale problem.** A browser on another tailnet device sends `Origin: http://100.x:2026` (or `https://<magicdns>.ts.net` through Serve). If those origins are not in the allowlists, the shell loads and every API call 403s — which reads as "Tailscale is broken", not "an origin list is short". So the same pass merges the detected origins into `GATEWAY_CORS_ORIGINS`, `DEER_FLOW_TRUSTED_ORIGINS`, and `DEER_FLOW_DEV_ALLOWED_ORIGINS`. The merge **only ever adds**: user entries keep their exact spelling and their position, duplicates are dropped on a normalized comparison so re-running a launch script is idempotent, and an operator who wrote `*` is left alone rather than silently narrowed.

The other origin-side pieces were already right and are worth knowing so they are not "fixed" into a regression: `docker/nginx/nginx.conf` maps an upstream `X-Forwarded-Proto` (added for the behind-another-TLS-proxy case, which is exactly the `tailscale serve` shape), the Gateway's `_request_origin` honours `X-Forwarded-Proto` / `X-Forwarded-Host`, and `frontend/src/dev-origins.js` already ships `100.*.*.*` and `**.ts.net` in its default dev-origin patterns.

**Two access styles, and the banner prints whichever is live:**

| URL                            | Requires                      | Notes                                                                                                                                          |
| ------------------------------ | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `http://<tailscale-ipv4>:2026` | Detection only                | The compatibility URL — what bookmarks and phones already use. Plain HTTP, so **not** a secure origin: Web Push stays unavailable on it.       |
| `https://<magicdns>.ts.net`    | `tailscale serve` on the host | A real certificate, so PWA install and Web Push work. Serve terminates TLS and forwards to loopback, so it needs no published port of its own. |

**Serve is never run for you, and never reset.** `tailscale serve` usually needs `--operator=$USER` or sudo, so a launch path that ran it would either prompt or fail; the banner prints the exact command instead. More importantly, Serve config is **global to the machine** and may carry rules for your other services — so DeerFlow never runs `tailscale serve reset` on stop, and `tailscale_serve_is_active` is a read-only status probe. Pinned by `test_the_library_never_runs_tailscale_serve_itself` and `test_stop_and_down_never_reset_tailscale_serve`.

**Do not use `https://100.x.y.z`.** The certificate is issued for the MagicDNS _name_, not the IP, so an HTTPS URL on the bare address is a certificate error every time. `tailnet_origins` deliberately never emits it — allowlisting an origin that can only ever fail to load helps nobody.

**Opt out** with `DEER_FLOW_TAILSCALE_PUBLISH=0` in `.env`, for a host that is on a tailnet but should not serve DeerFlow to it. Without Tailscale running, none of this applies: nothing extra is published and the default stays `127.0.0.1`.

**Look out for this when you touch the launch scripts.** The `--env-file` in `scripts/docker.sh` is load-bearing — drop it, or make it relative, and the root `.env` silently stops reaching `ports:` again. The overlay's `${DEER_FLOW_TAILSCALE_IPV4:?…}` is also deliberate: giving it a default would let `"${VAR}:${PORT}:2026"` collapse to `"${PORT}:2026"` on an empty value, which binds `0.0.0.0` — the exact wildcard the overlay exists to avoid. Pinned by `backend/tests/test_detect_tailscale.py` and `backend/tests/test_docker_dev_tailnet.py`, the latter including the regression that a repo-root `.env` `BIND_HOST` reaches the publish and that a stray `docker/.env` cannot mask it.

### 28. Scrolling back through a long conversation

Loading a conversation does not load all of it. `useThreadHistory` is a
TanStack infinite query that fetches the newest 50 rows from
`GET /api/threads/{id}/messages/page` and pages backwards by cursor; an
IntersectionObserver on a sentinel above the list asks for the next page as the
reader reaches the top. That part was always right. Holding the reader's place
while a page lands was not.

**Three things owned `scrollTop` at once.** Past 60 message groups
(`VIRTUALIZATION_THRESHOLD`) the list virtualizes, and from then on
`use-stick-to-bottom`, `@tanstack/react-virtual`'s measurement corrections, and
the component's own prepend anchor were all writing scroll position against
each other. The sharp edge is in the library: `handleScroll` clears
`escapedFromLock` on _any_ downward scroll and cannot tell the anchor restore
from the reader choosing to go back to the newest turn. It defers that decision
by 1ms so its own ResizeObserver can mark the event resize-driven — so whether
the lock survived a prepend was a race, and losing it scrolled the reader to
the bottom of the thread they were scrolling back through.

What changed, all in `virtual-message-list.tsx`:

- **The restore holds the lock open.** A prepend that lands while the reader is
  away from the bottom calls `stopScroll()` and keeps `isAtBottom` revoked for
  `PREPEND_STICK_SUPPRESSION_MS` — comfortably past that 1ms deferral, which
  makes the outcome deterministic rather than load-dependent.
- **Growth at the front is not growth at the tail.** `resolveListGrowth`
  classifies a list change as `append` / `prepend` / `none`, and only an append
  may pull the viewport to the newest turn. A loaded history page grows the
  list too, and used to be read as new content arriving.
- **The restore runs before anything else may scroll.** Effect order is the
  contract: the position restore settles first, and the stick-to-bottom effect
  then reads the suppression window it opened.
- **The static list is left to the browser.** Below the threshold the rows
  above the viewport are real DOM with real heights, so CSS scroll anchoring
  already holds the position; scrolling to an offset the virtualizer derived
  from estimates was breaking exactly what it was meant to preserve. The anchor
  is read off the DOM there instead, which is what lets a thread cross the
  threshold — as a loaded page routinely makes it — without losing the reader.
- **The row estimate is learned, not fixed.** A page of never-rendered rows is
  prepended at `estimateSize()` each, and the whole error lands above the
  viewport. `createRowHeightEstimator` is a clamped moving average over this
  thread's measured rows, replacing a 176px constant that matched no real
  thread.

**On testing this.** The lock race is not deterministically reproducible in a
clean run — the same reason the `thread-history.spec.ts` flake above showed up
only under load, and CPU throttling heavy enough to flip the ordering stalls
the app instead. So the coverage is layered rather than pretending otherwise:
`virtual-message-list-helpers.test.ts` tests the two extracted decisions
directly, `virtual-message-list.test.ts` pins the wiring and the effect
ordering in milliseconds, and `thread-history.spec.ts`'s "keeps the reader's
place when an older history page loads" asserts the invariant against a real
layout engine, holding the older-page response until the reader has scrolled
back so the prepend lands into a parked viewport. Do not rewrite that last one
to assert it goes red on the old code; it does not, and the comment says why.

**The page endpoint is the only source, so its store has to be durable.**
Everything above is about holding the reader's place while a page lands. A
separate failure stops the page from existing at all, and it looks nothing like
a scroll bug: after restarting the machine the Gateway runs on, a long
conversation opens normally, shows its most recent turns, and then simply stops
loading older ones when the reader scrolls up.

`GET /api/threads/{id}/messages/page` reads the **run-event store** and nothing
else. Upstream ships `run_events.backend: memory`, which makes that store
process state — so a Gateway restart empties it, while the LangGraph checkpoint
(durable on the default `database.backend: sqlite`) keeps supplying the recent
window through thread state. The two sources disagreeing is what produces the
symptom: `mergeMessages` still renders a populated thread, the page endpoint
returns `has_more: false`, the IntersectionObserver sentinel therefore never
fires, and **no error is logged on either side**. On a chat long enough to have
been compacted, every turn before the compaction point is simply gone from the
UI.

The fork's default is `run_events.backend: db`. It writes into the same
`deerflow.db` the checkpointer already uses, so durability costs no extra setup,
and `make_run_event_store()` still falls back to the memory store when
`database.backend: memory` leaves no session factory — an install that wants
ephemeral runs is unaffected. Three things had to move together, because any one
alone reaches only some installs:

- **`RunEventsConfig.backend` defaults to `db`** — covers a `config.yaml` with no
  `run_events:` section, and the Helm chart, which embeds no such section.
- **`config.example.yaml` ships `db`** (`config_version: 50`) — covers fresh
  installs, which copy the example verbatim rather than falling back to the
  schema default.
- **`config_upgrade.py` migration 50 rewrites `run_events:\n  backend: memory`**
  — covers existing installs, whose `config.yaml` would otherwise keep the value
  it was created with forever. This is the one place the upgrade rewrites a
  value the user may have set on purpose; it is anchored on the section header
  so `backend: memory` under `database:` is untouched, and it is justified by
  `memory` being a data-loss setting whose only symptom is silent.

For an install that never runs `make config-upgrade`, `make doctor` reports the
combination directly (`run history survives a restart`). History already lost to
earlier restarts is not recoverable — the rows were never written.

`make_run_event_store(None)` resolves `RunEventsConfig()`'s defaults rather than
hardcoding a backend of its own. That looked like tidying and is not: the two
paths silently diverging is exactly how a caller ends up with less durability
than its configuration asked for.

**On testing this.** The durability claim is provable in a way the lock race
above is not, so it is pinned end to end rather than by layers.
`test_run_history_durability.py` writes messages through a real SQLite-backed
store, tears the engine down, rebuilds it — a restart, as far as the store is
concerned — and asserts the backward `before_seq` page still returns the older
turns and that `seq` continues from the persisted maximum instead of restarting
at 1 (a reset would interleave new turns underneath old ones). Its
`test_the_memory_store_is_what_loses_it` asserts the other direction, so the
file fails if someone "fixes" durability by making the memory store persist
instead of changing the default. `test_no_config_resolves_the_same_store_as_default_config`
is the divergence guard, and both default sources — schema and example — are
asserted separately because either one alone still reaches real installs.

**Not addressed here.** Every run finish invalidates the whole history query,
so TanStack refetches _every_ loaded page in sequence — twenty pages loaded
means twenty requests after each turn. That is a real cost and the churn the
scroll has to survive, but it is an optimisation touching the reconciliation
path this file's neighbours warn about, so it was deliberately left out of a
scroll fix.

### 29. An edited message keeps the conversation's model

Editing a message branches the conversation into a **new thread id**
(`useCreateEditVersion` -> `branchThreadFromTurn`), and every per-conversation
setting is stored under the thread id — that is the whole point of
`THREAD_SCOPED_CONTEXT_KEYS` and the reason selecting a model in one chat does
not leak into another (§ the thread-context isolation tests). The fork was
never carried over, so the version read no override and fell back to the app
defaults: an edit silently moved the conversation onto the default model, and
took the mode, reasoning effort, internet switch and Democracy panel with it.

`copyThreadContextOverride(source, target)` copies the override onto the new
thread id before anything routes to it, on both fork paths — the edit version
and `useBranchThread`. It is a copy, not a share: changing the model in the
version must not reach back into its parent. Pinned by
`tests/unit/core/settings/thread-context-isolation.dom.test.ts`.

### 30. A model bigger than VRAM gets a window the agent can actually run in

`vram_num_ctx_limit` computed `available = vram - weights - overhead` and, when
that went negative, returned `MIN_VRAM_NUM_CTX` — so a 120B model advertising a
128K native window was written into `config.yaml` as `num_ctx: 4096`. That is
below the floor the constant exists to defend: the agent's system prompt, tool
schemas, skills and memory do not fit in 4096 tokens. The class of model a 24 GiB
card runs best was the class the sync quietly made unusable.

**The first fix for this was wrong, and the way it was wrong is worth keeping.**
It assumed Ollama offloads MoE *experts* the way llama.cpp's `--n-cpu-moe` does,
and sized the window against the ~2% of weights that would stay resident — which
would have handed gpt-oss-120b a 131072-token window on a 24 GiB card. Ollama
does not do that. [ollama/ollama#11772](https://github.com/ollama/ollama/issues/11772)
is still open; Ollama splits **whole layers** across GPU and CPU via `num_gpu`,
and each layer carries its own experts.

The consequence inverts the intuition. Per
[ollama/ollama#9750](https://github.com/ollama/ollama/issues/9750), when the
weights and the KV cache do not both fit, Ollama **keeps the cache and drops GPU
layers to make room**. So for an offloaded model a larger context window is not
free — it is *paid for in layers*, and layers pushed to the CPU are the slow
ones. An unbounded window would have been a different silent failure from the
one it replaced: not "unusable", but "usable and inexplicably crawling".

So the sizing is bounded on both sides, and that is the property to preserve:

- **`OFFLOAD_KV_VRAM_SHARE` (0.25)** caps what the KV cache may take of VRAM
  once a model no longer fits, leaving the rest to hold weights. Raising this to
  "whatever fits" reintroduces the layer eviction above.
- **`MIN_OFFLOAD_NUM_CTX` (16384)** is the floor for that path, deliberately
  larger than `MIN_VRAM_NUM_CTX`. The old 4096 floor is right for "this barely
  fits"; it is not a usable window for an agent.
- **The fits-in-VRAM path is untouched.** Spare VRAM has no better use than KV
  cache, so that branch still takes all of it, and every pre-existing sizing
  expectation is a regression test for exactly that.

One pre-existing test changed contract deliberately:
`test_no_room_floors_at_minimum` became
`test_no_room_takes_the_offload_floor_not_the_old_4096`. It asserted the 4096
return that this section calls the bug, so re-asserting the new floor is the
point rather than a loosened check.

`ollama.system_ram_gb` (optional, unset by default, detected by `make setup`)
names the pool those offloaded layers land in. It is warn-only:
`offload_capacity_warning` names any installed model whose weights exceed VRAM +
RAM together, the state where Ollama pages from disk and generation drops to
seconds per token. It never reassigns a model choice — the rule
`vram_contention_warning` already follows. That warning stays costed at **total**
weights, because whole-layer offload means two big models really do evict each
other.

### 31. The three defaults that made a fresh install fail on a VPN

Found by debugging a clean Docker dev stack on Arch behind NordVPN, where
`web_fetch` failed for an entire agent run and `web_search` went dead partway
through. Three independent defects, none of which surfaces as an error at
install time; the first two are the ones that made the stack look broken.

**Camoufox was installed without the libraries it loads.** The runtime stage is
`python:3.12-slim-bookworm` and it copied `/root/.cache/camoufox` in without any
GTK/X11 stack, so the browser was on disk and could not execute
(`libgtk-3.so.0: cannot open shared object file` → `Couldn't load XPCOM`). This
is worse than a missing browser: **every presence check passes**, because the
binary really is there. `browser_present()` looks for `version.json`,
`ensure_camoufox` calls an existing install a no-op, and `make doctor` reports
nothing — the failure appears only at agent runtime, on every clean build, for
the *default* `web_fetch` backend. The install is now in the same stage as the
`COPY`, and `test_camoufox_runtime_deps.py` asserts that adjacency, because the
bug is precisely a browser copied into a stage that cannot run it. The list is
the headless subset by hand; `playwright install-deps firefox` pulls ~130
packages / 406 MB, mostly fonts and xvfb that headless never touches.

**A stale `GITHUB_TOKEN` turned a working anonymous path into a hard failure.**
Camoufox resolves its release through the GitHub API. Anonymous calls return 200
(or 403 when rate-limited) — a **401 proves a credential was sent and rejected**,
and camoufox treats that as fatal rather than retrying anonymously ("Synced 0
versions from 0 repos"). The gateway loads the whole repo-root `.env` via
`env_file`, and that is where `GITHUB_TOKEN` lives for the sandbox, so the
default Docker path hands the fetch a token it never needed.
`fetch_environment()` strips it for that subprocess only — a copy, so nothing
else in the process loses the token. Scoping the variable out of the gateway
entirely would mean abandoning `env_file` and enumerating every key, which trades
one failure for a maintenance burden; the surgical fix is at the one call site
that is harmed by it. **`test_the_fetch_call_site_actually_uses_the_scrubbed_environment`
is the load-bearing test, not the helper tests beside it**: the first version of
this fix passed every `fetch_environment` unit test and would have raised
`NameError` on the real path, because the module never imported `os`.

**SearXNG's engine failures were discarded.** The client read `data["results"]`
and ignored `unresponsive_engines`. When every engine is blocked SearXNG answers
**HTTP 200 with an empty array** and names the failures in that field, then
benches each blocked engine for ~180 seconds. Reported as a successful empty
search, the agent re-queries immediately, which re-triggers the block and
extends the suspension — a search tool that works for the first few calls of a
run and then returns nothing for the rest. The tell is timing: a suspended query
answers in ~50 ms because nothing is being contacted.

The distinction the fix rests on is that **an empty result set is ambiguous** and
only `unresponsive_engines` disambiguates it. Nothing matched → still an empty
success. Every engine blocked → `SearxngEnginesUnavailableError`, naming the
engines and the suspension window so the agent can back off instead of
amplifying. Partial failure with some results → not an error at all; degraded
beats failed. Those three cases are three tests, and collapsing them into "empty
means error" would break the first one silently. `_format_unresponsive` tolerates
any shape upstream sends, because failing to parse a diagnostic must never become
the failure being diagnosed.

Two shipped defaults were set for a fast unfiltered connection and changed with
them: `web_fetch` had `timeout: 10` for a **full Firefox render** (raised to 30,
matching every other timeout in the file), and the bundled SearXNG ran the stock
engine mix — Google CSE, DuckDuckGo, Brave, Startpage, all four of which block
datacenter and VPN exits. `mojeek`, `qwant` and `bing` are now enabled by name so
a blocked consumer engine costs some results rather than all of them. **Do not
"fix" that list by adding the four blockers back**; they are the failure, not the
fallback. `fallback: jina` stays commented out on purpose: it routes every
fetched URL through a third party, which is the one thing the local-first default
exists to prevent, so it is an informed choice rather than a silent default.

Note that a suspension is time-based and survives an IP change — the SearXNG
container must be restarted to clear it.

### 32. Folders in the sidebar chat tree

The side list was one flat, recency-ordered column: pinning kept a handful of conversations at the top, and everything else scrolled. This fork adds **folders**, and they behave the way a file manager's do — a conversation dropped into a folder is *inside* it and **no longer in the list outside it**, and the folder collapses to a single row you open with the arrow beside its name. Create one with the **+** in the "Recent chats" header, file conversations by dragging them onto a folder (or via **Move to folder** in a chat's row menu), and rename or delete a folder from its own **⋯** menu — the same affordance the conversation rows already carry.

- **"Inside" means inside — that is the whole feature.** `groupThreadsByFolder` partitions the loaded list before anything renders it, and the two properties it guarantees are the ones a refactor would quietly break. First, **a conversation appears exactly once**: a filed chat is absent from the root list, not merely also shown in a folder — a duplicate would make the sidebar unreadable and is the state this feature exists to avoid. Second, **bad data never hides a conversation**: a thread whose `deerflow_folder` names a folder that no longer exists (deleted on another device, or dropped by the store's normalization) falls back to the **root list**. That fallback is what makes folder deletion safe — the chats reappear in the list the instant the folder is gone, before any metadata is rewritten, so a failed cleanup write can never swallow a conversation.
- **The registry and the membership are stored in two different places, on purpose.** The folder list — id, name, display order — is per-user server state in the same `{base_dir}/users/{user_id}/ui_state.json` bag as the keep-alive tab strip (§9), exposed as `GET`/`PUT /api/settings/chat-folders`, ungated for the same reason: it is per-user UI state, not a server-wide setting. *Which* conversation is in *which* folder rides on that conversation's own thread metadata (`deerflow_folder`). Renaming a folder is therefore one small write instead of one write per conversation inside it, and a conversation carries its filing with it wherever the thread record goes. Do not "simplify" this by storing member ids in the registry: a rename is the cheap operation, and a membership list would need reconciling against every delete, branch and edit-version the thread list already performs.
- **Filing a chat must not reorder the sidebar.** The list is recency-ordered, so a PATCH that bumped `updated_at` would shove the conversation the user just dragged to the top and reshuffle everything under their cursor mid-gesture. The Gateway's `PATCH /api/threads/{id}` therefore recognizes a **narrow placement-only patch** — `deerflow_pinned` and/or `deerflow_folder`, nothing else — and skips the touch. It is the same exemption pin/unpin already had, generalized. It is **shape-guarded per key**, not granted on the key name: a patch smuggling a non-string folder value, or mixing a placement key with ordinary metadata, falls back to the endpoint's normal recency contract rather than silently buying the exemption.
- **One drag, two drop targets.** A sidebar chat row advertises its thread id under the tab strip's existing `application/x-deerflow-thread-id` MIME, so the same drag files the chat into a folder *or* pins it as a keep-alive tab depending on where it lands. Rows are now **always** draggable (they used to be draggable only when chat tabs were enabled) — folders work whether or not that feature is on. Drop targets are explicit and disjoint: a folder header, a folder's expanded child area, and the root list container. Nothing else accepts a drop, so there is no ambiguous middle ground where a drag silently does nothing or does the wrong thing.
- **Drag-and-drop is the fast path, never the only path.** Native HTML5 DnD is unusable by keyboard and by screen readers, so every folder operation also exists in a menu: **Move to folder ▸** in a chat's row menu (with the folders, a **No folder** entry, and a **New folder** shortcut), and rename/delete in the folder's own menu. The `+` in the group header is a real button.
- **Expanded/collapsed is per browser; the folders themselves are not.** Which folders are open lives in `localStorage` under one key — the same tree can reasonably be open on a desktop and collapsed on a laptop, and it is the one piece of this feature nobody would miss after a data clear. A folder the user *just created* is opened automatically, so the drop they are about to make has a visible target. Everything else — names, order, membership — is server state that follows the user across browsers and devices.
- **Branches are flattened per partition, not once over the whole list.** `flattenThreadBranches` runs on each folder's threads *after* the partition, so a branch whose parent sits in a different folder simply renders top-level in its own folder. The alternative — teaching the branch tree about folders — would have to choose between showing a child outside its folder and hiding it entirely, and both break a rule above.

**Where it's wired.**

| Piece                                                                     | Location                                                                                                                                                                       |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Pure model (create/rename/remove, normalization, the grouping rules)      | `frontend/src/core/threads/chat-folders.ts`                                                                                                                                    |
| Durable per-user registry + API                                          | `backend/packages/harness/deerflow/config/user_ui_state.py` (`get_chat_folders` / `set_chat_folders` / `normalize_chat_folders`); `GET`/`PUT /api/settings/chat-folders` in `backend/app/gateway/routers/settings.py` |
| Placement-only PATCH exemption                                           | `backend/app/gateway/routers/threads.py` (`_is_ui_placement_metadata_patch`); key in `deerflow/persistence/thread_meta/base.py`                                                 |
| Registry client                                                          | `frontend/src/core/threads/chat-folders-api.ts` (`fetchChatFolders` returns `null` for "unknown", so an unreachable gateway never collapses the tree)                          |
| Folder state, optimistic edits, per-browser expanded set                 | `frontend/src/core/threads/use-chat-folders.ts`                                                                                                                                |
| Move mutation                                                            | `frontend/src/core/threads/hooks.ts` (`useMoveThreadToFolder`)                                                                                                                 |
| Sidebar tree + folder row                                                | `frontend/src/components/workspace/recent-chat-list.tsx`, `chat-folder-row.tsx`                                                                                                |
| i18n                                                                      | `core/i18n/locales/{en-US,zh-CN}.ts` (`chats.folders.*`)                                                                                                                       |

Pinned by `frontend/tests/unit/core/threads/chat-folders.test.ts` (the pure model — the exactly-once partition, the unknown-folder fallback, order preservation inside a partition, the cap and the defensive parsers) and `frontend/tests/e2e/sidebar-chat-folders.spec.ts` (create from the `+`, drag a chat in and confirm it left the root list, collapse/expand by the arrow, drag back out, rename and delete from the folder menu, the row menu's non-drag path, and reload persistence).

The two halves the pure model cannot see are pinned separately:

- `backend/tests/test_user_ui_state.py` — the registry in the shared per-user bag: cold-cache round-trip in display order, per-user isolation, an explicit empty list persisting, malformed/duplicate/oversized input degrading rather than raising, and folders and tabs not clobbering each other in the one file.
- `backend/tests/test_chat_folders_settings_router.py` — the routes: round-trip, the normalized response being authoritative, the cap, an explicit clear, per-user scoping, and an email-shaped identity not breaking per-user path resolution.
- `backend/tests/test_threads_router.py` — the no-touch exemption, in **both** directions: a folder move and a folder clear preserve `updated_at`, and a wrong-typed folder value or a placement key mixed with ordinary metadata still bumps it. Collapsing those into "the key is present" is exactly the silent regression the pair exists to catch.

**Verify it works.**

```bash
cd frontend && corepack pnpm test chat-folders
cd frontend && corepack pnpm test:e2e sidebar-chat-folders
cd backend && uv run pytest tests/test_user_ui_state.py tests/test_chat_folders_settings_router.py -q
cd backend && uv run pytest tests/test_threads_router.py -k "folder or pin" -q
```

Then end-to-end (`make dev`): click **+** in the sidebar's "Recent chats" header, name a folder, drag a conversation onto it → it disappears from the list and appears under the folder; click the arrow to collapse and expand; drag it back onto the list below → it leaves the folder; rename and delete the folder from its **⋯** menu and confirm the conversations come back rather than going with it; reload and confirm the folder and its contents are still there.

### 33. Renaming a conversation is a setting, and it waits for the answer

Upstream renames a thread from its first exchange and gives you no say in it: the
behaviour is `config.yaml -> title`, which a *user* never sees. Two things were
wrong with that on a personal deployment. It is an LLM call you did not ask for
(off by default upstream only in the sense that `model_name` is `null`, which
silently degrades to truncating your first message), and it fired from
`after_model` — inside the agent loop, right after the first model call — which
is the one window in which the user is *forbidden* to rename the conversation
themselves.

**Why the timing matters, and is not cosmetic.** A manual rename is
`POST /api/threads/{id}/state`, and that route holds `reserve_checkpoint_write`,
which raises `ConflictError` → **409 "Thread has a run in flight. Update state
after the run finishes."** while a run is live. So the automatic rename used to
land during the exact stretch in which the user's own rename is refused: you
watch the sidebar entry change under you and cannot correct it until the answer
finishes. Moving the hook to `after_agent` puts the automatic rename in the same
window the user gets their manual one back. That is the whole design goal of the
move, and a refactor that pushes it back into the loop for latency reasons is
undoing the feature, not optimizing it.

- **`after_agent`, not `after_model` — pinned by identity, not by name.**
  LangChain's agent factory decides where a middleware's node goes by comparing
  the bound method against `AgentMiddleware`'s base implementation:
  `after_agent`/`aafter_agent` become the graph's **exit node**, `after_model`
  runs once per model call *inside* the loop. `test_auto_title_preference.py`
  asserts on exactly those four comparisons, so the test pins the graph position
  rather than a method name — renaming the hook back is red, and so is adding an
  `after_model` override "as well".
- **The golden replay is the proof, and it moved on purpose.**
  `tests/fixtures/replay/write_read_file.ultra.events.json` records the SSE
  key-sequence of a real recorded turn. Before the move, `title` appeared in the
  `values` frames from **index 6 onward** — mid-run, while the user's own rename
  was still being refused with a 409. It now appears only in the **last** frame
  before `end`. A merge that puts the hook back in the loop shows up there as a
  golden diff, which is the most direct evidence this feature works that the
  suite has. Regenerate it with `DEERFLOW_WRITE_GOLDEN=1 uv run pytest
  tests/test_replay_golden.py` only when you mean to change the timing.
- **The prompt now describes the answer, not the tool scaffolding.** At
  `after_model` on a tool-using turn the only assistant message is the
  tool-call message, whose text content is usually empty, so the title was
  written from the request alone. `_get_title_assistant_message` takes the
  **last** assistant message that carries text — which at `after_agent` is the
  final answer — and falls back to the first. This is a consequence of the move,
  not a separate feature: revert it and titles quietly get worse on every turn
  that used a tool, with nothing failing.
- **The clarification exit had to be covered, or a whole class of conversation
  is never named.** `ask_clarification` ends the run with `Command(goto=END)`,
  which LangGraph honors directly and which therefore **bypasses the
  `after_agent` node**. That is fine for most middleware and fatal here, because
  `_should_generate_title` requires *exactly one* user message: miss the first
  turn and the second turn has two, so the conversation stays *New Conversation*
  **permanently**. The worker's existing `_ensure_interrupted_title` — written
  for cancelled runs — now runs on every terminal status instead of only
  `interrupted`. Its cost on the ordinary success path is **one**
  `aget_tuple`, and the ordering matters: `_checkpoint_title` is read *before*
  `wait_for_prior_finalizing`, because that wait is an unbounded poll loop that
  used to be reached only by cancelled runs. Widening the guard without moving
  the read first would let one stuck older run hold up the finalization of every
  completed run on the thread. Do not narrow the guard back to `interrupted` to
  save the read either: the failure it prevents is silent and permanent.
- **The per-run preference is a one-way opt-out, and the model name is
  validated.** `apply_auto_title_preference` (in `config/title_config.py`, so
  both the lead-agent factory and the run worker resolve it the same way) layers
  two context keys on the operator's block. `auto_title_enabled: false` disables
  renaming for the run; an explicit `true` deliberately changes nothing, so a
  browser can never switch on a feature the operator turned off — the same
  contract as `memory_enabled` (§ *Long-term memory off by default*).
  `auto_title_model_name` is checked against `app_config.models` and **dropped**
  when it names a model the operator has not configured; that string arrives
  from a client, and honoring it unchecked is how a client picks the run's
  model. A config object with no `models` attribute at all means "no catalog to
  check against" and accepts the name — not the same as a configured-but-empty
  catalog, which rejects everything.
- **Three states for the model, and two of them look alike.** The key being
  **absent** means "keep `config.yaml -> title.model_name`"; the **empty string**
  means "clear it — rename without a model call". Collapsing them is the silent
  regression: send `""` for both and a user who configured a title model server
  side quietly stops getting it; omit for both and a user who asked for no model
  call quietly starts paying for one. The frontend keeps the same three states
  (`undefined` / `""` / a name) in `localStorage`, and `autoTitleRunContext()`
  omits the key rather than sending `undefined`.

**Where it's wired.**

| Piece                                                     | Location                                                                                                       |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| The hook, and the assistant-message selection             | `backend/packages/harness/deerflow/agents/middlewares/title_middleware.py`                                      |
| The per-run resolver (pure, shared by both call sites)    | `backend/packages/harness/deerflow/config/title_config.py` (`apply_auto_title_preference`)                      |
| Applied to the config the middleware chain is built from  | `backend/packages/harness/deerflow/agents/lead_agent/agent.py` (`_assemble_lead_agent`)                         |
| Clarification / cancellation fallback                     | `backend/packages/harness/deerflow/runtime/runs/worker.py` (`_ensure_interrupted_title`, now on every status)   |
| Context allowlist (without it the toggle is a no-op)      | `backend/app/gateway/services.py` (`_CONTEXT_CONFIGURABLE_KEYS`)                                                |
| Operator master switch, for the greyed-out toggle          | `backend/app/gateway/routers/features.py` (`auto_title` in `GET /api/features`)                                |
| Stored preference and the run-context keys                | `frontend/src/core/settings/local.ts`, `frontend/src/core/threads/run-context.ts` (`autoTitleRunContext`)       |
| Settings page                                              | `frontend/src/components/workspace/settings/auto-title-settings-page.tsx`                                       |
| i18n                                                       | `core/i18n/locales/{en-US,zh-CN}.ts` + `types.ts` (`settings.autoTitle.*`)                                      |

**No new config keys.** The page reads `title.enabled` and `title.model_name`,
which already existed, so `config_version` is deliberately **not** bumped and the
Helm chart copies are untouched. Adding a key here later does need the full
`scripts/check_config_version.sh` dance described at the top of this section.

Pinned by `backend/tests/test_auto_title_preference.py` (the hook identity, the
final-answer prompt, the opt-out direction, the dropped model name, the three
model states, and the context allowlist) and
`frontend/tests/unit/core/threads/auto-title.test.ts` (the wire shape of the
three states, both call sites, the default, and the merge for settings written
before the toggle existed), plus
`frontend/tests/e2e/auto-title-settings.spec.ts` for the page itself: the
default-on toggle, the picker starting on *Server default*, a model pick and
*No model call* landing in `localStorage` as a name and as `""`, the picker
disappearing when the switch is off, and the greyed-out toggle explaining the
operator's `title.enabled`.

**Verify it works.**

```bash
cd backend && uv run pytest tests/test_auto_title_preference.py tests/test_title_middleware_core_logic.py tests/test_title_generation.py tests/test_features_router.py -q
cd frontend && corepack pnpm test auto-title lazy-panels
cd frontend && corepack pnpm test:e2e auto-title-settings
```

Then end-to-end (`make dev`): open **Settings → Conversation titles**, leave it
on, start a chat and confirm the sidebar entry changes **only after the answer
finishes** (and that **Rename** in the chat's ⋯ menu works at that same moment).
Pick a model in the dropdown and start another chat — the new title should read
like a summary rather than a truncation. Turn the switch off, start a third chat,
and confirm it stays *New Conversation*.

### 34. Local models get as much parallelism as the GPU actually has

Enable subagents, pick a local model, ask for five things at once, and the fork
dispatched three of them concurrently — because `subagent_runtime.max_running`
is 3. That number is chosen once, at startup, with no idea which model the work
will land on. For a hosted model it is the right shape. For a 20 GiB model on a
24 GiB card it is a number about the wrong resource.

**Nothing failed, which is why nobody noticed.** Ollama does not reject an
over-dispatch. One model, more concurrent requests than `OLLAMA_NUM_PARALLEL`
slots: the extras queue *inside the daemon*, invisible to the Gateway, while
each subagent's own `timeout_seconds` runs down against a request that has not
started. Two different local models that do not co-reside — an Ultra-mode lead
on one and subagents on another (§3), or a cost-routing rule that picked a
second one (§15) — and the daemon evicts one to load the other, on every
alternation. Both look identical from outside: local subagents are slow, and no
log says why. That is the same class of silent failure the ComfyUI GPU arbiter
was built for (§23), one layer down.

So the gate asks the question per dispatch instead of once per process, against
numbers the sync already measured. Five subagents on a model that fits once run
one at a time; on a model the card holds twice, two at a time; on models that
co-reside, all of them at once. Four properties are load-bearing:

- **"Fits twice" is two different questions, and answering both with one number
  gets one of them wrong.** Ollama never loads a second copy of a model it
  already has resident — concurrency there is `OLLAMA_NUM_PARALLEL` slots
  against the one copy, whose KV cache `scripts/sync-ollama-models.py` already
  sized for exactly that many slots (§30). Distinct models each need their own
  residency, so those are bounded by a VRAM ledger instead. A single
  "max concurrent local subagents" knob cannot express both.
- **Strict FIFO, deliberately at some cost to throughput.** Admitting a small
  model past a queued large one is free throughput and unbounded starvation for
  the large one, which is the failure the gate exists to prevent rather than a
  tuning opportunity. A model whose footprint exceeds the whole card is charged
  the whole card, so it runs *alone* rather than *never* — it is not
  un-runnable, it is offloaded and slow (§30).
- **The wait is bounded by its own timeout, not by the process one.**
  `subagent_runtime.queue_timeout_seconds` is 300s and bounds a wait for a
  process slot. Reusing it here would fail the fifth of five deliberately
  serialized subagents for being fifth, turning a slow answer into a failed one
  — the fix causing a worse symptom than the bug.
  `local_model_capacity.queue_timeout_seconds` is 1800s for that reason. When it
  does expire the subagent fails as an *admission* failure
  (`LocalModelResidencyTimeout` subclasses `SubagentCapacityError`), so it never
  reads as the delegated work having failed. The wait it bounds is not *new*
  wall-clock time — three sub-agents on a card that holds one take the same
  three slots of time whether the daemon serializes them or this does; what
  changes is that the waiting is visible, bounded, and tunable instead of
  happening inside Ollama. One consequence is worth knowing: the parent's poll
  window is derived from `subagents.timeout_seconds` (1800s → ~1860s) and it
  starts at dispatch, so a serialized batch whose *total* time exceeds that
  window loses its last item to the parent's timeout. That ceiling is unchanged
  by this feature — it applied to the invisible daemon queue too — but it is now
  a number you can reason about.
- **Unknown means ungated, never guessed.** No `ollama.vram_gb`, a hosted
  model, an entry with no `size_bytes`: every one of those dispatches exactly as
  it did before this feature existed. Inventing a footprint would serialize work
  on precisely the deployments that gave the gate the least information.

**Where the numbers come from, and the one new field.** `size_bytes` and
`num_ctx` were already written per entry; the missing term was the KV cache's
per-token cost, which the sync computes for its own sizing and threw away. It is
now written as `kv_bytes_per_token`, so the Gateway can price a model's resident
footprint as *weights + the cache for the window this entry asks for* rather
than weights alone. It is a property of the model, not of this machine, so it
does not go stale when `num_parallel` changes. A config synced before this
change carries no such field; that model is costed at its weights and flagged as
an estimate — it under-counts, which still bounds dispatch better than not
bounding it, and `make dev` re-runs the sync anyway.

**What it deliberately does not do.** It does not consult the daemon. The
ComfyUI arbiter re-reads residency from the services on every acquire because
another process owns that state; this gate arbitrates *this* process's own
dispatches against measurements the sync already took, so bookkeeping is
authoritative and no HTTP round trip sits in front of a subagent. It also does
not stop a local lead and a local subagent from evicting each other — that is
inherent to choosing two models, is already warned about at sync time by
`vram_contention_warning`, and no admission policy can fix it. And it assumes
one Ollama host: a `models:` list split across two machines' daemons would be
costed against one budget.

| Piece            | Where                                                                                  |
| ---------------- | -------------------------------------------------------------------------------------- |
| Plan and gate    | `deerflow/subagents/local_residency.py`                                                |
| Config           | `subagent_runtime.local_model_capacity`, top-level `ollama:` (`deerflow/config/ollama_config.py`) |
| Acquisition      | `SubagentExecutor._aexecute` — inside the process capacity slot, around the whole run   |
| Footprint metadata | `scripts/sync-ollama-models.py::render_entry`, `ModelConfig.kv_bytes_per_token`       |
| Tests            | `backend/tests/test_subagent_local_residency.py`, `test_subagent_executor.py`, `test_sync_ollama_models.py` |

### 35. The sidebar list that scrolled to nowhere

Past 60 rows (`VIRTUALIZATION_THRESHOLD`) the sidebar's chat lists virtualize,
and virtualization here is unusual in one way: the lists do **not** own a scroll
container. Folders (§32) mean there are several lists — one per open folder plus
the root list — and they all scroll inside the sidebar's single
`[data-sidebar="content"]`. So each list has to tell `@tanstack/react-virtual`
its own offset inside that shared container, as `scrollMargin`. That number is
what maps a scroll position onto a row index.

**It was measured once, in a layout effect keyed on the list's own item count.**
Everything that moves a list sits *above* it and moves without that count
changing:

- a folder expands one render after mount, when the per-browser expanded set
  hydrates from `localStorage` (§32) — several hundred pixels, on the very first
  paint the user sees;
- the channels list swaps its skeletons for rows, and the nav list grows an
  "Agents" row, when their queries resolve;
- the window resizes, or a font lands and reflows a section above.

**A stale margin does not misplace a row — it selects the wrong rows.** The
virtualizer picks which items to mount from `scrollOffset` against the margin,
then the component positions each mounted row *relative to its own container*.
The choosing is wrong and the positioning is right, so the mounted rows are drawn
a fixed distance below the band the reader is looking at, and that band is empty.
Conversations in it cannot be scrolled to: they are not in the DOM while their
region is on screen, and scrolling further only slides the hole along. At the
very bottom the range clamps to the last index, so the newest and the oldest
handful still render — which is exactly why this reads as "the middle of my
history is gone" rather than "the sidebar is broken".

**And it is worst after a restart**, which is the part that made it look
haunted. A warm client-side navigation already has the sections above the list
cached at their final heights, and any later page of chats changed the item
count and silently re-measured. A cold load is the one case where every section
settles *after* the single measurement and nothing changes the count again.

The fix is in `frontend/src/components/workspace/thread-list-virtualizer.tsx`:
`useThreadListScrollMargin` keeps the number honest for as long as the list is
mounted, from three signals, because no one of them covers the others.

- **Every render, in a layout effect with no dependency list.** A re-render is
  the cheapest signal that this subtree moved — an opening folder is exactly
  this — and a layout effect lands the correction before the browser paints the
  wrong window. The write is guarded by an equality check, so a no-op
  measurement costs two `getBoundingClientRect` calls and no render.
- **A `ResizeObserver` over the scroll container, the list, and the container's
  own sections**, with a `MutationObserver` keeping that set current as sections
  mount and unmount. A sibling section growing re-renders *it*, not this
  component, so React alone never reports it — this is the cold-load case, and
  the sidebar renders several of its sections conditionally, so the set of boxes
  to watch is not fixed at mount.
- **A passive `scroll` listener as the backstop.** The margin is
  scroll-invariant (`rootTop - parentTop + scrollTop`), so re-reading it during
  a scroll is free of side effects and self-heals anything the observers missed
  before the reader can reach a row a stale margin would have hidden.

**Do not collapse the three into one.** They fail in different directions: the
render pass cannot see a sibling grow, the observers cannot see a change that
resizes no box, and the scroll backstop only fires once the reader has already
started moving. Each on its own leaves a real path to the same silent hole.

**Not addressed here, deliberately.** `MAX_VISIBLE_THREADS` in
`thread-list-model.ts` still bounds the sidebar at 200 non-pinned conversations
and turns pagination off at that point — filed and unfiled alike, since folders
partition the same loaded window. That is a deliberate performance bound with
its own tests, not the bug above; conversations past it are reached from the
chats page, and raising it is a separate change with its own measurements.

While in the same file: **Move to folder ▸ New folder** created the folder and
left the conversation where it was. The entry reads as one action, and the
folder appearing made it look like the action had happened, so the chat quietly
stayed in the list. The create dialog now carries the thread it was opened from
and files it as soon as the folder is named; opened from the `+` in the group
header there is no thread and nothing moves.

| Piece                          | Where                                                                                     |
| ------------------------------ | ----------------------------------------------------------------------------------------- |
| Margin measurement + observers | `frontend/src/components/workspace/thread-list-virtualizer.tsx` (`useThreadListScrollMargin`) |
| Sidebar tree that moves it     | `frontend/src/components/workspace/recent-chat-list.tsx`                                    |
| Unit tests                     | `frontend/tests/unit/components/workspace/thread-list-scroll-margin.dom.test.tsx`, `thread-list-virtualizer.test.ts` |
| E2E                            | `frontend/tests/e2e/sidebar-long-chat-list.spec.ts`, `sidebar-chat-folders.spec.ts`         |

**On testing this.** The unit tests drive each signal directly — happy-dom has
no layout engine, so the rects are stated by the test and the observers are
fired by hand — and five of the eight go red against the single-measurement
version. What they cannot prove is that a real browser agrees, so
`sidebar-long-chat-list.spec.ts` seeds 80 root conversations and 30 in a folder,
loads every page first (so no later fetch can re-measure for it), opens the
folder, and asserts that the sidebar's visible band actually contains
conversation rows. Zero rows in the band *is* the bug, stated the way the user
meets it.

## Credits

All credit for the underlying system goes to the [ByteDance DeerFlow](https://github.com/bytedance/deer-flow) team. This fork wires convenience features around their work.
