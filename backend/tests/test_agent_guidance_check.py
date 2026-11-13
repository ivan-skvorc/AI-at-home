from __future__ import annotations

import importlib.util
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_agent_guidance.py"
EXPECTED_GUIDANCE_PATHS = {
    "AGENTS.md",
    "docker/AGENTS.md",
    "skills/AGENTS.md",
    "skills/public/data-analysis/AGENTS.md",
    "skills/public/video-generation/AGENTS.md",
    "backend/AGENTS.md",
    "backend/tests/AGENTS.md",
    "backend/scripts/benchmark/AGENTS.md",
    "frontend/AGENTS.md",
    "backend/app/gateway/AGENTS.md",
    "backend/app/gateway/routers/AGENTS.md",
    "backend/app/channels/AGENTS.md",
    "backend/packages/harness/deerflow/AGENTS.md",
    "backend/packages/harness/deerflow/agents/AGENTS.md",
    "backend/packages/harness/deerflow/agents/middlewares/AGENTS.md",
    "backend/packages/harness/deerflow/agents/memory/AGENTS.md",
    "backend/packages/harness/deerflow/agents/generation/AGENTS.md",
    "backend/packages/harness/deerflow/agents/lead_agent/AGENTS.md",
    "backend/packages/harness/deerflow/community/comfyui/AGENTS.md",
    "backend/packages/harness/deerflow/community/speech/AGENTS.md",
    "backend/packages/harness/deerflow/community/xai/AGENTS.md",
    "backend/packages/harness/deerflow/agents/task_continuity/AGENTS.md",
    "backend/packages/harness/deerflow/community/AGENTS.md",
    "backend/packages/harness/deerflow/community/groundroute/AGENTS.md",
    "backend/packages/harness/deerflow/community/jina_ai/AGENTS.md",
    "backend/packages/harness/deerflow/community/ragflow/AGENTS.md",
    "backend/packages/harness/deerflow/community/serper/AGENTS.md",
    "backend/packages/harness/deerflow/community/tavily/AGENTS.md",
    "backend/packages/harness/deerflow/community/ddg_search/AGENTS.md",
    "backend/packages/harness/deerflow/community/e2b_sandbox/AGENTS.md",
    "backend/packages/harness/deerflow/community/aio_sandbox/AGENTS.md",
    "backend/packages/harness/deerflow/community/boxlite/AGENTS.md",
    "backend/packages/harness/deerflow/community/browser_automation/AGENTS.md",
    "backend/packages/harness/deerflow/community/opensandbox/AGENTS.md",
    "backend/packages/harness/deerflow/config/AGENTS.md",
    "backend/packages/harness/deerflow/documents/AGENTS.md",
    "backend/packages/harness/deerflow/extensions/AGENTS.md",
    "backend/packages/harness/deerflow/runtime/AGENTS.md",
    "backend/packages/harness/deerflow/sandbox/AGENTS.md",
    "backend/packages/harness/deerflow/mcp/AGENTS.md",
    "backend/packages/harness/deerflow/models/AGENTS.md",
    "backend/packages/harness/deerflow/persistence/AGENTS.md",
    "backend/packages/harness/deerflow/persistence/migrations/AGENTS.md",
    "backend/packages/harness/deerflow/persistence/user/AGENTS.md",
    "backend/packages/harness/deerflow/skills/AGENTS.md",
    "backend/packages/harness/deerflow/storage/AGENTS.md",
    "backend/packages/harness/deerflow/subagents/AGENTS.md",
    "backend/packages/harness/deerflow/tools/AGENTS.md",
    "backend/packages/harness/deerflow/tracing/AGENTS.md",
    "backend/packages/harness/deerflow/tui/AGENTS.md",
    "backend/packages/harness/deerflow/typesafe/AGENTS.md",
    "backend/packages/harness/deerflow/uploads/AGENTS.md",
    "backend/packages/harness/deerflow/utils/AGENTS.md",
    "frontend/src/AGENTS.md",
    "frontend/src/components/workspace/AGENTS.md",
    "frontend/src/components/workspace/browser-view/AGENTS.md",
    "frontend/src/core/auth/AGENTS.md",
    "frontend/src/core/background-tasks/AGENTS.md",
    "frontend/src/core/memory/AGENTS.md",
    "frontend/src/core/models/AGENTS.md",
    "frontend/tests/e2e/AGENTS.md",
    "scripts/AGENTS.md",
    "backend/scripts/benchmark/AGENTS.md",
    "frontend/src/components/workspace/chats/AGENTS.md",
    "examples/deerflow-extension-agent-teams/AGENTS.md",
    "examples/deerflow-extension-workflows/AGENTS.md",
    # The bundled snapshot copies its package byte for byte, guide included.
    "backend/extensions/sources/deerflow-extension-workflows/AGENTS.md",
    "examples/deerflow-extension-weknora/AGENTS.md",
    "examples/deerflow-extension-knowledge-management/AGENTS.md",
    "examples/deerflow-extension-knowledge-platform/AGENTS.md",
    "examples/deerflow-extension-knowledge-center/AGENTS.md",
    "examples/deerflow-extension-lightrag/AGENTS.md",
}


