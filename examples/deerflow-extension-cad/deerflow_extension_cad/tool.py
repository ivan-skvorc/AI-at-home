"""The ``cad_build`` model tool: build in a child process, decide, hand over the files.

The Gateway process never parses the script and never loads the CAD kernel.
It starts ``worker.py`` in a fresh interpreter with a wall-clock limit, reads
back measured numbers, compares them with what the model said the part must
meet, and writes files through the host (``ToolContext.write_output``).

The tool decides pass or fail, not the model: STEP, STL and GLB are written
only when every check passed, so a STEP file listed in a ``cad_build`` answer
means a part that passed.
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
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deerflow_extension_api import HostCapabilityError, ToolContext

from deerflow_extension_cad.build import MESH_STEPS

WORKER = Path(__file__).with_name("worker.py")
REQUEST_FILE = "request.json"
RESULT_FILE = "result.json"
PHASE_FILE = "phase"

DEFAULT_TIMEOUT_SECONDS = 20
#: The host stops a plugin tool at 30 seconds; the build and the file writes must fit inside.
MAX_TIMEOUT_SECONDS = 25
DEFAULT_MEMORY_MB = 4096
#: The kernel needs about 1 GiB of address space just to load, and dies on a signal when a build runs out.
MIN_MEMORY_MB = 3072
#: Builds at once. Each holds several hundred MiB and works on several cores, so more of
#: them than the machine can carry all run out of time together and blame the part.
MAX_PARALLEL_BUILDS = 16


def default_parallel_builds() -> int:
    """Half the processors, inside the range an operator may set."""
    return min(MAX_PARALLEL_BUILDS, max(1, (os.cpu_count() or 2) // 2))


#: How long a call waits for a free slot before it is told to call again. With the
#: longest build it still ends inside the host's 30 seconds.
QUEUE_SECONDS = 3
#: The worker's answer and each exported file are read into Gateway memory, so both are bounded here.
MAX_RESULT_BYTES = 256 * 1024
#: If the Gateway dies mid-build nobody is left to stop the worker; the operating system does,
#: this many processor seconds after the most a build could use inside its wall clock.
CPU_BACKSTOP_SECONDS = 10
MAX_EXPORT_BYTES = 16 * 1024 * 1024

#: A bounding box side or a hole diameter matches within 0.01 mm or 0.1 %, whichever is larger.
#: The kernel's own noise is far below that; the slack is for the model's rounding.
LENGTH_TOLERANCE_MM = 0.01
LENGTH_TOLERANCE_RATIO = 0.001

# Every character here is paid on every request of every conversation, and a
# small local model gets only the opening sentences within 280 characters (the
# host's short tool form). So the opening sentences stand on their own, the
# parameter names say what they hold instead of carrying descriptions, and the
# handler checks the values itself (``_problem_with``). The context-fit critical
# check pins the cost (backend/tests/test_context_fit_critical.py).
DESCRIPTION = (
    "Build and check a part from a CadQuery script. It is read, not run: only assignments, arithmetic and "
    "allow-listed Workplane methods. Millimetres. Assign the part to result. "
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
        # No item types: they cost twenty tokens of every request, and the handler checks each number itself.
        "bbox_xyz_mm": {"type": "array"},
        "volume_min_max_mm3": {"type": "array"},
        "hole_diameters_mm": {"type": "array"},
    },
    "required": ["name", "script", "bbox_xyz_mm"],
}
EXPECTATIONS = ("bbox_xyz_mm", "volume_min_max_mm3", "hole_diameters_mm")

MAX_NAME_CHARS = 60
MAX_HOLES = 400
#: No expected number may exceed what a script itself may state.
MAX_EXPECTED = 1e12

NEXT_FIX = "Fix the script or the expected numbers and call cad_build again. Do not present this part as finished."
NEXT_UNAVAILABLE = "The CAD kernel cannot run on this server, so another script will not help. Do not call cad_build again; tell the user, and that `make doctor` on the server names what is missing."
NEXT_BUSY = "Nothing is wrong with the script. Call cad_build again with the same arguments."
NEXT_UNSTORED = "The part met its checks but its files could not all be stored, so it is not delivered. Tell the user which file was refused; a part with fewer small fillets and holes gives smaller files."
NEXT_NO_FILES = "Nothing could be stored in this conversation, so nothing is delivered. Tell the user which file was refused."
NEXT_ARGUMENTS = "Correct the arguments and call cad_build again."
NEXT_STILL_LOADING = "Nothing is wrong with the script. Call cad_build again with the same arguments: the next build is quick."
NEXT_NOT_LOADING = "The CAD kernel does not finish loading on this server. Do not call cad_build again; tell the user to run `make doctor`, which loads it once and names what is wrong."
#: Builds in a row, in one conversation, that may end while the kernel is still loading before the
#: answer stops saying "call again". Each attempt leaves more of the kernel in the disk cache, so two
#: are enough on a fresh install; on a host too slow to ever load it, calling again would never end.
MAX_LOADING_ANSWERS = 3
#: Conversations whose count is kept. A count is a few bytes; the cap only keeps the table from growing for ever.
MAX_COUNTED_CONVERSATIONS = 1000
#: What a timed-out worker was doing, in the words of the answer.
_PHASES = {
    "exporting": "The part was built, and writing its files did not finish in time. Simplify the part: fewer small fillets and holes.",
    "measuring": "The part was built, and measuring it did not finish in time. Reduce the number of holes and fillets.",
}


def _problem_with(payload: Mapping[str, Any]) -> str | None:
    """Say what is wrong with the arguments, in words the model can act on; None when they are usable."""

    def numbers(key: str, count: int | None) -> bool:
        value = payload.get(key)
        # Bounded as well as finite: an integer too large for a float passes the schema and breaks the arithmetic.
        return isinstance(value, (list, tuple)) and (count is None or len(value) == count) and all(type(item) in (int, float) and abs(item) <= MAX_EXPECTED for item in value)

    unknown = sorted(set(payload) - set(INPUT_SCHEMA["properties"]))
    if unknown:
        # A misspelled expectation would otherwise be a check that silently never runs.
        return f"unknown argument {unknown[0]!r}; cad_build takes: {', '.join(INPUT_SCHEMA['properties'])}"
    if not payload["name"].strip() or len(payload["name"]) > MAX_NAME_CHARS:
        return f"name must be 1 to {MAX_NAME_CHARS} characters"
    if not payload["script"].strip():
        return "script is empty"
    for key in ("name", "script"):
        try:
            payload[key].encode("utf-8")
        except UnicodeEncodeError:
            return f"{key} contains a character that cannot be stored in a file (half of a surrogate pair)"
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

    return {
        "timeout_seconds": whole("timeout_seconds", DEFAULT_TIMEOUT_SECONDS, 5, MAX_TIMEOUT_SECONDS),
        "memory_mb": whole("memory_mb", DEFAULT_MEMORY_MB, MIN_MEMORY_MB, 65536),
        "parallel_builds": whole("parallel_builds", default_parallel_builds(), 1, MAX_PARALLEL_BUILDS),
    }


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-") or "part"


# --- Deciding ---------------------------------------------------------------


def _close(expected: float, measured: float) -> bool:
    return abs(expected - measured) <= max(LENGTH_TOLERANCE_MM, LENGTH_TOLERANCE_RATIO * abs(expected))


def decide(measured: Mapping[str, Any], payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Compare what was measured on the re-imported STEP with what the part must meet."""
    voids = measured.get("enclosed_voids") or 0
    checks: list[dict[str, Any]] = [
        {
            "check": "one closed solid",
            "expected": "exactly one valid, closed solid",
            "measured": f"{measured['solids']} solid(s), valid={measured['valid']}, closed={measured['closed']}" + (f", {voids} sealed {'cavity' if voids == 1 else 'cavities'} inside" if voids else ""),
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
        check = {"check": "holes", "expected": expected, "measured": found, "passed": len(expected) == len(found) and all(_close(e, m) for e, m in zip(expected, found))}
        # The check compares diameters. A hole that stops inside the part is said, with how deep it goes.
        blind = sorted(hole["depth_mm"] for hole in measured["holes"] if hole.get("through") is False)
        if blind:
            check["blind_depths_mm"] = blind
        checks.append(check)
    return checks


def notes_on(measured: Mapping[str, Any]) -> list[str]:
    """What the checks do not decide and a reader of the answer should still know."""
    notes = []
    if measured.get("unused_outline"):
        notes.append("The script draws an outline that is never extruded or cut; it is not part of the result.")
    voids = measured.get("enclosed_voids") or 0
    if voids:
        notes.append(f"The part has {voids} sealed {'cavity' if voids == 1 else 'cavities'} inside that cannot be reached from outside.")
    tolerance = (measured.get("mesh") or {}).get("tolerance_mm")
    if isinstance(tolerance, (int, float)) and tolerance > MESH_STEPS[0][0]:
        notes.append(f"The STL mesh is coarser than usual ({tolerance:g} mm off the surface at most) to keep the file small; the STEP file is exact.")
    crossing = [hole for hole in measured.get("holes") or [] if isinstance(hole.get("walls"), int) and hole["walls"] > 1]
    if crossing:
        most = max(hole["walls"] for hole in crossing)
        notes.append(f"{len(crossing)} hole{'' if len(crossing) == 1 else 's'} pass{'es' if len(crossing) == 1 else ''} through {most} walls with air between and count{'s' if len(crossing) == 1 else ''} once: one drill pass is one hole.")
    return notes


def unchecked(measured: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    """What was measured and not asked about, under the name of the argument that would check it."""
    extra: dict[str, Any] = {}
    if "volume_min_max_mm3" not in payload:
        extra["volume_mm3"] = measured["volume_mm3"]
    if "hole_diameters_mm" not in payload:
        extra["hole_diameters_mm"] = sorted(hole["diameter_mm"] for hole in measured["holes"])[:MAX_HOLES]
    return extra


# --- Running the worker -----------------------------------------------------


def _prepare(script: str, memory_mb: int, timeout_seconds: int) -> str:
    directory = tempfile.mkdtemp(prefix="deerflow-cad-")
    # The kernel works on several cores at once, so processor time runs ahead of the clock.
    cpu_seconds = timeout_seconds * (os.cpu_count() or 1) + CPU_BACKSTOP_SECONDS
    request = {"script": script, "memory_mb": memory_mb, "max_export_bytes": MAX_EXPORT_BYTES, "cpu_seconds": cpu_seconds}
    try:
        Path(directory, REQUEST_FILE).write_text(json.dumps(request), encoding="utf-8")
    except BaseException:
        shutil.rmtree(directory, True)  # a full disk must not leave one directory per call
        raise
    return directory


class _Preparation:
    """A directory made in a thread for a caller that may be cancelled before it gets the name.

    A cancelled wait does not stop the thread. Whoever comes second removes the
    directory: the thread when the caller has already left, the caller when the
    thread has already finished. Neither depends on the event loop still running.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._abandoned = False
        self._directory: str | None = None

    def make(self, script: str, memory_mb: int, timeout_seconds: int) -> str | None:
        directory = _prepare(script, memory_mb, timeout_seconds)
        with self._lock:
            if not self._abandoned:
                self._directory = directory
                return directory
        shutil.rmtree(directory, True)
        return None

    def abandon(self) -> None:
        with self._lock:
            self._abandoned = True
            directory, self._directory = self._directory, None
        if directory is not None:
            shutil.rmtree(directory, True)


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
    try:
        if os.name == "posix":
            # The worker leads its own session, so this is its whole group, and it is sent
            # even when the worker has already finished: anything it left running goes too.
            # Process ids are handed out in sequence, so the group's id cannot have been
            # given to another process in the instant since the worker was collected.
            os.killpg(process.pid, signal.SIGKILL)
        elif process.returncode is None:
            process.kill()
    except (ProcessLookupError, PermissionError):
        pass


async def _acquire(slots: threading.BoundedSemaphore, wait_seconds: float) -> bool:
    # A thread semaphore polled from the loop: tools may run on more than one event loop.
    deadline = time.monotonic() + wait_seconds
    while not slots.acquire(blocking=False):
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.05)
    return True


async def _clean_up(process: asyncio.subprocess.Process | None, directory: str | None) -> None:
    try:
        if process is not None:
            await process.wait()
    finally:
        if directory is not None:
            await asyncio.to_thread(shutil.rmtree, directory, True)


def _finish(cleaning: asyncio.Future, directory: str | None, slots: threading.BoundedSemaphore | None) -> None:
    """Runs once whatever became of the clean-up task, also when it was cancelled before its first step."""
    if directory is not None and cleaning.cancelled():
        shutil.rmtree(directory, True)  # the loop is ending: there is no thread to hand this to
    if slots is not None:
        slots.release()


def _phase_of(directory: str) -> str:
    try:
        return Path(directory, PHASE_FILE).read_text(encoding="utf-8")[:32]
    except OSError:
        return ""


async def run_worker(script: str, *, timeout_seconds: int, memory_mb: int, slots: threading.BoundedSemaphore | None = None) -> dict[str, Any]:
    """Build *script* in a child interpreter and return its answer, or a failure it could not report itself."""
    if slots is not None and not await _acquire(slots, QUEUE_SECONDS):
        return {"status": "busy", "message": "the server is building other parts right now and has no free slot for this one"}
    process = None
    directory = None
    stopped = False
    try:
        preparation = _Preparation()
        try:
            directory = await asyncio.to_thread(preparation.make, script, memory_mb, timeout_seconds)
        except asyncio.CancelledError:
            preparation.abandon()
            raise
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
            phase = await asyncio.to_thread(_phase_of, directory)
            if phase == "loading":
                # Nothing was built yet, so nothing can be said about the part. The modules Python
                # compiled before it was stopped stay compiled, which is why calling again works.
                return {"status": "loading", "message": "the CAD kernel was still loading when the time ran out. The first build after an install, an update or a restart takes longer."}
            advice = _PHASES.get(phase, "Simplify the part: fewer pattern points, fewer fillets, and hole() instead of circle().cutThruAll() for round holes.")
            return {"status": "failed", "message": f"the build did not finish within {timeout_seconds} seconds and was stopped. {advice}"}
        # At once, before its files are read: whatever the worker left running goes with it.
        _stop(process)
        stopped = True
        result = await asyncio.to_thread(_collect, directory)
        if result.get("status"):
            return result
        reason = f"signal {-code}" if code < 0 else f"exit code {code}"
        return {"status": "failed", "message": f"the CAD kernel stopped without an answer ({reason}); it most likely ran out of memory or processor time. Simplify the part."}
    finally:
        # Also on cancellation: the host's 30 second limit or a stopped run must not leave a kernel
        # running, a script on disk or a slot taken. The kill is not left to a task, because a task
        # cancelled before its first step never runs. The rest is shielded, so a second cancellation
        # leaves it running off the loop; the callback covers a loop that ends first.
        if process is not None and not stopped:
            _stop(process)
        cleaning = asyncio.ensure_future(_clean_up(process, directory))
        cleaning.add_done_callback(lambda done: _finish(done, directory, slots))
        await asyncio.shield(cleaning)


# --- The handler ------------------------------------------------------------


async def _save(context: ToolContext, name: str, content: bytes, saved: list[str], problems: list[str]) -> str | None:
    try:
        path = await context.write_output(name, content)
    except HostCapabilityError as exc:
        size = f"{len(content) / (1024 * 1024):.1f} MB" if len(content) >= 1024 * 1024 else f"{max(1, len(content) // 1024)} KB"
        problems.append(f"{name} ({size}) was not saved ({exc.code})")
        return None
    saved.append(path)
    return path


def make_handler(settings: Mapping[str, int]):
    slots = threading.BoundedSemaphore(settings.get("parallel_builds") or default_parallel_builds())
    # Builds in a row that never got past loading the kernel, by conversation: three people
    # asking at once after a restart are each on their first attempt.
    still_loading: dict[str, int] = {}

    async def cad_build(payload: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
        if context.output_writer is None:
            return {"passed": False, "error": {"message": "This conversation cannot receive files, so no part was built."}, "files": [], "next": "Tell the user; calling cad_build again will not help."}
        problem = _problem_with(payload)
        if problem:
            return {"passed": False, "error": {"message": problem}, "files": [], "next": NEXT_ARGUMENTS}
        script = payload["script"]
        result = await run_worker(script, timeout_seconds=settings["timeout_seconds"], memory_mb=settings["memory_mb"], slots=slots)
        status = result.get("status")
        conversation = str(context.thread_id or "")
        if status == "loading":
            if conversation not in still_loading and len(still_loading) >= MAX_COUNTED_CONVERSATIONS:
                still_loading.clear()
            still_loading[conversation] = still_loading.get(conversation, 0) + 1
            return {"passed": False, "error": {"message": result["message"]}, "files": [], "next": NEXT_NOT_LOADING if still_loading[conversation] >= MAX_LOADING_ANSWERS else NEXT_STILL_LOADING}
        if status == "busy":
            return {"passed": False, "error": {"message": result["message"]}, "files": [], "next": NEXT_BUSY}
        if status != "refused":
            still_loading.pop(conversation, None)  # the kernel loaded, or failed to: either way not "still loading"
        saved: list[str] = []
        problems: list[str] = []
        # The script is saved first: the name the host gives it is this build's stem, so
        # a rebuild of the same part gets plate-1.* as a set instead of a mix.
        script_path = await _save(context, f"{slug(payload['name'])}.py", script.encode("utf-8"), saved, problems)
        if script_path is None:
            # Without the script there is no stem for the set, and files under a guessed one would mix with
            # another build's. What the build itself said still reaches the model: a refusal stays a refusal.
            status = result.get("status")
            error = {key: result[key] for key in ("construct", "line", "operation", "message") if result.get(key) is not None}
            if status == "built":
                error = {"message": "the part was built, but its script could not be stored, so nothing was"}
            return {
                "passed": False,
                "error": error or {"message": "the build failed"},
                "problems": problems,
                "files": [],
                "next": NEXT_NO_FILES if status == "built" else NEXT_UNAVAILABLE if status == "unavailable" else NEXT_FIX,
            }
        stem = Path(script_path).stem
        answer: dict[str, Any] = {"passed": False}
        next_step = NEXT_FIX
        report: dict[str, Any] = {"name": payload["name"], "passed": False, "expected": {key: payload[key] for key in EXPECTATIONS if key in payload}}
        files = result.get("files") or {}
        if result.get("status") == "built":
            checks = decide(result["measured"], payload)
            passed = all(check["passed"] for check in checks)
            answer.update(passed=passed, checks=checks)
            report.update(passed=passed, checks=checks, measured=result["measured"])
            notes = notes_on(result["measured"])
            if notes:
                answer["notes"] = report["notes"] = notes
            extra = unchecked(result["measured"], payload)
            if extra:
                answer["unchecked"] = extra
            if passed:
                # STEP goes last: a STEP file in the outputs means the whole set was handed over.
                for kind in ("glb", "stl", "step"):
                    if kind not in files:
                        problems.append(f"the {kind.upper()} export is missing or larger than {MAX_EXPORT_BYTES // (1024 * 1024)} MiB")
                    elif await _save(context, f"{stem}.{kind}", files[kind], saved, problems) is not None:
                        continue
                    # A part that passed but could not be handed over in full is not presented as delivered.
                    answer["passed"] = report["passed"] = False
                    next_step = NEXT_UNSTORED
                    break
            elif "glb" in files:
                await _save(context, f"{stem}.failed.glb", files["glb"], saved, problems)
        else:
            error = {key: result[key] for key in ("construct", "line", "operation", "message") if result.get(key) is not None}
            answer["error"] = report["error"] = error or {"message": "the build failed"}
            if result.get("status") == "unavailable":
                next_step = NEXT_UNAVAILABLE
        if problems:
            report["problems"] = list(problems)
        await _save(context, f"{stem}.report.json", json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8"), saved, problems)
        if problems:
            answer["problems"] = problems
        answer["files"] = saved
        if not answer["passed"]:
            answer["next"] = next_step
        return answer

    return cad_build
