#!/usr/bin/env python3
"""cadkit: render, check, look at and export a multi-body OpenSCAD model.

Runs inside the conversation's sandbox container (the CAD image), never in the
Gateway. Every command reads and writes one version folder, so a design keeps
its history: ``render`` makes ``<design>/v<N>/`` and the other commands take
that folder, or the design folder for its newest version.

    cadkit.py render    model.scad --design /mnt/user-data/outputs/stand [-D name=value ...]
    cadkit.py check     /mnt/user-data/outputs/stand [--poses poses.json] [--clearance 0.3]
    cadkit.py views     /mnt/user-data/outputs/stand [--sections z=5,y=0] [--poses p.json --pose NAME [--at 40]]
    cadkit.py print     /mnt/user-data/outputs/stand/print [--bed 250x210x220] [--slice]
    cadkit.py export    /mnt/user-data/outputs/stand [--step] [--3mf] [--zip]
    cadkit.py guide     /mnt/user-data/outputs/stand [--title T] [--steps steps.md]
    cadkit.py study     model.scad --design /mnt/user-data/outputs/stand --param r=8,10,12 [--poses poses.json]
    cadkit.py testpiece /mnt/user-data/outputs/stand --box 0,0,0,30,20,15 [--bodies base,pin]
    cadkit.py compare   base.stl base-cq.step [--tolerance 1]

``study`` renders into ``<design>/studies/<name>/<value>/``, outside the
versions; ``testpiece`` writes ``v<N>/test/``. Both of those folders, like
``v<N>/print/``, hold a report.json, so ``views`` and ``print`` take them too.

Units are millimetres, Z up, as OpenSCAD writes them. A model of several bodies
declares them in one top-level list and draws one body per ``part`` value:

    part = "all";                       // cadkit sets this per body
    BODIES = ["base", "strut"];
    if (part == "base" || part == "all") base();
    if (part == "strut" || part == "all") strut();

Each command prints a short summary for the model to read and writes the full
result as JSON next to the meshes. Exit status: 0 pass, 1 a check failed,
2 the command could not run (bad input, a render error, a missing tool).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
import warnings as warnings_module
import zipfile
from pathlib import Path

NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
BODIES_LINE = re.compile(r"^\s*BODIES\s*=\s*\[([^\]]*)\]\s*;", re.MULTILINE)
QUOTED = re.compile(r'"([^"]*)"')
DEFINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.+$")
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PLA_DENSITY_G_CM3 = 1.24
PALETTE = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2", "#EECA3B", "#9D755D", "#FF9DA6", "#BAB0AC"]
MAX_SWEEP_STEPS = 360
MAX_STEP_TRIANGLES = 60000
# PrusaSlicer's own log lines ("[2026-...] [0x7f...] [trace]   Initializing StaticPrintConfigs"), printed on every run.
SLICER_LOG = re.compile(r"^\[[^\]]*\] \[0x[0-9a-fA-F]+\] \[(trace|debug|info)\]")
# A written file reads back as its body within these: STEP volume and box against the mesh, STL against report.json.
VERIFY_VOLUME_PCT = 0.5
VERIFY_BOX_MM = 0.05
MAX_STUDY_VALUES = 12
# steps.md is model-written text: read this much, keep this many paragraphs of this length.
MAX_STEPS_BYTES = 20000
MAX_STEPS = 30
MAX_STEP_CHARS = 600
# Chord and angle tolerance when a STEP's B-rep is turned into triangles for compare.
STEP_DEFLECTION_MM = 0.01
STEP_ANGLE_RAD = 0.05
# A file the zip may carry: a plain name, at most one known subfolder deep.
ARCNAME = re.compile(r"^(?:(?:print|views|test)/)?[A-Za-z0-9_+-][A-Za-z0-9_.+-]{0,99}$")
LIMIT = "Every figure here is a check on the model, not on a print: nothing was printed, and a test print decides the fits."
OCP_MISSING = "CadQuery (OCP) is not installed here; it is in the CAD sandbox image."


class Failed(Exception):
    """A check ran and the part failed it (exit 1)."""


class Unusable(Exception):
    """The command could not run (exit 2)."""


# ---------------------------------------------------------------- helpers


def _lazy_imports():
    try:
        import numpy as np
        import trimesh
    except ImportError as exc:  # pragma: no cover - the image provides both
        raise Unusable(f"{exc.name} is not installed here. This needs the CAD sandbox image (make sandbox-enable MODE=container IMAGE=cad).") from exc
    return np, trimesh


def _manifold():
    try:
        import manifold3d
    except ImportError as exc:  # pragma: no cover
        raise Unusable("manifold3d is not installed here. This needs the CAD sandbox image (make sandbox-enable MODE=container IMAGE=cad).") from exc
    return manifold3d


def _r(value: float, digits: int = 3) -> float:
    return float(round(float(value), digits))


def _version_dir(path: Path) -> Path:
    """A version folder (has report.json), or the newest v<N> inside a design folder."""
    path = path.resolve()
    if (path / "report.json").is_file():
        return path
    versions = sorted(
        (p for p in path.glob("v*") if p.is_dir() and re.fullmatch(r"v\d+", p.name) and (p / "report.json").is_file()),
        key=lambda p: int(p.name[1:]),
    )
    if not versions:
        raise Unusable(f"{path} holds no rendered version (no report.json). Run: cadkit.py render model.scad --design {path}")
    return versions[-1]


def _next_version(design: Path) -> Path:
    design.mkdir(parents=True, exist_ok=True)
    numbers = [int(p.name[1:]) for p in design.glob("v*") if p.is_dir() and re.fullmatch(r"v\d+", p.name)]
    target = design / f"v{max(numbers, default=0) + 1}"
    target.mkdir()
    return target


def _bodies_of(source: str, given: str | None) -> list[str]:
    if given:
        names = [n.strip() for n in given.split(",") if n.strip()]
    else:
        match = BODIES_LINE.search(_strip_comments(source))
        names = QUOTED.findall(match.group(1)) if match else []
    for name in names:
        if not NAME.match(name):
            raise Unusable(f"body name {name!r}: use letters, digits, '-' or '_' (at most 40).")
    if len(set(names)) != len(names):
        raise Unusable("a body name is listed twice in BODIES.")
    return names


def _strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", source)


def _load_report(version: Path) -> dict:
    return json.loads((version / "report.json").read_text())


def _label(folder: Path) -> str:
    """How a summary names a folder: its report.json says (v3, v3/print, v3/test, studies/r/8)."""
    named = (_read_json(folder / "report.json") or {}).get("version")
    return named if isinstance(named, str) and re.fullmatch(r"[A-Za-z0-9_.+/-]{1,120}", named) else folder.name


def _load_meshes(version: Path) -> dict:
    np, trimesh = _lazy_imports()
    report = _load_report(version)
    meshes = {}
    for name, info in report["bodies"].items():
        if "error" in info:
            continue
        mesh = trimesh.load(version / info["file"], force="mesh", process=True)
        meshes[name] = mesh
    if not meshes:
        raise Unusable(f"{version} has no body that rendered.")
    return meshes


def _version_root(path: Path) -> Path:
    """The version folder itself: a version's print/ or test/ folder stands for the version it belongs to."""
    version = _version_dir(path)
    if version.name in ("print", "test") and re.fullmatch(r"v\d+", version.parent.name) and (version.parent / "report.json").is_file():
        return version.parent
    return version


def _to_manifold(name: str, mesh, hint: str = "fix the model (render reports which bodies are not watertight) before checking it"):
    np, _ = _lazy_imports()
    m3d = _manifold()
    solid = m3d.Manifold(m3d.Mesh(vert_properties=np.asarray(mesh.vertices, dtype=np.float32), tri_verts=np.asarray(mesh.faces, dtype=np.uint32)))
    if solid.status() != m3d.Error.NoError:
        raise Unusable(f"body {name} is not a closed solid ({solid.status()}); {hint}.")
    return solid


def _from_manifold(solid):
    np, trimesh = _lazy_imports()
    mesh = solid.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties, dtype=float)[:, :3], faces=np.asarray(mesh.tri_verts, dtype=np.int64), process=True)


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")


def _read_json(path: Path) -> dict | None:
    """A JSON object cadkit wrote earlier, or None when the file is missing or unreadable."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _clear(folder: Path) -> None:
    """Remove a folder cadkit writes afresh; a link there is removed, never followed."""
    if folder.is_symlink() or folder.is_file():
        folder.unlink()
    elif folder.exists():
        shutil.rmtree(folder)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@contextlib.contextmanager
def _quiet_stdout():
    """The OCP kernel prints transfer statistics on file descriptor 1; keep them out of the summary."""
    sys.stdout.flush()
    saved = os.dup(1)
    try:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), 1)
            yield
    finally:
        os.dup2(saved, 1)
        os.close(saved)


def _colours(report: dict) -> dict:
    """Body name -> colour, in report order: the colour it has in assembly.glb and on the design page."""
    return {name: PALETTE[index % len(PALETTE)] for index, name in enumerate(report.get("bodies", {}))}


def _fmt_box(lo, hi) -> str:
    return " ".join(f"{axis} {lo[i]:.1f}..{hi[i]:.1f}" for i, axis in enumerate("xyz"))


# ---------------------------------------------------------------- poses


def _rotation(axis, degrees):
    np, _ = _lazy_imports()
    axis = np.asarray(axis, dtype=float)
    norm = np.linalg.norm(axis)
    if norm == 0:
        raise Unusable("a rotation axis is [0, 0, 0].")
    x, y, z = axis / norm
    a = math.radians(degrees)
    c, s, t = math.cos(a), math.sin(a), 1 - math.cos(a)
    m = np.eye(4)
    m[:3, :3] = [[t * x * x + c, t * x * y - s * z, t * x * z + s * y], [t * x * y + s * z, t * y * y + c, t * y * z - s * x], [t * x * z - s * y, t * y * z + s * x, t * z * z + c]]
    return m


def _translation(vector):
    np, _ = _lazy_imports()
    m = np.eye(4)
    m[:3, 3] = vector
    return m


def _vec(value, what: str) -> list[float]:
    if not (isinstance(value, list) and len(value) == 3 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in value)):
        raise Unusable(f"{what} must be three numbers, like [0, 0, 10].")
    return [float(v) for v in value]


def _step_matrix(step: dict, where: str):
    """One placement step, in OpenSCAD's meaning: translate, rotate([x,y,z]) or rotate(a, v), about a point."""
    if not isinstance(step, dict):
        raise Unusable(f'{where}: each step is an object such as {{"rotate": [0, 30, 0], "about": [0, 0, 10]}}.')
    unknown = set(step) - {"translate", "rotate", "axis", "angle", "about"}
    if unknown:
        raise Unusable(f"{where}: unknown key(s) {sorted(unknown)}; use translate, rotate, axis with angle, and about.")
    if "translate" in step:
        if set(step) != {"translate"}:
            raise Unusable(f"{where}: a translate step stands alone.")
        return _translation(_vec(step["translate"], f"{where}.translate"))
    about = _vec(step.get("about", [0, 0, 0]), f"{where}.about")
    if "rotate" in step:
        rx, ry, rz = _vec(step["rotate"], f"{where}.rotate")
        # OpenSCAD's rotate([x, y, z]) turns about X, then Y, then Z.
        turn = _rotation([0, 0, 1], rz) @ _rotation([0, 1, 0], ry) @ _rotation([1, 0, 0], rx)
    elif "axis" in step and "angle" in step:
        angle = step["angle"]
        if not isinstance(angle, (int, float)) or not math.isfinite(angle):
            raise Unusable(f"{where}.angle must be a number of degrees.")
        turn = _rotation(_vec(step["axis"], f"{where}.axis"), float(angle))
    else:
        raise Unusable(f"{where}: give translate, rotate, or axis with angle.")
    return _translation(about) @ turn @ _translation([-c for c in about])


def _place(steps, where: str):
    np, _ = _lazy_imports()
    if isinstance(steps, dict):
        steps = [steps]
    if not isinstance(steps, list):
        raise Unusable(f"{where}: a list of steps.")
    matrix = np.eye(4)
    for index, step in enumerate(steps):
        # Each later step acts on the already placed body, as nested OpenSCAD transforms read from the inside out.
        matrix = _step_matrix(step, f"{where}[{index}]") @ matrix
    return matrix


def _sweep_values(sweep: dict, where: str) -> list[float]:
    try:
        start, stop = float(sweep["from"]), float(sweep["to"])
    except (KeyError, TypeError, ValueError) as exc:
        raise Unusable(f"{where}: a sweep needs numbers from and to.") from exc
    steps = int(sweep.get("steps", 12))
    if not 1 <= steps <= MAX_SWEEP_STEPS:
        raise Unusable(f"{where}.steps must be 1..{MAX_SWEEP_STEPS}.")
    if steps == 1:
        return [start]
    return [start + (stop - start) * i / (steps - 1) for i in range(steps)]


def _sweep_matrix(sweep: dict, value: float, where: str):
    if "axis" in sweep:
        return _step_matrix({"axis": sweep["axis"], "angle": value, "about": sweep.get("about", [0, 0, 0])}, where)
    if "direction" in sweep:
        np, _ = _lazy_imports()
        d = np.asarray(_vec(sweep["direction"], f"{where}.direction"))
        n = np.linalg.norm(d)
        if n == 0:
            raise Unusable(f"{where}.direction is [0, 0, 0].")
        return _translation(d / n * value)
    raise Unusable(f"{where}: a sweep turns about an axis (axis, about, from, to in degrees) or slides along a direction (direction, from, to in mm).")


