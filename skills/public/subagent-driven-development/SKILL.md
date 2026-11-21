---
name: subagent-driven-development
description: Use this skill when executing a multi-task implementation plan with subagents enabled (Ultra mode) - a fresh task subagent implements each task, then a spec-compliance review and a code-quality review must pass before the next task starts.
license: MIT
author: Hermes Agent (Nous Research), adapted from obra/superpowers and gsd-build/get-shit-done; adapted for DeerFlow
version: 1.1.0
metadata:
  tags: [delegation, subagent, implementation, workflow]
  related-skills: [requesting-code-review, test-driven-development, systematic-debugging]
  upstream: NousResearch/hermes-agent optional-skills/software-development/subagent-driven-development (aeb5a07)
---

# Subagent-Driven Development

## Overview

Execute implementation plans by dispatching a fresh subagent per task, with a systematic two-stage review.

**Core principle:** Fresh subagent per task + two-stage review (spec, then quality) = high quality, fast iteration.

## Requirements

This skill needs the `task` tool, which exists only when subagents are enabled (Ultra mode). Subagents cannot call `task` themselves, so only the lead agent runs this loop. Without the `task` tool, execute the plan yourself task by task with the `test-driven-development` skill, and run the `requesting-code-review` skill after each task as the review gate.

Know these DeerFlow facts before dispatching:

- **Subagents share the thread workspace** (/mnt/user-data/workspace/). Never run two implementers at once on tasks that touch the same files, and tell reviewers not to edit anything.
- **A subagent cannot ask you questions mid-task** (it has no `ask_clarification`). Resolve ambiguities before dispatch — with the user if needed — and tell the implementer to stop and report open questions instead of guessing.
- **The default context is isolated**: the subagent sees only your prompt, so the prompt must carry the full task text and scene-setting context.
- **One response can carry only as many `task` calls as the concurrency limit** your subagent instructions state; extra calls are silently dropped. The per-run total is capped too, and each task here costs up to three delegations (implementer, spec reviewer, quality reviewer), so check the plan fits before starting.
- **Reports are self-reports.** Attach `acceptance_criteria` with checkable forms such as `tests_passed:<command>` and `file:<path> exists`; the result then carries a deterministic checklist instead of only the subagent's word.

## When to Use

- You have an implementation plan (from the user, or one you wrote and the user approved)
- Tasks are mostly independent
- Quality and spec compliance matter
- You want review between tasks

Compared with executing everything yourself: each task gets fresh context (no confusion from accumulated state), review catches issues early, and quality checks stay consistent across tasks.

## The Process

### 1. Read and Parse the Plan

Read the plan file ONCE with `read_file`. Extract ALL tasks with their full text and context up front, and record them with `write_todos` (available in Pro and Ultra mode):

~~~text
write_todos:
  - Create User model with email field          (pending)
  - Add password hashing utility                (pending)
  - Create login endpoint                       (pending)
~~~

**Key:** don't make subagents read the plan file — paste the full task text into each prompt.

### 2. Per-Task Workflow

For EACH task in the plan:

#### Step 1: Dispatch the Implementer

Call `task` with `subagent_type: general-purpose`, a short `description`, and a complete prompt:

~~~text
Implement Task 1: Create User model with email and password_hash fields.

TASK FROM PLAN:
- Create: src/models/user.py
- Add a User class with email (str) and password_hash (str) fields
- Use bcrypt for password hashing
- Include __repr__ for debugging

FOLLOW TDD (/mnt/skills/public/test-driven-development/SKILL.md):
1. Write a failing test in tests/models/test_user.py
2. Run: cd /mnt/user-data/workspace/project && pytest tests/models/test_user.py -v  (verify FAIL)
3. Write the minimal implementation
4. Run the same command (verify PASS)
5. Run: cd /mnt/user-data/workspace/project && pytest tests/ -q  (verify no regressions)

PROJECT CONTEXT:
- Python 3.11, Flask app in src/app.py; existing models in src/models/
- Tests use pytest, run from the project root; bcrypt is in requirements.txt

If anything in the task is ambiguous, stop and report the question instead of guessing.
Report the files you changed and the final test output.
~~~

with these `acceptance_criteria`:

~~~text
file:/mnt/user-data/workspace/project/src/models/user.py exists
tests_passed:cd /mnt/user-data/workspace/project && pytest tests/models/test_user.py -v
~~~

Spell the `tests_passed` command exactly as the prompt tells the subagent to run it; a different spelling comes back UNVERIFIED.

#### Step 2: Dispatch the Spec Compliance Reviewer

After the implementer completes, verify against the original spec with a fresh `general-purpose` subagent:

~~~text
Review whether the implementation matches the spec. Do not edit any file.

ORIGINAL TASK SPEC:
- Create src/models/user.py with a User class
- Fields: email (str), password_hash (str)
- Use bcrypt for password hashing
- Include __repr__

CHECK:
- [ ] All requirements from the spec implemented?
- [ ] File paths match the spec?
- [ ] Function signatures match the spec?
- [ ] Behavior matches what is expected?
- [ ] Nothing extra added (no scope creep)?

OUTPUT: PASS, or a list of specific spec gaps to fix.
~~~

**If spec issues are found:** have them fixed, then re-run the spec review. Continue only when spec-compliant.

#### Step 3: Dispatch the Code Quality Reviewer

After spec compliance passes:

~~~text
Review code quality for the Task 1 implementation. Do not edit any file.

FILES TO REVIEW:
- src/models/user.py
- tests/models/test_user.py

