"""The fork's Alembic merge points, and the re-parenting they exist to prevent.

The fork adds its own migration branch (`0019_runs_pricing_snapshot`, FORK.md
§17) beside upstream's, so every sync where upstream extends a revision the
fork has already merged leaves Alembic with **two heads**. `upgrade head`
refuses to run against more than one and the Gateway's schema bootstrap fails
outright, so the collision itself is loud.

What is *silent* is the wrong fix. Re-parenting one branch onto the other's tip
also produces a single head, passes every other test in this suite, and leaves
any database already stamped at the re-parented revision reading as "at head"
with the other branch's DDL never applied — a wrong schema that only surfaces
at query time. This file pins the shape that distinguishes the two: one head,
reached from *both* branches, with every branch root still claiming its
original parent.
"""

from __future__ import annotations

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory

from deerflow.persistence.bootstrap import _MIGRATIONS_DIR, _get_head_revision

# Branch roots, and the parent each must keep. A sync that "resolves" two heads
# by editing one of these values is the failure this file exists to catch.
ORIGINAL_PARENTS = {
    # The fork's pricing-snapshot branch (FORK.md §17) forks from 0018 and must
    # keep doing so: fork databases are stamped here.
    "0019_runs_pricing_snapshot": ("0018_oauth_identity_pg_partial",),
    # Upstream's incarnation revision keeps the id its rollback-floor binary
    # audited, and hangs off 0021 — the revision 0022_merge_pricing_projects
    # had already claimed, which is what split the tree a second time.
    "0019_thread_incarnations": ("0021_batch_acceptance",),
}

# Every leaf the merge points must keep reachable: one per branch tip that
# existed before it was merged.
MERGED_TIPS = ("0019_runs_pricing_snapshot", "0021_batch_acceptance", "0022_scheduled_occurrence_seq")


def _script() -> ScriptDirectory:
    config = AlembicConfig()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return ScriptDirectory.from_config(config)


def test_the_migration_tree_has_exactly_one_head() -> None:
    """Two heads make `alembic upgrade head` refuse and bootstrap fail."""
    assert len(_script().get_heads()) == 1


def test_every_merged_branch_tip_is_an_ancestor_of_the_head() -> None:
    """A merge point that stops covering a branch silently skips its DDL."""
    script = _script()
    head = _get_head_revision()
    reachable = {revision.revision for revision in script.iterate_revisions(head, "base")}

    missing = [tip for tip in MERGED_TIPS if tip not in reachable]
    assert not missing, f"not reachable from head {head!r}: {missing} — a merge revision is missing or stopped naming a branch"


def test_no_branch_root_was_re_parented_to_resolve_a_collision() -> None:
    """The wrong fix for two heads, and the one nothing else fails on."""
    script = _script()
    for revision, expected_parents in ORIGINAL_PARENTS.items():
        actual = script.get_revision(revision).down_revision
        actual_parents = (actual,) if isinstance(actual, str) or actual is None else tuple(actual)
        assert actual_parents == expected_parents, (
            f"{revision} now descends from {actual_parents} rather than {expected_parents}. "
            "Two heads are joined with another merge revision, never by re-parenting a branch: "
            "a database stamped at the old parent would read as being at head with the other branch's DDL never applied."
        )
