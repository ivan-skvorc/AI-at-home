# Designing for an FDM printer

Starting values for a part printed on a home FDM printer, and for the screws,
nuts and inserts it takes. Each is a typical start, not a promise: printers
differ, and a coupon (below) settles a fit that matters. The defaults of
`cadkit.py print` match this page: a 0.4 mm nozzle, 0.2 mm layers, 45 degree
overhangs, 0.8 mm walls, a 250 x 210 x 220 mm bed. When the user names another
printer or value, pass it (`--bed`, `--min-wall`, `--overhang`) and use it here.
Do not ask the user for printer facts.

## Orientation

Choose the print layout for a large flat face down, round holes along z, few
overhangs and loads along the layers. A print is weakest between layers, so a
hook or a clip lies down rather than stands. Each body gets its own
orientation in `place()`; `cadkit.py print` says when one starts above the bed
or has no flat face on it.

## Walls, features and overhangs

- Walls at least two nozzle widths, 0.8 mm; three where a wall carries load;
  2 mm around screws and inserts. Thinner prints as one weak line or not at all.
- Pins and posts at least 2 mm across: thinner ones wobble and snap.
- Heights in whole layers, 0.2 mm: a 0.3 mm step prints as 0.2 or 0.4.
- Overhangs up to 45 degrees from vertical print without support. A flat
  ceiling held at both ends is a bridge: up to about 10 mm prints clean, past
  20 mm it sags. A flat ceiling held on one side is a ledge and falls: chamfer
  it at 45 degrees or turn the body.
- Bed edges get a 0.5 mm chamfer, not a fillet. A fillet there starts flat, an
  overhang in the first layers; the chamfer also hides the squashed first layer
  (elephant's foot) that otherwise spoils a fit.
- A horizontal hole droops at the top. Up to about 6 mm, model it 0.1 mm larger
  than a vertical one. Larger, make it a teardrop with its point up:
  `hull() { circle(r); rotate(45) square(r); }` extruded along the hole's axis.

## Holes for hardware

FDM prints holes small: the slicer's polygon and the squeezed perimeter take
about 0.2 mm off a diameter. Model a hole for a metal part 0.2 mm over the size
it must have. Give a round hole enough facets that its flats do not eat the
clearance: `$fn` of at least 32 for holes under 10 mm.

| Size | Clearance, ISO 273 medium | Model at | Nut across flats, ISO 4032 | Nut trap across flats | Nut height | Socket head Ø × height, ISO 4762 | Insert hole |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M2 | 2.4 | 2.6 | 4 | 4.3 | 1.6 | 3.8 × 2 | 3.2 |
| M2.5 | 2.9 | 3.1 | 5 | 5.3 | 2 | 4.5 × 2.5 | 3.6 |
| M3 | 3.4 | 3.6 | 5.5 | 5.8 | 2.4 | 5.5 × 3 | 4 |
| M4 | 4.5 | 4.7 | 7 | 7.3 | 3.2 | 7 × 4 | 5.6 |
| M5 | 5.5 | 5.7 | 8 | 8.3 | 4.7 | 8.5 × 5 | 6.4 |

- Nut trap: across flats plus 0.3 mm, as deep as the nut plus 0.3 mm. In
  OpenSCAD a hexagon is `cylinder(d = af / cos(30), h = h, $fn = 6)`: `d` is
  across corners, and using the across-flats size there makes it 13% too small.
- Socket head counterbore: head diameter plus 0.6 mm, head height plus 0.3 mm.
- Countersunk heads (ISO 10642) are 90 degrees, not 82, and about 2.24 × the
  size across (M3: 6.7); model the cone 0.4 mm wider.
- A screw cut straight into plastic: a hole of about 0.9 × the size (M3:
  2.7), for a few assemblies; an insert for more.
- Heat-set inserts: the column is typical of short knurled brass inserts,
  modelled as is with no allowance; the vendor's table wins. The hole is 1 mm
  deeper than the insert is long.

## Fits between printed parts

A gap is per side: a 5 mm pin with a 0.2 mm gap goes in a 5.4 mm hole. The gaps
already include the printer's error, so add no hole allowance on top. Pass the
smallest gap you designed as `--clearance` to `check`, so a tighter one shows.

| Fit | Gap per side |
| --- | --- |
| Press: stays without glue | 0 to 0.1 mm |
| Sliding: a lid, a pin that turns | 0.2 to 0.3 mm |
| Print-in-place: printed together, must come free | 0.3 to 0.5 mm |
| Printed thread, per flank | 0.3 to 0.5 mm |

- A press fit in PLA cracks rather than stretches: try it on a coupon first.
- Print-in-place parts are separate bodies drawn in place with their gaps; a
  gap above or below a body is at least two layers, 0.4 mm, because what is
  printed over it sags.
- A real print outranks these numbers: when the user reports a fit as too
  tight or loose, change that gap and say by how much.

## A fit-test coupon

Offer one when the part must fit real hardware or another part and its print
takes more than about an hour: the coupon prints in about 10 minutes. Make it
its own small design:

- a plate 1.5 mm thicker than its deepest feature, as small as they allow;
- only the features the part depends on, each three times: the table value,
  and 0.2 mm smaller and larger (0.1 mm for a printed fit, whose peg is a
  second small body);
- 1, 2 and 3 notches in the edge beside the variants, so the user can name the
  one that fit;
- printed in the part's orientation, material and settings.

Use the variant that fit in the real part, and tell the user its value so
later parts start from it.
