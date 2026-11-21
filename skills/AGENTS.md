# Skills (`skills/`)

`public/` holds committed skills and `custom/` holds local, gitignored skills.
Tests for public skill scripts are in `tests/skills/` at the repository root and
run in Skill Review CI, independent of package review.

- **`public/skill-reviewer/` is the built-in read-only reviewer.** Its contracts
  are in `contracts/skill_review/`. Review data that the model sees is
  tag-neutralized, and raw payloads stay in tool artifacts.
- **CI waivers are in `.github/skill-review-waivers.v1.json`.** Only the
  manifest from the trusted base revision can suppress a run, and a blocker
  finding cannot be waived.
- **Read `SKILL.md` as `utf-8-sig` and write text resources as `utf-8`.** The
  platform locale is not reliable, and a leading BOM would become part of the
  content.
- **Skill script tests run offline.** Test a dependency fallback with the
  optional import unavailable, and mock the HTTP transport.
- **A skill CLI exits non-zero on failure**, with diagnostics on stderr and
  result URLs on stdout.
- **A skill that drives an extension's tool repeats that tool's contract in
  prose, so a test ties the two.** `cad-modeling` quotes the arguments, limits
  and messages of `cad_build`, and its operations page is generated from the
  module's allow-list. `tests/skills/test_cad_modeling.py` reads both sides;
  reword a quoted message in the module and on the page together.
- **Every enabled public skill's name rides each small-window request.** The
  32K context-fit critical check (`backend/tests/test_context_fit_critical.py`)
  has a few dozen tokens of headroom in the heaviest mode; a new public skill
  may have to pay its name back elsewhere (FORK.md §55).
- **A skill adapted from another project keeps its `LICENSE.txt` and an
  `author:` credit**, as the Hermes-derived coding skills do.
