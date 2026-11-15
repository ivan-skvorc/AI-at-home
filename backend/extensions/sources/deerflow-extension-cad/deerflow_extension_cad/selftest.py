"""Build a one-millimetre cube through the real tool: ``python -m deerflow_extension_cad.selftest``.

``make doctor`` runs this in a child interpreter when the extension is
installed, and the Gateway image runs it once while it is built. It calls the
same handler the model does, with a writer that keeps the files in memory, and
prints one JSON line: ``{"ok": true, "bbox_mm": ...}`` or
``{"ok": false, "error": ...}``. A missing system library shows up in the error
text by name. Exit status is 0 only for a cube that was built and measured.

The kernel is loaded once first, with a limit of its own. Its first load after
an install or a restart reads over a gigabyte of libraries from disk and
compiles about six hundred modules, which on a slow or busy disk outlasts the
time a build may take; done here, a model's first build is not the one that
pays for it.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time

from deerflow_extension_api import ExtensionPrincipal, ToolContext

from deerflow_extension_cad.tool import _worker_environment, make_handler, settings_from

CUBE = 'import cadquery as cq\nresult = cq.Workplane("XY").box(1, 1, 1)\n'
#: How long loading the kernel may take here. A build has 20 seconds for everything.
#: A load stopped at this limit still leaves the libraries in the disk cache.
LOAD_TIMEOUT_SECONDS = 25


def load_kernel() -> float:
    """Import the kernel once in a child, as the worker does, and return the seconds it took.

    A failure is not reported from here: the build that follows meets the same
    failure and says what it is, a missing library by name.
    """
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="deerflow-cad-load-") as directory:
        try:
            subprocess.run(
                [sys.executable, "-I", "-c", "import cadquery"],
                cwd=directory,
                env=_worker_environment(directory),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=LOAD_TIMEOUT_SECONDS,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass
    return round(time.monotonic() - started, 1)


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
    load_seconds = load_kernel()
    result = {**asyncio.run(build_cube()), "load_seconds": load_seconds}
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
