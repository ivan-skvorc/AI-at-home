"""The whole tool against the real kernel: a script goes in, checked files come out.

The handler starts the real worker process. The host is replaced by a
``ToolContext`` whose writer keeps the files in memory and, like the host,
never replaces a name that is taken.
"""

from __future__ import annotations

import inspect
import json
import time

import pytest
from deerflow_extension_api import ExtensionPrincipal, ToolContext

cq = pytest.importorskip("cadquery", reason="the CAD kernel is not installed")

from deerflow_extension_cad import allowlist, build  # noqa: E402
from deerflow_extension_cad.interpreter import compile_script  # noqa: E402
from deerflow_extension_cad.tool import make_handler, settings_from  # noqa: E402

PLATE = """\
import cadquery as cq

length = 60
width = 40
thickness = 6
hole_d = 4

result = (
    cq.Workplane("XY")
    .box(length, width, thickness)
    .faces(">Z")
    .workplane()
    .pushPoints([(-15, 0), (15, 0)])
    .hole(hole_d)
)
"""
ONE_HOLE = PLATE.replace("[(-15, 0), (15, 0)]", "[(-15, 0)]")
# The volume range admits the plate with one hole or two, so a missing hole fails the hole check alone.
EXPECT = {"bbox_xyz_mm": [60, 40, 6], "volume_min_max_mm3": [14000, 14400], "hole_diameters_mm": [4, 4]}


class Outputs:
    """Stands in for the host: stores files, suffixes a taken name, returns the virtual path."""

    def __init__(self):
        self.files: dict[str, bytes] = {}

    async def write(self, name: str, content: bytes) -> str:
        stem, dot, suffix = name.rpartition(".")
        candidate, index = name, 0
        while candidate in self.files:
            index += 1
            candidate = f"{stem}-{index}{dot}{suffix}"
        self.files[candidate] = content
        return f"/mnt/user-data/outputs/{candidate}"


async def _build(script: str, outputs: Outputs | None = None, **expect):
    outputs = outputs or Outputs()
    context = ToolContext(ExtensionPrincipal("alice"), {"enabled": True}, "thread-a", output_writer=outputs.write)
    handler = make_handler(settings_from({}))
    answer = await handler({"name": "part", "script": script, **(expect or EXPECT)}, context)
    return answer, outputs.files


async def test_the_plate_is_built_and_its_five_files_are_handed_over():
    answer, files = await _build(PLATE)
    assert answer["passed"] is True, answer
    assert {check["check"]: check["passed"] for check in answer["checks"]} == {"one closed solid": True, "bounding box": True, "volume": True, "holes": True}
    assert sorted(files) == ["part.glb", "part.py", "part.report.json", "part.step", "part.stl"]
    assert files["part.py"].decode() == PLATE
    assert files["part.step"].startswith(b"ISO-10303-21") and b"MANIFOLD_SOLID_BREP" in files["part.step"]
    assert files["part.glb"][:4] == b"glTF"
    report = json.loads(files["part.report.json"])
    assert report["passed"] is True
    assert report["measured"]["bbox_mm"] == [60.0, 40.0, 6.0]
    assert [hole["diameter_mm"] for hole in report["measured"]["holes"]] == [4.0, 4.0]
    assert sorted(answer["files"]) == sorted(f"/mnt/user-data/outputs/{name}" for name in files)


async def test_the_same_script_with_one_hole_removed_fails_the_hole_check_and_leaves_no_step():
    answer, files = await _build(ONE_HOLE)
    assert answer["passed"] is False
    failed = [check for check in answer["checks"] if not check["passed"]]
    assert [(check["check"], check["expected"], check["measured"]) for check in failed] == [("holes", [4, 4], [4.0])]
    assert sorted(files) == ["part.failed.glb", "part.py", "part.report.json"]
    assert files["part.failed.glb"][:4] == b"glTF"
    assert json.loads(files["part.report.json"])["passed"] is False


