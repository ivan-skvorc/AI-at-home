"""Measure the part that was written, not the part that was meant.

``measure_step`` re-imports the STEP file the build just exported and reports
what is in it: how many solids, whether they are valid and closed, the bounding
box, the volume and the drilled holes. The tool compares these numbers with the
ones the model said the part must meet; the model does not get a vote.

What counts as a hole
---------------------
A hole is a chain of coaxial, concave surfaces of revolution (cylinders, plus
cones that touch a cylinder) that

1. is concave: the outward face normal points towards the axis. That separates
   a hole wall from the outside of a cylinder or a boss. A point-in-solid test
   on the axis is not enough (the axis of a tube's outer face lies in the bore);
2. spans the full 360 degrees at one radius, as one face or several. Fillets,
   rounded pocket corners and the 180 degree ends of a slot fail this, and so
   does a hole that breaks out through an edge;
3. has air inside: the axis point at mid height is not in material (this
   rejects the outer wall of a groove around a solid island). When two full
   walls on one axis overlap axially, the wider one is a recess around a bored
   island and is dropped: a real stepped hole has walls that abut, never overlap;
4. is open at one end (blind) or at both (through). Closed at both ends is an
   enclosed void, not a hole.

Faces are grouped by axis line. On one axis, segments that touch are one hole
(a counterbore step, a countersink cone, a chamfered mouth). Segments with a
gap between them are one hole only when the whole gap is air, from the end of
one wall to the start of the next, and both sides have the same diameter: one
drill pass through both walls of an enclosure. Such a hole reports how many
walls it crosses. Two blind holes that face each other across a cavity each end
in material, so they stay two.

A hole's diameter is the smallest cylinder diameter of its chain, the drill
diameter. A chain without a cylinder (a pure taper or a dimple) is not counted.

Known limits, stated rather than hidden: the cavity of a shelled cylinder (a
cup) is geometrically a large blind hole and is reported as one; a blind hole
with a domed floor reads as through, because only cylinders and cones are
chained.

Where a hole is
---------------
Each hole says where it is entered (``at``, the point of its axis on the face it
opens into) and which way it runs from there into the part (``axis``, a unit
vector). A blind hole is entered at its open end. A through hole is entered
where it is widest (a counterbore, a countersink, a chamfered mouth); else from
the outside, when only one end has nothing more of the part beyond it along the
axis (the outer face of an enclosure wall); else at the end that lies further
along its axis's canonical direction, whose first non-zero component is
positive: the top of a vertical hole, the +x end of one along x.

Several bodies
--------------
A file of several solids (a print-in-place hinge, a kit modelled assembled) is
also measured body by body, in the file's order: each body's size, mass and
holes, with air told from material against that body alone, so a captive pin
does not fill its bore. The whole keeps ``holes`` empty, as before. The gaps
between bodies are listed smallest first: every pair closer than
``GAP_NEAR_MM`` and always the closest pair, each with the direction from the
first body to the second. Bodies that touch, overlap or sit inside one another
have a gap of 0.

``sampled_wall`` is separate because it is spent from a time budget: it casts
rays straight into the material from a grid of points on every face and
reports the shortest, which is the thinnest wall it found, not a proof that
none is thinner.

This module needs the kernel and runs in the worker process only (or in
``measure_cli``, which measures one STEP the same way).
"""

from __future__ import annotations

import math
import time
from pathlib import Path

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp_Face
from OCP.BRepTools import BRepTools
from OCP.BRepTopAdaptor import BRepTopAdaptor_FClass2d
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Pnt2d, gp_Vec
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.IntCurveSurface import IntCurveSurface_Tangent
from OCP.TopAbs import TopAbs_IN

