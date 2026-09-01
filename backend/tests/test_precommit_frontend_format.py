"""The local prettier gate must cover everything the CI job checks.

CI's `lint-frontend` job runs `cd frontend && pnpm format`, which is
`prettier --check .` over the **whole** of `frontend/` — every file type
prettier has a parser for, minus `.prettierignore`. The pre-commit hook is
supposed to be the local half of that pair, and for a while it was not: it
carried a `types_or: [javascript, tsx, ts, json, css]` allowlist, so a Markdown
file under `frontend/` — `frontend/AGENTS.md`, `frontend/CLAUDE.md`, and above
all `frontend/src/AGENTS.md`, the module guide every docs change touches — was
formatted by CI and by nothing locally.

That is the same shape of trap as `test_editing_guidance_is_gated_locally_before_ci_sees_it`
in `test_agent_guidance_check.py`, and it failed the same way: the checks were
run, then the documentation was edited, and `prettier --check` rejected an
italic written as `*and*` instead of `_and_` in a file the author did not think
of as "code". A test cannot catch that (the format command was green when it
ran); only a hook that fires on the commit can.

Two things were changed to close it, and this module pins both.

* `pnpm check` — the command every guide tells you to run before committing —
  now starts with `prettier --check .`. It used to be eslint + `tsc` only, so the
  documented gate was not the gate CI applies.
* The hook lost its extension allowlist in favour of `--ignore-unknown`, which
  makes prettier itself decide what it can format — the one definition that
  cannot drift away from CI's.

What is pinned here is therefore *coverage*, not a file list: an allowlist that
comes back, or a `check` script that loses its first command, is a test failure
rather than a surprise in CI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _prettier_hook() -> dict:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [hook for repo in config["repos"] for hook in repo.get("hooks", [])]
    hook = next((hook for hook in hooks if hook.get("id") == "frontend-prettier"), None)
    assert hook is not None, "the frontend-prettier pre-commit hook is gone; formatting is CI's problem again"
    return hook


def test_prettier_hook_formats_every_file_type_ci_checks() -> None:
    hook = _prettier_hook()

    assert "prettier" in hook["entry"]
    assert "--write" in hook["entry"], "the hook must fix the file, not merely report it"
    # The load-bearing flag: with no type allowlist, pre-commit hands prettier
    # every staged frontend file including images and lockfiles, and this is what
    # makes that safe. Drop it and the hook fails on a PNG; add an allowlist back
    # to avoid that and the Markdown gap returns.
    assert "--ignore-unknown" in hook["entry"], "without --ignore-unknown the hook needs a type allowlist, which is what drifted from CI"
    assert "types" not in hook and "types_or" not in hook, "an extension allowlist is a second definition of 'what prettier formats' that has to be kept equal to CI's by memory; it already drifted once, and the drift is silent locally"


def test_prettier_hook_fires_on_the_markdown_that_broke_it() -> None:
    pattern = _prettier_hook()["files"]

    # The regression itself, plus the module guide and the sibling files that
    # sit in the same directory and are equally invisible to a type allowlist.
    assert re.search(pattern, "frontend/src/AGENTS.md")
    assert re.search(pattern, "frontend/AGENTS.md")
    assert re.search(pattern, "frontend/CLAUDE.md")
    assert re.search(pattern, "frontend/src/core/threads/image-generation.ts")
    # Root-level Markdown is outside the CI job's scope, so it must stay outside
    # the hook's too — a hook that reformatted FORK.md would be inventing a rule
    # nothing else enforces.
    assert not re.search(pattern, "FORK.md")
    assert not re.search(pattern, "backend/AGENTS.md")


def test_the_ci_half_of_the_pair_still_exists() -> None:
    """The hook is only worth pinning while CI is what it mirrors."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "lint-check.yml").read_text(encoding="utf-8")
    package_json = (REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")

    assert "lint-frontend:" in workflow
    assert "pnpm format" in workflow
    # `prettier --check .` — the directory argument is the whole point: it is why
    # Markdown is checked at all, and why narrowing the hook by extension leaves
    # a hole rather than an equivalent check.
    assert '"format": "prettier --check ."' in package_json


def test_the_documented_pre_commit_command_runs_the_format_check() -> None:
    """`pnpm check` must gate on formatting, because that is what the guides name.

    `AGENTS.md`, `frontend/AGENTS.md` and `frontend/README.md` all point at
    `pnpm check` as the thing to run before committing. While that script was
    eslint + `tsc` only, following those instructions to the letter still left
    formatting to CI — the gap this test exists to keep closed.
    """
    package_json = json.loads((REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    check = package_json["scripts"]["check"]

    assert "prettier --check" in check, "pnpm check no longer gates on formatting; the documented pre-commit command is not CI's again"
    assert "eslint" in check
    assert "tsc --noEmit" in check
    # Prettier first, matching the CI job's step order, so the two report the
    # same failure first rather than disagreeing about which one to fix.
    assert check.index("prettier") < check.index("eslint")


def test_the_guides_still_point_at_that_command() -> None:
    """The mechanism above is only the fix while the guides still name it."""
    for relative in ("AGENTS.md", "frontend/AGENTS.md"):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "pnpm check" in text, relative
