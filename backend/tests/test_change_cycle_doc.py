"""Tests for change_cycle.md — the procedure a change is expected to follow.

The cycle follows the setup brief shipped with the `repo-change-cycle` skill
(`skills/public/repo-change-cycle/references/setup-brief.md`): three levels, a
repo map whose sync line marks the last checked commit, a PR summary, and a
merge. It owns the order of operations and reads its fork-specific lists (the
critical checks, the post-sync checklist, the model audit) out of FORK.md
rather than copying them, so there is one checklist to maintain instead of two
that drift. That design has one silent failure mode — a heading in FORK.md gets
renamed, every link in the cycle still renders, and the procedure quietly
points at nothing.

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
CHANGE_CYCLE = REPO_ROOT / "change_cycle.md"
FORK_MD = REPO_ROOT / "FORK.md"
ROOT_AGENTS = REPO_ROOT / "AGENTS.md"
README = REPO_ROOT / "README.md"
PR_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"
BRIEF = REPO_ROOT / "skills" / "public" / "repo-change-cycle" / "references" / "setup-brief.md"

TRIGGER = "run change_cycle.md level 1"
LEGACY_TRIGGER = "run the code change cycle from CHANGE_CYCLE.md"
# The sentence that introduces README.md's leading bullet list — the fork's shop
# window, and the thing every new feature owes a bullet in (Every level, step 4).
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


def _without_code_blocks(markdown: str) -> str:
    return re.sub(r"^```.*?^```", "", markdown, flags=re.MULTILINE | re.DOTALL)


def _section(markdown: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", markdown, re.MULTILINE | re.DOTALL)
    assert match, f"change_cycle.md lost its {heading!r} section"
    return match.group(1)


def test_the_trigger_sentence_is_in_the_file_that_answers_to_it() -> None:
    """The whole point is that one sentence runs the procedure.

    Reword the trigger in the file and the sentence users type stops matching
    anything, which reads as "the agent ignored the instruction" rather than as
    a documentation change. The older phrase stays an alias for level 1.
    """
    text = CHANGE_CYCLE.read_text(encoding="utf-8")
    assert TRIGGER in text.replace('"', "")
    assert LEGACY_TRIGGER in text


def test_every_link_the_cycle_follows_exists() -> None:
    text = CHANGE_CYCLE.read_text(encoding="utf-8")
    missing = []
    for target in _local_links(text):
        path_part = target.split("#", 1)[0]
        if not path_part:  # a bare in-page anchor
            continue
        if not (REPO_ROOT / path_part).exists():
            missing.append(target)
    assert not missing, f"change_cycle.md links to paths that do not exist: {missing}"


def test_every_fork_md_section_the_cycle_names_still_exists() -> None:
    """The silent one: a renamed heading leaves a link that renders and goes nowhere."""
    cycle = CHANGE_CYCLE.read_text(encoding="utf-8")
    fork_anchors = _anchors(FORK_MD.read_text(encoding="utf-8"))

    dangling = [target for target in _local_links(cycle) if target.startswith("FORK.md#") and target.split("#", 1)[1] not in fork_anchors]
    assert not dangling, f"change_cycle.md points at FORK.md sections that are gone: {dangling}"


def test_the_checklist_heading_is_the_one_the_sync_script_parses() -> None:
    """One heading serves both readers; it may be renamed, but only in both places."""
    heading_re = re.compile(r"^###\s+Post-sync feature checklist\s*$", re.MULTILINE)
    script = (REPO_ROOT / "scripts" / "upstream_sync.py").read_text(encoding="utf-8")

    assert heading_re.search(FORK_MD.read_text(encoding="utf-8")), "FORK.md no longer has the checklist heading change_cycle.md and scripts/upstream_sync.py both address it by"
    assert r"^###\s+Post-sync feature checklist\s*$" in script, "scripts/upstream_sync.py stopped parsing the checklist by that heading; update change_cycle.md's links in the same change"


def test_the_cycle_still_ends_by_opening_and_merging_a_pull_request() -> None:
    """The steps most likely to be dropped, and the ones whose loss is silent.

    Every other step announces itself when it goes missing: a skipped test run
    shows up as red CI, a stale map shows up in the next level 2 run. A missing
    PR step shows up as nothing at all — the branch is pushed, the report reads
    green, and the work sits there. Pinned on the numbered steps of "Every
    level", not on their prose.
    """
    every_level = _section(CHANGE_CYCLE.read_text(encoding="utf-8"), "Every level")

    assert re.search(r"^\d+\.\s+Open a PR with the summary below", every_level, re.MULTILINE), "Every level no longer opens a PR"
    assert re.search(r"^\d+\.\s+Merge once the level's checks pass", every_level, re.MULTILINE), "Every level no longer merges once the checks pass"
    assert "revert that PR first" in every_level, "the revert-first rule for a broken main is gone"
    assert "PR:" in _section(CHANGE_CYCLE.read_text(encoding="utf-8"), "PR summary"), "the summary stopped asking for the PR url"


def test_the_cycle_has_the_brief_s_shape_with_every_placeholder_filled() -> None:
    """The brief is the contract: its sections, its levels, its sync-point command.

    A placeholder left in a command is a command that fails when pasted, which
    is the one thing the brief forbids; the PR summary block keeps its fields
    on purpose (it is the template the PR body fills in).
    """
    text = CHANGE_CYCLE.read_text(encoding="utf-8")
    for heading in ("Commands", "Every level", "Level 1: affected features", "Level 2: whole app", "Level 3: quality review", "PR summary", "References"):
        _section(text, heading)
    for row in ("| 1 | Features linked to the changed files |", "| 2 | The whole app |", "| 3 | The whole app + quality review |"):
        assert row in text, f"the level table lost {row!r}"

    summary = _section(text, "PR summary")
    outside_summary = text.replace(summary, "")
    leftovers = re.findall(r"`[^`]*<[a-z][^>`]*>[^`]*`", outside_summary)
    assert not leftovers, f"unfilled placeholders in commands: {leftovers}"

    assert "SYNC=$(git log -1 --format=%H -G'Synced by change cycle:' origin/main -- docs/repo-map.md docs/repo-map/index.md)" in text
    assert '{ git diff --name-only --no-renames "$SYNC"; git ls-files --others --exclude-standard; } | sort -u' in text
    for line in ("Level:", "Changed since sync point:", "Checks run:", "Map:", "Quality fixes:", "Exceptions added/removed:"):
        assert line in summary, f"the PR summary lost the brief's {line!r} line"

    assert (REPO_ROOT / "docs" / "quality-exceptions.md").is_file()
    assert (REPO_ROOT / "docs" / "repo-map" / "index.md").is_file()
    brief = BRIEF.read_text(encoding="utf-8")
    assert "## Done when" in brief and "## 3. `change_cycle.md`" in brief, "the bundled setup brief is no longer the full brief"


def test_the_entry_point_is_reachable_from_the_guidance_an_agent_reads_first() -> None:
    """A procedure nobody is pointed at is a procedure nobody runs.

    An agent starts at AGENTS.md (imported by CLAUDE.md); a maintainer starts at
    FORK.md. Both have to name the cycle, and the agent guide the map too (the
    brief's one-line pointer), or they are discoverable only by someone who
    already knows they exist.
    """
    root = ROOT_AGENTS.read_text(encoding="utf-8")
    assert "change_cycle.md" in root
    assert "docs/repo-map/index.md" in root
    assert "change_cycle.md" in FORK_MD.read_text(encoding="utf-8")


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
    assert "change_cycle.md" in root[:first_section], "the cycle pointer moved below the root guide's first section"
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
        assert "change_cycle" not in text.lower() and "## " not in text, f"{shim.relative_to(REPO_ROOT)} carries rules of its own; put them in AGENTS.md"


def test_the_cycle_keeps_the_test_and_audit_steps_the_owner_asked_for() -> None:
    """Run tests, add them only for gaps, prune redundant ones, audit only on request.

    Each of these can be deleted or inverted without any other test noticing:
    the cycle still renders, its links resolve, and the next agent simply stops
    pruning tests or starts auditing models on every change.
    """
    text = CHANGE_CYCLE.read_text(encoding="utf-8")
    every_level = _section(text, "Every level")

    assert "A new feature gets at least one test in the same change." in every_level
    assert re.search(r"remove a test only when", every_level, re.IGNORECASE), "the review-and-remove-unnecessary-tests rule is gone"
    assert "Don't weaken or delete a test to make it pass" in every_level
    audit = _section(text, "Model audit (only when asked)")
    assert "only" in audit and "asks for one in words" in audit, "the model audit is no longer opt-in"
    assert "Model audit:" in _section(text, "PR summary")

    root = ROOT_AGENTS.read_text(encoding="utf-8")
    header = root[: root.index("\n## ")]
    assert "remove unnecessary tests" in header, "the root pointer stopped naming test pruning"
    assert "pull request" in header, "the root pointer stopped naming the pull request"

    template = PR_TEMPLATE.read_text(encoding="utf-8")
    assert "Changed since sync point:" in template, "the PR template no longer carries the change-cycle summary"
    assert re.search(r"^##\s+Validation\s*$", template, re.MULTILINE), "the PR template lost the Validation section"
    section = re.search(r"^##\s+Test maintenance\s*$(.*?)(?=^##\s)", template, re.MULTILINE | re.DOTALL)
    assert section, "the PR template lost the Test maintenance section"
    assert "removed" in section.group(1).lower(), "Test maintenance no longer asks which tests were removed"


def test_the_cycle_asks_whether_the_change_is_a_feature_and_owes_the_readme() -> None:
    """The documentation duty CI cannot fail for you.

    Every other gate in the cycle has a machine behind it: a missing test shows
    up red, a stale map shows up in `test_repo_map.py`, an unbumped
    `config_version` shows up in `validate-chart`. A feature that never reaches
    README.md shows up as nothing — the suite is green, the diff is clean, and
    the feature is simply undiscoverable. So the duty has to be stated in the
    step itself.
    """
    every_level = _section(CHANGE_CYCLE.read_text(encoding="utf-8"), "Every level")
    assert "README.md" in every_level and SHOP_WINDOW_LEAD in every_level, "Every level no longer sends a new feature to README.md's bullet list"


def test_the_readme_still_has_the_shape_the_cycle_sends_a_feature_to() -> None:
    """The cycle names a specific place in a specific file; this is that place.

    The instruction is worth exactly as much as the list it points at. Rewrite
    README.md's opening blockquote — drop the fork description, re-title the
    bullet list, flatten it out of the quote — and the cycle still renders,
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

    assert SHOP_WINDOW_LEAD in readme, f"README.md no longer introduces its leading bullet list with {SHOP_WINDOW_LEAD!r}; change_cycle.md points at a list that is gone"

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


def test_the_critical_checks_come_first_and_include_the_local_model_window() -> None:
    """The checks a user loses the product over run before everything else.

    Each piece can be dropped without anything else noticing: the section, the
    FORK.md list it points at, the ordering that keeps that list ahead of the
    sync PR body's truncation, the Ollama context check the owner asked for by
    name, and the report line that shows they ran.
    """
    cycle = CHANGE_CYCLE.read_text(encoding="utf-8")
    fork = FORK_MD.read_text(encoding="utf-8")

    assert re.search(r"^##\s+Critical checks\b", cycle, re.MULTILINE), "change_cycle.md lost its critical-checks section"
    assert "Critical checks:" in cycle, "the report shape stopped listing the critical checks"
    checklist = fork[fork.index("### Post-sync feature checklist") :]
    assert re.search(r"^####\s+Critical checks\s*$", checklist, re.MULTILINE), "FORK.md's checklist lost its Critical checks list"
    first_gate = next(line for line in checklist.splitlines() if line.lstrip().startswith("- [ ]"))
    assert "Critical" in first_gate, "the critical checks are no longer the first lines the sync script parses"
    assert "tests/test_context_fit_critical.py" in first_gate, "the local-model context-size check is no longer a critical check"
    assert (REPO_ROOT / "backend" / "tests" / "test_context_fit_critical.py").is_file()


def test_no_check_is_run_twice_on_one_tree() -> None:
    """One tree, one run: the rule, and the two ways it used to be broken.

    A second run of a test a suite already collected proves nothing, and it is
    silent: the cycle just gets slower. Pinned on the rule's own lead-in, on the
    critical files staying where `make test` collects them, and on no whole
    test file being run by two checklist items.
    """
    cycle = CHANGE_CYCLE.read_text(encoding="utf-8")
    fork = FORK_MD.read_text(encoding="utf-8")

    assert "**Once per tree.**" in cycle and "Run each check once on the final tree" in cycle, "change_cycle.md lost the run-each-check-once rule"

    checklist = fork[fork.index("### Post-sync feature checklist") :]
    checklist = checklist[: re.search(r"^## ", checklist, re.MULTILINE).start()]
    owners: dict[str, set[int]] = {}
    for number, line in enumerate(checklist.splitlines()):
        if not (line.lstrip().startswith("- [ ]") or line.startswith("|")):
            continue
        for command in re.findall(r"`cd backend && uv run pytest ([^`]+)`", line):
            if " -k " in f" {command} ":
                continue  # a -k selection is a slice of the file, not the file
            for path in re.findall(r"tests/[\w/]+\.py(?!::)", command):
                owners.setdefault(path, set()).add(number)
                if "Critical —" in line:
                    assert not path.startswith("tests/blocking_io/"), f"{path}: `make test` ignores tests/blocking_io, so it would stop running this critical check"
    twice = sorted(path for path, rows in owners.items() if len(rows) > 1)
    assert not twice, f"run whole by two checklist items; name the first row in the second instead: {twice}"


def test_every_level_updates_the_map() -> None:
    """The map goes stale silently: a new file with no row is only caught by the next full check.

    "Every level, step 3" says to update it, but an agent running one level reads that
    level's section; each of the three names the update and the check that proves it,
    and level 3 updates again after its own fixes add, delete or rename files.
    """
    text = CHANGE_CYCLE.read_text(encoding="utf-8")
    for heading in ("Level 1: affected features", "Level 2: whole app", "Level 3: quality review"):
        section = _section(text, heading)
        assert "Update the map" in section, f"{heading} no longer updates the map"
        assert "test_repo_map.py" in section, f"{heading} no longer runs the map check"
    for row in ("| 1 | Features linked to the changed files |", "| 2 | The whole app |", "| 3 | The whole app + quality review |"):
        line = next(line for line in text.splitlines() if line.startswith(row))
        assert line.rstrip().rstrip("|").rsplit("|", 1)[-1].strip(), f"the level table row {row!r} lost its map column"
