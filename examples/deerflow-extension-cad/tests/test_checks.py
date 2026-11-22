"""The checks on their own: what decides pass or fail, outside the host.

``checks.py`` is what ``cad_build``, ``measure_cli`` and the CAD eval all judge
a part with, so it must import where the extension API is not installed. These
tests need no CAD kernel.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: Run in a fresh interpreter with the extension API made unimportable, the way a host-free caller sees the package.
WITHOUT_API = "import sys; sys.path.insert(0, {root!r}); sys.modules['deerflow_extension_api'] = None\n"


def _without_api(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", "-c", WITHOUT_API.format(root=str(ROOT)) + code], capture_output=True, text=True, timeout=120, check=False)


def test_the_checks_import_and_decide_without_the_extension_api():
    code = (
        "import json\n"
        "from deerflow_extension_cad import checks\n"
        "measured = {'solids': 1, 'valid': True, 'closed': True, 'bbox_mm': [60.0, 40.0, 6.0], 'volume_mm3': 14249.2, 'holes': []}\n"
        "verdict = checks.decide(measured, {'bbox_xyz_mm': [60, 40, 6]})\n"
        "print(json.dumps({'passed': all(c['passed'] for c in verdict), 'loaded': sorted(m for m, module in sys.modules.items() if module is not None and m.split('.')[0] in ('deerflow_extension_api', 'cadquery', 'OCP', 'numpy'))}))\n"
    )
    run = _without_api(code)
    assert run.returncode == 0, run.stderr
    # Nothing heavier than the checks themselves: no API, no kernel, no numpy.
    assert json.loads(run.stdout) == {"passed": True, "loaded": []}


def test_measure_cli_runs_as_a_program_without_the_extension_api():
    # What `python -I -m deerflow_extension_cad.measure_cli` does, with the API absent. Without
    # arguments it answers with its usage, in its own JSON, instead of failing on the package's import.
    code = "import runpy\nsys.argv = ['measure_cli']\nrunpy.run_module('deerflow_extension_cad.measure_cli', run_name='__main__')\n"
    run = _without_api(code)
    assert run.returncode == 2, run.stderr
    assert json.loads(run.stdout)["error"]["message"].startswith("usage: python -I -m deerflow_extension_cad.measure_cli")


# --- Holes expected where they are ------------------------------------------------

from deerflow_extension_cad import checks  # noqa: E402


def _plate(*holes: dict) -> dict:
    """A 60 x 40 x 6 plate as measure.py reports it, with the holes given."""
    return {"solids": 1, "valid": True, "closed": True, "bbox_mm": [60.0, 40.0, 6.0], "volume_mm3": 14000.0, "holes": list(holes)}


def _down(x: float, y: float, d: float = 4.0) -> dict:
    """A through hole drilled down from the top face at (x, y)."""
    return {"diameter_mm": d, "through": True, "depth_mm": 6.0, "at": [x, y, 6.0], "axis": [0.0, 0.0, -1.0]}


CORNERS = [(-15.0, -10.0), (-15.0, 10.0), (15.0, -10.0), (15.0, 10.0)]
#: A hole drilled into the +x side of the plate, halfway up, along -x.
SIDE = {"diameter_mm": 3.0, "through": False, "depth_mm": 12.0, "at": [30.0, 0.0, 3.0], "axis": [-1.0, 0.0, 0.0]}


def _holes_check(measured: dict, holes: list) -> dict:
    (check,) = [check for check in checks.decide(measured, {"bbox_xyz_mm": [60, 40, 6], "hole_diameters_mm": holes}) if check["check"] == "holes"]
    return check


def test_holes_at_their_stated_centres_pass_and_holes_a_millimetre_off_fail_with_both_points():
    measured = _plate(*(_down(x, y) for x, y in CORNERS))
    assert _holes_check(measured, [[4, x, y, 6] for x, y in CORNERS])["passed"] is True
    # Any point on the axis places the hole: the middle of the plate's thickness, or its bottom face.
    assert _holes_check(measured, [[4, x, y, 3] for x, y in CORNERS[:2]] + [[4, x, y, 0] for x, y in CORNERS[2:]])["passed"] is True
    off = _holes_check(measured, [[4, x + 1, y, 6] for x, y in CORNERS])
    assert off["passed"] is False and off["measured"] == [4.0, 4.0, 4.0, 4.0]
    assert sorted(map(tuple, (said["expected"] for said in off["misplaced"]))) == sorted((4, x + 1, y, 6) for x, y in CORNERS)
    for said in off["misplaced"]:
        # The point that was expected and the hole it is nearest to, a millimetre off its axis.
        assert said["nearest_at"] == [said["expected"][1] - 1, said["expected"][2], 6.0] and said["off_axis_mm"] == 1.0


def test_a_point_on_a_side_holes_axis_places_it_even_beside_the_part():
    measured = _plate(_down(-15, 0), SIDE)
    assert _holes_check(measured, [4, [3, 25, 0, 3]])["passed"] is True
    assert _holes_check(measured, [[4, -15, 0, 6], [3, 0, 0, 3]])["passed"] is True
    # The same point is a millimetre off the axis once the hole sits a millimetre higher.
    assert _holes_check(measured, [4, [3, 25, 0, 4]])["passed"] is False


def test_one_measured_hole_stands_for_one_expected_hole():
    measured = _plate(_down(-15, 0), _down(15, 0))
    twice = _holes_check(measured, [[4, -15, 0, 6], [4, -15, 0, 6]])
    assert twice["passed"] is False and [said["expected"] for said in twice["misplaced"]] == [[4, -15, 0, 6]]
    # A plain diameter takes whichever hole is left over.
    assert _holes_check(measured, [4, [4, 15, 0, 6]])["passed"] is True
    # The matching does not stop at a first guess that takes the hole a later point needs: the first
    # point fits both holes and would take the one at 0.04, which is the only one the second fits.
    small = {**_plate(_down(0.04, 0), _down(0, 0)), "bbox_mm": [20.0, 20.0, 6.0]}
    assert _holes_check(small, [[4, 0.02, 0, 6], [4, 0.08, 0, 6]])["passed"] is True


def test_a_position_needs_a_hole_of_its_own_diameter():
    measured = _plate(_down(-15, 0), _down(15, 0, d=5.0))
    check = _holes_check(measured, [[4, -15, 0, 6], [4, 15, 0, 6]])
    assert check["passed"] is False
    (said,) = check["misplaced"]
    # The only 4 mm hole is taken by the first point: the nearest one of that size is said, far off.
    assert said["expected"] == [4, 15, 0, 6] and said["nearest_at"] == [-15.0, 0.0, 6.0] and said["off_axis_mm"] == 30.0
    lone = _holes_check(_plate(_down(15, 0, d=5.0)), [[4, 15, 0, 6]])
    assert lone["misplaced"] == [{"expected": [4, 15, 0, 6], "nearest_at": None}]


def test_plain_diameters_are_checked_exactly_as_before():
    measured = _plate(_down(-15, 0), _down(15, 0))
    assert _holes_check(measured, [4, 4]) == {"check": "holes", "expected": [4, 4], "measured": [4.0, 4.0], "passed": True}
    assert _holes_check(measured, [4.5, 4])["passed"] is False and "misplaced" not in _holes_check(measured, [4.5, 4])


def test_the_tolerance_grows_with_a_large_part():
    # 0.1 % of a 1000 mm side is a millimetre; on a 20 mm part it is the 0.05 mm floor.
    large = {**_plate(_down(0, 0)), "bbox_mm": [1000.0, 40.0, 6.0]}
    assert _holes_check(large, [[4, 0.9, 0, 6]])["passed"] is True and _holes_check(large, [[4, 1.1, 0, 6]])["passed"] is False
    small = {**_plate(_down(0, 0)), "bbox_mm": [20.0, 20.0, 6.0]}
    assert _holes_check(small, [[4, 0.04, 0, 6]])["passed"] is True and _holes_check(small, [[4, 0.06, 0, 6]])["passed"] is False


def test_the_same_holes_listed_another_way_are_the_same_holes():
    assert checks.canonical_holes([[4, 15, 0, 6], 6, 4.0, (4, -15, 0, 6)]) == [4.0, [4, -15, 0, 6], [4, 15, 0, 6], 6]
    assert checks.canonical_holes([6, 4]) == [4, 6]


def test_more_misplaced_holes_than_a_check_names_are_counted():
    measured = _plate(*(_down(x, 0.0) for x in range(-20, 20)))
    check = _holes_check(measured, [[4, x, 5, 6] for x in range(-20, 20)])
    assert len(check["misplaced"]) == checks.MAX_HOLES_LISTED and check["misplaced_count"] == 40
