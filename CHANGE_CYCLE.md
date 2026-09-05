# The code change cycle

**The trigger.** State the change you want, then end the request with:

> run the code change cycle from CHANGE_CYCLE.md

That sentence means: do everything below, in this order, without asking for the
steps one at a time. Stop and ask only when a step cannot be decided from the
repository — never to confirm that the next step should happen.

**Two files, one procedure.** This file is the **procedure**: the order, the
decisions, and the gates. It owns no test commands of its own. The material it
runs on lives in [`FORK.md`](FORK.md):

| What | Where |
| ---- | ----- |
| The test list | [FORK.md → Post-sync feature checklist](FORK.md#post-sync-feature-checklist) — mechanical gates, then one row per fork feature naming the exact command that proves it still works |
| The model audit | [FORK.md → The model bundle and its audit](FORK.md#the-model-bundle-and-its-audit), whose pass is [Auditing the model list](FORK.md#auditing-the-model-list-settings--pricing) |
| What a new feature must document | [FORK.md → Adding a new fork feature](FORK.md#adding-a-new-fork-feature--what-to-write-and-where) |

Keep it that way. `scripts/upstream_sync.py` parses the checklist **out of
FORK.md by heading** into every automated sync PR, so a row that moves to
another file silently disappears from the list meant to prove the fork still
works.

---

## 1. Restate and branch

Restate the change in one sentence — the observable behavior that is wrong or
missing, and what replaces it. If the sentence cannot be written, the
requirements are not sufficient yet: say so and stop.

```bash
git checkout -b <feat|fix|docs|chore>/<short-slug>
```

Never commit to `main`. For anything beyond a mechanical edit, run the decision
gates in [`.agent/skills/engineer-system-change`](.agent/skills/engineer-system-change/SKILL.md)
first — they are what keeps a real problem from turning into an oversized fix.

## 2. Implement the smallest sufficient change

Change only the paths the accepted outcome needs. Do not widen the diff with
speculative abstractions, compatibility layers, or drive-by refactors; note them
instead and let the next cycle decide.

## 3. Decide whether the change needs a new test — then write it

Ask it explicitly, and answer in the report. **Yes** when the change:

- alters behavior a caller, user, or the UI can observe;
- changes a default, a config key, a schema, a stored shape, or a wire contract;
- fixes a bug — the bug becomes a failing test **before** the fix;
- adds or removes a security, ownership, or concurrency boundary;
- relies on an invariant whose broken state is **silent** (a lock that must stay
  scoped, an option that must reach the wire, a branch that must decline rather
  than evict). This is the fork's most common shape, and the reason a row exists
  at all.

**No** for prose docs, comments, formatting, and renames with no behavior
change. Say "no new test, <reason>" rather than leaving it unstated.

Where they go: `backend/tests/` for Python (TDD is mandatory there),
`frontend/tests/unit/` for the pure model, `frontend/tests/e2e/` for a user
workflow. Then:

- **Prove it fails without the change.** Neutralize the one line that implements
  the behavior, watch the new test go red, put it back. A test that passes both
  ways pins nothing.
- **Pin the property, not the implementation** — assert the thing a future
  refactor would quietly "simplify" away.

## 4. Update the test list in FORK.md

Same change set as the code. Three operations, and the third is the one people
skip:

- **Add a row** when the change adds a fork feature, or a load-bearing invariant
  an upstream merge could break **silently**. That is the table's job — it is a
  *post-sync* list, so a check the mechanical gates already run (anything inside
  `make test` or `pnpm test` that fails loudly on its own) does not need one.
  Row content: the feature name, the exact command, and the one or two asserts
  that are silent when broken. Depth goes in the feature's own `### N.` section
  or the nearest `AGENTS.md`, never in the row.

  **The table is over budget today, so a new row has to be paid for.** The
  generated sync-PR body is clamped at 65,000 characters
  (`scripts/upstream_sync.py`) against GitHub's 65,536 limit, and the current
  checklist already renders past it — the tail is being truncated out of every
  automated sync PR. `test_the_body_stays_within_github_limits` cannot catch
  that: it measures the body *after* truncation, so it passes either way. Check
  what a row actually costs before adding one, and shorten an existing row to
  make room:

  ```bash
  python3 -c "
  import importlib.util, sys, pathlib
  spec = importlib.util.spec_from_file_location('us', 'scripts/upstream_sync.py')
  m = importlib.util.module_from_spec(spec); sys.modules['us'] = m; spec.loader.exec_module(m)
  c = m.parse_post_sync_checklist(pathlib.Path('FORK.md').read_text(encoding='utf-8'))
  b = m.render_pr_body(checklist=c, gates={}, conflicts=[], upstream_sha='x', commit_count=1)
  print(len(b), 'chars; truncated:', 'truncated; see FORK.md' in b)"
  ```

- **Edit the row** when the command, the test path, or the property changed.
- **Remove the row** when the feature is gone, or when the check no longer
  proves anything. A row whose test no longer exists is worse than no row: it
  reads green and checks nothing. Sweep for those every cycle:

  ```bash
  # any test path the checklist names that is no longer on disk. Rows quote
  # paths relative to backend/ or frontend/ as often as from the root, so try
  # all three before believing a hit.
  grep -oE '(backend/|frontend/)?tests/[A-Za-z0-9_/.-]+\.(py|ts|tsx)' FORK.md \
    | sort -u \
    | while read -r p; do
        [ -f "$p" ] || [ -f "backend/$p" ] || [ -f "frontend/$p" ] || echo "MISSING: $p"
      done
  ```

  Anything it prints is either a row to fix or a row to delete — decide, don't
  leave it.

## 5. Run the full list

The whole [post-sync checklist](FORK.md#post-sync-feature-checklist), in its own
order: the mechanical gates first, then every feature row — not only the rows
you think you touched. The wide gates are:

```bash
git grep -nE '^(<{7}|={7}|>{7})( |$)'   # must print nothing
cd backend  && make lint && make test
cd frontend && pnpm check && pnpm test
cd frontend && pnpm test:e2e            # no filter — a shared control's specs are not in the file you edited
```

Then the per-row commands from the table.

**Environmental failures are reported, never patched away.** FORK.md names the
known ones — chiefly a sandbox whose pre-baked Playwright browsers are older
than the pinned `playwright`, which fails deterministically and is not a
regression. Confirm one against `origin/main` on the same commit before calling
it environmental, then say so in the report with that evidence. Do **not** run
`playwright install`, and never skip, disable, or quarantine a test to reach
green.

## 6. Model audit — decide, don't default

Run the [audit pass](FORK.md#auditing-the-model-list-settings--pricing) **only**
when one of these is true:

- the change touched the bundle — `config.example.yaml` model blocks,
  `scripts/wizard/providers.py`, `scripts/sync-api-key-models.py`, or any
  `price:` / `discount:` block;
- the weekly `model-audit` issue reports real drift;
- the user asked for one.

Otherwise quote the last dated line of
[`docs/model-audit-log.md`](docs/model-audit-log.md), say the audit was not due,
and move on. Re-deriving an unchanged roster costs a dozen provider page reads
for the answer the last pass already gave.

When you do run it: follow FORK.md's eight steps, read every price off the
provider's own page (or several independent sources that agree, recorded as
corroborated), and **write the pass into `docs/model-audit-log.md`**. The cheap
machine half is `python3 scripts/audit_models.py`; it never confirms a price.

## 7. Land the documentation in the same change set

Per [Adding a new fork feature](FORK.md#adding-a-new-fork-feature--what-to-write-and-where):
`README.md` for the user-facing half (plus its TOC and the leading bullet list),
a `### N.` section in FORK.md for the reasoning, the nearest `AGENTS.md` for
what an agent must know before editing the code, and one `### Added` bullet
under `## [Unreleased]` in `CHANGELOG.md`. Any new config key also bumps
`config_version` and **both** chart copies.

## 8. Format, commit, push

```bash
cd backend  && make format
cd frontend && pnpm check
cd .. && git add -A
git commit -m "<type>: <what changed for the user>"
git push -u origin <branch>
```

## 9. Open the pull request

Fill in [`.github/pull_request_template.md`](.github/pull_request_template.md) —
every section, including **Validation** with what you actually ran and any
failure you classified as environmental.

## 10. Report

Last thing you output, in this shape:

```text
Change:           <the one sentence from step 1>
Tests added:      <paths, or "none — <reason>">
Rows added:       <FORK.md rows>
Rows removed:     <rows, and why they went obsolete>
Full list:        <pass | pass except <check> (environmental, evidence: …)>
Model audit:      <run — logged <date> | not due — last pass <date>>
PR:               <url>
```

**Done means:** the list ran, the checklist matches the code, the docs landed in
the same commit, and the PR is open. A green diff with a stale checklist is not
done.
