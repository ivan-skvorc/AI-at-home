# Fork notes: bundled install, Plus and Double Plus Ultracode

Split out of [`AGENTS.md`](AGENTS.md) to keep it within its guidance budget
(`scripts/check_agent_guidance.py`). The rules there are the entry point; this
is their full contract. Rationale: FORK.md §44, run limits §46.

## Bundled install

Edit `examples/deerflow-extension-workflows`, then copy it over the committed
snapshot uv installs, `backend/extensions/sources/deerflow-extension-workflows`
(`test_bundled_workflows_extension.py`). A relative `storage_path` resolves under
`DEER_FLOW_HOME`; keep `pyproject.toml`'s uv cache-keys.

## Plus Ultracode and Double Plus Ultracode

They live in `ultracode.py` and `delivery.py`.

Read limits only from `ToolContext.run_options`/`plugin_run_options` and clamp to
operator config; never let run options raise a limit. Both `ultracode` and
`double_ultracode` get the brief; only the double mode gets the no-automatic-limits
note and no wall clock (`NO_WALL_CLOCK_SECONDS` in `run_limits`), and only its
children and its result run are started with `context.mode = "double_ultracode"`
so the host lifts the step limit, tool-call limits and token budgets for them.
A Plus or plain workflow must not carry that mode. The result run also gets the run
options back, rebuilt from the record (`result_context`: mode, clamped limits,
`max_minutes` for Plus only), so a follow-up workflow launched from it keeps them;
on that turn skip the brief and keep the result note plus, for Double, the
limits-off line. The record's `model` and `internet_enabled: false` come only from
the launching run's options (anything malformed is ignored, never an error); every
child and the result run default to them, and a step's own `model` wins. An inherited
model the host refuses is dropped from the record, never fatal (`start_child`, `deliver_once`).

Keep the brief behind the mode option and the result note behind the host-stamped
`EXTENSION_MESSAGE_ORIGIN_KEY` for this namespace only. Delivery is exactly once:
idempotency key `workflow-result:<run>`, deterministic message text, state in
`workflow_deliveries` (never the lease-fenced record), busy threads retried, never
interrupted; cancelled runs are skipped. Schema re-asks persist the new attempt
identity before admission; an uncertain re-ask needs reconciliation. A 402 is a
definitive pre-admission rejection for a child; on the result run it is waited out
like a busy conversation. Workspace copy/merge only through AgentRuns,
gated by `shared_workspace`; merge results stay bounded in the row.

`max_minutes` (Plus only) clamps to `timeout_seconds` into the record's limits; the supervisor
reads the record, never the config, for wall time. `RUN_NOTE` (unattended, bounded
answer) goes on ultracode children only, so plain tasks stay byte-identical. A busy
conversation is waiting, not a failed delivery attempt (bounded by BUSY_WAIT_SECONDS).

The host shows the model one fixed sentence for anything a tool raises, so the
`launch_workflow` tool returns a refusal as `{launched: false, error}`; the browser
action still raises. `inspect_workflow_step` returns only `{step_id, status, attempt,
output}` of a completed agent step, a refusal as `{found: false, error}`; never expose
`get_step` as a tool (its row holds evidence and file hashes). At 100 retained records
`create` drops the owner's oldest completed, failed or cancelled record with no pending
delivery, never another terminal state; PostgreSQL also skips what delete refuses
(shared `_held`/`_discard`).

The brief names the allowed `agents` and the `shared_workspace` rule (read both with
`.get`; tests build the middleware without them) and the 12,000-byte result limit.
Double Plus lifts host limits only: the workflow's stops (README, Limits and status)
still end a run, so `DOUBLE_LIMITS` says what still applies and promises no ending.
Brief and tool-description text spends the 12,000-token fixed request pinned by
backend/tests/test_context_fit_critical.py (run it with this source first on
PYTHONPATH); cut brief words to pay for new ones. A small window sees only a tool
description's opening sentences (280 characters), so limits belong in the brief too.

Tests: backend/tests/test_ultracode_mode.py (FORK.md §46 covers the run limits).
