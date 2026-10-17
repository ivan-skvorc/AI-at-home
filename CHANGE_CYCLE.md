# The code change cycle

**Automatic for every change request, whichever agent or model runs it.** Claude
Code (Opus, Sonnet), Codex/ChatGPT (Sol, Astra), Grok Build, any other coding
agent, and their delegated agents follow this procedure whenever they modify the
repository. Read it before editing; no special phrase is needed. Read-only
questions and reviews do not start a change cycle. Nothing here depends on one
vendor's tools: where a step names a command (`gh`, a PR tool), use the
equivalent your environment provides, and report it if there is none. Explicit user instructions
can narrow the scope (for example, local edits without a PR); otherwise carry
the cycle through to an open pull request without asking for each step.

The existing phrase remains a supported reminder:

> run the code change cycle from CHANGE_CYCLE.md

Stop and ask only when a material decision cannot be resolved from the request
or repository. Report unavailable tools or access honestly; do not claim an
unfinished check or unopened PR is complete.

**The shape, end to end:** run relevant existing tests → make the change → reuse
coverage, add missing tests, and remove unnecessary tests in the affected area →
maintain FORK.md's checklist → run the required checks at the scope in step 5,
including new or changed tests → run the model audit **only if you were told
to** → land the docs, and a **new feature owes `README.md` its bullet** → commit,
push, and **open the pull request**. The cycle is
not finished when the tests pass; it is finished when the PR is open. Nobody has
to ask for that PR separately — it is step 9, not a follow-up request.

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

Inspect the working tree, the root and applicable nested `AGENTS.md` files, and
existing tests for the affected behavior. Choose the checks using step 5 and run
the relevant existing tests before editing to establish a baseline. Give delegated
agents the same instructions and scope; the lead agent remains responsible for
the final combined checks and the PR. Preserve unrelated user changes.

## 2. Implement the smallest sufficient change

Change only the paths the accepted outcome needs. Do not widen the diff with
speculative abstractions, compatibility layers, or drive-by refactors; note them
instead and let the next cycle decide.

## 3. Maintain useful tests: reuse, add, and remove

Review existing coverage before adding anything. Ask whether it already protects
the changed behavior, and answer in the report. Add or extend a test only when
there is a gap, particularly when the change:

- alters behavior a caller, user, or the UI can observe;
- changes a default, a config key, a schema, a stored shape, or a wire contract;
- fixes a bug — reproduce an executable regression **before** the fix;
- adds or removes a security, ownership, or concurrency boundary;
- relies on an invariant whose broken state is **silent** (a lock that must stay
  scoped, an option that must reach the wire, a branch that must decline rather
  than evict). This is the fork's most common shape, and the reason a row exists
  at all.

**No new test** when existing tests already prove the contract, or for prose docs,
comments, formatting, and renames with no behavior change. Name the existing
coverage or say "no new test, <reason>". Prefer extending the nearest focused test
or parameterizing equivalent cases to adding a parallel suite. Use the cheapest
test layer that catches the failure; add E2E only when a user workflow needs it.

Where they go: `backend/tests/` for Python (TDD for new behavioral coverage),
`frontend/tests/unit/` for the pure model, `frontend/tests/e2e/` for a user
workflow. Then:

- **Prove new behavioral coverage detects the regression.** Run it before the
  fix, or safely reproduce the old behavior in isolation, then run the final
  version after the change. Explain when a failing reproduction is impractical.
- **Pin the property, not the implementation** — assert the thing a future
  refactor would quietly "simplify" away.

### Review and remove unnecessary tests on every change

Review tests for the area being changed, including nearby fixtures and checklist
commands. Keep this local to the task; a routine change is not a suite-wide purge.
Remove or consolidate tests when evidence shows they:

- duplicate the same contract and failure mode already covered by a retained test;
- exercise removed behavior or assert an implementation detail no longer required
  by any caller, contract, or security boundary;
