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

**Delimiter escaping.** `SourceTranscript.render()` wraps each digest in a
`<source …>` block, and the body is the user's own text. `transcript.py::
neutralize_source_delimiters` escapes any `<source>` / `</source>` shape (with
the same whitespace/attribute tolerance as the production blocked-tag pattern) so
a conversation containing `</source>` cannot close the block early and have what
follows read as prompt structure. This is required *here* rather than left to
`InputSanitizationMiddleware`, which only rewrites the lead agent's
`ModelRequest` and never sees a one-shot `run_oneshot_llm` call — the same reason
the summarizer/memory-updater blocks are exempted in
`tests/test_input_sanitization_middleware.py`. Only the delimiter shape is
escaped, not every angle bracket: transcripts carry code, and mangling all of it
would cost the analysis the signal it is reading for.

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