def _read_poses(path: Path | None, bodies: list[str]) -> dict:
    if path is None:
        return {"poses": [{"name": "assembled"}], "ignore": [], "tolerance_mm3": 0.01}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise Unusable(f"{path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("poses"), list) or not data["poses"]:
        raise Unusable(f'{path}: expected {{"poses": [{{"name": ..., "place": {{body: [steps]}}, "sweep": {{...}}}}]}}.')
    for index, pose in enumerate(data["poses"]):
        where = f"poses[{index}]"
        if not isinstance(pose, dict) or not isinstance(pose.get("name"), str) or not pose["name"]:
            raise Unusable(f"{where}: every pose has a name.")
        unknown = set(pose) - {"name", "place", "sweep"}
        if unknown:
            raise Unusable(f"{where}: unknown key(s) {sorted(unknown)}.")
        if not isinstance(pose.get("place", {}), dict):
            raise Unusable(f'{where}.place maps each body to its steps, like {{"lid": [{{"translate": [0, 0, 5]}}]}}.')
        for body in pose.get("place", {}):
            if body not in bodies:
                raise Unusable(f"{where}.place: no body {body!r}; bodies are {bodies}.")
        sweep = pose.get("sweep")
        if sweep is not None:
            if not isinstance(sweep, dict):
                raise Unusable(f'{where}.sweep is an object, like {{"body": "lid", "direction": [0, 0, 1], "from": 0, "to": 30}}.')
            moving = sweep.get("bodies", [sweep.get("body")])
            if not moving or any(b not in bodies for b in moving):
                raise Unusable(f"{where}.sweep: name the moving body (body) or bodies (bodies) from {bodies}.")
    ignore = data.get("ignore", [])
    if not isinstance(ignore, list) or not all(isinstance(p, list) and len(p) == 2 and all(b in bodies for b in p) for p in ignore):
        raise Unusable(f'{path}: ignore is a list of body pairs, like [["pin", "base"]].')
    data.setdefault("tolerance_mm3", 0.01)
    data["ignore"] = ignore
    return data


def _pose_states(pose: dict, bodies: list[str]):
    """(label, {body: 4x4}) for each state of a pose: one, or one per sweep value."""
    np, _ = _lazy_imports()
    where = f"pose {pose['name']!r}"
    base = {b: _place(pose.get("place", {}).get(b, []), f"{where}.place.{b}") for b in bodies}
    sweep = pose.get("sweep")
    if not sweep:
        return [(pose["name"], base)]
    moving = sweep.get("bodies") or [sweep["body"]]
    unit = "deg" if "axis" in sweep else "mm"
    states = []
    for value in _sweep_values(sweep, f"{where}.sweep"):
        move = _sweep_matrix(sweep, value, f"{where}.sweep")
        placed = {b: (move @ m if b in moving else m) for b, m in base.items()}
        states.append((f"{pose['name']} @ {value:g} {unit}", placed))
    return states


# ---------------------------------------------------------------- render


def _openscad() -> str:
    exe = shutil.which("openscad")
    if not exe:
        raise Unusable("openscad is not installed here. CAD runs in the CAD sandbox image: make sandbox-enable MODE=container IMAGE=cad.")
    return exe


def _openscad_flags(exe: str) -> list[str]:
    try:
        run = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    text = run.stdout + run.stderr
    # Newer OpenSCAD builds render through Manifold, often a hundred times faster than CGAL.
    return ["--backend=manifold"] if "--backend" in text else []


def _measure(mesh) -> dict:
    np, trimesh = _lazy_imports()
    lo, hi = mesh.bounds
    shells = mesh.split(only_watertight=False)
    info = {
        "size_mm": [_r(v, 2) for v in (hi - lo)],
        "min_mm": [_r(v, 2) for v in lo],
        "max_mm": [_r(v, 2) for v in hi],
        "triangles": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
        "shells": int(len(shells)),
        "area_mm2": _r(mesh.area, 1),
    }
    if mesh.is_volume:
        info["volume_mm3"] = _r(mesh.volume, 1)
        info["solid_mass_g_pla"] = _r(mesh.volume / 1000 * PLA_DENSITY_G_CM3, 1)
        info["center_of_mass_mm"] = [_r(v, 2) for v in mesh.center_mass]
    return info


def _assembly_glb(meshes: dict, target: Path) -> None:
    np, trimesh = _lazy_imports()
    # glTF is metres and Y-up: (x, y, z) mm -> (x, z, -y) m, as the file preview expects.
    to_gltf = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], dtype=float) * np.array([0.001, 0.001, 0.001, 1.0])[:, None]
    scene = trimesh.Scene()
    for index, (name, mesh) in enumerate(meshes.items()):
        copy = mesh.copy()
        colour = PALETTE[index % len(PALETTE)].lstrip("#")
        rgba = [int(colour[i : i + 2], 16) for i in (0, 2, 4)] + [255]
        copy.visual = trimesh.visual.ColorVisuals(copy, face_colors=np.tile(rgba, (len(copy.faces), 1)))
        copy.apply_transform(to_gltf)
        scene.add_geometry(copy, node_name=name, geom_name=name)
    target.write_bytes(scene.export(file_type="glb"))


def _overlaps(meshes: dict, matrices: dict | None, ignore: list, tolerance: float, clearance: float) -> tuple[list, list]:
    """Pairwise intersection volume and smallest gap of the placed bodies."""
    solids = {}
    for name, mesh in meshes.items():
        solid = _to_manifold(name, mesh)
        if matrices is not None:
            solid = solid.transform(matrices[name][:3, :4])
        solids[name] = solid
    skip = {frozenset(p) for p in ignore}
    clashes, gaps = [], []
    for a, b in itertools.combinations(solids, 2):
        if frozenset((a, b)) in skip:
            continue
        common = solids[a] ^ solids[b]
        volume = common.volume()
        if volume > tolerance:
            box = common.bounding_box()
            clashes.append({"pair": [a, b], "overlap_mm3": _r(volume, 3), "where": _fmt_box(box[:3], box[3:])})
            continue
        search = max(clearance * 4, 2.0)
        gap = solids[a].min_gap(solids[b], search)
        gaps.append({"pair": [a, b], "min_gap_mm": _r(gap, 3) if gap < search else None, "tight": bool(gap < clearance)})
    return clashes, gaps


def _render_set(exe: str, flags: list[str], source_path: Path, folder: Path, bodies: list[str], defines: list[str], timeout: int) -> dict:
    """Render each body of *source_path* into *folder* and measure it; the report as a dict."""
    np, trimesh = _lazy_imports()
    started = time.monotonic()
    report = {"model": str(source_path), "defines": defines, "bodies": {}, "warnings": [], "echo": []}
    for name in bodies or ["part"]:
        out = folder / f"{name}.stl"
        command = [exe, "-o", str(out), "--export-format", "binstl", *flags]
        if bodies:
            command += ["-D", f'part="{name}"']
        for define in defines:
            command += ["-D", define]
        command.append(str(source_path))
        try:
            run = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=source_path.parent)
        except subprocess.TimeoutExpired:
            report["bodies"][name] = {"error": f"render took longer than {timeout} s; lower $fn or simplify (minkowski and hull of many parts are slow)."}
            continue
        log = (run.stdout + run.stderr).splitlines()
        report["warnings"] += [f"{name}: {line}" for line in log if line.startswith(("WARNING", "DEPRECATED"))]
        report["echo"] += [f"{name}: {line[6:]}" for line in log if line.startswith("ECHO:")][:50]
        errors = [line for line in log if line.startswith("ERROR") or "top level object is empty" in line.lower()]
        if run.returncode != 0 or not out.is_file():
            report["bodies"][name] = {"error": "; ".join(errors) or f"openscad exited {run.returncode}", "file": out.name}
            continue
        mesh = trimesh.load(out, force="mesh", process=True)
        if len(mesh.faces) == 0:
            report["bodies"][name] = {"error": "the body is empty: nothing is drawn for this part value", "file": out.name}
            continue
        report["bodies"][name] = {"file": out.name, **_measure(mesh)}
    report["seconds"] = _r(time.monotonic() - started, 1)
    return report


def _print_bodies(report: dict) -> None:
    for name, info in report["bodies"].items():
        if "error" in info:
            print(f"  {name}: ERROR {info['error']}")
            continue
        size = " x ".join(f"{v:g}" for v in info["size_mm"])
        extra = f"vol {info['volume_mm3']:g} mm3, ~{info['solid_mass_g_pla']:g} g solid PLA" if "volume_mm3" in info else "NOT A CLOSED SOLID (volume unknown)"
        shells = "" if info["shells"] == 1 else f", {info['shells']} separate shells"
        print(f"  {name}: {size} mm, {extra}{shells}, {info['triangles']} triangles")


def cmd_render(args) -> int:
    np, trimesh = _lazy_imports()
    source_path = Path(args.model).resolve()
    if not source_path.is_file():
        raise Unusable(f"{source_path} does not exist.")
    source = source_path.read_text(errors="replace")
    bodies = _bodies_of(source, args.bodies)
    for define in args.define:
        if not DEFINE.match(define):
            raise Unusable(f"-D {define!r}: write name=value, like -D wall=2 or -D 'label=\"A\"'.")
    exe = _openscad()
    flags = _openscad_flags(exe)
    version = _next_version(Path(args.design).resolve())
    shutil.copyfile(source_path, version / "model.scad")
    report = {"version": version.name, **_render_set(exe, flags, source_path, version, bodies, args.define, args.timeout)}
    meshes = {n: trimesh.load(version / i["file"], force="mesh") for n, i in report["bodies"].items() if "error" not in i}
    if meshes:
        _assembly_glb(meshes, version / "assembly.glb")
    solid = {n: m for n, m in meshes.items() if m.is_volume}
    if len(solid) > 1:
        clashes, gaps = _overlaps(solid, None, [], 0.01, args.clearance)
        report["assembled"] = {"clashes": clashes, "gaps": gaps}
    layout = None
    if args.print_layout:
        folder = version / "print"
        folder.mkdir()
        layout = {"version": f"{version.name}/print", **_render_set(exe, flags, source_path, folder, bodies, [*args.define, 'layout="print"'], args.timeout)}
        _write_json(folder / "report.json", layout)
    _write_json(version / "report.json", report)

    count = len(bodies or ["part"])
    print(f"{version.name}: {len(meshes)}/{count} bodies rendered in {report['seconds']} s -> {version}")
    _print_bodies(report)
    for clash in report.get("assembled", {}).get("clashes", []):
        print(f"  CLASH as modelled: {clash['pair'][0]} / {clash['pair'][1]} overlap {clash['overlap_mm3']} mm3 at {clash['where']}")
    for line in report["warnings"][:10]:
        print(f"  {line}")
    if report["echo"]:
        print(f"  echo: {len(report['echo'])} lines in report.json")
    if layout is not None:
        print(f'  print layout (layout="print") -> {version / "print"}')
        _print_bodies(layout)
    print(f"  files: {', '.join(sorted(p.name for p in version.iterdir()))}")
    failed = any("error" in i for r in (report, layout or {"bodies": {}}) for i in r["bodies"].values())
    unsound = [n for n, m in meshes.items() if not m.is_volume]
    if unsound:
        print(f"  not closed solids: {', '.join(unsound)} - check unions that only touch, zero-thickness walls, or 2D shapes left in the part.")
    return 2 if failed or not meshes else (1 if unsound or report.get("assembled", {}).get("clashes") else 0)


# ---------------------------------------------------------------- check


def cmd_check(args) -> int:
    version = _version_dir(Path(args.path))
    meshes = _load_meshes(version)
    bodies = list(meshes)
    poses = _read_poses(Path(args.poses).resolve() if args.poses else None, bodies)
    if len(bodies) < 2:
        raise Unusable("collision checks need at least two bodies.")
    results, worst = [], None
    clash_count = 0
    for pose in poses["poses"]:
        for label, matrices in _pose_states(pose, bodies):
            clashes, gaps = _overlaps(meshes, matrices, poses["ignore"], float(poses["tolerance_mm3"]), args.clearance)
            clash_count += len(clashes)
            results.append({"pose": pose["name"], "state": label, "clashes": clashes, "gaps": gaps})
            for gap in gaps:
                if gap["min_gap_mm"] is not None and (worst is None or gap["min_gap_mm"] < worst[0]):
                    worst = (gap["min_gap_mm"], gap["pair"], label)
    states = len(results)
    out = {"version": version.name, "poses_file": args.poses, "clearance_mm": args.clearance, "states": states, "clashes": clash_count, "results": results}
    _write_json(version / "check.json", out)

    print(f"{_label(version)}: {states} states checked across {len(poses['poses'])} poses, {len(bodies)} bodies")
    # One line per pair and pose: a sweep that clashes in ten states is one finding, shown at its worst.
    findings: dict[tuple, dict] = {}
    for result in results:
        items = [("CLASH", c, c["overlap_mm3"]) for c in result["clashes"]] + [("tight", g, -g["min_gap_mm"]) for g in result["gaps"] if g["tight"]]
        for kind, item, badness in items:
            key = (kind, item["pair"][0], item["pair"][1], result["pose"])
            entry = findings.setdefault(key, {"states": [], "worst": None, "badness": None})
            entry["states"].append(result["state"])
            if entry["badness"] is None or badness > entry["badness"]:
                entry["worst"], entry["badness"], entry["at"] = item, badness, result["state"]
    for shown, ((kind, a, b, _), entry) in enumerate(findings.items()):
        if shown == 15:
            print(f"  ... {len(findings) - 15} more in check.json")
            break
        item = entry["worst"]
        text = f"{item['overlap_mm3']} mm3 at {item['where']}" if kind == "CLASH" else f"gap {item['min_gap_mm']} mm < {args.clearance} mm"
        count = len(entry["states"])
        spread = f" in {count} states, worst at [{entry['at']}]" if count > 1 else f" at [{entry['at']}]"
        print(f"  {kind} {a} / {b}{spread}: {text}")
    if worst:
        print(f"  smallest gap: {worst[0]} mm, {worst[1][0]} / {worst[1][1]} at [{worst[2]}]")
    print("  PASS: no overlap in any state" if clash_count == 0 else f"  FAIL: {clash_count} overlaps")
    return 1 if clash_count else 0


