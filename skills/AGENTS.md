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
- **A skill that drives a script repeats its contract in prose, so a test ties
  the two.** `cad-modeling` drives `scripts/cadkit.py` in the CAD sandbox image
  (`docker/sandbox-cad/`), never in the Gateway.
  `tests/skills/test_cad_modeling.py` ties the commands, flags and messages its
  pages quote to cadkit's argparse and source, and
  `backend/tests/test_sandbox_cad_image.py` ties every program and library
  cadkit uses to the image; change the three together. Skill Review CI skips
  `tests/skills/test_cadkit.py`'s end-to-end group, which needs openscad,
  trimesh and manifold3d, so run it where they are installed before changing
  cadkit; the Sandbox CAD Image workflow runs the loop inside the built image.
- **Every enabled public skill's name rides each small-window request.** The
  32K context-fit critical check (`backend/tests/test_context_fit_critical.py`)
  has a few dozen tokens of headroom in the heaviest mode; a new public skill
  may have to pay its name back elsewhere (FORK.md §55).
- **A skill adapted from another project keeps its `LICENSE.txt` and an
  `author:` credit**, as the Hermes-derived coding skills do.
