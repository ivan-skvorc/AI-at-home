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
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGE_CYCLE = REPO_ROOT / "CHANGE_CYCLE.md"
FORK_MD = REPO_ROOT / "FORK.md"
ROOT_AGENTS = REPO_ROOT / "AGENTS.md"
README = REPO_ROOT / "README.md"
PR_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"

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


def test_every_agent_reaches_the_cycle_without_being_asked() -> None:
    """The cycle runs automatically only if every agent's entry file leads to it.

    Codex, Grok Build and others read `AGENTS.md`; Claude Code reads `CLAUDE.md`
    and Gemini CLI reads `GEMINI.md`, and each of those, at any depth, must stay a
    pure `@AGENTS.md` import so no agent or model gets rules the others miss.
    The pointer sits above the root guide's first section because some agents
    cap how much instruction text they load (Codex: 32 KiB by default); moved
    further down, it still renders and is silently cut.
    """
    root = ROOT_AGENTS.read_text(encoding="utf-8")
    first_section = root.index("\n## ")
    assert "CHANGE_CYCLE.md" in root[:first_section], "the cycle pointer moved below the root guide's first section"
    assert "automatically" in root[:first_section]
    assert "Automatic for every change request" in CHANGE_CYCLE.read_text(encoding="utf-8")

    tracked = subprocess.run(
        ["git", "ls-files", "--", "CLAUDE.md", "*/CLAUDE.md", "GEMINI.md", "*/GEMINI.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    shims = [REPO_ROOT / rel for rel in sorted(tracked)]
    assert REPO_ROOT / "CLAUDE.md" in shims, "no root CLAUDE.md shim found"
    assert REPO_ROOT / "GEMINI.md" in shims, "no root GEMINI.md shim found; Gemini CLI reads GEMINI.md, not AGENTS.md"
    for shim in shims:
        text = shim.read_text(encoding="utf-8")
        assert text.rstrip().splitlines()[-1] in ("@AGENTS.md", "@./AGENTS.md"), f"{shim.relative_to(REPO_ROOT)} must import its sibling AGENTS.md"
        assert (shim.parent / "AGENTS.md").is_file(), f"{shim.relative_to(REPO_ROOT)} imports a missing AGENTS.md"
        assert "CHANGE_CYCLE" not in text and "## " not in text, f"{shim.relative_to(REPO_ROOT)} carries rules of its own; put them in AGENTS.md"


def test_the_cycle_keeps_the_test_and_audit_steps_the_owner_asked_for() -> None:
    """Run tests, add them only for gaps, prune redundant ones, audit only on request.

    Like the PR step, each of these can be deleted or inverted without any other
    test noticing: the cycle still renders, its links resolve, and the next agent
    simply stops pruning tests or starts auditing models on every change. Pinned
    by step headings and report lines, so the prose stays free to change.
    """
    text = CHANGE_CYCLE.read_text(encoding="utf-8")
    flags = re.MULTILINE | re.IGNORECASE

    assert re.search(r"^##\s+\d+\.\s+.*\btests\b.*\badd\b.*\bremove\b", text, flags), "the test-maintenance step no longer covers adding and removing tests"
    assert re.search(r"^###\s+.*\bremove\b.*\btests\b", text, flags), "the review-and-remove-unnecessary-tests sub-step is gone"
    assert re.search(r"^##\s+\d+\.\s+Run existing tests\b", text, flags), "the step that runs existing tests at the required scope is gone"
    assert re.search(r"^##\s+\d+\.\s+Model audit\b.*\boptional\b", text, flags), "the model audit step is no longer marked optional"
    for line in ("Tests added:", "Tests reviewed:", "Tests removed:", "Validation:", "Model audit:"):
        assert line in text, f"the report shape lost {line!r}"

    root = ROOT_AGENTS.read_text(encoding="utf-8")
    header = root[: root.index("\n## ")]
    assert "remove unnecessary tests" in header, "the root pointer stopped naming test pruning"
    assert "pull request" in header, "the root pointer stopped naming the pull request"

    template = PR_TEMPLATE.read_text(encoding="utf-8")
    assert re.search(r"^##\s+Validation\s*$", template, re.MULTILINE), "the PR template lost the Validation section step 9 fills in"
    section = re.search(r"^##\s+Test maintenance\s*$(.*?)(?=^##\s)", template, re.MULTILINE | re.DOTALL)
    assert section, "the PR template lost the Test maintenance section step 3 records into"
    assert "removed" in section.group(1).lower(), "Test maintenance no longer asks which tests were removed"


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
