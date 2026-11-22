---
name: cad-modeling
description: Use this skill when the user asks for a physical part or a 3D model as a file ("design a bracket", "make me an STL of…", "I need a STEP file for…", an enclosure, plate, stand, adapter or knob to print or machine), or asks to change one built earlier. Drives a requirements → script → build → measure → judge → repair loop with the cad_build tool, against requirements written down before the first build, and stops when the part meets them, when the tool says to stop, or when the part cannot be built with the operations available. Requires the CAD module's cad_build tool; it is not for images, diagrams or 2D drawings.
---

# CAD Modeling

## Overview

`cad_build` builds a part from a CadQuery script, measures what was built and
decides pass or fail on numbers. It does not know what the user wanted, and a
first build that meets a bounding box is rarely the part that was asked for.

This skill is a **loop you run**: write the requirements down, build, read the
measurements, judge the part against every requirement, change the script and
build again until it meets them all. The tool numbers the attempts, holds the
first build's expected numbers, and says in `next` what to do.

## Prerequisites

A tool whose name contains `cad_build` (listed as `ext_cad_cad_build_…`).
Without one, the CAD module is not installed or not enabled here: say so, say
that `make doctor` on the server reports why, and stop. Never describe a part
as built, invent measurements, or write files that look like the tool's.

## Workflow

### Step 1: Write the requirements down, before any script

List what the part must be, numbered, in your reply, so the user sees what it
will be held to. Every item is something that can be checked:

- **Measured by the tool**: the overall size along x, y and z; the volume; the
  diameter and position of every round hole; how many separate bodies.
- **Read from the answer or the script**: counts ("six slots"), positions of
  other features, wall thickness, clearances, which face lies on the bed.
- **Not checkable here**: strength, the fit to a real object. List these too,
  marked as not checked. How it prints is reported, not checked.

Ask only for a dimension that decides the shape: at most three questions, in
one message. Never ask for printer facts. Choose the rest, list them as
assumptions, and build a draft to show its picture: the user corrects a picture
faster than they answer questions.

Then work out the expected numbers from the requirements, by arithmetic: the
overall size, the volume (the solid volume minus what is cut away), and one
diameter per hole. Pass the volume as a narrow range around your number: no
wider than the smallest feature on your list, so that one slot too few falls
outside it. Widen it only for a shape whose volume you cannot work out, and
say so. These are the numbers of the request. Do not read them off a build.

### Step 2: Write the script

For a part to print, read `references/fdm.md` before the first script: holes
for screws, nuts and inserts, fits, walls and overhangs, and the fit-test
coupon. A hole for a metal part is modelled, and passed, with its print
allowance.

- Start with `import cadquery as cq`. Units are millimetres. Put every
  dimension in a named variable at the top. Assign the part to `result`.
  Build it in print orientation: the bed face flat, at the lowest z.
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
- Bodies become one solid where they overlap or share a face, with `union()`.
  Loose bodies (a print-in-place hinge, a box with its lid) are built in
  place, with their gaps, and passed as `bodies`.
- **Say where every feature goes from the part's own origin.** Build the part
  centred on the origin (`box()` does that by default), start each feature
  with `faces(selector).workplane(origin=(0, 0, 0))` and give its positions
  with `pushPoints([(x, y)])`: (0, 0) is then the middle of that face. A plain
  `workplane()` keeps the origin of the plane the part was last worked on,
  `center()` moves it for everything after, and the centre of a face moves
  when a cut splits the face. Do not use `center()`.
- **A selector takes everything that matches on the part as it is at that
  line.** After a boss, a peg or a rim is added, `faces(">Z")` is its top and
  `edges("|Z")` includes its edges. Cut the holes and pockets of a face, and
  round the corners of a body, before you add anything to it.
- `cutThruAll()` cuts through every wall in its way. To cut one wall of a
  hollow part, use `cutBlind(-wall)`.

`references/operations.md` gives each method's arguments: `revolve`, `loft`,
`sweep` and `twistExtrude` make turned, tapered, swept and twisted shapes,
`transformed` tilts a workplane, `text` letters a face, a thread is an outline
swept along `cq.Wire.makeHelix(...)`, and `split` cuts a part too tall for the
bed. Sketches, parametric curves and variable fillets are not available.

