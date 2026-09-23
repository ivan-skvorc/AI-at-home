### Middleware Chain

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
Any reply prevents cancellation; legacy replies without status metadata may
stay `in_progress`. Never infer status from reply text.

Assembly order: `tool_error_handling_middleware.py::_build_runtime_middlewares` (exposed as `build_lead_runtime_middlewares`), then `../lead_agent/agent.py::build_middlewares` appends lead-only entries. Optional entries require their config/runtime condition.

**Message provenance.** At injection/rewrite, always stamp `additional_kwargs`
via `deerflow_extension_api.provenance.provenance_kwargs()`:
`deerflow_content_kind`, `deerflow_producer_kind`, optional
`deerflow_producer_entity_id`. All are server-owned inbound metadata; stamp even
without observers, since downstream cannot recover producers. Producers:
DynamicContext (reminder/memory), DurableContext (contract/data),
SystemMessageCoalescing, ViewImage, SkillActivation. Summarization/Title use
`SystemOperationKind.SUMMARIZATION`/`.TITLE` model-call attribution; summaries
enter via DurableContext's stamped `durable_context_data`, not separate
messages. Memory only queues extraction; recall uses DynamicContext's
`dynamic_context_memory` stamp.

**Middleware self-description.** Behaviour-configurable middleware implements
`release_policy_parameters() -> dict[str, object]` (duck-typed
`deerflow_extension_api.release.ReleasePolicyProvider`, no base class).
Use JSON-serialisable values and `canonical_hash` for long text, not prompt
copies. `collect_release_policies()` gathers stack declarations; update them
alongside every behaviour-affecting field.
Summarization declares its enabled `task_continuity` retention settings (else
`None`); DurableContext declares its normalized skills root, sorted read-tool
names and continuity switch, so each capture/injection policy affects assembly
identity without private-field probing. Continuity history readers share shape
validation, so malformed persisted metadata cannot abort compaction or a model
call.

**Removing tool calls.** Use `clone_ai_message_with_tool_calls`, not a bare
`tool_calls` update: adapters resend stale `content` tool-call blocks, which
strict providers reject.

**Shared runtime base** (`build_lead_runtime_middlewares`; subagents reuse most of this via `build_subagent_runtime_middlewares`):

The per-middleware catalogue — all 37 entries, their order, and the invariants
each one carries — is reference material long enough to dominate this file's
guidance budget, so it lives beside it in [`CHAIN.md`](CHAIN.md). Read it before
adding, reordering or removing a middleware: position in the chain *is* the
contract for most of them.
