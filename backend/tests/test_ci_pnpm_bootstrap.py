"""CI's pnpm bootstrap: pinned to one version, and resilient to the download.

Every frontend job starts by having corepack fetch the pinned pnpm from the npm
registry. That step is a network download in the critical path of four
workflows, and when it fails it fails *badly*: a transient abort mid-download
crashes Node's bundled undici parser with

    AssertionError [ERR_ASSERTION]: The expression evaluated to a falsy value:
      assert(!this.paused)
        at Parser.finish (node:internal/deps/undici/undici)

which is not recognisable as a network error at all. The job dies before a
single test runs, the red tick reads like a Node bug or a broken branch, and
the natural response is to go looking through a diff that has nothing to do
with it. Observed on PR #106: `frontend-unit-tests` died this way while
`lint-frontend` downloaded the same tarball successfully in the same run, and
the immediately preceding commit on the same branch had passed.

Retrying is safe because nothing else in that step can fail — it does no
building, reads no repository file, and touches no test — so a retry can only
ever be recovering the download.

The version is pinned in five places (``frontend/package.json``'s
``packageManager`` plus one ``corepack prepare`` per workflow). A version drifts
out of exactly one place at a time, and the failure mode of a mismatch is a CI
job silently exercising a different pnpm than contributors run, so the pin is
asserted here too rather than trusted.

Run from ``backend/``:
    uv run pytest tests/test_ci_pnpm_bootstrap.py -q
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
FRONTEND_PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"

_COREPACK_PREPARE = re.compile(r"corepack\s+prepare\s+pnpm@(?P<version>\d+\.\d+\.\d+)\s+--activate")


def _pinned_pnpm_version() -> str:
    """The single source of truth: what contributors' own pnpm resolves to."""
    package_json = json.loads(FRONTEND_PACKAGE_JSON.read_text(encoding="utf-8"))
    package_manager = package_json.get("packageManager", "")
    assert package_manager.startswith("pnpm@"), f"{FRONTEND_PACKAGE_JSON} no longer pins a pnpm version in `packageManager`"
    return package_manager.split("@", 1)[1]


def _prepare_steps() -> list[tuple[str, str, dict]]:
    """``(workflow file, step name, step mapping)`` for every corepack prepare."""
    steps: list[tuple[str, str, dict]] = []
    for path in sorted(p for p in WORKFLOWS_DIR.iterdir() if p.suffix in {".yml", ".yaml"}):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job in (workflow.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                if isinstance(step, dict) and _COREPACK_PREPARE.search(str(step.get("run") or "")):
                    steps.append((path.name, str(step.get("name") or "<unnamed>"), step))
    return steps


def test_there_is_a_pnpm_bootstrap_to_check():
    # Guards the two tests below against silently passing on an empty list —
    # a renamed step or a restructured workflow would otherwise look green.
    assert _prepare_steps(), "no workflow runs `corepack prepare pnpm@... --activate` any more; if the bootstrap moved, move these assertions with it"


@pytest.mark.parametrize("workflow, step_name, step", _prepare_steps(), ids=lambda value: value if isinstance(value, str) else "")
def test_the_pnpm_download_is_retried(workflow: str, step_name: str, step: dict):
    """A one-shot download here turns a network hiccup into a red branch.

    Asserted on the *shape* of the step rather than its exact text so the retry
    can be rewritten, but not removed: it has to loop, and it has to re-run the
    prepare inside that loop.
    """
    run = str(step.get("run") or "")
    assert "for attempt in" in run, f"{workflow} :: {step_name} runs `corepack prepare` without a retry loop; a transient npm-registry abort will fail the job before any test runs"
    assert run.count("corepack prepare") >= 1 and "sleep" in run, f"{workflow} :: {step_name} has a loop but does not back off between attempts"


def test_every_workflow_prepares_the_version_the_repo_pins():
    """One pnpm version, five copies. This is the one that catches the drift."""
    expected = _pinned_pnpm_version()
    mismatches = [
        f"{workflow} :: {step_name} prepares pnpm@{match.group('version')}"
        for workflow, step_name, step in _prepare_steps()
        if (match := _COREPACK_PREPARE.search(str(step.get("run") or ""))) is not None and match.group("version") != expected
    ]
    assert not mismatches, f"CI would run a different pnpm than `frontend/package.json` pins ({expected}): " + "; ".join(mismatches)