### Step 3: Build

```
cad_build(name="<part name>", script="…", bbox_xyz_mm=[x, y, z],
          volume_min_max_mm3=[min, max], hole_diameters_mm=[d, [d, x, y, z], …])
```

- Use the **same `name`** on every attempt. The tool counts attempts by name.
- Pass the volume range and the hole list every time, `[]` for no holes. A
  number you leave out is not checked.
- A hole is its diameter, or `[d, x, y, z]` with a point on its axis, such as
  its centre on the face it is drilled from; it then passes only there, and a
  blind hole only from that side.
- For loose bodies add `bodies=N`, their count.

### Step 4: Read the whole answer

- `error`: the script was refused or a build step failed, with the line and,
  inside a loop, the pass.
- `checks`: each check with `expected`, `measured` and `passed`; a hole not at
  its point is under `misplaced`, with the nearest one.
- `holes`: each hole's diameter, where it is entered (`at`) and its `axis`.
- `notes`: what no check decides, such as unjoined bodies, the smallest gap
  between bodies, a step left out.
- `print`: grams, bed contact, overhang, thinnest wall and print notes.
- `unchecked`: the measured volume and holes you did not state.
- `expected_changed`: your expected numbers are not those of the first build.
- `attempt` and `next`: which attempt this was, and what to do now. Follow
  `next`.

### Step 5: Judge the part against your list

`passed: true` settles only the numbers you passed. Give every requirement on
the list one line: met, not met, or not checked, with its evidence (a check, a
measured number, a line of the script). Without evidence it is not met yet.

- The volume is evidence for a feature only when the measured volume and your
  arithmetic differ by less than that feature.
- Holes are measured where they are. Pockets, bosses and slots are not: their
  position is met when the script says it from the part's origin (Step 2).
- The numbers decide; the picture finds what they miss, such as a feature on
  the wrong face. Look at it once, at review, when `next` says so.
- Read `notes` first: dropped loop passes or unjoined bodies mean missing
  features. Fix what a print note names, or tell the user.

### Step 6: Change the script and build again

- Say the cause in one sentence before you change anything, and change that.
- Keep the name and the expected numbers. Change one only when you worked it
  out wrongly or the user changed the request, and tell the user which and why.
- When `next` says the failure is the same as before, your change did not reach
  its cause. Build the feature another way instead of adjusting the same line.
- `references/failures.md` gives each failure message's usual cause.

### Step 7: Stop

- **Every requirement is met or marked not checked**: show the picture inline
  as `![name](its path in files)`, then the list with its results,
  your assumptions and what was not checked, and the files: `.3mf` for the
  slicer (of several bodies, `.3mf` prints them in place, `.parts.3mf` apart),
  STEP to edit in CAD, the script. For a fit to real hardware, offer the
  coupon from `references/fdm.md`.
- **`next` says to stop** (8 builds in one run): report which requirement
  still fails, with the measured numbers, and what you would try next.
- **The part needs something the tool does not have**: say which requirement
  cannot be met and why, and offer the nearest part that can be built. A
  different part is never presented as the one that was asked for.

A part whose last build did not pass is reported as failed, with its numbers.
Its earlier files are not the part. To hand a part to a `task` subagent, read
`references/delegation.md`.

## What a good loop looks like

```
requirements: 1 plate 80 × 30 × 5   2 six slots 3 × 12 across it, 12 apart along x
              3 two M4 holes at x = ±35 (4.7: fdm.md)   not checked: real screws
expected:     bbox [80, 30, 5]   volume 10,720 to 10,890 (10,804 by arithmetic; a slot is 170)
              holes [[4.7, -35, 0, 0], [4.7, 35, 0, 0]]

1  refused, line 9: an if statement                 → the alternation becomes (-1) ** i
2  failed, line 11, pass 2 (i = 1): removed nothing → center() carried over; workplane(origin=(0, 0, 0))
3  passed, volume 10,804.4, holes at ±35            → 1 met (bbox), 2 met (volume, picture), 3 met (holes)
```

Three attempts, one cause each, every requirement with its evidence, the
picture viewed once and a coupon offered for the screws.
