"""The measurer: the CAD module's ``measure_cli``, run as a child process.

Every STEP the eval scores, and every reference part its truth comes from, is
measured by ``python -I -m deerflow_extension_cad.measure_cli <step>``: the
same re-import and the same ``measure_step`` that ``cad_build`` decides on, in
an environment that has the CAD module and its kernel. The eval's own Python
never loads the kernel.

Stdlib only: the CAD package's test loads this file by path and scores each
reference part through it, so the path a model's part takes is tested end to
end.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

MODULE = "deerflow_extension_cad.measure_cli"
#: measure_cli holds its own processor ceiling; this is the wall clock around it.
MEASURE_TIMEOUT_SECONDS = 300
PROBE_TIMEOUT_SECONDS = 60


class MeasureError(Exception):
    """measure_cli answered without a measurement: the reason it gave, or what it printed."""


class MeasureCli:
    """``python -I -m deerflow_extension_cad.measure_cli <step>`` in the environment of *python*."""

    def __init__(self, python: str = sys.executable):
        self.python = python

    def problem(self) -> str | None:
        """Why this Python cannot measure a STEP, or None. Checked before a run starts."""
        # find_spec looks without importing: the probe loads neither the module nor the kernel.
        probe = f"import importlib.util as u, sys; sys.exit(3 if u.find_spec({MODULE!r}) is None else 4 if u.find_spec('cadquery') is None else 0)"
        try:
            done = subprocess.run([self.python, "-I", "-c", probe], capture_output=True, timeout=PROBE_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"{self.python} could not be started ({exc})"
        if done.returncode == 3:
            return f"the CAD module's measure_cli is not installed for {self.python}: the eval measures each STEP with it. Install the CAD module there, or pass --measure-python."
        if done.returncode == 4:
            return f"the CAD kernel (cadquery) is not installed for {self.python}, so measure_cli cannot load a STEP. Install the CAD module with its kernel there, or pass --measure-python."
        if done.returncode != 0:
            return f"{self.python} could not check for measure_cli (exit {done.returncode}: {done.stderr.decode(errors='replace')[-300:].strip()})"
        return None

    def measure(self, step: Path) -> dict[str, Any]:
        """What measure_cli measures on *step*: the ``measured`` object of its answer."""
        done = subprocess.run([self.python, "-I", "-m", MODULE, str(step)], capture_output=True, text=True, timeout=MEASURE_TIMEOUT_SECONDS)
        try:
            answer = json.loads(done.stdout)
        except ValueError:
            raise MeasureError(f"measure_cli exited {done.returncode} without an answer: {done.stderr[-300:].strip()}") from None
        if done.returncode != 0 or not isinstance(answer, dict) or not isinstance(answer.get("measured"), dict):
            error = answer.get("error") if isinstance(answer, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            raise MeasureError(f"measure_cli exited {done.returncode}: {message or json.dumps(answer)[:300]}")
        return answer["measured"]
