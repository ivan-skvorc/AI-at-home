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
gap between them are one hole only when the gap is air and both sides have the
same diameter: one drill pass through both walls of an enclosure.

A hole's diameter is the smallest cylinder diameter of its chain, the drill
diameter. A chain without a cylinder (a pure taper or a dimple) is not counted.

Known limits, stated rather than hidden: the cavity of a shelled cylinder (a
cup) is geometrically a large blind hole and is reported as one; a blind hole
with a domed floor reads as through, because only cylinders and cones are
chained.

This module needs the kernel and runs in the worker process only.
"""

from __future__ import annotations

import math
from pathlib import Path

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepGProp import BRepGProp_Face
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder
from OCP.gp import gp_Pnt, gp_Vec
from OCP.TopAbs import TopAbs_IN

# Tolerances, millimetres unless noted.
DIR_TOL = 1e-6  # |d1 - d2| for two unit axis directions
POS_TOL = 1e-4  # distance between two axis lines
RADIUS_TOL = 1e-5
AXIAL_TOL = 1e-5  # two axial coordinates are the same
ARC_TOL = 1e-3  # radians short of 2*pi that still counts as a full circle
PROBE_EPS = 1e-3  # how far beyond a hole end the axis is probed
CLASSIFY_TOL = 1e-7
_SWEEP = (0.3711, 0.5373, 0.7577)  # generic direction for the grouping sweep


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


class _Classifier:
    def __init__(self, classifier, direction, anchor):
        self._c = classifier
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
        self._c.Perform(gp_Pnt(*self.point(a, ru, rv)), CLASSIFY_TOL)
        return self._c.State() == TopAbs_IN

    def air_inside(self, seg):
        return not self.in_material(0.5 * (seg["a0"] + seg["a1"]))


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
    for group in _group_by_axis(records):
        direction, anchor = group[0]["dir"], group[0]["anchor"]
        probe = _Classifier(classifier, direction, anchor)
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
            same_drill = not last["cone"] and not seg["cone"] and abs(last["r1"] - seg["r0"]) <= RADIUS_TOL and not probe.in_material(0.5 * (seg["a0"] + last["a1"]))
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
            holes.append((probe.point(a0), hole))
    holes.sort(key=lambda item: (item[1]["diameter_mm"], item[0]))
    return [hole for _, hole in holes]


def measure_step(path: Path, cq) -> dict:
    """Re-import the STEP at *path* and report what it holds. *cq* is the imported cadquery module."""
    solids = [solid for value in cq.importers.importStep(str(path)).vals() for solid in value.Solids()]
    measured: dict = {"solids": len(solids), "valid": False, "closed": False, "bbox_mm": [], "volume_mm3": 0.0, "holes": []}
    if not solids:
        return measured
    shells = [shell for solid in solids for shell in solid.Shells()]
    # isValid() alone is true for a wire or an open shell, and Volume() then returns a
    # length or an area: a solid counts only with closed shells and a volume of its own.
    measured["valid"] = all(solid.isValid() and solid.Volume() > 0 for solid in solids)
    measured["closed"] = bool(shells) and all(BRep_Tool.IsClosed_s(shell.wrapped) for shell in shells)
    if len(shells) > len(solids):
        # Sealed cavities are legal geometry and usually a mistake; they are reported, not refused.
        measured["enclosed_voids"] = len(shells) - len(solids)
    boxes = [solid.BoundingBox() for solid in solids]
    low = [min(getattr(box, axis + "min") for box in boxes) for axis in "xyz"]
    high = [max(getattr(box, axis + "max") for box in boxes) for axis in "xyz"]
    measured["bbox_mm"] = [round(top - bottom, 4) for bottom, top in zip(low, high)]
    measured["volume_mm3"] = round(sum(solid.Volume() for solid in solids), 3)
    if len(solids) == 1:
        measured["holes"] = measure_holes(solids[0])
    return measured
