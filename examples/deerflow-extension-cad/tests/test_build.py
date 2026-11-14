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
    ("a method that takes a path", "result = cq.Workplane('XY').box(1, 1, 1).exportSvg('/tmp/deerflow-cad-canary.svg')\n", "method"),
    ("a builtin that opens a file", "x = open('/tmp/deerflow-cad-canary', 'w')\nresult = cq.Workplane('XY').box(1, 1, 1)\n", "call"),
    ("a pattern of a million instances", "result = cq.Workplane('XY').box(9, 9, 1).faces('>Z').workplane().rarray(1, 1, 1000, 1000).hole(0.5)\n", "pattern"),
    ("a deeply nested expression", "x = " + "(" * 3000 + "1" + ")" * 3000 + "\nresult = cq.Workplane('XY').box(1, 1, 1)\n", "syntax"),
    ("a long operator chain", "x = " + "-" * 2500 + "1\nresult = cq.Workplane('XY').box(1, 1, 1)\n", "nesting"),
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


async def test_two_separate_bodies_are_not_one_part():
    script = 'a = cq.Workplane("XY").box(10, 10, 10)\nb = cq.Workplane("XY").box(10, 10, 10).translate((30, 0, 0))\nresult = a.union(b)\n'
    answer, files = await _build(script, bbox_xyz_mm=[40, 10, 10])
    assert answer["passed"] is False
    assert [check["check"] for check in answer["checks"] if not check["passed"]] == ["one closed solid"]
    assert "part.step" not in files and "part.failed.glb" in files


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
