# CAD parts: pictures, print files and print notes

Ask any model for a part to print, such as a bracket, a box with a lid, a
hinge or a name tag. It calls `cad_build`, the CAD module's tool, which builds
the part from a CadQuery script, measures it and checks it against the numbers
the model wrote down from your request. This page says what you get back, what
is checked and what is only reported, and how the operator's printer comes in.
The module itself is described in the
[extension README](../../examples/deerflow-extension-cad/README.md); the
procedure the model follows is the `cad-modeling` skill.

## What you get

A build that passes every check saves these files in the conversation, in this
order. The STEP file comes last among the part's files, so a STEP file in the
outputs means the whole set was saved.

| File | What it is for |
| --- | --- |
| `bracket.py` | The script, to edit or build again |
| `bracket.png` | A picture of the part, shown in the reply |
| `bracket.glb` | The mesh for a viewer, in metres (glTF's unit), one node per body |
| `bracket.stl` | The mesh, in millimetres |
| `bracket.3mf` | The part for a slicer, in millimetres |
| `bracket.parts.3mf` | Only for a part of several bodies: each body laid on the bed, to print apart |
| `bracket.step` | The exact part, for a CAD program |
| `bracket.report.json` | Every expected and measured number, each check, the print block, and what made the part |

A build that fails a check saves the script, `bracket.failed.png`,
`bracket.failed.glb` and the report, and no STEP, STL or 3MF. A script the
module refuses, or one the kernel cannot build, leaves the script and the
report. A second build of the same part never replaces the first: its files
are `bracket-1.*`, as a set.

The `.glb` and `.stl` files rotate in the artifact panel through the
[CAD model preview](file-previews.md#cad-model-preview-extension).

## The picture

Every build that produced a part, passed or failed, draws one picture: an
isometric view and the top, front and right views on one sheet, at one scale,
with an axis triad in each view. The footer gives the measured overall size,
for example `60 x 40 x 6 mm (W x D x H, measured)`. A failed build's picture
shows the part in orange under a red banner that names the checks it did not
pass.

The model shows the picture in its reply (`![bracket](/mnt/user-data/outputs/bracket.png)`),
so you see the part on a phone without opening a file. A model that can view
images is asked to look at it once, after the part passes, and compare it with
your request: a picture catches a feature on the wrong face or a feature that is
missing, which no number shows.

The picture is not a check and carries no dimension beyond the overall size.
It is drawn after the part is checked, so it never costs the part: a build with
less than 3 seconds of its time left, or a picture that cannot be drawn, is
delivered with a note such as `no picture: the build used most of its time`.

## What is checked, and what is reported

The checks decide pass or fail, on numbers the model states before the build:

- **Closed solids**: exactly one valid, closed solid, or exactly the number of
  bodies the model gave as `bodies`.
- **Bounding box**: the overall size along x, y and z, within 0.01 mm or 0.1 %.
- **Volume**: inside the range the model gave.
- **Holes**: one diameter per round hole. A hole can also be given as
  `[d, x, y, z]`, a diameter and any point on its axis, such as its centre on
  the face it is drilled from. It then passes only when a measured hole of that
  diameter has its axis within 0.05 mm, or 0.1 % of the part's largest side, of
  that point. One measured hole stands for one expected hole. A hole that is
  not where it was asked for is listed with the nearest hole of its diameter
  and how far off it is.

The answer also lists up to 12 holes, each with its diameter, the point where
it is entered and its drill direction. The report lists every hole, and its
`measured.selections` gives every fillet and chamfer with the line it is on,
the edges it took and the edges the part had then.

Everything else is reported and never changes pass or fail:

- **The print block**, for a part that passed (below).
- **Notes**: bodies the script built and never joined, loop passes whose work
  is not in the part, the smallest gap between bodies, a fillet or chamfer that
  took more than four edges and not every edge of the part (a selector that
  also caught a rim or a pocket), a step after the checks that was left out.
- **The report's provenance**: the module's and CadQuery's versions, the
  script's SHA-256, the starting numbers of the script, and the files of the set.

Not measured at all: the positions of pockets, bosses and slots, strength, and
the fit to a real object. The model lists these as not checked. The checks hold
the part to the model's own reading of your request; the
[CAD eval](cad-eval.md) measures how often that reading is right.

## How it prints

A passed part's answer carries a `print` block, measured on the STL that a
slicer would get:

| Field | Meaning |
| --- | --- |
| `grams` | Volume times the printer's density, solid, without infill |
| `bed_contact_mm2` | The area of downward faces at the lowest z |
| `overhang_mm2` | Downward faces steeper than the printer's overhang angle, the bed left out |
| `thinnest_wall_mm` | A sampled estimate: it can miss a wall thinner than the sample spacing |
| `fits_build_volume` | Whether it fits the bed, only when the operator set a build volume |

Notes come only past fixed thresholds: a wall under two nozzle widths, an
overhang of 25 mm² or more (with the side that would halve it when there is
one), nothing flat on the bed, a part larger than the build volume (and whether
it fits turned 90°), and a mesh that is not watertight. The report holds the
whole block for every built part, passed or failed.

The model builds a part in print orientation, with the bed face flat at the
lowest z. For holes that take screws, nuts and inserts, fits between printed
parts, walls and overhangs, it reads the skill's
[FDM reference](../../skills/public/cad-modeling/references/fdm.md), which also
describes a fit-test coupon: a small plate with each fit in three sizes, which
prints in about ten minutes. When a part must fit real hardware and takes more
than about an hour to print, the model offers one.

### The printer profile

The printer is the operator's, set under `printer:` in the CAD record's
`config:` in `config.yaml`. The model never asks you for printer facts and
cannot change them. Every value is optional:

| Key | Range | Default | Used for |
| --- | --- | --- | --- |
| `build_volume_mm` | three numbers, 10 to 5000 | none | The fit note; no fit note when unset |
| `nozzle_mm` | 0.1 to 2 | 0.4 | A wall under two nozzle widths gets a note |
| `layer_mm` | 0.02 to 1 | 0.2 | A gap between bodies across the layers under one layer gets a note |
| `overhang_deg` | 10 to 80, from vertical | 45 | Overhang past it counts as needing support |
| `min_clearance_mm` | 0.05 to 3 | 0.3 | A gap between bodies under it gets a note (print in place) |
| `density_g_cm3` | 0.5 to 20 | 1.24 | Grams (PLA 1.24, PETG 1.27) |

In the CAD record (`- name: cad`), the profile sits beside the module's other
values:

```yaml
    config:
      enabled: true
      printer:
        build_volume_mm: [256, 256, 256]
        nozzle_mm: 0.4
```

A key the module does not know, or a value outside its range, keeps the CAD
module from loading: the Gateway starts without `cad_build` and logs an error
that names the key, such as `cad: printer.nozzle_mm must be a number from 0.1
to 2`. Restart the Gateway after changing the profile.

## A part of several bodies

A print-in-place hinge, a chain, or a box modelled with its lid closed is
several separate solids. The model builds them in place, with their gaps, and
passes `bodies` with their count (1 to 20). The check is then "closed solids":
exactly that many valid, closed solids, with the volume their sum and the
bounding box around all of them. Each body's holes are measured on that body
alone, so a captive pin does not fill its bore, and the answer numbers the
bodies from 1.

The smallest gap between bodies is always a note, with the two bodies and its
direction. A further note says when that gap is under the printer's
`min_clearance_mm`, where the bodies may fuse, and when a gap across the
layers is thinner than one layer, which the slicer may fill. Gaps are never a
check: a gap of 0 already fails, because touching bodies fuse into fewer.

When a result has more bodies than expected, the answer offers both ways out:
join them, or build again with `bodies` set to the count when loose bodies are
meant.

Two 3MF files come with such a part:

- `bracket.3mf` keeps the bodies where they were modelled, as one object, to
  print in place.
- `bracket.parts.3mf` stands each body on the bed, side by side along x with
  5 mm between them, to print apart. Where it cannot be written, each body comes
  as `bracket.body-1.stl`, `bracket.body-2.stl` and so on, at most 8; where
  neither can be, a note says so and `bracket.3mf` still holds the bodies.

A part too tall for the bed can be cut in two with `split`, keeping both
halves, and built as two bodies; `bracket.parts.3mf` then lays the halves out.

In `report.json`, `measured.gaps` numbers the bodies from 0, as the
measurement does; the answer and its notes number them from 1.

## Lettering and threads

`text` letters a face in the module's own font (Liberation Sans, under the SIL
Open Font License), at most 64 plain ASCII characters. A negative distance cuts
the letters into the part; `combine=True` with a positive distance raises them.
The script cannot choose a font, and there is no bold or italic, because the
module ships one font file. Letters print legibly from about 5 mm tall and
0.6 mm deep.

A thread is an outline swept along `cq.Wire.makeHelix(pitch, height, radius)`
with `isFrenet=True`, at most 200 turns. The helix serves only as the path of a
sweep.

## Limits

- The module does not slice or send anything to a printer; the 3MF goes to the
  slicer you use.
- CadQuery's 3MF writer numbers its objects from 0 and writes each face's
  vertices separately, so a slicer may report that it repaired the file.
- The print block is a fast estimate on the mesh, not a slicer's preview.
- Whether a model follows the skill's procedure on real requests is measured by
  the [CAD eval](cad-eval.md), not by these checks.
- In Ultra mode a part can be handed to a subagent and accepted on its
  recorded `cad_build` answer; the recipe is the skill's
  [delegation reference](../../skills/public/cad-modeling/references/delegation.md).