HOSTILE = [
    ("another import", "import os\nresult = cq.Workplane('XY').box(1, 1, 1)\n", "import"),
    ("a dunder attribute", "result = cq.Workplane('XY').box(1, 1, 1).__class__.__mro__\n", "attribute"),
    ("a lambda", "f = lambda: 1\nresult = cq.Workplane('XY').box(1, 1, 1)\n", "lambda"),
    ("a method that takes a path", "result = cq.Workplane('XY').box(1, 1, 1).exportSvg('/tmp/deerflow-cad-canary.svg')\n", "export"),
    ("a builtin that opens a file", "x = open('/tmp/deerflow-cad-canary', 'w')\nresult = cq.Workplane('XY').box(1, 1, 1)\n", "call"),
    ("a pattern of a million instances", "result = cq.Workplane('XY').box(9, 9, 1).faces('>Z').workplane().rarray(1, 1, 1000, 1000).hole(0.5)\n", "pattern"),
    ("a deeply nested expression", "x = " + "(\n" * 3000 + "1" + "\n)" * 3000 + "\nresult = cq.Workplane('XY').box(1, 1, 1)\n", "syntax"),
    ("a long operator chain", "x = (" + "-\n" * 2500 + "1)\nresult = cq.Workplane('XY').box(1, 1, 1)\n", "nesting"),
    ("a number the size of a planet", "result = cq.Workplane('XY').box(10 ** 9, 1, 1)\n", "argument"),
]


@pytest.mark.parametrize(("label", "script", "construct"), HOSTILE, ids=[item[0] for item in HOSTILE])
async def test_a_hostile_script_is_refused_with_its_reason_and_nothing_runs(label, script, construct, tmp_path):
    from pathlib import Path

    canaries = [Path("/tmp/deerflow-cad-canary"), Path("/tmp/deerflow-cad-canary.svg")]
    started = time.monotonic()
    answer, files = await _build(script, bbox_xyz_mm=[1, 1, 1])
    elapsed = time.monotonic() - started
    assert answer["passed"] is False
    assert answer["error"]["construct"] in (construct, "script length", "nesting", "syntax") if construct in ("nesting", "syntax") else answer["error"]["construct"] == construct
    assert answer["error"]["message"]
    # Refused before the kernel is loaded: only the script and the report are kept, and it is quick.
    assert sorted(files) == ["part.py", "part.report.json"]
    assert elapsed < 10
    assert not any(canary.exists() for canary in canaries)


async def test_a_kernel_error_names_the_line_and_the_operation():
    script = 'import cadquery as cq\nbase = cq.Workplane("XY").box(10, 10, 10)\nresult = (\n    base\n    .edges("|Z")\n    .fillet(20)\n)\n'
    answer, files = await _build(script, bbox_xyz_mm=[10, 10, 10])
    assert answer["passed"] is False
    assert (answer["error"]["line"], answer["error"]["operation"]) == (6, "fillet")
    assert "radius is probably too large" in answer["error"]["message"]
    assert sorted(files) == ["part.py", "part.report.json"]


LOOPED = """\
import cadquery as cq

result = cq.Workplane("XY").box(60, 20, 4)
for x in [-18, -6, {third}, 18]:
    result = (
        result.faces(">Z")
        .workplane()
        .pushPoints([(x, 0)])
        .hole(3)
    )
"""


async def test_a_loop_builds_what_its_statements_written_out_build():
    looped, _ = await _build(LOOPED.format(third=6), bbox_xyz_mm=[60, 20, 4], hole_diameters_mm=[3, 3, 3, 3])
    assert looped["passed"] is True, looped
    written_out = 'result = cq.Workplane("XY").box(60, 20, 4)\n' + "".join(f'result = result.faces(">Z").workplane().pushPoints([({x}, 0)]).hole(3)\n' for x in (-18, -6, 6, 18))
    flat, files = await _build(written_out, bbox_xyz_mm=[60, 20, 4], hole_diameters_mm=[3, 3, 3, 3])
    assert flat["passed"] is True, flat
    volume = json.loads(files["part.report.json"])["measured"]["volume_mm3"]
    assert volume == pytest.approx(60 * 20 * 4 - 4 * 3.14159265 * 1.5**2 * 4, rel=1e-4)


async def test_a_failure_inside_a_loop_names_the_pass_as_well_as_the_line():
    # The third hole is drilled beside the plate. All four holes are line 9 of the script.
    answer, files = await _build(LOOPED.format(third=40), bbox_xyz_mm=[60, 20, 4], hole_diameters_mm=[3, 3, 3, 3])
    assert answer["passed"] is False
    assert (answer["error"]["line"], answer["error"]["operation"]) == (9, "hole")
    assert "removed no material" in answer["error"]["message"]
    assert answer["error"]["message"].endswith("(in pass 3 of the loop on line 4 (x = 40))")
    assert json.loads(files["part.report.json"])["error"] == answer["error"]


