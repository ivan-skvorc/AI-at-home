# Lead agent — fork reference notes

Reference material for the fork's lead-agent features, moved out of this
directory's `AGENTS.md` so it is not inherited by every guide below it. Read it
before changing `prompt.py` or `system_prompt_store.py`.

## Editable system prompt (fork, FORK.md §19)

`prompt.py` + `system_prompt_store.py`.

- `apply_prompt_template()` renders whatever `get_system_prompt_template()` returns: a
  user-authored override at `{base_dir}/SYSTEM_PROMPT.md` when one is saved (see
  `lead_agent/system_prompt_store.py`), otherwise the built-in
  `SYSTEM_PROMPT_TEMPLATE`. It is read on every agent build, so an edit saved from
  **Settings → System prompt** applies from the next run with no Gateway restart.
  Fork feature; full rationale in [FORK.md](../../../../../../FORK.md) (§19).
- **The allowed placeholder set is derived, never duplicated.**
  `SYSTEM_PROMPT_PLACEHOLDERS = extract_placeholders(SYSTEM_PROMPT_TEMPLATE)`. Adding a
  `{new_section}` to the template automatically permits it in an override and lists it in
  the Settings editor — do not introduce a second hardcoded list, which would rot silently.
- **An override may change a run, never break one.** Validation runs on save *and* again
  on every read, and `apply_prompt_template` still wraps its `.format()` call. A file
  hand-edited on disk, restored from an old backup, or written against a placeholder this
  version no longer supplies falls back to the built-in template with a warning instead of
  raising inside the agent build.
- **Saving proves renderability.** Checking field names is not enough: `{agent_name:{width}}`
  parses to an allowed field yet still raises `KeyError` on the inner `width`. Validation
  renders the template once against placeholder values, so a save cannot succeed and then
  silently fall back on every run.
- **Tests must pass `app_config` when rendering.** `apply_prompt_template(app_config=None)`
  falls back to loading the repo-root `config.yaml`, which is gitignored — a render test
  that omits it passes on a machine that has run `make config` and fails in CI with
  `FileNotFoundError`. Pinned by `tests/test_system_prompt_store.py::TestConfigIndependence`.