# ---------------------------------------------------------------- views


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _placed_meshes(version: Path, args) -> dict:
    meshes = _load_meshes(version)
    if not args.pose:
        return meshes
    if not args.poses:
        raise Unusable("--pose needs --poses FILE.")
    poses = _read_poses(Path(args.poses).resolve(), list(meshes))
    match = [p for p in poses["poses"] if p["name"] == args.pose]
    if not match:
        raise Unusable(f"no pose named {args.pose!r} in {args.poses}.")
    pose = dict(match[0])
    if pose.get("sweep") and args.at is not None:
        pose["sweep"] = {**pose["sweep"], "from": args.at, "to": args.at, "steps": 1}
    elif pose.get("sweep"):
        pose.pop("sweep")
    _, matrices = _pose_states(pose, list(meshes))[0]
    placed = {}
    for name, mesh in meshes.items():
        copy = mesh.copy()
        copy.apply_transform(matrices[name])
        placed[name] = copy
    return placed


def _bounds(meshes: dict):
    np, _ = _lazy_imports()
    lo = np.min([m.bounds[0] for m in meshes.values()], axis=0)
    hi = np.max([m.bounds[1] for m in meshes.values()], axis=0)
    return lo, hi


def _draw_shaded(ax, meshes: dict, elev: float, azim: float, bounds=None, colours: dict | None = None) -> None:
    """The bodies as lit flat-shaded triangles on one 3D axis, equal scale on every axis."""
    np, _ = _lazy_imports()
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    lo, hi = bounds if bounds is not None else _bounds(meshes)
    span = float(np.maximum(hi - lo, 1e-6).max())
    light = np.array([0.4, -0.5, 0.75])
    light /= np.linalg.norm(light)
    triangles, faces = [], []
    for colour_index, (name, mesh) in enumerate(meshes.items()):
        colour = (colours or {}).get(name, PALETTE[colour_index % len(PALETTE)])
        base = np.array([int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)])
        shade = 0.35 + 0.65 * np.clip(mesh.face_normals @ light, 0, 1)
        triangles.append(mesh.triangles)
        faces.append(np.clip(base[None, :] * shade[:, None], 0, 1))
        ax.plot([], [], color=base, label=name, linewidth=6)
    # One collection for every body: matplotlib sorts a collection's faces by depth, but whole collections
    # only as a block, so a body drawn as its own collection can be painted over one in front of it.
    # Rasterized: in a PDF page the triangles become one image, not tens of thousands of vector paths.
    ax.add_collection3d(Poly3DCollection(np.concatenate(triangles), facecolors=np.concatenate(faces), edgecolors="none", linewidths=0, rasterized=True))
    ax.set_xlim(lo[0], lo[0] + span)
    ax.set_ylim(lo[1], lo[1] + span)
    ax.set_zlim(lo[2], lo[2] + span)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=elev, azim=azim)


def _shaded(meshes: dict, target: Path) -> None:
    plt = _plt()
    bounds = _bounds(meshes)
    views = [("iso", 28, -58), ("front (looking +Y)", 0, -90), ("right (looking -X)", 0, 0), ("top (looking -Z)", 90, -90)]
    fig = plt.figure(figsize=(12, 9), dpi=110)
    for index, (title, elev, azim) in enumerate(views, 1):
        ax = fig.add_subplot(2, 2, index, projection="3d")
        _draw_shaded(ax, meshes, elev, azim, bounds)
        if index > 1:
            # Axis views are orthographic, so lengths on screen compare; the depth axis has no ticks.
            ax.set_proj_type("ortho")
            hidden = {2: ax.yaxis, 3: ax.xaxis, 4: ax.zaxis}[index]
            hidden.set_ticklabels([])
            hidden.label.set_visible(False)
        for axis, label in ((ax.xaxis, "x mm"), (ax.yaxis, "y mm"), (ax.zaxis, "z mm")):
            if axis.label.get_visible():
                axis.set_label_text(label)
        ax.set_title(title)
        if index == 1:
            ax.legend(loc="upper left", fontsize=8)
    with warnings_module.catch_warnings():
        warnings_module.simplefilter("ignore")
        fig.tight_layout()
    fig.savefig(target)
    plt.close(fig)


SECTION_AXES = {"x": (1, 2, [1, 0, 0]), "y": (0, 2, [0, 1, 0]), "z": (0, 1, [0, 0, 1])}
SECTION_NAMES = {"x": "side", "y": "front", "z": "plan"}


def _draw_section(ax, meshes: dict, axis: str, value: float, colours: dict | None = None, limits=None) -> list[str]:
    """One section plane through the bodies on a 2D axis; the names of the bodies it cuts."""
    np, trimesh = _lazy_imports()
    from matplotlib.patches import Polygon as Patch

    u, v, normal = SECTION_AXES[axis]
    origin = [0.0, 0.0, 0.0]
    origin["xyz".index(axis)] = value
    cut = []
    for colour_index, (name, mesh) in enumerate(meshes.items()):
        colour = (colours or {}).get(name, PALETTE[colour_index % len(PALETTE)])
        lines = trimesh.intersections.mesh_plane(mesh, plane_normal=normal, plane_origin=origin)
        if len(lines) == 0:
            continue
        cut.append(name)
        for polygon in _polygons(lines[:, :, [u, v]]):
            ax.add_patch(Patch(polygon, closed=True, facecolor=colour, alpha=0.35, edgecolor=colour, linewidth=1.2))
        for segment in lines:
            ax.plot(segment[:, u], segment[:, v], color=colour, linewidth=1.0)
        ax.plot([], [], color=colour, label=name, linewidth=4)
    ax.grid(True, linewidth=0.3)
    ax.set_xlabel(f"{'xyz'[u]} mm")
    ax.set_ylabel(f"{'xyz'[v]} mm")
    if limits is not None:
        # Fixed limits, so sheets side by side share one scale; the axes box takes the aspect instead.
        (u_lo, u_hi), (v_lo, v_hi) = limits
        ax.set_xlim(u_lo, u_hi)
        ax.set_ylim(v_lo, v_hi)
        ax.set_aspect("equal", adjustable="box")
    else:
        ax.set_aspect("equal", adjustable="datalim")
        ax.autoscale_view()
    return cut


