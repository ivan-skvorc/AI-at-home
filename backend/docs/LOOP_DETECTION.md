# Loop detection lifecycle

`LoopDetectionMiddleware` owns call-pattern detection. Its place in the chain
and audit contract are documented in the
[middleware guide](../packages/harness/deerflow/agents/middlewares/AGENTS.md).

## Run-scoped state

Hash histories, frequency windows/counters, and warning-suppression sets
share a `(thread_id, run_id)` key. This gives a fresh budget to each user
run when a compiled graph is cached and reused, while keeping one budget
across repeated graph entries belonging to the same Gateway run (including
hidden goal continuations). `after_agent` clears only transient pending
warnings for its own scope, not those histories; the sync/async
`before_agent` hooks remain topology-preserving no-ops and must not delete a
sibling run's pending warning. Direct LangGraph embedders may omit
`context.run_id`; that fallback is anchored to the invocation's shared
`Runtime.control` object and mapped to an opaque generated ID, because
LangGraph replaces `Runtime` per node and CPython can reuse freed object
addresses. `after_agent` releases the anchor mapping, while the bounded map
covers abnormal exits. The compatibility-named
`max_tracked_threads` limit bounds run scopes, and `reset(thread_id)` clears
every retained run scope for that thread.

## Edits are progress (fork)

A batch containing `write_file` or `str_replace` (`_WORKSPACE_EDIT_TOOLS`)
removes every non-edit entry from the run's hash history and from the
frequency window before it is counted; edit entries stay, tagged with
`_EDIT_HISTORY_PREFIX` so a later edit can tell them apart. A debug session is
edit → run the same test → edit → run it again, and the run command is
byte-identical each time: counted across edits it reached the hard limit on the
fifth fix and forced a final answer mid-task, and `bash` crossed its frequency
warning in any long setup-and-test session. What still stops a run: the same
call repeated with no edit between (reads are not progress), the same edit
re-applied, and edits past their own frequency limit. Edits made through
`bash` (`sed -i`, heredocs) are invisible here, which is one more reason the
repo skills edit through the file tools. `TestWorkspaceEditProgress` in
`backend/tests/test_loop_detection_middleware.py` pins both directions.

## Decision ordering

Loop decisions are severity-first across both detection layers: a warning
candidate never short-circuits frequency accounting for the remaining calls
in an admitted batch. A hard limit can stop scanning immediately because it
rejects the entire batch. Only the selected warning is marked and logged;
hash warnings still precede frequency warnings when neither layer stops the
run. Among simultaneous frequency-warning candidates, the first crossing in
model tool-call order remains selected for compatibility; later calls are
still counted and can warn in a later batch. A frequency warning whose burst
decays within the batch must not leave a stale suppression mark.

`backend/tests/test_loop_detection_middleware.py` covers mixed-tool batches,
window decay, overrides, and sync/async compiled-graph execution.
