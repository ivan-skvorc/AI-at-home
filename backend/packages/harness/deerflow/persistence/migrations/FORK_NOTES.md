# Schema migrations: fork notes

Reference detail for [AGENTS.md](AGENTS.md), which holds the rules. Why the fork
has a migration branch at all is FORK.md §17; how each sync met it is in FORK.md,
*Upstream sync*.

## Merge points

The fork's only schema revision, `0019_runs_pricing_snapshot`, branches off
`0018_oauth_identity_pg_partial`. Upstream keeps extending a revision that a
merge point has already claimed, which puts the tree back on two heads, so each
row below joins the fork's previous head to upstream's tip at that sync. Every
merge is a no-op revision; none re-parents a branch.

| Merge revision | Fork parent | Upstream parent |
| --- | --- | --- |
| `0022_merge_pricing_projects` | `0019_runs_pricing_snapshot` | `0021_batch_acceptance` |
| `0023_merge_pricing_scheduler` | `0022_merge_pricing_projects` | `0022_scheduled_occurrence_seq` |
| `0024_merge_preferences` | `0023_merge_pricing_scheduler` | `0023_user_preferences` |
| `0027_merge_preferences_mcp_tasks` | `0024_merge_preferences` | `0026_mcp_task_lease_tokens` |
| `0031_merge_prefs_notifications` | `0027_merge_preferences_mcp_tasks` | `0030_notification_claim_tokens` |
| `0038_merge_prefs_summaries` | `0031_merge_prefs_notifications` | `0037_project_document_summaries` |
| `0044_merge_prefs_im_notices` | `0038_merge_prefs_summaries` | `0043_runtime_im_notices` |
| `0048_merge_prefs_oauth_tokens` | `0044_merge_prefs_im_notices` | `0047_mcp_oauth_tokens` |
| `0049_merge_prefs_ext_leases` | `0048_merge_prefs_oauth_tokens` | `0048_extension_execution_leases` |
| `0052_merge_prefs_run_inputs` | `0049_merge_prefs_ext_leases` | `0051_merge_run_inputs_fencing` |
| `0053_merge_prefs_batch_cont` | `0052_merge_prefs_run_inputs` | `0052_batch_continuation` |
| `0055_merge_prefs_project_mem` (head) | `0053_merge_prefs_batch_cont` | `0054_project_memory` |

`0051_merge_run_inputs_fencing` is upstream's own merge of `0049_run_inputs` and
the `0049_run_producer_fencing` → `0050_history_seed_authority` branch. Upstream
reached `0054_project_memory` through `0053_tool_approvals`, off
`0052_batch_continuation`.

## Adding the next merge point

A sync that leaves two heads fails
`tests/test_migration_merge_points.py::test_the_migration_tree_has_exactly_one_head`,
and the Gateway refuses to bootstrap.

1. Add a no-op revision in `versions/` whose `down_revision` names the fork's head
   and upstream's new tip. Keep the ID within 32 characters
   (`test_every_revision_id_fits_postgres_version_column`).
2. In `tests/test_migration_merge_points.py`, add upstream's new branch root with
   its original parent to `ORIGINAL_PARENTS`, and upstream's tip to
   `MERGED_TIPS`.
3. Point the per-revision tests that assert the head at the new merge ID. Tests
   adapted at an earlier sync name the previous fork head, and new upstream tests
   name upstream's tip, so grep `backend/tests` for both IDs.
4. Update the head line in [AGENTS.md](AGENTS.md), the table above and FORK.md's
   sync history.
