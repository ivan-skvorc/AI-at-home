"""Tests for CHANGE_CYCLE.md — the procedure a change is expected to follow.

The cycle is a *pointer* document on purpose: it owns the order of operations
and reads its two lists (the post-sync checklist and the model audit) out of
FORK.md rather than copying them, so there is one checklist to maintain instead
of two that drift. That design has exactly one silent failure mode — a heading
in FORK.md gets renamed, every link in the cycle still renders, and the
procedure quietly points at nothing. Nothing else in the suite notices: the
markdown is valid, the tests are green, and the next agent following the cycle
lands on FORK.md's top and improvises.

`test_the_checklist_heading_is_the_one_the_sync_script_parses` is the same guard
from the other side: `scripts/upstream_sync.py` finds the checklist by that
exact heading text, so the cycle and the automated sync PR either break together
or not at all.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGE_CYCLE = REPO_ROOT / "CHANGE_CYCLE.md"
FORK_MD = REPO_ROOT / "FORK.md"
ROOT_AGENTS = REPO_ROOT / "AGENTS.md"

TRIGGER = "run the code change cycle from CHANGE_CYCLE.md"

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.MULTILINE)


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, drop punctuation, spaces to hyphens."""
    text = heading.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s", "-", text)


def _anchors(markdown: str) -> set[str]:
    return {_slug(h) for h in HEADING_RE.findall(markdown)}


def _local_links(markdown: str) -> list[str]:
    return [target for target in MARKDOWN_LINK_RE.findall(markdown) if not target.startswith(("http://", "https://", "mailto:"))]


def test_the_trigger_sentence_is_in_the_file_that_answers_to_it() -> None:
    """The whole point is that one sentence runs the procedure.

    Reword the trigger in the file and the sentence users type stops matching
    anything, which reads as "the agent ignored the instruction" rather than as
    a documentation change.
    """
    assert TRIGGER in CHANGE_CYCLE.read_text(encoding="utf-8")


def test_every_link_the_cycle_follows_exists() -> None:
    text = CHANGE_CYCLE.read_text(encoding="utf-8")
    missing = []
    for target in _local_links(text):
        path_part = target.split("#", 1)[0]
        if not path_part:  # a bare in-page anchor
            continue
        if not (REPO_ROOT / path_part).exists():
            missing.append(target)
    assert not missing, f"CHANGE_CYCLE.md links to paths that do not exist: {missing}"


def test_every_fork_md_section_the_cycle_names_still_exists() -> None:
    """The silent one: a renamed heading leaves a link that renders and goes nowhere."""
    cycle = CHANGE_CYCLE.read_text(encoding="utf-8")
    fork_anchors = _anchors(FORK_MD.read_text(encoding="utf-8"))

    dangling = [target for target in _local_links(cycle) if target.startswith("FORK.md#") and target.split("#", 1)[1] not in fork_anchors]
    assert not dangling, f"CHANGE_CYCLE.md points at FORK.md sections that are gone: {dangling}"


def test_the_checklist_heading_is_the_one_the_sync_script_parses() -> None:
    """One heading serves both readers; it may be renamed, but only in both places."""
    heading_re = re.compile(r"^###\s+Post-sync feature checklist\s*$", re.MULTILINE)
    script = (REPO_ROOT / "scripts" / "upstream_sync.py").read_text(encoding="utf-8")

    assert heading_re.search(FORK_MD.read_text(encoding="utf-8")), "FORK.md no longer has the checklist heading CHANGE_CYCLE.md and scripts/upstream_sync.py both address it by"
    assert r"^###\s+Post-sync feature checklist\s*$" in script, "scripts/upstream_sync.py stopped parsing the checklist by that heading; update CHANGE_CYCLE.md's links in the same change"


def test_the_entry_point_is_reachable_from_the_guidance_an_agent_reads_first() -> None:
    """A procedure nobody is pointed at is a procedure nobody runs.

    An agent starts at AGENTS.md (imported by CLAUDE.md); a maintainer starts at
    FORK.md. Both have to name the cycle, or it is discoverable only by someone
    who already knows it exists.
    """
    assert "CHANGE_CYCLE.md" in ROOT_AGENTS.read_text(encoding="utf-8")
    assert "CHANGE_CYCLE.md" in FORK_MD.read_text(encoding="utf-8")
