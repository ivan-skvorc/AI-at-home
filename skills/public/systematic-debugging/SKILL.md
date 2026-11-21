---
name: systematic-debugging
description: Use this skill when the user reports a bug, failing test, crash, build failure, flaky behavior or performance regression and wants it fixed or explained. Enforces root-cause investigation before any fix - a tight repro loop, ranked hypotheses, one change at a time, a regression test.
license: MIT
author: Hermes Agent (Nous Research), adapted from obra/superpowers; adapted for DeerFlow
version: 1.1.0
metadata:
  tags: [debugging, troubleshooting, root-cause, investigation]
  related-skills: [test-driven-development, subagent-driven-development]
  upstream: NousResearch/hermes-agent skills/software-development/systematic-debugging (aeb5a07)
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find the root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

~~~
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
~~~

If you haven't completed Phase 1, you cannot propose fixes.

## The Feedback Loop Rule

The feedback loop is the debugging work. Before reading code to build a theory, create or identify a **tight** command that can go red on the user's exact symptom and green when the bug is fixed. A tight loop is fast, deterministic, agent-runnable, and specific enough to catch this bug — not merely "doesn't crash".

When a clean repro is hard, spend disproportionate effort building the loop. Guessing without a red-capable loop is the failure mode this skill exists to prevent.

## When to Use

Use for ANY technical issue: test failures, bugs in production, unexpected behavior, performance problems, build failures, integration issues.

**Use this ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You've already tried multiple fixes, or the previous fix didn't work
- You don't fully understand the issue

**Don't skip when** the issue seems simple (simple bugs have root causes too), you're in a hurry (rushing guarantees rework), or someone wants it fixed NOW (systematic is faster than thrashing).

## Working in the DeerFlow sandbox

- The code usually lives under /mnt/user-data/workspace/ (a clone or an upload). Each `bash` call starts fresh in the workspace, so prefix commands with `cd <repo> &&`.
- Investigate with `grep` and `glob` (find error strings, callers, similar code), `read_file` with `start_line` and `end_line` (read the exact region), `bash` (run the loop, read git history) and `web_search` / `web_fetch` (error messages, library docs).
- If the `bash` tool is missing (host bash is disabled under the local sandbox), you cannot run a loop yourself: say so, give the user the exact command to run, and ask them to switch to the container sandbox for hands-on debugging.

## The Four Phases

You MUST complete each phase before proceeding to the next.

---

## Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

### 1. Read Error Messages Carefully

- Don't skip past errors or warnings; they often contain the exact solution
- Read stack traces completely
- Note line numbers, file paths, error codes

**Action:** `read_file` the relevant source files; `grep` for the error string across the codebase (`literal: true` for messages with regex characters).

### 2. Build a Tight Feedback Loop

- Can you trigger the user's exact symptom with one command?
- Does the command fail for this bug and only pass once the bug is fixed?
- Is it fast enough to run repeatedly?
- Is it deterministic? For flaky bugs, can you raise the reproduction rate high enough to debug?
- If not reproducible → gather more data, don't guess.

**Ways to construct a loop — try in roughly this order:**

1. **Failing test** at the seam that reaches the bug: unit, integration, or end-to-end.
2. **HTTP script / curl** against a running dev server.
3. **CLI invocation** with fixture input, diffing stdout/stderr against expected output.
4. **Headless browser script** (Playwright/Puppeteer) asserting on DOM, console, or network.
5. **Replay a captured trace**: HAR, request payload, event log, queue message, or webhook body.
6. **Throwaway harness** that boots the smallest useful slice of the system and calls the failing path.
7. **Property / fuzz loop** when the bug is intermittent wrong output over a broad input space.
8. **Bisection harness** suitable for `git bisect run` when the bug appeared between two known states.
9. **Differential loop** comparing old vs new version, two configs, two providers, or two datasets.
10. **Human-in-the-loop script** only as a last resort: script the human steps and capture their result so the loop stays structured.

**Tighten the loop once it exists:**

- Make it faster: cache setup, narrow scope, skip unrelated initialization.
- Make the signal sharper: assert the exact symptom, not generic success.
- Make it more deterministic: pin time, seed randomness, isolate filesystem, freeze network.

For non-deterministic bugs, the immediate goal is a higher reproduction rate, not perfection. Run the trigger 100x, parallelize, add stress, narrow timing windows, or inject sleeps. A 50% flake is debuggable; a 1% flake usually is not.

**Action:** run the loop with `bash`:

