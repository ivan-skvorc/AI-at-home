# Failures and what to change

What `cad_build` says when a build does not pass, and beside a part that did,
the usual cause, and the change that fixes it. Change one thing, then build
again with the same name and the same expected numbers.

## The script was refused

Nothing was built. The answer's `error` has the construct and the line.

| The message says | Cause | Change |
| --- | --- | --- |
| a script may not contain an if statement | A choice between two values | Compute it: `(-1) ** i` alternates the sign, `i % 2` alternates 0 and 1 |
| … a while loop | A loop with a condition | A `for` loop over `range(n)`, with `n` worked out beforehand |
| … a function definition, a lambda | A helper function | A `for` loop over the values the helper was called with |
| a comprehension has one for and no if | A comprehension that filters, or runs over two lists | Write the list out, or use one `for` and arithmetic: `[(10 * i, (-1) ** i) for i in range(4)]` |
| … a slice | `p[1:]` | Name the items one by one: `p[1]`, `p[2]` |
| index … is outside this list | An index past either end | The first item is `p[0]`, the last `p[-1]` |
| a script may contain two imports | `import os`, `import numpy` | Only `import cadquery as cq` and `import math`; compute the rest with arithmetic |
| from math import … is not available: write import math | `from math import sin` | `import math`, then `math.sin(x)` |
| has no answer: the number is outside what | `math.sqrt` of a negative number, `math.acos` of more than 1 | Check the arithmetic that leads to the call |
| is a name the script is given and cannot be assigned | A variable called `min`, `max`, `len`, `round` or `math` | Rename it: `largest`, `count`, `size` |
| range() takes whole numbers | A count that is not whole, such as 7.5 | Round it down with whole division (two slashes); a whole count is accepted with or without a decimal point |
| this loop would not run once | A count that came out as 0 | Check the arithmetic of the count |
| a loop runs over range(...) or over a list | `enumerate`, `zip`, a part | `for i in range(n):` and compute the rest from `i` |
| .name() is not on the allow-list | A method the tool does not have | Build the shape from the methods in `operations.md`; if it cannot be done, tell the user |
| a script does not export | An export or save line | Delete it: the tool writes the files |
| text() has no argument 'font' (or 'fontPath') | A font named by the script | Leave it out: lettering is always in the module's own font |
| on cq a script may use cq.Workplane(...) and cq.Wire.makeHelix(...) | Another kernel constructor, such as `cq.Wire.makePolygon` | Draw the shape with the methods of a part: `polyline`, `polygon` |
| … turns (height / pitch): at most 200 | A helix taller than 200 pitches | Shorten the thread, or check that pitch and height are in millimetres |
| sweep(path=...) must be an outline drawn earlier in the script that ends with lines, arcs … | A path that is a solid, a point, or a drawing moved after it was drawn | Draw the path on a workplane of its own and sweep along it as drawn: `path = cq.Workplane("XZ").polyline([(0, 0), (0, 20), (20, 20)])` |
| at most 300 operations, at most 1000 passes | A loop that is too long | One pattern call (`rarray`, `polarArray`, `pushPoints`) instead of one operation per pass |

## A build step failed

The kernel ran and one operation went wrong. The `error` names the line, and
for a line inside a loop the pass and the loop variable's value.

| The message says | Cause | Change |
| --- | --- | --- |
| removed no material | The cut or hole is beside the part, or repeats an earlier one | Check its position: a plain `workplane()` keeps the origin of the last one, and `center()` moves it for every pass after. Start with `workplane(origin=(0, 0, 0))` |
| removed no material: the cut ran away from the material | A blind cut with the wrong sign, one that started from the top of a boss or a lip, or a pocket that is already there | `cutBlind` cuts into the part with a negative distance from a face of the part. Cut the pocket before adding the boss |
| Leave this pass out | One pass of a loop repeats an earlier one, such as a ring of points that ends on its first point | Remove that item from the list, not the line |
| added no material | The new body lies inside the part | Check its position and the direction of the extrusion |
| left no solid | The operation removed the whole part | The cut or hole is larger than the part, or two parts that were intersected do not meet |
| fillet() or chamfer() failed | The radius is too large for an edge, or no edge is selected | A smaller radius, or a narrower selector such as `"\|Z"`; fillet before cutting small features |
| shell() failed, changed nothing | The wall is thicker than the part allows | A thinner wall, or shell before adding small features |
| there is no closed outline | `extrude` or a cut without a closed shape | Draw the outline and `close()` it first |
| loft needs two or more closed outlines | One outline, or all of them on one workplane | Draw each on its own workplane, first to last: `circle(10).workplane(offset=20).circle(5).loft()` |
| sweep needs a closed outline drawn before it | No profile before `sweep`, or a profile away from where the path starts | Draw the profile on the plane square to the path's first segment, at its first point |
| text() changed nothing: lettering is cut into the part unless combine=True | Raised lettering without `combine=True`, or a cut with a positive distance, or a workplane off the face | Cut: a negative distance into the face. Raised: `combine=True` and a positive distance. Letters at least 5 mm tall print legibly |
| the axis must not cross the outline | `revolve` about an axis through the outline | Draw the outline wholly on one side of the axis: `moveTo(12.5, 0).rect(5, 4)` about the y axis |
| did not finish within … seconds | The part is too costly to build | Fewer pattern points; `hole()` instead of `circle().cutThruAll()`; fewer small fillets |

