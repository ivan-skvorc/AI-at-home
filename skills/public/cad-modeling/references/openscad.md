# Writing the OpenSCAD

The conventions `cadkit.py` relies on, a template, and the mistakes that cost a
render. The image's OpenSCAD is the Ubuntu release (2021.01); `cadkit.py` uses
the faster Manifold backend on its own when the installed build has it.

## The template

```openscad
// <what it is>, v<N>: <what changed in this version>
part = "all";            // cadkit sets this per body
layout = "assembled";    // cadkit sets "print" for the print layout
BODIES = ["base", "rest", "strut"];
$fn = 48;                // 32-48 while designing; 64-96 for the final export

// Sizes
base_l = 160; base_w = 120; base_t = 6;
// Clearances (per side)
pin_gap = 0.25;          // a pin that turns
slide_gap = 0.3;         // a part that slides

module base()  { /* drawn where it sits in use */ }
module rest()  { /* ... */ }
module strut() { /* ... */ }

// Where each body lies on the bed when layout == "print": flat face down, at z = 0.
module place(name) {
  if (layout != "print") children();
  else if (name == "rest")  translate([0, 140, 5]) rotate([0, 90, 0]) children();
  else if (name == "strut") translate([100, 140, 2]) rotate([90, 0, 0]) children();
  else children();
}

if (part == "base"  || part == "all") place("base")  base();
if (part == "rest"  || part == "all") place("rest")  rest();
if (part == "strut" || part == "all") place("strut") strut();
```

- Body names are letters, digits, `-` and `_`. `BODIES` is one line of quoted
  names; cadkit reads it from the file.
- Draw each body where it sits in use, so the assembled render is the assembly
  and `check` poses start from there. Put a moving body in a known position
  (closed, folded, slot 1) and write that position in a comment.
- In the print layout every body lies on z = 0, apart from the others by at
  least 5 mm unless they are printed in place, and inside the bed.
- Keep the version line at the top current: it is the first thing the user
  reads in the Code tab.

## Habits that keep renders clean

- **Cut through, not to the surface.** A hole through a 6 mm plate is
  `translate([x, y, -1]) cylinder(d = d, h = 8)`. A cut that ends exactly on a
  face leaves a skin of zero thickness and a body that is not closed.
- **Join with overlap.** Two parts of one body that only touch become two
  shells. Overlap them by 0.01 to 0.5 mm.
- **`center = true` is per primitive.** `cube` and `cylinder` default to a
  corner and a base at z = 0. Say which in the code when it is not obvious.
- **`rotate([x, y, z])` turns about X, then Y, then Z, about the origin.**
  Move the pivot to the origin, rotate, move back:
  `translate(p) rotate(a) translate(-p)`.
- **A clearance is a variable, applied once.** A 5 mm pin in a hole with a
  0.25 mm gap per side is a 5.5 mm hole; write `d = pin_d + 2 * pin_gap`.
- **Slow operations.** `minkowski`, `hull` of many parts and a high `$fn` on
  many small cylinders make CGAL renders take minutes. Prefer `offset` on 2D
  shapes and `linear_extrude`; keep `$fn` low until the export.
- **2D stays 2D.** A `square` or `circle` left outside an extrude makes the
  body fail to render as a solid.
- **Lettering.** `text()` works in the image with the DejaVu and Liberation
  fonts; name one (`font = "Liberation Sans:style=Bold"`). Letters at least
  5 mm tall and 0.6 mm deep.
- **Threads.** Model a printed thread as a stack of `linear_extrude` with
  `twist`, or as a polyhedron; give it at least 0.3 mm of clearance on the
  flank per side, and check the nut and screw as two bodies in `check`.

## What OpenSCAD cannot give you

The output is a mesh. Fillets are approximated with `$fn` facets, holes are
polygons, and the STEP that `cadkit.py export --step` writes is faceted: good
for checking fit in a CAD program, not for editing features there. Say so when
you deliver a STEP.
