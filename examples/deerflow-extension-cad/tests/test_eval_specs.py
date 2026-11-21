"""Every CAD eval spec's reference part builds and meets the ground truth stored beside it.

The eval (``backend/scripts/benchmark/cad_eval``, ``make cad-eval``) scores a
model's part by measuring the STEP it delivered against a spec's truth. That
truth is only worth something if a part built the way a model would build it
reaches it. So each spec's ``reference.py`` is read by this package's reader,
built, exported, re-imported and measured, and the same ``judge_truth`` that
grades a model grades it. It must also measure to the stored numbers: a truth
that no longer matches its reference was typed in, not derived.

A reference that calls an operation this allow-list lacks is skipped with the
roadmap item that adds it. The truth is derived by ``derive_truth.py``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

cq = pytest.importorskip("cadquery", reason="the CAD kernel is not installed")

from deerflow_extension_cad import build, measure  # noqa: E402
from deerflow_extension_cad.allowlist import METHODS  # noqa: E402
from deerflow_extension_cad.interpreter import compile_script  # noqa: E402

EVAL = Path("backend", "scripts", "benchmark", "cad_eval")
ROOT = next((parent for parent in Path(__file__).resolve().parents if (parent / EVAL / "specs").is_dir()), None)
if ROOT is None:
    pytest.skip("the repository's CAD eval specs are not beside this package", allow_module_level=True)


def _load(name: str):
    # By path: the eval lives in the backend tree, whose packages this environment does not have.
    spec = importlib.util.spec_from_file_location(f"cad_eval_{name}", ROOT / EVAL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


specs = _load("specs")
score = _load("score")
REFERENCED = [spec for spec in specs.load_specs() if spec.has_reference]


def _measured(step: Path) -> dict:
    # The module's own measuring entry point once it has one (item 57), else the function it wraps.
    if importlib.util.find_spec("deerflow_extension_cad.measure_cli") is not None:
        done = subprocess.run([sys.executable, "-I", "-m", "deerflow_extension_cad.measure_cli", str(step)], capture_output=True, text=True, timeout=300, check=True)
        return score.measured_from(json.loads(done.stdout))
    return measure.measure_step(step, cq)


@pytest.mark.parametrize("spec", REFERENCED, ids=[spec.id for spec in REFERENCED])
def test_the_reference_part_builds_and_meets_its_truth(spec, tmp_path):
    missing = spec.missing_operations(METHODS)
    if missing:
        pytest.skip("needs " + "; ".join(f"item {item} ({', '.join(names)})" for item, names in missing.items()) + ", which this allow-list does not have yet")
    assert spec.truth is not None, f"{spec.id} has no truth: run derive_truth.py"

    program = compile_script(spec.reference.read_text(encoding="utf-8"))
    parts = build.build_parts(program, cq)
    names = build.export(build.solid_of(parts[program.result]), cq, tmp_path, 64 * 1024 * 1024)[0]
    measured = _measured(tmp_path / names["step"])

    verdict = score.judge_truth(measured, spec.truth, spec.orientation)
    assert verdict["passed"], verdict
    assert measured["solids"] == spec.truth["solids"]
    assert measured["bbox_mm"] == pytest.approx(spec.truth["bbox_mm"], abs=1e-3)
    assert measured["volume_mm3"] == pytest.approx(spec.truth["volume_mm3"], rel=1e-6)
    if "hole_diameters_mm" in spec.truth:
        assert sorted(hole["diameter_mm"] for hole in measured["holes"]) == pytest.approx(spec.truth["hole_diameters_mm"], abs=1e-3)
