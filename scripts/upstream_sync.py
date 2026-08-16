#!/usr/bin/env python3
"""Build the PR body for an automated upstream sync (fork feature).

"Lags upstream" is a real reason to choose upstream over this fork, and it
compounds: the longer a sync is deferred, the larger the merge and the more
likely the fork's UI wiring silently breaks. `.github/workflows/upstream-sync.yml`
turns that chore into a standing PR; this module owns the part worth testing.

The PR body is generated **from FORK.md's own post-sync checklist** rather than
copied into the workflow. A copy would be correct exactly once: every feature
added to the fork after that would be missing from the list that is supposed to
prove the fork still works.

Usage:
    python3 scripts/upstream_sync.py --upstream-sha <sha> --commit-count 12 \
        --gates gates.json --conflicts conflicts.txt --output body.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FORK_MD = REPO_ROOT / "FORK.md"

CHECKLIST_HEADING_RE = re.compile(r"^###\s+Post-sync feature checklist\s*$")
NEXT_SECTION_RE = re.compile(r"^##\s+")
CHECKBOX_RE = re.compile(r"^\s*-\s*\[\s*\]\s*(.+?)\s*$")
INTEGRATION_RE = re.compile(r"^\*\*Integration points that tend to need a hand\*\*(.*)$")

GATE_LABELS: dict[str, str] = {
    "conflict_markers": "No leftover conflict markers (`git grep -nE '^(<{7}|={7}|>{7})( |$)'`)",
    "backend_lint": "Backend `make lint` (CI enforces `ruff format --check`)",
    "backend_test": "Backend `make test`",
    "frontend_check": "Frontend `pnpm format && pnpm check && pnpm test`",
    "uv_lock": "`backend/uv.lock` reconciled (`uv lock`, every fork extra present)",
}

STATUS_ICON = {"pass": "✅", "fail": "❌", "skip": "⏭️", "unknown": "❔"}
STATUS_WORD = {"pass": "passed", "fail": "FAILED", "skip": "skipped", "unknown": "not run"}


@dataclass
class Checklist:
    mechanical: list[str] = field(default_factory=list)
    features: list[tuple[str, str]] = field(default_factory=list)
    integration_note: str = ""


def parse_post_sync_checklist(text: str) -> Checklist:
    """Read FORK.md's post-sync checklist: mechanical gates + the feature table."""
    checklist = Checklist()
    in_section = False

    for line in text.splitlines():
        if not in_section:
            if CHECKLIST_HEADING_RE.match(line):
                in_section = True
            continue
        if NEXT_SECTION_RE.match(line):
            break

        checkbox = CHECKBOX_RE.match(line)
        if checkbox:
            checklist.mechanical.append(checkbox.group(1))
            continue

        integration = INTEGRATION_RE.match(line.strip())
        if integration:
            checklist.integration_note = line.strip()
            continue

        if line.strip().startswith("|") and line.strip().endswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 2:
                continue
            name, how = cells[0], cells[1]
            if not name or name.lower().startswith("fork feature"):
                continue
            if set(name) <= {"-", ":", " "}:
                continue
            checklist.features.append((name, how))

    return checklist


def _gate_lines(gates: dict[str, str]) -> list[str]:
    lines = []
    for key, label in GATE_LABELS.items():
        status = gates.get(key, "unknown")
        icon = STATUS_ICON.get(status, STATUS_ICON["unknown"])
        word = STATUS_WORD.get(status, STATUS_WORD["unknown"])
        lines.append(f"| {icon} | {label} | {word} |")
    return lines


