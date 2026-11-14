"""The ``cad_build`` model tool: build in a child process, decide, hand over the files.

The Gateway process never parses the script and never loads the CAD kernel.
It starts ``worker.py`` in a fresh interpreter with a wall-clock limit, reads
back measured numbers, compares them with what the model said the part must
meet, and writes files through the host (``ToolContext.write_output``).

The tool decides pass or fail, not the model: STEP, STL and GLB are written
only when every check passed, so a STEP file in a conversation's outputs means
a part that passed.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deerflow_extension_api import HostCapabilityError, ToolContext

WORKER = Path(__file__).with_name("worker.py")
REQUEST_FILE = "request.json"
RESULT_FILE = "result.json"

DEFAULT_TIMEOUT_SECONDS = 20
#: The host stops a plugin tool at 30 seconds; the build and the file writes must fit inside.
MAX_TIMEOUT_SECONDS = 25
DEFAULT_MEMORY_MB = 4096
#: The kernel needs over 1.1 GiB of address space just to load, and dies on a signal when a build runs out.
MIN_MEMORY_MB = 3072
#: The worker's answer and each exported file are read into Gateway memory, so both are bounded here.
MAX_RESULT_BYTES = 256 * 1024
#: If the Gateway dies mid-build nobody is left to stop the worker; the operating system does, this much later.
CPU_BACKSTOP_SECONDS = 10
MAX_EXPORT_BYTES = 16 * 1024 * 1024

#: A bounding box side or a hole diameter matches within 0.01 mm or 0.1 %, whichever is larger.
#: The kernel's own noise is far below that; the slack is for the model's rounding.
LENGTH_TOLERANCE_MM = 0.01
LENGTH_TOLERANCE_RATIO = 0.001

# Every character here is paid on every request of every conversation, and a
# small local model gets only the opening sentences within 280 characters (the
# host's short tool form). So the first four sentences stand on their own, the
# parameter names say what they hold instead of carrying descriptions, and the
# handler checks the values itself (``_problem_with``). The context-fit critical
# check pins the cost (backend/tests/test_context_fit_critical.py).
DESCRIPTION = (
    "Build a part from a CadQuery script and check it. The script is read, not run: only `import cadquery as cq`, "
    "assignments, arithmetic and allow-listed Workplane methods. Millimetres. Assign the part to `result`. "
    "No loops, functions or other imports. Methods: box, cylinder, sphere, rect, circle, ellipse, polygon, slot2D, polyline, "
    "moveTo, move, lineTo, line, hLine, vLine, hLineTo, vLineTo, threePointArc, close, center, extrude, cutBlind, cutThruAll, "
    "hole, cboreHole, cskHole, fillet, chamfer, shell, pushPoints, rarray, polarArray, faces, edges, vertices, workplane, tag, "
    "workplaneFromTagged, translate, rotate, mirror, mirrorX, mirrorY, union, cut, intersect. "
    "bbox_xyz_mm is the expected overall size along x, y and z. volume_min_max_mm3 is the allowed volume range. "
    "hole_diameters_mm lists one diameter per expected hole, [] for none. "
    "Returns pass or fail per check with the measured values. STEP, STL and GLB files are saved only when every check passes."
)

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "script": {"type": "string"},
        "bbox_xyz_mm": {"type": "array", "items": {"type": "number"}},
        "volume_min_max_mm3": {"type": "array", "items": {"type": "number"}},
        "hole_diameters_mm": {"type": "array", "items": {"type": "number"}},
    },
    "required": ["name", "script", "bbox_xyz_mm"],
}
EXPECTATIONS = ("bbox_xyz_mm", "volume_min_max_mm3", "hole_diameters_mm")

MAX_NAME_CHARS = 60
MAX_HOLES = 400


def _problem_with(payload: Mapping[str, Any]) -> str | None:
    """Say what is wrong with the arguments, in words the model can act on; None when they are usable."""

    def numbers(key: str, count: int | None) -> bool:
        value = payload.get(key)
        return isinstance(value, (list, tuple)) and (count is None or len(value) == count) and all(type(item) in (int, float) and item == item and abs(item) != float("inf") for item in value)

    unknown = sorted(set(payload) - set(INPUT_SCHEMA["properties"]))
    if unknown:
        # A misspelled expectation would otherwise be a check that silently never runs.
        return f"unknown argument {unknown[0]!r}; cad_build takes: {', '.join(INPUT_SCHEMA['properties'])}"
    if not payload["name"].strip() or len(payload["name"]) > MAX_NAME_CHARS:
        return f"name must be 1 to {MAX_NAME_CHARS} characters"
    if not payload["script"].strip():
        return "script is empty"
    if not numbers("bbox_xyz_mm", 3) or any(side <= 0 for side in payload["bbox_xyz_mm"]):
        return "bbox_xyz_mm must be three positive numbers: the expected size along x, y and z in millimetres"
    if "volume_min_max_mm3" in payload and (not numbers("volume_min_max_mm3", 2) or not 0 <= payload["volume_min_max_mm3"][0] <= payload["volume_min_max_mm3"][1]):
        return "volume_min_max_mm3 must be [min, max] with 0 <= min <= max, in cubic millimetres"
    if "hole_diameters_mm" in payload and (not numbers("hole_diameters_mm", None) or len(payload["hole_diameters_mm"]) > MAX_HOLES or any(diameter <= 0 for diameter in payload["hole_diameters_mm"])):
        return f"hole_diameters_mm must list one positive diameter per expected hole, at most {MAX_HOLES}"
    return None


def settings_from(config: Mapping[str, Any]) -> dict[str, int]:
    """Read the operator's values for this extension, clamped to what the host allows."""

    def whole(key: str, default: int, low: int, high: int) -> int:
        value = config.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"cad: {key} must be a whole number from {low} to {high}")
        return value

    return {"timeout_seconds": whole("timeout_seconds", DEFAULT_TIMEOUT_SECONDS, 5, MAX_TIMEOUT_SECONDS), "memory_mb": whole("memory_mb", DEFAULT_MEMORY_MB, MIN_MEMORY_MB, 65536)}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "part"


