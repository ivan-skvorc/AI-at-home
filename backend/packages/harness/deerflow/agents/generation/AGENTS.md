### Agent Generation (`packages/harness/deerflow/agents/generation/`)

Turns a user's own past work into a *proposal* for a new custom agent. Entered
from `/workspace/agents/generate`; served by
`app/gateway/routers/agent_generation.py`. Gated by `agent_generation.enabled`
**and** `agents_api.enabled` — the second because the accepted draft is created
through `POST /api/agents`, and a draft the user cannot save is a dead end.

**Read-only by design.** The analyze route returns a draft (name, description,
`SOUL.md`) and never writes an agent; creation stays behind an explicit user
action on the existing create route. A hallucinated proposal must not be able to
become a real agent unattended — pinned by
`tests/test_agent_generation_router.py::test_analyze_never_creates_the_agent_itself`.

**Per-source ownership.** `require_permission`'s `owner_check` can only see a
single `thread_id` path parameter, so this route cannot lean on it for a *list*
of sources. Each selected thread is checked with
`ThreadMetaStore.check_access(..., require_existing=True)` (strict: a missing row
denies, rather than reading as "untracked legacy thread, allow" on a route that
returns conversation content), and each scheduled task through
`ScheduledTaskRepo.get(..., user_id=…)`. Message reads also pass `user_id` so the
event store applies its own isolation. Adding a new source kind means adding its
ownership check — there is no decorator doing it for you.

**Bounded prompt.** Every source is digested by `transcript.py` before
concatenation: tool-result bodies are dropped (the calling assistant turn still
names the tools it used, which is the signal without the bytes), only the most
recent `max_messages_per_source` turns survive, and per-message / per-source
character caps apply. The row fetch deliberately asks for *more* rows than the
message cap because digestion discards some — fetching exactly the cap leaves a
busy conversation nearly empty.

**Delimiter escaping.** The prompt wraps content in three block tags, listed in
`transcript.py::BLOCK_TAG_NAMES`: `<source>` (a digest), `<goal>` (the user's
typed intent or revision guidance), and `<draft>` (the proposal being revised).
Every one wraps user-controlled text, so `neutralize_block_delimiters` escapes
all three shapes out of every interpolated value (with
the same whitespace/attribute tolerance as the production blocked-tag pattern) so
a conversation containing `</source>` cannot close the block early and have what
follows read as prompt structure. This is required *here* rather than left to
`InputSanitizationMiddleware`, which only rewrites the lead agent's
`ModelRequest` and never sees a one-shot `run_oneshot_llm` call — the same reason
the summarizer/memory-updater blocks are exempted in
`tests/test_input_sanitization_middleware.py`. Only the delimiter shape is
escaped, not every angle bracket: transcripts carry code, and mangling all of it
would cost the analysis the signal it is reading for. **Adding a block tag to a
prompt means adding it to `BLOCK_TAG_NAMES` and classifying it in that guard** —
the guard fails until you do, which is the point.

**Verdict contract** (`analysis.py`, pure and unit-tested):

- `no_gap` is a **success**, not a failure to produce output. The system prompt
  says out loud that it is the safe answer, because an unnecessary agent dilutes
  the user's roster; `test_build_system_instruction_biases_toward_no_gap` pins
  that the bias survives prompt edits.
- A `propose` verdict with an empty `SOUL.md` is rejected, exactly as
  `setup_agent` rejects one (#3549) — an agent without a soul is unusable, so
  failing lets the user retry instead of leaving a broken draft on screen.
- A proposed name is coerced to `^[A-Za-z0-9-]+$` (models return
  "Weekly Report Writer") and then suffixed `-2`, `-3`… against the user's
  existing agents, so a draft can never 409 on the create route it is destined
  for.
- `skills: None` and `skills: []` mean opposite things in `AgentConfig` (all
  enabled skills vs. none), so an absent or unusable value stays `None`.

**Accounting.** The call is billed to the `agent_generation` aux-usage category
under a dedicated pseudo-thread id. One analysis spans several conversations, so
billing it to any single one would misattribute the cost; the dedicated bucket
gives it its own row on the Spend page instead.

**Four prompt modes, one builder.** `build_system_instruction` takes `has_goal`,
`force_proposal`, and `revising`, because the four shapes share the SOUL.md
structure and the JSON contract and would drift apart as separate strings.

| Mode | Trigger | Verdict menu |
| --- | --- | --- |
| analyze | none | both verdicts, biased to `no_gap` |
| analyze with intent | `goal` | both verdicts — a goal steers, it does not decide |
| forced draft | `force_proposal` | `propose` only |
| revise | `revise_from` | `propose` only, narrow "change nothing else" prompt |

The last two **remove** `no_gap` from the prompt rather than discouraging it, and
`parse_analysis(require_proposal=True)` rejects a `no_gap` reply as a retryable
failure. Both follow from the same rule: the user has already been shown the
overlap and decided, so re-offering the verdict lets the model overrule a decision
that is no longer its to make. What the override must *not* skip is authorization —
ownership is checked before any of this, and
`test_{revision,forced_draft}_still_checks_source_ownership` pin that.

**Ordering inside the user content is load-bearing.** `<draft>`, then `<goal>`,
then the sources. The first two are short and are what the model is being asked to
act on; the sources are bulk evidence. A one-line instruction placed after several
thousand characters of transcript is a one-line instruction that gets ignored.

**A revision keeps the draft's own name.** `existing_names` is passed empty on the
revise path, so `uniquify_agent_name` does not fire. Re-uniquifying on every refine
would rename the agent out from under someone mid-edit, and the name is already in
the form they are looking at.
