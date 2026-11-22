"""The child process: read one script, build it, measure it, answer in a file.

Started by ``tool.run_worker`` as ``python -I worker.py`` in an empty temporary
directory. It reads ``request.json`` and writes ``result.json`` plus the
exported files there; standard input and output are closed. The parent holds
the wall clock and kills the process group, because a kernel operation in
progress cannot be interrupted from inside.

The script is checked before the kernel is imported, so a refusal costs a
fraction of a second and no geometry.

Once the part is measured, the answer is written at once: that is the checked
part. What follows adds to it and may be cut short without costing it: the
picture (``render.py``) and the print block (``printability.py``). Each such
step is skipped with a note when less than ``MIN_SECONDS_LEFT`` of the build's
wall clock remains, and a failure inside one becomes a note, never a failed
build. After each step the answer is written again with what it added.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

#: When this process started, as near as it can tell: the parent's wall clock started a moment earlier.
_STARTED = time.monotonic()

REQUEST_FILE = "request.json"
RESULT_FILE = "result.json"
#: Lines of bodies and of loops left out of the result that an answer names; the counts are said in full.
MAX_UNUSED_SAID = 5
PHASE_FILE = "phase"
#: A step after the checks starts only with this much of the wall clock left. Drawing the largest
#: mesh takes about a second, and a step the parent kills mid-way adds nothing.
MIN_SECONDS_LEFT = 3.0
#: Why a step after the checks was left out when the clock was short.
OUT_OF_TIME = "the build used most of its time"


def _phase(name: str) -> None:
    # Read by the parent only when it stops this process, to say which step ran out of time.
    Path(PHASE_FILE).write_text(name, encoding="utf-8")


def _answer(value: dict) -> None:
    # Written beside and renamed: the parent never reads half an answer.
    Path(RESULT_FILE + ".part").write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
    os.replace(RESULT_FILE + ".part", RESULT_FILE)


def _reason(exc: BaseException) -> str:
    return " ".join(str(exc).split())[:200] or type(exc).__name__


def _seconds_left(request: dict) -> float:
    budget = request.get("budget_seconds")
    return float(budget) - (time.monotonic() - _STARTED) if isinstance(budget, (int, float)) else float("inf")


def _failed_checks(measured: dict, expected) -> list[str] | None:
    """The checks a part did not pass, for the picture's banner; None when it passed or nothing was expected."""
    if not isinstance(expected, dict):
        return None
    from deerflow_extension_cad import checks

    failed = [check["check"] for check in checks.decide(measured, expected) if not check["passed"]]
    return failed or None


def _picture(request: dict, answer: dict, notes: list[str]) -> None:
    """Draw the part from the STL it was exported as; a note instead of a picture when that cannot be done."""
    if _seconds_left(request) < MIN_SECONDS_LEFT:
        notes.append(f"no picture: {OUT_OF_TIME}")
        return
    measured, files = answer["measured"], answer["files"]
    try:
        from deerflow_extension_cad import render

        png = render.render_views(Path(files["stl"]).read_bytes(), measured["bbox_mm"], failed_checks=_failed_checks(measured, request.get("expected")))
        Path("part.png").write_bytes(png)
    except Exception as exc:
        notes.append(f"no picture: {_reason(exc)}")
        return
    files["png"] = "part.png"


def _print_check(request: dict, answer: dict, notes: list[str]) -> None:
    """How the part would print on the operator's printer, read off the STL; reported, never checked."""
    printer = request.get("printer")
    if not isinstance(printer, dict):
        return  # nothing to measure against
    if _seconds_left(request) < MIN_SECONDS_LEFT:
        notes.append(f"no print check: {OUT_OF_TIME}")
        return
    measured = answer["measured"]
    try:
        from deerflow_extension_cad import printability

        triangles = printability.read_stl(Path(answer["files"]["stl"]).read_bytes())
        # The thinnest wall is printability's own estimate on the STL: no clock, the same answer for the same file.
        block = printability.assess(triangles, overhang_deg=printer["overhang_deg"], build_volume_mm=printer.get("build_volume_mm"), density_g_cm3=printer["density_g_cm3"], volume_mm3=measured["volume_mm3"])
        said = printability.notes(block, nozzle_mm=printer["nozzle_mm"])
    except Exception as exc:
        notes.append(f"no print check: {_reason(exc)}")
        return
    if said:
        block["notes"] = said
    measured["print"] = block


