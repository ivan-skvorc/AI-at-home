"""Regression tests for the skill tool-policy / discovery interaction.

Root cause captured here (default lead agent silently losing its tools):

The built-in ``skill-reviewer`` public skill is enabled by default and declares
``allowed-tools: [review_skill_package]``. Because ``review_skill_package`` is an
always-available framework tool, that declaration scopes *no* business tools —
yet the old ``filter_tools_by_skill_allowed_tools`` treated it as an explicit
restriction and stripped every other tool from the agent, leaving only
``read_file`` / ``review_skill_package``. Separately, the skill-storage walk
descended into ``skill-reviewer/evals/fixtures/*/SKILL.md`` and loaded those eval
fixtures as real, enabled skills (one of which declared ``allowed-tools: [bash]``),
compounding the restriction.

These tests pin both fixes so the default agent keeps its full toolset while
genuine business-tool scoping still restricts.
"""

from pathlib import Path

from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
from deerflow.skills.tool_policy import (
    ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES,
    allowed_tool_names_for_skills,
    filter_tools_by_skill_allowed_tools,
)
from deerflow.skills.types import SKILL_MD_FILE, Skill


class _NamedTool:
    def __init__(self, name: str):
        self.name = name


def _skill(name: str, allowed_tools):
    return Skill(
        name=name,
        description=f"desc {name}",
        license="MIT",
        skill_dir=Path(f"/tmp/{name}"),
        skill_file=Path(f"/tmp/{name}/SKILL.md"),
        relative_path=Path(name),
        category="public",
        allowed_tools=tuple(allowed_tools) if allowed_tools is not None else None,
        enabled=True,
    )


# --------------------------------------------------------------------------
# Fix B: framework-only / empty allowed-tools must not restrict the agent
# --------------------------------------------------------------------------


def test_framework_only_declaration_does_not_restrict():
    """A skill whose only allowed-tool is an always-available framework tool
    (the real skill-reviewer case) must not flip the agent into restricted mode."""
    skills = [_skill("skill-reviewer", ["review_skill_package"])]
    allowed = allowed_tool_names_for_skills(skills, framework_tool_names=ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES)
    assert allowed is None  # None == legacy allow-all


def test_empty_declaration_does_not_restrict():
    skills = [_skill("noop-skill", [])]
    allowed = allowed_tool_names_for_skills(skills, framework_tool_names=ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES)
    assert allowed is None


def test_default_toolset_survives_enabled_skill_reviewer():
    """End-to-end shape of the bug: with skill-reviewer enabled, the full toolset
    must pass through unchanged (previously collapsed to read_file/review_skill_package)."""
    tools = [
        _NamedTool("web_search"),
        _NamedTool("web_fetch"),
        _NamedTool("write_file"),
        _NamedTool("read_file"),
        _NamedTool("bash"),
        _NamedTool("task"),
        _NamedTool("review_skill_package"),
    ]
    skills = [_skill("skill-reviewer", ["review_skill_package"])]
    filtered = filter_tools_by_skill_allowed_tools(tools, skills, always_allowed_tool_names=ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES)
    assert [t.name for t in filtered] == [t.name for t in tools]


def test_subagent_path_keeps_all_tools_with_skill_reviewer_enabled():
    """The subagent executor calls filter_tools_by_skill_allowed_tools WITHOUT
    passing an explicit framework set. The framework built-ins must still be
    recognized so an enabled skill-reviewer does not strip subagents' tools."""
    tools = [_NamedTool("web_search"), _NamedTool("web_fetch"), _NamedTool("bash"), _NamedTool("read_file")]
    skills = [_skill("skill-reviewer", ["review_skill_package"])]
    # No always_allowed_tool_names kwarg — mirrors executor._apply_skill_allowed_tools.
    filtered = filter_tools_by_skill_allowed_tools(tools, skills)
    assert [t.name for t in filtered] == [t.name for t in tools]


def test_business_tool_declaration_still_restricts():
    """A skill that declares a real business tool must still scope the agent."""
    tools = [_NamedTool("web_search"), _NamedTool("bash"), _NamedTool("read_file")]
    skills = [_skill("data-only", ["web_search"])]
    filtered = filter_tools_by_skill_allowed_tools(tools, skills, always_allowed_tool_names=ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES)
    # web_search (declared) + read_file (framework always-available) survive; bash dropped.
    assert sorted(t.name for t in filtered) == ["read_file", "web_search"]


def test_framework_declaration_alongside_business_declaration_still_restricts():
    """A framework-only skill does not weaken restrictions from a sibling skill
    that declares a real business tool."""
    tools = [_NamedTool("web_search"), _NamedTool("bash"), _NamedTool("read_file")]
    skills = [
        _skill("skill-reviewer", ["review_skill_package"]),  # framework-only -> ignored
        _skill("data-only", ["web_search"]),  # business -> restricts
    ]
    filtered = filter_tools_by_skill_allowed_tools(tools, skills, always_allowed_tool_names=ALWAYS_AVAILABLE_BUILTIN_TOOL_NAMES)
    assert sorted(t.name for t in filtered) == ["read_file", "web_search"]


# --------------------------------------------------------------------------
# Fix A: eval fixtures nested under a skill package are not discovered
# --------------------------------------------------------------------------


def test_nested_skill_md_is_not_discovered_as_a_skill(tmp_path):
    """A package's own SKILL.md is discovered, but nested SKILL.md files under it
    (e.g. evals/fixtures/*/SKILL.md) are package resources, not separate skills."""
    public = tmp_path / "public"
    reviewer = public / "skill-reviewer"
    (reviewer).mkdir(parents=True)
    (reviewer / SKILL_MD_FILE).write_text("---\nname: skill-reviewer\n---\n", encoding="utf-8")
    fixture = reviewer / "evals" / "fixtures" / "injection-example"
    fixture.mkdir(parents=True)
    (fixture / SKILL_MD_FILE).write_text("---\nname: injection-example\nallowed-tools:\n  - bash\n---\n", encoding="utf-8")

    storage = LocalSkillStorage(host_path=str(tmp_path))
    discovered = [md_path for _cat, _root, md_path in storage._iter_skill_files()]

    assert reviewer / SKILL_MD_FILE in discovered
    assert fixture / SKILL_MD_FILE not in discovered
    assert len(discovered) == 1