~~~bash
# Run a specific failing test
cd /mnt/user-data/workspace/project && pytest tests/test_module.py::test_name -v

# Or run a scripted repro
cd /mnt/user-data/workspace/project && python repro_bug.py

# Or run a high-repetition flaky repro
cd /mnt/user-data/workspace/project && for i in $(seq 1 100); do pytest tests/test_flake.py::test_name -q || break; done
~~~

### 3. Check Recent Changes

What changed that could cause this? Git diff, recent commits, new dependencies, config changes.

~~~bash
cd /mnt/user-data/workspace/project && git log --oneline -10
cd /mnt/user-data/workspace/project && git diff
cd /mnt/user-data/workspace/project && git log -p --follow src/problematic_file.py | head -100
~~~

### 4. Gather Evidence in Multi-Component Systems

**WHEN the system has multiple components (API → service → database, CI → build → deploy):**

**BEFORE proposing fixes, add diagnostic instrumentation.** For EACH component boundary:
- Log what data enters the component
- Log what data exits the component
- Verify environment/config propagation
- Check state at each layer

Run once to gather evidence showing WHERE it breaks. THEN analyze the evidence to identify the failing component. THEN investigate that specific component.

### 5. Trace Data Flow

**WHEN the error is deep in the call stack:**

- Where does the bad value originate?
- What called this function with the bad value?
- Keep tracing upstream until you find the source
- Fix at the source, not at the symptom

