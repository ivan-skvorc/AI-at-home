# Failures and what to change

What `cad_build` says when a build does not pass, the usual cause, and the
change that fixes it. Change one thing, then build again with the same name and
the same expected numbers.

## The script was refused

Nothing was built. The answer's `error` has the construct and the line.

| The message says | Cause | Change |
| --- | --- | --- |
| a script may not contain an if statement | A choice between two values | Compute it: `(-1) ** i` alternates the sign, `i % 2` alternates 0 and 1 |
| … a while loop | A loop with a condition | A `for` loop over `range(n)`, with `n` worked out beforehand |
| … a function definition, a lambda | A helper function | A `for` loop over the values the helper was called with |
| … a comprehension | A list built in one line | Write the list out, or build the feature in a `for` loop |
| … a subscript | `point[0]` | Take the point apart in the loop header: `for x, y in points:` |
| the only import a script may contain is: import cadquery as cq | `import math` | Write the value: sin 30° is `0.5`, a square root is `** 0.5` |
| range() takes whole numbers | A count that is not whole, such as 7.5 | Round it down with whole division (two slashes); a whole count is accepted with or without a decimal point |
| this loop would not run once | A count that came out as 0 | Check the arithmetic of the count |
| a loop runs over range(...) or over a list | `enumerate`, `zip`, a part | `for i in range(n):` and compute the rest from `i` |
| .name() is not on the allow-list | A method the tool does not have | Build the shape from the methods in `operations.md`; if it cannot be done, tell the user |
| a script does not export | An export or save line | Delete it: the tool writes the files |
| at most 300 operations, at most 1000 passes | A loop that is too long | One pattern call (`rarray`, `polarArray`, `pushPoints`) instead of one operation per pass |

## A build step failed

The kernel ran and one operation went wrong. The `error` names the line, and
for a line inside a loop the pass and the loop variable's value.

| The message says | Cause | Change |
| --- | --- | --- |
| removed no material | The cut or hole is beside the part, or repeats an earlier one | Check its position: a plain `workplane()` keeps the origin of the last one, and `center()` moves it for every pass after. Start with `workplane(centerOption="CenterOfBoundBox")`. `cutBlind` cuts into the part with a negative distance |
| removed no material: the cut starts where there is no material | A blind cut started from the highest face after a boss or a lip moved it, or the pocket is already there | Cut from the face the pocket belongs to, or cut the pocket before adding the boss |
| Leave this pass out | One pass of a loop repeats an earlier one, such as a ring of points that ends on its first point | Remove that item from the list, not the line |
| added no material | The new body lies inside the part | Check its position and the direction of the extrusion |
| left no solid | The operation removed the whole part | The cut or hole is larger than the part, or two parts that were intersected do not meet |
| fillet() or chamfer() failed | The radius is too large for an edge, or no edge is selected | A smaller radius, or a narrower selector such as `"\|Z"`; fillet before cutting small features |
| shell() failed, changed nothing | The wall is thicker than the part allows | A thinner wall, or shell before adding small features |
| there is no closed outline | `extrude` or a cut without a closed shape | Draw the outline and `close()` it first |
| did not finish within … seconds | The part is too costly to build | Fewer pattern points; `hole()` instead of `circle().cutThruAll()`; fewer small fillets |

## A check failed

The part was built and measured. Each check gives `expected` and `measured`.

| Check | Usual cause | Change |
| --- | --- | --- |
| one closed solid, with several solids | Bodies that do not touch, or a cut that goes right through the part | Make them overlap or share a face, then `union()`. A design of loose bodies, such as a print-in-place hinge, cannot be delivered: tell the user |
| bounding box | A feature that sticks out, a body that is not centred, axes in another order, a cut that removes the outermost points | Compare axis by axis. `box()` is centred on the origin unless `centered` says otherwise; a part drawn on `"XZ"` has its height along y; notches at 0° and 90° of a round part make it narrower |
| volume | A cut that is missing or made twice, a body that was never joined, a loop whose passes each start from the same part | Read `notes`: they name bodies left out of the result and passes of a loop whose outcome was dropped. Carry the part through the loop: `result = result.hole(...)` |
| holes | A hole missing, doubled or of another diameter | One entry per hole. A counterbore or countersink counts once, with its drill diameter. One pass through two walls is one hole. Slots are not holes. The inside of a round pot or a hollow boss counts as one blind hole of its inner diameter: list it. A hole that breaks out through an edge is not counted: check its position |

## Not a failure of the script

| The answer says | Do |
| --- | --- |
| Call cad_build again with the same arguments | Exactly that: the server was busy, or the kernel was still loading |
| Do not call cad_build again | Stop and tell the user what the answer says: the server cannot build |
| N builds of this part in this run and the last one did not pass | Stop. Report what fails with its numbers and what you would try next |
