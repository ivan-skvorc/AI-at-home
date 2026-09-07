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
README = REPO_ROOT / "README.md"

TRIGGER = "run the code change cycle from CHANGE_CYCLE.md"
# The sentence that introduces README.md's leading bullet list — the fork's shop
# window, and the thing CHANGE_CYCLE.md step 7 sends every new feature to.
SHOP_WINDOW_LEAD = "it adds — out of the box:"

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


def test_the_cycle_still_ends_by_opening_a_pull_request() -> None:
    """The step most likely to be dropped, and the one whose loss is silent.

    Every other step of the cycle announces itself when it goes missing: a
    skipped test run shows up as red CI, a stale checklist row shows up in the
    next sync PR. A missing PR step shows up as nothing at all — the branch is
    pushed, the report reads green, and the work simply sits there until someone
    thinks to look for it. So the numbered step is pinned structurally rather
    than by its prose: rename it freely, delete it and this fails.
    """
    text = CHANGE_CYCLE.read_text(encoding="utf-8")

    assert re.search(r"^##\s+\d+\.\s+Open the pull request\s*$", text, re.MULTILINE), "CHANGE_CYCLE.md no longer has a numbered step that opens the pull request; the cycle ends at a pushed branch nobody reviews"
    assert "PR:" in text, "the report shape stopped asking for the PR url, which is how a reader tells an opened PR from an intended one"


def test_the_entry_point_is_reachable_from_the_guidance_an_agent_reads_first() -> None:
    """A procedure nobody is pointed at is a procedure nobody runs.

    An agent starts at AGENTS.md (imported by CLAUDE.md); a maintainer starts at
    FORK.md. Both have to name the cycle, or it is discoverable only by someone
    who already knows it exists.
    """
    assert "CHANGE_CYCLE.md" in ROOT_AGENTS.read_text(encoding="utf-8")
    assert "CHANGE_CYCLE.md" in FORK_MD.read_text(encoding="utf-8")


def test_the_cycle_asks_whether_the_change_is_a_feature_and_owes_the_readme() -> None:
    """The documentation duty CI cannot fail for you.

    Every other gate in the cycle has a machine behind it: a missing test shows
    up red, a stale checklist row shows up in the next sync PR, an unbumped
    `config_version` shows up in `validate-chart`. A feature that never reaches
    README.md shows up as nothing — the suite is green, the diff is clean, and
    the feature is simply undiscoverable. So the question has to be asked in
    prose, in the step, the same way step 3 asks about tests.
    """
    text = CHANGE_CYCLE.read_text(encoding="utf-8")

    assert re.search(r"^###\s+.*\bREADME\.md\b.*$", text, re.MULTILINE), "CHANGE_CYCLE.md step 7 lost the sub-step that asks whether the change is a feature and sends it to README.md"
    assert "README:" in text, "the report shape stopped asking what happened to README.md, which is how a reader tells a landed bullet from an intended one"


def test_the_readme_still_has_the_shape_the_cycle_sends_a_feature_to() -> None:
    """Step 7 names a specific place in a specific file; this is that place.

    The instruction is worth exactly as much as the list it points at. Rewrite
    README.md's opening blockquote — drop the fork description, re-title the
    bullet list, flatten it out of the quote — and the step still renders,
    still reads sensibly, and lands the next feature nowhere. Pinned by the
    landmarks the step actually names, not by the prose between them, so the
    copy stays free to change.

    The order those landmarks appear in is deliberate and is asserted:
    **hook, then bullets, then description.** The bullet list is the fork's shop
    window, so it comes before the prose about what the repo is — a reader who
    stops after one screen should have seen what they get, not a paragraph
    explaining what they are looking at.
    """
    readme = README.read_text(encoding="utf-8")

    assert SHOP_WINDOW_LEAD in readme, f"README.md no longer introduces its leading bullet list with {SHOP_WINDOW_LEAD!r}; CHANGE_CYCLE.md step 7 points at a list that is gone"

    lead = readme.index(SHOP_WINDOW_LEAD)
    assert readme.count("\n> - ", lead) >= 10, "README.md's leading list is no longer a blockquote bullet list of what the fork adds over upstream"

    # The opening hook comes first: it is the one line a reader who bounces will
    # have read, and it is above the bullets on purpose.
    assert "AI too expensive?" in readme[:lead], "README.md lost the opening line that leads the shop window"

    # ...and the short description of the repo follows the bullets, so the
    # window comes before the explanation rather than after it.
    description = readme.find("fork of [bytedance/deer-flow]", lead)
    assert description != -1, "the short description of the repo that follows the bullet list is gone"
    assert "What this fork is for" in readme[description:], "README.md lost the statement of what the fork is for, which is what tells a reader whether a change belongs here"