async def test_bodies_a_loop_builds_and_never_joins_are_said_in_the_answer():
    # The usual slip: each pass builds a link, and the result is the last one alone. Its box even matches one link.
    links = 'for i in range(3):\n    link = cq.Workplane("XY").box(10, 4, 2).translate((i * 12, 0, 0))\nresult = link\n'
    answer, _ = await _build(links, bbox_xyz_mm=[10, 4, 2])
    assert answer["passed"] is True
    assert [note for note in answer["notes"] if "not part of the result" in note] == ["The script builds 2 bodies (built on line 2) that are not part of the result: join them with union(), or delete the lines."]
    # Joined, there is nothing to say.
    joined = 'result = cq.Workplane("XY").box(10, 4, 2)\nfor i in range(1, 3):\n    link = cq.Workplane("XY").box(10, 4, 2).translate((i * 9, 0, 0))\n    result = result.union(link)\n'
    answer, _ = await _build(joined, bbox_xyz_mm=[28, 4, 2])
    assert answer["passed"] is True and "notes" not in answer, answer
    # A trial cut is a branch off the part and a cutting tool is used up: neither is a body left over.
    spare = f'a = {BLOCK}\ntrial = a.faces(">Z").workplane().hole(3)\ntool = cq.Workplane("XY").box(10, 10, 20)\nsketch = cq.Workplane("XY").rect(5, 5)\nresult = a.cut(tool)\n'
    answer, _ = await _build(spare, bbox_xyz_mm=[60, 40, 6])
    assert answer["passed"] is True and not any("not part of the result" in note for note in answer.get("notes", [])), answer


async def test_passes_of_a_loop_whose_outcome_is_dropped_are_said_in_the_answer():
    # The other usual slip: every pass starts from the plate, so only the last slot is in the result.
    # With a bounding box to meet, a plate asked for with six slots passed with one, and nothing said so.
    dropped = 'plate = cq.Workplane("XY").box(100, 30, 5)\nfor i in range(6):\n    result = plate.faces(">Z").workplane().pushPoints([(-30 + i * 12, 0)]).slot2D(12, 3, 90).cutThruAll()\n'
    answer, _ = await _build(dropped, bbox_xyz_mm=[100, 30, 5])
    assert answer["passed"] is True
    (note,) = [note for note in answer["notes"] if "loop on line 2" in note]
    assert note == "5 passes of the loop on line 2 do work on the part that is not in the result: carry the part through the loop, for example result = result.hole(...), or delete the work."
    # Carried through the loop, all six are there and there is nothing to say.
    carried = dropped.replace('plate = cq.Workplane("XY")', 'result = cq.Workplane("XY")').replace("result = plate.faces", "result = result.faces")
    answer, files = await _build(carried, bbox_xyz_mm=[100, 30, 5])
    assert answer["passed"] is True and "notes" not in answer, answer
    assert json.loads(files["part.report.json"])["measured"]["volume_mm3"] < 14000
    # Rows lost one level up: the inner loop carries its row, and the outer loop starts every row from the bare plate.
    rows = 'base = cq.Workplane("XY").box(50, 50, 4)\nfor row in range(3):\n    result = base\n    for column in range(3):\n        result = result.faces(">Z").workplane().pushPoints([(-15 + column * 15, -15 + row * 15)]).hole(4)\n'
    answer, _ = await _build(rows, bbox_xyz_mm=[50, 50, 4])
    assert answer["passed"] is True and [note[:32] for note in answer["notes"]] == ["2 passes of the loop on line 4 d"], answer
    # A selection made in every pass and never used did no work on the part.
    looking = 'result = cq.Workplane("XY").box(20, 20, 4)\nfor i in range(3):\n    top = result.faces(">Z")\n'
    answer, _ = await _build(looking, bbox_xyz_mm=[20, 20, 4])
    assert answer["passed"] is True and "notes" not in answer, answer


async def test_a_tool_made_ready_for_the_next_pass_is_not_work_dropped():
    # Cut, then move the cutter on for the next pass. The last move is never used, and nothing is missing.
    advanced = 'result = cq.Workplane("XY").box(80, 30, 5)\ncutter = cq.Workplane("XY").box(3, 12, 10).translate((-30, 0, 0))\nfor i in range(6):\n    result = result.cut(cutter)\n    cutter = cutter.translate((12, 0, 0))\n'
    answer, _ = await _build(advanced, bbox_xyz_mm=[80, 30, 5], volume_min_max_mm3=[10900, 10940])
    assert answer["passed"] is True and "notes" not in answer, answer
    # A link joined and then moved on is the same idiom with union().
    joined = 'result = cq.Workplane("XY").box(10, 4, 2)\nlink = cq.Workplane("XY").box(10, 4, 2).translate((9, 0, 0))\nfor i in range(3):\n    result = result.union(link)\n    link = link.translate((9, 0, 0))\n'
    answer, _ = await _build(joined, bbox_xyz_mm=[37, 4, 2])
    assert answer["passed"] is True and "notes" not in answer, answer
    # The same with a fresh cutter built at the end of each pass.
    fresh = advanced.replace("cutter = cutter.translate((12, 0, 0))", 'cutter = cq.Workplane("XY").box(3, 12, 10).translate((-30 + (i + 1) * 12, 0, 0))')
    answer, _ = await _build(fresh, bbox_xyz_mm=[80, 30, 5], volume_min_max_mm3=[10900, 10940])
    assert answer["passed"] is True and "notes" not in answer, answer


