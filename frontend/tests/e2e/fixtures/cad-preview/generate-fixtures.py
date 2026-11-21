"""Regenerate the cad-preview e2e fixtures with the CAD module itself.

Run in the CAD kernel venv (see examples/deerflow-extension-cad/AGENTS.md):

    cd examples/deerflow-extension-cad
    uv run --no-project python ../../frontend/tests/e2e/fixtures/cad-preview/generate-fixtures.py
    cd ../../frontend && pnpm exec prettier --write tests/e2e/fixtures/cad-preview/*.json

It builds one part that passes and one that fails its bounding-box check, the
way `cad_build` names them, and writes the files the tool would save:

    mounting-plate.glb, mounting-plate.stl, mounting-plate.report.json
    mounting-plate-1.failed.glb, mounting-plate-1.report.json

The GLB is read as metres, the glTF unit. Until the CAD module writes its GLB
with a root scale of 0.001 itself, `metre_scale` adds that root scale here; on
a GLB that is already at metre scale it changes nothing.
"""

from __future__ import annotations

import json
import struct
import sys
import tempfile
from pathlib import Path

import cadquery as cq
from deerflow_extension_cad import build, measure
from deerflow_extension_cad.tool import decide

HERE = Path(__file__).resolve().parent
MAX_BYTES = 8 * 1024 * 1024


def plate(thickness: float):
    return cq.Workplane("XY").box(60, 40, thickness).faces(">Z").workplane().pushPoints([(-15, 0), (15, 0)]).hole(4)


def metre_scale(glb: bytes) -> bytes:
    """Give the scene roots a 0.001 scale unless the mesh is already in metres."""
    json_length = struct.unpack_from("<I", glb, 12)[0]
    doc = json.loads(glb[20 : 20 + json_length])
    largest = max(abs(value) for accessor in doc["accessors"] if accessor.get("type") == "VEC3" and "max" in accessor for value in accessor["max"] + accessor["min"])
    roots = doc["scenes"][doc.get("scene", 0)]["nodes"]
    scale = 1.0
    for root in roots:
        scale = min(scale, *doc["nodes"][root].get("scale", [1, 1, 1]))
    if largest * scale <= 10:
        return glb
    for root in roots:
        node = doc["nodes"][root]
        if "matrix" in node:
            raise SystemExit("A root node with a matrix: scale it by hand")
        node["scale"] = [value * 0.001 for value in node.get("scale", [1, 1, 1])]
        if "translation" in node:
            node["translation"] = [value * 0.001 for value in node["translation"]]
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    rest = glb[20 + json_length :]
    body = struct.pack("<II", len(text), 0x4E4F534A) + text + rest
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body


def write(stem: str, shape, expected_bbox: list[float]) -> None:
    payload = {"name": stem, "bbox_xyz_mm": expected_bbox}
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        names, _ = build.export(shape, cq, directory, MAX_BYTES)
        measured = measure.measure_step(directory / names["step"], cq)
        checks = decide(measured, payload)
        passed = all(check["passed"] for check in checks)
        glb = metre_scale((directory / names["glb"]).read_bytes())
        if passed:
            (HERE / f"{stem}.glb").write_bytes(glb)
            (HERE / f"{stem}.stl").write_bytes((directory / names["stl"]).read_bytes())
        else:
            (HERE / f"{stem}.failed.glb").write_bytes(glb)
    report = {"name": stem, "passed": passed, "expected": {"bbox_xyz_mm": expected_bbox}, "checks": checks, "measured": measured}
    (HERE / f"{stem}.report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(stem, "passed" if passed else "failed", measured["bbox_mm"], file=sys.stderr)


if __name__ == "__main__":
    write("mounting-plate", plate(6).findSolid(), [60, 40, 6])
    # Built 8 mm thick against an expected 6: the bounding-box check fails.
    write("mounting-plate-1", plate(8).findSolid(), [60, 40, 6])
