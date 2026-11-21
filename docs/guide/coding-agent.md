# Coding Agent: Gates, Learned Skills and Git

DeerFlow edits code in its sandbox with `read_file`, `write_file`,
`str_replace`, `grep`, `glob` and `bash`. This page covers what the fork adds
on top so the agent catches its own mistakes, gets better at your recurring
work, and hands changes over through git reliably. The reasoning and the
properties a refactor must keep are in [FORK.md §55](../../FORK.md#55-a-coding-agent-that-checks-its-work-learns-skills-and-ships-through-git).

## Gates on every edit

On by default; nothing to configure.

- **An ambiguous edit is refused.** `str_replace` with `replace_all` off
  requires `old_str` to match exactly one place. When it matches several, the
  call fails with the count and the first lines it matched, and the file is
  left untouched; widen `old_str` or set `replace_all`. It used to change the
  first copy and report `OK`.
- **A write that breaks a file says so.** After a successful `write_file` or
  `str_replace` on a `.py`, `.pyi`, `.json`, `.yaml`/`.yml` or `.toml` file,
  the result carries a warning with the line of the first syntax error (for
  an edit, only when the file parsed before it). The write still happens (a
  file written in parts is broken in between). Parsing never executes the
  content. JSON with comments (`tsconfig.json`), templated YAML (Helm, Jinja)
  and files with a byte-order mark are accepted, so a correct file never gets
  a false warning. To *block* an edit that breaks a previously valid file
  instead, set `harness_guard.write_verify_syntax: true`; it uses the same
  parsers.

## Verify before finishing

`harness_guard.verify_before_finish` (default `true`). When a run edited a
source file and ran no `bash` command after its last edit, the run does not
end at the agent's first final answer: that answer stays visible, and one more
model call follows with a hidden reminder — run the tests, the linter or the
program, or say why you could not — so the second answer reports the result.
It fires at most once per run, never after a spend, token or loop cap, never
while a to-do list is open, and only when the agent has `bash`. Docs, data and
config edits do not count as code. Cost: at most one extra model call in a run
that edited code and never ran it.

## Skills the agent learns, uses and retires

Off by default, because each skill write runs a security-scan model call.
Switch it on in `config.yaml`:

```yaml
skill_evolution:
  enabled: true
  nudge_after_tool_calls: 8      # 0 = no end-of-run reminder
  archive_unused_after_days: 90  # 0 = never switch skills off
```

With it on, the loop closes like this:

1. **Learn.** The agent has the `skill_manage` tool (create, patch, edit,
   delete, supporting files). When a run took `nudge_after_tool_calls` or more
   tool calls and never called it, the end-of-run review reminds the agent once
   to save the procedure it worked out — patching an existing skill rather
   than adding a near-duplicate, and asking you before it creates a new one.
2. **Use.** Your custom skills are listed in every system prompt; the agent
   loads one with `read_file`, or you name it with `/skill-name`.
3. **Improve.** When a run loaded one of your custom skills, the same review
   asks the agent to patch it now if it was wrong, incomplete or out of date.
4. **Count.** Every load is recorded in
   `{DEER_FLOW_HOME}/users/<user>/skills/custom/.learning/ledger.json` (use
   count, first and last use).
5. **Retire.** Once a day at most, the curator switches off skills **the agent
   wrote** that nobody loaded for `archive_unused_after_days`. Skills you wrote
   or installed are never touched. Switching off is the same toggle as
   **Settings → Skills**: turn it back on there and the curator leaves it
   alone from then on. Nothing is deleted, and every agent write stays in the
   skill's history (`.history/<name>.jsonl`), which the Skills page can roll
   back.

## Coding skills from day one

Bundled under `skills/public/`, enabled by default, and updated by every
`git pull`. The first six are adapted from
[Hermes Agent](https://github.com/NousResearch/hermes-agent) (MIT; several
originally from obra/superpowers) and `git-pr-workflow` adapts parts of its
GitHub skill; each of those seven carries its `LICENSE.txt`. `repo-change-cycle`
is DeerFlow's own.

| Skill | Use it when |
| --- | --- |
| `systematic-debugging` | A bug, failing test or crash: root cause before any fix |
| `test-driven-development` | New or changed behavior that should be test-backed |
| `requesting-code-review` | Before committing: security scan, tests, an independent reviewer |
| `simplify-code` | Cleaning up recent changes (parallel reviewers in Ultra mode) |
| `spike` | Trying an idea out before building it |
| `subagent-driven-development` | Executing a multi-task plan with subagents (Ultra mode) |
| `git-pr-workflow` | Branching, committing, pushing and opening a PR from the sandbox |
| `repo-change-cycle` | Setting up a repository with a feature map and a change cycle |

Turn any of them off in **Capability Center → Skills**.

### Git and pull requests

`git-pr-workflow` ships `scripts/gitflow.sh`, which the agent runs with
`bash`. Every subcommand prints JSON and fails loudly:

- `preflight` — branch, default branch, dirty files, ahead/behind, whether
  `gh` and a GitHub token are available.
- `branch NAME` — a fresh branch from the up-to-date default branch.
- `checkpoint` / `restore` — snapshot the working tree (untracked files too)
  without touching your index or history, and roll back to it.
- `commit` — stages only what you name, refuses the default branch, empty
  commits and anything that looks like a secret in the staged diff.
- `push` — retries network failures and then reads the remote ref back.
- `pr create` / `pr status` — through the GitHub API with the sandbox's
  GitHub token (or `gh`'s login when that is all there is), never twice for one
  branch, and read back before it reports a URL.
- `worktree add NAME` — a separate checkout per parallel subagent.

Private repositories authenticate through the GitHub token the sandbox
already receives ([Private GitHub repositories](../../README.md#private-github-repositories)).

### Repositories with a map and a change cycle

`repo-change-cycle` carries the setup brief this repository itself follows:
`docs/repo-map.md` (what the app does, feature by feature, and the files,
data and services each feature uses), `change_cycle.md` (test a change at
level 1, 2 or 3, keep the map current, open a PR and merge it) and
`docs/quality-exceptions.md`. Ask the agent to set up a new project "with a
repo map and change cycle", or point it at an existing one. DeerFlow's own
[change_cycle.md](../../change_cycle.md) and [repo map](../repo-map/index.md)
are the worked example.