async def test_a_body_started_on_a_shared_empty_workplane_is_still_a_body_left_out():
    # Both start from one empty workplane. That workplane is not the part, so the rib is not a branch off it.
    shared = 'wp = cq.Workplane("XY")\nresult = wp.box(80, 10, 5)\nrib = wp.box(4, 10, 20).translate((0, 0, 12.5))\n'
    answer, _ = await _build(shared, bbox_xyz_mm=[80, 10, 5])
    assert [note for note in answer["notes"] if "not part of the result" in note] == ["The script builds 1 body (built on line 3) that is not part of the result: join it with union(), or delete the lines."]


async def test_a_body_left_out_is_counted_once_and_named_where_it_starts():
    # One spare body with two selections on it is one body, built on line 2: not two, on the lines of the selections.
    spare = f'result = {BLOCK}\nspare = cq.Workplane("XY").box(5, 5, 5).translate((0, 0, 50))\ntop = spare.faces(">Z")\nside = spare.edges("|Z")\n'
    answer, _ = await _build(spare, bbox_xyz_mm=[60, 40, 6])
    assert [note for note in answer["notes"] if "not part of the result" in note] == ["The script builds 1 body (built on line 2) that is not part of the result: join it with union(), or delete the lines."]
    # Bodies dropped on different lines are each located, however many a loop drops on one line.
    many = f'for i in range(7):\n    link = cq.Workplane("XY").box(4, 4, 4).translate((i * 9, 0, 0))\nextra = cq.Workplane("XY").sphere(3)\nresult = {BLOCK}\n'
    answer, _ = await _build(many, bbox_xyz_mm=[60, 40, 6])
    (note,) = [note for note in answer["notes"] if "not part of the result" in note]
    assert note.startswith("The script builds 8 bodies (built on line 2, 3)")
    # More lines than an answer names are said to be more.
    seven = "".join(f'spare{index} = cq.Workplane("XY").box(2, 2, 2)\n' for index in range(7)) + f"result = {BLOCK}\n"
    answer, _ = await _build(seven, bbox_xyz_mm=[60, 40, 6])
    (note,) = [note for note in answer["notes"] if "not part of the result" in note]
    assert note.startswith("The script builds 7 bodies (built on line 1, 2, 3, 4, 5 and more)")


async def test_a_pass_that_repeats_another_is_told_to_leave_the_pass_out_not_the_line():
    # The last point closes the ring on the first. The line is all five holes; deleting it would remove them all.
    ring = 'result = cq.Workplane("XY").box(60, 60, 4)\nfor x, y in [(20, 0), (0, 20), (-20, 0), (0, -20), (20, 0)]:\n    result = result.faces(">Z").workplane().pushPoints([(x, y)]).hole(4)\n'
    answer, _ = await _build(ring, bbox_xyz_mm=[60, 60, 4])
    message = answer["error"]["message"]
    assert "Delete this line" not in message and "Leave this pass out if the part is right without it." in message
    assert message.endswith("(in pass 5 of the loop on line 2 (x = 20, y = 0))")


async def test_a_blind_cut_into_air_names_the_cause_that_fits_its_distance():
    # A lip added first: the highest face is now the top of the lip, and a cut of 4 below it meets no material.
    lip = f'result = {BLOCK}.union(cq.Workplane("XY").box(60, 6, 20).translate((0, 17, 13)))\nresult = result.faces(">Z").workplane().center(0, -20).rect(40, 6).cutBlind(-4)\n'
    answer, _ = await _build(lip, bbox_xyz_mm=[60, 40, 26])
    message = answer["error"]["message"]
    assert answer["error"]["operation"] == "cutBlind" and "highest face" in message and "use a negative distance" not in message
    # The same sentence has to be true of the same pocket cut twice: there the material is already gone.
    twice = f'result = {BLOCK}.faces(">Z").workplane().rect(20, 10).cutBlind(-3)\nresult = result.faces(">Z").workplane().rect(20, 10).cutBlind(-3)\n'
    answer, _ = await _build(twice, bbox_xyz_mm=[60, 40, 6])
    assert "already gone" in answer["error"]["message"] and "use a negative distance" not in answer["error"]["message"]
    # A positive distance still gets the sentence about the sign.
    away = f'result = {BLOCK}.faces(">Z").workplane().rect(20, 10).cutBlind(3)\n'
    answer, _ = await _build(away, bbox_xyz_mm=[60, 40, 6])
    assert "use a negative distance" in answer["error"]["message"]


