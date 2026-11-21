---
name: git-pr-workflow
description: Use this skill when a task commits, pushes, branches, or opens, updates or checks a GitHub pull request in the sandbox. gitflow.sh gives JSON-reporting primitives - work branches, checkpoints, secret-scanned commits, verified pushes, idempotent PRs, CI status, worktrees.
license: MIT
author: DeerFlow; workflow guidance adapted from Hermes Agent (Nous Research)
version: 1.0.0
compatibility: Needs bash 4.4+, git and Python 3.10+ in the sandbox (POSIX). gh is optional. Pull requests use the GitHub REST API with the GH_TOKEN or GITHUB_TOKEN that bash receives when the user connected GitHub, or with an authenticated gh's credentials.
metadata:
  tags: [git, github, pull-requests, commits, ci, code-review, worktrees]
  related-skills: [test-driven-development, systematic-debugging]
  upstream: NousResearch/hermes-agent skills/software-development/github (aeb5a071), adapted
---

# Git and Pull Request Workflow

## Overview

Agents lose work and report things that never happened when they drive git by
hand: commit messages mangled by quoting, commits on the default branch, tokens
pasted into remote URLs, a "pushed" branch that is not on the remote, a pull
request that was never opened, and parallel subagents editing one checkout. This
skill replaces those steps with one entry point, `scripts/gitflow.sh`. Every
subcommand checks its preconditions, does one thing, reads the result back from
git or GitHub, and prints a single JSON object. A failure exits non-zero with
`error` and `hint` fields, and the same text on stderr.

The bash script is the only part that starts processes (git, gh, python3). Its
Python helpers start none: `scripts/gitflow_json.py` parses git output and
formats the JSON, `scripts/gitflow_scan.py` scans the staged diff for secrets,
and `scripts/gitflow_github.py` calls the GitHub REST API over HTTPS.

**Core rule: never claim a branch, commit, push, pull request, CI result or
merge that you have not read back with gitflow.sh in this turn.** Quote the
`sha`, `remote_sha`, `url`, `state` and `checks.state` fields from its output.

## Running it

The script is mounted read-only at
/mnt/skills/public/git-pr-workflow/scripts/gitflow.sh. Each `bash` call starts
fresh, so begin every command with a `cd` into the repository:

~~~bash
cd /mnt/user-data/workspace/myrepo && bash /mnt/skills/public/git-pr-workflow/scripts/gitflow.sh preflight
~~~

`--repo DIR` works instead of `cd`. Paths passed to `--paths` are relative to the
repository root. Pull-request commands call the GitHub REST API with the
`GH_TOKEN` or `GITHUB_TOKEN` variable that the sandbox `bash` tool provides once
the user has connected GitHub; when neither is set and `gh` is installed and
logged in, they use gh's credentials instead. Output never contains a token.

## Routing

| Task | Command | Read first |
| --- | --- | --- |
| Start of any git task: state, default branch, auth | `preflight` | - |
| Start work on a fresh base | `branch NAME` | `references/pr-workflow.md` |
| About to try something risky | `checkpoint -m "what"` | - |
| Undo edits | `checkpoints`, then `restore ID` | `references/gitflow-cli.md` |
| Commit | `commit --paths ... --message-file -` | `references/conventional-commits.md` |
| Push | `push` (`--force-with-lease` after a rebase) | - |
| Open a pull request | `pr create` | `references/pr-workflow.md`, `templates/pr-body-feature.md`, `templates/pr-body-bugfix.md` |
| CI, review and merge state | `pr status` | `references/ci-troubleshooting.md` |
| Parallel subagents | `worktree add`, `worktree list`, `worktree remove` | the parallel work section below |
| Carry an issue to a verified pull request | - | `references/issue-to-pr.md` |
| Review a diff or someone's pull request | - | `references/code-review.md` |
| Flags, JSON fields, exit codes, the secret rules | - | `references/gitflow-cli.md` |

## The discipline

1. **Preflight first.** Run `preflight` once per task and read `warnings`: a
   detached HEAD, a protected branch, an operation in progress, a remote URL with
   embedded credentials, or missing GitHub auth all change what you do next.
2. **Work on a branch.** `branch NAME` fetches and branches from the fresh
   remote default branch; use names like feat/short-topic or fix/issue-123
   (`references/pr-workflow.md` lists the prefixes). `commit` and `push` refuse the default branch, main and
   master; pass `--allow-default-branch` to `commit` only when the user asked for
   a commit there.
