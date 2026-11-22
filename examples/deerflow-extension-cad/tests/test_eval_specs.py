"""Every CAD eval spec's reference part builds and meets the ground truth stored beside it.

The eval (``backend/scripts/benchmark/cad_eval``, ``make cad-eval``) scores a
model's part by measuring the STEP it delivered against a spec's truth. That
truth is only worth something if a part built the way a model would build it
reaches it. So each spec's ``reference.py`` is read by this package's reader,
built, exported, and measured by ``measure_cli`` through the eval's own
measurer, and the same ``judge_truth`` that grades a model grades it. It must
also measure to the stored numbers: a truth that no longer matches its
reference was typed in, not derived (``derive_truth.py`` derives it).

A part whose pass depends on the tool itself, one of several bodies or one
whose holes the request places, goes through the real ``cad_build`` handler
instead, and the eval reads the delivered STEP out of the tool's answer the way
it reads a run's transcript. Every roadmap item a spec names has landed, so a
reference this allow-list cannot build is a failure, not a skip.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

cq = pytest.importorskip("cadquery", reason="the CAD kernel is not installed")

from deerflow_extension_api import ExtensionPrincipal, ToolContext  # noqa: E402

from deerflow_extension_cad import build  # noqa: E402
from deerflow_extension_cad.allowlist import METHODS  # noqa: E402
from deerflow_extension_cad.interpreter import compile_script  # noqa: E402
from deerflow_extension_cad.tool import make_handler, settings_from  # noqa: E402

EVAL = Path("backend", "scripts", "benchmark", "cad_eval")
ROOT = next((parent for parent in Path(__file__).resolve().parents if (parent / EVAL / "specs").is_dir()), None)
if ROOT is None:
    pytest.skip("the repository's CAD eval specs are not beside this package", allow_module_level=True)
#: How the host registers the tool; the eval finds cad_build by this part of the name.
TOOL_NAME = "ext_cad_cad_build_0123456789ab"


def _load(name: str):
    # By path: the eval lives in the backend tree, whose packages this environment does not have.
    spec = importlib.util.spec_from_file_location(f"cad_eval_{name}", ROOT / EVAL / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


specs = _load("specs")
score = _load("score")
measuring = _load("measuring")
MEASURER = measuring.MeasureCli(sys.executable)
REFERENCED = [spec for spec in specs.load_specs() if spec.has_reference]
DELIVERED = [spec for spec in REFERENCED if spec.truth is not None and (spec.truth["solids"] > 1 or spec.hole_positions)]
BUILT = [spec for spec in REFERENCED if spec not in DELIVERED]


class Outputs:
    """Stands in for the host's output writer: keeps each file under the name it was given."""

    def __init__(self):
        self.files: dict[str, bytes] = {}

    async def write(self, name: str, content: bytes) -> str:
        self.files[name] = content
        return f"/mnt/user-data/outputs/{name}"


async def _cad_build(payload: dict, thread: str) -> tuple[dict, Outputs]:
    outputs = Outputs()
    context = ToolContext(ExtensionPrincipal("eval"), {"enabled": True}, thread, output_writer=outputs.write)
    return await make_handler(settings_from({}))(payload, context), outputs


def _transcript(payload: dict, answer: dict):
    """One cad_build call and its answer, as the run's event store hands them to the eval."""
    call = {"type": "ai", "content": "", "tool_calls": [{"name": TOOL_NAME, "args": payload, "id": "call-1"}]}
    result = {"type": "tool", "name": TOOL_NAME, "tool_call_id": "call-1", "content": json.dumps(answer)}
    return score.read_transcript([call, result, {"type": "ai", "content": "Here is the part.", "tool_calls": []}])


def _buildable(spec) -> None:
    assert spec.truth is not None, f"{spec.id} has no truth: run derive_truth.py"
    missing = spec.missing_operations(METHODS)
    assert not missing, "needs " + "; ".join(f"item {item} ({', '.join(names)})" for item, names in missing.items()) + ", which this allow-list lacks"


