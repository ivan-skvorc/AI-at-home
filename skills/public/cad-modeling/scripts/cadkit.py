#!/usr/bin/env python3
"""cadkit: render, check, look at and export a multi-body OpenSCAD model.

Runs inside the conversation's sandbox container (the CAD image), never in the
Gateway. Every command reads and writes one version folder, so a design keeps
its history: ``render`` makes ``<design>/v<N>/`` and the other commands take
that folder, or the design folder for its newest version.

    cadkit.py render model.scad --design /mnt/user-data/outputs/stand [-D name=value ...]
    cadkit.py check  /mnt/user-data/outputs/stand [--poses poses.json] [--clearance 0.3]
    cadkit.py views  /mnt/user-data/outputs/stand [--sections z=5,y=0] [--poses p.json --pose NAME [--at 40]]
    cadkit.py print  /mnt/user-data/outputs/stand/print [--bed 250x210x220] [--slice]
    cadkit.py export /mnt/user-data/outputs/stand [--step] [--3mf]

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
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import warnings as warnings_module
from pathlib import Path

NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
BODIES_LINE = re.compile(r"^\s*BODIES\s*=\s*\[([^\]]*)\]\s*;", re.MULTILINE)
QUOTED = re.compile(r'"([^"]*)"')
DEFINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.+$")
PLA_DENSITY_G_CM3 = 1.24
PALETTE = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2", "#EECA3B", "#9D755D", "#FF9DA6", "#BAB0AC"]
MAX_SWEEP_STEPS = 360
MAX_STEP_TRIANGLES = 60000
# PrusaSlicer's own log lines ("[2026-...] [0x7f...] [trace]   Initializing StaticPrintConfigs"), printed on every run.
SLICER_LOG = re.compile(r"^\[[^\]]*\] \[0x[0-9a-fA-F]+\] \[(trace|debug|info)\]")


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


def _to_manifold(name: str, mesh):
    np, _ = _lazy_imports()
    m3d = _manifold()
    solid = m3d.Manifold(m3d.Mesh(vert_properties=np.asarray(mesh.vertices, dtype=np.float32), tri_verts=np.asarray(mesh.faces, dtype=np.uint32)))
    if solid.status() != m3d.Error.NoError:
        raise Unusable(f"body {name} is not a closed solid ({solid.status()}); fix the model (render reports which bodies are not watertight) before checking it.")
    return solid


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")


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
        for body in pose.get("place", {}):
            if body not in bodies:
                raise Unusable(f"{where}.place: no body {body!r}; bodies are {bodies}.")
        sweep = pose.get("sweep")
        if sweep is not None:
            moving = sweep.get("bodies", [sweep.get("body")])
            if not moving or any(b not in bodies for b in moving):
                raise Unusable(f"{where}.sweep: name the moving body (body) or bodies (bodies) from {bodies}.")
    ignore = data.get("ignore", [])
    if not all(isinstance(p, list) and len(p) == 2 and all(b in bodies for b in p) for p in ignore):
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

    print(f"{version.name}: {states} states checked across {len(poses['poses'])} poses, {len(bodies)} bodies")
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


def _shaded(meshes: dict, target: Path) -> None:
    np, trimesh = _lazy_imports()
    plt = _plt()
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    lo = np.min([m.bounds[0] for m in meshes.values()], axis=0)
    hi = np.max([m.bounds[1] for m in meshes.values()], axis=0)
    span = np.maximum(hi - lo, 1e-6)
    light = np.array([0.4, -0.5, 0.75])
    light /= np.linalg.norm(light)
    views = [("iso", 28, -58), ("front (looking +Y)", 0, -90), ("right (looking -X)", 0, 0), ("top (looking -Z)", 90, -90)]
    fig = plt.figure(figsize=(12, 9), dpi=110)
    for index, (title, elev, azim) in enumerate(views, 1):
        ax = fig.add_subplot(2, 2, index, projection="3d")
        for colour_index, (name, mesh) in enumerate(meshes.items()):
            base = np.array([int(PALETTE[colour_index % len(PALETTE)][i : i + 2], 16) / 255 for i in (1, 3, 5)])
            shade = 0.35 + 0.65 * np.clip(mesh.face_normals @ light, 0, 1)
            colours = np.clip(base[None, :] * shade[:, None], 0, 1)
            ax.add_collection3d(Poly3DCollection(mesh.triangles, facecolors=colours, edgecolors="none", linewidths=0))
            ax.plot([], [], color=base, label=name, linewidth=6)
        ax.set_xlim(lo[0], lo[0] + span.max())
        ax.set_ylim(lo[1], lo[1] + span.max())
        ax.set_zlim(lo[2], lo[2] + span.max())
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=elev, azim=azim)
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


def _sections(meshes: dict, specs: list[tuple[str, float]], target: Path) -> list[dict]:
    np, trimesh = _lazy_imports()
    plt = _plt()
    from matplotlib.patches import Polygon as Patch

    axes_of = {"x": (1, 2, [1, 0, 0]), "y": (0, 2, [0, 1, 0]), "z": (0, 1, [0, 0, 1])}
    names = {"x": "side", "y": "front", "z": "plan"}
    columns = min(3, len(specs))
    rows = math.ceil(len(specs) / columns)
    fig, grid = plt.subplots(rows, columns, figsize=(6 * columns, 5 * rows), dpi=110, squeeze=False)
    summary = []
    for index, (axis, value) in enumerate(specs):
        ax = grid[index // columns][index % columns]
        u, v, normal = axes_of[axis]
        origin = [0.0, 0.0, 0.0]
        origin["xyz".index(axis)] = value
        cut = []
        for colour_index, (name, mesh) in enumerate(meshes.items()):
            colour = PALETTE[colour_index % len(PALETTE)]
            lines = trimesh.intersections.mesh_plane(mesh, plane_normal=normal, plane_origin=origin)
            if len(lines) == 0:
                continue
            cut.append(name)
            for polygon in _polygons(lines[:, :, [u, v]]):
                ax.add_patch(Patch(polygon, closed=True, facecolor=colour, alpha=0.35, edgecolor=colour, linewidth=1.2))
            for segment in lines:
                ax.plot(segment[:, u], segment[:, v], color=colour, linewidth=1.0)
            ax.plot([], [], color=colour, label=name, linewidth=4)
        ax.set_aspect("equal", adjustable="datalim")
        ax.grid(True, linewidth=0.3)
        ax.set_xlabel(f"{'xyz'[u]} mm")
        ax.set_ylabel(f"{'xyz'[v]} mm")
        ax.set_title(f"{names[axis]} section at {axis} = {value:g} mm" + ("" if cut else " (cuts nothing)"))
        if cut:
            ax.legend(fontsize=8, loc="best")
        ax.autoscale_view()
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
    print(f"{version.name}: views written. Look at both images before judging the part:")
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
    label = f"{version.parent.name}/print" if version.name == "print" else version.name
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


# ---------------------------------------------------------------- export


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
        raise Unusable("CadQuery (OCP) is not installed here; it is in the CAD sandbox image.") from exc
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
    # The kernel prints transfer statistics on file descriptor 1; keep them out of the summary.
    sys.stdout.flush()
    saved = os.dup(1)
    try:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), 1)
            writer.Transfer(result, STEPControl_AsIs)
            status = writer.Write(str(target))
    finally:
        os.dup2(saved, 1)
        os.close(saved)
    if status != IFSelect_RetDone:
        raise Unusable(f"the STEP writer failed for {target.name}")


def cmd_export(args) -> int:
    np, trimesh = _lazy_imports()
    version = _version_dir(Path(args.path))
    meshes = _load_meshes(version)
    if not (args.step or args.threemf):
        raise Unusable("choose --step, --3mf or both.")
    written = []
    if args.step:
        for name, mesh in meshes.items():
            if len(mesh.faces) > MAX_STEP_TRIANGLES:
                raise Unusable(f"{name} has {len(mesh.faces)} triangles (> {MAX_STEP_TRIANGLES}); render the export with a lower $fn, e.g. -D '$fn=64'.")
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
    print(f"{version.name}: wrote {', '.join(written)} in {version}")
    if args.step:
        print("  STEP files are faceted: each triangle of the mesh is a face. Good for fit-checking in a CAD program, not for editing features.")
    return 0


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

    export = sub.add_parser("export", help="STEP (via CadQuery's kernel) and 3MF of the rendered bodies")
    export.add_argument("path")
    export.add_argument("--step", action="store_true")
    export.add_argument("--3mf", dest="threemf", action="store_true")
    export.set_defaults(run=cmd_export)

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