CHECK:
- [ ] Follows project conventions and style?
- [ ] Proper error handling?
- [ ] Clear variable and function names?
- [ ] Adequate test coverage?
- [ ] No obvious bugs or missed edge cases?
- [ ] No security issues?

OUTPUT FORMAT:
- Critical Issues: [must fix before proceeding]
- Important Issues: [should fix]
- Minor Issues: [optional]
- Verdict: APPROVED or REQUEST_CHANGES
~~~

**If quality issues are found:** have them fixed, re-review. Continue only when approved.

#### Step 4: Mark Complete

Update the item with `write_todos` (status `completed`) and move to the next task.

### 3. Final Review

After ALL tasks are complete, dispatch a final integration reviewer: do all components work together, are there inconsistencies between tasks, do all tests pass, is it ready to merge? Use the rubric of the `requesting-code-review` skill.

### 4. Verify Yourself

Do not rely on the reviewers alone. Run the checks with `bash`:

~~~bash
cd /mnt/user-data/workspace/project && pytest tests/ -q
cd /mnt/user-data/workspace/project && git diff --stat
~~~

Commit only if the user asked for commits.

## Task Granularity

**Each task = 2-5 minutes of focused work.**

**Too big:** "Implement user authentication system".

**Right size:** "Create User model with email and password fields", "Add password hashing function", "Create login endpoint", "Add JWT token generation", "Create registration endpoint".

## Red Flags — Never Do These

- Start implementation without a plan
- Skip reviews (spec compliance OR code quality)
- Proceed with unfixed critical or important issues
- Dispatch multiple implementation subagents for tasks that touch the same files
- Make a subagent read the plan file (provide the full text in the prompt instead)
- Skip scene-setting context (the subagent needs to understand where the task fits)
- Leave a reported question unanswered and redispatch anyway
- Accept "close enough" on spec compliance
- Skip review loops (reviewer found issues → fix → review again)
- Let the implementer's self-review replace an actual review (both are needed)
- **Start the code quality review before spec compliance is PASS** (wrong order)
- Move to the next task while either review has open issues

## Handling Issues

### If a Subagent Reports Questions

Answer them clearly and completely (asking the user if you can't), add any missing context, and redispatch with the answers in the prompt. Don't rush it into implementation.

### If a Reviewer Finds Issues

A fix subagent (or a fresh implementer) fixes them, the reviewer reviews again, and you repeat until approved. Don't skip the re-review. Cap the loop at 3 rounds; if the issue count stops falling, escalate to the user.

### If a Subagent Fails a Task

Dispatch a new fix subagent with specific instructions about what went wrong, naming only the unmet condition. Don't fix it by hand in the lead conversation (context pollution).

## Efficiency Notes

**Why a fresh subagent per task:** it prevents context pollution from accumulated state; each subagent gets clean, focused context with no confusion from prior tasks' code or reasoning.

**Why a two-stage review:** the spec review catches under- and over-building early; the quality review ensures the implementation is well built; together they catch issues before they compound across tasks.

**Cost trade-off:** more subagent invocations (implementer + 2 reviewers per task), but issues are caught early, which is cheaper than debugging compounded problems later.

## Integration with Other Skills

- **`test-driven-development`:** implementer subagents follow TDD — failing test first, minimal code, verify pass. Put the TDD steps in every implementer prompt.
- **`requesting-code-review`:** the two-stage review IS the code review; use its rubric for the final integration review.
- **`systematic-debugging`:** if a subagent hits a bug during implementation, it follows that process — root cause first, then a regression test, then the fix.

## Example Workflow

~~~text
[Read plan: docs/plans/auth-feature.md]
[write_todos with 5 tasks]

--- Task 1: Create User model ---
[Clarify with the user: should email be unique? -> yes]
[Dispatch implementer]   -> implemented, 3/3 tests passing
[Dispatch spec reviewer] -> PASS, all requirements met
[Dispatch quality reviewer] -> APPROVED
[Mark Task 1 complete]

--- Task 2: Password hashing ---
[Dispatch implementer]   -> implemented, 5/5 tests passing
[Dispatch spec reviewer] -> Missing: password strength validation (spec says "min 8 chars")
[Dispatch fix subagent]  -> added validation, 7/7 tests passing
[Dispatch spec reviewer] -> PASS
[Dispatch quality reviewer] -> Important: magic number 8, extract to a constant
[Dispatch fix subagent]  -> extracted MIN_PASSWORD_LENGTH
[Dispatch quality reviewer] -> APPROVED
[Mark Task 2 complete]

... (continue for all tasks)

[Final integration review] [Run the full test suite yourself: all passing] [Done]
~~~

## Remember

~~~
Fresh subagent per task
Two-stage review every time
Spec compliance FIRST
Code quality SECOND
Never skip reviews
Catch issues early
~~~

## Further Reading (load when relevant)

- **`references/context-budget-discipline.md`** — read when a run will clearly consume significant context (multi-phase plans, many subagents, large artifacts): read-depth rules, a four-tier degradation model, and early warning signs of silent degradation.
- **`references/gates-taxonomy.md`** — read when designing or reviewing a workflow with validation checkpoints: the four gate types (pre-flight, revision, escalation, abort), each with entry, failure behavior and resumption rules.

Both live next to this file, under /mnt/skills/public/subagent-driven-development/.

---

Adapted from Hermes Agent (Nous Research), itself adapted from obra/superpowers; the references adapt the GSD (Get Shit Done) project (gsd-build/get-shit-done). MIT licensed; see `LICENSE.txt`.
