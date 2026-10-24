"""Regression test for skill discovery under a skill package.

The skill-storage walk used to descend into
``skill-reviewer/evals/fixtures/*/SKILL.md`` and load those eval fixtures as
real, enabled skills. Nested ``SKILL.md`` files are package resources, not
separate skills.

(The companion "framework-only allowed-tools must not restrict the agent" tests
went with upstream #6935, which retired allowed-tools enforcement entirely and
kept the field as compatibility metadata.)
"""

from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
from deerflow.skills.types import SKILL_MD_FILE


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
