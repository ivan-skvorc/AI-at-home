"""The ``cad_build`` model tool: build in a child process, decide, hand over the files.

The Gateway process never parses the script and never loads the CAD kernel.
It starts ``worker.py`` in a fresh interpreter with a wall-clock limit, reads
back measured numbers, compares them with what the model said the part must
meet, and writes files through the host (``ToolContext.write_output``).

The tool decides pass or fail, not the model: STEP, STL, 3MF and GLB are
written only when every check passed, so a STEP file listed in a ``cad_build``
answer means a part that passed. A failed build keeps its picture and GLB, named
``.failed``, to look at.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import re
import shutil
import signal
import sys
import tempfile
import threading
import time
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deerflow_extension_api import HostCapabilityError, ToolContext

# The checks live in checks.py, which needs no extension API (the eval and measure_cli use it);
# they are named here too, where the handler and older callers look for them.
from deerflow_extension_cad.checks import MAX_HOLES, MAX_HOLES_LISTED, canonical_holes, decide, notes_on, unchecked

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

# Every character here is paid on every request of every conversation, and a
# small local model gets only the opening sentences within 280 characters (the
# host's short tool form): everything before "Methods:", whose sentence is too
# long to fit. So the opening sentences stand on their own, what a small model
# can do without comes after the method list ("Assign the part to result": the
# reader falls back to the last part assigned), the
# parameter names say what they hold instead of carrying descriptions, and the
# handler checks the values itself (``_problem_with``). The context-fit critical
# check pins the cost (backend/tests/test_context_fit_critical.py).
DESCRIPTION = (
    "Build and check a part from a CadQuery script. It is read, not run: assignments, arithmetic, math, "
    "for loops and allow-listed Workplane methods; no if, while or def. Millimetres. "
    "Methods: box, cylinder, sphere, wedge, rect, circle, ellipse, polygon, slot2D, polyline, "
    "moveTo, move, lineTo, line, hLine, vLine, hLineTo, vLineTo, threePointArc, spline, radiusArc, sagittaArc, tangentArcPoint, "
    "polarLine, polarLineTo, close, center, offset2D, extrude, cutBlind, cutThruAll, revolve, loft, sweep, twistExtrude, text, split, "
    "hole, cboreHole, cskHole, fillet, chamfer, shell, pushPoints, rarray, polarArray, faces, edges, vertices, workplane, transformed, tag, "
    "workplaneFromTagged, end, first, last, translate, rotate, mirror, mirrorX, mirrorY, union, cut, intersect. "
    "bbox_xyz_mm is the expected overall size along x, y and z. volume_min_max_mm3 is the allowed volume range. "
    "hole_diameters_mm lists one diameter, or [d, x, y, z], per expected hole, [] for none. Assign the part to result. "
    "Returns pass or fail per check with the measured values. STEP, STL, GLB and 3MF files are saved only when every check passes."
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
#: No expected number may exceed what a script itself may state.
MAX_EXPECTED = 1e12

#: Builds of one part within one run before the answer says to stop and report. A new script
#: usually spends one or two on a refusal, so this leaves five or six for the geometry.
MAX_ATTEMPTS = 8
#: Parts whose builds are counted. An entry is a few hundred bytes; the cap only keeps the table from growing for ever.
MAX_COUNTED_PARTS = 1000
#: What the worker may say about a script it refused or a build that failed, passed on as it is.
_ERROR_KEYS = ("construct", "refused", "line", "operation", "message")
#: Notes from the worker an answer passes on ("no picture: ..."), and how long each may be.
MAX_WORKER_NOTES = 5
MAX_WORKER_NOTE_CHARS = 300

NEXT_FIX = "Attempt {attempt} of {limit}. Read what failed, change the script and call cad_build again with the same name. Keep the expected numbers: change one only if it was worked out wrongly. Do not present this part as finished."
#: For a build whose script could not be stored: without its files it is not one of the part's attempts.
NEXT_FIX_UNSTORED = "Fix the script and call cad_build again. Do not present this part as finished."
NEXT_SAME = " This is the same failure as the attempt before, so that change did not reach its cause: change something else."
#: "The last one did not pass": an earlier build of the run may have, and its files stand.
NEXT_STOP = (
    "{attempt} builds of this part in this run and the last one did not pass. Stop building. Tell the user what still fails, with the measured numbers, "
    "and what you would change next. Do not present this part as finished; build again only when the user asks."
)
#: For a result of several bodies. No change of one kind passes it, so both ways out are said in the field a model follows.
NEXT_LOOSE = (
    "Attempt {attempt} of {limit}. The result is several separate bodies and cad_build delivers one solid. If they are meant to be one part, "
    "make them overlap or share a face and call cad_build again with the same name. If the design is loose bodies, such as a print-in-place hinge, "
    "stop: tell the user that this tool cannot deliver it. Do not present this part as finished."
)
NEXT_REVIEW = "Every check passed. Before you present the part, go through what the user asked for that these numbers do not cover; if something is missing or wrong, change the script and build again."
NEXT_PRESENT = "Every check passed. Present the part, and say which of the user's requirements these numbers do not cover."
#: After either sentence of a pass, when the part's picture was saved. Viewed once, at review: the numbers decide.
NEXT_PICTURE = " Show {picture} in your reply; if you can view images, look at it once and compare it with the request."
NEXT_CHANGED = " The expected numbers are not the ones this part was first built against (expected_changed): they stand for what the user asked for, so tell the user which changed and why."
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
    # Only when the answer written before this step cannot be read: otherwise run_worker returns it.
    "rendering": "The part was built and checked, and drawing its picture did not finish in time. Simplify the part: fewer small fillets and holes.",
    "checking print": "The part was built and checked, and checking how it prints did not finish in time. Simplify the part: fewer small fillets and holes.",
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
    if "hole_diameters_mm" in payload:
        holes = payload["hole_diameters_mm"]

        def hole(entry: Any) -> bool:
            # A diameter, or a diameter and a point on the hole's axis: [d, x, y, z].
            point = entry if isinstance(entry, (list, tuple)) and len(entry) == 4 else [entry]
            return all(type(number) in (int, float) and abs(number) <= MAX_EXPECTED for number in point) and point[0] > 0

        if not isinstance(holes, (list, tuple)) or len(holes) > MAX_HOLES or not all(hole(entry) for entry in holes):
            return f"hole_diameters_mm must list one positive diameter, or [d, x, y, z], per expected hole, at most {MAX_HOLES}"
    return None


#: The operator's printer (``printer:`` in the CAD record's config), for the print block and its notes.
#: Defaults for a common 0.4 mm nozzle printing PLA. No build volume means no fit note.
PRINTER_DEFAULTS: dict[str, float] = {"nozzle_mm": 0.4, "layer_mm": 0.2, "overhang_deg": 45.0, "min_clearance_mm": 0.3, "density_g_cm3": 1.24}
PRINTER_RANGES: dict[str, tuple[float, float]] = {"nozzle_mm": (0.1, 2.0), "layer_mm": (0.02, 1.0), "overhang_deg": (10.0, 80.0), "min_clearance_mm": (0.05, 3.0), "density_g_cm3": (0.5, 20.0)}
BUILD_VOLUME_RANGE_MM = (10.0, 5000.0)


def printer_from(config: Mapping[str, Any]) -> dict[str, Any]:
    """The printer profile from the CAD record's config: every value bounded, and an error names its key.

    It is operator configuration in config.yaml, which no API writes, and it costs no tokens: the
    model sees only notes that name the value they compared against.
    """
    given = config.get("printer")
    if given is None:
        given = {}  # `printer:` with every value commented out
    if not isinstance(given, Mapping):
        raise ValueError("cad: printer must be a mapping of printer values, such as nozzle_mm: 0.4")
    known = ("build_volume_mm", *PRINTER_DEFAULTS)
    unknown = sorted(str(key) for key in given if key not in known)
    if unknown:
        # A misspelled value would otherwise be a default the operator thinks they changed.
        raise ValueError(f"cad: printer.{unknown[0]} is not a printer value; printer takes {', '.join(known)}")

    def number(value: Any, low: float, high: float) -> bool:
        return type(value) in (int, float) and math.isfinite(value) and low <= value <= high

    profile: dict[str, Any] = {"build_volume_mm": None}
    volume = given.get("build_volume_mm")
    if volume is not None:
        low, high = BUILD_VOLUME_RANGE_MM
        if not (isinstance(volume, (list, tuple)) and len(volume) == 3 and all(number(side, low, high) for side in volume)):
            raise ValueError(f"cad: printer.build_volume_mm must be three numbers from {low:g} to {high:g}: the bed's x and y and the height, in millimetres")
        profile["build_volume_mm"] = [float(side) for side in volume]
    for key, default in PRINTER_DEFAULTS.items():
        value = given.get(key, default)
        low, high = PRINTER_RANGES[key]
        if not number(value, low, high):
            raise ValueError(f"cad: printer.{key} must be a number from {low:g} to {high:g}")
        profile[key] = float(value)
    return profile


def settings_from(config: Mapping[str, Any]) -> dict[str, Any]:
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
        "printer": printer_from(config),
    }


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-") or "part"


def part_key(name: str) -> str:
    """One part, however its name is typed between attempts: case, width, spacing and invisible characters aside.

    Everything else is kept, signs and punctuation included: two parts told apart by
    "+0.1" and "-0.1" must not share a count, and a model that is told to keep the name
    keeps its punctuation. Not the file stem either: that is ASCII and cut at forty
    characters, so every name without a Latin letter would be the same part.
    """
    visible = "".join(character for character in unicodedata.normalize("NFKC", name).casefold() if unicodedata.category(character) != "Cf")
    return " ".join(visible.split()) or name


def _parameters_of(result: Mapping[str, Any]) -> dict[str, int | float]:
    """The script's starting numbers as the worker read them: names and numbers only, nothing else it sends."""
    parameters = result.get("parameters")
    if not isinstance(parameters, Mapping):
        return {}
    return {name: value for name, value in parameters.items() if isinstance(name, str) and type(value) in (int, float)}


