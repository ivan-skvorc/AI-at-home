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
overall size, the volume (the solid volume minus what is cut away), and one
diameter per hole. Pass the volume as a narrow range around your number: no
wider than the smallest feature on your list, so that one slot too few falls
outside it. Widen it only for a shape whose volume you cannot work out, and
say so. These are the numbers of the request. Do not read them off a build.

### Step 2: Write the script

- Start with `import cadquery as cq`. Units are millimetres. Put every
  dimension in a named variable at the top. Assign the part to `result`.
- A script may contain assignments (`w, d, t = 60, 40, 6` too), numbers,
  arithmetic (`+`, `-`, `*`, `%`, `**`, division with one slash or two, and
  `+=`), `import math` with `math.pi` and the functions named in
  `references/operations.md`, `abs`, `min`, `max`, `round`, `int`, `float`,
  `len`, an index by a whole number (`p[0]`, `p[-1]`), lists of numbers or
  points, a list comprehension with one `for` and no `if`, `for` loops over
  `range(...)` or a list, `cq.Workplane(...)` and the methods in
  `references/operations.md`.
- It may not contain `if`, `while`, functions, comparisons, conditional
  expressions, f-strings, slices (`p[1:]`), `from math import` or any other
  import, and a list cannot be added to. Write a choice as arithmetic
  (`(-1) ** i` alternates the sign).
- The part is **one solid**. Bodies must overlap or share a face and be joined
  with `union()`.
- **Say where every feature goes from the part's own origin.** Build the part
  centred on the origin (`box()` does that by default), start each feature
  with `faces(selector).workplane(origin=(0, 0, 0))` and give its positions
  with `pushPoints([(x, y)])`: (0, 0) is then the middle of that face. A plain
  `workplane()` keeps the origin of the plane the part was last worked on,
  `center()` moves it for everything after, and the centre of a face moves
  when a cut splits the face. A feature then lands somewhere else and every
  check still passes. Do not use `center()`.
- **A selector takes everything that matches on the part as it is at that
  line.** After a boss, a peg or a rim is added, `faces(">Z")` is its top and
  `edges("|Z")` includes its edges. Cut the holes and pockets of a face, and
  round the corners of a body, before you add anything to it; add several
  bosses in one `pushPoints` call.
- `cutThruAll()` cuts through every wall in its way. To cut one wall of a
  hollow part, use `cutBlind(-wall)`.

Read `references/operations.md` when you need a method's arguments: `revolve`,
`loft`, `sweep` and `twistExtrude` make turned, tapered, swept and twisted
shapes, and `transformed` tilts a workplane for an angled hole. Text, threads,
sketches, parametric curves, variable fillets and assemblies of loose bodies
are not available: see Step 7.

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

- The volume is evidence for a feature only when the measured volume and your
  arithmetic differ by less than that feature.
- The tool measures no positions. A position is met when the script says it
  from the part's origin on the right face (Step 2), not because the build
  passed.
- Read `notes` before anything else: passes of a loop whose outcome was
  dropped, or bodies that were never joined, mean features are missing from a
  part that passed.

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
requirements: 1 plate 80 × 30 × 5   2 six slots 3 wide and 12 long across the plate, 12 apart along x
              3 two M4 holes (4.3) at the ends
expected:     bbox [80, 30, 5]   volume 10,750 to 10,915 (10,833 by arithmetic; one slot is 170)   holes [4.3, 4.3]

1  refused, line 9: an if statement                 → the alternation becomes (-1) ** i
2  failed, line 11, pass 2 (i = 1): removed nothing → center() carried over; workplane(origin=(0, 0, 0)) and pushPoints
3  passed, volume 10,832.7, no notes                → 1 met (bbox), 2 met (volume within one slot of the arithmetic), 3 met (holes)
```

Three attempts, one cause each, and every requirement has its evidence.
