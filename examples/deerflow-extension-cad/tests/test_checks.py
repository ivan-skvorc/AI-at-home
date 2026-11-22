"""The checks on their own: what decides pass or fail, outside the host.

``checks.py`` is what ``cad_build``, ``measure_cli`` and the CAD eval all judge
a part with, so it must import where the extension API is not installed. These
tests need no CAD kernel.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: Run in a fresh interpreter with the extension API made unimportable, the way a host-free caller sees the package.
WITHOUT_API = "import sys; sys.path.insert(0, {root!r}); sys.modules['deerflow_extension_api'] = None\n"


def _without_api(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", "-c", WITHOUT_API.format(root=str(ROOT)) + code], capture_output=True, text=True, timeout=120, check=False)


def test_the_checks_import_and_decide_without_the_extension_api():
    code = (
        "import json\n"
        "from deerflow_extension_cad import checks\n"
        "measured = {'solids': 1, 'valid': True, 'closed': True, 'bbox_mm': [60.0, 40.0, 6.0], 'volume_mm3': 14249.2, 'holes': []}\n"
        "verdict = checks.decide(measured, {'bbox_xyz_mm': [60, 40, 6]})\n"
        "print(json.dumps({'passed': all(c['passed'] for c in verdict), 'loaded': sorted(m for m, module in sys.modules.items() if module is not None and m.split('.')[0] in ('deerflow_extension_api', 'cadquery', 'OCP', 'numpy'))}))\n"
    )
    run = _without_api(code)
    assert run.returncode == 0, run.stderr
    # Nothing heavier than the checks themselves: no API, no kernel, no numpy.
    assert json.loads(run.stdout) == {"passed": True, "loaded": []}


def test_measure_cli_runs_as_a_program_without_the_extension_api():
    # What `python -I -m deerflow_extension_cad.measure_cli` does, with the API absent. Without
    # arguments it answers with its usage, in its own JSON, instead of failing on the package's import.
    code = "import runpy\nsys.argv = ['measure_cli']\nrunpy.run_module('deerflow_extension_cad.measure_cli', run_name='__main__')\n"
    run = _without_api(code)
    assert run.returncode == 2, run.stderr
    assert json.loads(run.stdout)["error"]["message"].startswith("usage: python -I -m deerflow_extension_cad.measure_cli")
