"""The coding skills ported from Hermes Agent stay DeerFlow-native and keep their MIT notice.

Six public skills are adapted from NousResearch/hermes-agent (MIT), some of which
Hermes in turn adapted from obra/superpowers or gsd-build/get-shit-done. A port can
go wrong silently: frontmatter the loader drops, a copyright line lost in an edit, a
Hermes tool name the agent cannot call, or a pointer to a skill that does not ship.
These checks read the packages as files and run offline.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_SKILLS = REPO_ROOT / "skills" / "public"
HARNESS = REPO_ROOT / "backend" / "packages" / "harness" / "deerflow"

HERMES = "Copyright (c) 2025 Nous Research"
SUPERPOWERS = "Copyright (c) 2025 Jesse Vincent"
GSD = "Copyright (c) 2025 Lex Christopherson"

# Skill -> the copyright lines its LICENSE.txt must carry (Hermes, plus the
# project Hermes adapted it from).
PORTED_SKILLS = {
    "systematic-debugging": (HERMES, SUPERPOWERS),
    "test-driven-development": (HERMES, SUPERPOWERS),
    "requesting-code-review": (HERMES, SUPERPOWERS),
    "simplify-code": (HERMES,),
    "spike": (HERMES, GSD),
    "subagent-driven-development": (HERMES, SUPERPOWERS, GSD),
}

# Every enabled skill's description rides in every system prompt.
DESCRIPTION_BUDGET = 300

# Hermes tool names with no DeerFlow tool behind them; the DeerFlow names are
# bash, grep/glob, str_replace, task, read_file and web_fetch.
HERMES_ONLY_TOOLS = {"terminal", "search_files", "patch", "delegate_task", "skill_view", "web_extract", "todo", "execute_code"}
HERMES_ONLY_CONCEPTS = ("~/.hermes", "hermes chat", "HERMES.md", "kanban", "curator")

_TOOL_MENTION_RE = re.compile(r"`([a-z][a-z0-9_]*)`\s+tools?\b")
_SKILL_MENTION_RE = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`\s+skills?\b")
_SKILL_PATH_RE = re.compile(r"/mnt/skills/public/([a-z0-9-]+)/")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")

pytestmark = pytest.mark.parametrize("skill", sorted(PORTED_SKILLS))


def _skill_text(skill: str) -> str:
    return (PUBLIC_SKILLS / skill / "SKILL.md").read_text(encoding="utf-8-sig")


def _package_texts(skill: str) -> dict[str, str]:
    root = PUBLIC_SKILLS / skill
    return {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8-sig") for path in sorted(root.rglob("*.md"))}


def _frontmatter(skill: str) -> dict:
    frontmatter = pytest.importorskip("deerflow.skills.frontmatter", reason="the shared frontmatter parser ships with the backend harness")
    parts, error = frontmatter.split_skill_markdown(_skill_text(skill))
    assert error is None, error
    return parts.metadata


def _deerflow_tool_names() -> set[str]:
    """Tool names an agent can actually call, read from the code and the shipped config."""
    names: set[str] = set()
    for source in [HARNESS / "sandbox" / "tools.py", *sorted((HARNESS / "tools" / "builtins").glob("*.py"))]:
        names.update(re.findall(r'@tool\(\s*"([a-z_]+)"', source.read_text(encoding="utf-8")))
    config = (REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8")
    tools_section = re.search(r"(?ms)^tools:\n(.*?)^\S", config)
    assert tools_section, "config.example.yaml has no top-level tools: section"
    names.update(re.findall(r"(?m)^  - name: ([a-z_]+)$", tools_section.group(1)))
    # write_todos comes from langchain's TodoListMiddleware, which DeerFlow extends.
    if '"write_todos"' in (HARNESS / "agents" / "middlewares" / "todo_middleware.py").read_text(encoding="utf-8"):
        names.add("write_todos")
    return names


def test_frontmatter_passes_the_install_validator(skill):
    validation = pytest.importorskip("deerflow.skills.validation", reason="the install validator ships with the backend harness")
    valid, message, name = validation.validate_skill_frontmatter_text(_skill_text(skill))
    assert valid, message
    assert name == skill

    description = _frontmatter(skill)["description"].strip()
    assert description.startswith("Use this skill when"), description
    assert len(description) <= DESCRIPTION_BUDGET, f"{skill}: {len(description)} characters"


def test_review_core_reports_no_findings(skill):
    """The packages use ~~~ fences on purpose: the reviewer reads any backtick span holding a "/" as a package path."""
    analyzer = pytest.importorskip("deerflow.skills.review.analyzer", reason="the review core ships with the backend harness")
    readers = pytest.importorskip("deerflow.skills.review.readers")
    facts = analyzer.analyze_skill_package(readers.LocalDirectoryReader(PUBLIC_SKILLS / skill).read())
    findings = [f"{item['severity']} {item['rule_id']} at {item.get('path')}: {item['message']}" for item in facts["findings"]]
    assert findings == []
    assert facts["completeness"]["not_assessed"] == []


def test_license_is_mit_and_keeps_upstream_copyrights(skill):
    metadata = _frontmatter(skill)
    assert metadata["license"] == "MIT"
    assert "Hermes Agent (Nous Research)" in metadata["author"]

    license_text = (PUBLIC_SKILLS / skill / "LICENSE.txt").read_text(encoding="utf-8")
    assert license_text.startswith("MIT License")
    assert "Permission is hereby granted, free of charge" in license_text
    for copyright_line in PORTED_SKILLS[skill]:
        assert copyright_line in license_text, f"{skill}/LICENSE.txt lost: {copyright_line}"


def test_no_hermes_only_tool_or_concept_remains(skill):
    for path, text in _package_texts(skill).items():
        spans = {span.strip() for span in _INLINE_CODE_RE.findall(text)}
        assert not spans & HERMES_ONLY_TOOLS, f"{skill}/{path}: {sorted(spans & HERMES_ONLY_TOOLS)}"
        calls = re.findall(r"\b(terminal|search_files|delegate_task|skill_view|web_extract|execute_code)\(", text)
        assert not calls, f"{skill}/{path}: {calls}"
        for concept in HERMES_ONLY_CONCEPTS:
            assert concept not in text, f"{skill}/{path}: {concept}"


def test_every_named_tool_is_a_deerflow_tool(skill):
    known = _deerflow_tool_names()
    assert {"bash", "grep", "glob", "read_file", "str_replace", "write_file", "task", "write_todos", "web_fetch"} <= known
    mentioned = {name for text in _package_texts(skill).values() for name in _TOOL_MENTION_RE.findall(text)}
    assert mentioned, f"{skill} names no tool in the `name` tool form, so this check would pass vacuously"
    assert mentioned <= known, f"{skill}: not DeerFlow tools: {sorted(mentioned - known)}"


def test_cross_referenced_skills_ship(skill):
    referenced = set(_frontmatter(skill).get("metadata", {}).get("related-skills", []))
    for text in _package_texts(skill).values():
        referenced.update(_SKILL_MENTION_RE.findall(text))
        referenced.update(_SKILL_PATH_RE.findall(text))
    missing = sorted(name for name in referenced if not (PUBLIC_SKILLS / name / "SKILL.md").is_file())
    assert not missing, f"{skill} points at skills that do not ship: {missing}"
