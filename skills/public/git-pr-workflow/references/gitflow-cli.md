# gitflow.py reference

The script is `../scripts/gitflow.py`; the GitHub REST client it uses is
`../scripts/gitflow_github.py`. Both are standard-library Python 3.10+ for POSIX.

## Conventions

- Every subcommand accepts `--repo DIR` (default: the current directory) and
  works from the repository root, so `--paths` values are relative to that root.
  Absolute paths inside the repository work too.
- Success prints one JSON object with `"ok": true` and `"command"` on stdout and
  exits 0.
- A refusal or failure prints `"ok": false`, `error`, usually `hint`, and any
  details (for example `findings` or `stderr`) on stdout, repeats the error and
  hint on stderr, and exits 1. A usage error (unknown flag, missing argument)
  exits 2 with argparse's message on stderr and no JSON.
- Output is redacted: credentials inside URLs, token-shaped strings, and the
  values of `GH_TOKEN` and `GITHUB_TOKEN` are replaced with `***`.
- Git runs with terminal prompts disabled, so it fails instead of waiting for a
  password. Local git calls time out after 120 s and network calls after 300 s.
  When a parallel git process holds a lock, the call is retried a few times.
- Protected branches are the default branch plus main and master.

## preflight

`preflight [--remote NAME]` reads facts and changes nothing.

Fields: `repo_root`, `branch` (null when detached), `detached`, `head`,
`default_branch`, `default_branch_source` (the remote HEAD, a remote or local
main or master, the unborn HEAD, init.defaultBranch, or a fallback),
`on_default_branch`, `upstream`, `ahead`, `behind`, `dirty`, `staged`,
`unstaged`, `untracked`, `conflicted` (each capped at 200 entries; `counts` has
the totals), `operation_in_progress` (rebase, merge, cherry-pick, revert, bisect
or null), `remote`, `remote_url` (redacted), `remote_url_has_credentials`,
`github_repo` (OWNER and REPO joined by a slash, or null), `github_host`,
`gh` (`installed`, `authenticated`), `token_env` (names of the token variables
that are set, never values), `token_present`, `linked_worktree`, `checkpoints`
(count) and `warnings`.

## branch

`branch NAME [--from REF] [--remote NAME]`

- Validates NAME with `git check-ref-format --branch` and refuses protected names.
- Fetches with prune (up to 3 attempts). When the remote HEAD is not recorded
  locally yet, it records it with `git remote set-head --auto`.
- An existing local branch is switched to, never reset. A branch that exists
  only on the remote becomes a local tracking branch. Otherwise a new branch is
  created from REF, or from the remote default branch, without an upstream (the
  first push sets it).
- Uncommitted changes are carried over by `git switch` and listed in
  `carried_changes`; when they conflict with the base, git refuses and nothing
  changes.

Fields: `branch`, `created`, `source`, `base`, `base_sha`, `head`, `fetched`,
`upstream`, `carried_changes`, `warnings` (for example a failed fetch, which
means the base may be stale).

## checkpoint, checkpoints, restore

`checkpoint [-m MSG]` snapshots every tracked file and every untracked file
that is not ignored. It copies the index to a temporary index file, stages
everything there, writes a tree, and commits it with the current HEAD as parent.
HEAD, the real index and the working tree are not touched. The commit is stored
as a ref in the refs namespace deerflow-checkpoints, which a normal push or fetch
does not transfer. Checkpoint refs are shared by all worktrees of the
repository. Ignored files (build output, local env files) are never included.

Fields: `id`, `ref`, `commit`, `tree`, `head`, `branch`, `message`, `files`
(count), `same_as_head`.

`checkpoints [--limit N]` lists them newest first: `count`, `checkpoints`
(`id`, `commit`, `created`, `message`, `branch`, `head`, `worktree`).