## A check failed

The part was built and measured. Each check gives `expected` and `measured`.

| Check | Usual cause | Change |
| --- | --- | --- |
| one closed solid, with several solids | Bodies that do not touch, or a cut that goes right through the part | Make them overlap or share a face, then `union()`. If loose bodies are meant, such as a print-in-place hinge or a box and its lid, do what `next` says: call cad_build again with the same name and bodies=N, their count |
| closed solids (with `bodies` above 1), with fewer solids | Bodies that touch or overlap fuse into one | Leave a gap between bodies that must come apart: for print-in-place at least the printer's clearance (`fdm.md`). The smallest gap is in `notes` |
| closed solids, with more solids | A cut right through a body, or a piece of one body that does not touch the rest | Join the pieces of a body with `union()`; check the cut's depth and position |
| bounding box | A feature that sticks out, a body that is not centred, axes in another order, a cut that removes the outermost points | Compare axis by axis. `box()` is centred on the origin unless `centered` says otherwise; a part drawn on `"XZ"` has its height along y; notches at 0° and 90° of a round part make it narrower. Several bodies are measured together, where they were built |
| volume | A cut that is missing or made twice, a body that was never joined, a loop whose passes each start from the same part, a feature in the wrong place | Read `notes`: they name bodies left out of the result and passes of a loop whose work is not in it. Carry the part through the loop: `result = result.hole(...)`. A countersink cut from the top of a peg removes its drill and not its head; a slot placed from a face that an earlier slot split lands elsewhere: place it from the origin. Several bodies: the volume is their sum |
| holes, with "not measured" | One body was expected and the result is several, and holes are measured on one solid | Join the bodies, or pass `bodies` if they are meant to be loose; each body's holes are then measured on that body |
| holes | A hole missing, doubled or of another diameter | One entry per hole. A counterbore or countersink counts once, with its drill diameter. One pass through two walls is one hole. Slots are not holes. The inside of a round pot or a hollow boss counts as one blind hole of its inner diameter: list it. A hole that breaks out through an edge is not counted: check its position |
| holes, with `misplaced` | A hole is not at the point given as `[d, x, y, z]`. Each entry has your point (`expected`), the nearest hole of that diameter that no other point accounts for (`nearest_at`, where it is entered), how far its axis passes from your point (`off_axis_mm`) and, for a blind hole whose floor stops short of your point, by how much (`past_floor_mm`) | The point is in the part's coordinates, not the workplane's: on a side face the workplane's x is not the part's x. Move the hole by the difference, placed from `workplane(origin=(0, 0, 0))`. `past_floor_mm`: the hole is drilled into the opposite face; drill it from the face your point is on. `nearest_matches`: that hole already stands for the point named there, so leave it and add the missing hole. `nearest_at` null: no hole of that diameter at all. Check the sign of each coordinate before you move anything |

## What the picture shows

The checks pass on numbers. The picture (`<name>.png`, or `<name>.failed.png`
with the checks it did not pass) shows what they do not measure. It carries no
dimension but the overall size.

| You see | Usual cause | Change |
| --- | --- | --- |
| More edges rounded or cut than you meant | The selector took every edge that matched on the part as it was at that line, including those of a boss or a rim added before | A narrower selector (`"\|Z and >X"`), or round the body before adding the feature |
| A feature on the wrong face or side | A face selector with the wrong sign or axis, or a workplane whose origin carried over | Check `>` and `<` and the axis letter; start the feature from `workplane(origin=(0, 0, 0))` |
| A feature missing although every check passed | Nothing checked it: a pocket, a boss or a slot the volume band was too wide to catch | Narrow the volume band to less than that feature (SKILL.md step 1) and build again |