def _load_checker():
    assert CHECKER_PATH.exists(), f"{CHECKER_PATH} must exist"
    spec = importlib.util.spec_from_file_location("deerflow_agent_guidance_check", CHECKER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _files(**overrides: str) -> dict[PurePosixPath, str]:
    files = {PurePosixPath("AGENTS.md"): "# Repository instructions\n"}
    files.update({PurePosixPath(path): text for path, text in overrides.items()})
    return files


def _codes(findings, severity: str | None = None) -> list[str]:
    return [finding.code for finding in findings if severity is None or finding.severity == severity]


def test_normalized_utf8_size_uses_lf_and_counts_non_ascii_bytes() -> None:
    assert checker.normalized_utf8_size("a\r\n中\r") == len("a\n中\n".encode())


def test_single_file_over_hard_limit_is_an_error(tmp_path: Path) -> None:
    files = _files(**{"backend/AGENTS.md": "x" * (checker.AGENT_HARD + 1)})

    assert _codes(checker.analyze(tmp_path, files), "error") == ["AG001"]


def test_single_file_between_soft_and_hard_limit_is_a_warning(tmp_path: Path) -> None:
    files = _files(**{"backend/AGENTS.md": "x" * (checker.AGENT_SOFT + 1)})

    findings = checker.analyze(tmp_path, files)

    assert _codes(findings, "warning") == ["AG001"]
    assert _codes(findings, "error") == []


def test_file_at_soft_limit_has_no_finding(tmp_path: Path) -> None:
    files = _files(**{"backend/AGENTS.md": "x" * checker.AGENT_SOFT})

    assert checker.analyze(tmp_path, files) == []


def test_effective_ancestor_chain_can_fail_when_each_file_is_valid(tmp_path: Path) -> None:
    size = checker.AGENT_HARD - 1
    files = _files(
        **{
            "AGENTS.md": "r" * size,
            "backend/AGENTS.md": "m" * size,
            "backend/app/AGENTS.md": "l" * size,
            "backend/app/gateway/AGENTS.md": "g" * size,
            "backend/app/gateway/routers/AGENTS.md": "o" * size,
        }
    )

    findings = checker.analyze(tmp_path, files)

    assert "AG001" not in _codes(findings, "error")
    assert [finding.path.as_posix() for finding in findings if finding.code == "AG002" and finding.severity == "error"] == ["backend/app/gateway/routers/AGENTS.md"]


def test_legacy_hard_violation_may_shrink_but_may_not_grow(tmp_path: Path) -> None:
    base = _files(**{"AGENTS.md": "x" * (checker.AGENT_HARD + 2)})
    smaller = _files(**{"AGENTS.md": "x" * (checker.AGENT_HARD + 1)})
    grown = _files(**{"AGENTS.md": "x" * (checker.AGENT_HARD + 3)})

    smaller_findings = checker.analyze(tmp_path, smaller, base_files=base)
    grown_findings = checker.analyze(tmp_path, grown, base_files=base)

    assert "AG001" not in _codes(smaller_findings, "error")
    assert "AG001" in _codes(grown_findings, "error")


def test_root_readme_over_hard_limit_is_an_error(tmp_path: Path) -> None:
    findings = checker.analyze(tmp_path, _files(**{"README.md": "x" * (checker.README_HARD + 1)}))

    assert _codes(findings, "error") == ["AG003"]


def test_only_the_root_readme_is_budgeted(tmp_path: Path) -> None:
    files = _files(**{"README.md": "x" * checker.README_SOFT, "backend/README.md": "x" * (checker.README_HARD * 4)})

    assert checker.analyze(tmp_path, files) == []
    assert checker.budgeted_paths(files) == {PurePosixPath("AGENTS.md"), PurePosixPath("README.md")}


def test_oversized_readme_may_shrink_but_may_not_grow(tmp_path: Path) -> None:
    # Fork: sized off the budget rather than upstream's literal 16 KiB, because
    # the fork's README budget is its own (see README_HARD in the checker).
    oversized = checker.README_HARD + 4096
    base = _files(**{"README.md": "x" * oversized})
    smaller = _files(**{"README.md": "x" * (oversized - 1)})
    grown = _files(**{"README.md": "x" * (oversized + 1)})

    assert "AG003" not in _codes(checker.analyze(tmp_path, smaller, base_files=base), "error")
    assert "AG003" in _codes(checker.analyze(tmp_path, grown, base_files=base), "error")


def test_repository_readme_fits_hard_budget() -> None:
    files = {checker.README_PATH: (REPO_ROOT / "README.md").read_text(encoding="utf-8")}

    assert not [finding for finding in checker.analyze(REPO_ROOT, files) if finding.severity == "error"]


def test_discovery_uses_exact_agents_basename() -> None:
    paths = [
        PurePosixPath("AGENTS.md"),
        PurePosixPath("backend/AGENTS.md"),
        PurePosixPath("backend/CLAUDE.md"),
        PurePosixPath("backend/docs/GITHUB_AGENTS.md"),
    ]

    assert checker.guidance_paths(paths) == {
        PurePosixPath("AGENTS.md"),
        PurePosixPath("backend/AGENTS.md"),
    }


def test_repository_has_the_approved_scoped_guidance_shape() -> None:
    actual = {path.as_posix() for path in checker.guidance_paths(checker._worktree_paths(REPO_ROOT))}

    assert actual == EXPECTED_GUIDANCE_PATHS


def test_repository_guidance_has_no_checker_errors() -> None:
    """Run the real repository through the checker the CI job runs.

    The test below asserts each guidance file against its **own** hard budget.
    That is not the same check as the CI job, and the gap is a whole dimension:
    an *effective chain* (root + module + every guide down to a leaf) has its own
    budget, and nothing here used to evaluate it against the real tree — the
    chain tests in this file build synthetic files in a tmp_path, so they prove
    the checker works, not that this repository passes it.

    An upstream merge can therefore add a paragraph to four files that are each
    comfortably inside their own budget and push a leaf's inherited chain over
    the hard limit, with `make test` green and only `agent-guidance` in CI red.
    Observed exactly that way on the 2026-08-30 sync: every per-file budget
    passed while `agents/middlewares/AGENTS.md` inherited 99508 bytes against a
    98304 hard limit.

    This runs `analyze` over the worktree the way the job does, and fails on any
    finding it reports as an error — chain budgets and per-file hard limits
    alike. Warnings are deliberately not failed on: the job runs without
    `--strict-warnings`, so failing here would be stricter than CI, and several
    chains sit legitimately above the soft limit.

    Fork: upstream's `test_repository_guidance_has_no_budget_finding` asserts
    no finding at all, warnings included. Its guides are cut to fit the soft
    budget; the fork's carry fork rules on top, so this keeps the CI job's own
    line (errors fail, warnings do not) instead.
    """
    files = {PurePosixPath(relative): (REPO_ROOT / relative).read_text(encoding="utf-8") for relative in EXPECTED_GUIDANCE_PATHS}

    errors = [finding for finding in checker.analyze(REPO_ROOT, files) if finding.severity == "error"]

    assert not errors, "checker errors (the `agent-guidance` CI job fails on these):\n  " + "\n  ".join(f"{finding.code} {finding.path}: {finding.message}" for finding in errors)


def test_repository_exposes_one_local_and_one_ci_entrypoint() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github" / "workflows" / "lint-check.yml").read_text(encoding="utf-8")

    assert "check-agent-guidance:" in makefile
    assert "scripts/check_agent_guidance.py" in makefile
    assert workflow.count("agent-guidance:") == 1
    assert "fetch-depth: 0" in workflow
    assert "--base-ref" in workflow
    assert "--before" in workflow


def test_editing_guidance_is_gated_locally_before_ci_sees_it() -> None:
    """A pre-commit hook must run the repo-wide checker on any AGENTS.md edit.

    The chain rule makes this failure *non-local*: the error the CI job reports
    names a module the change never touched, because a few paragraphs added to
    the root `AGENTS.md` are inherited by every nested guide. It has now been hit
    twice — the 2026-08-30 sync (see the chain test above) and the change that
    added this hook, where a service-topology row pushed
    `agents/middlewares/AGENTS.md` 564 bytes over the hard limit.

    Both times the tests above existed and both times they were run *before* the
    doc edit that broke them. That is what a hook fixes and a test cannot: this
    one only pins that the hook is still configured, still points at the
    checker, still matches the files that trigger the rule, and still runs
    repo-wide — `pass_filenames: true` would hand the script a file list it does
    not take, and the chain it has to measure spans files the commit did not
    touch.
    """
    import re

    import yaml

    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [hook for repo in config["repos"] for hook in repo.get("hooks", [])]
    hook = next((hook for hook in hooks if hook.get("id") == "agent-guidance"), None)

    assert hook is not None, "the agent-guidance pre-commit hook is gone; an over-budget chain is CI's problem again"
    assert "check_agent_guidance.py" in hook["entry"]
    assert hook.get("pass_filenames") is False, "the chain check must run repo-wide, not on the staged files"
    pattern = hook["files"]
    assert re.search(pattern, "AGENTS.md")
    assert re.search(pattern, "backend/packages/harness/deerflow/agents/AGENTS.md")
    # The checker budgets the root README too (AG003), and only the root one.
    assert re.search(pattern, "README.md")
    assert not re.search(pattern, "backend/README.md")
    assert not re.search(pattern, "docs/AGENTS.md.bak")
