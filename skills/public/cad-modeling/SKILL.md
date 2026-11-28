---
name: cad-modeling
description: Use this skill when the user asks for a physical part, mechanism or 3D model as a file (a stand, bracket, enclosure, hinge, clip, adapter or knob to print; "make me an STL of…", "I need a STEP of…"), or to change one made earlier. Runs a loop in the conversation's container that proposes the mechanism, gets the user's pick, writes multi-body OpenSCAD, renders each body, checks clashes through every pose and swing by numbers, looks at sections and a shaded render, checks print and strength, fixes, re-renders and delivers. Needs a shell with openscad (the CAD sandbox image); not for images, diagrams or 2D drawings.
---

# CAD Modeling

## Overview

You design the part as parametric OpenSCAD and prove it on the model before
anyone prints it. `scripts/cadkit.py` does the mechanical work inside the
container: it renders every body to its own STL, measures the bodies, checks
them against each other in every pose, draws sections and a shaded render,
checks the print layout and runs a slicer, writes STEP and 3MF and reads each
back, and makes a guide and a zip to deliver. You decide what to build, read
every result, and fix what failed.

Every version runs the same loop, and you keep running it until every check
passes or a check shows the idea cannot work:

1. propose the mechanism and get the user's pick;
2. write the OpenSCAD;
3. render each body;
4. check by numbers: clashes and gaps in every pose and through every swing;
5. check by eye: sections and a shaded render;
6. check print and strength;
7. fix what failed and go back to 3;
8. deliver, with every figure marked as a model check.

## Prerequisites

Run once, before anything else:

```bash
openscad --version && python3 /mnt/skills/public/cad-modeling/scripts/cadkit.py --help
```

If there is no `bash` tool, or either command fails, this server has no CAD
container. Say that CAD needs the container sandbox with the CAD image
(`make sandbox-cad-image`, then `make sandbox-enable MODE=container IMAGE=cad`
and a Gateway restart; see the CAD design guide), and stop. Never describe a
part as rendered or checked without the tool's output, never invent a
measurement, and never ask the user to enable host bash.

Use the image's own `python3`. A virtual environment without
`--system-site-packages` hides the libraries the image provides.

## Step 1: Requirements and the concept

Write the requirements down as a numbered list the user can see: sizes, loads
(a 2.5 kg tablet), what moves and how far, what it must fit. Mark what cannot be
checked here (real strength, the fit to a real object) as not checked.

For anything that moves or carries a load, settle the concept by numbers before
any code: a tipping check (centre of mass inside the footprint at every
position), the force on each link, the travel. Offer two or three mechanisms
when they differ in a way the user would care about (slots or a lead screw, a
twist lock or a latch), one line each with the number that separates them, and
ask the user to pick. Ask at most three questions in one message, only about
what decides the shape; never ask for printer facts. Choose the rest, list them
as assumptions, and build a draft: a picture is corrected faster than a
question is answered.

## Step 2: Write the OpenSCAD

Read `references/openscad.md` before the first file, and `references/fdm.md`
for a part to print. In short:

- Millimetres, Z up. Every dimension and clearance is a named variable at the
  top. Each body is its own module, drawn where it sits in use.
- Declare the bodies and draw one per `part` value, so each renders alone:

  ```openscad
  part = "all";      // cadkit sets this per body
  layout = "assembled";  // "print" lays each body flat on the bed
  BODIES = ["base", "rest", "strut"];
  if (part == "base" || part == "all") place("base") base();
  ```

- Keep the working file at `/mnt/user-data/workspace/<design>/model.scad` and
  edit it in place; every render copies it into its version folder.
- No `include`, `use` or `import` of files you did not write in this
  conversation.

## Step 3: Render each body

```bash
python3 /mnt/skills/public/cad-modeling/scripts/cadkit.py render model.scad --design /mnt/user-data/outputs/<design> --print-layout
```

Each render makes the next version folder, `/mnt/user-data/outputs/<design>/v<N>/`,
with one STL per body, `assembly.glb` for the preview, `report.json` and the
`.scad` it was made from. `--print-layout` also renders every body with
`layout="print"` into `v<N>/print/`. Read the summary: every body must render,
be a closed solid and be one shell unless you meant otherwise. A `CLASH as
modelled` means two bodies overlap where they sit. Exit 0 is clean, 1 means a
check failed, 2 means the command could not run.