async def test_a_part_is_rebuilt_until_it_passes_and_each_answer_says_what_comes_next():
    """The loop the agent runs, against the real kernel: build, read what failed, repair, build again."""
    outputs = Outputs()
    context = ToolContext(ExtensionPrincipal("alice"), {"enabled": True}, "thread-a", run_id="run-1", output_writer=outputs.write)
    handler = make_handler(settings_from({}))

    refused = await handler({"name": "part", "script": PLATE.replace("result = (", "while True:\n    pass\nresult = ("), **EXPECT}, context)
    assert (refused["passed"], refused["attempt"], refused["error"]["construct"]) == (False, 1, "while loop")
    assert refused["next"].startswith("Attempt 1 of 8.")

    failed = await handler({"name": "part", "script": ONE_HOLE, **EXPECT}, context)
    assert (failed["passed"], failed["attempt"]) == (False, 2)
    assert failed["next"].startswith("Attempt 2 of 8.") and "same failure" not in failed["next"]

    passed = await handler({"name": "part", "script": PLATE, **EXPECT}, context)
    assert (passed["passed"], passed["attempt"]) == (True, 3)
    assert passed["next"].startswith("Every check passed.") and "expected_changed" not in passed
    assert [json.loads(outputs.files[name])["attempt"] for name in ("part.report.json", "part-1.report.json", "part-2.report.json")] == [1, 2, 3]
    assert "part-2.step" in outputs.files and "part.step" not in outputs.files and "part-1.step" not in outputs.files


async def test_two_separate_bodies_are_not_one_part():
    script = 'a = cq.Workplane("XY").box(10, 10, 10)\nb = cq.Workplane("XY").box(10, 10, 10).translate((30, 0, 0))\nresult = a.union(b)\n'
    answer, files = await _build(script, bbox_xyz_mm=[40, 10, 10])
    assert answer["passed"] is False
    assert [check["check"] for check in answer["checks"] if not check["passed"]] == ["one closed solid"]
    assert "part.step" not in files and "part.failed.glb" in files


BLOCK = 'cq.Workplane("XY").box(60, 40, 6)'
EMPTIED = [
    ("an intersection of parts that do not meet", 'a = cq.Workplane("XY").box(40, 40, 20)\nb = cq.Workplane("XY").sphere(22).translate((100, 0, 0))\nresult = a.intersect(b)\n', [40, 40, 20], 3, "intersect"),
    ("a hole wider than the part", 'result = (\n    cq.Workplane("XY").box(10, 10, 10)\n    .faces(">Z").workplane()\n    .hole(50)\n)\n', [10, 10, 10], 4, "hole"),
    ("a cut by a body that swallows the part", 'a = cq.Workplane("XY").box(4, 4, 4)\nresult = a.cut(cq.Workplane("XY").sphere(50))\n', [4, 4, 4], 2, "cut"),
]


@pytest.mark.parametrize(("label", "script", "bbox", "line", "operation"), EMPTIED, ids=[item[0] for item in EMPTIED])
async def test_an_operation_that_removes_the_whole_part_fails_instead_of_passing_as_the_part_before_it(label, script, bbox, line, operation):
    # CadQuery leaves an empty compound, and looking for the solid then walks back to the untouched part.
    answer, files = await _build(script, bbox_xyz_mm=bbox)
    assert answer["passed"] is False
    assert (answer["error"]["line"], answer["error"]["operation"]) == (line, operation)
    assert "nothing remains" in answer["error"]["message"]
    assert sorted(files) == ["part.py", "part.report.json"]


UNCHANGED = [
    ("a pocket cut away from the part", f'result = {BLOCK}.faces(">Z").workplane().rect(20, 10).cutBlind(3)\n', "cutBlind", "negative distance"),
    ("a hole drilled beside the part", f'result = {BLOCK}.faces(">Z").workplane().center(100, 0).hole(4)\n', "hole", "off the part"),
    ("a cut by a body that does not touch", f'a = {BLOCK}\nresult = a.cut(cq.Workplane("XY").sphere(5).translate((100, 0, 0)))\n', "cut", "do not overlap"),
    ("a wall thicker than the part", 'result = cq.Workplane("XY").box(60, 40, 30).faces(">Z").shell(-25)\n', "shell", "thicker"),
]


