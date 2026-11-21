# Change cycle

Run with "run change_cycle.md level 1" (or 2, or 3). Each level includes everything in the levels before it.

| Level | Tests | Typical use |
|---|---|---|
| 1 | Features linked to the changed files | Everyday changes |
| 2 | The whole app | Before a release; after large or risky changes |
| 3 | The whole app + quality review | Periodic clean-up; after a large feature |

**Automatic for every change request, whichever agent or model runs it.** Claude
Code, Codex, Grok Build, any other coding agent and their delegated agents run
level 1 whenever they modify the repository, unless the request names another
level; read-only questions and reviews run nothing. The older phrase
"run the code change cycle from CHANGE_CYCLE.md" means level 1. Explicit user
instructions can narrow delivery (for example, local edits without a PR). Stop
and ask only when a material decision cannot be resolved from the request or
the repository, and report unavailable tools or access honestly: a check that
did not run, or a PR that was not opened, is never reported as done.

This file follows the setup brief bundled with the `repo-change-cycle` skill
([skills/public/repo-change-cycle/references/setup-brief.md](skills/public/repo-change-cycle/references/setup-brief.md));
this repository is the worked example of a repo set up that way. The map it
keeps current is [docs/repo-map/index.md](docs/repo-map/index.md); the
fork-specific test list it runs from is [FORK.md → Post-sync feature
checklist](FORK.md#post-sync-feature-checklist), whose heading
`scripts/upstream_sync.py` parses into every automated sync PR.

## Commands

- Base branch: `main`
- Install: `make install`
- Test one feature: run the paths on its `Tests:` line — `cd backend && uv run pytest tests/test_x.py -q` for `backend/tests/`, `cd backend && uv run pytest ../tests/skills/test_x.py -q` for `tests/skills/`, `cd frontend && pnpm test chat-folders` (the unit test's file name) for `frontend/tests/unit/`, `cd frontend && pnpm test:e2e thread-files` (the spec's name) for `frontend/tests/e2e/`
- Full test suite: `cd backend && make test && make test-blocking-io && make test-bundled-extensions && uv run pytest ../tests/skills -q`, then `cd frontend && pnpm test && pnpm test:e2e`
- Lint / type-check / build: `cd backend && make lint` · `cd frontend && pnpm check` (Prettier, ESLint and `tsc --noEmit`) · `cd frontend && pnpm build` · `make check-agent-guidance`
- Related tests (optional): none
- Live checks (only when asked; they cost money): `cd backend && DEER_FLOW_RUN_LIVE_TESTS=1 make test-live` · `make drift-eval` (needs a configured model)
- Open a PR / merge it: `gh pr create --base main --title TITLE --body-file BODY.md` · `gh pr merge --squash --delete-branch` (or the equivalent GitHub tools your environment provides)

Files changed since the sync point (committed, uncommitted and new; bash):

```bash
git fetch origin
SYNC=$(git log -1 --format=%H -G'Synced by change cycle:' origin/main -- docs/repo-map.md docs/repo-map/index.md)
: "${SYNC:?no sync point found: check the whole map (level 2)}"
{ git diff --name-only --no-renames "$SYNC"; git ls-files --others --exclude-standard; } | sort -u
```

A shallow clone may not reach the sync point; fetch more history
(`git fetch --deepen=500 origin main`) before falling back to level 2.

## Critical checks

Four checks gate **every change that touches code, configuration or a
prompt**, at every level, before anything else: local models fit their window,
nothing listens beyond loopback by default, an existing install still starts,
a run cannot spend past its caps. Their commands are the first lines of
[FORK.md → Critical checks](FORK.md#critical-checks). Each guards something a
user loses outright and the rest of the suite does not notice.

- **Red stops the change.** Fix it or take the change back out. Never skip,
  loosen or raise a threshold to pass; raising a budget a check pins is a
  product decision for the reviewer, stated with what it costs.
- **Once per tree.** Every file they name is collected by `make test`; when
  the level runs `make test`, read their results out of that run first instead
  of running them twice. `scripts/check_config_version.sh` runs beside it.
- **Not affected** for prose-only changes and changes confined to `frontend/`
  (none of them reads a file there); say so in the PR. The one hand-kept link:
  the mode contexts in `frontend/src/core/threads/run-context.ts` are mirrored
  in `backend/tests/test_context_fit_critical.py`.
- **Environmental only with evidence**: the same failure on the unchanged base
  revision in the same environment, recorded in the PR. FORK.md names the
  known ones (an older pre-baked Playwright browser). Do not run
  `playwright install`.

## Every level

1. Work on a branch updated from the latest `main` (`git fetch origin && git checkout -b fix/short-slug origin/main`, prefixed `feat/`, `fix/`, `docs/` or `chore/`). Never commit to `main`.
2. List the files changed since the sync point (command above). This covers this branch and anything merged since the last change cycle.
3. Update `docs/repo-map/` for those files: add new features and files, remove deleted ones, fix renamed ones. Update the board if features, shared nodes, external services or data stores changed. Rewrite the sync line in `docs/repo-map/index.md`.
4. A new feature gets at least one test in the same change. In this repo a feature that is added or removed also owes, in the same change: its bullet in the `README.md` list under "it adds — out of the box:" (written first: if the one-line promise is hard to write, the feature is not finished), a `### N.` section in [FORK.md](FORK.md#adding-a-new-fork-feature--what-to-write-and-where), a checklist row only for a risk that is silent when broken, user docs in `docs/guide/` or `backend/docs/`, one `### Added` line under `## [Unreleased]` in `CHANGELOG.md`, and for a new config key a `config_version` bump in `config.example.yaml` and both chart copies. Review the tests of the area you touched: remove a test only when it duplicates a retained one, exercises removed behavior or cannot fail, and name what still covers it.
5. Run the level's checks, critical checks first. If one fails, fix it and rerun. Don't weaken or delete a test to make it pass unless the behavior change is intended and stated in the PR. If it can't be fixed within this change, stop without merging. Run each check once on the final tree: format first (`cd backend && make format`, `cd frontend && pnpm format:write`), and rerun only what reads a file that changed after the run.
6. Open a PR with the summary below.
7. Merge once the level's checks pass. If `main` breaks after a merge, revert that PR first, then fix.

## Level 1: affected features

- Look up each changed file in the file → features index and run the tests of every feature listed (`ALL` means every feature: run the level 2 suites).
- Run changed test files.
- Run lint / type-check if the repo has them: `cd backend && make lint` for backend changes, `cd frontend && pnpm check` for frontend changes, `make check-agent-guidance` and `backend/tests/test_agent_guidance_check.py` for any `AGENTS.md` edit, `backend/tests/test_change_cycle_doc.py` for this file.
- If the related-tests command is set, run it on the changed files. A test it finds that the map didn't point to means the map is wrong: fix the map and run that test too. (This repo sets none; level 2's full run is what catches a missing link.)
- Run the post-sync checklist rows in FORK.md of the features you touched, ticking a row from a suite that already ran it.

## Level 2: whole app

- Full test suite, lint, type-check and build.
- `git grep -nE '^(<{7}|={7}|>{7})( |$)'` prints nothing.
- Check the map against the code: every file that runs or ships is in the index, every feature has a test, the board shows every feature. `cd backend && uv run pytest tests/test_repo_map.py -q` checks the first two mechanically (and that no index row is stale); the board is checked by eye.
- An upstream merge, or a change whose effects cannot be bounded to named areas, also runs FORK.md's whole post-sync checklist.

## Level 3: quality review

Level 2, then review the whole repo, not only the changed files, for:

- **Duplicate implementations of the same thing.** Example: four separate model dropdowns where one shared component, with a simplified variant if needed, would do. Also duplicated API clients, model or provider lists, URLs, validation and formatting helpers. A shared component with variants is fine; copies are not.
- **Repeated remote calls.** LLM, API or database calls inside loops where one request carrying all items, the provider's batch API (for non-interactive jobs), bounded parallel requests or caching would do; the same data fetched by several components; polling where streaming, events or webhooks exist.
- **Other waste.** Dead code, unused dependencies, generic best-practice text copied into the repo (replace it with a link under References).
- **Also check:** secrets in code or committed config (move them to environment variables; the owner must rotate any secret that was ever committed), and errors that are caught and silently ignored.

Then:

1. Fix each finding unless it's too costly. Too costly (default; adjust per repo): the fix touches more than 10 files, or needs a change to a public API, database schema or stored data.
2. Fixes keep behavior the same. A fix that can't isn't made here; log it with "Why kept: needs owner decision".
3. Log every finding not fixed in [`docs/quality-exceptions.md`](docs/quality-exceptions.md).
4. Check every entry in `docs/quality-exceptions.md`. If its "Fix when" condition is met, fix it and delete the entry. Entries whose condition still holds are not reported again.
5. Rerun the Level 2 checks after the fixes.
6. Quality fixes go in their own PR, separate from feature changes, so either can be reverted alone.

## Model audit (only when asked)

Run the [model audit](FORK.md#auditing-the-model-list-settings--pricing) only
when the request asks for one in words ("and run the model audit"); a level
alone never does. A full pass is a dozen provider page reads for a roster that
usually has not moved, and a price read in a hurry is wrong with confidence.
When you run it: follow FORK.md's steps, read every price off the provider's
own page (or several independent sources that agree, logged as corroborated),
and write the pass into [`docs/model-audit-log.md`](docs/model-audit-log.md); a
pass that is not logged did not happen. `python3 scripts/audit_models.py` is
the cheap machine half and never confirms a price. When you were not asked,
quote the log's last dated line; if the change touched the model bundle
(`config.example.yaml` model blocks, `scripts/wizard/providers.py`,
`scripts/sync-api-key-models.py`, any `price:`/`discount:` block) or the weekly
`model-audit` issue reports drift, add a line recommending one.

## PR summary

```
Level: <1|2|3>
Changed since sync point: <files → features>
Checks run: <commands> — <pass/fail>
Map: <features/files added, removed, renamed; board updated: yes/no>
Quality fixes: <list, or "n/a">
Exceptions added/removed: <list, or "n/a">
Critical checks: <each: inside make test | by itself | not affected — why; result>
Model audit: <run — logged <date> | not run (not asked) — last pass <date>>
PR: <url, once opened>
```

The summary opens the PR body; [`.github/pull_request_template.md`](.github/pull_request_template.md)
carries it, followed by the review sections (why, surface area, test
maintenance).

## References

Generic guidance is linked here, never copied into the repo.

- Owner's guidelines: [AGENTS.md](AGENTS.md) and the nested `AGENTS.md` files, [FORK.md](FORK.md), [CONTRIBUTING.md](CONTRIBUTING.md)
- [Refactoring Guru: code smells](https://refactoring.guru/refactoring/smells), including duplicate and dead code
- [web.dev Learn](https://web.dev/learn) (performance, accessibility); [The Twelve-Factor App](https://12factor.net) (config, backing services, deploys)
- [OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org)
- [OWASP Top 10 for LLM Applications](https://genai.owasp.org/llm-top-10/)
