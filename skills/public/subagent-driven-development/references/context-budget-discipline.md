# Context Budget Discipline

Practical rules for keeping the lead agent's context lean when dispatching subagents or reading large artifacts. Use them whenever a multi-step loop will consume significant context — plan execution, subagent orchestration, review pipelines, multi-file refactors.

Adapted from the GSD (Get Shit Done) project's context-budget reference (gsd-build/get-shit-done, MIT, Lex Christopherson), via Hermes Agent (Nous Research).

## Universal rules

Every workflow that dispatches subagents or reads significant content follows these:

1. **Point subagents at skill files instead of pasting them.** A subagent can `read_file` the skill's SKILL.md under /mnt/skills/public/ itself; pasting a whole skill into its prompt doubles the cost.
2. **Never inline large files into subagent prompts.** Tell the subagent the absolute path under /mnt/user-data/ and let it read the file. The subagent gets the full content; your context stays lean.
3. **Read depth scales with the context window.** See the table below.
4. **Delegate heavy work to subagents.** The lead routes; it doesn't execute.
5. **Warn the user proactively** when you've consumed significant context ("Context is getting heavy — consider checkpointing progress before we continue").

## Read depth by context window

Use the serving model's actual context window. If you don't know it, assume the smaller row — err toward leanness.

| Context window | Subagent output | Summary files | Verification files | Plans for other phases |
|----------------|-----------------|---------------|--------------------|------------------------|
| < 500K (e.g. 200K, or a 32K local model) | Verdict/summary only | Summary only | Summary only | Current phase only |
| >= 500K (1M models) | Full body permitted | Full body permitted | Full body permitted | Current phase only |

"Verdict/summary only" means: read enough to see the final status, verdict or conclusion. If a subagent wrote a 3000-line debug log, read the summary section it produced, not the log.

## Four-tier degradation model

Watch your context usage and shift behavior as you climb the tiers. The point is to notice *before* you hit the wall, not when responses start truncating.

| Tier | Usage | Behavior |
|------|-------|----------|
| **PEAK** | 0 – 30% | Full operations. Read bodies, dispatch several subagents in parallel, inline results freely. |
| **GOOD** | 30 – 50% | Normal operations. Prefer summary reads. Delegate aggressively. |
| **DEGRADING** | 50 – 70% | Economize. Summary-only reads, minimal inlining, **warn the user** about the budget. |
| **POOR** | 70%+ | Emergency mode. **Checkpoint progress immediately** (update `write_todos`, write a progress note to the workspace). No new reads unless critical. Finish the current task and stop cleanly. |

## Early warning signs (before the thresholds fire)

Quality degrades *gradually* before hard limits hit. Watch for:

- **Silent partial completion.** A subagent claims done but the implementation is incomplete. Self-checks catch file existence, not semantic completeness. Always verify subagent output against the plan's must-haves, not just "did a file appear?"
- **Increasing vagueness.** An agent starts using phrases like "appropriate handling" or "standard patterns" instead of specific code. This is context pressure showing up before budget warnings fire.
- **Skipped protocol steps.** An agent omits steps it would normally follow. If the success criteria have 8 items and the report covers 5, suspect context pressure, not "the agent decided 5 was enough."

When these signs appear, checkpoint the work and hand off to a fresh subagent.

## Fundamental limitation

When you orchestrate, you cannot verify the semantic correctness of subagent output — only structural completeness ("did the file appear?", "does the test pass?"). Semantic verification requires either running the code yourself or delegating a review pass to another fresh subagent.

**Mitigation:** in every task you delegate, include explicit must-have truths the subagent must confirm in its report (for example, "confirm your test actually exercises X, not just that X was imported"), and attach checkable `acceptance_criteria` such as `tests_passed:<command>`. The subagent re-asserting concrete facts is evidence; a vague summary is not.
