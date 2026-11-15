"""The child process: read one script, build it, measure it, answer in a file.

Started by ``tool.run_worker`` as ``python -I worker.py`` in an empty temporary
directory. It reads ``request.json`` and writes ``result.json`` plus the
exported files there; standard input and output are closed. The parent holds
the wall clock and kills the process group, because a kernel operation in
progress cannot be interrupted from inside.

The script is checked before the kernel is imported, so a refusal costs a
fraction of a second and no geometry.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REQUEST_FILE = "request.json"
RESULT_FILE = "result.json"
PHASE_FILE = "phase"


def _phase(name: str) -> None:
    # Read by the parent only when it stops this process, to say which step ran out of time.
    Path(PHASE_FILE).write_text(name, encoding="utf-8")


def _answer(value: dict) -> None:
    # Written beside and renamed: the parent never reads half an answer.
    Path(RESULT_FILE + ".part").write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
    os.replace(RESULT_FILE + ".part", RESULT_FILE)


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
        _answer({"status": "refused", "construct": refused.construct, "line": refused.line, "message": refused.message})
        return

    try:
        _phase("loading")  # seconds on a warm machine; far longer the first time after an install
        import cadquery as cq

        from deerflow_extension_cad import build, measure
    except Exception as exc:
        # A missing system library arrives here as "libGL.so.1: cannot open shared object file".
        _answer({"status": "unavailable", "message": f"the CAD kernel could not be loaded: {exc}"})
        return

    try:
        _phase("building")
        part = build.run_program(program, cq)
        _phase("exporting")
        files, mesh = build.export(build.solid_of(part), cq, Path.cwd(), max_export_bytes)
        _phase("measuring")
        measured = measure.measure_step(Path(files["step"]), cq)
        measured["mesh"] = mesh
        if build.unused_outline(part):
            measured["unused_outline"] = True
    except build.BuildFailed as failed:
        _answer({"status": "failed", "line": failed.line, "operation": failed.operation, "message": failed.message})
        return
    except MemoryError:
        _answer({"status": "failed", "message": "the kernel ran out of memory building this part"})
        return
    _answer({"status": "built", "measured": measured, "files": files})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # A fault of this module or an error the kernel raised outside a build step.
        # Said as what it is: without an answer the parent can only guess at memory.
        _answer({"status": "failed", "message": f"the CAD module could not finish this part ({type(exc).__name__}: {str(exc)[:200]}). Try building the same shape another way."})