# Tolerances, millimetres unless noted.
DIR_TOL = 1e-6  # |d1 - d2| for two unit axis directions
POS_TOL = 1e-4  # distance between two axis lines
RADIUS_TOL = 1e-5
AXIAL_TOL = 1e-5  # two axial coordinates are the same
ARC_TOL = 1e-3  # radians short of 2*pi that still counts as a full circle
PROBE_EPS = 1e-3  # how far beyond a hole end the axis is probed
CLASSIFY_TOL = 1e-7
# Material or air at a point is decided by counting surface crossings along a ray. These
# directions are generic on purpose: a ray along a grid of holes runs through the seam of
# every wall in its row, and the kernel's own classifier, which picks its rays from the
# faces, then retries hundreds of times (0.4 s a point on a part with half holes on an edge).
_RAYS = ((0.3411, 0.5873, 0.7340), (-0.6229, 0.2671, 0.7354), (0.7112, -0.6377, 0.2954))
_RAY_LENGTH = 1e7  # past any part: sizes are capped at 1e5
_RAY_NEAR = 1e-6  # a crossing this close to the start means the point is on a surface
_SWEEP = (0.3711, 0.5373, 0.7577)  # generic direction for the grouping sweep
#: A hole's entry point is said to 0.01 mm, its direction to four decimals.
AT_DIGITS = 2
AXIS_DIGITS = 4
#: Pairs of bodies closer than this are all listed: every printer clearance and layer height is below it.
GAP_NEAR_MM = 2.0
#: Exact distances worked out at most: every pair of 20 bodies, the most a part may expect.
MAX_GAP_PAIRS = 190
#: Gaps one measurement lists, smallest first.
MAX_GAPS_LISTED = 20
#: Two bodies this close touch: no slicer leaves a gap that small.
GAP_TOUCH_MM = 1e-6
#: The sampled wall: grids of points per face, coarse first, so a short budget still reaches every face once.
WALL_GRIDS = (2, 5)
WALL_SECONDS = 1.0
#: A crossing this close to a sample point is the face the ray starts on.
_WALL_NEAR = 1e-4


def _tidy(values, ndigits):
    # + 0.0 turns -0.0 into 0.0, which a reader would otherwise take for a sign that means something.
    return [round(value, ndigits) + 0.0 for value in values]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _canonical(d):
    """Flip a unit vector so the first significant component is positive."""
    for c in d:
        if abs(c) > 1e-9:
            return (d, 1.0) if c > 0 else ((-d[0], -d[1], -d[2]), -1.0)
    raise ValueError("zero axis direction")


def _face_record(face):
    """Return a dict for a concave cylindrical or conical face, else None."""
    adaptor = BRepAdaptor_Surface(face, True)
    kind = adaptor.GetType()
    if kind == GeomAbs_Cylinder:
        surf = adaptor.Cylinder()
        radius = surf.Radius()
        sin_a, cos_a = 0.0, 1.0
    elif kind == GeomAbs_Cone:
        surf = adaptor.Cone()
        radius = surf.RefRadius()
        sin_a, cos_a = math.sin(surf.SemiAngle()), math.cos(surf.SemiAngle())
    else:
        return None

    axis = surf.Axis()
    loc = (axis.Location().X(), axis.Location().Y(), axis.Location().Z())
    raw_dir = (axis.Direction().X(), axis.Direction().Y(), axis.Direction().Z())
    umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)

    # Concave or convex: outward normal against the radial direction.
    pnt, nrm = gp_Pnt(), gp_Vec()
    BRepGProp_Face(face).Normal(0.5 * (umin + umax), 0.5 * (vmin + vmax), pnt, nrm)
    p = (pnt.X(), pnt.Y(), pnt.Z())
    rel = (p[0] - loc[0], p[1] - loc[1], p[2] - loc[2])
    along = _dot(rel, raw_dir)
    radial = (rel[0] - along * raw_dir[0], rel[1] - along * raw_dir[1], rel[2] - along * raw_dir[2])
    if _dot((nrm.X(), nrm.Y(), nrm.Z()), radial) >= 0:
        return None  # convex: outside of a cylinder, boss, outer fillet, chamfer on a boss

    d, sign = _canonical(raw_dir)
    base = _dot(loc, d)
    anchor = (loc[0] - base * d[0], loc[1] - base * d[1], loc[2] - base * d[2])
    ends = []
    for v in (vmin, vmax):
        ends.append((base + sign * v * cos_a, abs(radius + v * sin_a)))
    ends.sort()
    return {
        "cone": kind == GeomAbs_Cone,
        "dir": d,
        "anchor": anchor,  # the point of the axis line closest to the origin
        "a0": ends[0][0],
        "a1": ends[1][0],
        "r0": ends[0][1],  # radius at a0
        "r1": ends[1][1],  # radius at a1
        "arc": umax - umin,
    }


