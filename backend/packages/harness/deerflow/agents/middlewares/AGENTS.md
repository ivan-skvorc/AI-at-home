### Middleware Chain

Async gate waiters own separate cross-loop futures. Cancel only their signal;
notify outside the state lock. `_await_off_thread` drains started I/O across
repeated cancellation.

Table synopses count nonblank CSV/TSV logical records, excluding the header.
Preserve the recognition sample and 5,000,000 UTF-8-byte guard. Count incrementally;
on parsing or field-limit errors, report an undetermined count rather than a
physical-line or sample total.

Compaction keeps state `SystemMessage`s; transient instructions use request
wrappers, and fully rescued partitions skip compaction. If latest-user rescue
empties an AI/Tool-only window, use `_build_summary_input_text(strategy="last")`;
mixed windows keep normal anchoring and final-message fallback. Budget raw text
before escaping/wrapping; pass `trim_tokens_to_summarize=None` to avoid the
LangChain default.

Todo compaction: [contract](../../../../../docs/summarization.md#todo-reminders).

Delegation verdicts are untrusted: revalidate persisted values, ignore malformed
ones, and treat completed work as reusable evidence rather than acceptance.

On new user turns, DurableContext cancels earlier-run unanswered delegations.
It preserves resumes, same-run continuations, and entries without `run_id`.
A pre-turn reply prevents cancellation; legacy replies without status metadata may
stay `in_progress`. Never infer status from reply text.

Assembly order: `tool_error_handling_middleware.py::_build_runtime_middlewares` (exposed as `build_lead_runtime_middlewares`), then `../lead_agent/agent.py::build_middlewares` appends lead-only entries. Optional entries require their config/runtime condition.

**Message provenance.** Stamp injected/rewritten messages with
`provenance_kwargs()` from `deerflow_extension_api.provenance`: server-owned
`deerflow_content_kind`, `deerflow_producer_kind`, and optional entity ID, even
without observers. Producers: DynamicContext, DurableContext,
SystemMessageCoalescing, ViewImage, SkillActivation. Summarization/Title use
`SystemOperationKind.SUMMARIZATION`/`.TITLE`; summaries enter via DurableContext's
`durable_context_data`, memory recall via DynamicContext's
`dynamic_context_memory`. Memory only queues extraction.

**Self-description.** Configurable middleware exposes JSON-serialisable
`release_policy_parameters()` (`ReleasePolicyProvider`, duck typed). Update
`collect_release_policies()` declarations with behavior; use `canonical_hash`
for long text. Summarization declares enabled task-continuity retention or None;
DurableContext declares normalized skills root, sorted read tools and continuity
switch. History readers, including capture failures, validate persisted metadata
so malformed values cannot abort compaction/model calls.

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
