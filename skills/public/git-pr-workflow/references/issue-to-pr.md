# From a GitHub issue to a verified pull request

Turn an issue into a tested pull request with honest CI reporting. Use it for
"fix issue #123 and open a PR", "implement this feature request", or "take this
bug to green CI". It is not for reviewing an existing pull request
(`code-review.md`) or answering a question that needs no change.

## 1. Read the live issue, body and full thread

Run `gh issue view N --comments` with `bash`, or read the issue and its comments
endpoints through the REST API. The body is a snapshot from filing time; the
newest comments carry the live state: partial fixes already merged, new root
causes, maintainer decisions, questions addressed to you. Read the repository's
instructions too (AGENTS.md, contribution docs) with `read_file`. Done when the
requested behavior, the non-goals and any open questions are known.

## 2. Sweep for existing and duplicate work

Before writing anything, search for open and closed pull requests that mention
the issue number, plus at least two keyword variants of the symptom
(`gh pr list --search "#N" --state all`, `gh pr list --search "upload timeout"`).
Check whether a recent commit already fixed it: `git log --oneline -20` on the
relevant files. Done when you know every pull request and recent commit that
touches the issue, or that there are none.

## 3. Validate the premise against current code and design intent

Reproduce the bug or show the missing behavior on the current default branch,
ideally as a failing test (the test-driven-development skill). Trace the
reported path with `grep`, `glob` and `read_file`. Then ask whether the "bug" is
deliberate: `git log -p -S "symbol"` on the code the issue wants changed shows
the original intent. Challenge stale or mistaken issue text instead of
implementing it blindly. Done when the root cause or the gap is demonstrated in
current code and the change does not fight an intentional design.

## 4. Define acceptance and risk

List the acceptance criteria, the interfaces touched, state or migration
changes, compatibility, security and privacy, rollout and rollback. Map every
criterion to a test or an explicit verification step.

## 5. Implement the smallest complete change and fix the whole class

Create the branch with `gitflow.py branch`, named like fix/issue-N (or a worktree when
subagents work in parallel). Add the regression test first, then the fix. When
the fix works, `grep` for the same bug shape at sibling call sites and fix them
in the same pull request, or rule them out explicitly. Every changed line should
trace to the issue; no drive-by cleanup.

## 6. Prove the regression test bites

Checkpoint, temporarily restore the old behavior of the function under test, run
the new test and confirm it fails, then restore the fix (`gitflow.py restore`
with the checkpoint id) and confirm it passes. A test that passes with and
without the fix proves nothing.

## 7. Run the quality gates, then open the pull request

Run the formatter, linter, type checker and the project's test entry point on
the affected area. Review your own diff (`code-review.md`). Commit, push and
open the pull request right away: CI only starts once it exists. The body links
the issue ("Closes #N") and states the problem, the approach, the tests you ran,
the risk and what is out of scope. `gitflow.py pr create` reads the pull request
back; check its `head_sha`, `base` and `title`.

## 8. Shepherd CI honestly and close the loop

Read the live checks with `gitflow.py pr status` and the failing logs as
described in `ci-troubleshooting.md`. Separate failures caused by your diff from
pre-existing or infrastructure failures (reproduce on the default branch when
unsure; rerun once only for a genuine flake). Never say green, merged or
released without that exact state in the latest output. When the pull request
lands, and if the user wants it, comment on the issue with the pull request link
and one line of explanation.

## Pitfalls

- Coding before reading the issue comments, sweeping for duplicates, or reading
  the current code.
- "Fixing" behavior that the history shows is intentional.
- Fixing one call site while siblings keep the same bug.
- A regression test that also passes without the fix.
- A pull request with unrun tests or unrelated formatting churn.
- Calling the issue delivered because a pull request exists.

## Checklist

- [ ] Full issue thread read; the newest state is reflected in the plan.
- [ ] Duplicate sweep run with the issue number and two keyword variants.
- [ ] Premise reproduced on current code; design intent checked in history.
- [ ] Regression test shown to fail without the fix.
- [ ] Sibling call sites fixed or ruled out.
- [ ] Every changed line traces to the issue.
- [ ] CI state reported from live `pr status` output only.