def _same_axis(a, b):
    return math.dist(a["dir"], b["dir"]) <= DIR_TOL and math.dist(a["anchor"], b["anchor"]) <= POS_TOL


def _group_by_axis(records):
    """Union-find over a sweep, so a few thousand faces stay cheap."""
    order = sorted(range(len(records)), key=lambda i: _dot(records[i]["anchor"], _SWEEP))
    keys = [_dot(records[i]["anchor"], _SWEEP) for i in order]
    parent = list(range(len(records)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for x, i in enumerate(order):
        for y in range(x + 1, len(order)):
            if keys[y] - keys[x] > POS_TOL:
                break
            j = order[y]
            if _same_axis(records[i], records[j]):
                parent[find(j)] = find(i)
    groups = {}
    for i in range(len(records)):
        groups.setdefault(find(i), []).append(records[i])
    return list(groups.values())


def _cylinder_segments(faces):
    """Axial intervals where cylinder faces of one radius cover 360 degrees."""
    segments = []
    if not faces:
        return segments  # an axis that carries cones only: a countersink through thin sheet, a tapered cut
    faces = sorted(faces, key=lambda f: f["r0"])
    cluster = []
    for f in faces + [None]:
        if f is not None and (not cluster or f["r0"] - cluster[-1]["r0"] <= RADIUS_TOL):
            cluster.append(f)
            continue
        cuts = sorted({c for g in cluster for c in (g["a0"], g["a1"])})
        merged = [cuts[0]]
        for c in cuts[1:]:
            if c - merged[-1] > AXIAL_TOL:
                merged.append(c)
        radius = cluster[0]["r0"]
        current = None
        for lo, hi in zip(merged, merged[1:]):
            mid = 0.5 * (lo + hi)
            arc = sum(g["arc"] for g in cluster if g["a0"] < mid < g["a1"])
            if arc >= 2 * math.pi - ARC_TOL:
                if current is not None and lo - current["a1"] <= AXIAL_TOL:
                    current["a1"] = hi
                else:
                    current = {"cone": False, "a0": lo, "a1": hi, "r0": radius, "r1": radius}
                    segments.append(current)
            else:
                current = None
        cluster = [f] if f is not None else []
    return segments


def _cone_segments(faces):
    """Cone faces that share their ends and together cover 360 degrees."""
    segments = []
    used = [False] * len(faces)
    for i, f in enumerate(faces):
        if used[i]:
            continue
        arc = 0.0
        for j in range(i, len(faces)):
            g = faces[j]
            if not used[j] and all(abs(f[k] - g[k]) <= max(AXIAL_TOL, RADIUS_TOL) for k in ("a0", "a1", "r0", "r1")):
                used[j] = True
                arc += g["arc"]
        if arc >= 2 * math.pi - ARC_TOL:
            segments.append({"cone": True, "a0": f["a0"], "a1": f["a1"], "r0": f["r0"], "r1": f["r1"]})
    return segments


def _by_ray(rays, point):
    """True or False from an odd or even number of clean crossings, None when no ray is clean."""
    for direction in _RAYS:
        rays.Perform(gp_Lin(point, gp_Dir(*direction)), 0.0, _RAY_LENGTH)
        if not rays.IsDone():
            continue
        crossings = rays.NbPnt()
        # Clean: every crossing passes through the inside of a face, not along an edge
        # (two faces would both report it) and not tangent to it (no crossing at all).
        if all(rays.State(i) == TopAbs_IN and rays.Transition(i) != IntCurveSurface_Tangent and rays.WParameter(i) > _RAY_NEAR for i in range(1, crossings + 1)):
            return crossings % 2 == 1
    return None


class _Classifier:
    def __init__(self, classifier, rays, direction, anchor):
        self._c = classifier
        self._rays = rays
        self._d = direction
        self._o = anchor
        # two unit vectors perpendicular to the axis
        ref = (1.0, 0.0, 0.0) if abs(direction[0]) < 0.9 else (0.0, 1.0, 0.0)
        u = (
            direction[1] * ref[2] - direction[2] * ref[1],
            direction[2] * ref[0] - direction[0] * ref[2],
            direction[0] * ref[1] - direction[1] * ref[0],
        )
        n = math.sqrt(_dot(u, u))
        self._u = (u[0] / n, u[1] / n, u[2] / n)
        self._v = (
            direction[1] * self._u[2] - direction[2] * self._u[1],
            direction[2] * self._u[0] - direction[0] * self._u[2],
            direction[0] * self._u[1] - direction[1] * self._u[0],
        )

    def point(self, a, ru=0.0, rv=0.0):
        return tuple(self._o[k] + a * self._d[k] + ru * self._u[k] + rv * self._v[k] for k in range(3))

    def in_material(self, a, ru=0.0, rv=0.0):
        point = gp_Pnt(*self.point(a, ru, rv))
        counted = self._by_ray(point)
        if counted is not None:
            return counted
        # No clean ray: the point is on a surface, or every ray grazed an edge. The kernel decides.
        self._c.Perform(point, CLASSIFY_TOL)
        return self._c.State() == TopAbs_IN

    def _by_ray(self, point):
        return _by_ray(self._rays, point)

    def air_inside(self, seg):
        return not self.in_material(0.5 * (seg["a0"] + seg["a1"]))

    def opens_to_outside(self, a, sign):
        """Whether the axis from *a* onwards, away from the hole (*sign* +1 or -1), meets no more of the part."""
        d = tuple(sign * c for c in self._d)
        self._rays.Perform(gp_Lin(gp_Pnt(*self.point(a)), gp_Dir(*d)), 0.0, _RAY_LENGTH)
        return not (self._rays.IsDone() and self._rays.NbPnt() > 0)


def _drop_recess_walls(segments):
    """Of two full walls that overlap axially, keep the narrower (the bore of an island)."""
    keep = []
    for s in segments:
        narrow = min(s["r0"], s["r1"])
        inner = any(o is not s and max(o["r0"], o["r1"]) < narrow - RADIUS_TOL and min(s["a1"], o["a1"]) - max(s["a0"], o["a0"]) > AXIAL_TOL for o in segments)
        if not inner:
            keep.append(s)
    return keep


def measure_holes(solid, ndigits: int = 4) -> list[dict]:
    """Return the drilled holes of one cadquery Solid, smallest diameter first."""
    records = [record for record in (_face_record(face.wrapped) for face in solid.Faces()) if record is not None]
    holes = []
    classifier = BRepClass3d_SolidClassifier(solid.wrapped) if records else None
    rays = IntCurvesFace_ShapeIntersector()
    if records:
        rays.Load(solid.wrapped, CLASSIFY_TOL)
    for group in _group_by_axis(records):
        direction, anchor = group[0]["dir"], group[0]["anchor"]
        probe = _Classifier(classifier, rays, direction, anchor)
        segments = _cylinder_segments([f for f in group if not f["cone"]])
        segments += _cone_segments([f for f in group if f["cone"]])
        segments = _drop_recess_walls([s for s in segments if probe.air_inside(s)])
        segments.sort(key=lambda s: (s["a0"], s["a1"]))

        chains, chain = [], []
        for seg in segments:
            if not chain:
                chain = [seg]
                continue
            last = max(chain, key=lambda s: s["a1"])
            gap = seg["a0"] - last["a1"]
            # Air at both ends of the gap as well as in its middle: a blind hole ends in
            # material, and two of them facing each other across a cavity are not one pass.
            same_drill = (
                gap > AXIAL_TOL
                and not last["cone"]
                and not seg["cone"]
                and abs(last["r1"] - seg["r0"]) <= RADIUS_TOL
                and not any(probe.in_material(a) for a in (last["a1"] + PROBE_EPS, 0.5 * (seg["a0"] + last["a1"]), seg["a0"] - PROBE_EPS))
            )
            if same_drill:
                seg = {**seg, "new_wall": True}
            if gap <= AXIAL_TOL or same_drill:
                chain.append(seg)
            else:
                chains.append(chain)
                chain = [seg]
        if chain:
            chains.append(chain)

        for chain in chains:
            cylinders = sorted({round(2 * s["r0"], ndigits) for s in chain if not s["cone"]})
            if not cylinders:
                continue  # a pure cone is a taper or a dimple, not a drilled hole
            a0 = min(s["a0"] for s in chain)
            a1 = max(s["a1"] for s in chain)
            open_lo = not probe.in_material(a0 - PROBE_EPS)
            open_hi = not probe.in_material(a1 + PROBE_EPS)
            if not (open_lo or open_hi):
                continue  # an enclosed void
            cones = sorted({round(2 * max(s["r0"], s["r1"]), ndigits) for s in chain if s["cone"]})
            diameter = cylinders[0]
            larger, larger_kind = None, None
            for value, kind in [(c, "counterbore") for c in cylinders[1:]] + [(c, "countersink") for c in cones]:
                if value > diameter + 10**-ndigits and (larger is None or value > larger):
                    larger, larger_kind = value, kind
            hole = {"diameter_mm": diameter, "through": open_lo and open_hi, "depth_mm": round(a1 - a0, ndigits)}
            if larger is not None:
                hole["larger_diameter_mm"], hole["larger_kind"] = larger, larger_kind
            walls = 1 + sum(1 for s in chain if s.get("new_wall"))
            if walls > 1:
                hole["walls"] = walls
            if open_lo and open_hi:
                wide = [s for s in chain if round(2 * max(s["r0"], s["r1"]), ndigits) == larger] if larger is not None else []
                if wide:
                    entry_hi = sum(s["a0"] + s["a1"] for s in wide) / len(wide) >= a0 + a1
                else:
                    # An end that opens into the part's own cavity (the inside of an enclosure wall) is the exit.
                    entry_hi = probe.opens_to_outside(a1 + PROBE_EPS, 1) or not probe.opens_to_outside(a0 - PROBE_EPS, -1)
            else:
                entry_hi = open_hi
            hole["at"] = _tidy(probe.point(a1 if entry_hi else a0), AT_DIGITS)
            hole["axis"] = _tidy([-c for c in direction] if entry_hi else direction, AXIS_DIGITS)
            holes.append((probe.point(a0), hole))
    holes.sort(key=lambda item: (item[1]["diameter_mm"], item[0]))
    return [hole for _, hole in holes]


def _size(solids) -> dict:
    """Bounding box, volume, corners, centre of mass and area of one or more solids taken together."""
    boxes = [solid.BoundingBox() for solid in solids]
    low = [min(getattr(box, axis + "min") for box in boxes) for axis in "xyz"]
    high = [max(getattr(box, axis + "max") for box in boxes) for axis in "xyz"]
    volumes = [solid.Volume() for solid in solids]
    total = sum(volumes)
    centres = [solid.Center().toTuple() for solid in solids]
    return {
        "bbox_mm": [round(top - bottom, 4) for bottom, top in zip(low, high)],
        "volume_mm3": round(total, 3),
        "bbox_min_mm": _tidy(low, 4),
        "bbox_max_mm": _tidy(high, 4),
        # Weighted by volume; None only for a shape with no volume, which is not valid either.
        "centre_of_mass_mm": _tidy([sum(v * c[k] for v, c in zip(volumes, centres)) / total for k in range(3)], 4) if total > 0 else None,
        "area_mm2": round(sum(solid.Area() for solid in solids), 3),
    }


def _shells_of(solids) -> tuple[bool, bool, int]:
    """Valid, closed, and the number of sealed cavities."""
    shells = [shell for solid in solids for shell in solid.Shells()]
    # isValid() alone is true for a wire or an open shell, and Volume() then returns a
    # length or an area: a solid counts only with closed shells and a volume of its own.
    valid = all(solid.isValid() and solid.Volume() > 0 for solid in solids)
    closed = bool(shells) and all(BRep_Tool.IsClosed_s(shell.wrapped) for shell in shells)
    return valid, closed, len(shells) - len(solids)


def _body(solid) -> dict:
    valid, closed, voids = _shells_of([solid])
    body: dict = {"valid": valid, "closed": closed}
    if voids > 0:
        body["enclosed_voids"] = voids
    body.update(_size([solid]))
    body["holes"] = measure_holes(solid)
    return body


def _box_gap(a, b) -> float:
    """Distance between two bounding boxes: never more than the distance between what they hold."""
    (a_low, a_high), (b_low, b_high) = a, b
    return math.sqrt(sum(max(0.0, b_low[k] - a_high[k], a_low[k] - b_high[k]) ** 2 for k in range(3)))


def _inside(solid, point: gp_Pnt) -> bool:
    rays = IntCurvesFace_ShapeIntersector()
    rays.Load(solid.wrapped, CLASSIFY_TOL)
    inside = _by_ray(rays, point)
    if inside is None:
        inside = BRepClass3d_SolidClassifier(solid.wrapped, point, CLASSIFY_TOL).State() == TopAbs_IN
    return inside


def _gap(solids, i: int, j: int, boxes_meet: bool) -> dict | None:
    """The gap between bodies *i* and *j*, or None when the kernel cannot work it out."""
    distance = BRepExtrema_DistShapeShape(solids[i].wrapped, solids[j].wrapped)
    if not distance.IsDone() or distance.NbSolution() < 1:
        return None
    value = distance.Value()
    p, q = distance.PointOnShape1(1), distance.PointOnShape2(1)
    at = ((p.X() + q.X()) / 2, (p.Y() + q.Y()) / 2, (p.Z() + q.Z()) / 2)
    direction, inner = None, None
    if value > GAP_TOUCH_MM and boxes_meet:
        # No surface of one meets the other, so the kernel measured surface to surface; one body can
        # still sit in the other's material. Then the point said is on the inner body.
        inner = q if _inside(solids[i], q) else p if _inside(solids[j], p) else None
    if inner is not None:
        value, at = 0.0, (inner.X(), inner.Y(), inner.Z())
    elif value > GAP_TOUCH_MM:
        direction = _tidy([(q.X() - p.X()) / value, (q.Y() - p.Y()) / value, (q.Z() - p.Z()) / value], AXIS_DIGITS)
    else:
        value = 0.0
    return {"bodies": [i, j], "gap_mm": round(value, 4) + 0.0, "direction": direction, "at_mm": _tidy(at, AT_DIGITS)}


def body_gaps(solids) -> tuple[list[dict], bool]:
    """Gaps between bodies, smallest first: every pair closer than GAP_NEAR_MM and always the closest pair.

    Also says whether every pair that could matter was measured. Pairs are taken in the
    order of their bounding boxes' distance, which no pair's gap can be below, so the
    search stops once no further pair can be near or the smallest.
    """
    boxes = []
    for solid in solids:
        box = solid.BoundingBox()
        boxes.append(((box.xmin, box.ymin, box.zmin), (box.xmax, box.ymax, box.zmax)))
    pairs = sorted((_box_gap(boxes[i], boxes[j]), i, j) for i in range(len(solids)) for j in range(i + 1, len(solids)))
    found: list[dict] = []
    smallest, complete, tried = math.inf, True, 0
    for lower, i, j in pairs:
        if lower > max(GAP_NEAR_MM, smallest):
            break
        if tried >= MAX_GAP_PAIRS:
            complete = False
            break
        tried += 1
        gap = _gap(solids, i, j, lower == 0)
        if gap is None:
            complete = False
            continue
        smallest = min(smallest, gap["gap_mm"])
        found.append(gap)
    found.sort(key=lambda gap: (gap["gap_mm"], gap["bodies"]))
    listed = [gap for index, gap in enumerate(found) if index == 0 or gap["gap_mm"] <= GAP_NEAR_MM]
    return listed[:MAX_GAPS_LISTED], complete


def step_solids(path: Path, cq) -> list:
    """The solids of the STEP at *path*, in the file's order. *cq* is the imported cadquery module."""
    return [solid for value in cq.importers.importStep(str(path)).vals() for solid in value.Solids()]


def measure_step(path: Path, cq) -> dict:
    """Re-import the STEP at *path* and report what it holds. *cq* is the imported cadquery module."""
    return measure_solids(step_solids(path, cq))


def measure_solids(solids: list) -> dict:
    """Report what *solids* hold, as one part: the keys of one solid first, then what several bodies add."""
    measured: dict = {"solids": len(solids), "valid": False, "closed": False, "bbox_mm": [], "volume_mm3": 0.0, "holes": []}
    if not solids:
        return measured
    measured["valid"], measured["closed"], voids = _shells_of(solids)
    if voids > 0:
        # Sealed cavities are legal geometry and usually a mistake; they are reported, not refused.
        measured["enclosed_voids"] = voids
    measured.update(_size(solids))
    if len(solids) == 1:
        measured["holes"] = measure_holes(solids[0])
    else:
        # The whole keeps no holes: a hole is a feature of one body, and the checks of one solid read the whole.
        measured["bodies"] = [_body(solid) for solid in solids]
        measured["gaps"], complete = body_gaps(solids)
        if not complete:
            measured["gaps_incomplete"] = True
    return measured


def sampled_wall(solids, seconds: float = WALL_SECONDS) -> dict:
    """The thinnest wall found by rays cast straight into the material from points on every face.

    A sample is a grid point inside a face; its ray runs against the outward normal
    and the first surface it meets ends the wall. Every face gets the coarse grid
    before any gets the fine one, and sampling stops when *seconds* are spent
    (``wall_sampling_complete`` is then false). A wall thinner than every sampled one
    can exist between samples.
    """
    deadline = time.monotonic() + seconds
    thinnest, where, samples, complete = None, None, 0, True
    loaded: dict[int, IntCurvesFace_ShapeIntersector] = {}

    def faces():
        for grid in WALL_GRIDS:
            for index, solid in enumerate(solids):
                for face in solid.Faces():
                    yield grid, index, face.wrapped

    for grid, index, face in faces():
        if time.monotonic() >= deadline:
            complete = False
            break
        rays = loaded.get(index)
        if rays is None:
            rays = loaded[index] = IntCurvesFace_ShapeIntersector()
            rays.Load(solids[index].wrapped, CLASSIFY_TOL)
        umin, umax, vmin, vmax = BRepTools.UVBounds_s(face)
        within = BRepTopAdaptor_FClass2d(face, CLASSIFY_TOL)
        surface = BRepGProp_Face(face)
        for i in range(grid):
            for k in range(grid):
                u, v = umin + (i + 0.5) / grid * (umax - umin), vmin + (k + 0.5) / grid * (vmax - vmin)
                if within.Perform(gp_Pnt2d(u, v)) != TopAbs_IN:
                    continue  # in a hole of the face, or outside its trimmed outline
                point, normal = gp_Pnt(), gp_Vec()
                surface.Normal(u, v, point, normal)
                length = normal.Magnitude()
                if length < 1e-12:
                    continue  # a degenerate point: the apex of a cone, the pole of a sphere
                rays.PerformNearest(gp_Lin(point, gp_Dir(-normal.X() / length, -normal.Y() / length, -normal.Z() / length)), _WALL_NEAR, _RAY_LENGTH)
                samples += 1
                if rays.IsDone() and rays.NbPnt() > 0 and (thinnest is None or rays.WParameter(1) < thinnest):
                    thinnest, where = rays.WParameter(1), (point.X(), point.Y(), point.Z())
    return {
        "thinnest_wall_sampled_mm": None if thinnest is None else round(thinnest, 3),
        "thinnest_wall_at_mm": None if where is None else _tidy(where, AT_DIGITS),
        "wall_samples": samples,
        "wall_sampling_complete": complete,
    }
