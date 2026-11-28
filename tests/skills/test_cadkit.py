"""cadkit.py, the cad-modeling skill's script: helpers offline, the loop end to end.

The offline tests run in Skill Review CI's backend environment, which has numpy
but neither trimesh, manifold3d nor openscad. The end-to-end group renders real
models and runs only where openscad, trimesh and manifold3d are present: in the
CAD sandbox image (docker/sandbox-cad/smoke.sh runs the same loop there) or a
local environment that has them. Every test writes under tmp_path.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CADKIT = REPO_ROOT / "skills" / "public" / "cad-modeling" / "scripts" / "cadkit.py"


def _load():
    """cadkit as a module; its heavy imports are lazy, so loading needs nothing."""
    spec = importlib.util.spec_from_file_location("cadkit_under_test", CADKIT)
    module = importlib.util.module_from_spec(spec)
    # A scripts/__pycache__ would land in the committed skill tree, which the skill review scans.
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


cadkit = _load()


@pytest.fixture
def numpy_only(monkeypatch):
    """cadkit's lazy import asks for numpy and trimesh; the helpers under test use numpy alone."""
    pytest.importorskip("numpy")
    monkeypatch.setitem(sys.modules, "trimesh", types.ModuleType("trimesh"))


def run(capsys, *argv) -> tuple[int, str, str]:
    code = cadkit.main([str(arg) for arg in argv])
    out, err = capsys.readouterr()
    return code, out, err


# ---------------------------------------------------------------- bodies


def test_bodies_come_from_the_bodies_line_and_comments_do_not_count():
    source = """
    // BODIES = ["old"];
    /* BODIES = ["older"];
    */
    part = "all";
    BODIES = ["base", "rest_2", "strut-a"];  // the bodies
    """
    assert cadkit._bodies_of(source, None) == ["base", "rest_2", "strut-a"]


def test_bodies_given_on_the_command_line_win_and_a_model_without_them_is_one_part():
    assert cadkit._bodies_of('BODIES = ["a", "b"];', "b, c") == ["b", "c"]
    assert cadkit._bodies_of("cube(10);", None) == []


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ('BODIES = ["my part"];', "body name 'my part'"),
        ('BODIES = ["a.b"];', "body name 'a.b'"),
        (f'BODIES = ["{"x" * 41}"];', "at most 40"),
        ('BODIES = ["a", "a"];', "listed twice"),
    ],
)
def test_bad_or_repeated_body_names_are_refused(source, message):
    with pytest.raises(cadkit.Unusable, match=message):
        cadkit._bodies_of(source, None)


# ---------------------------------------------------------------- arguments


@pytest.mark.parametrize(("text", "bed"), [("250x210x220", [250, 210, 220]), ("180.5x180x180", [180.5, 180, 180])])
def test_a_bed_is_width_depth_height(text, bed):
    assert cadkit._parse_bed(text) == bed


@pytest.mark.parametrize("text", ["250x210", "250 x 210 x 220", "-1x2x3", "250x210x220mm"])
def test_a_malformed_bed_is_refused(text):
    with pytest.raises(cadkit.Unusable, match="WxDxH"):
        cadkit._parse_bed(text)


def test_sections_are_axis_value_planes(numpy_only):
    assert cadkit._parse_sections("z=5,y=0, x = -12.5 ", {}) == [("z", 5.0), ("y", 0.0), ("x", -12.5)]


@pytest.mark.parametrize(("text", "message"), [("w=1", "axis=value"), ("z=", "axis=value"), ("z=5;y=0", "axis=value"), (",".join(["z=1"] * 10), "at most 9")])
def test_malformed_sections_are_refused(numpy_only, text, message):
    with pytest.raises(cadkit.Unusable, match=message):
        cadkit._parse_sections(text, {})


def test_without_sections_the_planes_cut_the_middle_of_each_axis(numpy_only):
    import numpy as np

    meshes = {"a": types.SimpleNamespace(bounds=np.array([[0, 0, 0], [10, 20, 30]])), "b": types.SimpleNamespace(bounds=np.array([[-10, 0, 0], [0, 4, 4]]))}
    assert cadkit._parse_sections(None, meshes) == [("z", 15.0), ("y", 10.0), ("x", 0.0)]