def _sections(meshes: dict, specs: list[tuple[str, float]], target: Path) -> list[dict]:
    plt = _plt()
    columns = min(3, len(specs))
    rows = math.ceil(len(specs) / columns)
    fig, grid = plt.subplots(rows, columns, figsize=(6 * columns, 5 * rows), dpi=110, squeeze=False)
    summary = []
    for index, (axis, value) in enumerate(specs):
        ax = grid[index // columns][index % columns]
        cut = _draw_section(ax, meshes, axis, value)
        ax.set_title(f"{SECTION_NAMES[axis]} section at {axis} = {value:g} mm" + ("" if cut else " (cuts nothing)"))
        if cut:
            ax.legend(fontsize=8, loc="best")
        summary.append({"plane": f"{axis}={value:g}", "bodies_cut": cut})
    for index in range(len(specs), rows * columns):
        grid[index // columns][index % columns].axis("off")
    with warnings_module.catch_warnings():
        warnings_module.simplefilter("ignore")
        fig.tight_layout()
    fig.savefig(target)
    plt.close(fig)
    return summary


def _polygons(segments):
    """Closed outlines from 2D segments, for filling; an outline that does not close is drawn as lines only."""
    try:
        from shapely.geometry import MultiLineString
        from shapely.ops import polygonize, unary_union
    except ImportError:
        return []
    merged = unary_union(MultiLineString([[tuple(p) for p in s] for s in segments.round(4)]))
    return [list(p.exterior.coords) for p in polygonize(merged) if p.area > 1e-6]


def _parse_sections(text: str | None, meshes: dict) -> list[tuple[str, float]]:
    np, _ = _lazy_imports()
    if not text:
        lo = np.min([m.bounds[0] for m in meshes.values()], axis=0)
        hi = np.max([m.bounds[1] for m in meshes.values()], axis=0)
        mid = (lo + hi) / 2
        return [("z", _r(mid[2], 2)), ("y", _r(mid[1], 2)), ("x", _r(mid[0], 2))]
    specs = []
    for item in text.split(","):
        match = re.fullmatch(r"\s*([xyz])\s*=\s*(-?\d+(?:\.\d+)?)\s*", item)
        if not match:
            raise Unusable(f"--sections {item!r}: write axis=value, like z=5,y=0,x=12.5.")
        specs.append((match.group(1), float(match.group(2))))
    if len(specs) > 9:
        raise Unusable("at most 9 sections per image.")
    return specs


def cmd_views(args) -> int:
    version = _version_dir(Path(args.path))
    meshes = _placed_meshes(version, args)
    folder = version / "views"
    folder.mkdir(exist_ok=True)
    suffix = "" if not args.pose else "-" + re.sub(r"[^A-Za-z0-9_-]+", "-", args.pose).strip("-") + ("" if args.at is None else f"-{args.at:g}")
    shaded = folder / f"shaded{suffix}.png"
    sections = folder / f"sections{suffix}.png"
    triangles = sum(len(m.faces) for m in meshes.values())
    if triangles > 150000:
        print(f"  note: {triangles} triangles; the shaded view is slow at this size, lower $fn for drafts.")
    _shaded(meshes, shaded)
    summary = _sections(meshes, _parse_sections(args.sections, meshes), sections)
    print(f"{_label(version)}: views written. Look at both images before judging the part:")
    print(f"  {shaded}  (iso, front, right, top)")
    print(f"  {sections}  ({', '.join(s['plane'] + (' cuts ' + '/'.join(s['bodies_cut']) if s['bodies_cut'] else ' cuts nothing') for s in summary)})")
    return 0


# ---------------------------------------------------------------- print


def _parse_bed(text: str) -> list[float]:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)", text)
    if not match:
        raise Unusable("--bed is WxDxH in mm, like 250x210x220.")
    return [float(g) for g in match.groups()]


def _overhang_regions(mesh, angle: float, bed_z: float) -> tuple[list[dict], float]:
    np, trimesh = _lazy_imports()
    normals = mesh.face_normals
    limit = -math.sin(math.radians(angle))
    on_bed = (normals[:, 2] < -0.999) & (np.abs(mesh.triangles[:, :, 2] - bed_z).max(axis=1) < 0.05)
    down = (normals[:, 2] < limit) & ~on_bed
    contact = float(mesh.area_faces[on_bed].sum())
    if not down.any():
        return [], contact
    index = np.nonzero(down)[0]
    keep = set(index.tolist())
    pairs = [p for p in mesh.face_adjacency if p[0] in keep and p[1] in keep]
    groups = trimesh.graph.connected_components(pairs, nodes=index, min_len=1)
    regions = []
    for group in groups:
        group = np.asarray(sorted(group))
        area = float(mesh.area_faces[group].sum())
        if area < 1.0:
            continue
        points = mesh.triangles[group].reshape(-1, 3)
        lo, hi = points.min(axis=0), points.max(axis=0)
        flat = bool((normals[group, 2] < -0.999).all())
        span = float(min(hi[0] - lo[0], hi[1] - lo[1]))
        kind = "overhang"
        if flat:
            kind = "bridge" if _held_both_sides(mesh, group, float(lo[2])) else "ledge"
        regions.append(
            {
                "kind": kind,
                "area_mm2": _r(area, 1),
                "z_mm": [_r(lo[2], 2), _r(hi[2], 2)],
                "where": _fmt_box(lo, hi),
                "span_mm": _r(span, 1) if flat else None,
                # Across its narrow side: the top of a small horizontal hole is a strip a few mm wide.
                "width_mm": _r(span, 1),
                # A surface's angle from vertical: 0 for a wall, 90 for a flat ceiling.
                "steepest_deg_from_vertical": _r(math.degrees(math.asin(min(1.0, float(-normals[group, 2].min())))), 1),
            }
        )
    regions.sort(key=lambda r: -r["area_mm2"])
    return regions, contact


def _narrow(region: dict, width: float) -> bool:
    """The top of a small horizontal hole or a short chamfer: a strip a few mm wide and under 1.5 mm tall prints anyway."""
    low, high = region["z_mm"]
    return region["width_mm"] <= width and high - low <= 1.5


def _held_both_sides(mesh, group, z: float, probes: int = 40) -> bool:
    """Whether a flat ceiling rests on material at both ends (a bridge) rather than one (a ledge).

    Points on the ceiling look out along eight directions in the layer just below it; a
    point is held when two opposite directions both meet material. Most points held is a bridge.
    """
    np, trimesh = _lazy_imports()
    try:
        from shapely.geometry import LineString, MultiLineString, Point
        from shapely.ops import polygonize, unary_union
    except ImportError:
        return True
    lines = trimesh.intersections.mesh_plane(mesh, plane_normal=[0, 0, 1], plane_origin=[0, 0, z - 0.3])
    if len(lines) == 0:
        return False
    below = unary_union(list(polygonize(unary_union(MultiLineString([[tuple(p) for p in seg] for seg in lines[:, :, :2].round(4)])))))
    if below.is_empty:
        return False
    centres = mesh.triangles_center[group][:, :2]
    weights = mesh.area_faces[group]
    rng = np.random.default_rng(7)
    picks = centres[rng.choice(len(centres), size=min(probes, len(centres)), replace=False, p=weights / weights.sum())]
    reach = float(np.ptp(mesh.bounds[:, :2], axis=0).max()) + 1.0
    directions = [(1, 0), (0, 1), (0.7071, 0.7071), (0.7071, -0.7071)]
    held = 0
    for x, y in picks:
        start = Point(x, y)
        if below.buffer(0.05).contains(start):
            held += 1  # material directly under this point
            continue
        for dx, dy in directions:
            ahead = LineString([(x, y), (x + dx * reach, y + dy * reach)])
            behind = LineString([(x, y), (x - dx * reach, y - dy * reach)])
            if ahead.intersects(below) and behind.intersects(below):
                held += 1
                break
    return held >= 0.8 * len(picks)


def _thin_walls(mesh, minimum: float, samples: int = 3000) -> dict:
    np, trimesh = _lazy_imports()
    points, faces = trimesh.sample.sample_surface_even(mesh, samples, seed=7)
    directions = -mesh.face_normals[faces]
    origins = points + directions * 1e-3
    hits, rays, _ = mesh.ray.intersects_location(origins, directions, multiple_hits=False)
    if len(rays) == 0:
        return {"sampled": int(len(points))}
    thickness = np.linalg.norm(hits - origins[rays], axis=1)
    thin = rays[thickness < minimum]
    result = {"sampled": int(len(points)), "min_mm": _r(thickness.min(), 2), "p1_mm": _r(np.percentile(thickness, 1), 2), "below_min": int(len(thin))}
    if len(thin):
        where = points[thin]
        result["thin_where"] = _fmt_box(where.min(axis=0), where.max(axis=0))
    return result


def _slice(version: Path, files: list[Path], bed: list[float]) -> dict:
    exe = shutil.which("prusa-slicer") or shutil.which("PrusaSlicer")
    if not exe:
        return {"skipped": "no slicer here (prusa-slicer is in the CAD sandbox image)"}
    gcode = version / "print.gcode"
    w, d, _ = bed
    command = [
        exe, "--export-gcode", "--output", str(gcode), "--bed-shape", f"0x0,{w:g}x0,{w:g}x{d:g},0x{d:g}",
        "--layer-height", "0.2", "--fill-density", "15%", "--perimeters", "2", "--filament-density", str(PLA_DENSITY_G_CM3),
        "--filament-diameter", "1.75", "--nozzle-diameter", "0.4",
        # One plate: without --merge the slicer slices each file on its own and the last one overwrites the G-code.
        "--merge", *[str(f) for f in files],
    ]  # fmt: skip
    try:
        run = subprocess.run(command, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"error": "the slicer took longer than 600 s"}
    if run.returncode != 0 or not gcode.is_file():
        tail = (run.stderr or run.stdout).strip().splitlines()[-3:]
        return {"error": " / ".join(tail) or f"slicer exited {run.returncode}"}
    found = {}
    # The slicer's own warnings ("Low bed adhesion / rest.stl, strut.stl") are everything but progress lines.
    notes = [line.strip() for line in (run.stdout + run.stderr).splitlines() if line.strip() and "=>" not in line and not line.startswith("Slicing result") and not SLICER_LOG.match(line.strip())]
    if notes:
        found["warnings"] = [" ".join(notes)[:400]]
    with gcode.open(errors="replace") as handle:
        for line in handle:
            for key, label in (("filament used [g]", "filament_g"), ("filament used [mm]", "filament_mm"), ("estimated printing time (normal mode)", "time")):
                if line.startswith(f"; {key} ="):
                    found[label] = line.split("=", 1)[1].strip()
    found["settings"] = "0.4 mm nozzle, 0.2 mm layers, 2 perimeters, 15% infill, PLA, no supports"
    found["gcode"] = gcode.name
    return found


def cmd_print(args) -> int:
    np, trimesh = _lazy_imports()
    version = _version_dir(Path(args.path))
    if (version / "print" / "report.json").is_file():
        version = version / "print"
    elif version.name != "print":
        print(f"  note: {version.name} has no print layout, so the bodies are checked where they sit in the assembly. Render with --print-layout to check them laid out for the bed.")
    label = _label(version)
    report = _load_report(version)
    meshes = _load_meshes(version)
    bed = _parse_bed(args.bed)
    lo = np.min([m.bounds[0] for m in meshes.values()], axis=0)
    hi = np.max([m.bounds[1] for m in meshes.values()], axis=0)
    bed_z = float(lo[2])
    problems, bodies = [], {}
    for name, mesh in meshes.items():
        own_lo, own_hi = mesh.bounds
        regions, contact = _overhang_regions(mesh, args.overhang, float(own_lo[2]))
        info = {"contact_mm2": _r(contact, 1), "regions": regions[:8], "walls": _thin_walls(mesh, args.min_wall) if mesh.is_volume else {"skipped": "not a closed solid"}}
        if abs(own_lo[2] - bed_z) > 0.05:
            problems.append(f"{name} starts at z={own_lo[2]:.2f}, above the bed (z={bed_z:.2f}): it would print in mid-air")
        if contact < 1.0:
            problems.append(f"{name} has no flat face on the bed")
        for region in regions:
            if region["kind"] == "bridge" and region["span_mm"] is not None and region["span_mm"] > args.max_bridge:
                problems.append(f"{name}: bridge spans {region['span_mm']} mm (> {args.max_bridge}) at {region['where']}")
            elif region["kind"] == "ledge" and region["area_mm2"] > args.max_overhang_area:
                problems.append(f"{name}: {region['area_mm2']} mm2 flat ledge held on one side only at {region['where']}: needs support, or a 45 deg chamfer under it")
            elif region["kind"] == "overhang" and region["area_mm2"] > args.max_overhang_area and not _narrow(region, args.narrow):
                problems.append(f"{name}: {region['area_mm2']} mm2 overhang steeper than {args.overhang} deg at {region['where']}")
        walls = info["walls"]
        if walls.get("below_min"):
            problems.append(f"{name}: {walls['below_min']} of {walls['sampled']} samples thinner than {args.min_wall} mm at {walls.get('thin_where')}")
        bodies[name] = info
    size = hi - lo
    if any(size[i] > bed[i] for i in range(3)):
        problems.append(f"layout is {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm, the bed {args.bed} mm")
    solids = {n: m for n, m in meshes.items() if m.is_volume}
    gaps = []
    if len(solids) > 1:
        clashes, gaps = _overlaps(solids, None, [], 0.01, args.min_gap)
        problems += [f"{c['pair'][0]} / {c['pair'][1]} overlap on the bed ({c['overlap_mm3']} mm3): they would print fused" for c in clashes]
        problems += [f"{g['pair'][0]} / {g['pair'][1]} only {g['min_gap_mm']} mm apart (< {args.min_gap}): may fuse" for g in gaps if g["tight"]]
    sliced = _slice(version, [version / report["bodies"][n]["file"] for n in meshes], bed) if args.slice else {"skipped": "run with --slice"}
    # A slicer warning (low bed adhesion, "consider enabling supports") is a print problem like ours.
    problems += [f"slicer says: {warning}" for warning in sliced.get("warnings", [])]
    out = {"version": label, "bed_mm": bed, "overhang_deg": args.overhang, "min_wall_mm": args.min_wall, "layout_mm": [_r(v, 2) for v in size], "bodies": bodies, "gaps": gaps, "slicer": sliced, "problems": problems}
    _write_json(version / "print.json", out)

    print(f"{label}: print layout {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm on a {args.bed} mm bed")
    for name, info in bodies.items():
        regions = info["regions"]
        worst = f", largest {regions[0]['kind']} {regions[0]['area_mm2']} mm2 at z {regions[0]['z_mm'][0]}..{regions[0]['z_mm'][1]}" if regions else ""
        walls = info["walls"]
        wall = f", thinnest wall {walls['min_mm']} mm" if "min_mm" in walls else ""
        print(f"  {name}: bed contact {info['contact_mm2']} mm2, {len(regions)} down-facing regions{worst}{wall}")
    if "error" in sliced:
        print(f"  slicer: ERROR {sliced['error']}")
    elif "skipped" in sliced:
        print(f"  slicer: {sliced['skipped']}")
    else:
        print(f"  slicer: {sliced.get('filament_g', '?')} g, {sliced.get('time', '?')} ({sliced['settings']})")
    for problem in problems:
        print(f"  PROBLEM {problem}")
    print("  PASS: prints without supports on this layout" if not problems else f"  FAIL: {len(problems)} problems")
    return 1 if problems or "error" in sliced else 0


# ---------------------------------------------------------------- STEP


def _step(mesh, target: Path) -> None:
    try:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
        from OCP.StlAPI import StlAPI_Reader
        from OCP.TopAbs import TopAbs_SHELL
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS, TopoDS_Shape
    except ImportError as exc:
        raise Unusable(OCP_MISSING) from exc
    scratch = target.with_suffix(".tmp.stl")
    mesh.export(scratch)
    shape = TopoDS_Shape()
    StlAPI_Reader().Read(shape, str(scratch))
    scratch.unlink()
    sewing = BRepBuilderAPI_Sewing(1e-4)
    sewing.Add(shape)
    sewing.Perform()
    sewn = sewing.SewedShape()
    solid_maker = BRepBuilderAPI_MakeSolid()
    explorer = TopExp_Explorer(sewn, TopAbs_SHELL)
    shells = 0
    while explorer.More():
        solid_maker.Add(TopoDS.Shell_s(explorer.Current()))
        shells += 1
        explorer.Next()
    result = solid_maker.Solid() if shells else sewn
    writer = STEPControl_Writer()
    with _quiet_stdout():
        writer.Transfer(result, STEPControl_AsIs)
        status = writer.Write(str(target))
    if status != IFSelect_RetDone:
        raise Unusable(f"the STEP writer failed for {target.name}")


def _read_step(path: Path):
    """The shape a STEP file holds, or None when it does not read as one."""
    try:
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_Reader
    except ImportError as exc:
        raise Unusable(OCP_MISSING) from exc
    reader = STEPControl_Reader()
    with _quiet_stdout():
        status = reader.ReadFile(str(path))
        if status == IFSelect_RetDone:
            reader.TransferRoots()
    if status != IFSelect_RetDone:
        return None
    shape = reader.OneShape()
    return None if shape.IsNull() else shape


def _step_facts(shape) -> dict:
    """Solids, open shells, volume and the tight bounding box of a B-rep shape."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRep import BRep_Tool
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    def each(kind):
        explorer = TopExp_Explorer(shape, kind)
        while explorer.More():
            yield explorer.Current()
            explorer.Next()

    shells = list(each(TopAbs_SHELL))
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    facts = {
        "solids": sum(1 for _ in each(TopAbs_SOLID)),
        "shells": len(shells),
        # A shell is closed when every edge joins two of its faces.
        "open_shells": sum(1 for shell in shells if not BRep_Tool.IsClosed_s(shell)),
        "volume_mm3": float(props.Mass()),
    }
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    if not box.IsVoid():
        x0, y0, z0, x1, y1, z1 = box.Get()
        facts["min_mm"], facts["max_mm"] = [_r(v, 4) for v in (x0, y0, z0)], [_r(v, 4) for v in (x1, y1, z1)]
    return facts


def _tessellate(shape):
    """A B-rep shape as one triangle mesh, faces joined along their shared edges."""
    np, trimesh = _lazy_imports()
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    BRepMesh_IncrementalMesh(shape, STEP_DEFLECTION_MM, False, STEP_ANGLE_RAD, True)
    vertices, faces = [], []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is not None:
            transform = location.Transformation()
            offset = len(vertices) - 1  # OCP counts nodes from 1
            vertices += [triangulation.Node(i).Transformed(transform).Coord() for i in range(1, triangulation.NbNodes() + 1)]
            flip = face.Orientation() == TopAbs_REVERSED
            for i in range(1, triangulation.NbTriangles() + 1):
                a, b, c = triangulation.Triangle(i).Get()
                faces.append((offset + a, offset + c, offset + b) if flip else (offset + a, offset + b, offset + c))
        explorer.Next()
    if not faces:
        return trimesh.Trimesh()
    mesh = trimesh.Trimesh(vertices=np.asarray(vertices, dtype=float), faces=np.asarray(faces, dtype=np.int64), process=False)
    # Neighbouring faces repeat the nodes of their shared edge; joining them closes the surface.
    mesh.merge_vertices(digits_vertex=6)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    return mesh


# ---------------------------------------------------------------- export


def _off_pct(value: float, expected: float) -> float:
    return abs(value - expected) / abs(expected) * 100 if expected else (0.0 if value == expected else math.inf)


def _verify_step(path: Path, mesh) -> dict:
    """Re-import a body's STEP: one solid, closed shells, and the volume and box of the mesh it came from."""
    entry = {"file": path.name, "kind": "STEP", "ok": False, "problems": []}
    problems = entry["problems"]
    shape = _read_step(path)
    if shape is None:
        problems.append("does not read back as STEP")
        return entry
    facts = _step_facts(shape)
    entry.update({**facts, "volume_mm3": _r(facts["volume_mm3"], 3)})
    if facts["solids"] != 1:
        problems.append(f"{facts['solids']} solids where cadkit writes one")
    if facts["open_shells"]:
        problems.append(f"{facts['open_shells']} of {facts['shells']} shells are open")
    if not mesh.is_volume:
        problems.append("its mesh is not a closed solid, so the STEP is not one either")
    else:
        expected = float(mesh.volume)
        off = _off_pct(facts["volume_mm3"], expected)
        entry.update(mesh_volume_mm3=_r(expected, 3), volume_off_pct=_r(off, 3))
        if off > VERIFY_VOLUME_PCT:
            problems.append(f"volume {facts['volume_mm3']:.1f} mm3, its mesh {expected:.1f} mm3 ({off:.2f}% > {VERIFY_VOLUME_PCT}%)")
    if "min_mm" not in facts:
        problems.append("holds no geometry")
    else:
        box_off = max(abs(a - float(b)) for a, b in zip([*facts["min_mm"], *facts["max_mm"]], [*mesh.bounds[0], *mesh.bounds[1]]))
        entry["box_off_mm"] = _r(box_off, 4)
        if box_off > VERIFY_BOX_MM:
            problems.append(f"bounding box {box_off:.3f} mm off its mesh's (> {VERIFY_BOX_MM} mm)")
    entry["ok"] = not problems
    return entry


def _verify_3mf(path: Path, meshes: dict) -> dict:
    """Re-load bodies.3mf: one object per body, each with its body's volume."""
    np, trimesh = _lazy_imports()
    entry = {"file": path.name, "kind": "3MF", "ok": False, "problems": []}
    problems = entry["problems"]
    try:
        scene = trimesh.load(path, file_type="3mf", force="scene")
    except Exception as exc:  # a damaged archive raises anything from zipfile to lxml
        problems.append(f"does not load ({type(exc).__name__}: {exc})"[:300])
        return entry
    found = {}
    for node in scene.graph.nodes_geometry:
        transform, geometry = scene.graph[node]
        placed = scene.geometry[geometry].copy()
        placed.apply_transform(transform)
        found[node] = placed
    entry["bodies"] = len(found)
    if len(found) != len(meshes):
        problems.append(f"{len(found)} bodies where the version has {len(meshes)}")
    volumes = {}
    for name, mesh in meshes.items():
        back = found.get(name)
        if back is None:
            problems.append(f"no body named {name}")
            continue
        volumes[name] = _r(back.volume, 1) if back.is_volume else None
        if not mesh.is_volume:
            continue
        if not back.is_volume:
            problems.append(f"{name} is not a closed solid in the 3MF")
        elif _off_pct(float(back.volume), float(mesh.volume)) > VERIFY_VOLUME_PCT:
            problems.append(f"{name}: volume {back.volume:.1f} mm3, its mesh {mesh.volume:.1f} mm3")
    entry["volumes_mm3"] = volumes
    entry["ok"] = not problems
    return entry


def _verify_stl(path: Path, info: dict, label: str) -> dict:
    """Re-read an STL: the triangles and volume its report.json recorded."""
    np, trimesh = _lazy_imports()
    entry = {"file": label, "kind": "STL", "ok": False, "problems": []}
    problems = entry["problems"]
    try:
        mesh = trimesh.load(path, force="mesh", process=True)
    except Exception as exc:  # a missing or truncated file
        problems.append(f"does not load ({type(exc).__name__}: {exc})"[:300])
        return entry
    entry["triangles"] = int(len(mesh.faces))
    if entry["triangles"] != info.get("triangles"):
        problems.append(f"{entry['triangles']} triangles where report.json has {info.get('triangles')}")
    expected = info.get("volume_mm3")
    if isinstance(expected, (int, float)):
        if not mesh.is_volume:
            problems.append("no longer a closed solid")
        else:
            entry["volume_mm3"] = _r(mesh.volume, 1)
            # report.json rounds to 0.1 mm3, so a tiny body is allowed that much.
            if abs(mesh.volume - expected) > max(abs(expected) * VERIFY_VOLUME_PCT / 100, 0.1):
                problems.append(f"volume {mesh.volume:.1f} mm3 where report.json has {expected}")
    entry["ok"] = not problems
    return entry


def _proven(version: Path, body: str) -> dict | None:
    """The passing compare of an editable <body>-cq.step against <body>.stl, made on the file as it is now."""
    result = _read_json(version / f"{body}-cq.compare.json")
    step = version / f"{body}-cq.step"
    if not result or result.get("passed") is not True or not step.is_file():
        return None
    if Path(str(result.get("a", ""))).name != f"{body}.stl" or Path(str(result.get("b", ""))).name != step.name:
        return None
    # A STEP edited after its compare is not the one that passed.
    return result if result.get("b_sha256") == _sha256(step) else None


def _zip_candidates(version: Path) -> list[str]:
    """Names, relative to the version folder, of what a delivery holds, in order."""
    report = _load_report(version)
    rendered = {n: i for n, i in report.get("bodies", {}).items() if isinstance(i, dict) and "error" not in i and isinstance(i.get("file"), str)}
    layout = _read_json(version / "print" / "report.json")
    if layout and isinstance(layout.get("bodies"), dict):
        meshes = [f"print/{i['file']}" for i in layout["bodies"].values() if isinstance(i, dict) and "error" not in i and isinstance(i.get("file"), str)]
    else:
        meshes = [i["file"] for i in rendered.values()]
    steps = [f"{n}.step" for n in rendered] + [f"{n}-cq.step" for n in rendered if _proven(version, n)]

    def listing(folder: str, pattern: str) -> list[str]:
        path = version / folder
        return sorted(f"{folder}/{p.name}" for p in path.glob(pattern)) if path.is_dir() and not path.is_symlink() else []

    return [
        *meshes, "bodies.3mf", *steps, "model.scad", "guide.pdf", *listing("views", "*.png"),
        "report.json", "check.json", "print/report.json", "print/print.json", "print.json",
        *listing("test", "*.stl"), "test/test.json",
    ]  # fmt: skip


def _zip_members(version: Path) -> list[tuple[Path, str]]:
    """(file, name in the zip) for each deliverable: only regular files inside the version folder, no links."""
    root = version.resolve()
    members, seen = [], set()
    for arcname in _zip_candidates(root):
        if arcname in seen or not ARCNAME.fullmatch(arcname):
            continue
        path = root / arcname
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            continue
        seen.add(arcname)
        members.append((path, arcname))
    return members


def _manifest(version: Path, members: list[tuple[Path, str]], verified: list[dict]) -> dict:
    report = _load_report(version)
    bodies = {n: {k: i.get(k) for k in ("size_mm", "volume_mm3", "solid_mass_g_pla")} for n, i in report.get("bodies", {}).items() if isinstance(i, dict) and "error" not in i}
    printed = _read_json(version / "print" / "print.json") or _read_json(version / "print.json")
    check = _read_json(version / "check.json")
    problems = [p for p in (printed or {}).get("problems", []) if isinstance(p, str)]
    slicer = (printed or {}).get("slicer") if isinstance((printed or {}).get("slicer"), dict) else {}
    editable = {n: {"file": f"{n}-cq.step", "symmetric_difference_pct": r.get("symmetric_difference_pct")} for n in bodies if (r := _proven(version, n))}
    return {
        "design": version.parent.name,
        "version": version.name,
        "date_utc": _utc_now(),
        "made_by": "cadkit.py export --zip",
        "bodies": bodies,
        "editable_step": editable,
        "print": None if printed is None else {"checked": printed.get("version"), "bed_mm": printed.get("bed_mm"), "settings": slicer.get("settings"), "filament_g": slicer.get("filament_g"), "time": slicer.get("time")},
        "checks": {
            "poses": {"states": check.get("states"), "clashes": check.get("clashes")} if check else "not run",
            "print": "not run" if printed is None else {"problems": len(problems)},
            "export": {"files_read_back": len(verified), "mismatches": sum(1 for v in verified if not v["ok"])},
        },
        "files": [{"path": arcname, "bytes": path.stat().st_size, "sha256": _sha256(path)} for path, arcname in members],
        "limit": LIMIT,
    }


def _write_zip(version: Path, verified: list[dict]) -> dict:
    """<design>-v<N>.zip with the deliverables and manifest.json, read back member by member."""
    members = _zip_members(version)
    manifest = _manifest(version, members, verified)
    target = version / f"{version.parent.name}-{version.name}.zip"
    partial = version / f".{target.name}.partial"
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, arcname in members:
            archive.write(path, arcname)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
    os.replace(partial, target)
    entry = {"file": target.name, "kind": "zip", "files": len(members) + 1, "bytes": target.stat().st_size, "sha256": _sha256(target), "problems": []}
    expected = {item["path"]: item["sha256"] for item in manifest["files"]}
    with zipfile.ZipFile(target) as archive:
        broken = archive.testzip()
        if broken:
            entry["problems"].append(f"{broken} is damaged in the zip")
        names = archive.namelist()
        if sorted(names) != sorted([*expected, "manifest.json"]):
            entry["problems"].append("the zip's file list differs from its manifest")
        for name, digest in expected.items():
            if name in names and hashlib.sha256(archive.read(name)).hexdigest() != digest:
                entry["problems"].append(f"{name} differs from its manifest entry")
    entry["ok"] = not entry["problems"]
    return entry


def cmd_export(args) -> int:
    np, trimesh = _lazy_imports()
    version = _version_root(Path(args.path))
    if not (args.step or args.threemf or args.zip):
        raise Unusable("choose --step, --3mf, --zip or several.")
    meshes = _load_meshes(version)
    written = []
    if args.step:
        for name, mesh in meshes.items():
            if len(mesh.faces) > MAX_STEP_TRIANGLES:
                raise Unusable(f"{name} has {len(mesh.faces)} triangles (> {MAX_STEP_TRIANGLES}); render the export with a lower $fn, e.g. -D '$fn=64'.")
        for name, mesh in meshes.items():
            target = version / f"{name}.step"
            _step(mesh, target)
            written.append(target.name)
    if args.threemf:
        scene = trimesh.Scene()
        for name, mesh in meshes.items():
            scene.add_geometry(mesh, node_name=name, geom_name=name)
        target = version / "bodies.3mf"
        target.write_bytes(scene.export(file_type="3mf"))
        written.append(target.name)

    # Read back what goes out: every STL the version holds, and each STEP and 3MF written now or zipped.
    verified = []
    for sub in ("", "print", "test"):
        layout = _read_json(version / sub / "report.json")
        for info in (layout or {}).get("bodies", {}).values():
            if isinstance(info, dict) and "error" not in info and isinstance(info.get("file"), str) and ARCNAME.fullmatch(f"{sub}/{info['file']}".lstrip("/")):
                verified.append(_verify_stl(version / sub / info["file"], info, f"{sub}/{info['file']}".lstrip("/")))
    for name, mesh in meshes.items():
        path = version / f"{name}.step"
        if path.name in written or (args.zip and path.is_file()):
            verified.append(_verify_step(path, mesh))
    if "bodies.3mf" in written or (args.zip and (version / "bodies.3mf").is_file()):
        verified.append(_verify_3mf(version / "bodies.3mf", meshes))
    failed = [v for v in verified if not v["ok"]]
    zipped, stale, removed = None, version / f"{version.parent.name}-{version.name}.zip", False
    if args.zip and failed and stale.is_file():
        stale.unlink()  # an earlier zip no longer matches the folder; delivering it would hide the mismatch
        removed = True
    if args.zip and not failed:
        zipped = _write_zip(version, verified)
        written.append(zipped["file"])
        if not zipped["ok"]:
            failed.append(zipped)
    unproven = [f"{n}-cq.step" for n in meshes if (version / f"{n}-cq.step").is_file() and not _proven(version, n)]
    _write_json(version / "export.json", {"version": version.name, "written": written, "verified": verified, "zip": zipped, "mismatches": len(failed)})

    print(f"{version.name}: wrote {', '.join(written) or 'nothing'} in {version}")
    good = [v["file"] for v in verified if v["ok"]] + ([zipped["file"]] if zipped and zipped["ok"] else [])
    if good:
        print(f"  read back as written: {', '.join(good[:12])}" + (f" and {len(good) - 12} more" if len(good) > 12 else ""))
    for entry in failed:
        print(f"  FAIL {entry['file']}: {'; '.join(entry['problems'])}")
    if zipped:
        print(f"  {zipped['file']}: {zipped['files']} files with manifest.json (sizes and sha256 of each), {zipped['bytes']} bytes")
    elif args.zip:
        print(f"  zip not written{f', and the earlier {stale.name} removed' if removed else ''}: a file above does not match its body. Fix the cause and export again.")
    for name in unproven:
        print(f"  {name} left out of the zip: no passing compare. Run cadkit.py compare {name.removesuffix('-cq.step')}.stl {name} in this folder.")
    if args.step:
        print("  STEP files are faceted: each triangle of the mesh is a face. Good for fit-checking in a CAD program, not for editing features.")
    print("  PASS: every file reads back as the body it came from" if not failed else f"  FAIL: {len(failed)} {'file does' if len(failed) == 1 else 'files do'} not read back as written")
    return 1 if failed else 0


# ---------------------------------------------------------------- guide

A4 = (8.27, 11.69)
# "1. ", "2) ", "Step 3: ", "- ": the marker needs a space after it, so "2.5 mm spacer" keeps its number.
STEP_MARK = re.compile(r"^(?:step\s*)?\d{1,3}\s*[.):]\s+|^[-*]\s+", re.IGNORECASE)


def _read_steps(path: Path) -> tuple[list[str], bool]:
    """Assembly steps from model-written plain text, one per paragraph, its own numbering dropped; and whether any was cut."""
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_STEPS_BYTES + 1)
    except OSError as exc:
        raise Unusable(f"--steps {path}: {exc.strerror or exc}.") from exc
    cut = len(data) > MAX_STEPS_BYTES
    text = data[:MAX_STEPS_BYTES].decode("utf-8", errors="replace").replace("\r\n", "\n")
    steps = []
    for paragraph in re.split(r"\n[ \t]*\n", text):
        # A heading is a title, not a step; a list written without blank lines is still one step per item.
        lines = [line for line in paragraph.split("\n") if not line.lstrip().startswith("#")]
        for item in re.split(r"\n(?=[ \t]*(?:(?:step\s*)?\d{1,3}\s*[.):]|[-*])\s)", "\n".join(lines), flags=re.IGNORECASE):
            flat = STEP_MARK.sub("", " ".join(item.split()))
            if len(flat) > MAX_STEP_CHARS:
                flat, cut = flat[: MAX_STEP_CHARS - 1].rstrip() + "…", True
            if flat:
                steps.append(flat)
    if len(steps) > MAX_STEPS:
        steps, cut = steps[:MAX_STEPS], True
    return steps, cut