@pytest.mark.parametrize(("label", "script", "operation", "says"), UNCHANGED, ids=[item[0] for item in UNCHANGED])
async def test_a_cut_that_removes_nothing_fails_instead_of_passing_on_the_untouched_block(label, script, operation, says):
    # With only a bounding box to meet, the plain block would pass every check.
    answer, files = await _build(script, bbox_xyz_mm=[60, 40, 30] if operation == "shell" else [60, 40, 6])
    assert answer["passed"] is False
    assert answer["error"]["operation"] == operation and says in answer["error"]["message"]
    assert "part.step" not in files


ADDS_NOTHING = [
    ("an extrusion down into the block", f'result = {BLOCK}.faces(">Z").workplane().rect(20, 10).extrude(-3)\n', "extrude"),
    ("a cylinder placed inside the plate", f"result = {BLOCK}.cylinder(4, 3)\n", "cylinder"),
    ("a body joined where the part already is", f'a = {BLOCK}\nresult = a.union(cq.Workplane("XY").box(10, 10, 2))\n', "union"),
]


@pytest.mark.parametrize(("label", "script", "operation"), ADDS_NOTHING, ids=[item[0] for item in ADDS_NOTHING])
async def test_a_feature_that_adds_nothing_fails_instead_of_passing_on_the_untouched_block(label, script, operation):
    # Posts drawn inside the floor, a boss extruded the wrong way: the block still meets its bounding box.
    answer, files = await _build(script, bbox_xyz_mm=[60, 40, 6])
    assert answer["passed"] is False
    assert answer["error"]["operation"] == operation and "added no material" in answer["error"]["message"]
    assert "part.step" not in files


async def test_only_what_the_result_is_made_of_is_held_to_account():
    # A clash test and a trial cut that the part never uses: both do nothing, and neither is the part.
    script = f'a = {BLOCK}\nb = cq.Workplane("XY").sphere(5).translate((100, 0, 0))\nclash = a.intersect(b)\ntrial = a.cut(b)\nresult = a.faces(">Z").workplane().hole(4)\n'
    answer, _ = await _build(script, bbox_xyz_mm=[60, 40, 6], hole_diameters_mm=[4])
    assert answer["passed"] is True, answer
    # A body built apart and then cut away: extrude(combine=False) makes the tool, it does not add to the part.
    script = f'a = {BLOCK}\ntool = a.faces(">Z").workplane().rect(20, 10).extrude(-3, combine=False)\nresult = a.cut(tool)\n'
    answer, _ = await _build(script, bbox_xyz_mm=[60, 40, 6], volume_min_max_mm3=[13700, 13900])
    assert answer["passed"] is True, answer


async def test_a_redundant_operation_is_refused_with_a_reason_that_fits():
    # The same hole drilled again from the other side removes nothing. The point is on the part.
    answer, _ = await _build(f'result = {BLOCK}.faces(">Z").workplane().hole(4).faces("<Z").workplane().hole(4)\n', bbox_xyz_mm=[60, 40, 6])
    assert answer["passed"] is False and answer["error"]["operation"] == "hole"
    assert "already gone" in answer["error"]["message"] and "Delete this line" in answer["error"]["message"]


async def test_a_real_cut_is_never_too_small_to_count():
    # One millimetre in a ten metre cube: far below any tolerance on the volume, and still a cut.
    answer, _ = await _build('result = cq.Workplane("XY").box(10000, 10000, 10000).faces(">Z").workplane().hole(1, 1)\n', bbox_xyz_mm=[10000, 10000, 10000])
    assert answer["passed"] is True, answer


async def test_the_stl_follows_the_surface_within_a_tenth_of_a_millimetre():
    # Not a fraction of each edge, which is how the kernel's exporter reads a tolerance by default.
    answer, files = await _build('result = cq.Workplane("XY").sphere(100)\n', bbox_xyz_mm=[200, 200, 200])
    assert answer["passed"] is True
    triangles = int.from_bytes(files["part.stl"][80:84], "little")
    assert triangles > 5000, triangles


