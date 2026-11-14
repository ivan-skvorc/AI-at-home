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
    _limit(int(request["memory_mb"]), int(request["max_export_bytes"]), int(request["cpu_seconds"]))

    from deerflow_extension_cad.interpreter import ScriptRefused, compile_script

    try:
        program = compile_script(request["script"])
    except ScriptRefused as refused:
        _answer({"status": "refused", "construct": refused.construct, "line": refused.line, "message": refused.message})
        return

    try:
        import cadquery as cq

        from deerflow_extension_cad import build, measure
    except Exception as exc:
        # A missing system library arrives here as "libGL.so.1: cannot open shared object file".
        _answer({"status": "unavailable", "message": f"the CAD kernel could not be loaded: {exc}"})
        return

    try:
        shape = build.solid_of(build.run_program(program, cq))
        files = build.export(shape, cq, Path.cwd())
        measured = measure.measure_step(Path(files["step"]), cq)
    except build.BuildFailed as failed:
        _answer({"status": "failed", "line": failed.line, "operation": failed.operation, "message": failed.message})
        return
    except MemoryError:
        _answer({"status": "failed", "message": "the kernel ran out of memory building this part"})
        return
    _answer({"status": "built", "measured": measured, "files": files})


if __name__ == "__main__":
    main()