3. **Checkpoint before risky edits**: large refactors, codemods, generators,
   deleting files, rebases. `restore` brings the files back and first saves the
   current state as another checkpoint, so a restore can be undone. Use it
   instead of `git reset --hard`, `git checkout .` or `git clean`, which destroy
   work.
4. **Run the project's tests and linters before committing.** Find the commands
   in the repository's AGENTS.md, CONTRIBUTING.md, Makefile or CI workflow and run
   the relevant ones. Do not commit on a red suite unless the user agreed.
5. **Commit only what you changed.** Name the files with `--paths` (or `--all`
   after checking `preflight`). Pass multi-line messages through a quoted
   heredoc so nothing is expanded. If the secret scan refuses, remove the
   secret; never route around the scan with plain `git commit`.
6. **Push with gitflow.sh.** `push` never uses plain `--force`, retries
   transient network errors, and verifies that the remote ref equals local HEAD.
   Never put a token into a remote URL or onto a command line.
7. **Open the pull request with `pr create`.** It returns the open pull request
   for the branch instead of creating a duplicate. Give the user the `url` it
   printed.
8. **Report CI and merge state from `pr status`.** "Green" means
   `checks.state` is `success`; "merged" means `merged` is true. Anything else is
   pending or failed: say which.
9. **On failure, read `error` and `hint`.** Fix the cause instead of repeating
   the command. For authentication problems ask the user to connect GitHub;
   never ask them to paste a token into the chat.

## End-to-end example

~~~bash
cd /mnt/user-data/workspace/myrepo && bash /mnt/skills/public/git-pr-workflow/scripts/gitflow.sh preflight
cd /mnt/user-data/workspace/myrepo && bash /mnt/skills/public/git-pr-workflow/scripts/gitflow.sh branch fix/empty-payload
cd /mnt/user-data/workspace/myrepo && bash /mnt/skills/public/git-pr-workflow/scripts/gitflow.sh checkpoint -m "before payload refactor"
# ... edit with str_replace or write_file, run the project's tests with bash ...
cd /mnt/user-data/workspace/myrepo && bash /mnt/skills/public/git-pr-workflow/scripts/gitflow.sh commit \
  --paths src/api.py tests/test_api.py --message-file - <<'EOF'
fix(api): return 400 for an empty payload

The handler indexed into the body before checking it, so an empty
request crashed with a 500.
EOF
cd /mnt/user-data/workspace/myrepo && bash /mnt/skills/public/git-pr-workflow/scripts/gitflow.sh push
~~~

Write the pull request body with `write_file` outside the repository, starting
from `templates/pr-body-feature.md` or `templates/pr-body-bugfix.md` (for example
to /mnt/user-data/workspace/pr-body.md), then open the pull request and read its
state back:

~~~bash
cd /mnt/user-data/workspace/myrepo && bash /mnt/skills/public/git-pr-workflow/scripts/gitflow.sh pr create \
  --title "fix(api): return 400 for an empty payload" --body-file /mnt/user-data/workspace/pr-body.md
cd /mnt/user-data/workspace/myrepo && bash /mnt/skills/public/git-pr-workflow/scripts/gitflow.sh pr status
~~~

## Parallel subagents

Subagents started with `task` share the thread's workspace, so two of them
editing one checkout overwrite each other's files and index. Give each one its
own worktree:

1. The lead runs `worktree add NAME` once per subagent. Each gets a checkout in
   the repository's .worktrees directory, on branch agent/NAME, branched from the
   fresh default branch; the directory is added to the repository's
   info/exclude file so it never shows up as untracked.
2. The `task` prompt names the absolute `path` from the JSON output and tells the
   subagent to run every command as a `cd` into that path, to commit there, and to
   report the commit `sha` it got back.
3. The lead integrates the branches (merge, cherry-pick, or one pull request per
   branch), then runs `worktree remove NAME`. A worktree with uncommitted
   changes is refused unless `--force`, which checkpoints the changes first.

## Pitfalls

- A `bash` call does not keep `cd` or variables from the previous call.
- `git stash` hides work from `preflight` and from other agents; prefer
  `checkpoint`, which leaves the working tree as it is.
- Checkpoints live under the refs namespace deerflow-checkpoints; a normal push
  does not send them, and ignored files (build output, local env files) are not
  included.
- A pull request body that says tests pass must match tests you actually ran.
- `pr status` can report `mergeable` as null right after a push while GitHub is
  still computing it; run it again rather than guessing.
