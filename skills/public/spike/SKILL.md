---
name: spike
description: Use this skill when the user wants to try out an idea before committing to a build - "is this even possible?", "spike this", "quick prototype", "compare A vs B". Breaks the idea into feasibility questions and builds disposable experiments in the workspace, each ending in a written verdict.
license: MIT
author: Hermes Agent (Nous Research), adapted from gsd-build/get-shit-done; adapted for DeerFlow
version: 1.0.0
metadata:
  tags: [spike, prototype, experiment, feasibility, proof-of-concept]
  related-skills: [test-driven-development, subagent-driven-development]
  upstream: NousResearch/hermes-agent skills/software-development/spike (aeb5a07)
---

# Spike

Use this skill when the user wants to **feel out an idea** before committing to a real build — validating feasibility, comparing approaches, or surfacing unknowns that no amount of research will answer. Spikes are disposable by design. Throw them away once they've paid their debt.

Typical phrasings: "let me try this", "I want to see if X works", "spike this out", "before I commit to Y", "quick prototype of Z", "is this even possible?", "compare A vs B".

## When NOT to use this

- The answer is knowable from docs or reading code — just do the research, don't build
- The work is on the production path — build it properly with the `test-driven-development` skill (and `subagent-driven-development` for a multi-task plan)
- The idea is already validated — go straight to implementation

## Core method

Regardless of scale, every spike follows this loop:

~~~
decompose  →  research  →  build  →  verdict
   ↑__________________________________________↓
                  iterate on findings
~~~

### 1. Decompose

Break the user's idea into **2-5 independent feasibility questions**. Each question is one spike. Present them as a table with Given/When/Then framing:

| # | Spike | Validates (Given/When/Then) | Risk |
|---|-------|----------------------------|------|
| 001 | websocket-streaming | Given a WS connection, when the LLM streams tokens, then the client receives chunks < 100ms | High |
| 002a | pdf-parse-pdfjs | Given a multi-page PDF, when parsed with pdfjs, then structured text is extractable | Medium |
| 002b | pdf-parse-camelot | Given a multi-page PDF, when parsed with camelot, then structured text is extractable | Medium |

**Spike types:**
- **standard** — one approach answering one question
- **comparison** — the same question, different approaches (shared number, letter suffix `a`/`b`/`c`)

**Good spike questions:** specific feasibility with observable output.
**Bad spike questions:** too broad, no observable output, or just "read the docs about X".

**Order by risk.** The spike most likely to kill the idea runs first. There is no point prototyping the easy parts if the hard part doesn't work.

**Skip decomposition** only if the user already knows exactly what they want to spike and says so. Then take their idea as a single spike.

### 2. Align (for multi-spike ideas)

Present the spike table and ask: "Build all in this order, or adjust?" Let the user drop, reorder, or re-frame before you write any code. In an unattended run, proceed in risk order and say so.

### 3. Research (per spike, before building)

Spikes are not research-free — you research enough to pick the right approach, then you build. Per spike:

1. **Brief it.** 2-3 sentences: what this spike is, why it matters, the key risk.
2. **Surface competing approaches** if there's a real choice:

   | Approach | Tool/Library | Pros | Cons | Status |
   |----------|-------------|------|------|--------|
   | ... | ... | ... | ... | maintained / abandoned / beta |

3. **Pick one.** State why. If 2+ are credible, build quick variants within the spike.
4. **Skip research** for pure logic with no external dependencies.

Research tools: `web_search` to find candidates, `web_fetch` to read the actual docs, and `bash` to check what is installed (`pip show websockets`, `npm ls`). For libraries without docs pages, clone the repository into the workspace and `read_file` its `README.md` and examples.

### 4. Build

One directory per spike, standalone, under /mnt/user-data/workspace/spikes/ (or a spikes/ directory at the root of the repository you are working in):