**Action:** trace references with `grep` — for example `pattern: "function_name\("` (narrowed with the `glob` parameter to the language's files) to find callers, and `pattern: "variable_name\s*="` to find where a value is set.

### Phase 1 Completion Checklist

- [ ] Error messages fully read and understood
- [ ] A tight loop command exists and has been run at least once
- [ ] Loop is red-capable: it asserts the user's exact symptom, not a nearby failure
- [ ] Loop is deterministic, or a flaky bug has a high enough reproduction rate to debug
- [ ] Recent changes identified and reviewed
- [ ] Evidence gathered (logs, state, data flow)
- [ ] Problem isolated to specific component/code
- [ ] Root cause hypotheses can be stated and tested

**STOP:** Do not proceed to Phase 2 until you understand WHY it's happening.

---

## Phase 2: Pattern Analysis

**Find the pattern before fixing:**

### 0. Minimize the Reproduction

Once the loop is red, shrink the repro to the smallest scenario that still goes red. Cut inputs, callers, config, data, and steps **one at a time**, re-running the loop after each cut. Keep only what is load-bearing for the failure.

Done when removing any remaining element makes the loop go green. A minimal repro narrows the hypothesis space and often becomes the cleanest regression test.

### 1. Find Working Examples

Locate similar working code in the same codebase (`grep` for the pattern). What works that's similar to what's broken?

### 2. Compare Against References

If implementing a pattern, read the reference implementation COMPLETELY. Don't skim — read every line. Understand the pattern fully before applying it.

### 3. Identify Differences

What's different between working and broken? List every difference, however small. Don't assume "that can't matter".

### 4. Understand Dependencies

What other components does this need? What settings, config, environment? What assumptions does it make?

---

## Phase 3: Hypothesis and Testing

**Scientific method:**

### 1. Form Ranked Falsifiable Hypotheses

- Generate 3–5 plausible hypotheses before testing any single one.
- Rank them by likelihood and cheapness to falsify.
- State the prediction each hypothesis makes: "If X is the cause, then changing or observing Y should make Z happen."
- Discard or sharpen any hypothesis that does not make a testable prediction.

In an interactive chat, show the ranked list before testing: the user may have domain knowledge that instantly re-ranks it. In an unattended run (a scheduled task, a channel nobody is watching), proceed with your ranking.

### 2. Test Minimally

- Test the highest-ranked hypothesis with the smallest possible probe.
- Change one variable at a time. Don't fix multiple things at once.
- Prefer debugger/REPL inspection when available; one breakpoint beats ten logs.
- If you add logs, tag every temporary line with a unique prefix such as `[DEBUG-a4f2]` so cleanup is a single `grep`.

### 3. Verify Before Continuing

- Did it work? → Phase 4
- Didn't work? → Form a NEW hypothesis
- DON'T add more fixes on top

### 4. When You Don't Know

Say "I don't understand X". Don't pretend to know. Research more, or ask the user with `ask_clarification`.

---

## Phase 4: Implementation

**Fix the root cause, not the symptom:**

### 1. Create a Failing Test Case

Simplest possible reproduction, automated if possible, and it MUST exist before fixing. Follow the `test-driven-development` skill.

### 2. Implement a Single Fix

Address the root cause identified. ONE change at a time. No "while I'm here" improvements, no bundled refactoring.

### 3. Verify the Fix

~~~bash
# The specific regression test
cd /mnt/user-data/workspace/project && pytest tests/test_module.py::test_regression -v

# The full suite — no regressions
cd /mnt/user-data/workspace/project && pytest tests/ -q
~~~

Remove every `[DEBUG-...]` line you added before reporting.

### 4. If the Fix Doesn't Work — The Rule of Three

- **STOP.** Count how many fixes you have tried.
- If < 3: return to Phase 1 and re-analyze with the new information.
- **If ≥ 3: STOP and question the architecture (step 5 below).** Don't attempt fix #4 without that discussion.

### 5. If 3+ Fixes Failed: Question the Architecture

**Patterns indicating an architectural problem:**
- Each fix reveals new shared state/coupling in a different place
- Fixes require "massive refactoring" to implement
- Each fix creates new symptoms elsewhere

**STOP and question fundamentals:** Is this pattern fundamentally sound? Are we sticking with it through sheer inertia? Should we refactor the architecture instead of continuing to fix symptoms?

**Discuss with the user before attempting more fixes.** This is NOT a failed hypothesis — this is a wrong architecture.

---

## Red Flags — STOP and Follow Process

If you catch yourself thinking:
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"
- "Skip the test, I'll manually verify"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- "Pattern says X but I'll adapt it differently"
- "Here are the main problems: [lists fixes without investigation]"
- Proposing solutions before tracing data flow
- **"One more fix attempt" (when already tried 2+)**
- **Each fix reveals a new problem in a different place**

**ALL of these mean: STOP. Return to Phase 1.** If 3+ fixes failed, question the architecture (Phase 4 step 5).

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Issue is simple, don't need process" | Simple issues have root causes too. Process is fast for simple bugs. |
| "Emergency, no time for process" | Systematic debugging is FASTER than guess-and-check thrashing. |
| "Just try this first, then investigate" | The first fix sets the pattern. Do it right from the start. |
| "I'll write the test after confirming the fix works" | Untested fixes don't stick. Test first proves it. |
| "Multiple fixes at once saves time" | You can't isolate what worked, and it causes new bugs. |
| "Reference too long, I'll adapt the pattern" | Partial understanding guarantees bugs. Read it completely. |
| "I see the problem, let me fix it" | Seeing symptoms ≠ understanding the root cause. |
| "One more fix attempt" (after 2+ failures) | 3+ failures = architectural problem. Question the pattern, don't fix again. |

## Quick Reference

| Phase | Key Activities | Success Criteria |
|-------|---------------|------------------|
| **1. Root Cause** | Read errors, build the loop, check changes, gather evidence, trace data flow | Understand WHAT and WHY |
| **2. Pattern** | Minimize the repro, find working examples, compare, identify differences | Know what's different |
| **3. Hypothesis** | Rank theories, test minimally, one variable at a time | Confirmed or new hypothesis |
| **4. Implementation** | Create regression test, fix root cause, verify | Bug resolved, all tests pass |

## With Subagents (Ultra mode only)

The `task` tool exists only when subagents are enabled (Ultra mode). For a multi-component bug it can investigate components in parallel: one `general-purpose` subagent per component, each told to report findings and **not** to fix anything — subagents share the thread workspace, so a "helpful" edit from one corrupts another's evidence. Send no more `task` calls in one response than the concurrency limit your instructions state; extra calls are dropped. A prompt shape that works:

~~~text
Investigate why <test or behavior> fails. Follow /mnt/skills/public/systematic-debugging/SKILL.md, Phase 1 only:
read the error, reproduce it, trace the data flow, and report the root cause with file:line evidence.
Do NOT edit any file.

Error: <full error text>
File: <path to failing code>
Loop command: <exact command>
~~~

Without subagents, do the same investigation yourself, one component at a time.

## With test-driven-development

When fixing bugs: write a test that reproduces the bug (RED), debug systematically to find the root cause, fix the root cause (GREEN). The test proves the fix and prevents regression.

**No shortcuts. No guessing. Systematic always wins.**

---

Adapted from Hermes Agent (Nous Research), itself adapted from obra/superpowers. MIT licensed; see `LICENSE.txt`.