def render_pr_body(
    *,
    checklist: Checklist,
    gates: dict[str, str],
    conflicts: list[str],
    upstream_sha: str,
    commit_count: int = 0,
    workflow_files: list[str] | None = None,
) -> str:
    workflow_files = workflow_files or []
    lines: list[str] = []

    lines += [
        "Automated merge of `bytedance/deer-flow@main` into this fork.",
        "",
        f"Upstream head: `{upstream_sha}` — **{commit_count} upstream commit(s)** in this merge.",
        "",
        "This is a **merge, never a rebase**: this fork's `main` carries its own merge commits and merged PRs, so a rebase would rewrite published history, orphan the merged-PR refs, and force every overlapping-file conflict to be re-resolved commit by commit.",
        "",
    ]

    if conflicts:
        lines += [
            "## ⚠️ Merge conflicts — do not merge as-is",
            "",
            f"The merge left **{len(conflicts)} conflicted path(s)**. This PR is opened anyway, and deliberately: a conflict is the case where a human is most needed and most needs to know early. Check the branch out, resolve, and push.",
            "",
            *[f"- `{path}`" for path in conflicts],
            "",
        ]
        if checklist.integration_note:
            lines += [checklist.integration_note, ""]
    else:
        lines += ["## Merge", "", "Merged cleanly — no conflicts.", ""]

    lines += [
        "## Mechanical gates",
        "",
        "| | Gate | Result |",
        "| --- | --- | --- |",
        *_gate_lines(gates),
        "",
    ]
    if any(status == "skip" for status in gates.values()):
        lines += ["Skipped gates could not run — usually because the merge conflicted, so there was no coherent tree to test.", ""]

    if workflow_files:
        lines += [
            "## ⚠️ Workflow files changed upstream",
            "",
            "This merge touches files under `.github/workflows/`, which `GITHUB_TOKEN` is **not permitted to push**. If the sync branch is missing these changes, re-run the merge locally with a personal access token (or apply them by hand):",
            "",
            *[f"- `{path}`" for path in workflow_files],
            "",
        ]

    lines += [
        "## Fork feature verification",
        "",
        "Passing unit tests do not prove the fork's *UI wiring* or *launch-time scripts* survived a large merge. This list is generated from FORK.md's post-sync checklist, so it stays current as the fork grows.",
        "",
        "### Remaining mechanical checks",
        "",
    ]
    lines += [f"- [ ] {item}" for item in checklist.mechanical]
    lines += ["", "### Each fork feature, end to end", ""]
    for name, how in checklist.features:
        lines.append(f"- [ ] {name} — {how}")

    lines += [
        "",
        "---",
        "",
        "Generated by `.github/workflows/upstream-sync.yml`. The checklist body comes from [FORK.md's post-sync checklist](../blob/main/FORK.md#post-sync-feature-checklist); edit it there, not here.",
        "",
        "🤖 Generated with [Claude Code](https://claude.com/claude-code)",
    ]

    body = "\n".join(lines)
    # GitHub rejects bodies over 65536 characters, and the feature table grows
    # with every fork feature. Truncate the tail rather than failing the job.
    limit = 65000
    if len(body) > limit:
        body = body[:limit] + "\n\n… truncated; see FORK.md's post-sync checklist for the remaining items."
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the PR body for an automated upstream sync.")
    parser.add_argument("--fork-md", default=str(FORK_MD))
    parser.add_argument("--gates", default=None, help="JSON file of gate name -> pass|fail|skip")
    parser.add_argument("--conflicts", default=None, help="File of conflicted paths, one per line")
    parser.add_argument("--workflow-files", default=None, help="File of changed .github/workflows paths, one per line")
    parser.add_argument("--upstream-sha", default="unknown")
    parser.add_argument("--commit-count", type=int, default=0)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    checklist = parse_post_sync_checklist(Path(args.fork_md).read_text(encoding="utf-8"))

    gates: dict[str, str] = {}
    if args.gates:
        try:
            gates = json.loads(Path(args.gates).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A missing or broken gates file means "not run", which the body
            # renders as ❔ — never as a silent pass.
            gates = {}

    def _read_lines(path: str | None) -> list[str]:
        if not path:
            return []
        try:
            return [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError:
            return []

    body = render_pr_body(
        checklist=checklist,
        gates=gates,
        conflicts=_read_lines(args.conflicts),
        upstream_sha=args.upstream_sha,
        commit_count=args.commit_count,
        workflow_files=_read_lines(args.workflow_files),
    )

    print(body)
    if args.output:
        Path(args.output).write_text(body, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