def _worker_notes(result: Mapping[str, Any]) -> list[str]:
    """What the worker says about the steps after the checks ("no picture: ..."): sentences only, bounded."""
    notes = result.get("notes")
    if not isinstance(notes, list):
        return []
    return [note[:MAX_WORKER_NOTE_CHARS] for note in notes if isinstance(note, str) and note][:MAX_WORKER_NOTES]


#: The print block's numbers an answer carries; report.json keeps the whole block.
_PRINT_SAID = ("grams", "bed_contact_mm2", "overhang_mm2", "thinnest_wall_mm")


def print_block(measured: Mapping[str, Any]) -> dict[str, Any] | None:
    """The print block as an answer carries it: four numbers, the fit when there is a bed to fit, and the notes."""
    block = measured.get("print")
    if not isinstance(block, Mapping):
        return None
    said: dict[str, Any] = {key: _short(block[key]) for key in _PRINT_SAID if type(block.get(key)) in (int, float)}
    if isinstance(block.get("fits_build_volume"), bool):
        said["fits_build_volume"] = block["fits_build_volume"]
    notes = _worker_notes(block)
    if notes:
        said["notes"] = notes
    return said or None


def _short(value: Any) -> Any:
    """A number as an answer prints it: a whole number without its '.0', which is a token saved per number."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def listed_holes(measured: Mapping[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """The holes an answer lists, with where each is entered and which way it runs, and how many have a position."""
    located = [hole for hole in measured.get("holes") or [] if isinstance(hole, Mapping) and isinstance(hole.get("at"), list) and isinstance(hole.get("axis"), list)]
    listed = [{"d": _short(hole["diameter_mm"]), "at": [_short(value) for value in hole["at"]], "axis": [_short(value) for value in hole["axis"]]} for hole in located[:MAX_HOLES_LISTED]]
    return listed, len(located)


def provenance() -> dict[str, str | None]:
    """What made a report: this module's release and the kernel's, read from the installed metadata, never by importing the kernel."""
    found: dict[str, str | None] = {}
    for key, distribution in (("module_version", "deerflow-extension-cad"), ("cadquery_version", "cadquery")):
        try:
            found[key] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            found[key] = None
    return found


def report_text(report: Mapping[str, Any]) -> str:
    """report.json as text: a key per line in the outer two levels and one record per line in a list of records.

    A part with hundreds of holes stays a file of tens of kilobytes this way; indenting every
    number of every hole's point and axis doubled it.
    """

    def compact(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def block(value: Any, depth: int) -> str:
        pad, end = "  " * (depth + 1), "  " * depth
        if isinstance(value, Mapping) and value and depth < 2:
            return "{\n" + ",\n".join(f"{pad}{compact(key)}: {block(item, depth + 1)}" for key, item in value.items()) + "\n" + end + "}"
        if isinstance(value, list) and value and all(isinstance(item, Mapping) for item in value):
            return "[\n" + ",\n".join(pad + compact(item) for item in value) + "\n" + end + "]"
        return compact(value)

    return block(report, 0) + "\n"


# --- Counting the attempts ---------------------------------------------------


class Attempts:
    """Builds of each part, by conversation: how many this run, and the numbers the first one was held to.

    The agent runs the loop, build, read, repair, build again. This keeps what a model
    loses over a long one: the count, so the loop ends in a report and not in a run
    limit; the first expected numbers, so a part cannot pass by moving them unsaid; and
    the last failure, so a change that did nothing is said to have done nothing.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._parts: dict[tuple[str, str], dict[str, Any]] = {}

    def record(self, conversation: str, part: str, run: str | None, expected: Mapping[str, Any], passed: bool, failure: str) -> tuple[int, dict[str, Any], bool]:
        """Count one build. Returns its number in this run, the expected numbers that changed, and whether it failed as the last one did."""
        key = (conversation, part)
        # The holes are checked in any order and printed sorted, so they are held sorted.
        expected = {name: canonical_holes(value) if name == "hole_diameters_mm" else list(value) for name, value in expected.items()}
        with self._lock:
            # Taken out and put back last: the table is kept in the order parts were last built.
            entry = self._parts.pop(key, None)
            # A new run is the user speaking again: the count starts over. What the part is held
            # to starts over only after a pass, because "keep going" does not change the request.
            # A host that stamps no run cannot tell runs apart, so there a pass ends the count.
            if entry is None or (entry["run"] != run if run is not None else entry["passed"]):
                first = dict(expected) if entry is None or entry["passed"] else entry["first"]
                entry = {"run": run, "builds": 0, "first": first, "failure": None, "passed": False}
            while len(self._parts) >= MAX_COUNTED_PARTS:
                # The part built longest ago makes room, not every loop in progress.
                del self._parts[next(iter(self._parts))]
            self._parts[key] = entry
            entry["builds"] += 1
            same = not passed and failure == entry["failure"]
            entry["failure"] = None if passed else failure
            entry["passed"] = passed
            # A check added later makes the part harder to pass, not easier: it is held from then on and not reported.
            entry["first"].update({name: expected[name] for name in expected if name not in entry["first"]})
            # Compared exactly: a tolerance here would let a band move by a feature's worth without a word.
            changed = {name: {"first": entry["first"][name], "now": expected.get(name)} for name in EXPECTATIONS if name in entry["first"] and entry["first"][name] != expected.get(name)}
            return entry["builds"], changed, same


