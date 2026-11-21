# Code review

Review local changes before pushing, or review someone else's pull request.
Most of it is plain git; only posting the review needs GitHub access.

## Reviewing local changes before a push

~~~bash
cd /mnt/user-data/workspace/myrepo && git fetch origin && git diff --stat origin/main...HEAD
cd /mnt/user-data/workspace/myrepo && git log --oneline origin/main..HEAD
cd /mnt/user-data/workspace/myrepo && git diff origin/main...HEAD -- src/auth/login.py
~~~

Use the default branch from `gitflow.py preflight` in place of main. Then:

1. Read the summary first (files and sizes), then the diff file by file. Use
   `read_file` on each changed file for context: a diff hides what surrounds it.
2. Search the diff for leftovers: debug prints, TODO or FIXME, merge conflict
   markers, commented-out code, large files that were staged by accident.
3. Apply the checklist below and present the findings in the format below.
4. If you find a critical issue in your own change, fix it before pushing.

`gitflow.py commit` already refuses staged secrets, but review for logic that
leaks them too (logging a request with its headers, for example).

## Reviewing someone's pull request

1. Read the pull request: title, body, linked issue, and the discussion.
   With gh: `gh pr view N --comments` and `gh pr diff N --name-only`. Without gh,
   the REST API pull request and files endpoints return the same.
2. Check it out in its own worktree so your main checkout stays untouched:

~~~bash
cd /mnt/user-data/workspace/myrepo && git fetch origin pull/42/head:pr-42
cd /mnt/user-data/workspace/myrepo && python3 /mnt/skills/public/git-pr-workflow/scripts/gitflow.py worktree add review-42 --from pr-42
~~~

3. Read the diff against the base and the changed files in full, run the tests
   and linters in the worktree, and check the CI state with
   `gitflow.py pr status --number 42`.
4. Apply the checklist, write the review, then remove the worktree with
   `gitflow.py worktree remove review-42 --force`.

## Checklist

- **Correctness**: does the code do what the pull request claims? Edge cases
  (empty input, nulls, large data, concurrency)? Error paths?
- **Security**: no hard-coded credentials; input validation at trust
  boundaries; no injection (SQL, shell, path traversal, XSS); authorization
  checks where needed.
- **Tests**: are the new paths tested, including failures? Would the tests fail
  without the change?
- **Design and quality**: clear names, no needless complexity or duplication,
  focused functions, consistent with the surrounding code.
- **Performance**: no N+1 queries, no blocking calls on async paths, no
  unbounded growth.
- **Documentation**: public behavior documented; comments explain why.

## Output format

~~~text
## Code review summary

Verdict: Changes requested (2 issues, 1 suggestion)

### Critical
- src/auth.py:45 - user input reaches the SQL query unescaped; use parameters.

### Warnings
- src/models/user.py:23 - password stored without hashing.

### Suggestions
- src/utils/helpers.py:8 - duplicates core/utils.py:34; consolidate.

### Looks good
- Clear separation between the middleware and the handlers.
~~~

Verdict: approve when there are only minor suggestions; request changes for
any critical or warning-level issue; comment when unsure or for a draft.

## Posting the review

Write the review body with `write_file`, then post it.

With gh:

~~~bash
cd /mnt/user-data/workspace/myrepo && gh pr review 42 --request-changes --body-file /mnt/user-data/workspace/review.md
~~~

Without gh, build the payload as a JSON file with `write_file` (the commit id is
the pull request's `head_sha` from `gitflow.py pr status`; `line` is the line in
the new version of the file):

~~~json
{
  "commit_id": "HEAD_SHA",
  "event": "REQUEST_CHANGES",
  "body": "Found 2 issues, see the inline comments.",
  "comments": [
    {"path": "src/auth.py", "line": 45, "side": "RIGHT", "body": "Use query parameters here."}
  ]
}
~~~

~~~bash
curl -sS -X POST -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/OWNER/REPO/pulls/42/reviews --data @/mnt/user-data/workspace/review.json
~~~

Event values: APPROVE, REQUEST_CHANGES, COMMENT. Post a review only when the
user asked you to; otherwise give them the review text.
