# Checks: poses and answers

How to describe poses and sweeps for `cadkit.py check`, and what each line of
cadkit's answers means.

## poses.json

```json
{
  "poses": [
    {"name": "seated"},
    {"name": "strut in slot 4",
     "place": {"strut": [{"translate": [36, 0, 0]}, {"rotate": [0, -12, 0], "about": [46, 0, 6]}]}},
    {"name": "rest folds",
     "sweep": {"bodies": ["rest", "lip"], "axis": [0, 1, 0], "about": [-71, 0, 11],
               "from": 0, "to": 75, "steps": 16}},
    {"name": "lid lifts out",
     "place": {"lid": [{"rotate": [-90, 0, 0], "about": [0, 40, 20]}]},
     "sweep": {"body": "lid", "direction": [0, 0, 1], "from": 0, "to": 30, "steps": 7}}
  ],
  "ignore": [["rest", "lip"]],
  "tolerance_mm3": 0.01
}
```

- A pose places bodies from where the model draws them. `place` maps a body to
  a list of steps applied in order: `{"translate": [x, y, z]}`,
  `{"rotate": [x, y, z], "about": [px, py, pz]}` (OpenSCAD's order: X, then Y,
  then Z) or `{"axis": [ux, uy, uz], "angle": deg, "about": [...]}`. Bodies a
  pose does not name stay where they are.
- A `sweep` moves one `body` or a list of `bodies` after `place`, in steps
  from `from` to `to`, both included: about an `axis` through `about`, in
  degrees, or along a `direction`, in millimetres. Up to 360 steps; 12 to 24
  usually find a clash, and a range with a tight spot deserves its own pose.
- `ignore` lists pairs that are allowed to overlap: parts glued or pressed
  together, a pin modelled without its gap on purpose. Use it sparingly and say
  why in the report.
- Cover every slot, both ends of each swing, the sweep between them, and the
  paths of assembly: a part dropped in, lifted out, slid along its rail.

## Reading the answers

`render`

- `CLASH as modelled: a / b overlap V mm3 at x .. y .. z ..`: the bodies
  overlap in the assembled position, inside that box.
- `NOT A CLOSED SOLID`: the mesh has holes or loose faces; see the habits in
  `openscad.md` (cut through, join with overlap, no 2D left over).
- `N separate shells`: the body is in pieces. Fine for a body that is meant to
  be a set, a defect otherwise.
- `ERROR ... top level object is empty`: nothing is drawn for that `part`
  value; check the `if (part == ...)` line and the name in `BODIES`.
- `render took longer than ...`: lower `$fn`, or replace `minkowski` and large
  `hull` calls.

`check`

- `CLASH a / b in K states, worst at [pose @ value]: V mm3 at <box>`: the two
  bodies overlap in K states of that pose; the box is where, at the worst state.
  Draw that state with `views --pose` to see it.
- `tight a / b ...: gap G mm < C mm`: no overlap, but closer than the clearance
  you passed. Right for a press fit, wrong for anything meant to move.
- `smallest gap`: the tightest pair over every state. Compare it with the gap
  you designed.
- `PASS` / `FAIL`: whether any state overlaps.

`print`

- `bridge`: a flat ceiling held at both ends; it prints clean up to about
  10 mm, sags past 20 mm (`--max-bridge`).
- `ledge`: a flat ceiling held on one side only; it falls without support.
  Give it a 45 degree chamfer underneath, or turn the body.
- `overhang`: a surface steeper than `--overhang` degrees from vertical over
  more than `--max-overhang-area` mm2.
- `thinnest wall` and `samples thinner than`: walls under `--min-wall` print as
  one weak line or not at all.
- `starts above the bed`, `no flat face on the bed`: the print layout is wrong.
- `may fuse`: two bodies printed together closer than `--min-gap`.
- `slicer:` grams and time from PrusaSlicer for the whole layout on one plate,
  at the stated settings, no supports. The grams are the slicer's, not the
  solid volume's.
- `slicer says:` the slicer's own warning, such as low bed adhesion or a
  suggestion to enable supports, with the files it names. Treat it like any
  other problem.

`export`

- `read back as written`: each file was read again and matched its body:
  every STL its report.json; each STEP re-imported as one solid with closed
  shells, its volume within 0.5% and its bounding box within 0.05 mm of the
  mesh; `bodies.3mf` one object per body, each with its body's volume.
  `export.json` holds every result.
- `FAIL <file>: ...`: that file does not match the body it came from, so
  `zip not written`, and an earlier zip is removed. Export again; when it
  fails again, the body itself is broken (see `render`).
- `<design>-v<N>.zip`: the print-layout STLs (or the assembled ones), the 3MF,
  the STEP files, `model.scad`, `guide.pdf`, the view images, the test pieces,
  the JSON results, and `manifest.json`: the bodies, the slicer's settings,
  grams and time, the checks, and each file with its size and sha256.
- `<body>-cq.step left out of the zip`: an editable STEP joins the zip only
  after `compare` passed on it in the version folder.

`study`

- One row per value: the `clashes` over every state of the poses, the
  `smallest gap`, and each body's volume. `render error` and `not closed` mark
  a value whose bodies failed; the lines below the table say which.
- `passes:` the values whose bodies are all closed with no clash.
  `no value passes` exits 1. The study lives in `<design>/studies/<name>/`,
  outside the versions, and the same name run again replaces it. `compare.png` is one
  column per value at one scale; `--section z=5` picks its plane.
- `assigns no <name> at the top level`: `-D` only overrides a top-level
  assignment, so every value may render the same model.

`testpiece`

- One line per piece: its size, volume and share of its body. The pieces keep
  their assembled position, in `v<N>/test/`; lay each flat to print it.
  `views` and `print` take `v<N>/test` like a version.
- `left out, the box misses them`: bodies the box does not reach. A body named
  in `--bodies` that the box misses, or a box that misses every body, is an
  `ERROR ... holds nothing of`. Write `--box=-5,...` when the first number is
  negative.
- `CLASH`, `tight` and `smallest gap` between the pieces read as in `check`.

`compare`

- `volume differs by` and `bounding boxes by at most`: B against A.
- `symmetric difference`: the volume inside one solid and not the other, as a
  share of A's volume. `PASS` is below `--tolerance` (1%). A round feature at
  `$fn = 48` differs from its true circle by about 0.3%.
- `largest surface deviation`: the farthest a sampled point of one surface lies
  from the other, and where. A missing hole or boss shows here even when the
  volumes are close.
