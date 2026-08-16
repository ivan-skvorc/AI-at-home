"""Tests for scripts/upstream_sync.py — the automated upstream-merge PR body.

"Lags upstream" is a real reason to pick upstream over this fork, and it
compounds: the longer a sync is deferred, the larger the merge and the more
likely the fork's UI wiring silently breaks. The workflow turns a manual chore
into a standing PR; this module owns the part worth unit-testing — turning
FORK.md's post-sync checklist into the PR body, so the checklist is
single-sourced instead of copied into a workflow and left to rot.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "upstream_sync.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "upstream-sync.yml"


def _load_script():
    spec = importlib.util.spec_from_file_location("upstream_sync", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sync = _load_script()

FORK_MD = """# FORK.md

### Post-sync feature checklist

First, the mechanical gates:

- [ ] No leftover conflict markers: `git grep -nE '...'` returns nothing.
- [ ] Backend: `make lint && make test`.
- [ ] Frontend: `pnpm format && pnpm check && pnpm test`.

Then confirm each fork feature end-to-end:

| Fork feature | How to verify it survived the merge |
| --- | --- |
| **Ollama auto-populate** (§1) | Run the dry-run and check the entries. |
| **Cost overview** (§7) | Open the header and confirm a green figure. |

**Integration points that tend to need a hand**: the AIO sandbox provider.

