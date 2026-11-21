# CI troubleshooting

Start from `gitflow.py pr status`: `checks.failing` names each failed check
with its URL. Never report CI as green unless `checks.state` is `success` for
the commit you pushed (`head_matches_local` true).

## Getting the logs

With gh:

~~~bash
cd /mnt/user-data/workspace/myrepo && gh run list --branch "$(git branch --show-current)" --limit 5
cd /mnt/user-data/workspace/myrepo && gh run view RUN_ID --log-failed > /mnt/user-data/workspace/ci-failed.log
~~~

Without gh, use the REST API. The token stays in the environment variable; do
not echo it. List the workflow runs for the branch, then the jobs of the failed
run, then download one job's log as plain text:

~~~bash
curl -sS -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/OWNER/REPO/actions/runs?branch=BRANCH&per_page=5" > /mnt/user-data/workspace/runs.json
curl -sS -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/OWNER/REPO/actions/runs/RUN_ID/jobs" > /mnt/user-data/workspace/jobs.json
curl -sSL -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/OWNER/REPO/actions/jobs/JOB_ID/logs" > /mnt/user-data/workspace/job.log
~~~

Read the JSON with `read_file`, and search the log with `grep` for `FAILED`,
`Error`, `error:` and `Traceback` before reading the surrounding lines.

## Common failure patterns

**Test failures.** Signatures: `FAILED` lines naming a test, `AssertionError`,
`ModuleNotFoundError`. Read the failing test and the code under test. Decide
whether the code is wrong or the expectation is stale, and reproduce it
locally before changing anything (the systematic-debugging skill). A missing
module usually means a dependency that is not declared.

**Lint and format failures.** Signatures: `would reformat`, rule codes such as
E501 or F401. Run the repository's formatter and linter locally (its Makefile or
CI workflow names them) and commit the result.

**Type check failures.** Signatures: `error: Argument 1 ... has incompatible
type`, `Missing return statement`. Fix the types; use an ignore comment only as
a last resort, with a reason.

**Build and dependency failures.** Signatures: `Could not find a version that
satisfies the requirement`, `npm ERR! Could not resolve dependency`. Check the
manifest and lockfile and the toolchain version CI uses, and update the lockfile
with the project's own tool.

**Permission and authentication failures.** Signatures: `Resource not
accessible by integration`, `403`, `could not read Username`. These usually need
workflow permissions or repository secrets that only the user can change, and
pull requests from forks do not get secrets by design. Report it; do not try to
work around it.

**Timeouts.** Signatures: `The operation was canceled`, `exceeded the maximum
execution time`. Look for a hung process, an infinite loop or a slow network
call in the step that timed out.

**Container builds.** Signatures: `failed to solve`, `COPY failed: file not
found in build context`. Check the Dockerfile paths and the .dockerignore file.

## Decision tree

~~~text
CI failed
- is it also failing on the default branch?  -> pre-existing: report it, do not "fix" it in this PR
- test failure         -> reproduce locally, fix code or stale expectation
- lint or format       -> run the formatter, commit
- type error           -> fix the types
- build or dependency  -> fix the manifest or lockfile
- permission or secret -> needs the user
- timeout or flake     -> rerun once (gh run rerun RUN_ID --failed); if it repeats, investigate
~~~

## After a fix

Commit with gitflow.py, push, and run `gitflow.py pr status` again. The new
commit's checks start from `pending`. Stop after three attempts on the same
failure and report what you found.
