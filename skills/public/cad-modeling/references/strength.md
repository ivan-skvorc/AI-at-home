# Loads and strength by hand

Work out every load path on paper and write the arithmetic into your answer.
These are estimates for a model that was never printed; say so.

## Material values to start from

Typical values for printed parts, along the layers. Across layers (pulling
layers apart) take half. The filament's own data sheet wins when the user
names one.

| Material | Tensile strength | Shear (about 0.6 x tensile) | Young's modulus | Softens near |
| --- | --- | --- | --- | --- |
| PLA | 40-50 MPa | 25 MPa | 3.0 GPa | 55 C |
| PETG | 35-45 MPa | 22 MPa | 2.0 GPa | 75 C |
| ABS / ASA | 30-40 MPa | 20 MPa | 2.0 GPa | 95 C |

Use a safety factor of at least 3 on these for a printed part under a steady
load, and 5 where it is hit, cycled or warm (a car, a window).

## Forces

- Weight: F = m x 9.81 N (a 2.5 kg tablet is 24.5 N).
- A stand or a leaning load: take moments about the pivot. A strut at angle a
  from the rest, carrying a moment M about the hinge at distance d, takes
  F = M / (d x sin a). Shallow struts take large forces: work out both ends of
  the range.
- Tipping: the stand is stable when the combined centre of mass stays inside
  the footprint with margin in every position. `report.json` gives each body's
  centre of mass (solid; scale by the slicer's grams when infill is low);
  combine them with the load's.
- Friction holding a position: F_hold = mu x N, mu about 0.3 for PLA on PLA.
  Do not rely on it alone for anything that drops when it slips.
- A screw drive: torque T = F x p / (2 pi x eta), with p the pitch and eta about
  0.3 for a printed screw. A fingertip gives about 0.3 N m on a 20 mm knob.

## Stresses

- Pin in shear: tau = F / (n x pi d^2 / 4), n = 1 for single shear, 2 for a pin
  held on both sides.
- Bearing on a printed hole: sigma = F / (d x t), t the wall length the pin
  bears on; keep it under about a third of tensile.
- Bending of a beam (strut, arm, clip): sigma = M x c / I. Rectangle b x h bent
  across h: I = b h^3 / 12, c = h / 2, so sigma = 6 M / (b h^2). Round rod:
  sigma = 32 M / (pi d^3).
- Cantilever deflection: delta = F L^3 / (3 E I).
- A snap fit flexes safely while the strain stays under about 2 % for PLA and
  4 % for PETG: strain = 1.5 x delta x h / L^2 for a straight arm.
- Layer direction: a load that pulls layers apart takes half the strength.
  Turn the body in the print layout so the load runs along the layers, or
  thicken it.

## What to report

For each part that carries load: the load case, the force, the stress or
strain, the limit used, and the safety factor. Name the weakest point. When a
factor is under 3, change the design (thicker, a fillet at the root, another
print orientation) and check again.