def _problems_of(name: str, problems) -> list[str]:
    """The print problems that concern one body: its own, a pair it is in, a slicer warning naming its file."""
    mine = []
    for problem in problems if isinstance(problems, list) else []:
        if not isinstance(problem, str):
            continue
        own = problem.startswith((f"{name} ", f"{name}:")) or re.match(rf"^\S+ / {re.escape(name)} ", problem)
        if own or re.search(rf"(?<![A-Za-z0-9_-]){re.escape(name)}\.stl\b", problem):
            mine.append(problem)
    return mine


def _bed_note(name: str, layout: dict | None, printed: dict | None) -> str:
    """How a body lies on the bed, from the print layout's report and print.json."""
    if not layout:
        return "as modelled (no print layout)"
    info = layout.get("bodies", {}).get(name)
    if not isinstance(info, dict) or "error" in info or not isinstance(info.get("size_mm"), list):
        return "not in the print layout"
    x, y, z = info["size_mm"]
    note = f"{x:g} x {y:g} mm footprint, {z:g} mm tall"
    body = ((printed or {}).get("bodies") or {}).get(name)
    if isinstance(body, dict) and isinstance(body.get("contact_mm2"), (int, float)):
        note += f", {body['contact_mm2']:g} mm2 flat on the bed"
    return note