def _meets_its_truth(spec, measured: dict) -> None:
    verdict = score.judge_truth(measured, spec.truth, spec.orientation)
    assert verdict["passed"], verdict
    # And the truth is what the reference measures, not a number typed in beside it.
    fresh = score.truth_from(measured, positions=spec.hole_positions)
    assert set(fresh) == set(spec.truth)
    assert fresh["solids"] == spec.truth["solids"]
    assert fresh["bbox_mm"] == pytest.approx(spec.truth["bbox_mm"], abs=1e-3)
    assert fresh["volume_mm3"] == pytest.approx(spec.truth["volume_mm3"], rel=1e-6)
    assert fresh["hole_diameters_mm"] == pytest.approx(spec.truth["hole_diameters_mm"], abs=1e-3)
    if "min_gap_mm" in fresh:
        assert fresh["min_gap_mm"] == pytest.approx(spec.truth["min_gap_mm"], abs=1e-3)
    if "holes_at_mm" in fresh:

        def rows(holes: list) -> list[float]:
            return [number for row in sorted([hole["diameter_mm"], *hole["at"], *hole["axis"]] for hole in holes) for number in row]

        assert rows(fresh["holes_at_mm"]) == pytest.approx(rows(spec.truth["holes_at_mm"]), abs=1e-3)
        assert sorted((hole["diameter_mm"], hole["through"]) for hole in fresh["holes_at_mm"]) == sorted((hole["diameter_mm"], hole["through"]) for hole in spec.truth["holes_at_mm"])


def test_the_eval_measures_with_measure_cli_in_this_environment():
    # The measurer the eval and derive_truth use finds the program and its kernel: there is no other path.
    assert MEASURER.problem() is None


@pytest.mark.parametrize("spec", BUILT, ids=[spec.id for spec in BUILT])
def test_the_reference_part_builds_and_meets_its_truth(spec, tmp_path):
    _buildable(spec)
    program = compile_script(spec.reference.read_text(encoding="utf-8"))
    parts = build.build_parts(program, cq)
    names = build.export(build.solid_of(parts[program.result]), cq, tmp_path, 64 * 1024 * 1024)[0]
    _meets_its_truth(spec, MEASURER.measure(tmp_path / names["step"]))


@pytest.mark.parametrize("spec", DELIVERED, ids=[spec.id for spec in DELIVERED])
async def test_cad_build_delivers_the_reference_part_and_the_eval_scores_it(spec, tmp_path):
    _buildable(spec)
    truth = spec.truth
    payload = {
        "name": spec.id,
        "script": spec.reference.read_text(encoding="utf-8"),
        "bbox_xyz_mm": truth["bbox_mm"],
        "volume_min_max_mm3": [truth["volume_mm3"] * 0.999, truth["volume_mm3"] * 1.001],
        "hole_diameters_mm": truth["hole_diameters_mm"],
        **({"bodies": truth["solids"]} if truth["solids"] > 1 else {}),
    }
    answer, outputs = await _cad_build(payload, f"thread-{spec.id}")
    assert answer["passed"] is True, answer

    transcript = _transcript(payload, answer)
    delivered = transcript.delivered
    assert transcript.presented and delivered is not None and delivered.step and delivered.report
    step = tmp_path / Path(delivered.step).name
    step.write_bytes(outputs.files[step.name])
    _meets_its_truth(spec, MEASURER.measure(step))
    # The row's provenance comes from the delivered report.
    report = json.loads(outputs.files[Path(delivered.report).name])
    assert report["module_version"] and report["cadquery_version"]


async def test_a_refused_build_reaches_the_eval_by_the_name_the_reader_gives_it():
    payload = {"name": "plate", "script": "import os\nresult = cq.Workplane('XY').box(10, 10, 10)\n", "bbox_xyz_mm": [10, 10, 10]}
    answer, _ = await _cad_build(payload, "thread-refused")
    assert answer["passed"] is False and answer["error"]["construct"] == "import"
    transcript = _transcript(payload, answer)
    # Counted by error.refused, which names what was refused; error.construct only says what kind it was.
    assert transcript.refusals == {"import os": 1} and transcript.delivered is None
