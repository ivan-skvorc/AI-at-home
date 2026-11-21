# Pull request workflow

The full lifecycle of a change, from a fresh branch to a merged pull request,
with gitflow.sh doing the steps that must not go wrong. In the commands below,
GITFLOW stands for bash /mnt/skills/public/git-pr-workflow/scripts/gitflow.sh.
Write the full command each time, because a `bash` call keeps no variables.

## 1. Before you start

- Run `GITFLOW preflight` and read `warnings`.
- Read the repository's contribution rules with `read_file`: AGENTS.md,
  CONTRIBUTING.md, the pull request template (under the .github directory), and
  the CI workflows. They name the test, lint and format commands and the
  expected commit style.
- If the work comes from an issue, follow `issue-to-pr.md` in this directory.

## 2. Branch

~~~bash
cd /mnt/user-data/workspace/myrepo && GITFLOW branch feat/user-auth
~~~

Branch name prefixes:

| Prefix | For |
| --- | --- |
| feat/ | new features |
| fix/ | bug fixes |
| refactor/ | restructuring without behavior change |
| docs/ | documentation |
| test/ | tests only |
| ci/ | CI and build pipeline changes |
| chore/ | maintenance, dependencies, tooling |

Use the repository's own convention when its docs name one.

## 3. Change, test, commit

1. Checkpoint before a risky edit: `GITFLOW checkpoint -m "before splitting the module"`.
2. Edit with `str_replace` and `write_file`; inspect with `read_file`, `grep` and
   `glob`.
3. Run the project's tests, linters and formatter with `bash`. A commit is a
   claim that the tree works.
4. Commit only the files you changed, one logical change per commit, with a
   Conventional Commits message (`conventional-commits.md`):

~~~bash
cd /mnt/user-data/workspace/myrepo && GITFLOW commit --paths src/auth.py tests/test_auth.py --message-file - <<'EOF'
feat(auth): add JWT-based login

- Add login and register endpoints
- Hash passwords with argon2
- Cover the token refresh path with tests

Closes #42
EOF
~~~

The quoted heredoc marker (`<<'EOF'`) stops the shell from expanding dollar
signs and backquotes in the message. If the secret scan refuses, take the
secret out of the file (read it from the environment at runtime instead) and
commit again; do not commit with plain git to get past it.

## 4. Push

~~~bash
cd /mnt/user-data/workspace/myrepo && GITFLOW push
~~~

Report the `remote_sha` it printed. After a rebase or an amend on your own
branch, push with `--force-with-lease`; it refuses to overwrite commits that
someone else pushed in the meantime. A rejection with a non-fast-forward hint
means the remote branch moved: fetch, rebase onto it, run the tests, and push
again.

## 5. Write the pull request body

Start from `../templates/pr-body-feature.md` or `../templates/pr-body-bugfix.md`
(or the repository's own template, which takes precedence) and write the body
with `write_file` to a file outside the repository, such as
/mnt/user-data/workspace/pr-body.md. A good body states:

- what changed and why, in a few bullets;
- how it was tested: only the commands you actually ran and their outcome;
- risk and rollback, and anything reviewers should look at first;
- the issue it closes ("Closes #42") when there is one.

## 6. Open the pull request

~~~bash
cd /mnt/user-data/workspace/myrepo && GITFLOW pr create --title "feat(auth): add JWT-based login" \
  --body-file /mnt/user-data/workspace/pr-body.md
~~~

Add `--draft` for work in progress and `--base BRANCH` when the target is not
the default branch. Running it again returns the existing open pull request
(`created: false`) instead of opening a second one. Give the user `url` and
`number` from the output. Reviewers and labels are not part of gitflow.sh; see
the table at the end.

## 7. Watch CI and fix failures

~~~bash
cd /mnt/user-data/workspace/myrepo && GITFLOW pr status
~~~

- `checks.state` pending: CI is still running. Check again later; do not report
  success.
- `checks.state` failure: read `checks.failing`, then follow
  `ci-troubleshooting.md` to get the logs. Fix, run the tests locally, commit,
  push, and check again.
- `checks.state` none: the repository has no CI for this commit, or it has not
  started yet. Say so.

Stop after three fix attempts on the same failure and report to the user what
you found. Before you treat a failure as yours, check whether the default
branch fails the same way: pre-existing and infrastructure failures are not
fixed by changing your diff.

## 8. Address review comments

Push more commits to the same branch; the pull request updates itself. Reply to
each comment saying what changed. Rebase or squash only when the repository
asks for it, and then push with `--force-with-lease`.

## 9. Merge (only when the user asks)

Merging is the user's decision. When asked, check `GITFLOW pr status` first
(`checks.state` success, `mergeable` true, required approvals present), then:

~~~bash
# with gh
cd /mnt/user-data/workspace/myrepo && gh pr merge 42 --squash --delete-branch
# without gh: the REST API; the token stays in the environment variable
curl -sS -X PUT -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/OWNER/REPO/pulls/42/merge -d '{"merge_method": "squash"}'
~~~

Then confirm with `GITFLOW pr status --number 42` that `merged` is true before
telling the user it is merged.

## Parallel work with worktrees

When several subagents work on one repository at the same time, give each its
own checkout with `GITFLOW worktree add NAME` and pass the returned `path` in
the `task` prompt. Each subagent commits on its branch agent/NAME (and pushes it
if the plan calls for one pull request per subagent). The lead then either opens
a pull request per branch or merges the branches into one feature branch in the
main checkout and runs the full test suite there. Remove each worktree with
`GITFLOW worktree remove NAME` once its work is integrated.

## Other pull request operations

gitflow.sh covers the steps where mistakes are costly. For everything else use
`gh` when it is available, or the REST API with curl, keeping the token in the
environment variable. For a JSON payload with free text, write it with
`write_file` and send it with `--data @file`, which avoids shell quoting.

| Action | gh | REST |
| --- | --- | --- |
| Comment | `gh pr comment N --body-file FILE` | POST to the issue comments endpoint of N |
| Request review | `gh pr edit N --add-reviewer USER` | POST to the requested reviewers endpoint of N |
| Add labels | `gh pr edit N --add-label LABEL` | POST to the issue labels endpoint of N |
| Close | `gh pr close N` | PATCH the pull request with state closed |
| Check out someone's pull request | `gh pr checkout N` | fetch the pull request head, then add a worktree (below) |
| View the diff | `gh pr diff N` | a three-dot git diff against the base (below) |

~~~bash
cd /mnt/user-data/workspace/myrepo && git fetch origin pull/42/head:pr-42 && GITFLOW worktree add review-42 --from pr-42
cd /mnt/user-data/workspace/myrepo && git diff --stat origin/main...HEAD
~~~

Never print the token (`echo`, `env`, `set -x`) and never put it in a URL.
