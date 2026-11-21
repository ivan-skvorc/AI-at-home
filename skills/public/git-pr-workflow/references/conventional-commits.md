# Conventional Commits quick reference

Format: a subject line `type(scope): description`, a blank line, then an
optional body and footers. Keep the subject under 72 characters, in the
imperative mood ("add", not "added"), without a trailing period. Wrap the body
at 72 characters and explain why the change is needed, not only what changed.

Follow the repository's own convention when its history or docs show a
different one (check the recent subjects with `git log --oneline -20`).

## Types

| Type | When to use | Example |
| --- | --- | --- |
| `feat` | New feature or capability | feat(auth): add OAuth2 login flow |
| `fix` | Bug fix | fix(api): handle a null response from the users endpoint |
| `refactor` | Restructuring without behavior change | refactor(db): extract the query builder into its own module |
| `docs` | Documentation only | docs: update the API usage examples in the README |
| `test` | Adding or updating tests | test(auth): add integration tests for token refresh |
| `ci` | CI configuration | ci: add Python 3.12 to the test matrix |
| `chore` | Maintenance, dependencies, tooling | chore: upgrade pytest |
| `perf` | Performance improvement | perf(search): add an index on users.email |
| `style` | Formatting only | style: run the formatter on the source tree |
| `build` | Build system or external dependencies | build: switch from setuptools to hatch |
| `revert` | Reverts an earlier commit | revert: feat(auth): add OAuth2 login flow |

## Scope

An optional short name for the area of the codebase: auth, api, db, ui, cli.

## Breaking changes

Add `!` after the type or scope, or a `BREAKING CHANGE:` footer that explains
the migration:

~~~text
feat(api)!: require bearer authentication

BREAKING CHANGE: endpoints no longer accept the API key header; clients
must send a bearer header instead.
~~~

## Body and footers

~~~text
feat(auth): add JWT-based user authentication

- Add login and register endpoints with input validation
- Hash passwords with argon2
- Rotate refresh tokens on use

Closes #42
Co-authored-by: Name <name@example.com>
~~~

`Closes #42` or `Fixes #42` closes the issue when the commit reaches the default
branch; `Refs #42` links without closing.

## Choosing the type

- Added something new: `feat`.
- Something was broken and now works: `fix`.
- Changed how code is organized but not what it does: `refactor`.
- Only touched tests: `test`. Only touched docs: `docs`.
- Changed CI pipelines: `ci`. Updated dependencies or tooling: `chore`.
- Made something faster: `perf`.

Pass the message to `gitflow.sh commit` with `--message-file -` and a quoted
heredoc, so backquotes and dollar signs in it reach git unchanged.