def _next_after(passed: bool, attempt: int, changed: Mapping[str, Any], same: bool, loose: bool) -> str:
    if passed:
        step = NEXT_REVIEW if attempt < MAX_ATTEMPTS else NEXT_PRESENT
    elif attempt >= MAX_ATTEMPTS:
        step = NEXT_STOP.format(attempt=attempt)
    elif loose:
        step = NEXT_LOOSE.format(attempt=attempt, limit=MAX_ATTEMPTS)
    else:
        step = NEXT_FIX.format(attempt=attempt, limit=MAX_ATTEMPTS) + (NEXT_SAME if same else "")
    return step + (NEXT_CHANGED if changed else "")


# --- Running the worker -----------------------------------------------------


#: The worker's steps after the checks, in order, and the note for each one a timeout leaves out.
_AFTER_THE_CHECKS = {"rendering": "no picture: the build used most of its time", "checking print": "no print check: the build used most of its time"}


def _prepare(script: str, memory_mb: int, timeout_seconds: int, extra: Mapping[str, Any] | None = None) -> str:
    directory = tempfile.mkdtemp(prefix="deerflow-cad-")
    # The kernel works on several cores at once, so processor time runs ahead of the clock.
    cpu_seconds = timeout_seconds * (os.cpu_count() or 1) + CPU_BACKSTOP_SECONDS
    # The wall clock too, so the worker can leave out a step after the checks that would not finish in it.
    request = {"script": script, "memory_mb": memory_mb, "max_export_bytes": MAX_EXPORT_BYTES, "cpu_seconds": cpu_seconds, "budget_seconds": timeout_seconds, **(extra or {})}
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

    def make(self, script: str, memory_mb: int, timeout_seconds: int, extra: Mapping[str, Any] | None = None) -> str | None:
        directory = _prepare(script, memory_mb, timeout_seconds, extra)
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