def _slicer_line(printed: dict | None) -> str:
    if printed is None:
        return "Slicer: not run; this version has no print.json (cadkit.py print --slice)."
    slicer = printed.get("slicer") if isinstance(printed.get("slicer"), dict) else {}
    if slicer.get("filament_g"):
        return f"Slicer, the whole plate in one print: {slicer['filament_g']} g, {slicer.get('time', '?')} ({slicer.get('settings', 'settings not recorded')})."
    if slicer.get("error"):
        return f"Slicer: failed ({slicer['error']})."
    return f"Slicer: not run ({slicer.get('skipped', 'cadkit.py print --slice')})."


def _check_lines(check: dict | None, printed: dict | None, exported: dict | None) -> list[str]:
    """The checks page as lines; a check that did not run is a line saying so."""
    lines = []
    if not check:
        lines.append("Poses and sweeps: not checked; this version has no check.json (cadkit.py check).")
    else:
        results = [r for r in check.get("results", []) if isinstance(r, dict)]
        states: dict = {}
        for result in results:
            states[result.get("pose")] = states.get(result.get("pose"), 0) + 1
        sweeps = sum(1 for count in states.values() if count > 1)
        lines.append(f"Poses and sweeps: {len(results)} states across {len(states)} poses ({sweeps} sweeps), clearance {check.get('clearance_mm')} mm.")
        worst: dict = {}
        for result in results:
            for clash in result.get("clashes", []):
                key = (tuple(clash.get("pair", [])), result.get("pose"))
                if key not in worst or clash.get("overlap_mm3", 0) > worst[key][0].get("overlap_mm3", 0):
                    worst[key] = (clash, result.get("state"))
        for (pair, pose), (clash, state) in list(worst.items())[:10]:
            lines.append(f"Clash: {' / '.join(map(str, pair))} in pose {pose}, worst {clash.get('overlap_mm3')} mm3 at [{state}], {clash.get('where')}.")
        if not worst:
            lines.append("Clashes: none in any state.")
        gaps = [(g["min_gap_mm"], g.get("pair", []), r.get("state")) for r in results for g in r.get("gaps", []) if isinstance(g, dict) and isinstance(g.get("min_gap_mm"), (int, float))]
        if gaps:
            gap, pair, state = min(gaps, key=lambda item: item[0])
            lines.append(f"Smallest gap: {gap} mm, {' / '.join(map(str, pair))} at [{state}].")
        else:
            lines.append("Smallest gap: no pair of bodies within the search distance.")
    if not printed:
        lines.append("Print: not checked; this version has no print.json (cadkit.py print --slice).")
    else:
        problems = [p for p in printed.get("problems", []) if isinstance(p, str)]
        lines.append(f"Print check of {printed.get('version')} on a {' x '.join(f'{v:g}' for v in printed.get('bed_mm') or [])} mm bed: " + (f"{len(problems)} problems." if problems else "no problem found."))
        lines += [f"Problem: {problem}" for problem in problems[:15]]
        if len(problems) > 15:
            lines.append(f"... {len(problems) - 15} more in print.json.")
        lines.append(_slicer_line(printed))
    if exported:
        verified = [v for v in exported.get("verified", []) if isinstance(v, dict)]
        bad = [v for v in verified if not v.get("ok")]
        lines.append(f"Export: {len(verified) - len(bad)} of {len(verified)} files read back as the bodies they came from.")
        lines += [f"Mismatch: {v.get('file')}: {'; '.join(map(str, v.get('problems', [])))}" for v in bad[:10]]
    return lines


def _wrap(lines: list[str], width: int) -> list[str]:
    wrapped = []
    for line in lines:
        wrapped += textwrap.wrap(line, width=width, subsequent_indent="    ") or [""]
    return wrapped


class _Guide:
    """The pages of guide.pdf: A4, text in points, renders rasterized."""

    def __init__(self, pdf, plt, footer: str):
        self.pdf, self.plt, self.footer, self.pages = pdf, plt, footer, 0

    def page(self, heading: str | None = None):
        fig = self.plt.figure(figsize=A4, dpi=150)
        if heading:
            fig.text(0.07, 0.95, heading, fontsize=17, weight="bold", va="top", parse_math=False)
        return fig

    def text(self, fig, lines: list[str], x: float = 0.07, top: float = 0.9, bottom: float = 0.07, size: float = 9.5, width: int = 100) -> list[str]:
        """Write wrapped lines down the page; the lines that did not fit."""
        step = size * 1.45 / 72 / A4[1]
        wrapped = _wrap(lines, width)
        y = top
        for index, line in enumerate(wrapped):
            if y < bottom:
                return wrapped[index:]
            fig.text(x, y, line, fontsize=size, va="top", parse_math=False)
            y -= step
        return []

    def flow(self, heading: str, lines: list[str], **kwargs) -> None:
        """As many pages as the lines need, the heading repeated."""
        rest = _wrap(lines, kwargs.pop("width", 100))
        first = True
        while first or rest:
            fig = self.page(heading if first else f"{heading} (continued)")
            rest = self.text(fig, rest, width=10_000, **kwargs)
            self.finish(fig)
            first = False

    def finish(self, fig) -> None:
        self.pages += 1
        fig.text(0.5, 0.025, f"{self.footer} · page {self.pages}", ha="center", fontsize=7, color="#666666", parse_math=False)
        self.pdf.savefig(fig)
        self.plt.close(fig)


def cmd_guide(args) -> int:
    np, trimesh = _lazy_imports()
    plt = _plt()
    from matplotlib.backends.backend_pdf import PdfPages

    version = _version_root(Path(args.path))
    steps, steps_cut = _read_steps(Path(args.steps).resolve()) if args.steps else (None, False)
    report = _load_report(version)
    meshes = _load_meshes(version)
    colours = _colours(report)
    layout_report = _read_json(version / "print" / "report.json")
    try:
        layout = _load_meshes(version / "print") if layout_report else {}
    except Unusable:
        layout = {}
    printed = _read_json(version / "print" / "print.json") or _read_json(version / "print.json")
    check = _read_json(version / "check.json")
    exported = _read_json(version / "export.json")
    design = version.parent.name
    title = " ".join((args.title or design).split())[:80] or design
    date = _utc_now()[:10]
    notes = []
    if check is None:
        notes.append("no check.json: the checks page says the poses were not checked")
    if printed is None:
        notes.append("no print.json: the parts and checks pages say printing was not checked")
    if steps is None:
        notes.append("no --steps: the assembly page says no steps were given")
    elif steps_cut:
        notes.append(f"steps.md was cut to {MAX_STEPS} steps of at most {MAX_STEP_CHARS} characters")
    if not layout:
        notes.append("no print layout: each body page shows the body as assembled")

    target = version / "guide.pdf"
    partial = version / ".guide.pdf.partial"
    metadata = {"Title": f"{title} ({version.name})", "Subject": "Print and assembly guide", "Creator": "cadkit.py guide"}
    with warnings_module.catch_warnings():
        warnings_module.simplefilter("ignore")
        with PdfPages(partial, metadata=metadata) as pdf:
            guide = _Guide(pdf, plt, f"{design} {version.name} · {date}")
            # Cover: the title, the version and the shaded assembly.
            fig = guide.page()
            fig.text(0.07, 0.93, title, fontsize=24, weight="bold", va="top", parse_math=False)
            guide.text(fig, [f"Print and assembly guide · design {design}, version {version.name} · {date} (UTC)", f"{len(meshes)} bodies: {', '.join(meshes)}"], top=0.88, size=11, width=85)
            ax = fig.add_axes([0.03, 0.1, 0.94, 0.7], projection="3d")
            _draw_shaded(ax, meshes, 28, -58, colours=colours)
            ax.legend(loc="upper left", fontsize=8)
            ax.set_title("assembled", fontsize=10)
            guide.finish(fig)

            # Parts: one row per body; the slicer's grams are for the whole plate.
            rows = []
            for name, info in report.get("bodies", {}).items():
                if not isinstance(info, dict) or "error" in info:
                    rows.append([name, "render error", "", ""])
                    continue
                mass = f"~{info['solid_mass_g_pla']:g} g" if isinstance(info.get("solid_mass_g_pla"), (int, float)) else "not a closed solid"
                rows.append([name, " x ".join(f"{v:g}" for v in info.get("size_mm", [])), mass, _bed_note(name, layout_report, printed)])
            for start in range(0, max(len(rows), 1), 16):
                fig = guide.page("Parts" if start == 0 else "Parts (continued)")
                lines = [_slicer_line(printed), f"Solid mass is the volume in PLA ({PLA_DENSITY_G_CM3} g/cm3) as if printed solid; the slicer's grams are what the print uses."]
                guide.text(fig, lines, top=0.9, size=9.5)
                ax = fig.add_axes([0.07, 0.1, 0.86, 0.72])
                ax.axis("off")
                # A table cell does not wrap on its own: wrap each to its column and give the row the height of its tallest cell.
                chunk = [["\n".join(_wrap([cell], width)) for cell, width in zip(row, (22, 22, 16, 52))] for row in rows[start : start + 16] or [["(no body)", "", "", ""]]]
                table = ax.table(cellText=chunk, colLabels=["Body", "Size, mm", "Solid mass", "On the bed"], loc="upper left", cellLoc="left", colLoc="left", colWidths=[0.2, 0.2, 0.15, 0.45])
                table.auto_set_font_size(False)
                table.set_fontsize(8.5)
                tallest = [1] + [max(cell.count("\n") + 1 for cell in row) for row in chunk]
                for (row, _), cell in table.get_celld().items():
                    cell.get_text().set_parse_math(False)
                    cell.set_height(cell.get_height() * (0.6 + tallest[row]))
                guide.finish(fig)

            # One page per body: its numbers, its print notes and problems, the way it lies on the bed.
            for name, mesh in meshes.items():
                info = report["bodies"][name]
                fig = guide.page(f"Body: {name}")
                size = " x ".join(f"{v:g}" for v in info.get("size_mm", []))
                lines = [f"Size as assembled: {size} mm" + (f", volume {info['volume_mm3']:g} mm3, ~{info['solid_mass_g_pla']:g} g solid PLA." if "volume_mm3" in info else ", not a closed solid.")]
                lines.append(f"On the bed: {_bed_note(name, layout_report, printed)}.")
                body = ((printed or {}).get("bodies") or {}).get(name)
                if printed is None:
                    lines.append("Print: not checked; this version has no print.json (cadkit.py print).")
                elif isinstance(body, dict):
                    regions = [r for r in body.get("regions", []) if isinstance(r, dict)]
                    walls = body.get("walls") if isinstance(body.get("walls"), dict) else {}
                    note = f"Print check: {len(regions)} down-facing regions"
                    if regions:
                        note += f", the largest a {regions[0].get('kind')} of {regions[0].get('area_mm2')} mm2"
                    if "min_mm" in walls:
                        note += f"; thinnest wall {walls['min_mm']} mm"
                    lines.append(note + ".")
                    lines += [f"Problem: {p}" for p in _problems_of(name, printed.get("problems"))] or ["No print problem found for this body."]
                rest = guide.text(fig, lines, top=0.9)
                ax = fig.add_axes([0.05, 0.06, 0.9, 0.62], projection="3d")
                shown = {name: layout[name]} if name in layout else {name: mesh}
                _draw_shaded(ax, shown, 28, -58, colours=colours)
                ax.set_title("laid out for printing (the print layout)" if name in layout else "as assembled (no print layout)", fontsize=10)
                if rest:
                    fig.text(0.07, 0.69, f"... {len(rest)} more lines in print.json", fontsize=8, parse_math=False)
                guide.finish(fig)

            # Assembly: the model's steps next to the assembled render.
            if steps is None:
                lines = ["No assembly steps were given. Write them to steps.md, one step per paragraph, and run cadkit.py guide with --steps steps.md."]
            elif not steps:
                lines = ["The steps file holds no step."]
            else:
                lines = [f"{index}. {step}" for index, step in enumerate(steps, 1)]
            rest, first = _wrap(lines, 52), True
            while first or rest:
                fig = guide.page("Assembly" if first else "Assembly (continued)")
                if first:
                    ax = fig.add_axes([0.47, 0.35, 0.52, 0.55], projection="3d")
                    _draw_shaded(ax, meshes, 28, -58, colours=colours)
                    ax.legend(loc="upper left", fontsize=7)
                rest = guide.text(fig, rest, top=0.9, width=10_000, size=10)
                guide.finish(fig)
                first = False

            # Checks, and the limit of every figure in the guide.
            guide.flow("Checks", [*_check_lines(check, printed, exported), "", f"Limit: {LIMIT}"], top=0.9)
    os.replace(partial, target)

    print(f"{version.name}: guide.pdf written, {guide.pages} pages -> {target}")
    for note in notes:
        print(f"  note: {note}")
    return 0


