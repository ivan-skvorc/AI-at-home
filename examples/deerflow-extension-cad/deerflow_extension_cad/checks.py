"""Decide whether a measured part meets what it was asked to meet.

Pure functions over the dict ``measure.measure_step`` returns and the expected
numbers under the names ``cad_build`` takes them. Nothing here imports the
extension API, the kernel or the Gateway, so the CAD eval and ``measure_cli``
judge a STEP file exactly as the tool does, outside the host.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from deerflow_extension_cad.build import MESH_STEPS

#: A bounding box side or a hole diameter matches within 0.01 mm or 0.1 %, whichever is larger.
#: The kernel's own noise is far below that; the slack is for the model's rounding.
LENGTH_TOLERANCE_MM = 0.01
LENGTH_TOLERANCE_RATIO = 0.001

MAX_HOLES = 400
#: Lines of left-out bodies one note names, and loops that drop work one answer names.
MAX_LINES_SAID = 5


def _close(expected: float, measured: float) -> bool:
    return abs(expected - measured) <= max(LENGTH_TOLERANCE_MM, LENGTH_TOLERANCE_RATIO * abs(expected))


def decide(measured: Mapping[str, Any], payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Compare what was measured on the re-imported STEP with what the part must meet."""
    voids = measured.get("enclosed_voids") or 0
    checks: list[dict[str, Any]] = [
        {
            "check": "one closed solid",
            "expected": "exactly one valid, closed solid",
            "measured": f"{measured['solids']} solid(s), valid={measured['valid']}, closed={measured['closed']}" + (f", {voids} sealed {'cavity' if voids == 1 else 'cavities'} inside" if voids else ""),
            "passed": measured["solids"] == 1 and measured["valid"] and measured["closed"],
        },
    ]
    box = measured["bbox_mm"]
    checks.append({"check": "bounding box", "expected": list(payload["bbox_xyz_mm"]), "measured": box, "passed": len(box) == 3 and all(_close(e, m) for e, m in zip(payload["bbox_xyz_mm"], box))})
    if "volume_min_max_mm3" in payload:
        low, high = payload["volume_min_max_mm3"]
        slack = 1e-6 * high
        checks.append({"check": "volume", "expected": [low, high], "measured": measured["volume_mm3"], "passed": low - slack <= measured["volume_mm3"] <= high + slack})
    if "hole_diameters_mm" in payload:
        expected = sorted(payload["hole_diameters_mm"])
        found = sorted(hole["diameter_mm"] for hole in measured["holes"])
        check = {"check": "holes", "expected": expected, "measured": found, "passed": len(expected) == len(found) and all(_close(e, m) for e, m in zip(expected, found))}
        if measured["solids"] != 1:
            # Holes are measured on one solid. An empty list would read as "your holes are gone".
            check.update(measured="not measured: the result is not one solid", passed=False)
        # The check compares diameters. A hole that stops inside the part is said, with how deep it goes.
        blind = sorted(hole["depth_mm"] for hole in measured["holes"] if hole.get("through") is False)
        if blind:
            check["blind_depths_mm"] = blind
        checks.append(check)
    return checks


def notes_on(measured: Mapping[str, Any]) -> list[str]:
    """What the checks do not decide and a reader of the answer should still know."""
    notes = []
    solids = measured.get("solids")
    if isinstance(solids, int) and solids > 1:
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
    crossing = [hole for hole in measured.get("holes") or [] if isinstance(hole.get("walls"), int) and hole["walls"] > 1]
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
        extra["hole_diameters_mm"] = sorted(hole["diameter_mm"] for hole in measured["holes"])[:MAX_HOLES]
    return extra
