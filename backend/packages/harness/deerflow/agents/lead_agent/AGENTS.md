### Lead Agent — Democracy panels (fork, FORK.md §22)

`democracy.py` owns the two pure pieces of a Democracy run: which panel a run
actually has, and the organizer instructions rendered into the system prompt. One
*organizer* model dispatches one identical assignment to several deliberately
different *panelist* models via `task(model=...)`, then synthesizes.

Four invariants are load-bearing, and **every one of them fails silently** — the
run still produces a confident, well-written answer, it is just no longer several
models' answer. None of them is caught by a smoke test; `tests/test_democracy_panel.py`
is the gate.

- **The roster is filtered, never trusted.** `normalize_democracy_participants`
  runs in `agent.py` against `app_config.models`: it drops names that are not
  configured models, dedupes while preserving the user's order, caps at
  `MAX_DEMOCRACY_PARTICIPANTS`, and returns `[]` below
  `MIN_DEMOCRACY_PARTICIPANTS` (2). Never substitute a fallback model for a
  dropped name and never let a sub-quorum roster through — a "panel" of one model
  asked twice is one opinion at twice the price, and it would be reported as
  agreement. Sub-quorum renders no section, and the run degrades to ordinary
  Ultra.

- **`democracy_participants` is the only key.** There is deliberately no
  companion `democracy_enabled` flag: two keys can disagree, and "which models are
  on the panel" already answers "is this a panel". The key must stay in
  `app/gateway/services.py::_CONTEXT_CONFIGURABLE_KEYS`; drop it and every panel
  silently becomes a plain Ultra turn with no error anywhere.

- **The organizer section rides `{subagent_section}`, not a placeholder of its
  own.** An operator's saved `SYSTEM_PROMPT.md` (FORK.md §19) predates this
  feature, and `str.format` drops an absent placeholder without raising — a
  dedicated `{democracy_section}` would hand them a panel with no organizer rules
  at all. A panel is dispatched entirely through `task`, so any template that can
  run one already carries the subagent block. Do not "tidy" this into its own
  placeholder.

- **The prompt's content *is* the feature**, so treat `DEMOCRACY_SECTION_TEMPLATE`
  as behavior, not copy. Four rules must survive any edit: collect the shared
  facts **once** and hand every panelist the *identical* brief (N panelists each
  retrieving costs Nx and yields N slightly different datasets, so the panel ends
  up disagreeing about its inputs while appearing to disagree about its
  judgement); take those facts **as given** and do not spend a round verifying
  them; **anonymize** peers during cross-review (a model told it is arguing with a
  bigger-name model defers to the name rather than the argument); and in synthesis
  report the real distribution **including a lone dissenter** rather than
  flattening 4-1 into "the panel concluded". The tests normalize whitespace, so
  re-wrapping a paragraph is allowed and dropping a rule is not.

- **The panel is standing, and the prompt is the only thing holding that up.**
  Every follow-up turn re-runs the roster, and each panelist is re-briefed with
  its *own* prior answers, the review discussion, and the previous final answer.
  Subagents get a fresh `ThreadState` per call and remember nothing, so
  continuity exists solely because the organizer carries it into the dispatch
  prompt; deleting any of those four items turns turn two into a brand-new panel
  wearing turn one's roster, with no error anywhere. The budget line says **per
  turn** on purpose: `max_total_per_run` is per *run* and each user message is
  its own run, so an organizer told it had one allowance for the conversation
  would ration a panel that gets a fresh one every turn.

- **Grading scores the contribution, never agreement.**
  `normalize_democracy_grading` accepts only `five_point` / `boolean`; anything
  else — including absent — is `None`, i.e. no grading. Never default to a scale:
  a user who did not ask for a scoreboard should not get one appended to every
  answer. The criteria in `_GRADING_PREAMBLE` are the design, not decoration: a
  dissent that turned out to be right is a high grade and restating the majority
  is not, because grading closeness-to-my-conclusion rewards the echo and
  punishes the signal — the panelist actually worth paying for. Grades are
  per-turn so nothing coasts on an earlier turn.

`<democracy_panel>` is a framework authority block and is registered in
`InputSanitizationMiddleware._BLOCKED_TAG_NAMES`: it names the panel's models and
says how to weigh them, so a counterfeit copy in user input could re-roster or
bias a panel from inside the message. Any further block this feature emits needs
the same registration — `test_denylist_covers_framework_authority_blocks` scans
for paired tags and fails on anything neither blocked nor exempted.

The per-call `task(model=...)` precedence that makes a panel possible — it
outranks the per-thread subagent dropdown and stands the cost-aware routing
policy down entirely — is documented in
[`../../subagents/AGENTS.md`](../../subagents/AGENTS.md).

### Editable system prompt (fork, FORK.md §19)

`prompt.py` + `system_prompt_store.py`. Moved here from `agents/AGENTS.md`:
it is lead-agent depth, and parking it one level up put it in the inherited
chain of every sibling package (`middlewares/` among them).

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