# ---------------------------------------------------------------- study


def _parse_param(text: str, defines: list[str]) -> tuple[str, list[tuple[str, str]]]:
    """--param name=v1,v2,...: the name and (value, folder name) pairs, each value one -D would take."""
    name, equals, rest = text.partition("=")
    name = name.strip()
    if not equals or not IDENTIFIER.match(name):
        raise Unusable(f"--param {text!r}: write name=v1,v2,..., like --param r=8,10,12.")
    values = [value.strip() for value in rest.split(",")]
    if any(not value for value in values):
        raise Unusable(f"--param {text!r}: a value is empty; write name=v1,v2,..., like --param r=8,10,12.")
    if len(values) > MAX_STUDY_VALUES:
        raise Unusable(f"--param: at most {MAX_STUDY_VALUES} values in one study.")
    for define in defines:
        if define.partition("=")[0].strip() == name:
            raise Unusable(f"-D {define!r} sets {name}, which --param varies; leave it out.")
    pairs, folders = [], {}
    for value in values:
        if not DEFINE.match(f"{name}={value}") or len(value) > 40 or re.search(r"[\s/\\]", value):
            raise Unusable(f"--param value {value!r}: a number or a short OpenSCAD value without spaces or slashes, like 2.5, true or '\"M3\"'.")
        folder = re.sub(r"[^A-Za-z0-9.+-]+", "_", value).strip("_.") or "value"
        if folder in folders:
            raise Unusable(f"--param values {folders[folder]!r} and {value!r} would share the folder {folder}; give each value once.")
        folders[folder] = value
        pairs.append((value, folder))
    return name, pairs


def _study_sheet(name: str, drawn: list[tuple[str, dict]], plane: tuple[str, float] | None, colours: dict, target: Path) -> tuple[str, float]:
    """compare.png: one column per value, the shaded iso above one section plane, every column at one scale."""
    np, _ = _lazy_imports()
    plt = _plt()
    present = [meshes for _, meshes in drawn if meshes]
    lo = np.min([_bounds(m)[0] for m in present], axis=0)
    hi = np.max([_bounds(m)[1] for m in present], axis=0)
    axis, value = plane or ("z", _r((lo[2] + hi[2]) / 2, 2))
    u, v, _ = SECTION_AXES[axis]
    pad = 0.05 * max(hi[u] - lo[u], hi[v] - lo[v], 1.0)
    limits = ((lo[u] - pad, hi[u] + pad), (lo[v] - pad, hi[v] + pad))
    columns = len(drawn)
    fig = plt.figure(figsize=(3.4 * columns + 0.6, 7.4), dpi=90)
    for index, (label, meshes) in enumerate(drawn):
        top = fig.add_subplot(2, columns, index + 1, projection="3d")
        bottom = fig.add_subplot(2, columns, columns + index + 1)
        top.set_title(f"{name} = {label}", parse_math=False)
        if not meshes:
            bottom.text(0.5, 0.5, "render error", ha="center", va="center", transform=bottom.transAxes)
            continue
        _draw_shaded(top, meshes, 28, -58, (lo, hi), colours)
        if index == 0:
            top.legend(loc="upper left", fontsize=7)
        cut = _draw_section(bottom, meshes, axis, value, colours, limits)
        bottom.set_title(f"{SECTION_NAMES[axis]} section at {axis} = {value:g}" + ("" if cut else " (cuts nothing)"), fontsize=9)
    with warnings_module.catch_warnings():
        warnings_module.simplefilter("ignore")
        fig.tight_layout()
    fig.savefig(target)
    plt.close(fig)
    return axis, value


def cmd_study(args) -> int:
    np, trimesh = _lazy_imports()
    source_path = Path(args.model).resolve()
    if not source_path.is_file():
        raise Unusable(f"{source_path} does not exist.")
    source = source_path.read_text(errors="replace")
    bodies = _bodies_of(source, args.bodies)
    for define in args.define:
        if not DEFINE.match(define):
            raise Unusable(f"-D {define!r}: write name=value, like -D wall=2 or -D 'label=\"A\"'.")
    name, values = _parse_param(args.param, args.define)
    plane = None
    if args.section:
        planes = _parse_sections(args.section, {})
        if len(planes) != 1:
            raise Unusable("--section is one plane, like z=5.")
        plane = planes[0]
    poses_path = Path(args.poses).resolve() if args.poses else None
    if poses_path is not None:
        _read_poses(poses_path, bodies)  # a bad file stops the study before any render
    exe = _openscad()
    flags = _openscad_flags(exe)
    root = Path(args.design).resolve() / "studies" / name
    _clear(root)  # a study run again replaces its last run
    root.mkdir(parents=True)
    shutil.copyfile(source_path, root / "model.scad")
    started = time.monotonic()
    names = bodies or ["part"]
    colours = {body: PALETTE[index % len(PALETTE)] for index, body in enumerate(names)}
    rows, drawn = [], []
    for value, folder_name in values:
        folder = root / folder_name
        folder.mkdir()
        report = {"version": f"studies/{name}/{folder_name}", "study": {name: value}, **_render_set(exe, flags, source_path, folder, bodies, [*args.define, f"{name}={value}"], args.timeout)}
        _write_json(folder / "report.json", report)
        meshes = {n: trimesh.load(folder / i["file"], force="mesh") for n, i in report["bodies"].items() if "error" not in i}
        errors = {n: i["error"] for n, i in report["bodies"].items() if "error" in i}
        unsound = [n for n, m in meshes.items() if not m.is_volume]
        row = {"value": value, "folder": folder_name, "bodies": {n: {"size_mm": i.get("size_mm"), "volume_mm3": i.get("volume_mm3"), **({"error": i["error"]} if "error" in i else {})} for n, i in report["bodies"].items()}}
        row.update(errors=errors, not_closed=unsound, states=0, clashes=None, smallest_gap=None)
        if not errors and not unsound and len(meshes) > 1:
            poses = _read_poses(poses_path, list(meshes))
            row["clashes"] = 0
            for pose in poses["poses"]:
                for label, matrices in _pose_states(pose, list(meshes)):
                    clashes, gaps = _overlaps(meshes, matrices, poses["ignore"], float(poses["tolerance_mm3"]), args.clearance)
                    row["states"] += 1
                    row["clashes"] += len(clashes)
                    for gap in gaps:
                        if gap["min_gap_mm"] is not None and (row["smallest_gap"] is None or gap["min_gap_mm"] < row["smallest_gap"]["mm"]):
                            row["smallest_gap"] = {"mm": gap["min_gap_mm"], "pair": gap["pair"], "state": label}
        row["passes"] = bool(meshes) and not errors and not unsound and not row["clashes"]
        rows.append(row)
        drawn.append((value, meshes))
    sheet = None
    if any(meshes for _, meshes in drawn):
        sheet = root / "compare.png"
        plane = _study_sheet(name, drawn, plane, colours, sheet)
    out = {"param": name, "values": [value for value, _ in values], "defines": args.define, "poses_file": args.poses, "clearance_mm": args.clearance}
    out.update(section=f"{plane[0]}={plane[1]:g}" if plane else None, seconds=_r(time.monotonic() - started, 1), results=rows)
    _write_json(root / "study.json", out)

    print(f"study {name}: {len(values)} values rendered in {out['seconds']} s -> {root}")
    if not re.search(rf"^\s*{name}\s*=", _strip_comments(source), flags=re.MULTILINE):
        print(f"  note: {source_path.name} assigns no {name} at the top level, so every value may render the same model.")
    checked = [row["states"] for row in rows if row["states"]]
    if checked:
        print(f"  each value checked in {max(checked)} states" + (f" from {args.poses}" if args.poses else " (as modelled)") + f", clearance {args.clearance} mm")
    header = [name, "clashes", "smallest gap", *[f"{body} mm3" for body in names]]
    table = []
    for row in rows:
        clash = "render error" if row["errors"] else ("not closed" if row["not_closed"] else ("-" if row["clashes"] is None else str(row["clashes"])))
        gap = f"{row['smallest_gap']['mm']:g}" if row["smallest_gap"] else "-"
        cells = []
        for body in names:
            info = row["bodies"].get(body, {})
            cells.append("ERROR" if "error" in info else (f"{info['volume_mm3']:g}" if isinstance(info.get("volume_mm3"), (int, float)) else "open"))
        table.append([row["value"], clash, gap, *cells])
    widths = [max(len(str(line[i])) for line in [header, *table]) for i in range(len(header))]
    for line in [header, *table]:
        print("  " + "  ".join(str(cell).ljust(width) for cell, width in zip(line, widths)).rstrip())
    for row in rows:
        for body, error in row["errors"].items():
            print(f"  {name}={row['value']}: {body}: ERROR {error}")
    passing = [row["value"] for row in rows if row["passes"]]
    if sheet:
        print(f"  {sheet}  (shaded iso and the {plane[0]} = {plane[1]:g} section, one column per value)")
    if not any(meshes for _, meshes in drawn):
        raise Unusable(f"no value of {name} rendered a body; see the errors above.")
    print(f"  passes: {', '.join(passing)} (every body a closed solid, no clash in any state)" if passing else "  no value passes: each has a clash, a render error or a body that is not closed")
    return 0 if passing else 1


# ---------------------------------------------------------------- testpiece


def _parse_box(text: str) -> tuple[list[float], list[float]]:
    try:
        numbers = [float(part) for part in text.split(",")]
    except ValueError:
        numbers = []
    if len(numbers) != 6 or not all(math.isfinite(n) for n in numbers):
        raise Unusable(f"--box {text!r}: six numbers x0,y0,z0,x1,y1,z1 in mm, like --box 0,0,0,30,20,15 (write --box=-5,... when the first is negative).")
    lo, hi = numbers[:3], numbers[3:]
    if any(hi[i] <= lo[i] for i in range(3)):
        raise Unusable("--box: x1, y1 and z1 must each be larger than x0, y0 and z0.")
    return lo, hi


def cmd_testpiece(args) -> int:
    lo, hi = _parse_box(args.box)
    np, trimesh = _lazy_imports()
    m3d = _manifold()
    version = _version_root(Path(args.path))
    meshes = _load_meshes(version)
    named = _bodies_of("", args.bodies) if args.bodies else []
    unknown = [n for n in named if n not in meshes]
    if unknown:
        raise Unusable(f"no body {unknown[0]!r} in {version.name}; its bodies are {', '.join(meshes)}.")
    where = _fmt_box(lo, hi)
    box = m3d.Manifold.cube([hi[i] - lo[i] for i in range(3)]).translate(lo)
    pieces, missed = {}, []
    for name in named or list(meshes):
        solid = _to_manifold(name, meshes[name])
        piece = solid ^ box
        if piece.is_empty() or piece.volume() < 1e-6:
            missed.append(name)
        else:
            pieces[name] = (piece, solid.volume())
    spans = "; ".join(f"{n} spans {_fmt_box(*meshes[n].bounds)}" for n in missed)
    if named and missed:
        raise Unusable(f"the box {where} holds nothing of {', '.join(missed)} ({spans}); move the box or leave {'it' if len(missed) == 1 else 'them'} out of --bodies.")
    if not pieces:
        raise Unusable(f"the box {where} holds nothing of any body ({spans}); move the box.")

    folder = version / "test"
    _clear(folder)  # a new cut replaces the last one
    folder.mkdir()
    report = {"version": f"{version.name}/test", "model": str(version / "model.scad"), "box_mm": [*lo, *hi], "bodies": {}}
    loaded, results = {}, {}
    for name, (piece, whole) in pieces.items():
        target = folder / f"{name}.stl"
        _from_manifold(piece).export(target)
        mesh = trimesh.load(target, force="mesh", process=True)
        loaded[name] = mesh
        measured = _measure(mesh)
        report["bodies"][name] = {"file": target.name, **measured}
        results[name] = {"file": target.name, **{k: measured.get(k) for k in ("size_mm", "min_mm", "max_mm", "volume_mm3", "solid_mass_g_pla", "shells")}}
        results[name]["share_of_body_pct"] = _r(piece.volume() / whole * 100, 1) if whole else None
    clashes, gaps = _overlaps(loaded, None, [], 0.01, args.clearance) if len(loaded) > 1 else ([], [])
    _write_json(folder / "report.json", report)
    _write_json(folder / "test.json", {"version": f"{version.name}/test", "box_mm": [*lo, *hi], "pieces": results, "left_out": missed, "clearance_mm": args.clearance, "clashes": clashes, "gaps": gaps})

    print(f"{version.name}/test: {len(pieces)} piece{'' if len(pieces) == 1 else 's'} cut by the box {where} -> {folder}")
    for name, piece in results.items():
        size = " x ".join(f"{v:g}" for v in piece["size_mm"])
        volume = f"vol {piece['volume_mm3']:g} mm3, ~{piece['solid_mass_g_pla']:g} g solid PLA" if piece["volume_mm3"] is not None else "NOT A CLOSED SOLID"
        shells = "" if piece["shells"] == 1 else f", {piece['shells']} separate shells"
        print(f"  {name}: {size} mm, {volume}, {piece['share_of_body_pct']:g}% of the body{shells}")
    if missed:
        print(f"  left out, the box misses them: {', '.join(missed)}")
    for clash in clashes:
        print(f"  CLASH {clash['pair'][0]} / {clash['pair'][1]}: {clash['overlap_mm3']} mm3 at {clash['where']}")
    for gap in gaps:
        if gap["tight"]:
            print(f"  tight {gap['pair'][0]} / {gap['pair'][1]}: gap {gap['min_gap_mm']} mm < {args.clearance} mm")
    measured = [g for g in gaps if g["min_gap_mm"] is not None]
    if measured:
        smallest = min(measured, key=lambda g: g["min_gap_mm"])
        print(f"  smallest gap: {smallest['min_gap_mm']} mm, {smallest['pair'][0]} / {smallest['pair'][1]}")
    print(f"  The pieces sit where they are in the assembly: lay each flat to print it. views and print take {version.name}/test like a version.")
    print("  PASS: the pieces do not overlap" if not clashes else f"  FAIL: {len(clashes)} overlaps")
    return 1 if clashes else 0