def test_without_a_slicer_print_skips_slicing(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert "skipped" in cadkit._slice(tmp_path, [], [250, 210, 220])


# ---------------------------------------------------------------- poses


def test_without_a_poses_file_the_bodies_are_checked_as_modelled():
    assert cadkit._read_poses(None, ["a", "b"]) == {"poses": [{"name": "assembled"}], "ignore": [], "tolerance_mm3": 0.01}


@pytest.mark.parametrize(
    ("poses", "message"),
    [
        ("{not json", "poses.json"),
        ({}, "expected"),
        ({"poses": []}, "expected"),
        ({"poses": [{"place": {}}]}, "every pose has a name"),
        ({"poses": [{"name": "p", "spin": 1}]}, "unknown key"),
        ({"poses": [{"name": "p", "place": {"lid": []}}]}, "no body 'lid'"),
        ({"poses": [{"name": "p", "place": [{"translate": [0, 0, 1]}]}]}, "place maps each body"),
        ({"poses": [{"name": "p", "sweep": {"direction": [0, 0, 1], "from": 0, "to": 5}}]}, "name the moving body"),
        ({"poses": [{"name": "p", "sweep": {"body": "lid", "direction": [0, 0, 1], "from": 0, "to": 5}}]}, "name the moving body"),
        ({"poses": [{"name": "p", "sweep": [{"body": "a"}]}]}, "sweep is an object"),
        ({"poses": [{"name": "p"}], "ignore": ["a", "b"]}, "ignore is a list of body pairs"),
        ({"poses": [{"name": "p"}], "ignore": 5}, "ignore is a list of body pairs"),
    ],
)
def test_a_malformed_poses_file_is_refused_with_its_cause(tmp_path, poses, message):
    path = tmp_path / "poses.json"
    path.write_text(poses if isinstance(poses, str) else json.dumps(poses))
    with pytest.raises(cadkit.Unusable, match=message):
        cadkit._read_poses(path, ["a", "b"])


def _apply(matrix, point):
    return [round(float(v), 6) for v in (matrix @ [*point, 1.0])[:3]]


def test_placement_steps_follow_openscad(numpy_only):
    # rotate([x, y, z]) turns about X, then Y, then Z: (1, 0, 0) stays on X, then Z turns it to Y.
    assert _apply(cadkit._place([{"rotate": [90, 0, 90]}], "t"), [1, 0, 0]) == [0, 1, 0]
    # A turn about a point, and steps applied in the order listed.
    assert _apply(cadkit._place([{"rotate": [0, 0, 90], "about": [10, 0, 0]}], "t"), [20, 0, 0]) == [10, 10, 0]
    assert _apply(cadkit._place([{"translate": [10, 0, 0]}, {"rotate": [0, 0, 90]}], "t"), [0, 0, 0]) == [0, 10, 0]
    assert _apply(cadkit._place({"axis": [0, 0, 2], "angle": 180}, "t"), [1, 0, 0]) == [-1, 0, 0]


def test_a_sweep_has_one_state_per_step_both_ends_included(numpy_only):
    pose = {"name": "lift", "sweep": {"body": "lid", "direction": [0, 0, 2], "from": 0, "to": 30, "steps": 4}}
    states = cadkit._pose_states(pose, ["base", "lid"])
    assert [label for label, _ in states] == ["lift @ 0 mm", "lift @ 10 mm", "lift @ 20 mm", "lift @ 30 mm"]
    assert _apply(states[-1][1]["lid"], [0, 0, 0]) == [0, 0, 30]
    assert _apply(states[-1][1]["base"], [0, 0, 0]) == [0, 0, 0]
    with pytest.raises(cadkit.Unusable, match="steps must be"):
        cadkit._pose_states({**pose, "sweep": {**pose["sweep"], "steps": cadkit.MAX_SWEEP_STEPS + 1}}, ["base", "lid"])


# ---------------------------------------------------------------- versions


def test_each_render_takes_the_next_version_number(tmp_path):
    design = tmp_path / "outputs" / "design"
    assert cadkit._next_version(design).name == "v1"
    assert cadkit._next_version(design).name == "v2"
    assert sorted(p.name for p in design.iterdir()) == ["v1", "v2"]


def test_the_next_version_counts_folders_only(tmp_path):
    design = tmp_path / "design"
    for name in ("v1", "v2", "v10", "v3b", "version"):
        (design / name).mkdir(parents=True)
    (design / "v20").write_text("a file, not a version")
    assert cadkit._next_version(design).name == "v11"


def test_a_design_folder_means_its_newest_rendered_version(tmp_path):
    design = tmp_path / "design"
    for name in ("v2", "v9", "v10", "v11", "v12b"):
        (design / name).mkdir(parents=True)
    for name in ("v2", "v9", "v10", "v12b"):
        (design / name / "report.json").write_text("{}")
    # v11 has no report.json (a render that failed); v10 beats v9 by number, not by spelling.
    assert cadkit._version_dir(design) == (design / "v10").resolve()
    assert cadkit._version_dir(design / "v2") == (design / "v2").resolve()


def test_a_design_folder_without_a_version_says_how_to_make_one(tmp_path):
    with pytest.raises(cadkit.Unusable, match="no rendered version .* cadkit.py render model.scad --design"):
        cadkit._version_dir(tmp_path)


# ---------------------------------------------------------------- could not run


def _model(tmp_path) -> Path:
    model = tmp_path / "model.scad"
    model.write_text('part = "all";\nBODIES = ["a"];\nif (part == "a" || part == "all") cube(10);\n')
    return model


def test_a_missing_library_exits_2_with_an_error_line(tmp_path, capsys, monkeypatch):
    monkeypatch.setitem(sys.modules, "trimesh", None)
    code, out, err = run(capsys, "render", _model(tmp_path), "--design", tmp_path / "design")
    assert code == 2 and out == ""
    assert err.startswith("ERROR: trimesh is not installed here.") and "make sandbox-enable MODE=container IMAGE=cad" in err
    assert not (tmp_path / "design").exists()


def test_a_missing_openscad_exits_2_and_makes_no_version(tmp_path, capsys, monkeypatch, numpy_only):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    code, out, err = run(capsys, "render", _model(tmp_path), "--design", tmp_path / "design")
    assert code == 2 and out == ""
    assert err.startswith("ERROR: openscad is not installed here.") and "make sandbox-enable MODE=container IMAGE=cad" in err
    assert not (tmp_path / "design").exists()


def test_the_command_line_exits_2_with_an_error_line_on_stderr(tmp_path):
    # Without openscad on PATH this fails for trimesh or for openscad, whichever is missing first.
    empty = tmp_path / "empty"
    empty.mkdir()
    run_ = subprocess.run(
        [sys.executable, str(CADKIT), "render", str(_model(tmp_path)), "--design", str(tmp_path / "design")],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PATH": str(empty), "PYTHONDONTWRITEBYTECODE": "1"},
        cwd=tmp_path,
    )
    assert run_.returncode == 2, run_.stderr
    assert run_.stdout == ""
    assert run_.stderr.startswith("ERROR: ") and "is not installed here" in run_.stderr
    assert not (tmp_path / "design").exists()


def test_a_missing_model_exits_2(tmp_path, capsys, numpy_only):
    code, out, err = run(capsys, "render", tmp_path / "missing.scad", "--design", tmp_path / "design")
    assert code == 2 and err.startswith("ERROR: ") and "does not exist" in err
    assert not (tmp_path / "design").exists()


# ---------------------------------------------------------------- end to end

E2E_MISSING = [name for name in ("trimesh", "manifold3d") if importlib.util.find_spec(name) is None] + ([] if shutil.which("openscad") else ["openscad"])
needs_cad = pytest.mark.skipif(bool(E2E_MISSING), reason=f"end to end needs {', '.join(E2E_MISSING)} (the CAD sandbox image has them)")

# Two 10 x 20 x 30 boxes side by side, `gap` apart; the print layout moves b 30 mm further.
TWO_BOXES = """
part = "all";
layout = "assembled";
BODIES = ["a", "b"];
gap = 0.5;
module place(name) { if (layout == "print" && name == "b") translate([30, 0, 0]) children(); else children(); }
if (part == "a" || part == "all") place("a") cube([10, 20, 30]);
if (part == "b" || part == "all") place("b") translate([10 + gap, 0, 0]) cube([10, 20, 30]);
"""

# A cube that slides and swings, and a cube 10 mm beyond it that stops it.
SLIDER = """
part = "all";
BODIES = ["slider", "stop"];
if (part == "slider" || part == "all") cube(10);
if (part == "stop" || part == "all") translate([20, 0, 0]) cube(10);
"""

# A beam on two posts (a 10 mm bridge) and an arm held on one side (a ledge), both flat on the bed.
BRIDGE_AND_LEDGE = """
part = "all";
layout = "assembled";
BODIES = ["bridge", "ledge"];
if (part == "bridge" || part == "all") union() { cube([5, 10, 10]); translate([15, 0, 0]) cube([5, 10, 10]); translate([0, 0, 9.9]) cube([20, 10, 3.1]); }
if (part == "ledge" || part == "all") translate([0, 30, 0]) union() { cube([10, 10, 20]); translate([0, 0, 17]) cube([25, 10, 3]); }
"""


def render(capsys, tmp_path, source, *extra):
    work = tmp_path / "workspace"
    work.mkdir(exist_ok=True)
    (work / "model.scad").write_text(source)
    design = tmp_path / "outputs" / "design"
    code, out, err = run(capsys, "render", work / "model.scad", "--design", design, *extra)
    return design, code, out, err


def poses(tmp_path, data) -> Path:
    path = tmp_path / "workspace" / "poses.json"
    path.write_text(json.dumps(data))
    return path


@needs_cad
def test_render_writes_each_body_and_the_preview_into_a_new_version(tmp_path, capsys):
    import trimesh

    design, code, out, err = render(capsys, tmp_path, TWO_BOXES, "--print-layout")
    assert code == 0, out + err
    version = design / "v1"
    assert {"model.scad", "a.stl", "b.stl", "assembly.glb", "report.json"} <= {p.name for p in version.iterdir()}
    assert {"a.stl", "b.stl", "report.json"} <= {p.name for p in (version / "print").iterdir()}
    report = json.loads((version / "report.json").read_text())
    for name in ("a", "b"):
        body = report["bodies"][name]
        assert body["watertight"] and body["shells"] == 1 and body["size_mm"] == [10, 20, 30] and body["volume_mm3"] == 6000
    assert report["assembled"]["clashes"] == [] and report["assembled"]["gaps"][0]["min_gap_mm"] == pytest.approx(0.5)
    # The print layout is the same file rendered with layout="print".
    assert trimesh.load(version / "print" / "b.stl").bounds[0][0] == pytest.approx(40.5)
    # The preview: one node per body, in metres, Y up.
    scene = trimesh.load(version / "assembly.glb")
    assert set(scene.graph.nodes_geometry) == {"a", "b"}
    assert scene.bounds.flatten().tolist() == pytest.approx([0, 0, -0.02, 0.0205, 0.03, 0], abs=1e-6)
    # The next render is the next version; v1 stays as it was.
    _, code, out, _ = render(capsys, tmp_path, TWO_BOXES)
    assert code == 0 and out.startswith("v2: 2/2 bodies rendered") and (design / "v2" / "a.stl").is_file()


@needs_cad
def test_a_body_with_nothing_drawn_is_a_render_error(tmp_path, capsys):
    design, code, out, _ = render(capsys, tmp_path, TWO_BOXES.replace('BODIES = ["a", "b"]', 'BODIES = ["a", "b", "ghost"]'))
    assert code == 2
    assert "ghost: ERROR" in out and "top level object is empty" in out
    assert "empty" in json.loads((design / "v1" / "report.json").read_text())["bodies"]["ghost"]["error"]


@needs_cad
def test_overlapping_bodies_fail_check_and_are_named(tmp_path, capsys):
    design, code, out, _ = render(capsys, tmp_path, TWO_BOXES, "-D", "gap=-2")
    assert code == 1
    assert "CLASH as modelled: a / b overlap 1200.0 mm3 at x 8.0..10.0 y 0.0..20.0 z 0.0..30.0" in out
    code, out, _ = run(capsys, "check", design)
    assert code == 1
    assert "CLASH a / b at [assembled]: 1200.0 mm3 at x 8.0..10.0 y 0.0..20.0 z 0.0..30.0" in out and "FAIL: 1 overlaps" in out
    assert json.loads((design / "v1" / "check.json").read_text())["clashes"] == 1
    # A pair listed under ignore may overlap.
    code, out, _ = run(capsys, "check", design, "--poses", poses(tmp_path, {"poses": [{"name": "glued"}], "ignore": [["b", "a"]]}))
    assert code == 0 and "PASS: no overlap in any state" in out


@needs_cad
def test_a_gap_passes_and_is_reported(tmp_path, capsys):
    design, code, _, _ = render(capsys, tmp_path, TWO_BOXES)
    assert code == 0
    code, out, _ = run(capsys, "check", design)
    assert code == 0
    assert "smallest gap: 0.5 mm, a / b at [assembled]" in out and "PASS: no overlap in any state" in out and "tight" not in out
    # Closer than the clearance asked for is reported, and is not a clash.
    code, out, _ = run(capsys, "check", design, "--clearance", "1")
    assert code == 0 and "tight a / b at [assembled]: gap 0.5 mm < 1.0 mm" in out


@needs_cad
def test_a_sweep_collision_is_caught_at_the_states_where_it_happens(tmp_path, capsys):
    design, code, _, _ = render(capsys, tmp_path, SLIDER)
    assert code == 0
    sweeps = {
        "poses": [
            {"name": "slide", "sweep": {"body": "slider", "direction": [1, 0, 0], "from": 0, "to": 20, "steps": 5}},
            # Swung clockwise about the stop's near edge line x = 15: clear at -30 degrees, into the stop from -60.
            {"name": "swing", "sweep": {"body": "slider", "axis": [0, 0, 1], "about": [15, 0, 0], "from": 0, "to": -90, "steps": 4}},
        ]
    }
    code, out, _ = run(capsys, "check", design, "--poses", poses(tmp_path, sweeps))
    assert code == 1
    result = json.loads((design / "v1" / "check.json").read_text())
    assert result["states"] == 9
    assert [r["state"] for r in result["results"] if r["clashes"]] == ["slide @ 15 mm", "slide @ 20 mm", "swing @ -60 deg", "swing @ -90 deg"]
    assert "CLASH slider / stop in 2 states, worst at [slide @ 20 mm]: 1000.0 mm3 at x 20.0..30.0" in out
    assert "CLASH slider / stop in 2 states, worst at [swing @ -90 deg]: " in out
    worst = next(r for r in result["results"] if r["state"] == "swing @ -90 deg")["clashes"][0]
    assert worst["overlap_mm3"] == pytest.approx(250, abs=0.1)
    # Touching at 10 mm is not an overlap, but it is the smallest gap.
    assert "smallest gap: 0.0 mm, slider / stop at [slide @ 10 mm]" in out


@needs_cad
def test_views_write_a_shaded_render_and_sections(tmp_path, capsys):
    pytest.importorskip("matplotlib")
    design, code, _, _ = render(capsys, tmp_path, SLIDER)
    assert code == 0
    code, out, _ = run(capsys, "views", design, "--sections", "z=5,x=25")
    assert code == 0 and "z=5 cuts slider/stop, x=25 cuts stop" in out
    folder = design / "v1" / "views"
    for name in ("shaded.png", "sections.png"):
        assert (folder / name).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", name
    swing = poses(tmp_path, {"poses": [{"name": "swing", "sweep": {"body": "slider", "axis": [0, 0, 1], "about": [15, 0, 0], "from": 0, "to": -90}}]})
    code, _, _ = run(capsys, "views", design, "--poses", swing, "--pose", "swing", "--at", "-90")
    assert code == 0 and (folder / "shaded-swing--90.png").is_file() and (folder / "sections-swing--90.png").is_file()


@needs_cad
def test_print_flags_a_one_sided_ledge_and_passes_a_bridge(tmp_path, capsys):
    design, code, out, err = render(capsys, tmp_path, BRIDGE_AND_LEDGE, "--print-layout")
    assert code == 0, out + err
    code, out, _ = run(capsys, "print", design)
    assert code == 1
    assert "PROBLEM ledge: 150.0 mm2 flat ledge held on one side only" in out
    assert "PROBLEM bridge" not in out and "FAIL: 1 problems" in out
    result = json.loads((design / "v1" / "print" / "print.json").read_text())
    assert result["version"] == "v1/print"
    assert [r["kind"] for r in result["bodies"]["bridge"]["regions"]] == ["bridge"]
    assert [r["kind"] for r in result["bodies"]["ledge"]["regions"]] == ["ledge"]
    # The bridge is measured: a shorter limit than its 10 mm span flags it.
    code, out, _ = run(capsys, "print", design, "--max-bridge", "8")
    assert code == 1 and "PROBLEM bridge: bridge spans 10.0 mm (> 8.0)" in out


@needs_cad
@pytest.mark.skipif(not (shutil.which("prusa-slicer") or shutil.which("PrusaSlicer")), reason="needs prusa-slicer (the CAD sandbox image has it)")
def test_print_slices_every_body_of_the_layout_on_one_plate(tmp_path, capsys):
    design, code, out, err = render(capsys, tmp_path, BRIDGE_AND_LEDGE, "--print-layout")
    assert code == 0, out + err
    code, out, _ = run(capsys, "print", design, "--slice")
    result = json.loads((design / "v1" / "print" / "print.json").read_text())
    sliced = result["slicer"]
    assert "error" not in sliced and (design / "v1" / "print" / "print.gcode").is_file()
    assert f"slicer: {sliced['filament_g']} g, {sliced['time']}" in out
    # The slicer's own warnings are problems like cadkit's own, and decide the exit status with them.
    assert [p for p in result["problems"] if p.startswith("slicer says: ")] == [f"slicer says: {w}" for w in sliced.get("warnings", [])]
    assert code == (1 if result["problems"] else 0)
    # Sliced file by file, the last body's G-code would replace the rest: the plate weighs more than the last body alone.
    (tmp_path / "workspace" / "ledge.scad").write_text(BRIDGE_AND_LEDGE)
    alone = tmp_path / "outputs" / "ledge"
    assert run(capsys, "render", tmp_path / "workspace" / "ledge.scad", "--design", alone, "--bodies", "ledge", "--print-layout")[0] == 0
    run(capsys, "print", alone, "--slice")
    ledge = json.loads((alone / "v1" / "print" / "print.json").read_text())["slicer"]
    assert float(sliced["filament_g"]) > 1.5 * float(ledge["filament_g"])


@needs_cad
def test_export_writes_a_3mf_with_every_body(tmp_path, capsys):
    pytest.importorskip("lxml")
    import trimesh

    design, code, _, _ = render(capsys, tmp_path, TWO_BOXES)
    assert code == 0
    code, out, _ = run(capsys, "export", design, "--3mf")
    assert code == 0 and "wrote bodies.3mf" in out
    scene = trimesh.load(design / "v1" / "bodies.3mf")
    assert len(scene.geometry) == 2 and sum(m.volume for m in scene.geometry.values()) == pytest.approx(12000)


@needs_cad
def test_export_writes_a_step_per_body_that_reads_back_as_the_solid(tmp_path, capsys):
    pytest.importorskip("OCP")
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    design, code, _, _ = render(capsys, tmp_path, TWO_BOXES)
    assert code == 0
    code, out, _ = run(capsys, "export", design, "--step")
    assert code == 0 and "wrote a.step, b.step" in out and "STEP files are faceted" in out
    reader = STEPControl_Reader()
    assert reader.ReadFile(str(design / "v1" / "a.step")) == IFSelect_RetDone
    reader.TransferRoots()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(reader.OneShape(), props)
    assert props.Mass() == pytest.approx(6000, rel=0.01)
