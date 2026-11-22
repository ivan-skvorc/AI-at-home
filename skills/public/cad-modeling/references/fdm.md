# Designing for an FDM printer

Starting values for a part printed on a home FDM printer, and for the screws,
nuts and inserts it takes. Each is a typical start, not a promise: printers
differ, and a coupon (below) settles a fit that matters.

Values marked (P) are defaults of the operator's printer profile (`printer:` in
`config.yaml`), which the print block and print notes apply. When a print note
or the user states another value, use that one. Do not ask the user for printer
facts.

## Draft first, then details

When details are open, ask only for the dimensions that decide the shape. Build
a draft with the rest listed as assumptions, show its picture, and ask for
corrections on the picture: one look replaces a round of questions, on a phone
most of all. Settle fillets, fits and lettering once the shape is agreed.

## Orientation

Build the part in print orientation: the face that lies on the bed is flat and
at the lowest z. Choose it for a large flat face down, round holes along z, few
overhangs and loads along the layers. A print is weakest between layers, so a
hook or a clip lies down rather than stands. The print block names a better
face down when one halves the overhang, and a print note says when the part is
larger than the bed (P): turn it, or offer to split it.

## Walls, features and overhangs

- Walls at least two nozzle widths, 0.8 mm (P); three where a wall carries
  load; 2 mm around screws and inserts. Thinner prints as one weak line or
  not at all.
- Pins and posts at least 2 mm across: thinner ones wobble and snap.
- Heights in whole layers, 0.2 mm (P): a 0.3 mm step prints as 0.2 or 0.4.
- Overhangs up to 45° from vertical (P) print without support. A flat ceiling
  is a bridge: up to about 10 mm prints clean, past 20 mm it sags. Shorten it
  or turn the part.
- Bed edges get a 0.5 mm chamfer, not a fillet. A fillet there starts flat, an
  overhang in the first layers; the chamfer also hides the squashed first layer
  (elephant's foot) that otherwise spoils a fit.
- A horizontal hole droops at the top. Up to about 6 mm, model it 0.1 mm larger
  than a vertical one. Larger, cut a teardrop from the side face's
  `workplane(origin=(0, 0, 0))`: `moveTo(-0.707 * r, 0.707 * r)`, `lineTo`
  the point (0, 1.414 * r) and (0.707 * r, 0.707 * r), `threePointArc`
  through (0, -r) back to the start, `close()`. The point faces +z. Off
  centre, add the centre's workplane position to each point and check it in
  the picture. The tool counts only full round holes, so a teardrop stays out
  of `hole_diameters_mm`.

## Holes for hardware

FDM prints holes small: the slicer's polygon and the squeezed perimeter take
about 0.2 mm off a diameter. Model a hole for a metal part 0.2 mm over the size
it must have, and pass that modelled diameter in `hole_diameters_mm`: the tool
measures the model, not the print. A coupon gives this printer's real
allowance.

| Size | Clearance, ISO 273 medium | Model at | Nut across flats, ISO 4032 | Nut trap across flats | Nut height | Socket head Ø × height, ISO 4762 | Insert hole |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M2 | 2.4 | 2.6 | 4 | 4.3 | 1.6 | 3.8 × 2 | 3.2 |
| M2.5 | 2.9 | 3.1 | 5 | 5.3 | 2 | 4.5 × 2.5 | 3.6 |
| M3 | 3.4 | 3.6 | 5.5 | 5.8 | 2.4 | 5.5 × 3 | 4 |
| M4 | 4.5 | 4.7 | 7 | 7.3 | 3.2 | 7 × 4 | 5.6 |
| M5 | 5.5 | 5.7 | 8 | 8.3 | 4.7 | 8.5 × 5 | 6.4 |

- Nut trap: across flats plus 0.3 mm, as deep as the nut plus 0.3 mm.
  `polygon(6, size, circumscribed=True)` takes the across-flats size; plain
  `polygon(6, size)` takes it across corners and comes out 13% too small. A
  hexagon is not a round hole: leave it out of `hole_diameters_mm`, but list
  the screw hole through it.
- Socket head: `cboreHole(hole, head + 0.6, height + 0.3)`.
- Countersunk heads (ISO 10642) are 90°, not 82°, and about 2.24 × the size
  across (M3: 6.7): `cskHole(hole, head + 0.4, 90)`.
- A screw cut straight into plastic: a hole of about 0.9 × the size (M3:
  2.7), for a few assemblies; an insert for more.
- Heat-set inserts: the column is typical of short knurled brass inserts,
  modelled as is with no allowance; the vendor's table wins. The hole is 1 mm
  deeper than the insert is long.

## Fits between printed parts

A gap is per side: a 5 mm pin with a 0.2 mm gap goes in a 5.4 mm hole. The gaps
already include the printer's error, so add no hole allowance on top.

| Fit | Gap per side |
| --- | --- |
| Press: stays without glue | 0 to 0.1 mm |
| Sliding: a lid, a pin that turns | 0.2 mm |
| Print-in-place: printed together, must come free | 0.3 to 0.5 mm, at least 0.3 (P) |

- A press fit in PLA cracks rather than stretches: try it on a coupon first.
- Print-in-place needs loose bodies: build it only where SKILL.md allows
  several bodies. A gap above or below a body is at least two layers, 0.4 mm
  (P), because what is printed over it sags.

## Lettering

Only when `operations.md` lists `text`: letters at least 5 mm tall and 0.6 mm
deep or raised (three layers (P)), in a bold sans-serif, on the top face or a
side. Raised letters cannot go on the bed face.

## A fit-test coupon

Offer one when the part must fit real hardware or another part and its print
takes more than about an hour: the coupon prints in about 10 minutes. Build it
with `cad_build` like any part:

- a plate 1.5 mm thicker than its deepest feature, as small as they allow;
- only the features the part depends on, each three times: the table value,
  and 0.2 mm smaller and larger (0.1 mm for a printed fit, whose peg is a
  second small part);
- 1, 2 and 3 notches in the edge beside the variants, so the user can name the
  one that fit;
- printed in the part's orientation, material and settings.

Use the variant that fit in the real part, and tell the user its value so
later parts start from it. A print-in-place gap other than 0.3 mm belongs in
the printer profile's `min_clearance_mm`, which only the operator can change.