# ---------------------------------------------------------------- compare

COMPARE_SUFFIXES = (".stl", ".3mf", ".step", ".stp")


def _load_solid(path: Path, label: str):
    """One solid from an .stl, a one-body .3mf or a .step/.stp (tessellated), and what the file said about itself."""
    if path.suffix.lower() not in COMPARE_SUFFIXES:
        raise Unusable(f"{label} {path.name}: compare reads .stl, .3mf (one body), .step or .stp.")
    if not path.is_file():
        raise Unusable(f"{label} {path} does not exist.")
    np, trimesh = _lazy_imports()
    info = {"file": str(path)}
    suffix = path.suffix.lower()
    if suffix == ".stl":
        mesh = trimesh.load(path, force="mesh", process=True)
    elif suffix == ".3mf":
        try:
            scene = trimesh.load(path, file_type="3mf", force="scene")
        except Exception as exc:  # a damaged archive raises anything from zipfile to lxml
            raise Unusable(f"{label} {path.name} does not load as 3MF ({type(exc).__name__}).") from exc
        nodes = list(scene.graph.nodes_geometry)
        if len(nodes) != 1:
            raise Unusable(f"{label} {path.name} holds {len(nodes)} bodies; compare takes one solid per file, so compare that body's STL.")
        transform, geometry = scene.graph[nodes[0]]
        mesh = scene.geometry[geometry].copy()
        mesh.apply_transform(transform)
    else:
        shape = _read_step(path)
        if shape is None:
            raise Unusable(f"{label} {path.name} does not read as STEP.")
        facts = _step_facts(shape)
        info.update(solids=facts["solids"], open_shells=facts["open_shells"], brep_volume_mm3=_r(facts["volume_mm3"], 3))
        mesh = _tessellate(shape)
    if len(mesh.faces) == 0:
        raise Unusable(f"{label} {path.name} holds no surface.")
    info.update(triangles=int(len(mesh.faces)), min_mm=[_r(v, 3) for v in mesh.bounds[0]], max_mm=[_r(v, 3) for v in mesh.bounds[1]])
    return mesh, info


def cmd_compare(args) -> int:
    if not 0 < args.tolerance <= 100:
        raise Unusable("--tolerance is a percentage of A's volume, above 0 and at most 100.")
    if not 100 <= args.samples <= 50000:
        raise Unusable("--samples is 100 to 50000 points per solid.")
    a_path, b_path = Path(args.a).resolve(), Path(args.b).resolve()
    mesh_a, info_a = _load_solid(a_path, "A")
    mesh_b, info_b = _load_solid(b_path, "B")
    np, trimesh = _lazy_imports()
    hint = "compare measures volumes, so both files must be closed solids"
    solid_a = _to_manifold(f"A ({a_path.name})", mesh_a, hint)
    solid_b = _to_manifold(f"B ({b_path.name})", mesh_b, hint)
    volume_a, volume_b = solid_a.volume(), solid_b.volume()
    if volume_a <= 0:
        raise Unusable(f"A ({a_path.name}) has no volume.")
    common = (solid_a ^ solid_b).volume()
    symmetric = max(volume_a + volume_b - 2 * common, 0.0)
    percent = symmetric / volume_a * 100
    box_off = float(np.abs(np.asarray(mesh_a.bounds) - np.asarray(mesh_b.bounds)).max())
    # The largest distance from a point on one surface to the other, both ways: a sampled Hausdorff distance.
    points_a, _ = trimesh.sample.sample_surface(mesh_a, args.samples, seed=7)
    points_b, _ = trimesh.sample.sample_surface(mesh_b, args.samples, seed=7)
    _, from_a, _ = trimesh.proximity.closest_point(mesh_b, points_a)
    _, from_b, _ = trimesh.proximity.closest_point(mesh_a, points_b)
    worst_a, worst_b = int(np.argmax(from_a)), int(np.argmax(from_b))
    deviation, at = (float(from_a[worst_a]), points_a[worst_a]) if from_a[worst_a] >= from_b[worst_b] else (float(from_b[worst_b]), points_b[worst_b])
    passed = percent < args.tolerance
    out = {
        "a": str(a_path), "b": str(b_path), "a_info": info_a, "b_info": info_b, "a_sha256": _sha256(a_path), "b_sha256": _sha256(b_path),
        "volume_a_mm3": _r(volume_a, 3), "volume_b_mm3": _r(volume_b, 3), "volume_difference_mm3": _r(volume_b - volume_a, 3),
        "box_difference_mm": _r(box_off, 4), "symmetric_difference_mm3": _r(symmetric, 3), "symmetric_difference_pct": _r(percent, 4),
        "max_deviation_mm": _r(deviation, 4), "max_deviation_at_mm": [_r(v, 2) for v in at], "samples_per_solid": args.samples,
        "tolerance_pct": args.tolerance, "passed": passed,
    }  # fmt: skip
    result = b_path.parent / f"{b_path.stem}.compare.json"
    try:
        _write_json(result, out)
    except OSError:
        result = None

    print(f"compare A {a_path.name} with B {b_path.name}" + (f" -> {result}" if result else " (the result could not be written next to B)"))
    for label, mesh, volume, info in (("A", mesh_a, volume_a, info_a), ("B", mesh_b, volume_b, info_b)):
        solids = f", {info['solids']} solids in the STEP" if info.get("solids", 1) != 1 else ""
        print(f"  {label}: vol {volume:.1f} mm3, {_fmt_box(*mesh.bounds)}{solids}")
    print(f"  volume differs by {volume_b - volume_a:+.1f} mm3 ({_off_pct(volume_b, volume_a):.2f}% of A); the bounding boxes by at most {box_off:.3f} mm")
    print(f"  symmetric difference: {symmetric:.1f} mm3, {percent:.2f}% of A")
    print(f"  largest surface deviation: {deviation:.3f} mm at ({', '.join(f'{v:.1f}' for v in at)}), over {args.samples} points on each surface")
    verdict = f"symmetric difference {percent:.2f}% {'<' if passed else '>='} {args.tolerance:g}% of A"
    print(f"  PASS: {verdict}" if passed else f"  FAIL: {verdict}")
    return 0 if passed else 1


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cadkit.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render", help="render each body to STL in a new version folder")
    render.add_argument("model", help="the .scad file")
    render.add_argument("--design", required=True, help="the design folder; the render goes into its next v<N>")
    render.add_argument("--bodies", help="comma-separated body names (default: the BODIES list in the file)")
    render.add_argument("-D", dest="define", action="append", default=[], help="name=value passed to openscad, repeatable")
    render.add_argument("--timeout", type=int, default=600, help="seconds per body")
    render.add_argument("--clearance", type=float, default=0.3, help="report gaps below this, mm")
    render.add_argument("--print-layout", action="store_true", help='also render each body with layout="print" into <version>/print')
    render.set_defaults(run=cmd_render)

    check = sub.add_parser("check", help="overlap and clearance of the bodies in each pose and sweep")
    check.add_argument("path", help="a version folder, or a design folder for its newest version")
    check.add_argument("--poses", help="poses JSON; without it, the bodies as modelled")
    check.add_argument("--clearance", type=float, default=0.3, help="flag gaps below this, mm")
    check.set_defaults(run=cmd_check)

    views = sub.add_parser("views", help="shaded render and cross-sections as PNG")
    views.add_argument("path")
    views.add_argument("--sections", help="planes like z=5,y=0,x=12.5 (default: the middle of each axis)")
    views.add_argument("--poses")
    views.add_argument("--pose", help="draw the bodies placed as in this pose")
    views.add_argument("--at", type=float, help="the sweep value to draw the pose at")
    views.set_defaults(run=cmd_views)

    print_ = sub.add_parser("print", help="print checks on a print-layout render, optional slicer run")
    print_.add_argument("path")
    print_.add_argument("--bed", default="250x210x220", help="WxDxH mm")
    print_.add_argument("--overhang", type=float, default=45.0, help="steepest printable overhang, degrees from vertical")
    print_.add_argument("--max-overhang-area", type=float, default=25.0, help="mm2 of steeper overhang tolerated per region")
    print_.add_argument("--max-bridge", type=float, default=15.0, help="longest flat bridge, mm")
    print_.add_argument("--narrow", type=float, default=6.0, help="overhang strips this narrow and under 1.5 mm tall print anyway (small holes, short chamfers), mm")
    print_.add_argument("--min-wall", type=float, default=0.8, help="thinnest wall, mm (two 0.4 mm lines)")
    print_.add_argument("--min-gap", type=float, default=0.3, help="smallest gap between separate bodies, mm")
    print_.add_argument("--slice", action="store_true", help="run PrusaSlicer without supports for grams and time")
    print_.set_defaults(run=cmd_print)

    export = sub.add_parser("export", help="STEP (via CadQuery's kernel) and 3MF of the rendered bodies, each read back; a zip to deliver")
    export.add_argument("path")
    export.add_argument("--step", action="store_true")
    export.add_argument("--3mf", dest="threemf", action="store_true")
    export.add_argument("--zip", action="store_true", help="also pack the deliverables and a manifest into <design>-v<N>.zip")
    export.set_defaults(run=cmd_export)

    guide = sub.add_parser("guide", help="print and assembly guide as guide.pdf in the version folder")
    guide.add_argument("path")
    guide.add_argument("--title", help="the cover's title (default: the design folder's name)")
    guide.add_argument("--steps", help="assembly steps as plain text, one step per paragraph")
    guide.set_defaults(run=cmd_guide)

    study = sub.add_parser("study", help="render and check the model once per value of one parameter, outside the versions")
    study.add_argument("model", help="the .scad file")
    study.add_argument("--design", required=True, help="the design folder; the study goes into its studies/<name>/<value>/")
    study.add_argument("--param", required=True, help=f"name=v1,v2,... (at most {MAX_STUDY_VALUES} values)")
    study.add_argument("--bodies", help="comma-separated body names (default: the BODIES list in the file)")
    study.add_argument("-D", dest="define", action="append", default=[], help="name=value held for every value, repeatable")
    study.add_argument("--poses", help="poses JSON checked for every value; without it, the bodies as modelled")
    study.add_argument("--clearance", type=float, default=0.3, help="flag gaps below this, mm")
    study.add_argument("--section", help="the section plane of compare.png, like z=5 (default: the middle of z)")
    study.add_argument("--timeout", type=int, default=600, help="seconds per body")
    study.set_defaults(run=cmd_study)

    testpiece = sub.add_parser("testpiece", help="cut the bodies with a box, to print one joint or fit first")
    testpiece.add_argument("path")
    testpiece.add_argument("--box", required=True, help="x0,y0,z0,x1,y1,z1 in mm, where the bodies sit assembled")
    testpiece.add_argument("--bodies", help="comma-separated bodies to cut (default: every body the box reaches)")
    testpiece.add_argument("--clearance", type=float, default=0.3, help="flag gaps below this, mm")
    testpiece.set_defaults(run=cmd_testpiece)

    compare = sub.add_parser("compare", help="whether two solids (.stl, .3mf, .step) are the same shape")
    compare.add_argument("a", help="the reference solid, such as the OpenSCAD body's STL")
    compare.add_argument("b", help="the solid to prove, such as a body rebuilt in CadQuery")
    compare.add_argument("--tolerance", type=float, default=1.0, help="PASS below this symmetric difference, percent of A's volume")
    compare.add_argument("--samples", type=int, default=2000, help="points sampled on each surface for the deviation")
    compare.set_defaults(run=cmd_compare)

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except Failed as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Unusable as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    os.environ.setdefault("MPLBACKEND", "Agg")
    sys.exit(main())
