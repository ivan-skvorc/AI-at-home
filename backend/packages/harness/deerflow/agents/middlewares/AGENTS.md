### Middleware Chain

ToolProgress fences late results/hint retries by entry epoch, even for one run.

JSON depth failures preserve content and never abort graphs. Unclassified
explicit failures stay `unknown` / recoverable / `try_alternative`; incidental
JSON fields cannot establish auth failure. Producer metadata wins. Keep real
sync/async LocalSandbox tests in `tests/test_tool_result_meta_json_depth.py`;
deep cases must prove parser depth failure or skip.

Browserless artifact.deerflow_http_response.status_code carries X-Response-Code; only non-bool int 400..599 establishes failure, never titles. Direct calls return (content, artifact).

Tool-call argument depth handling is best-effort; see `tests/test_tool_call_json_depth.py`.

Async gate waiters own separate cross-loop futures. Cancel only their signal;
notify outside the state lock. `_await_off_thread` drains started I/O across
repeated cancellation.

Table synopses count nonblank CSV/TSV logical records, excluding the header.
Preserve the recognition sample and 5,000,000 UTF-8-byte guard. Count incrementally;
on parsing or field-limit errors, report an undetermined count rather than a
physical-line or sample total.

Fold selected source in order; preserve required context. Copy document metadata
and direct plaintext; no media decoding/fetching or nested-document traversal.
PII before splitting, budgets before escaping; hooks/history/removal on success.
Chunk/carry/cooldown invariants and tests:
[contract](../../../../../docs/summarization.md).

vLLM compaction counts replayed reasoning. Keep it out of summary input.

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
LLMErrorHandling release identity: `structured_evidence_v1`. Classify model
failures by status/provider fields and exception types; prose is diagnostic.
Status/code-less OpenAI `APIError` gets at most one retry; `APIConnectionError`
(including `APITimeoutError`) keeps `llm_call.retry_max_attempts`.
Adapters and the legacy `langchain_openai:ChatOpenAI` factory must raise
`EmptyModelResponseError` for HTTP-success empty choices before LangChain indexing.

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
