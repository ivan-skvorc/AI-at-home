# Delegating a part to a subagent

Read this before you hand a part, or one candidate design of a part, to a
subagent with the `task` tool. It applies in Ultra mode, where `task` runs
the subagent and checks its acceptance criteria when it finishes.

Delegate only when it clearly pays: several independent parts of an assembly
built side by side, or candidates you want to compare. One part is faster to
build yourself.

## The recipe

1. **Give every subagent or candidate its own part name.** `cad_build` keeps
   one attempt record per part name in a conversation, and subagents work in
   this conversation. Two subagents that build under the same name share that
   record: they reset or use up each other's attempt count and get each
   other's `next` advice. Names that differ only in case, width or spacing are
   the same part to `cad_build`; make them differ in letters or digits:
   `bracket-a`, `bracket-b`.
2. **Put the name in the prompt, verbatim.** Write the requirements and the
   expected numbers as you would for your own build, and tell the subagent to
   pass that exact `name` on every `cad_build` call, rebuilds included, and to
   end its report with the script of its last build.
3. **Attach one criterion per part:**

   ```
   acceptance_criteria=["tool_result:cad/cad_build passed=true where name=\"bracket-a\""]
   ```

   Write the tool as `cad/cad_build`, not as the `ext_cad_cad_build_…` name
   you call; the host resolves it. The name is a JSON string in double quotes
   and is compared exactly, so spell it as the subagent will pass it.
4. **Read the checklist line for each part** in the subagent's result:
   - `holds`: the subagent's newest `cad_build` call with exactly that name
     answered `passed: true` against the expected numbers the subagent passed.
     Those may not be the numbers in your prompt: `cad_build` judges whatever
     numbers its caller gives, a builder may change one it thinks it worked
     out wrongly, and the checklist does not record them. Before you call the
     part finished, build the script from the subagent's report once yourself
     with `cad_build`, the same name and your own expected numbers: that
     answer is your evidence for the size. Then judge the part against the
     requirements the numbers do not cover, as in your own loop.
   - `does not hold`: the newest build of that name failed. An earlier pass
     does not count, because a later build replaced it. Repair or delegate
     only that part again.
   - `UNVERIFIED`: no build of that name was recorded, its answer was cut
     short or rewritten, or it fell out of the subagent's history. This is
     missing evidence, not a failure: build the part yourself with
     `cad_build` before you call it finished.

   The line sees only calls spelled exactly as the criterion. A rebuild under
   a case or spacing variant, such as `Bracket-A`, is the same part to
   `cad_build` but invisible to the line, which then still reads the older
   build; your own build of the subagent's last script settles it.

## What is not evidence

- **Files.** A subagent can write any file, including one named like a
  report or a `.step`. Do not accept a part because `<name>.report.json` says
  it passed, and do not write `file:` criteria as proof of a pass. Rebuilt
  parts also get numbered file names, so a file criterion written in advance
  cannot name the last build.
- **The subagent's own report.** It says what the subagent believes. The
  checklist line is the tool's recorded answer, and the script in the report
  is input for your own build, not proof of it.

## Not covered

Plus Ultracode workflow agents run on their own threads, where acceptance
criteria are not checked. A part built as a workflow step comes back without
this line; check it yourself, or delegate it with `task` in Ultra mode.
