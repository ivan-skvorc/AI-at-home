"""Decide whether a measured part meets what it was asked to meet.

Pure functions over the dict ``measure.measure_step`` returns and the expected
numbers under the names ``cad_build`` takes them. Nothing here imports the
extension API, the kernel or the Gateway, so the CAD eval and ``measure_cli``
judge a STEP file exactly as the tool does, outside the host.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from deerflow_extension_cad.build import MESH_STEPS

#: A bounding box side or a hole diameter matches within 0.01 mm or 0.1 %, whichever is larger.
#: The kernel's own noise is far below that; the slack is for the model's rounding.
LENGTH_TOLERANCE_MM = 0.01
LENGTH_TOLERANCE_RATIO = 0.001

MAX_HOLES = 400
#: Lines of left-out bodies one note names, and loops that drop work one answer names.
MAX_LINES_SAID = 5
#: A hole expected at a point, [d, x, y, z], is there when a measured hole of that diameter has its axis
#: within 0.05 mm or 0.1 % of the part's largest side of the point, whichever is larger. Any point on the
#: axis will do: the centre on the face it is drilled from, or a point beside the part on a side hole's line.
POSITION_TOLERANCE_MM = 0.05
POSITION_TOLERANCE_RATIO = 0.001
#: Holes the check names as not where they were expected; report.json lists every measured hole.
MAX_HOLES_LISTED = 12
#: A gap between bodies whose direction is within this angle of z lies across the layers.
VERTICAL_DEG = 10.0


def _close(expected: float, measured: float) -> bool:
    return abs(expected - measured) <= max(LENGTH_TOLERANCE_MM, LENGTH_TOLERANCE_RATIO * abs(expected))


def hole_diameter(entry: Any) -> float:
    """The diameter of an expected hole: a plain number, or the first of [d, x, y, z]."""
    return entry[0] if isinstance(entry, (list, tuple)) else entry


def canonical_holes(entries: Sequence[Any]) -> list[Any]:
    """Expected holes in one order, so the same holes listed another way are the same holes.

    By diameter; at one diameter plain numbers come first, then positioned holes by their point.
    """
    holes = [list(entry) if isinstance(entry, (list, tuple)) else entry for entry in entries]
    return sorted(holes, key=lambda entry: (entry[0], 1, *entry[1:]) if isinstance(entry, list) else (entry, 0, 0, 0, 0))


def _off_axis(point: Sequence[float], hole: Mapping[str, Any]) -> float:
    """How far *point* lies from the axis line of a measured hole (``axis`` is a unit vector)."""
    offset = [p - a for p, a in zip(point, hole["at"])]
    along = sum(o * d for o, d in zip(offset, hole["axis"]))
    return math.sqrt(sum((o - along * d) ** 2 for o, d in zip(offset, hole["axis"])))


def holes_of(measured: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Every measured hole: the part's own, or each body's in turn for a part of several bodies.

    measure.py measures a hole against its own body, so a captive pin does not fill its bore,
    and keeps the part's ``holes`` empty when there is more than one body.
    """
    bodies = measured.get("bodies")
    if isinstance(bodies, list):
        return [hole for body in bodies if isinstance(body, Mapping) for hole in body.get("holes") or []]
    return list(measured.get("holes") or [])


def _misplaced(positioned: list[list[float]], holes: Sequence[Mapping[str, Any]], tolerance: float) -> list[dict[str, Any]]:
    """The positioned holes that no measured hole of their diameter stands for, each with the nearest one.

    One measured hole stands for one expected hole: two expected at the same point need two holes
    there. The matching is a maximum matching, so an early guess never blocks a later hole.
    """
    located = [hole for hole in holes if isinstance(hole.get("at"), list) and isinstance(hole.get("axis"), list)]
    sized = [[k for k, hole in enumerate(located) if _close(entry[0], hole["diameter_mm"])] for entry in positioned]
    fits = [[k for k in sized[i] if _off_axis(entry[1:], located[k]) <= tolerance] for i, entry in enumerate(positioned)]
    owner: dict[int, int] = {}

    def claim(i: int, seen: set[int]) -> bool:
        for k in fits[i]:
            if k not in seen:
                seen.add(k)
                if k not in owner or claim(owner[k], seen):
                    owner[k] = i
                    return True
        return False

    for i in range(len(positioned)):
        claim(i, set())
    matched = set(owner.values())
    misplaced = []
    for i, entry in enumerate(positioned):
        if i in matched:
            continue
        nearest = min(sized[i], key=lambda k: _off_axis(entry[1:], located[k]), default=None)
        said: dict[str, Any] = {"expected": entry, "nearest_at": None}
        if nearest is not None:
            said.update(nearest_at=located[nearest]["at"], off_axis_mm=round(_off_axis(entry[1:], located[nearest]), 3))
        misplaced.append(said)
    return misplaced


