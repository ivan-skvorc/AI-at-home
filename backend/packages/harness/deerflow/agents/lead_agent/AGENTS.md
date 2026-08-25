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
