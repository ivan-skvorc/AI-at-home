"""Measure one STEP file the way ``cad_build`` measures a part, outside the Gateway.

    python -I -m deerflow_extension_cad.measure_cli <part.step> [truth.json]

Standard output carries one JSON object and nothing else:

- ``measured``: what ``measure.measure_step`` reports, the dict ``cad_build``
  decides on and stores as ``measured`` in its ``.report.json``;
- with *truth.json*: ``expected`` (the file's object as given), ``checks``
  (``checks.decide()``'s list, as in the tool's answer) and ``passed``;
- ``notes``, when the checks have any: ``notes_on()`` for the bodies expected,
  and the smallest gap between bodies (the tool adds its printer's clearance
  notes to that; this program has no printer profile).

*truth.json* holds an object with the expected numbers under the names the tool
takes them: ``bbox_xyz_mm`` (required), ``volume_min_max_mm3``,
``hole_diameters_mm`` (a diameter, or ``[d, x, y, z]`` for a hole whose axis
passes through that point) and ``bodies`` (1 when not given). The checks read
what they know and ignore other keys.

Exit status: 0 when the report is printed and every check passed, or no truth
was given; 1 when a check failed; 2 when nothing could be judged (bad
arguments, an unreadable file, a kernel that does not load), and the object is
then ``{"error": {"message": ...}}``.

The measurement runs under the worker's ceilings (``worker._limit``), and what
the kernel prints goes to standard error. As with the worker, the caller holds
the wall clock and kills the process. Importing this module loads neither the
kernel, nor the extension API, nor anything of the Gateway: the CAD eval scores
every part with it as a program, and a container route can run it the same way.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from deerflow_extension_cad import checks
from deerflow_extension_cad.worker import _limit

USAGE = "usage: python -I -m deerflow_extension_cad.measure_cli <part.step> [truth.json]"
#: ``tool.MAX_BODIES``, repeated because tool.py needs the extension API, which this program does without.
MAX_BODIES = 20
#: The worker's default ceiling (``tool.DEFAULT_MEMORY_MB``): the kernel needs about 1 GiB just to load.
MEMORY_MB = 4096
#: Processor seconds: a part with hundreds of holes measures in a few.
CPU_SECONDS = 120
#: The process writes no file; this bounds the answer when standard output is one.
MAX_OUTPUT_BYTES = 16 * 1024 * 1024


class Refused(Exception):
    """Nothing can be judged: said in the answer's ``error``."""


def _truth(path: Path) -> dict[str, Any]:
    try:
        truth = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"the truth file {path.name} could not be read as JSON ({type(exc).__name__})") from None
    return _usable(truth)


def _usable(truth: Any) -> dict[str, Any]:
    """*truth* when the checks can judge against it; otherwise why not, as a refusal."""
    if not isinstance(truth, Mapping):
        raise Refused('the truth file must hold a JSON object of expected numbers, such as {"bbox_xyz_mm": [60, 40, 6]}')
    box = truth.get("bbox_xyz_mm")
    if not (isinstance(box, list) and len(box) == 3 and all(type(side) in (int, float) for side in box)):
        raise Refused("the truth file needs bbox_xyz_mm: three numbers, the expected size along x, y and z in millimetres")
    bodies = truth.get("bodies", 1)
    if type(bodies) is not int or not 1 <= bodies <= MAX_BODIES:
        raise Refused(f"bodies, when given, is a whole number from 1 to {MAX_BODIES}: how many separate solids the part is")
    return dict(truth)


def report(step: Path, truth: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Measure the STEP at *step* and, given *truth*, judge it as ``cad_build`` would. Loads the kernel."""
    if truth is not None:
        truth = _usable(truth)
    import cadquery as cq

    from deerflow_extension_cad import measure

    measured = measure.measure_step(Path(step), cq)
    answer: dict[str, Any] = {"measured": measured}
    if truth is not None:
        try:
            verdict = checks.decide(measured, truth)
        except (TypeError, ValueError, KeyError, IndexError) as exc:
            raise Refused(f"the truth file does not fit the checks ({type(exc).__name__}: {str(exc)[:200]})") from None
        answer.update(expected=truth, checks=verdict, passed=all(check["passed"] for check in verdict))
    # The tool's notes, less the ones its printer profile adds: this program reads no config.
    notes = checks.notes_on(measured, (truth or {}).get("bodies", 1)) + checks.gap_notes(measured, {})
    if notes:
        answer["notes"] = notes
    return answer


def _run(args: list[str]) -> tuple[int, dict[str, Any]]:
    if not 1 <= len(args) <= 2:
        raise Refused(USAGE)
    step = Path(args[0])
    if not step.is_file():
        raise Refused(f"no STEP file at {args[0]}")
    truth = _truth(Path(args[1])) if len(args) == 2 else None
    _limit(MEMORY_MB, MAX_OUTPUT_BYTES, CPU_SECONDS)
    # One BLAS thread, as the worker gets: every extra thread reserves address space under the ceiling.
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    # From here on what the kernel prints goes to standard error, for the rest of the process, so that
    # nothing it writes later lands in the answer: the STEP reader prints its errors to standard output.
    sys.stdout.flush()
    os.dup2(2, 1)
    try:
        answer = report(step, truth)
    except ImportError as exc:
        raise Refused(f"the measurement could not load its modules: {exc}") from None
    return (0 if answer.get("passed", True) else 1), answer


def main(argv: list[str] | None = None) -> int:
    """Run as a program: answer on the original standard output and return the exit status."""
    answer_fd = os.dup(1)
    try:
        code, answer = _run(sys.argv[1:] if argv is None else list(argv))
        text = json.dumps(answer, allow_nan=False)
    except Refused as refused:
        code, text = 2, json.dumps({"error": {"message": str(refused)}})
    except Exception as exc:  # the kernel's or this module's fault: still one object on standard output
        code, text = 2, json.dumps({"error": {"message": f"the STEP could not be measured ({type(exc).__name__}: {str(exc)[:200]})"}})
    with os.fdopen(answer_fd, "w", encoding="utf-8") as answer_out:
        answer_out.write(text + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
