"""cadkit.py, the cad-modeling skill's script: helpers offline, the loop end to end.

The offline tests run in Skill Review CI's backend environment, which has numpy
but neither trimesh, manifold3d nor openscad. The end-to-end group renders real
models and runs only where openscad, trimesh and manifold3d are present: in the
CAD sandbox image (docker/sandbox-cad/smoke.sh runs the same loop there) or a
local environment that has them. Every test writes under tmp_path.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import types
import zipfile
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


# ---------------------------------------------------------------- study, testpiece, guide and the zip


@pytest.mark.parametrize(("text", "box"), [("0,0,0,30,20,15", ([0, 0, 0], [30, 20, 15])), ("-5,-2.5,0,5,2.5,1e1", ([-5, -2.5, 0], [5, 2.5, 10]))])
def test_a_box_is_two_corners(text, box):
    assert cadkit._parse_box(text) == box


@pytest.mark.parametrize(
    ("text", "message"),
    [("0,0,0,30,20", "six numbers"), ("0,0,0,a,20,15", "six numbers"), ("0,0,0,inf,1,1", "six numbers"), ("0,0,0,30,0,15", "larger than"), ("10,0,0,5,5,5", "larger than")],
)
def test_a_malformed_box_is_refused(text, message):
    with pytest.raises(cadkit.Unusable, match=message):
        cadkit._parse_box(text)


def test_a_bad_box_exits_2_before_anything_is_loaded(tmp_path, capsys):
    code, out, err = run(capsys, "testpiece", tmp_path, "--box", "0,0,0,1,1")
    assert code == 2 and out == "" and err.startswith("ERROR: --box '0,0,0,1,1': six numbers")


def test_a_study_parameter_is_a_name_and_values_each_with_a_safe_folder():
    assert cadkit._parse_param("r=8, 10,12.5", []) == ("r", [("8", "8"), ("10", "10"), ("12.5", "12.5")])
    # A value is what -D takes; its folder keeps safe characters only, so no value names a path.
    assert cadkit._parse_param('label="M3",-0.5,true', ["wall=2"])[1] == [('"M3"', "M3"), ("-0.5", "-0.5"), ("true", "true")]
    assert cadkit._parse_param("gap=..", [])[1] == [("..", "value")]


@pytest.mark.parametrize(
    ("text", "defines", "message"),
    [
        ("r", [], "name=v1,v2"),
        ("2r=1,2", [], "name=v1,v2"),
        ("r=1,,2", [], "a value is empty"),
        ("r=" + ",".join(str(v) for v in range(13)), [], "at most 12 values"),
        ("r=1,2", ["r=3"], "sets r, which --param varies"),
        ("r=1,../x", [], "without spaces or slashes"),
        ("r=1,a b", [], "without spaces or slashes"),
        ("r=1,1", [], "would share the folder 1"),
        ('r="a",a', [], "would share the folder a"),
    ],
)
def test_a_malformed_study_parameter_is_refused(text, defines, message):
    with pytest.raises(cadkit.Unusable, match=message):
        cadkit._parse_param(text, defines)


def test_a_bad_study_parameter_exits_2_and_makes_no_folder(tmp_path, capsys, numpy_only):
    code, out, err = run(capsys, "study", _model(tmp_path), "--design", tmp_path / "design", "--param", "r=1,../x")
    assert code == 2 and out == "" and "without spaces or slashes" in err
    assert not (tmp_path / "design").exists()


def test_assembly_steps_are_paragraphs_with_their_own_numbering_dropped(tmp_path):
    path = tmp_path / "steps.md"
    path.write_text(
        "# Assembly\n\n1. Push the pin\n   through the hole.\n\nStep 2: Turn it.\n- Snap the lid on.\n* Check it turns.\n\n2.5 mm spacer goes first.\n\n\n",
        encoding="utf-8",
    )
    # A list written without blank lines is still one step per item; a heading is not a step.
    assert cadkit._read_steps(path) == (["Push the pin through the hole.", "Turn it.", "Snap the lid on.", "Check it turns.", "2.5 mm spacer goes first."], False)


def test_assembly_steps_are_bounded(tmp_path):
    path = tmp_path / "steps.md"
    path.write_text("\n\n".join(["x" * 2000] + [f"part {i} goes in" for i in range(40)]), encoding="utf-8")
    steps, cut = cadkit._read_steps(path)
    assert cut and len(steps) == cadkit.MAX_STEPS and len(steps[0]) == cadkit.MAX_STEP_CHARS and steps[0].endswith("…")
    with pytest.raises(cadkit.Unusable, match="--steps"):
        cadkit._read_steps(tmp_path / "missing.md")


def test_a_body_page_lists_the_print_problems_that_name_the_body():
    problems = [
        "base starts at z=1.00, above the bed (z=0.00): it would print in mid-air",
        "base: 3 of 3000 samples thinner than 0.8 mm at x 0.0..1.0",
        "rest / base only 0.1 mm apart (< 0.3): may fuse",
        "baseplate has no flat face on the bed",
        "slicer says: Low bed adhesion / base.stl, strut.stl",
        "slicer says: Low bed adhesion / database.stl",
    ]
    assert cadkit._problems_of("base", problems) == [problems[0], problems[1], problems[2], problems[4]]


def test_the_checks_page_says_what_was_not_checked():
    lines = cadkit._check_lines(None, None, None)
    assert [line.split(";")[0] for line in lines] == ["Poses and sweeps: not checked", "Print: not checked"]


def test_the_checks_page_reads_the_check_print_and_export_results():
    check = {
        "clearance_mm": 0.3,
        "results": [
            {"pose": "seated", "state": "seated", "clashes": [], "gaps": [{"pair": ["a", "b"], "min_gap_mm": 0.5, "tight": False}]},
            {"pose": "swing", "state": "swing @ 0 deg", "clashes": [], "gaps": [{"pair": ["a", "b"], "min_gap_mm": 0.2, "tight": True}]},
            {"pose": "swing", "state": "swing @ 90 deg", "clashes": [{"pair": ["a", "b"], "overlap_mm3": 5.0, "where": "x 0.0..1.0"}], "gaps": []},
        ],
    }
    printed = {"version": "v1/print", "bed_mm": [250, 210, 220], "problems": ["a: bridge spans 20 mm"], "slicer": {"filament_g": "3.84", "time": "22m 17s", "settings": "0.4 mm nozzle"}}
    exported = {"verified": [{"file": "a.step", "ok": True}, {"file": "b.step", "ok": False, "problems": ["volume off"]}]}
    assert cadkit._check_lines(check, printed, exported) == [
        "Poses and sweeps: 3 states across 2 poses (1 sweeps), clearance 0.3 mm.",
        "Clash: a / b in pose swing, worst 5.0 mm3 at [swing @ 90 deg], x 0.0..1.0.",
        "Smallest gap: 0.2 mm, a / b at [swing @ 0 deg].",
        "Print check of v1/print on a 250 x 210 x 220 mm bed: 1 problems.",
        "Problem: a: bridge spans 20 mm",
        "Slicer, the whole plate in one print: 3.84 g, 22m 17s (0.4 mm nozzle).",
        "Export: 1 of 2 files read back as the bodies they came from.",
        "Mismatch: b.step: volume off",
    ]


def _delivery(tmp_path) -> Path:
    """A rendered version as files only: what the zip may take, a link out of it, and a report that names a path."""
    version = tmp_path / "outputs" / "stand" / "v2"
    (version / "print").mkdir(parents=True)
    (version / "views").mkdir()
    (tmp_path / "secret.png").write_bytes(b"not yours")
    body = {"file": "base.stl", "size_mm": [10, 20, 30], "volume_mm3": 6000.0, "solid_mass_g_pla": 7.4, "triangles": 12}
    (version / "report.json").write_text(json.dumps({"version": "v2", "bodies": {"base": body, "ghost": {"error": "empty", "file": "ghost.stl"}}}))
    (version / "print" / "report.json").write_text(json.dumps({"version": "v2/print", "bodies": {"base": body, "evil": {"file": "../../../secret.png"}}}))
    for name in ("base.stl", "print/base.stl", "base.step", "base-cq.step", "model.scad", "views/shaded.png", "notes.txt", "stand-v1.zip"):
        (version / name).write_bytes(name.encode() * 3)
    (version / "base-cq.compare.json").write_text(json.dumps({"passed": True, "b": str(version / "base-cq.step"), "symmetric_difference_pct": 0.2}))
    (version / "views" / "link.png").symlink_to(tmp_path / "secret.png")
    return version


def test_the_zip_takes_only_deliverables_inside_the_version_folder(tmp_path):
    version = _delivery(tmp_path)
    members = [arcname for _, arcname in cadkit._zip_members(version)]
    # The print layout's STLs before the assembled ones; no link, no ../ name, no notes, no older zip.
    assert members == ["print/base.stl", "base.step", "base-cq.step", "model.scad", "views/shaded.png", "report.json", "print/report.json"]
    # An editable STEP goes in only on a passing compare.
    (version / "base-cq.compare.json").write_text(json.dumps({"passed": False, "b": str(version / "base-cq.step")}))
    assert "base-cq.step" not in [arcname for _, arcname in cadkit._zip_members(version)]


def test_the_zip_carries_a_manifest_and_reads_back_against_it(tmp_path):
    version = _delivery(tmp_path)
    entry = cadkit._write_zip(version, [{"file": "base.stl", "kind": "STL", "ok": True, "problems": []}])
    assert entry["ok"] and entry["file"] == "stand-v2.zip" and entry["files"] == 8
    with zipfile.ZipFile(version / "stand-v2.zip") as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert names == [item["path"] for item in manifest["files"]] + ["manifest.json"]
        for item in manifest["files"]:
            assert item["sha256"] == hashlib.sha256(archive.read(item["path"])).hexdigest() == hashlib.sha256((version / item["path"]).read_bytes()).hexdigest()
            assert item["bytes"] == (version / item["path"]).stat().st_size
    assert (manifest["design"], manifest["version"], manifest["made_by"]) == ("stand", "v2", "cadkit.py export --zip")
    assert manifest["bodies"] == {"base": {"size_mm": [10, 20, 30], "volume_mm3": 6000.0, "solid_mass_g_pla": 7.4}}
    assert manifest["editable_step"] == {"base": {"file": "base-cq.step", "symmetric_difference_pct": 0.2}}
    assert manifest["checks"] == {"poses": "not run", "print": "not run", "export": {"files_read_back": 1, "mismatches": 0}}
    assert manifest["print"] is None and "nothing was printed" in manifest["limit"]
    assert not list(version.glob(".*.partial"))


def test_export_needs_something_to_write(tmp_path, capsys, numpy_only):
    version = _delivery(tmp_path)
    code, out, err = run(capsys, "export", version)
    assert code == 2 and out == "" and err.startswith("ERROR: choose --step, --3mf, --zip or several.")


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["a.obj", "b.stl"], "A a.obj: compare reads .stl, .3mf (one body), .step or .stp."),
        (["a.stl", "b.stl"], "does not exist"),
        (["a.stl", "b.stl", "--tolerance", "0"], "--tolerance is a percentage"),
        (["a.stl", "b.stl", "--samples", "10"], "--samples is 100 to 50000"),
    ],
)
def test_compare_refuses_what_it_cannot_measure_before_loading_anything(tmp_path, capsys, argv, message):
    code, out, err = run(capsys, "compare", *[tmp_path / arg if arg.endswith((".obj", ".stl")) else arg for arg in argv])
    assert code == 2 and out == "" and err.startswith("ERROR: ") and message in err


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


@needs_cad
def test_export_reads_every_file_back_and_zips_the_delivery(tmp_path, capsys):
    pytest.importorskip("OCP")
    pytest.importorskip("lxml")
    design, code, out, err = render(capsys, tmp_path, TWO_BOXES, "--print-layout")
    assert code == 0, out + err
    assert run(capsys, "views", design)[0] == 0
    code, out, err = run(capsys, "export", design, "--step", "--3mf", "--zip")
    assert code == 0, out + err
    version = design / "v1"
    assert "read back as written: a.stl, b.stl, print/a.stl, print/b.stl, a.step, b.step, bodies.3mf, design-v1.zip" in out
    assert "PASS: every file reads back as the body it came from" in out
    result = json.loads((version / "export.json").read_text())
    assert result["mismatches"] == 0 and [v["file"] for v in result["verified"]] == ["a.stl", "b.stl", "print/a.stl", "print/b.stl", "a.step", "b.step", "bodies.3mf"]
    step = next(v for v in result["verified"] if v["file"] == "a.step")
    assert (step["solids"], step["open_shells"]) == (1, 0) and step["volume_off_pct"] < 0.5 and step["box_off_mm"] <= 0.05
    assert next(v for v in result["verified"] if v["file"] == "bodies.3mf")["volumes_mm3"] == {"a": 6000, "b": 6000}
    with zipfile.ZipFile(version / "design-v1.zip") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert archive.namelist() == ["print/a.stl", "print/b.stl", "bodies.3mf", "a.step", "b.step", "model.scad", "views/sections.png", "views/shaded.png", "report.json", "print/report.json", "manifest.json"]
        for item in manifest["files"]:
            assert hashlib.sha256(archive.read(item["path"])).hexdigest() == item["sha256"] == hashlib.sha256((version / item["path"]).read_bytes()).hexdigest()
    assert (manifest["design"], manifest["version"], manifest["bodies"]["a"]["volume_mm3"]) == ("design", "v1", 6000)
    assert manifest["checks"] == {"poses": "not run", "print": "not run", "export": {"files_read_back": 7, "mismatches": 0}}
    # A STEP that is not its body's: export says which file and why, and leaves no zip to deliver.
    shutil.copyfile(version / "b.step", version / "a.step")
    code, out, _ = run(capsys, "export", design, "--zip")
    assert code == 1
    assert "FAIL a.step: bounding box 10.500 mm off its mesh's (> 0.05 mm)" in out and "FAIL: 1 file does not read back as written" in out
    assert "zip not written, and the earlier design-v1.zip removed" in out and not (version / "design-v1.zip").exists()


@needs_cad
def test_guide_writes_a_page_per_part_and_says_what_was_not_checked(tmp_path, capsys):
    pytest.importorskip("matplotlib")
    design, code, _, _ = render(capsys, tmp_path, TWO_BOXES, "--print-layout")
    assert code == 0
    # Nothing checked and no steps: every page is still there, each gap a line saying so. A "$" is text, not math.
    code, out, err = run(capsys, "guide", design, "--title", "Two $boxes$ for 5$")
    assert code == 0, out + err
    # Cover, parts, a page per body, assembly, checks.
    assert out.startswith("v1: guide.pdf written, 6 pages")
    assert "note: no check.json" in out and "note: no print.json" in out and "note: no --steps" in out
    pdf = (design / "v1" / "guide.pdf").read_bytes()
    assert pdf.startswith(b"%PDF") and len(re.findall(rb"/Type\s*/Page\b", pdf)) == 6
    assert not list((design / "v1").glob(".*.partial"))
    assert run(capsys, "check", design)[0] == 0
    run(capsys, "print", design)
    steps = tmp_path / "workspace" / "steps.md"
    steps.write_text("1. Stand a on the bench.\n\n2. Set b beside it, 0.5 mm away.\n")
    code, out, _ = run(capsys, "guide", design, "--steps", steps)
    assert code == 0 and "note:" not in out
    code, _, err = run(capsys, "guide", design, "--steps", tmp_path / "missing.md")
    assert code == 2 and err.startswith("ERROR: --steps")


@needs_cad
def test_study_renders_each_value_outside_the_versions_and_tabulates_them(tmp_path, capsys):
    pytest.importorskip("matplotlib")
    work = tmp_path / "workspace"
    work.mkdir()
    (work / "model.scad").write_text(TWO_BOXES)
    design = tmp_path / "outputs" / "design"
    code, out, err = run(capsys, "study", work / "model.scad", "--design", design, "--param", "gap=0.5,-2,0.1")
    assert code == 0, out + err
    lines = out.splitlines()
    assert lines[0].startswith("study gap: 3 values rendered in ") and lines[0].endswith(str(design / "studies" / "gap"))
    assert [line.split() for line in lines[2:6]] == [
        ["gap", "clashes", "smallest", "gap", "a", "mm3", "b", "mm3"],
        ["0.5", "0", "0.5", "6000", "6000"],
        ["-2", "1", "-", "6000", "6000"],
        ["0.1", "0", "0.1", "6000", "6000"],
    ]
    assert "passes: 0.5, 0.1 (every body a closed solid, no clash in any state)" in out
    # The study is no version: the design page's list stays as it was.
    assert sorted(p.name for p in design.iterdir()) == ["studies"]
    root = design / "studies" / "gap"
    assert (root / "-2" / "a.stl").is_file() and (root / "compare.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    study = json.loads((root / "study.json").read_text())
    assert [(r["value"], r["clashes"], r["passes"]) for r in study["results"]] == [("0.5", 0, True), ("-2", 1, False), ("0.1", 0, True)]
    # check and views take a value's folder like a version.
    code, out, _ = run(capsys, "check", root / "-2")
    assert code == 1 and out.startswith("studies/gap/-2: 1 states checked")
    # Run again under the same name, it replaces the last run; no value passing exits 1.
    code, out, _ = run(capsys, "study", work / "model.scad", "--design", design, "--param", "gap=-2,-1", "--section", "y=10")
    assert code == 1 and "no value passes" in out and "the y = 10 section" in out
    assert sorted(p.name for p in root.iterdir()) == ["-1", "-2", "compare.png", "model.scad", "study.json"]


@needs_cad
def test_testpiece_cuts_the_joint_out_of_each_body(tmp_path, capsys):
    design, code, _, _ = render(capsys, tmp_path, TWO_BOXES)
    assert code == 0
    # A slab across the gap between a (x 0..10) and b (x 10.5..20.5), 10 mm tall.
    code, out, err = run(capsys, "testpiece", design, "--box", "6,0,0,14.5,20,10")
    assert code == 0, out + err
    assert out.startswith("v1/test: 2 pieces cut by the box x 6.0..14.5 y 0.0..20.0 z 0.0..10.0")
    assert "  a: 4 x 20 x 10 mm, vol 800 mm3, ~1 g solid PLA, 13.3% of the body" in out
    assert "smallest gap: 0.5 mm, a / b" in out and "PASS: the pieces do not overlap" in out
    folder = design / "v1" / "test"
    result = json.loads((folder / "test.json").read_text())
    assert {name: piece["volume_mm3"] for name, piece in result["pieces"].items()} == {"a": 800, "b": 800}
    assert result["box_mm"] == [6, 0, 0, 14.5, 20, 10] and result["clashes"] == []
    code, out, _ = run(capsys, "views", folder)
    assert code == 0 and out.startswith("v1/test: views written")
    # By default a body the box misses is left out; a body named in --bodies must be cut.
    code, out, _ = run(capsys, "testpiece", design, "--box", "0,0,0,5,5,5")
    assert code == 0 and "1 piece cut" in out and "left out, the box misses them: b" in out
    code, out, err = run(capsys, "testpiece", design, "--box", "0,0,0,5,5,5", "--bodies", "a,b")
    assert code == 2 and out == ""
    assert err.startswith("ERROR: the box x 0.0..5.0 y 0.0..5.0 z 0.0..5.0 holds nothing of b (b spans x 10.5..20.5")
    assert sorted(p.name for p in folder.glob("*.stl")) == ["a.stl"]
    code, _, err = run(capsys, "testpiece", design, "--box", "0,0,0,5,5,5", "--bodies", "c")
    assert code == 2 and "no body 'c'" in err


@needs_cad
def test_compare_proves_a_step_against_its_stl_and_catches_another_solid(tmp_path, capsys):
    pytest.importorskip("OCP")
    design, code, _, _ = render(capsys, tmp_path, TWO_BOXES)
    assert code == 0 and run(capsys, "export", design, "--step")[0] == 0
    version = design / "v1"
    code, out, err = run(capsys, "compare", version / "a.stl", version / "a.step")
    assert code == 0, out + err
    assert "symmetric difference: 0.0 mm3, 0.00% of A" in out and "PASS: symmetric difference 0.00% < 1% of A" in out
    result = json.loads((version / "a.compare.json").read_text())
    assert result["passed"] and result["b_info"]["solids"] == 1 and result["max_deviation_mm"] < 0.01
    # b is a 6000 mm3 box beside a: the volumes agree, so only the symmetric difference and the deviation tell them apart.
    code, out, _ = run(capsys, "compare", version / "a.stl", version / "b.stl")
    assert code == 1 and "volume differs by +0.0 mm3 (0.00% of A)" in out and "FAIL: symmetric difference 200.00% >= 1% of A" in out
    # Every point of a's far face is 10.5 mm from b's near face, and b's far face as far from a.
    assert "largest surface deviation: 10.500 mm at (" in out


@needs_cad
def test_a_body_rebuilt_in_cadquery_is_proven_and_joins_the_zip(tmp_path, capsys):
    cq = pytest.importorskip("cadquery")
    pytest.importorskip("lxml")
    design, code, _, _ = render(capsys, tmp_path, TWO_BOXES)
    assert code == 0
    version = design / "v1"
    cq.exporters.export(cq.Workplane().box(10, 20, 30, centered=False), str(version / "a-cq.step"))
    # 1 mm short: compare fails it, so export leaves it out.
    cq.exporters.export(cq.Workplane().box(10.5, 20, 29, centered=False).translate((10, 0, 0)), str(version / "b-cq.step"))
    assert run(capsys, "compare", version / "a.stl", version / "a-cq.step")[0] == 0
    assert run(capsys, "compare", version / "b.stl", version / "b-cq.step")[0] == 1
    code, out, err = run(capsys, "export", design, "--3mf", "--zip")
    assert code == 0, out + err
    assert "b-cq.step left out of the zip: no passing compare. Run cadkit.py compare b.stl b-cq.step in this folder." in out
    with zipfile.ZipFile(version / "design-v1.zip") as archive:
        assert "a-cq.step" in archive.namelist() and "b-cq.step" not in archive.namelist()
        editable = json.loads(archive.read("manifest.json"))["editable_step"]
    assert list(editable) == ["a"] and editable["a"]["symmetric_difference_pct"] == pytest.approx(0, abs=0.01)
    # A 3MF holds both bodies: compare takes one solid per file.
    code, _, err = run(capsys, "compare", version / "a.stl", version / "bodies.3mf")
    assert code == 2 and "holds 2 bodies" in err
