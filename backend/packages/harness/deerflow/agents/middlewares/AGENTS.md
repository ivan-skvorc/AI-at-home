### Middleware Chain

Tool-result JSON analysis is best-effort: parser depth failures must preserve the
original content and must not abort the graph. Explicit error results fall back
to `unknown` / recoverable / `try_alternative`, without classifying incidental
JSON fields as auth failures. Producer metadata remains authoritative. Keep
depth regressions in `tests/test_tool_result_meta_json_depth.py`, including real
LocalSandbox reads through both synchronous and asynchronous agent graphs.
Deep graph cases must establish a real parser depth failure or report a skip.

Tool-call argument depth handling is best-effort; see `tests/test_tool_call_json_depth.py`.

Async gate waiters own separate cross-loop futures. Cancel only their signal;
notify outside the state lock. `_await_off_thread` drains started I/O across
repeated cancellation.

Table synopses count nonblank CSV/TSV logical records, excluding the header.
Preserve the recognition sample and 5,000,000 UTF-8-byte guard. Count incrementally;
on parsing or field-limit errors, report an undetermined count rather than a
physical-line or sample total.

Keep state `SystemMessage`s; inject transient instructions via request wrappers.
Skip fully rescued partitions. Fold all raw source in order without human
anchoring. PII-redact before splitting; budget before escaping. Generated carry:
marked head/tail within half the raw budget; at most 64 chunks/pass. Commit
hooks/history/removal only on success. Cap breaches use a bounded process-local
5m cooldown across builds for the same user/thread/executor/window/policy;
smaller source or changed policy retries immediately. See the linked contract.
`trim_tokens_to_summarize=None` uses one unbounded step.

Todo compaction: [contract](../../../../../docs/summarization.md#todo-reminders).

Delegation verdicts are untrusted: revalidate persisted values, ignore malformed
ones, and treat completed work as reusable evidence rather than acceptance.

On new user turns, DurableContext cancels earlier-run unanswered delegations.
It preserves resumes, same-run continuations, and entries without `run_id`.
A pre-turn reply prevents cancellation; legacy replies without status metadata may
stay `in_progress`. Never infer status from reply text.

Assembly order: `tool_error_handling_middleware.py::_build_runtime_middlewares` (exposed as `build_lead_runtime_middlewares`), then `../lead_agent/agent.py::build_middlewares`. Optional entries require their config/runtime condition.

Config-declared middleware uses `configured_extensions.py`; the lead and subagent
builders pass their own required keyword-only `scope` (no implicit lead default).
Optional `apply_to: both | lead | subagent`
defaults to both, including legacy strings. Filter before reflection/construction;
preserve selected entry order and create fresh instances per build. This fixed-slot
selector does not alter packaged extensions' `AgentScope` or placement contract.

**Message provenance.** Injected/rewritten messages use
`deerflow_extension_api.provenance.provenance_kwargs()`: server-owned
`deerflow_content_kind`, `deerflow_producer_kind`, optional entity ID, even
without observers. Producers: DynamicContext, DurableContext,
SystemMessageCoalescing, ViewImage, SkillActivation. Summarization/Title use
`SystemOperationKind.SUMMARIZATION`/`.TITLE`; summaries enter through
DurableContext's `durable_context_data`, recall through DynamicContext's
`dynamic_context_memory`; Memory only queues extraction. Request-only rewrites
need no stamps (InputSanitization, DanglingToolCall, ModelContentCompatibility).

**Self-description.** Configurable middleware: JSON-safe
`release_policy_parameters()` (`ReleasePolicyProvider`, duck typed). Update
`collect_release_policies()` with behavior; hash long text with `canonical_hash`.
Summarization: enabled task-continuity retention or None. DurableContext:
normalized skills root, sorted read tools, continuity switch. All history readers,
including capture failures, validate persisted metadata; malformed values must
not abort compaction/model calls.

**Removing tool calls.** Use `clone_ai_message_with_tool_calls`, not a bare
`tool_calls` update: adapters resend stale `content` tool-call blocks, which
strict providers reject.

Read marks bind to request `tool_call_id`, including `Command` results.
No match: skip inspection, log ID. Tests: `test_read_mark_tool_call_correlation.py`.

**Shared runtime base** (`build_lead_runtime_middlewares`; subagents reuse most of this via `build_subagent_runtime_middlewares`):

The per-middleware catalogue — all 39 entries, their order, and the invariants
each one carries — is reference material long enough to dominate this file's
guidance budget, so it lives beside it in [`CHAIN.md`](CHAIN.md). Read it before
adding, reordering or removing a middleware: position in the chain *is* the
contract for most of them.