- cannot detect a regression (for example, assertions only on a mock's own setup).

For every removal, name the retained coverage or the behavior deliberately removed
and explain why no unique guarantee is lost. Preserve distinct edge cases and
regression, security, ownership, and concurrency checks. A slow or flaky test needs
investigation; failure, age, test count, or runtime alone never justifies deletion.
Never delete, weaken, skip, or quarantine a test just to make a failing run green.

Update shared fixtures, FORK.md rows, and other references in the same change set,
then run the remaining affected suite. Record tests reviewed, added/reused,
removed/consolidated, and the reason in the PR's **Test maintenance** section.
"None removed — <what was reviewed and why it remains useful>" is a valid outcome;
there is no quota for adding or removing tests.

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

## 5. Run existing tests at the required scope

Always run relevant **existing** tests, as well as any tests added or changed.
Use the baseline from step 1 to distinguish pre-existing failures from regressions.
After all edits (including docs and formatting), run the checks below and the
affected rows in the [post-sync checklist](FORK.md#post-sync-feature-checklist):

| Change | Required final checks |
| ------ | --------------------- |
| Docs, comments, formatting, or agent guidance only | Relevant existing documentation/contract tests and link checks; for any `AGENTS.md` edit, run `python3 scripts/check_agent_guidance.py` and `backend/tests/test_agent_guidance_check.py`; for this procedure, run `backend/tests/test_change_cycle_doc.py`. No application-wide suites for prose alone. |
| Backend code | `cd backend && make lint && make test`; also `make test-blocking-io` for async, runtime, or I/O changes. |
| Frontend code | `cd frontend && pnpm check && pnpm test`; run affected `pnpm test:e2e <pattern>` workflows for UI behavior. Shared UI controls, navigation, or streaming changes require the full E2E suite. |
| Scripts, config, build, or CI | Existing tests for the changed commands/contracts and affected consumers; add module gates when their behavior can change. |
| Upstream merge, changes whose effects cannot be bounded to named areas, or explicit full-cycle validation request | Whole post-sync checklist: mechanical gates, then every feature row. |

The reminder phrase alone uses this table; it does not request unrelated suites.
For a complete cross-module pass, the wide gates include:

```bash
git grep -nE '^(<{7}|={7}|>{7})( |$)'   # must print nothing
cd backend  && make lint && make test
cd frontend && pnpm check && pnpm test
cd frontend && pnpm test:e2e            # no filter — a shared control's specs are not in the file you edited
```

Run each check once on the final tree. When a selected suite already executes a
checklist row or a new test, record that coverage instead of repeating the same
command; run separately only what the suite omits. Broaden or repeat checks when
failures, new edits, or unresolved impact justify it. A test written and never executed in
its final form is the most common way this cycle ships red: it passed while you
were iterating, then a rename, a fixture edit, or a formatter pass moved under it.

**Environmental failures are reported, never patched away.** FORK.md names the
known ones — chiefly a sandbox whose pre-baked Playwright browsers are older
than the pinned `playwright`, which fails deterministically and is not a
regression. Reproduce the same failure on the unchanged base revision in the same
environment before calling it environmental, then report that evidence. When
this is not possible, classify it as an unresolved validation failure. Do **not** run
`playwright install`, and never skip, disable, or quarantine a test to reach
green.

## 6. Model audit — optional, and only on instruction

**Do not run it unless you were told to.** This is the one step of the cycle
that is opt-in: the trigger sentence alone does not ask for it. Run the
[audit pass](FORK.md#auditing-the-model-list-settings--pricing) when the request
asks for one in words — "and run the model audit", "audit the models", or the
same thing said any other way — and not otherwise.

The reason it is opt-in rather than conditional: a full pass is a dozen provider
page reads for a roster that usually has not moved, and a *wrong* price read in a
hurry is worse than a stale one, because it is wrong with confidence and silences
the next pass. When you were not asked, quote the last dated line of
[`docs/model-audit-log.md`](docs/model-audit-log.md), say the audit was not run,
and move on.

**Two cases still get a sentence in the report, without running anything.** They
are recommendations, not triggers — the decision stays with whoever asked for the
change:

- the change touched the bundle — `config.example.yaml` model blocks,
  `scripts/wizard/providers.py`, `scripts/sync-api-key-models.py`, or any
  `price:` / `discount:` block;
- the weekly `model-audit` issue reports real drift.

Say which one applies and that an audit is worth asking for. Editing a price is
not the same as auditing the roster, so a change that edits one entry still owes
the reader that note.

When you do run it: follow FORK.md's eight steps, read every price off the
provider's own page (or several independent sources that agree, recorded as
corroborated), and **write the pass into `docs/model-audit-log.md`** — a pass
that is not logged did not happen, since the log is what the next reader checks
before deciding whether to run one. The cheap machine half is
`python3 scripts/audit_models.py`; it never confirms a price.

## 7. Land the documentation in the same change set

Per [Adding a new fork feature](FORK.md#adding-a-new-fork-feature--what-to-write-and-where):
`README.md` for the user-facing half (plus its TOC and the leading bullet list),
a `### N.` section in FORK.md for the reasoning, the nearest `AGENTS.md` for
what an agent must know before editing the code, and one `### Added` bullet
under `## [Unreleased]` in `CHANGELOG.md`. Any new config key also bumps
`config_version` and **both** chart copies.

### Does the change add a feature? Then it owes `README.md`

Ask it explicitly, the way step 3 asks about tests, and answer it in the report.
**Yes** when the change gives a user something they could not do before, or could
do only by hand: a new page, panel, button, setting, config key, tool, backend,
model source, or command — and equally when it *removes* one, because the list
below is a promise about what is there today. **No** for a fix that restores
intended behavior, an internal refactor, or a performance change nobody can name
from the outside. Say "no README change, <reason>" rather than leaving it
unstated. This is the one documentation duty nothing in CI can fail for you: a
feature that ships without its README line is a feature nobody discovers, and the
suite stays green the whole way.

**Start with the bullet points.** Before the prose, before the TOC, before
FORK.md — write the bullet. The leading list inside the blockquote at the top of
`README.md` ("On top of upstream, it adds — out of the box:") is the fork's shop
window, deliberately **exhaustive**: every upgrade this fork has over
[upstream](https://github.com/bytedance/deer-flow) gets one line, with its own
emoji, in the same change set that adds it. Two or three sentences that lead with
what a user *gets*, name the behavior they would not expect, and say what it costs
to switch on (a config key, a daemon setting, nothing). Writing it first is not
ceremony: if the one-line promise is hard to write, the feature is not finished,
and the deeper section is easier once it exists. A removed feature loses its
bullet in the same change set, the way it loses its checklist row in step 4.

Those bullets sit inside the three things `README.md` has to keep, whatever else
changes around them:

- **A short description of the repo** — what DeerFlow is, in a few sentences a
  newcomer reads without scrolling.
- **Its goals** — what this fork is *for* (a private, self-hosted personal AI you
  reach over your own network, cheap to run, yours), so a reader can tell whether
  a proposed change belongs here at all.
- **The bullet list of what it adds over upstream** — exhaustive, one bullet per
  feature, and the part you edit first.

Only then the depth: a `###` subsection under **Core Features** (or a top-level
`##` for something that is not a core-agent behavior), plus its anchor in the
hand-maintained Table of Contents — a section missing from the TOC is a section
nobody browses to. FORK.md's [Adding a new fork
feature](FORK.md#adding-a-new-fork-feature--what-to-write-and-where) owns what
belongs inside that subsection.

## 8. Format, commit, push

Format only the affected code, then rerun any checks affected by formatting.
For backend code use `make format`; for frontend code use `pnpm check`.
Stage only files belonging to this change; preserve unrelated work.

```bash
git diff --check
git add <changed-paths>
git commit -m "<type>: <what changed for the user>"
git push -u origin <branch>
```

## 9. Open the pull request

**This step is not optional and does not wait to be asked for.** The change is
delivered when a reviewer can see it, and a pushed branch nobody opened a PR
against is work that has not been handed over. Open it yourself, as the last
action of the cycle, against the default branch.

Fill in [`.github/pull_request_template.md`](.github/pull_request_template.md) —
**every** section, in its own words rather than a restatement of the diff:

- **Why** — the observable problem from step 1, not the implementation.
- **What changed** — what a user or caller sees differently now.
- **Surface area** — what the change can reach that the diff does not name.
- **Bug fix verification** — for a fix, how the bug was reproduced before it.
- **Validation** — the commands you actually ran and their outcome, plus any
  failure classified as environmental **with the evidence from step 5**. This is
  the section reviewers read first and the one most often filled in with
  intentions instead of results; "the suite passes" without the numbers is not
  validation.
- **Test maintenance** — the coverage reviewed, tests added or reused and why,
  tests removed or consolidated with retained coverage or retired behavior,
  and the reason for the validation scope. State when no new or removed tests
  were needed; do not leave the decision implicit.

Then post the link. One PR per cycle: if the branch already carries earlier
commits from this session, say so in **What changed** rather than opening a
second PR against the same branch — a branch has one PR, and a second one is
either a duplicate or a mistake.

## 10. Report

Last thing you output, in this shape:

```text
Change:           <the one sentence from step 1>
Tests added:      <paths, or "none — <reason>">
Tests reviewed:   <existing coverage reused and scope>
Tests removed:    <paths and retained coverage/retired behavior, or "none — <reason>">
README:           <the bullet added or edited, or "no README change — <reason>">
Rows added:       <FORK.md rows>
Rows removed:     <rows, and why they went obsolete>
Validation:       <scope, commands and results; failures/skips and evidence>
Model audit:      <run — logged <date> | not run (not asked) — last pass <date>
                  [; recommended because <bundle touched | drift reported>]>
PR:               <url>
```

**Done means:** the checks required by step 5 ran, test maintenance was reviewed,
the checklist matches the code, the docs landed in the same change set, and
**the PR is open with its URL in the report** (unless the user explicitly narrowed
delivery). If checks or PR creation are blocked, report the actual failure and
remaining work; do not call the cycle complete.
