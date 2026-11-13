# Subagents: fork notes

Reference detail for [AGENTS.md](AGENTS.md), which holds the rules. Each
feature's rationale is in the FORK.md section named beside it.

## Per-call model (FORK.md §22)

`task(model=...)` pins one delegation to a named configured model, for a
Democracy panel or a genuinely model-specific specialist. Its precedence is
absolute and deliberate: it is written into `subagent_model_override` **before**
`apply_routing_policy` is consulted (`tools/builtins/task_tool.py`), so it
outranks the per-thread `subagent_model_name` dropdown *and* stands the
cost-aware routing policy (`routing.py`, FORK.md §15) down entirely. Either of
them winning would run several panelists on one model while the run reports N
independent opinions.

An unknown name **fails that delegation** (`resolve_requested_subagent_model`)
instead of falling back to the inherited model, because a silent substitution is
undetectable in the output, while a failed delegation leaves the rest of the
panel intact. A caller with no readable model catalog cannot adjudicate the name
and accepts it as given.

Upstream's `model_name` / run-context `subagent_model_name` (the user's scoped
choice, authorized by `deerflow.models.selection`) is an override too: it stands
routing down, and `model=` still outranks it.

Pinned by `tests/test_democracy_panel.py::TestPerCallModel`; routing by
`tests/test_model_routing.py`.

## GPU residency for local models (`local_residency.py`, FORK.md §34)

`max_running` is chosen at startup and cannot know which model a dispatch will
use; for a local model the card is the real ceiling. The reservation is acquired
inside the capacity slot in `SubagentExecutor._aexecute`, so every holder of a
reservation is already running and a release is always pending.

There are two limits, both real and not collapsible into one: one resident model
serves `ollama.num_parallel` callers (Ollama never loads a second copy), and
distinct models are bounded by a VRAM ledger. Admission is strict FIFO, because
skipping a waiting large model starves it. A model larger than the card is
charged the whole card, so it runs alone rather than never. Anything the plan
lacks numbers for is ungated rather than guessed.

Pinned by `tests/test_subagent_local_residency.py`.

## Double Plus Ultracode suspends run limits (FORK.md §44)

Context `mode` `double_ultracode` (`run_limits_suspended`, in
`config/run_limit_overrides.py`) makes `LoopDetectionMiddleware` and the token
budget skip their hard stops. `task` subagents inherit the mode with no turn or
time limit: the task tool sets the child's timeout to unlimited and passes
`limits_suspended` to `SubagentExecutor`, which writes the mode into the child's
context and lifts its recursion limit. Pinned by `tests/test_ultracode_mode.py`
and the limit-middleware tests.