## Notes beside the checks

`notes` decide nothing. Each says what a reader of the answer should still know.

| The note says | Do |
| --- | --- |
| The result is N separate bodies. Bodies become one part only where they overlap or share a face | Join them, or pass `bodies` with their count if they are meant to be loose |
| The smallest gap between bodies is … mm, between body … and body … | Compare it with the gap you meant: a print-in-place gap is 0.3 to 0.5 mm (`fdm.md`). A gap of 0: the bodies touch and print as one |
| That gap is under the printer's minimum clearance (… mm) | Widen it to at least that clearance, which is the operator's printer, or tell the user it may print fused |
| The gap of … mm between … is thinner than one layer | A gap across the layers prints as solid: widen it to at least two layers (`fdm.md`) |
| The answer lists 12 of the N holes; ….report.json lists every hole with where it is | The holes check covered all of them; read the report for the positions the answer leaves out |
| fillet() on line N rounded M edges: check that the selection took only the edges meant (a chamfer "cut" them) | Said when one took more than four edges and not every edge of the part: the selector took every edge that matched on the part as it was at that line, such as a rim's inner corners as well as its outer ones. If those are the edges you meant, nothing changes. Otherwise use a narrower selector (`"\|Z and >X"`), or round the body before adding the feature. The report's `measured.selections` counts every fillet and chamfer |
| no picture: the build used most of its time | The part was checked and delivered without its picture. Judge it on its numbers and say that there is no picture; a part with fewer small fillets and holes draws in time |
| no picture: … (any other reason) | The same: the part stands without its picture |
| no print check: the build used most of its time, or another reason | The part stands; its answer has no `print` block, so say that how it prints was not reported |
| no laid-out 3MF: the bodies could not be written apart; the .3mf holds them as modelled | Present the `.3mf`: the bodies are in it as built, and the user can separate them in the slicer |

Several bodies normally also come as `<name>.parts.3mf`, laid out side by side
on the bed to print apart. Where that file could not be written, each body
comes as `<name>.body-1.stl`, `<name>.body-2.stl` and so on (at most 8).

## Print notes

A passed part's `print` block has `grams` (solid, at the printer's density),
`bed_contact_mm2`, `overhang_mm2`, `thinnest_wall_mm` and, when the operator set
a build volume, `fits_build_volume`. It is reported, never checked: a part
passes or fails on its numbers alone. Its `notes` come only past a fixed
threshold. The printer is the operator's; do not ask the user for it. For
several bodies the block has `printed_apart: true`: each body is judged on the
bed as `.parts.3mf` lays it out, and each note names its bodies (`body 2: …`).

| The print note says | Do |
| --- | --- |
| thinnest wall about … mm (sampled), under two nozzle widths | Thicken that wall to two nozzle widths or more, or tell the user it may print weak. The wall is sampled: a thinner one can be missed, and the note is an estimate |
| … mm² overhangs past …° and needs support | When the note names a better side (`; with its … side on the bed it would be …`), tell the user to lay the part on that side in the slicer. Turning it in the script instead changes the expected bounding box: say why when `expected_changed` reports it. Otherwise chamfer the underside at 45°, or tell the user it needs support |
| nothing flat rests on the bed: give it a flat face at the lowest z, or it needs a brim or support | Cut a flat at the lowest z, or turn the part onto a flat face |
| larger than the build volume (… mm) in … | With `; it fits turned 90° on the bed`, say so: the user turns it in the slicer. Otherwise `split` it, keeping both halves, and build it with `bodies=2`: the `.parts.3mf` lays the halves apart, so a gap note about where they touch does not apply to it. Or tell the user it does not fit their printer |
| as modelled the bodies do not fit the build volume together (… mm) in …; printed apart, as the .parts.3mf lays them out, each one does | Present the `.parts.3mf` for printing. The bodies cannot be printed in place from the `.3mf` on this printer: say so when they were meant to be |
| the mesh is not watertight | The STEP is exact; the STL and 3MF have gaps a slicer usually repairs. Tell the user, and simplify the smallest features if the slicer cannot |

## Not a failure of the script

| The answer says | Do |
| --- | --- |
| Call cad_build again with the same arguments | Exactly that: the server was busy, or the kernel was still loading |
| Do not call cad_build again | Stop and tell the user what the answer says: the server cannot build |
| N builds of this part in this run and the last one did not pass | Stop. Report what fails with its numbers and what you would try next |
