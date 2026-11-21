---
name: test-driven-development
description: Use this skill when writing or changing production code - a new feature, bug fix, refactor or behavior change - that should be test-backed, or when the user asks for TDD. Enforces red-green-refactor - write one failing test, watch it fail, write minimal code to pass, then refactor.
license: MIT
author: Hermes Agent (Nous Research), adapted from obra/superpowers; adapted for DeerFlow
version: 1.1.0
metadata:
  tags: [testing, tdd, quality, red-green-refactor]
  related-skills: [systematic-debugging, subagent-driven-development]
  upstream: NousResearch/hermes-agent skills/software-development/test-driven-development (aeb5a07)
---

# Test-Driven Development (TDD)

## Overview

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you didn't watch the test fail, you don't know if it tests the right thing.

**Violating the letter of the rules is violating the spirit of the rules.**

## When to Use

**Always:** new features, bug fixes, refactoring, behavior changes.

**Exceptions (ask the user first, with `ask_clarification`):** throwaway prototypes (see the `spike` skill), generated code, configuration files.

Thinking "skip TDD just this once"? Stop. That's rationalization.

## The Iron Law

~~~
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
~~~

Write code before the test? Delete it. Start over.

**No exceptions:**
- Don't keep it as "reference"
- Don't "adapt" it while writing tests
- Don't look at it
- Delete means delete

Implement fresh from tests. Period.

## Running Tests in DeerFlow

Run every step with the `bash` tool. The code usually lives under /mnt/user-data/workspace/, and each `bash` call starts fresh in the workspace, so prefix commands with `cd <repo> &&`. Write tests with `write_file` and change code with `str_replace` (read the file with `read_file` first). If the `bash` tool is missing (host bash is disabled under the local sandbox), you cannot watch a test fail: say so instead of claiming a red or green you did not see.

## Red-Green-Refactor Cycle

### RED — Write a Failing Test

Write one minimal test showing what should happen.

**Good test:**
~~~python
def test_retries_failed_operations_3_times():
    attempts = 0
    def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise Exception('fail')
        return 'success'

    result = retry_operation(operation)

    assert result == 'success'
    assert attempts == 3
~~~
Clear name, tests real behavior, one thing.

**Bad test:**
~~~python
def test_retry_works():
    mock = MagicMock()
    mock.side_effect = [Exception(), Exception(), 'success']
    result = retry_operation(mock)
    assert result == 'success'  # What about retry count? Timing?
~~~
Vague name, tests the mock, not real code.

**Requirements:**
- One behavior per test
- Clear descriptive name ("and" in the name? Split it)
- Real code, not mocks (unless truly unavoidable)
- Name describes behavior, not implementation

### Verify RED — Watch It Fail

**MANDATORY. Never skip.**

~~~bash
cd /mnt/user-data/workspace/project && pytest tests/test_feature.py::test_specific_behavior -v
~~~

Confirm:
- The test fails (not errors from typos)
- The failure message is the expected one
- It fails because the feature is missing

**Test passes immediately?** You're testing existing behavior. Fix the test.

**Test errors?** Fix the error, re-run until it fails correctly.

### GREEN — Minimal Code

Write the simplest code to pass the test. Nothing more.

**Good:**
~~~python
def add(a, b):
    return a + b  # Nothing extra
~~~

**Bad:**
~~~python
def add(a, b):
    result = a + b
    logging.info(f"Adding {a} + {b} = {result}")  # Extra!
    return result
~~~

Don't add features, refactor other code, or "improve" beyond the test.

**Cheating is OK in GREEN:** hardcode return values, copy-paste, duplicate code, skip edge cases. We'll fix it in REFACTOR.

### Verify GREEN — Watch It Pass

**MANDATORY.**

~~~bash
# The specific test
cd /mnt/user-data/workspace/project && pytest tests/test_feature.py::test_specific_behavior -v

# Then ALL tests, to check for regressions
cd /mnt/user-data/workspace/project && pytest tests/ -q
~~~

Confirm the test passes, other tests still pass, and the output is pristine (no errors, warnings).

**Test fails?** Fix the code, not the test.

**Other tests fail?** Fix regressions now.

### REFACTOR — Clean Up

After green only: remove duplication, improve names, extract helpers, simplify expressions. Keep tests green throughout. Don't add behavior.

**If tests fail during refactor:** undo immediately. Take smaller steps.

### Repeat

Next failing test for the next behavior. One cycle at a time.

## Avoid Horizontal Slices

Do **not** write all tests first and then all implementation. That is horizontal slicing: RED becomes "write a pile of imagined tests" and GREEN becomes "make the pile pass." It produces brittle tests, because the tests are designed before the implementation has taught you what behavior and interface actually matter.

Use vertical tracer bullets instead:

~~~text
WRONG:
  RED:   test1, test2, test3, test4
  GREEN: impl1, impl2, impl3, impl4

