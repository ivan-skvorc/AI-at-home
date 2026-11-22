"""Regenerate the cad-preview e2e fixtures with the CAD module itself.

Run in the CAD kernel venv (see examples/deerflow-extension-cad/AGENTS.md):

    cd examples/deerflow-extension-cad
    uv run --no-project python ../../frontend/tests/e2e/fixtures/cad-preview/generate-fixtures.py
    cd ../../frontend && pnpm exec prettier --write tests/e2e/fixtures/cad-preview/*.json

It builds a part that passes, one that fails its bounding-box check and one of
two bodies, the way `cad_build` names them, and writes the files the tool would
save that the spec reads:

    mounting-plate.glb, mounting-plate.stl, mounting-plate.report.json
    mounting-plate-1.failed.glb, mounting-plate-1.report.json
    split-plate.glb, split-plate.report.json

The module writes its GLB in metres, the glTF unit, with one node per body; the
files are copied as it wrote them.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import cadquery as cq

from deerflow_extension_cad import build, measure
from deerflow_extension_cad.checks import decide

HERE = Path(__file__).resolve().parent
MAX_BYTES = 8 * 1024 * 1024


def plate(thickness: float):
    return cq.Workplane("XY").box(60, 40, thickness).faces(">Z").workplane().pushPoints([(-15, 0), (15, 0)]).hole(4)


def split_plate():
    """Two 25 x 40 x 6 halves 10 mm apart along x. The holes stay off y = 0, the line the spec scans."""
    halves = [(-17.5, 0), (17.5, 0)]
    holes = [(x, y) for x, _ in halves for y in (-12, 12)]
    return cq.Workplane("XY").pushPoints(halves).box(25, 40, 6).faces(">Z").workplane().pushPoints(holes).hole(4)


def write(stem: str, shape, expected: dict, *, stl: bool = True) -> None:
    payload = {"name": stem, **expected}
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        names, _ = build.export(shape, cq, directory, MAX_BYTES)
        measured = measure.measure_step(directory / names["step"], cq)
        checks = decide(measured, payload)
        passed = all(check["passed"] for check in checks)
        glb = (directory / names["glb"]).read_bytes()
        if passed:
            (HERE / f"{stem}.glb").write_bytes(glb)
            if stl:
                (HERE / f"{stem}.stl").write_bytes((directory / names["stl"]).read_bytes())
        else:
            (HERE / f"{stem}.failed.glb").write_bytes(glb)
    report = {"name": stem, "passed": passed, "expected": expected, "checks": checks, "measured": measured}
    (HERE / f"{stem}.report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(stem, "passed" if passed else "failed", measured["solids"], "solid(s)", measured["bbox_mm"], file=sys.stderr)


if __name__ == "__main__":
    write("mounting-plate", plate(6).findSolid(), {"bbox_xyz_mm": [60, 40, 6]})
    # Built 8 mm thick against an expected 6: the bounding-box check fails.
    write("mounting-plate-1", plate(8).findSolid(), {"bbox_xyz_mm": [60, 40, 6]})
    write("split-plate", split_plate().findSolid(), {"bbox_xyz_mm": [60, 40, 6], "bodies": 2}, stl=False)