~~~
spikes/
├── 001-websocket-streaming/
│   ├── README.md
│   └── main.py
├── 002a-pdf-parse-pdfjs/
│   ├── README.md
│   └── parse.js
└── 002b-pdf-parse-camelot/
    ├── README.md
    └── parse.py
~~~

**Bias toward something the user can interact with.** Spikes fail when the only output is a log line that says "it works." The user wants to *feel* the spike working. Default choices, in order of preference:

1. A runnable CLI that takes input and prints observable output
2. A minimal HTML page that demonstrates the behavior
3. A small web server with one endpoint
4. A unit test that exercises the question with recognizable assertions

To hand the user something they can open, copy the demo page or the verdict `README.md` into /mnt/user-data/outputs/ and call `present_files` on it.

**Depth over speed.** Never declare "it works" after one happy-path run. Test edge cases. Follow surprising findings. The verdict is only trustworthy when the investigation was honest.

**Avoid** unless the spike specifically requires it: complex package management, build tools/bundlers, Docker, env files, config systems. Hardcode everything — it's a spike. Installing packages needs the container sandbox; under the host-local sandbox, keep to the standard library and what is already installed.

**Building one spike** — a typical sequence:

1. `write_file` the spike's `README.md` (question, approach) and its code, for example /mnt/user-data/workspace/spikes/001-websocket-streaming/main.py.
2. Run it with `bash`: cd /mnt/user-data/workspace/spikes/001-websocket-streaming && python main.py
3. Observe the output, iterate, and probe the edge cases.

**Parallel comparison spikes (002a / 002b).** When two approaches need real engineering (not 10-line prototypes) and subagents are enabled (Ultra mode, which provides the `task` tool), give each approach to its own `general-purpose` subagent. Each works only inside its own spike directory — subagents share the workspace — and returns its own verdict; you write the head-to-head. Without subagents, build them back to back yourself.

### 5. Verdict

Each spike's `README.md` closes with:

~~~markdown
## Verdict: VALIDATED | PARTIAL | INVALIDATED

### What worked
- ...

### What didn't
- ...

### Surprises
- ...

### Recommendation for the real build
- ...
~~~

**VALIDATED** = the core question was answered yes, with evidence.
**PARTIAL** = it works under constraints X, Y, Z — document them.
**INVALIDATED** = it doesn't work, for this reason. This is a successful spike.

## Comparison spikes

When two approaches answer the same question (002a / 002b), build them **back to back**, then write a head-to-head comparison:

~~~markdown
## Head-to-head: pdfjs vs camelot

| Dimension | pdfjs (002a) | camelot (002b) |
|-----------|--------------|----------------|
| Extraction quality | 9/10 structured | 7/10 table-only |
| Setup complexity | npm install, 1 line | pip + ghostscript |
| Perf on 100-page PDF | 3s | 18s |
| Handles rotated text | no | yes |

**Winner:** pdfjs for our use case. Camelot if we need table-first extraction later.
~~~

## Frontier mode (picking what to spike next)

If spikes already exist and the user asks "what should I spike next?", walk the existing directories (`ls`, then each `README.md` verdict) and look for:

- **Integration risks** — two validated spikes that touch the same resource but were tested independently
- **Data handoffs** — spike A's output was assumed compatible with spike B's input; never proven
- **Gaps in the vision** — capabilities assumed but unproven
- **Alternative approaches** — different angles for PARTIAL or INVALIDATED spikes

Propose 2-4 candidates as Given/When/Then. Let the user pick.

## Output

- A spikes/ directory, with one NNN-descriptive-name/ directory per spike
- A `README.md` per spike capturing the question, approach, results and verdict
- Throwaway code — a spike that takes 2 days to "clean up for production" was a bad spike

---

Adapted from Hermes Agent (Nous Research), whose version adapts the GSD (Get Shit Done) project's spike workflow (gsd-build/get-shit-done, MIT, Lex Christopherson). MIT licensed; see `LICENSE.txt`.
