"""Build a one-millimetre cube through the real tool: ``python -m deerflow_extension_cad.selftest``.

``make doctor`` runs this in a child interpreter when the extension is
installed. It calls the same handler the model does, with a writer that keeps
the files in memory, and prints one JSON line: ``{"ok": true, "bbox_mm": ...}``
or ``{"ok": false, "error": ...}``. A missing system library shows up in the
error text by name. Exit status is 0 only for a cube that was built and
measured.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

from deerflow_extension_api import ExtensionPrincipal, ToolContext

from deerflow_extension_cad.tool import make_handler, settings_from

CUBE = 'import cadquery as cq\nresult = cq.Workplane("XY").box(1, 1, 1)\n'


async def build_cube() -> dict:
    files: dict[str, bytes] = {}

    async def keep(name: str, content: bytes) -> str:
        files[name] = content
        return f"/mnt/user-data/outputs/{name}"

    context = ToolContext(ExtensionPrincipal("doctor"), {"enabled": True}, "selftest", output_writer=keep)
    started = time.monotonic()
    answer = await make_handler(settings_from({}))({"name": "cube", "script": CUBE, "bbox_xyz_mm": [1, 1, 1], "volume_min_max_mm3": [0.999, 1.001], "hole_diameters_mm": []}, context)
    seconds = round(time.monotonic() - started, 1)
    if answer.get("passed") is True and "cube.step" in files:
        report = json.loads(files["cube.report.json"])
        return {"ok": True, "bbox_mm": report["measured"]["bbox_mm"], "volume_mm3": report["measured"]["volume_mm3"], "seconds": seconds}
    error = (answer.get("error") or {}).get("message") or "; ".join(answer.get("problems") or []) or "the cube did not pass its own checks"
    return {"ok": False, "error": error, "seconds": seconds}


def main() -> int:
    result = asyncio.run(build_cube())
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
