# Gates Taxonomy

Canonical gate types for validation checkpoints in any workflow that dispatches subagents, runs review loops, or pauses for human approval. Every validation checkpoint maps to one of these four types — naming them explicitly makes the workflow legible and prevents "what happens when this check fails?" confusion.

Adapted from the GSD (Get Shit Done) project's gates reference (gsd-build/get-shit-done, MIT, Lex Christopherson), via Hermes Agent (Nous Research).

## The four gate types

### 1. Pre-flight gate

**Purpose:** Validates preconditions before starting an operation.

**Behavior:** Blocks entry if conditions are unmet. No partial work is created — bail before anything changes.

**Recovery:** Fix the missing precondition, then retry.

**Examples:**
- The implementation phase checks that the plan file exists before it starts writing code.
- A delegated subagent checks that required environment variables are set before making API calls.
- A commit step checks that tests passed before pushing.

### 2. Revision gate

**Purpose:** Evaluates output quality and routes back for revision if it is insufficient.

**Behavior:** Loops back to the producer with specific feedback, bounded by an iteration cap (typically 3).

**Recovery:** The producer addresses the feedback; the checker re-evaluates. The loop escalates early if the issue count does not decrease between consecutive iterations (stall detection). After the maximum iterations, it escalates to the user unconditionally — never loop forever.

**Examples:**
- A plan reviewer reads a draft plan and returns specific issues; the planner revises; the reviewer re-reads (max 3 cycles).
- A code reviewer checks subagent-produced code against the must-haves and dispatches fixes back to an implementer if any must-have failed.
- A test-coverage checker validates that new tests exercise the new paths; if not, it sends the work back.

### 3. Escalation gate

**Purpose:** Surfaces unresolvable issues to the human for a decision.

**Behavior:** Pauses the workflow, presents options, and waits for human input (`ask_clarification`). Never guesses, never picks a default.

**Recovery:** The human chooses an action; the workflow resumes on the selected path.

**Examples:**
- A revision loop exhausted after 3 iterations.
- A merge conflict during automated cleanup.
- An ambiguous requirement — two reasonable interpretations, and the choice changes the approach.
- A subagent reports "the plan says X but the codebase actually does Y" — the human decides which is right.

### 4. Abort gate

**Purpose:** Terminates the operation to prevent damage or waste.

**Behavior:** Stops immediately, preserves state (checkpoints current progress), and reports the specific reason.

**Recovery:** The human investigates the root cause, fixes it, and restarts from the checkpoint.

**Examples:**
- The context window is critically low during execution (POOR tier, >70%) — abort cleanly rather than produce truncated output.
- A critical dependency becomes unavailable mid-run (network down, API key revoked).
- Unrecoverable filesystem state (disk full, permissions lost).
- A safety invariant is violated (an agent attempted an irreversible destructive action outside the approved scope).

## How to use this

When you design a workflow with validation checkpoints, **name each checkpoint by its gate type explicitly** and answer three questions:

1. **What condition triggers this gate?** (e.g., "plan file missing", "issue count didn't decrease", "context >70%")
2. **What happens when it fails?** (block / loop back / ask the human / abort)
3. **Who resumes, and from where?** (fix the precondition and retry, revise and re-check, human decision, restart from the checkpoint)

Answering these up front means the workflow never hits "what do we do now?" at runtime.

## Example — a review loop with all four gate types

~~~
[Pre-flight] plan.md exists and is non-empty?   → no: bail, ask the user for a plan first
                ↓ yes
[Execute]  subagent implements the task
                ↓
[Revision] reviewer checks against must-haves  → fail: loop back to an implementer (max 3)
                ↓ pass
[Pre-flight] tests pass?                       → no: bail, report failing tests
                ↓ yes
[Commit]
                ↓
(on revision loop exhaustion)
[Escalation] "3 review cycles failed to converge on issue X — pick: force-merge, rewrite the task, abandon"
                ↓ user picks
(on POOR-tier context pressure during the loop)
[Abort] "context at 73%, checkpointing and stopping"
~~~

The vocabulary is small on purpose. Every gate in every workflow should fit one of these four. If you find yourself inventing a fifth, it is probably a revision gate with extra branching, or an escalation gate in disguise.
