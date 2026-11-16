---
name: cad-modeling
description: Use this skill when the user asks for a physical part or a 3D model as a file ("design a bracket", "make me an STL of…", "I need a STEP file for…", an enclosure, plate, stand, adapter or knob to print or machine), or asks to change one built earlier. Drives a requirements → script → build → measure → judge → repair loop with the cad_build tool, against requirements written down before the first build, and stops when the part meets them, when the tool says to stop, or when the part cannot be built with the operations available. Requires the CAD module's cad_build tool; it is not for images, diagrams or 2D drawings.
---

# CAD Modeling

## Overview

`cad_build` builds a part from a CadQuery script, measures what was built and
decides pass or fail on numbers. It does not know what the user wanted. It
checks the numbers it is given, and a first build that meets a bounding box is
rarely the part that was asked for.

This skill is a **loop you run**. You write the requirements down, build, read
the measurements, judge the part against every requirement, change the script
and build again, until the part meets them all. The tool holds what gets lost
in a long loop: it numbers the attempts, remembers the expected numbers of the
first build, and says in `next` what to do after each one.

## Prerequisites

A tool whose name contains `cad_build` (it is listed as `ext_cad_cad_build_…`).
If you have none, the CAD module is not installed or not enabled on this server:
say so, say that `make doctor` on the server reports why, and stop. Do not
describe a part as built, do not invent measurements, and do not write files
that look like the tool's.

## Workflow

### Step 1: Write the requirements down, before any script

List what the part must be, numbered, in your reply, so the user sees what it
will be held to. Every item is something that can be checked:

- **Measured by the tool**: the overall size along x, y and z; the volume; the
  diameter of every round hole.
- **Read from the answer or the script**: counts ("six slots"), positions, wall
  thickness, clearances, which face lies on the print bed.
- **Not checkable here**: strength, the fit to a real object, how it prints.
  List these too, marked as not checked.

If a dimension that decides the shape is missing, ask: at most three questions,
in one message. Otherwise choose a sensible value and list it as an assumption.

Then work out the expected numbers from the requirements, by arithmetic: the
overall size, a volume range (the solid volume minus what is cut away, give or
take 5 %), and one diameter per hole. They are the numbers of the request. Do
not read them off a build.

### Step 2: Write the script

- Start with `import cadquery as cq`. Units are millimetres. Put every
  dimension in a named variable at the top. Assign the part to `result`.
- A script may contain assignments, numbers, arithmetic with Python's
  operators (and `+=`), lists of numbers or points, `for` loops over
  `range(...)` or over a list, `cq.Workplane(...)` and the methods in
  `references/operations.md`.
- It may not contain `if`, `while`, functions, comprehensions, `import math`,
  f-strings or indexing (`p[0]`). Write a choice as arithmetic (`(-1) ** i`
  alternates the sign), take a point apart in the loop header
  (`for x, y in points:`), write a sine as its number and a square root as
  `** 0.5`.
- The part is **one solid**. Bodies must overlap or share a face and be joined
  with `union()`.
- In a loop, `center()` moves the origin for every pass after it. Give absolute
  positions with `pushPoints([(x, y)])`.

Read `references/operations.md` when you need a method's arguments. Threads,
sweeps, lofts, revolved shapes, text and assemblies of loose bodies are not
available: see Step 7.

### Step 3: Build

```
cad_build(name="<part name>", script="…", bbox_xyz_mm=[x, y, z],
          volume_min_max_mm3=[min, max], hole_diameters_mm=[d, d, …])
```

- Use the **same `name`** on every attempt. The tool counts attempts by name,
  and a new name starts a new part.
- Pass the volume range and the hole list every time, `[]` for a part without
  holes. A number you leave out is not checked.

### Step 4: Read the whole answer

- `error`: the script was refused or a build step failed. It names the line;
  inside a loop it also names the pass and the loop variable's value.
- `checks`: each check with `expected`, `measured` and `passed`.
- `notes`: what no check decides, such as bodies the script built and never
  joined, a result made of loose bodies, an outline that was never extruded.
- `unchecked`: the measured volume and holes you did not state. Compare them
  with what you meant.
- `expected_changed`: your expected numbers are not those of the first build.
- `attempt` and `next`: which attempt this was, and what to do now. Follow
  `next`.

### Step 5: Judge the part against your list

`passed: true` settles only the numbers you passed. Go through the list from
Step 1 and give every requirement one line: met, not met, or not checked, with
its evidence (a check, a measured number, a line of the script). A requirement
you cannot point to evidence for is not met yet.

### Step 6: Change the script and build again

- Say the cause in one sentence before you change anything, and change that.
- Keep the name and the expected numbers. Change an expected number only when
  you worked it out wrongly or the user changed the request, and tell the user
  which one changed and why.
- When `next` says the failure is the same as before, your change did not reach
  its cause. Build the feature another way instead of adjusting the same line.
- `references/failures.md` lists the failure messages with their usual causes.

### Step 7: Stop

- **Every requirement is met or marked not checked**: present the files (STEP
  for a CAD program, STL for a slicer, GLB to look at, the script to edit), the
  list with its results, your assumptions, and what was not checked.
- **`next` says to stop** (8 builds in one run): report which requirement
  still fails, with the measured numbers, and what you would try next. Build
  again when the user asks.
- **The part needs something the tool does not have**: say which requirement
  cannot be met and why, and offer the nearest part that can be built. A
  different part is never presented as the one that was asked for.

A part whose last build did not pass is reported as failed, with its numbers.
Its earlier files are not the part.

## What a good loop looks like

```
requirements: 1 plate 80 × 30 × 5   2 six slots 12 × 3, pitch 12, along x   3 two M4 holes (4.3) at the ends
expected:     bbox [80, 30, 5]   volume 10,300 to 11,400   holes [4.3, 4.3]

1  refused, line 9: an if statement                 → the alternation becomes (-1) ** i
2  failed, line 11, pass 3 (i = 2): removed nothing → center() carried over between passes; pushPoints([(x, y)])
3  passed; unchecked: nothing; six slots at line 11 → 1 met (bbox), 2 met (script, volume), 3 met (holes)
```

Three attempts, one cause each, and every requirement has its evidence.