RIGHT:
  RED→GREEN: test1→impl1
  RED→GREEN: test2→impl2
  RED→GREEN: test3→impl3
~~~

A tracer bullet is one end-to-end behavior slice. It proves the path works, teaches you about the interface, and keeps each next test grounded in what you just learned.

## Why Order Matters

**"I'll write tests after to verify it works."** Tests written after code pass immediately, and passing immediately proves nothing: they might test the wrong thing, test implementation instead of behavior, or miss edge cases you forgot. You never saw them catch the bug. Test-first forces you to see the test fail, proving it actually tests something.

**"I already manually tested all the edge cases."** Manual testing is ad hoc: no record of what you tested, can't re-run when code changes, easy to forget cases under pressure. "It worked when I tried it" ≠ comprehensive.

**"Deleting X hours of work is wasteful."** Sunk cost fallacy. The time is already gone. The "waste" is keeping code you can't trust.

**"TDD is dogmatic; being pragmatic means adapting."** TDD IS pragmatic: it finds bugs before commit, prevents regressions, documents behavior and enables refactoring. "Pragmatic" shortcuts = debugging in production = slower.

**"Tests after achieve the same goals — it's spirit, not ritual."** No. Tests-after answer "What does this do?" Tests-first answer "What should this do?" Tests-after are biased by your implementation; tests-first force edge-case discovery before implementing.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. The test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "Already manually tested" | Ad hoc ≠ systematic. No record, can't re-run. |
| "Deleting X hours is wasteful" | Sunk cost fallacy. Keeping unverified code is technical debt. |
| "Keep as reference, write tests first" | You'll adapt it. That's testing after. Delete means delete. |
| "Need to explore first" | Fine. Throw away the exploration, then start with TDD. |
| "Test hard = design unclear" | Listen to the test. Hard to test = hard to use. |
| "TDD will slow me down" | TDD is faster than debugging. Pragmatic = test-first. |
| "Existing code has no tests" | You're improving it. Add tests for the code you touch. |

## Red Flags — STOP and Start Over

If you catch yourself doing any of these, delete the code and restart with TDD:

- Code before test, or test after implementation
- Test passes immediately on first run
- Can't explain why the test failed
- Tests added "later"
- Rationalizing "just this once", "I already manually tested it", "this is different because..."
- "Keep as reference" or "adapt existing code"
- "Already spent X hours, deleting is wasteful"

**All of these mean: delete the code. Start over with TDD.**

## Verification Checklist

Before marking work complete:

- [ ] Every new function/method has a test
- [ ] Watched each test fail before implementing
- [ ] Each test failed for the expected reason (feature missing, not a typo)
- [ ] Wrote minimal code to pass each test
- [ ] All tests pass, and the output is pristine (no errors, warnings)
- [ ] Tests use real code (mocks only if unavoidable)
- [ ] Edge cases and errors covered

Can't check all boxes? You skipped TDD. Start over.

## When Stuck

| Problem | Solution |
|---------|----------|
| Don't know how to test | Write the wished-for API. Write the assertion first. Ask the user. |
| Test too complicated | Design too complicated. Simplify the interface. |
| Must mock everything | Code too coupled. Use dependency injection. |
| Test setup huge | Extract helpers. Still complex? Simplify the design. |

## Testing Anti-Patterns

- **Testing mock behavior instead of real behavior** — mocks should verify interactions, not replace the system under test
- **Testing implementation details** — test behavior and results, not internal method calls
- **Happy path only** — always test edge cases, errors, and boundaries
- **Brittle tests** — tests verify behavior, not structure; refactoring shouldn't break them

## With Subagents (Ultra mode only)

When you hand implementation to a `task` subagent (see the `subagent-driven-development` skill), put the TDD steps in its prompt, because it does not inherit this conversation:

~~~text
Implement <feature> using strict TDD (/mnt/skills/public/test-driven-development/SKILL.md):
1. Write the failing test first.
2. Run it and confirm it fails for the expected reason; paste the failure line.
3. Write the minimal code to pass.
4. Run it and confirm it passes; then run the full suite: <project test command>.
5. Refactor if needed, keeping the suite green.
Relevant files: <paths>
~~~

Add `tests_passed:<project test command>` to the call's `acceptance_criteria` so the result carries a checked verdict instead of only a self-report.

## With systematic-debugging

Bug found? Follow the `systematic-debugging` skill to find the root cause, write a failing test reproducing it, and follow the TDD cycle. The test proves the fix and prevents regression. Never fix bugs without a test.

## Final Rule

~~~
Production code → test exists and failed first
Otherwise → not TDD
~~~

No exceptions without the user's explicit permission.

---

Adapted from Hermes Agent (Nous Research), itself adapted from obra/superpowers. MIT licensed; see `LICENSE.txt`.