def decide(measured: Mapping[str, Any], payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Compare what was measured on the re-imported STEP with what the part must meet.

    ``bodies`` (1 when not given) is how many separate solids the part is: a print-in-place hinge
    or a box with its lid. The volume of several is their sum and the bounding box their union.
    """
    voids = measured.get("enclosed_voids") or 0
    bodies = payload.get("bodies", 1)
    state = f"{measured['solids']} solid(s), valid={measured['valid']}, closed={measured['closed']}" + (f", {voids} sealed {'cavity' if voids == 1 else 'cavities'} inside" if voids else "")
    whole = measured["solids"] == bodies and measured["valid"] and measured["closed"]
    if bodies == 1:
        checks: list[dict[str, Any]] = [{"check": "one closed solid", "expected": "exactly one valid, closed solid", "measured": state, "passed": whole}]
    else:
        checks = [{"check": "closed solids", "expected": f"exactly {bodies} valid, closed solids", "measured": state, "passed": whole}]
    box = measured["bbox_mm"]
    checks.append({"check": "bounding box", "expected": list(payload["bbox_xyz_mm"]), "measured": box, "passed": len(box) == 3 and all(_close(e, m) for e, m in zip(payload["bbox_xyz_mm"], box))})
    if "volume_min_max_mm3" in payload:
        low, high = payload["volume_min_max_mm3"]
        slack = 1e-6 * high
        checks.append({"check": "volume", "expected": [low, high], "measured": measured["volume_mm3"], "passed": low - slack <= measured["volume_mm3"] <= high + slack})
    if "hole_diameters_mm" in payload:
        expected = canonical_holes(payload["hole_diameters_mm"])
        diameters = sorted(hole_diameter(entry) for entry in expected)
        holes = holes_of(measured)
        found = sorted(hole["diameter_mm"] for hole in holes)
        check = {"check": "holes", "expected": expected, "measured": found, "passed": len(diameters) == len(found) and all(_close(e, m) for e, m in zip(diameters, found))}
        positioned = [entry for entry in expected if isinstance(entry, list)]
        if positioned:
            tolerance = max(POSITION_TOLERANCE_MM, POSITION_TOLERANCE_RATIO * max(box, default=0.0))
            misplaced = _misplaced(positioned, holes, tolerance)
            if misplaced:
                # Both points, so the model can move the hole by the difference instead of guessing.
                check.update(passed=False, misplaced=misplaced[:MAX_HOLES_LISTED])
                if len(misplaced) > MAX_HOLES_LISTED:
                    check["misplaced_count"] = len(misplaced)
        if bodies == 1 and measured["solids"] != 1:
            # Holes are measured on one solid. An empty list would read as "your holes are gone".
            check.update(measured="not measured: the result is not one solid", passed=False)
        # The check compares diameters. A hole that stops inside the part is said, with how deep it goes.
        blind = sorted(hole["depth_mm"] for hole in holes if hole.get("through") is False)
        if blind:
            check["blind_depths_mm"] = blind
        checks.append(check)
    return checks


def notes_on(measured: Mapping[str, Any], bodies: int = 1) -> list[str]:
    """What the checks do not decide and a reader of the answer should still know. *bodies* is how many were expected."""
    notes = []
    solids = measured.get("solids")
    if isinstance(solids, int) and solids > 1 and solids != bodies:
        notes.append(f"The result is {solids} separate bodies. Bodies become one part only where they overlap or share a face, and a cut that goes right through a part leaves two.")
    bodies = measured.get("unused_bodies") or 0
    if bodies:
        lines = sorted({line for line in measured.get("unused_body_lines") or [] if isinstance(line, int)})
        where = f" (built on line {', '.join(map(str, lines[:MAX_LINES_SAID]))}{' and more' if len(lines) > MAX_LINES_SAID else ''})" if lines else ""
        notes.append(f"The script builds {bodies} bod{'y' if bodies == 1 else 'ies'}{where} that {'is' if bodies == 1 else 'are'} not part of the result: join {'it' if bodies == 1 else 'them'} with union(), or delete the lines.")
    loops = [dropped for dropped in measured.get("dropped_passes") or [] if isinstance(dropped, Mapping)]
    for dropped in loops[:MAX_LINES_SAID]:
        count, line = dropped.get("passes"), dropped.get("loop_line")
        if isinstance(count, int) and isinstance(line, int):
            notes.append(
                f"{count} pass{'' if count == 1 else 'es'} of the loop on line {line} do{'es' if count == 1 else ''} work on the part that is not in the result: "
                "carry the part through the loop, for example result = result.hole(...), or delete the work."
            )
    if len(loops) > MAX_LINES_SAID:
        notes.append("More loops than these do work that is not in the result.")
    if measured.get("unused_outline"):
        notes.append("The script draws an outline that is never extruded or cut; it is not part of the result.")
    voids = measured.get("enclosed_voids") or 0
    if voids:
        notes.append(f"The part has {voids} sealed {'cavity' if voids == 1 else 'cavities'} inside that cannot be reached from outside.")
    tolerance = (measured.get("mesh") or {}).get("tolerance_mm")
    if isinstance(tolerance, (int, float)) and tolerance > MESH_STEPS[0][0]:
        notes.append(f"The STL mesh is coarser than usual ({tolerance:g} mm off the surface at most) to keep the file small; the STEP file is exact.")
    crossing = [hole for hole in holes_of(measured) if isinstance(hole.get("walls"), int) and hole["walls"] > 1]
    if crossing:
        most = max(hole["walls"] for hole in crossing)
        notes.append(f"{len(crossing)} hole{'' if len(crossing) == 1 else 's'} pass{'es' if len(crossing) == 1 else ''} through {most} walls with air between and count{'s' if len(crossing) == 1 else ''} once: one drill pass is one hole.")
    return notes


def unchecked(measured: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    """What was measured and not asked about, under the name of the argument that would check it."""
    extra: dict[str, Any] = {}
    if "volume_min_max_mm3" not in payload:
        extra["volume_mm3"] = measured["volume_mm3"]
    if "hole_diameters_mm" not in payload:
        extra["hole_diameters_mm"] = sorted(hole["diameter_mm"] for hole in holes_of(measured))[:MAX_HOLES]
    return extra


def _towards(direction: Sequence[float]) -> str:
    """A direction as a reader takes it in: along an axis when it is one, else the vector."""
    for axis, component in zip("xyz", direction):
        if abs(abs(component) - 1.0) <= 1e-6:
            return f"along {'+' if component > 0 else '-'}{axis}"
    return f"along {[round(component, 3) for component in direction]}"


def gap_notes(measured: Mapping[str, Any], printer: Mapping[str, Any]) -> list[str]:
    """The smallest gap between bodies, and gaps the operator's printer may close. Notes, never checks.

    *printer* is the operator's profile (``min_clearance_mm``, ``layer_mm``). Bodies are numbered
    from 1 here, in the order of ``measured.bodies``.
    """
    gaps = [gap for gap in measured.get("gaps") or [] if isinstance(gap, Mapping) and type(gap.get("gap_mm")) in (int, float) and isinstance(gap.get("bodies"), list) and len(gap["bodies"]) == 2]
    if not gaps:
        return []

    def between(gap: Mapping[str, Any]) -> str:
        first, second = gap["bodies"]
        direction = gap.get("direction")
        return f"between body {first + 1} and body {second + 1}" + (f", {_towards(direction)}" if isinstance(direction, list) and len(direction) == 3 else "")

    smallest = gaps[0]
    unsure = " (not every pair of bodies was measured)" if measured.get("gaps_incomplete") else ""
    notes = [f"The smallest gap between bodies is {smallest['gap_mm']:g} mm, {between(smallest)}{unsure}."]
    clearance = printer.get("min_clearance_mm")
    if isinstance(clearance, (int, float)) and smallest["gap_mm"] < clearance:
        notes.append(f"That gap is under the printer's minimum clearance ({clearance:g} mm): printed as modelled, the bodies may fuse.")
    layer = printer.get("layer_mm")
    if isinstance(layer, (int, float)):
        across = math.cos(math.radians(VERTICAL_DEG))
        thin = [gap for gap in gaps if isinstance(gap.get("direction"), list) and len(gap["direction"]) == 3 and abs(gap["direction"][2]) >= across and gap["gap_mm"] < layer]
        for gap in thin[:MAX_LINES_SAID]:
            notes.append(f"The gap of {gap['gap_mm']:g} mm {between(gap)} is thinner than one layer ({layer:g} mm): the slicer may fill it and fuse the bodies.")
    return notes