`restore ID [--paths P ...] [--clean]` accepts a full id, a unique id or commit
prefix, or `latest`. It first saves the current state as a new checkpoint
(`safety_checkpoint`), then writes the checkpoint's files over the working tree
(all of them, or those under `--paths`). The index and HEAD stay as they are, so
restored files appear as working-tree changes. Files created after the
checkpoint are left alone unless `--clean` is given; then non-ignored files that
are not in the checkpoint (within `--paths`, when given) are deleted. Ignored
files are never deleted.

Fields: `id`, `commit`, `paths`, `restored`, `restored_count`, `deleted`,
`deleted_count`, `safety_checkpoint`, `note`.

To drop a checkpoint, delete its ref with `git update-ref -d` and the `ref` value.

## commit

`commit (-m MSG [-m MSG ...] | --message-file FILE) [--paths P ... | --all] [--allow-default-branch]`

Repeated `-m` values become paragraphs. `--message-file -` reads the message
from stdin, which is the safe way to pass a multi-line message through a quoted
heredoc. Checks run in this order, and the first failure refuses the commit:

1. The message is not empty; HEAD is on a branch, and that branch is not
   protected unless `--allow-default-branch` is given.
2. No rebase, cherry-pick, revert or bisect is in progress, and there are no
   unresolved conflicts. Finishing a merge is allowed.
3. With `--paths`, nothing outside those paths is already staged (it would be
   committed too).
4. Staging: `--paths` stages changes, deletions and new files under the paths;
   `--all` stages everything; with neither, the existing index is committed.
5. Something is staged.
6. The secret scan of the staged diff finds nothing.

The commit is made with `git commit -F -` (the message travels on stdin), so
hooks and signing settings apply. If a check or the commit fails after staging,
the index is put back the way it was and the JSON says `index_restored: true`.

Secret scan rules (only lines the commit adds are scanned; renames count as
additions, so a secret moved to a new file is caught):

| Rule | Matches |
| --- | --- |
| `github-token` | classic tokens with the ghp_, gho_, ghu_, ghs_ or ghr_ prefix, and fine-grained github_pat_ tokens |
| `aws-access-key` | AKIA or ASIA followed by 16 upper-case letters or digits |
| `private-key` | a PEM, OpenSSH or PGP private key header line |
| `slack-token` | xoxa, xoxb, xoxp, xoxo, xoxs or xoxr tokens |
| `hardcoded-credential` | a name ending in api_key, secret, password, passwd, token, credential or auth, assigned (with =, :, := or =>) a quoted literal of 12 or more characters without spaces |
| `sensitive-file` | a staged file named .env or .env.something (except .example, .sample, .template, .dist and .defaults), id_rsa, id_dsa, id_ecdsa or id_ed25519, a .pem, .key, .p12 or .pfx file, .netrc or .pypirc |

The credential rule ignores obvious placeholders: values containing example,
sample, placeholder, changeme, your, dummy, fake, redacted or xxxx, values that
start with a dollar sign or contain template braces, and upper-case variable
names such as GITHUB_TOKEN. A verified fake value in a test may carry the marker
`pragma: allowlist secret` on the same line; mention it to the user. There is no
override for the file rule: if such a file must be committed (a public test
certificate, say), ask the user.

Fields: `sha`, `short_sha`, `branch`, `subject`, `files`, `shortstat`,
`files_changed`, `insertions`, `deletions`, `warnings` (for example a subject
over 72 characters). A refusal by the scan carries `findings`, each with
`file`, `line` (null for the file rule) and `rule`; the secret itself is never
printed.

## push

`push [--remote NAME] [--force-with-lease]`

- Refuses a detached HEAD, a protected branch, a branch without commits, and an
  unknown remote. Warns when the remote URL embeds credentials.
- Runs `git push --porcelain -u REMOTE` with the explicit branch refspec.
  `--force-with-lease` is scoped to that branch (plus `--force-if-includes` on
  git 2.30 and newer). Plain `--force` is never used.
- Retries transient failures (name resolution, timeouts, connection resets,
  HTTP 5xx) up to 4 times with 2, 4, 8 and 16 second waits. Authentication
  failures and rejections are not retried.