## PDF and Office document support
"""


# ---------------------------------------------------------------------------
# Parsing FORK.md
# ---------------------------------------------------------------------------


class TestParseChecklist:
    def test_extracts_the_mechanical_gates(self):
        checklist = sync.parse_post_sync_checklist(FORK_MD)
        assert len(checklist.mechanical) == 3
        assert any("conflict markers" in item for item in checklist.mechanical)

    def test_extracts_the_feature_table_rows(self):
        checklist = sync.parse_post_sync_checklist(FORK_MD)
        assert [name for name, _ in checklist.features] == ["**Ollama auto-populate** (§1)", "**Cost overview** (§7)"]

    def test_the_table_header_and_separator_are_not_rows(self):
        checklist = sync.parse_post_sync_checklist(FORK_MD)
        assert all("Fork feature" not in name for name, _ in checklist.features)
        assert all(set(name.strip()) != {"-"} for name, _ in checklist.features)

    def test_the_scan_stops_at_the_next_top_level_section(self):
        checklist = sync.parse_post_sync_checklist(FORK_MD)
        assert all("PDF" not in name for name, _ in checklist.features)

    def test_the_real_fork_md_parses(self):
        checklist = sync.parse_post_sync_checklist((REPO_ROOT / "FORK.md").read_text(encoding="utf-8"))
        assert len(checklist.mechanical) >= 5
        assert len(checklist.features) >= 15
        # The checklist is the point of the PR body; an empty parse would ship
        # a PR that silently asks for nothing.
        assert all(name.strip() for name, _ in checklist.features)


# ---------------------------------------------------------------------------
# PR body
# ---------------------------------------------------------------------------


def gates(**overrides):
    base = {"conflict_markers": "pass", "backend_lint": "pass", "backend_test": "pass", "frontend_check": "pass", "uv_lock": "pass"}
    base.update(overrides)
    return base


class TestRenderPrBody:
    def test_clean_merge_renders_every_gate_as_passing(self):
        body = sync.render_pr_body(checklist=sync.parse_post_sync_checklist(FORK_MD), gates=gates(), conflicts=[], upstream_sha="abc1234", commit_count=12)
        assert "abc1234" in body
        assert "12 upstream commit" in body
        assert body.count("✅") >= 5
        assert "merge conflict" not in body.lower()

    def test_every_feature_row_becomes_an_unchecked_box(self):
        body = sync.render_pr_body(checklist=sync.parse_post_sync_checklist(FORK_MD), gates=gates(), conflicts=[], upstream_sha="abc1234", commit_count=1)
        assert body.count("- [ ]") >= 2
        assert "Ollama auto-populate" in body
        assert "Open the header and confirm a green figure." in body

    def test_a_failing_gate_is_marked_and_not_hidden(self):
        body = sync.render_pr_body(checklist=sync.parse_post_sync_checklist(FORK_MD), gates=gates(backend_test="fail"), conflicts=[], upstream_sha="abc1234", commit_count=3)
        assert "❌" in body
        assert "backend" in body.lower()

    def test_a_skipped_gate_is_distinct_from_a_failing_one(self):
        body = sync.render_pr_body(checklist=sync.parse_post_sync_checklist(FORK_MD), gates=gates(frontend_check="skip"), conflicts=[], upstream_sha="abc", commit_count=1)
        assert "⏭️" in body or "skipped" in body.lower()
        assert "❌" not in body

    def test_conflicts_are_flagged_at_the_top_with_every_path(self):
        body = sync.render_pr_body(
            checklist=sync.parse_post_sync_checklist(FORK_MD),
            gates=gates(conflict_markers="skip", backend_test="skip"),
            conflicts=["backend/app/gateway/services.py", "frontend/src/components/workspace/input-box.tsx"],
            upstream_sha="abc1234",
            commit_count=40,
        )
        first_section = body.split("##")[1]
        assert "conflict" in first_section.lower()
        assert "services.py" in body
        assert "input-box.tsx" in body

    def test_a_conflicted_pr_says_it_is_not_mergeable_as_is(self):
        body = sync.render_pr_body(checklist=sync.parse_post_sync_checklist(FORK_MD), gates=gates(), conflicts=["a.py"], upstream_sha="abc", commit_count=1)
        assert "do not merge" in body.lower() or "not mergeable" in body.lower()

    def test_the_body_says_merge_never_rebase(self):
        body = sync.render_pr_body(checklist=sync.parse_post_sync_checklist(FORK_MD), gates=gates(), conflicts=[], upstream_sha="abc", commit_count=1)
        assert "rebase" in body.lower()

    def test_the_integration_hint_paths_are_carried_over(self):
        body = sync.render_pr_body(checklist=sync.parse_post_sync_checklist(FORK_MD), gates=gates(), conflicts=["backend/app/gateway/services.py"], upstream_sha="abc", commit_count=1)
        assert "AIO sandbox provider" in body

    def test_workflow_file_changes_are_called_out(self):
        body = sync.render_pr_body(
            checklist=sync.parse_post_sync_checklist(FORK_MD),
            gates=gates(),
            conflicts=[],
            upstream_sha="abc",
            commit_count=1,
            workflow_files=[".github/workflows/backend-unit-tests.yml"],
        )
        assert "GITHUB_TOKEN" in body
        assert "backend-unit-tests.yml" in body

    def test_the_body_stays_within_github_limits(self):
        checklist = sync.parse_post_sync_checklist((REPO_ROOT / "FORK.md").read_text(encoding="utf-8"))
        body = sync.render_pr_body(checklist=checklist, gates=gates(), conflicts=[], upstream_sha="abc", commit_count=1)
        # GitHub rejects PR bodies over 65536 characters; the real feature table
        # is long, so this is a live constraint, not a theoretical one.
        assert len(body) < 65536, len(body)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:
    def test_writes_a_body_file(self, tmp_path, capsys):
        gates_file = tmp_path / "gates.json"
        gates_file.write_text(json.dumps(gates()), encoding="utf-8")
        out = tmp_path / "body.md"
        code = sync.main(["--gates", str(gates_file), "--upstream-sha", "deadbee", "--commit-count", "7", "--output", str(out)])
        capsys.readouterr()
        assert code == 0
        assert "deadbee" in out.read_text(encoding="utf-8")

    def test_conflicts_file_is_read_line_by_line(self, tmp_path, capsys):
        conflicts = tmp_path / "conflicts.txt"
        conflicts.write_text("backend/a.py\nfrontend/b.tsx\n\n", encoding="utf-8")
        out = tmp_path / "body.md"
        sync.main(["--conflicts", str(conflicts), "--upstream-sha", "abc", "--output", str(out)])
        capsys.readouterr()
        body = out.read_text(encoding="utf-8")
        assert "backend/a.py" in body and "frontend/b.tsx" in body

    def test_a_missing_gates_file_degrades_to_unknown_rather_than_crashing(self, tmp_path, capsys):
        out = tmp_path / "body.md"
        assert sync.main(["--gates", str(tmp_path / "nope.json"), "--upstream-sha", "abc", "--output", str(out)]) == 0
        capsys.readouterr()
        assert out.exists()


# ---------------------------------------------------------------------------
# The workflow itself
# ---------------------------------------------------------------------------


class TestWorkflow:
    def test_the_workflow_exists_and_is_valid_yaml(self):
        import yaml

        assert WORKFLOW_PATH.exists()
        data = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
        # `on` is parsed as the boolean True by YAML 1.1 — hence the odd key.
        triggers = data.get("on") or data.get(True)
        assert "schedule" in triggers
        assert "workflow_dispatch" in triggers

    def test_the_workflow_never_force_pushes(self):
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        assert "--force" not in text
        assert "-f origin" not in text
        assert "push --force-with-lease" not in text

    def test_the_workflow_merges_rather_than_rebases(self):
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        assert "git merge" in text
        assert "git rebase" not in text

    def test_a_conflicted_merge_still_opens_a_pr(self):
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        # The conflict path is exactly when a human most needs to know early,
        # so the PR step must not be gated on the merge succeeding.
        assert "if: always()" in text or "continue-on-error" in text