async def run_worker(
    script: str,
    *,
    timeout_seconds: int,
    memory_mb: int,
    slots: threading.BoundedSemaphore | None = None,
    expected: Mapping[str, Any] | None = None,
    printer: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build *script* in a child interpreter and return its answer, or a failure it could not report itself.

    *expected* is what the part must meet; the worker draws a failed part's picture with the checks it did
    not pass. *printer* is the operator's printer profile, which the print check measures against.
    """
    if slots is not None and not await _acquire(slots, QUEUE_SECONDS):
        return {"status": "busy", "message": "the server is building other parts right now and has no free slot for this one"}
    process = None
    directory = None
    stopped = False
    try:
        preparation = _Preparation()
        try:
            extra = {key: dict(value) for key, value in (("expected", expected), ("printer", printer)) if value is not None} or None
            directory = await asyncio.to_thread(preparation.make, script, memory_mb, timeout_seconds, extra)
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
            if phase in _AFTER_THE_CHECKS:
                # The checked part was answered before this step began. It stands, without what the step adds.
                _stop(process)
                stopped = True
                result = await asyncio.to_thread(_collect, directory)
                if result.get("status") == "built":
                    steps = list(_AFTER_THE_CHECKS)
                    left_out = [_AFTER_THE_CHECKS[step] for step in steps[steps.index(phase) :]]
                    result["notes"] = [note for note in result.get("notes") or [] if isinstance(note, str)] + left_out
                    return result
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


def make_handler(settings: Mapping[str, Any]):
    slots = threading.BoundedSemaphore(settings.get("parallel_builds") or default_parallel_builds())
    printer = settings.get("printer") or printer_from({})
    # Read once, when the module is installed: every report names the code that made it.
    made_by = provenance()
    # Builds in a row that never got past loading the kernel, by conversation: three people
    # asking at once after a restart are each on their first attempt.
    still_loading: dict[str, int] = {}
    attempts = Attempts()

    async def cad_build(payload: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
        if context.output_writer is None:
            return {"passed": False, "error": {"message": "This conversation cannot receive files, so no part was built."}, "files": [], "next": "Tell the user; calling cad_build again will not help."}
        problem = _problem_with(payload)
        if problem:
            return {"passed": False, "error": {"message": problem}, "files": [], "next": NEXT_ARGUMENTS}
        script = payload["script"]
        expected = {key: payload[key] for key in EXPECTATIONS if key in payload}
        result = await run_worker(script, timeout_seconds=settings["timeout_seconds"], memory_mb=settings["memory_mb"], slots=slots, expected=expected, printer=printer)
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
            error = {key: result[key] for key in _ERROR_KEYS if result.get(key) is not None}
            if status == "built":
                error = {"message": "the part was built, but its script could not be stored, so nothing was"}
            return {
                "passed": False,
                "error": error or {"message": "the build failed"},
                "problems": problems,
                "files": [],
                "next": NEXT_NO_FILES if status == "built" else NEXT_UNAVAILABLE if status == "unavailable" else NEXT_FIX_UNSTORED,
            }
        stem = Path(script_path).stem
        answer: dict[str, Any] = {"passed": False}
        # None while the build's own outcome decides what comes next; a sentence when something else does.
        next_step: str | None = None
        picture: str | None = None
        report: dict[str, Any] = {"name": payload["name"], "passed": False, "expected": expected, **made_by, "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest()}
        parameters = _parameters_of(result)
        if parameters:
            # The numbers the script starts with, for a follow-up edit. The model has them in its script already.
            report["parameters"] = parameters
        failure = ""
        files = result.get("files") or {}
        if result.get("status") == "built":
            checks = decide(result["measured"], payload)
            passed = all(check["passed"] for check in checks)
            answer.update(passed=passed, checks=checks)
            report.update(passed=passed, checks=checks, measured=result["measured"])
            # A hole moved but still not where it belongs is a different failure, not the same one.
            failure = json.dumps([[check["check"], check["measured"], *([check["misplaced"]] if "misplaced" in check else [])] for check in checks if not check["passed"]], sort_keys=True, default=str)
            notes = notes_on(result["measured"])
            extra = unchecked(result["measured"], payload)
            if extra:
                answer["unchecked"] = extra
            listed, located = listed_holes(result["measured"])
            if listed:
                answer["holes"] = listed
                if located > len(listed):
                    notes.append(f"The answer lists {len(listed)} of the {located} holes; {stem}.report.json lists every hole with where it is.")
            notes += _worker_notes(result)
            if notes:
                answer["notes"] = report["notes"] = notes
            if passed:
                printing = print_block(result["measured"])
                if printing:
                    # Reported, never checked: the block cannot change pass or fail.
                    answer["print"] = printing
                # The picture first: it is what a reader looks at, and a picture the host refuses is a problem, not a lost part.
                if "png" in files:
                    picture = await _save(context, f"{stem}.png", files["png"], saved, problems)
                # STEP goes last: a STEP file in the outputs means the whole set was handed over. The 3MF is
                # part of the set when the worker wrote one (it always does since item 54).
                for kind in ("glb", "stl", *(("3mf",) if "3mf" in files else ()), "step"):
                    if kind not in files:
                        problems.append(f"the {kind.upper()} export is missing or larger than {MAX_EXPORT_BYTES // (1024 * 1024)} MiB")
                    elif await _save(context, f"{stem}.{kind}", files[kind], saved, problems) is not None:
                        continue
                    # A part that passed but could not be handed over in full is not presented as delivered.
                    answer["passed"] = report["passed"] = False
                    next_step = NEXT_UNSTORED
                    break
            else:
                for kind in ("png", "glb"):
                    if kind in files:
                        await _save(context, f"{stem}.failed.{kind}", files[kind], saved, problems)
        else:
            error = {key: result[key] for key in _ERROR_KEYS if result.get(key) is not None}
            answer["error"] = report["error"] = error or {"message": "the build failed"}
            failure = json.dumps(answer["error"], sort_keys=True, default=str)
            if result.get("status") == "unavailable":
                next_step = NEXT_UNAVAILABLE
        if next_step is None:
            # A build the script answers for: counted, and held to the numbers the part started with.
            attempt, changed, same = attempts.record(conversation, part_key(payload["name"]), context.run_id, expected, answer["passed"], failure)
            answer["attempt"] = report["attempt"] = attempt
            if changed:
                answer["expected_changed"] = report["expected_changed"] = changed
            solids = (result.get("measured") or {}).get("solids")
            next_step = _next_after(answer["passed"], attempt, changed, same, isinstance(solids, int) and solids > 1)
            if answer["passed"] and picture is not None:
                next_step += NEXT_PICTURE.format(picture=picture)
        if problems:
            report["problems"] = list(problems)
        # The set as stored, for whoever reads the report later: the eval finds the delivered part this way.
        report["files"] = [Path(path).name for path in saved]
        await _save(context, f"{stem}.report.json", report_text(report).encode("utf-8"), saved, problems)
        if problems:
            answer["problems"] = problems
        answer["files"] = saved
        answer["next"] = next_step
        return answer

    return cad_build