- Afterwards reads the remote ref with `git ls-remote`; if it is not local HEAD,
  the command fails even though git reported success.

Fields: `remote`, `remote_url` (redacted), `branch`, `local_sha`, `remote_sha`,
`verified`, `result` (new branch, fast-forward, forced update or up to date),
`forced`, `upstream`, `attempts`, `new_pull_request_url` (GitHub remotes only),
`warnings`.

## pr create and pr status

Both read OWNER and REPO from the remote URL (https, ssh, or the scp-like
user-at-host form; github.com or GitHub Enterprise, whose API is under
/api/v3 on the same host). Transport: `gh api` when gh is installed and
`gh auth status` succeeds for the host; otherwise the REST API over HTTPS with
`GH_TOKEN` or `GITHUB_TOKEN` (in that order) sent only in the Authorization
header. With neither, the command fails and asks for GitHub to be connected.

`pr create --title T (--body B | --body-file FILE) [--base BRANCH] [--draft] [--remote NAME]`

- Refuses a detached or protected head branch, and a head that is not on the
  remote yet (push first). Warns when the remote branch is not at local HEAD.
- Looks for an open pull request whose head is this branch. If one exists it is
  returned unchanged with `created: false`; otherwise a pull request is
  created. A lost connection during creation is followed by the same lookup
  before one retry, so a retry cannot open a duplicate.
- The result is read back from GitHub, never taken from the create response.

Fields: `created`, `via` (gh or rest), `repository`, `number`, `url`, `title`,
`state`, `draft`, `merged`, `merged_at`, `mergeable`, `mergeable_state`, `base`,
`head`, `head_sha`, `head_matches_remote`, `head_matches_local`, `warnings`.

`pr status [--number N] [--remote NAME]` finds the pull request for the current
branch (open first, then the newest in any state) unless `--number` is given.
Fields: the pull request fields above, plus `checks`, `reviews` and `notes`.

- `checks`: `sha`, `state` (none, pending, failure or success), `counts`
  (`total`, `success`, `failure`, `pending`, `other`), `failing` (`name`,
  `kind`, `outcome`, `conclusion`, `url`) and `pending` (names). Check runs and
  legacy commit statuses are both counted. Failure, timed out, cancelled, action
  required, startup failure and stale conclusions count as failures; neutral and
  skipped count as passing.
- `reviews`: `approved`, `changes_requested`, `commented`, counting each
  reviewer's latest verdict.
- `mergeable` is null while GitHub is still computing it.

Limitations: the head branch must live in the same repository as the remote
(for a pull request from a fork to its upstream, use `gh pr create` with its
repository and head options), and only GitHub-style remotes are supported.

## worktree

`worktree add NAME [--from REF] [--remote NAME]` creates a checkout in the main
repository's .worktrees directory, on branch agent/NAME. It adds the .worktrees
directory to the repository's info/exclude file, fetches, and branches from REF
or the remote default branch. An existing branch agent/NAME is checked out as
it is. Calling it again for an existing worktree returns it with
`created: false`. Fields: `name`, `path`, `branch`, `base`, `base_sha`, `head`,
`created`, `fetched`, `exclude_added`, `warnings`.

`worktree remove NAME [--force] [--delete-branch]` refuses when the worktree has
uncommitted changes, unless `--force`, which first saves them as a checkpoint
(`checkpoint` holds its id). `--delete-branch` deletes agent/NAME only when git
considers it merged; otherwise it is kept and a warning says so. Run it from the
main checkout, not from inside the worktree. Fields: `name`, `path`, `removed`,
`branch`, `branch_deleted`, `checkpoint`, `warnings`.

`worktree list` reports `main_root` and `worktrees`, each with `path`,
`branch`, `head`, `agent` (true for the .worktrees checkouts), `name`,
`detached`, `locked`, `prunable` and `dirty` (agent worktrees only).