def _limit(memory_mb: int, max_export_bytes: int, cpu_seconds: int) -> None:
    """Ceilings the operating system enforces, where it offers them. The parent's clock works everywhere.

    A kernel operation holds the interpreter for its whole duration, so no Python
    timer or signal handler can stop one; only the parent's kill and these limits can.
    """
    try:
        import resource
    except ImportError:  # Windows
        return
    for name, value in (("RLIMIT_AS", memory_mb * 1024 * 1024), ("RLIMIT_FSIZE", max_export_bytes), ("RLIMIT_CPU", cpu_seconds), ("RLIMIT_CORE", 0)):
        limit = getattr(resource, name, None)
        if limit is None:
            continue
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            pass  # a host that forbids lowering the limit keeps its own


def main() -> None:
    # -I leaves this file's directory off sys.path; the package is one level up.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    request = json.loads(Path(REQUEST_FILE).read_text(encoding="utf-8"))
    max_export_bytes = int(request["max_export_bytes"])
    # One byte over the cap: a file the operating system cuts off is then over it, not exactly at it.
    _limit(int(request["memory_mb"]), max_export_bytes + 1, int(request["cpu_seconds"]))

    from deerflow_extension_cad.interpreter import ScriptRefused, compile_script

    try:
        program = compile_script(request["script"])
    except ScriptRefused as refused:
        _answer({"status": "refused", "construct": refused.construct, "refused": refused.name, "line": refused.line, "message": refused.message})
        return
    # The numbers the script starts with, for report.json; tool.py copies names and numbers only.
    parameters = dict(program.parameters)

    try:
        _phase("loading")  # two seconds when the libraries are in the disk cache, far longer when they are not
        import cadquery as cq

        from deerflow_extension_cad import build, measure
    except Exception as exc:
        # A missing system library arrives here as "libGL.so.1: cannot open shared object file".
        _answer({"status": "unavailable", "message": f"the CAD kernel could not be loaded: {exc}"})
        return

    try:
        _phase("building")
        parts = build.build_parts(program, cq)
        part = parts[program.result]
        _phase("exporting")
        files, mesh = build.export(build.solid_of(part), cq, Path.cwd(), max_export_bytes)
        _phase("measuring")
        measured = measure.measure_step(Path(files["step"]), cq)
        measured["mesh"] = mesh
        if build.unused_outline(part):
            measured["unused_outline"] = True
        bodies, passes = build.left_out(program, parts)
        if bodies:
            measured["unused_bodies"] = len(bodies)
            # One more than an answer names, so it can say that there are more.
            measured["unused_body_lines"] = sorted(set(bodies))[: MAX_UNUSED_SAID + 1]
        if passes:
            measured["dropped_passes"] = [{"loop_line": line, "passes": count} for line, count in passes.items()][: MAX_UNUSED_SAID + 1]
        # Every count, for report.json; the answer names only the fillets and chamfers that took more than a selector usually means.
        selected = build.selections(program, parts, cq)
        if selected:
            measured["selections"] = selected
    except build.BuildFailed as failed:
        _answer({"status": "failed", "line": failed.line, "operation": failed.operation, "message": failed.message, "parameters": parameters})
        return
    except MemoryError:
        _answer({"status": "failed", "message": "the kernel ran out of memory building this part"})
        return
    answer = {"status": "built", "measured": measured, "files": files, "parameters": parameters}
    notes: list[str] = []
    if measured.get("solids", 0) > 1 and not any(kind == "parts.3mf" or kind.startswith("body-") for kind in files):
        notes.append("no laid-out 3MF: the bodies could not be written apart; the .3mf holds them as modelled")
    if notes:
        answer["notes"] = notes
    # The checked part, before anything that may run out of time: the parent falls back on it.
    _answer(answer)
    answer["notes"] = notes
    try:
        _phase("rendering")
        _picture(request, answer, notes)
        _answer(answer)
        _phase("checking print")
        _print_check(request, answer, notes)
        _answer(answer)
    except Exception:
        # Not even the answer could be written again (a full disk): the one above stands, and
        # nothing after the checks may turn a checked part into a failed build.
        return


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # A fault of this module or an error the kernel raised outside a build step.
        # Said as what it is: without an answer the parent can only guess at memory.
        _answer({"status": "failed", "message": f"the CAD module could not finish this part ({type(exc).__name__}: {str(exc)[:200]}). Try building the same shape another way."})