# --- Deciding ---------------------------------------------------------------


def _close(expected: float, measured: float) -> bool:
    return abs(expected - measured) <= max(LENGTH_TOLERANCE_MM, LENGTH_TOLERANCE_RATIO * abs(expected))


def decide(measured: Mapping[str, Any], payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Compare what was measured on the re-imported STEP with what the part must meet."""
    checks: list[dict[str, Any]] = [
        {
            "check": "one closed solid",
            "expected": "exactly one valid, closed solid",
            "measured": f"{measured['solids']} solid(s), valid={measured['valid']}, closed={measured['closed']}",
            "passed": measured["solids"] == 1 and measured["valid"] and measured["closed"],
        },
    ]
    box = measured["bbox_mm"]
    checks.append({"check": "bounding box", "expected": list(payload["bbox_xyz_mm"]), "measured": box, "passed": len(box) == 3 and all(_close(e, m) for e, m in zip(payload["bbox_xyz_mm"], box))})
    if "volume_min_max_mm3" in payload:
        low, high = payload["volume_min_max_mm3"]
        slack = 1e-6 * high
        checks.append({"check": "volume", "expected": [low, high], "measured": measured["volume_mm3"], "passed": low - slack <= measured["volume_mm3"] <= high + slack})
    if "hole_diameters_mm" in payload:
        expected = sorted(payload["hole_diameters_mm"])
        found = sorted(hole["diameter_mm"] for hole in measured["holes"])
        checks.append({"check": "holes", "expected": expected, "measured": found, "passed": len(expected) == len(found) and all(_close(e, m) for e, m in zip(expected, found))})
    return checks


# --- Running the worker -----------------------------------------------------


def _prepare(script: str, memory_mb: int, timeout_seconds: int) -> str:
    directory = tempfile.mkdtemp(prefix="deerflow-cad-")
    request = {"script": script, "memory_mb": memory_mb, "max_export_bytes": MAX_EXPORT_BYTES, "cpu_seconds": timeout_seconds + CPU_BACKSTOP_SECONDS}
    Path(directory, REQUEST_FILE).write_text(json.dumps(request), encoding="utf-8")
    return directory


def _collect(directory: str) -> dict[str, Any]:
    path = Path(directory, RESULT_FILE)
    if not path.is_file() or path.stat().st_size > MAX_RESULT_BYTES:
        return {}
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    if not isinstance(result, dict):
        return {}
    files = {}
    for kind, name in (result.get("files") or {}).items():
        exported = Path(directory, name)
        # The worker names files in its own directory; anything else is not read.
        if exported.parent == Path(directory) and exported.is_file() and not exported.is_symlink() and exported.stat().st_size <= MAX_EXPORT_BYTES:
            files[kind] = exported.read_bytes()
    result["files"] = files
    return result


def _worker_environment(directory: str) -> dict[str, str]:
    # One BLAS thread: the kernel does no linear algebra worth more, and every extra
    # thread reserves address space that counts against the memory ceiling.
    environment = {"PATH": os.defpath, "LANG": "C.UTF-8", "HOME": directory, "OPENBLAS_NUM_THREADS": "1"}
    if os.name == "nt" and "SYSTEMROOT" in os.environ:
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]  # Python cannot start without it on Windows
    return environment


def _stop(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)  # the worker leads its own session
        else:
            process.kill()
    except ProcessLookupError:
        pass


async def run_worker(script: str, *, timeout_seconds: int, memory_mb: int) -> dict[str, Any]:
    """Build *script* in a child interpreter and return its answer, or a failure it could not report itself."""
    directory = await asyncio.to_thread(_prepare, script, memory_mb, timeout_seconds)
    process = None
    try:
        # -I: no PYTHONPATH, no user site, no current directory on sys.path. The
        # environment carries nothing from the Gateway: no credentials, no proxy.
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(WORKER),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=directory,
            env=_worker_environment(directory),
            start_new_session=os.name == "posix",
        )
        try:
            async with asyncio.timeout(timeout_seconds):
                code = await process.wait()
        except TimeoutError:
            return {
                "status": "failed",
                "message": f"the build did not finish within {timeout_seconds} seconds and was stopped. Simplify the part: fewer pattern points, fewer fillets, and hole() instead of circle().cutThruAll() for round holes.",
            }
        result = await asyncio.to_thread(_collect, directory)
        if result.get("status"):
            return result
        reason = f"signal {-code}" if code < 0 else f"exit code {code}"
        return {"status": "failed", "message": f"the CAD kernel stopped without an answer ({reason}); it may have run out of memory"}
    finally:
        # Also on cancellation: the host's 30 second limit or a stopped run must not leave a kernel running.
        if process is not None:
            _stop(process)
            await asyncio.shield(process.wait())
        await asyncio.to_thread(shutil.rmtree, directory, True)


# --- The handler ------------------------------------------------------------


async def _save(context: ToolContext, name: str, content: bytes, saved: list[str], problems: list[str]) -> str | None:
    try:
        path = await context.write_output(name, content)
    except HostCapabilityError as exc:
        problems.append(f"{name} was not saved ({exc.code})")
        return None
    saved.append(path)
    return path


def make_handler(settings: Mapping[str, int]):
    async def cad_build(payload: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
        if context.output_writer is None:
            return {"passed": False, "error": "This conversation cannot receive files, so no part was built."}
        problem = _problem_with(payload)
        if problem:
            return {"passed": False, "error": {"message": problem}, "next": "Correct the arguments and call cad_build again."}
        script = payload["script"]
        result = await run_worker(script, timeout_seconds=settings["timeout_seconds"], memory_mb=settings["memory_mb"])
        saved: list[str] = []
        problems: list[str] = []
        # The script is saved first: the name the host gives it is this build's stem, so
        # a rebuild of the same part gets plate-1.* as a set instead of a mix.
        script_path = await _save(context, f"{slug(payload['name'])}.py", script.encode("utf-8"), saved, problems)
        stem = Path(script_path).stem if script_path else slug(payload["name"])
        answer: dict[str, Any] = {"passed": False}
        report: dict[str, Any] = {"name": payload["name"], "passed": False, "expected": {key: payload[key] for key in EXPECTATIONS if key in payload}}
        files = result.get("files") or {}
        if result.get("status") == "built":
            checks = decide(result["measured"], payload)
            passed = all(check["passed"] for check in checks)
            answer.update(passed=passed, checks=checks)
            report.update(passed=passed, checks=checks, measured=result["measured"])
            if passed:
                # STEP goes last: a STEP file in the outputs means the whole set was handed over.
                for kind in ("glb", "stl", "step"):
                    if kind not in files:
                        problems.append(f"the {kind.upper()} export is missing or larger than {MAX_EXPORT_BYTES // (1024 * 1024)} MiB")
                    elif await _save(context, f"{stem}.{kind}", files[kind], saved, problems) is not None:
                        continue
                    # A part that passed but could not be handed over in full is not presented as delivered.
                    answer["passed"] = report["passed"] = False
                    break
            elif "glb" in files:
                await _save(context, f"{stem}.failed.glb", files["glb"], saved, problems)
        else:
            error = {key: result[key] for key in ("construct", "line", "operation", "message") if result.get(key) is not None}
            answer["error"] = report["error"] = error or {"message": "the build failed"}
        if problems:
            report["problems"] = list(problems)
        await _save(context, f"{stem}.report.json", json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8"), saved, problems)
        if problems:
            answer["problems"] = problems
        answer["files"] = saved
        if not answer["passed"]:
            answer["next"] = "Fix the script or the expected numbers and call cad_build again. Do not present this part as finished."
        return answer

    return cad_build
