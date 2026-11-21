---
name: repo-change-cycle
description: Use this skill when creating or setting up a code repository, or when the user asks for a repo map, a change cycle, a change_cycle.md, or a feature-by-feature map of an existing codebase. Sets up docs/repo-map.md, change_cycle.md, docs/quality-exceptions.md and one test per feature.
---

# Repo map and change cycle

Sets a repository up so any developer or agent can change it safely: a map of
what the app does feature by feature (and which files, data and services each
feature uses), and a `change_cycle.md` routine that tests a change, keeps the
map current, opens a pull request and merges it, at one of three levels.

The full specification is `references/setup-brief.md`. Read it completely with
`read_file` before starting; it is the contract, and this page only routes.

## When to use

- You are creating a new repository for the user, or bootstrapping a project
  in the workspace that will keep changing.
- The user asks for a repo map, a feature map, a change cycle, or
  "set this repo up like the brief".
- An existing repository has `change_cycle.md`: follow it for every change
  ("run change_cycle.md level 1") instead of improvising a procedure.

## Procedure

1. Read `references/setup-brief.md`.
2. Inventory the repository with `glob` and `grep`: entry points (pages,
   routes, CLI commands), external services, data stores, and existing tests.
   Name features the way the project and its users already name them.
3. Write `docs/repo-map.md` in this order: title, sync line, Mermaid board,
   feature entries, file → features index (brief section 1). Past ~500 lines,
   split into `docs/repo-map/index.md` plus one file per area.
4. Give every feature at least one automated test of its main path. Tests mock
   paid or rate-limited services and need no committed secrets (section 2).
5. Copy the `change_cycle.md` template from section 3 to the repository root
   and replace every `<...>` with commands you ran and saw work.
6. Create `docs/quality-exceptions.md` (it may start empty), and add one line
   pointing to the map and `change_cycle.md` in the repo's agent instructions
   file (`AGENTS.md`, `CLAUDE.md`) if it has one.
7. Put the setup itself through a pull request; merging it is the first sync
   point. Then check the brief's "Done when" list item by item.

## Pitfalls

- A map by function or by file instead of by feature is not this map: one
  entry per thing a user can do.
- Every file that runs or ships belongs in the index, including config, styles
  and migrations; lockfiles and the app shell are `ALL`.
- A command in `change_cycle.md` that was never run is a broken promise to the
  next agent. Paste only commands you executed in this repository.
- Generic best-practice text goes under References as a link, never copied in.

## Worked example

DeerFlow's own repository is set up this way: its `change_cycle.md`, its
`docs/repo-map/` (split by area) and its `docs/quality-exceptions.md` follow
the brief, with repository-specific additions (critical checks, a model audit
that runs only when asked).