## Step 4: Check by numbers

Write `poses.json` next to the model with every way the bodies sit and move:
each slot or detent, both ends of every swing, a sweep through each range, and
the paths for putting the parts together and taking them apart.
`references/checks.md` gives the format and what each line of the answer means.

```bash
python3 /mnt/skills/public/cad-modeling/scripts/cadkit.py check /mnt/user-data/outputs/<design> --poses poses.json --clearance 0.3
```

Every `CLASH` is a defect until you can name why it is not (two bodies meant to
be one, listed under `ignore`). Read `tight` gaps against the fit you intended.
Fix the cause, render again, and check again: a fix often moves a clash
somewhere else.

Choosing a dimension: when one size decides between a clash and a fit (a hinge
radius, a slot width), try several in one run with `cadkit.py study model.scad
--design /mnt/user-data/outputs/<design> --param r=8,10,12 --poses poses.json`.
It renders each value outside the versions, prints a row per value (clashes,
smallest gap, volumes) and draws `compare.png`; set the value it picks and render.

## Step 5: Check by eye

```bash
python3 /mnt/skills/public/cad-modeling/scripts/cadkit.py views /mnt/user-data/outputs/<design> --sections z=5,y=0,x=12
```

Open both images with `view_image` and look: a feature on the wrong face, a
floating or missing part, a thin neck, a hole that does not go through. Put
sections through every joint, pin and slot. Add `--poses poses.json --pose
"<name>" [--at <value>]` to look at the bodies in one pose. Without
`view_image`, say that you could not look, and lean on the section planes the
summary names.

## Step 6: Print and strength

```bash
python3 /mnt/skills/public/cad-modeling/scripts/cadkit.py print /mnt/user-data/outputs/<design> --slice
```

It checks the print layout: bed contact, overhangs, bridges and one-sided
ledges, thin walls, gaps between bodies printed together, the bed size, and
slices without supports for grams and time. Fix every `PROBLEM`, or tell the
user why it stays. For a joint or fit that matters, cut it out with `cadkit.py
testpiece /mnt/user-data/outputs/<design> --box x0,y0,z0,x1,y1,z1` and offer
those pieces as a short print to try first. Then work out the loads by hand with
`references/strength.md`: for each part that carries load, the force, the
stress, the material's limit and the safety factor. Write the arithmetic down.

## Step 7: Fix and render again

Say the cause in one sentence, change that, and run steps 3 to 6 again. Keep a
short log: version, what changed, which check drove it. When the same failure
comes back, your change did not reach its cause: build the feature another way.
When the user reports a real print, that report outranks every model check:
change the clearance or the feature it names and say so.

## Step 8: Deliver

Write the assembly steps to `steps.md` beside the model, one step per paragraph.

```bash
python3 /mnt/skills/public/cad-modeling/scripts/cadkit.py guide /mnt/user-data/outputs/<design> --steps steps.md
python3 /mnt/skills/public/cad-modeling/scripts/cadkit.py export /mnt/user-data/outputs/<design> --step --3mf --zip
```

`guide` writes `guide.pdf`: parts, a page per body, the steps, the checks.
`export` reads every file back and packs `<design>-v<N>.zip` with a manifest; a
`FAIL` line is a file that does not match its body, so fix it first. For a STEP
the user will edit, rebuild that body in CadQuery in the container, save it as
`v<N>/<body>-cq.step`, and prove it in that folder with `cadkit.py compare
<body>.stl <body>-cq.step`; only a `PASS` joins the zip.

Present the files with `present_files`: the zip, `guide.pdf`, the print-layout
STLs or the 3MF, the STEP, `model.scad`, and the two view images. Then report
in this order:

- **Build**: the bodies, the version, what each version changed and why.
- **Checks by numbers**: poses and sweeps checked, clashes found and fixed, the
  smallest gap.
- **Checks by eye**: what the sections and the render showed.
- **Print and strength**: grams and time from the slicer, overhangs, the loads
  and safety factors.
- **Limit**: every figure is a check on the model, not on a print. Ask for the
  print's result; it decides the next clearance.