async def test_a_mesh_the_file_limit_cuts_off_is_written_coarser_not_delivered(monkeypatch):
    from deerflow_extension_cad import tool

    monkeypatch.setattr(tool, "MAX_EXPORT_BYTES", 300_000)  # the finest mesh of this sphere is about 500 kB
    answer, files = await _build('result = cq.Workplane("XY").sphere(100)\n', bbox_xyz_mm=[200, 200, 200])
    assert answer["passed"] is True, answer
    assert int.from_bytes(files["part.stl"][80:84], "little") * 50 + 84 == len(files["part.stl"]) <= 300_000
    assert any("coarser" in note for note in answer["notes"])


async def test_what_the_checks_do_not_cover_is_said_in_the_answer():
    # An outline nobody extruded or cut: the part is the plain block and still meets its bounding box.
    answer, _ = await _build(f'result = {BLOCK}.faces(">Z").workplane().circle(5)\n', bbox_xyz_mm=[60, 40, 6])
    assert answer["passed"] is True and any("outline" in note for note in answer["notes"])
    # A cavity sealed inside the part.
    answer, _ = await _build('result = cq.Workplane("XY").box(20, 20, 20).shell(-2)\n', bbox_xyz_mm=[20, 20, 20])
    assert answer["passed"] is True and any("sealed" in note for note in answer["notes"])
    # A hole that barely scratches the surface counts as a hole of its diameter, so its depth is given.
    answer, _ = await _build(f'result = {BLOCK}.faces(">Z").workplane().hole(4, 0.5)\n', bbox_xyz_mm=[60, 40, 6], hole_diameters_mm=[4])
    holes = next(check for check in answer["checks"] if check["check"] == "holes")
    assert holes["passed"] is True and holes["blind_depths_mm"] == [0.5]
    # One drill pass through both walls of an enclosure is one hole, and the answer says why.
    answer, _ = await _build('result = cq.Workplane("XY").box(80, 60, 30).faces(">Z").shell(-2).faces(">X").workplane().hole(8)\n', bbox_xyz_mm=[80, 60, 30], hole_diameters_mm=[8])
    assert answer["passed"] is True and any("2 walls" in note for note in answer["notes"])
    # What was measured and not asked about is given, so a model can compare it with what it meant.
    answer, _ = await _build(PLATE, bbox_xyz_mm=[60, 40, 6])
    assert answer["unchecked"]["hole_diameters_mm"] == [4.0, 4.0] and 14200 < answer["unchecked"]["volume_mm3"] < 14300
    # A plain passing part with every expectation given says nothing extra.
    answer, _ = await _build(PLATE)
    assert "notes" not in answer and "unchecked" not in answer and "blind_depths_mm" not in next(check for check in answer["checks"] if check["check"] == "holes")


@pytest.mark.parametrize(
    "script",
    [
        'result = cq.Workplane("XY").box(40, 20, 1).faces(">Z").workplane().cskHole(3.2, 6.3, 90)\n',
        'result = cq.Workplane("XY").box(40, 20, 6).faces(">Z").workplane().circle(5).cutBlind(-3, taper=10)\n',
        'result = cq.Workplane("XY").box(40, 20, 6).faces(">Z").workplane().circle(2).cutThruAll(taper=5)\n',
    ],
    ids=["a countersink deeper than the sheet", "a tapered pocket", "a tapered through cut"],
)
async def test_a_round_opening_with_sloped_walls_is_measured_not_crashed_on(script):
    answer, files = await _build(script, bbox_xyz_mm=[40, 20, 1 if "cskHole" in script else 6], hole_diameters_mm=[])
    assert answer["passed"] is True, answer
    assert "part.step" in files


async def test_a_dense_part_gets_a_coarser_mesh_instead_of_a_file_the_host_refuses():
    # At the default tolerance this STL is about 10 MB, over the host's default 8 MiB per file.
    script = 'result = cq.Workplane("XY").box(40, 40, 3).faces(">Z").workplane().rarray(3, 3, 10, 10).hole(2).edges().fillet(0.2)\n'
    answer, files = await _build(script, bbox_xyz_mm=[40, 40, 3], hole_diameters_mm=[2] * 100)
    assert answer["passed"] is True, answer
    assert len(files["part.stl"]) <= build.MESH_TARGET_BYTES
    assert int.from_bytes(files["part.stl"][80:84], "little") * 50 + 84 == len(files["part.stl"])
    report = json.loads(files["part.report.json"])
    assert report["measured"]["mesh"]["tolerance_mm"] > build.MESH_STEPS[0][0]
    assert any("coarser" in note for note in answer["notes"])


async def test_a_part_of_several_metres_is_meshed_in_proportion_to_its_size():
    # At a tenth of a millimetre this sphere is 17 MB of triangles, cut off by the file limit and once delivered as passed.
    started = time.monotonic()
    answer, files = await _build('result = cq.Workplane("XY").sphere(3400)\n', bbox_xyz_mm=[6800, 6800, 6800])
    assert answer["passed"] is True, answer
    assert time.monotonic() - started < 15
    assert int.from_bytes(files["part.stl"][80:84], "little") * 50 + 84 == len(files["part.stl"]) <= build.MESH_TARGET_BYTES


async def test_an_export_over_the_size_limit_is_a_failed_build_not_a_cut_off_file(monkeypatch):
    from deerflow_extension_cad import tool

    monkeypatch.setattr(tool, "MAX_EXPORT_BYTES", 20_000)  # the plate's STEP is about 25 kB
    answer, files = await _build(PLATE)
    assert answer["passed"] is False and "larger than" in answer["error"]["message"]
    assert sorted(files) == ["part.py", "part.report.json"]


async def test_the_real_worker_says_it_is_loading_while_it_imports_the_kernel():
    # One second is less than the kernel takes to import even when everything is compiled,
    # so the clock runs out in the same place a fresh install's first build does.
    from deerflow_extension_cad import tool

    result = await tool.run_worker(PLATE, timeout_seconds=1, memory_mb=4096)
    assert result["status"] == "loading", result


def test_the_self_test_loads_the_kernel_first_and_then_builds_its_cube():
    # What `make doctor` and the image build run. Loading has its own, longer limit, so a
    # fresh install's first run is not a time-out.
    import subprocess
    import sys

    run = subprocess.run([sys.executable, "-m", "deerflow_extension_cad.selftest"], capture_output=True, text=True, timeout=300, check=False)
    answer = json.loads(run.stdout.strip().splitlines()[-1])
    assert run.returncode == 0 and answer["ok"] is True and answer["bbox_mm"] == [1.0, 1.0, 1.0]
    # The kernel takes over a second to import even when everything is cached: a zero means it was not loaded here.
    assert 0.5 < answer["load_seconds"] < 60


async def test_a_rebuild_does_not_touch_the_first_build():
    outputs = Outputs()
    await _build(PLATE, outputs)
    answer, files = await _build(ONE_HOLE, outputs)
    assert answer["passed"] is False
    assert sorted(files) == ["part-1.failed.glb", "part-1.py", "part-1.report.json", "part.glb", "part.py", "part.report.json", "part.step", "part.stl"]


def test_every_allow_listed_method_matches_the_kernels_own_signature():
    """Positional arguments are bound by the table, so its order must be CadQuery's order."""
    for name, method in allowlist.METHODS.items():
        kernel = [parameter for parameter in inspect.signature(vars(cq.Workplane)[name]).parameters if parameter != "self"]
        ours = [param.name for param in method.params]
        assert ours == kernel[: len(ours)], f"{name}: the table says {ours}, cadquery {cq.__version__} says {kernel}"
    constructor = [parameter for parameter in inspect.signature(cq.Workplane.__init__).parameters if parameter != "self"]
    assert [param.name for param in allowlist.CONSTRUCTOR.params] == constructor[:2]


@pytest.mark.parametrize("name", sorted(allowlist.METHODS))
def test_every_allow_listed_method_has_an_example_that_builds_a_solid(name):
    example = allowlist.METHODS[name].example
    script = example if "result =" in example else f"result = {example}"
    program = compile_script(script)
    assert name in {operation.method for operation in program.operations}, f"the example for {name} does not use it"
    part = build.run_program(program, cq)
    solid = build.solid_of(part)
    assert solid.isValid() and solid.Volume() > 0


def test_the_table_holds_no_method_that_takes_a_path_a_callable_or_a_font():
    forbidden = {
        "export",
        "exportSvg",
        "toSvg",
        "text",
        "each",
        "eachpoint",
        "cutEach",
        "invoke",
        "apply",
        "map",
        "filter",
        "sort",
        "sketch",
        "placeSketch",
        "add",
        "newObject",
        "val",
        "vals",
        "findSolid",
        "split",
        "sweep",
        "toPending",
        "copyWorkplane",
    }
    assert not forbidden & set(allowlist.METHODS)
    for name in allowlist.METHODS:
        for parameter in inspect.signature(vars(cq.Workplane)[name]).parameters.values():
            annotation = str(parameter.annotation)
            if parameter.name in {param.name for param in allowlist.METHODS[name].params}:
                assert "Callable" not in annotation, f"{name}({parameter.name}) accepts a callable"
