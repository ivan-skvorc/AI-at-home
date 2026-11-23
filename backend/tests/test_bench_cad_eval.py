"""Offline tests for the CAD eval (``make cad-eval``).

The runner is driven end to end against a fake Gateway: an ``httpx``
transport under the real client, serving synthetic run transcripts, and a
fake measurer in place of the ``measure_cli`` child process. No network, no
kernel, no model. The property that matters is the one the eval exists for:
``cad_build``'s own ``passed`` is self-graded, so a part is scored only by
measuring the STEP it delivered against truth the model never saw.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from scripts.benchmark.cad_eval.__main__ import build_parser, run_eval
from scripts.benchmark.cad_eval.design_path import DRAFT_INSTRUCTIONS, DRAFT_RULES, extract_draft, finalize_prompt, path_hash
from scripts.benchmark.cad_eval.measuring import MeasureCli, MeasureError
from scripts.benchmark.cad_eval.score import TABLE_HEADER, judge_truth, read_transcript, truth_from, wilson
from scripts.benchmark.cad_eval.specs import BANDS, NO_MODULE_BAND, PREAMBLE, load_specs, spec_set_hash

CAD = "ext_cad_cad_build_0123456789ab"
GUIDE = Path(__file__).resolve().parents[2] / "docs" / "guide" / "cad-eval.md"
PLATE = next(spec for spec in load_specs() if spec.id == "h01-mounting-plate")
OUTPUTS = "/mnt/user-data/outputs"


# --- Synthetic transcripts ----------------------------------------------------


def _call(call_id: str, tool: str = CAD, **args) -> dict:
    return {"type": "ai", "content": "", "tool_calls": [{"name": tool, "args": args, "id": call_id}]}


def _answer(call_id: str, answer: dict, tool: str = CAD) -> dict:
    return {"type": "tool", "name": tool, "tool_call_id": call_id, "content": json.dumps(answer)}


def _built(stem: str, attempt: int = 1) -> dict:
    files = [f"{OUTPUTS}/{stem}.{kind}" for kind in ("py", "glb", "stl", "step", "report.json")]
    return {"passed": True, "checks": [], "attempt": attempt, "files": files, "next": "Every check passed."}


def _refused(name: str, attempt: int) -> dict:
    return {"passed": False, "error": {"refused": name, "construct": "call", "line": 3, "message": f"{name} is not allowed"}, "attempt": attempt, "files": [f"{OUTPUTS}/plate.py"], "next": "Attempt..."}


def _final(text: str = "Here is your plate: plate.step") -> dict:
    return {"type": "ai", "content": text, "tool_calls": []}


def _measured(box, volume=19607.3, holes=(5, 5, 5, 5), solids=1) -> dict:
    return {"solids": solids, "valid": True, "closed": True, "bbox_mm": list(box), "volume_mm3": volume, "holes": [{"diameter_mm": d, "through": True} for d in holes]}


GOOD = _measured([80, 50, 5])


# --- The fake Gateway ---------------------------------------------------------


class FakeGateway:
    """Public routes the runner uses, answering from scripted transcripts."""

    def __init__(self, transcripts: list[list[dict]], *, cad: bool = True, models=("qwen-32k",), files: dict[str, bytes] | None = None, compacted: bool = False, usage: dict | None = None):
        self.transcripts = list(transcripts)
        self.cad = cad
        self.models = models
        self.files = files or {}
        self.compacted = compacted
        self.usage = usage or {"total_input_tokens": 900, "total_output_tokens": 100, "total_tokens": 1000, "total_cost": 0.002, "currency": "USD"}
        self.posted: list[dict] = []
        self.threads: dict[str, list[dict]] = {}
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(f"{request.method} {path}")
        if path == "/api/plugins":
            plugins = [{"namespace": "workflows", "model_tools": ["plan"], "settings": {"enabled": True}}]
            if self.cad:
                plugins.append({"namespace": "cad", "model_tools": ["cad_build"], "settings": {"enabled": True}})
            return httpx.Response(200, json=plugins)
        if path == "/api/models":
            return httpx.Response(200, json={"models": [{"name": name, "model": f"{name}-q4_K_M", "context_window": 32768} for name in self.models], "token_usage": {"enabled": True}})
        if path == "/api/runs/wait":
            body = json.loads(request.content)
            self.posted.append(body)
            thread = body["config"]["configurable"]["thread_id"]
            messages = [{"type": "human", "content": body["input"]["messages"][0]["content"]}, *self.transcripts.pop(0)]
            self.threads[thread] = messages
            # A compacted state keeps only the last answer; the run's event store keeps every message.
            return httpx.Response(200, json={"messages": messages[-1:] if self.compacted else messages})
        match = re.fullmatch(r"/api/threads/([^/]+)/(runs|token-usage|runs/run-1/messages|artifacts/(.+))", path)
        if match is None or match.group(1) not in self.threads:
            return httpx.Response(404, json={"detail": "not found"})
        thread, route = match.group(1), match.group(2)
        if route == "runs":
            return httpx.Response(200, json=[{"run_id": "run-1", "thread_id": thread, "status": "success"}])
        if route == "token-usage":
            return httpx.Response(200, json={"thread_id": thread, **self.usage})
        if route == "runs/run-1/messages":
            after = int(parse_qs(request.url.query.decode()).get("after_seq", ["0"])[0])
            rows = [
                {"seq": seq, "event_type": "message", "content": {key: value for key, value in message.items() if key != "_caller"}, "metadata": {"caller": message.get("_caller", "lead_agent")}}
                for seq, message in enumerate(self.threads[thread], 1)
                if seq > after
            ]
            return httpx.Response(200, json={"data": rows[:2], "has_more": len(rows) > 2})
        content = self.files.get("/" + match.group(3))
        return httpx.Response(200, content=content) if content is not None else httpx.Response(404)


class FakeMeasurer:
    """Stands in for ``python -m deerflow_extension_cad.measure_cli``: the STEP bytes name what it measures."""

    def __init__(self, by_content: dict[bytes, dict], problem: str | None = None):
        self.by_content = by_content
        self._problem = problem
        self.measured: list[Path] = []

    def problem(self) -> str | None:
        return self._problem

    def measure(self, step: Path) -> dict:
        self.measured.append(step)
        return self.by_content[step.read_bytes()]


def _args(tmp_path: Path, *extra: str):
    return build_parser().parse_args(["run", "--model", "qwen-32k", "--spec", PLATE.id, "--k", "1", "--out-dir", str(tmp_path), *extra])


def _record(tmp_path: Path) -> dict:
    (path,) = tmp_path.glob("cad-eval-*.json")
    return json.loads(path.read_text(encoding="utf-8"))


async def _run(tmp_path, gateway: FakeGateway, measurer: FakeMeasurer, *extra: str) -> int:
    return await run_eval(_args(tmp_path, *extra), transport=httpx.MockTransport(gateway.handler), measurer=measurer)


# --- Scoring on ground truth --------------------------------------------------


@pytest.mark.anyio
async def test_a_self_passed_part_with_a_wrong_bbox_scores_a_truth_fail(tmp_path, capsys):
    gateway = FakeGateway([[_call("c1", name="plate", script="..."), _answer("c1", _built("plate")), _final()]], files={f"{OUTPUTS}/plate.step": b"thick"})
    measurer = FakeMeasurer({b"thick": _measured([80, 50, 8])})

    assert await _run(tmp_path, gateway, measurer) == 0

    (sample,) = _record(tmp_path)["samples"]
    assert sample["self_passed"] is True and sample["presented"] is True
    assert sample["truth_passed"] is False
    assert [check["check"] for check in sample["truth"]["checks"] if not check["passed"]] == ["bbox"]
    summary = _record(tmp_path)["summary"]
    assert (summary["truth_passes"], summary["presented"], summary["claim_precision"]) == (0, 1, 0.0)
    assert "| 0/1 0% [0%–79%] | 1/1 | 0/1 0% |" in capsys.readouterr().out


@pytest.mark.anyio
async def test_a_part_that_meets_its_truth_passes_single_shot(tmp_path):
    gateway = FakeGateway([[_call("c1", name="plate", script="..."), _answer("c1", _built("plate")), _final()]], files={f"{OUTPUTS}/plate.step": b"good"})
    assert await _run(tmp_path, gateway, FakeMeasurer({b"good": GOOD})) == 0

    (sample,) = _record(tmp_path)["samples"]
    assert (sample["truth_passed"], sample["single_shot"], sample["builds_to_pass"]) == (True, True, 1)
    assert _record(tmp_path)["summary"]["claim_precision"] == 1.0


@pytest.mark.anyio
async def test_the_newest_passed_step_is_scored_and_a_pass_without_its_holes_fails(tmp_path):
    # The first build passed its own numbers with no holes; the model rebuilt and passed again with them.
    transcript = [
        _call("c1", name="plate", script="..."),
        _answer("c1", _built("plate")),
        _call("c2", name="plate", script="..."),
        _answer("c2", _built("plate-1", attempt=2)),
        _final(),
    ]
    gateway = FakeGateway([transcript], files={f"{OUTPUTS}/plate.step": b"no holes", f"{OUTPUTS}/plate-1.step": b"good"})
    measurer = FakeMeasurer({b"no holes": _measured([80, 50, 5], volume=20000, holes=()), b"good": GOOD})

    assert await _run(tmp_path, gateway, measurer) == 0

    (sample,) = _record(tmp_path)["samples"]
    assert sample["truth_passed"] is True
    # Single-shot is the first build against the truth: its holes are missing, though volume is within 2 %.
    assert sample["single_shot"] is False and sample["builds_to_pass"] == 1
    assert [step.name for step in measurer.measured] == ["plate-1.step", "plate.step"]


@pytest.mark.anyio
async def test_refusals_are_counted_by_their_error_refused_name(tmp_path):
    transcript = [
        _call("c1", name="plate", script="..."),
        _answer("c1", _refused("loft", 1)),
        _call("c2", name="plate", script="..."),
        _answer("c2", _refused("import os", 2)),
        _call("c3", name="plate", script="..."),
        _answer("c3", _refused("loft", 3)),
        _call("c4", name="plate", script="..."),
        _answer("c4", _built("plate", attempt=4)),
        _final(),
    ]
    gateway = FakeGateway([transcript], files={f"{OUTPUTS}/plate.step": b"good"})
    assert await _run(tmp_path, gateway, FakeMeasurer({b"good": GOOD})) == 0

    record = _record(tmp_path)
    (sample,) = record["samples"]
    assert sample["refusals"] == {"loft": 2, "import os": 1}
    assert (sample["builds_to_pass"], sample["single_shot"]) == (4, False)
    assert record["summary"]["repair_rounds_mean"] == 3
    assert record["summary"]["refusals"] == {"loft": 2, "import os": 1}


def test_a_module_before_structured_refusals_is_counted_by_its_construct():
    transcript = read_transcript([_call("c1"), _answer("c1", {"passed": False, "error": {"construct": "import", "line": 1, "message": "..."}, "files": []})])
    assert transcript.refusals == {"import": 1}
    assert transcript.delivered is None and not transcript.presented


@pytest.mark.anyio
async def test_the_transcript_comes_from_the_run_event_store_not_the_compacted_state(tmp_path):
    transcript = [_call("c1", name="plate", script="..."), _answer("c1", _refused("loft", 1)), _call("c2", name="plate", script="..."), _answer("c2", _built("plate", attempt=2)), _final()]
    gateway = FakeGateway([transcript], files={f"{OUTPUTS}/plate.step": b"good"}, compacted=True)
    assert await _run(tmp_path, gateway, FakeMeasurer({b"good": GOOD})) == 0

    (sample,) = _record(tmp_path)["samples"]
    assert (sample["builds"], sample["refusals"], sample["truth_passed"]) == (2, {"loft": 1}, True)


@pytest.mark.anyio
async def test_view_image_calls_tokens_and_spend_reach_the_row(tmp_path, capsys):
    transcript = [
        _call("c1", name="plate", script="..."),
        _answer("c1", _built("plate")),
        _call("v1", tool="view_image", image_path=f"{OUTPUTS}/plate.png"),
        _answer("v1", {"ok": True}, tool="view_image"),
        _final(),
    ]
    gateway = FakeGateway([transcript], files={f"{OUTPUTS}/plate.step": b"good"}, usage={"total_input_tokens": 4000, "total_output_tokens": 500, "total_tokens": 4500, "total_cost": 0.0125, "currency": "USD"})
    assert await _run(tmp_path, gateway, FakeMeasurer({b"good": GOOD}), "--quant", "Q4_K_M") == 0

    (sample,) = _record(tmp_path)["samples"]
    assert (sample["view_image_calls"], sample["total_tokens"], sample["cost"]) == (1, 4500, 0.0125)
    row = next(line for line in capsys.readouterr().out.splitlines() if line.startswith("| 20"))
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[0])
    assert cells[1:4] == ["qwen-32k", "Q4_K_M", "32768"]
    assert cells[7].startswith(spec_set_hash([PLATE]))
    assert cells[-3:] == ["1", "4500", "0.0125 USD"]


def test_the_wilson_interval_is_the_published_one():
    assert wilson(8, 10) == pytest.approx((0.4902, 0.9433), abs=5e-5)
    assert wilson(0, 3) == pytest.approx((0.0, 0.5615), abs=5e-5)
    assert wilson(3, 3) == pytest.approx((0.4385, 1.0), abs=5e-5)
    assert wilson(0, 0) == (0.0, 1.0)


def test_truth_compares_the_footprint_in_either_order_but_holds_the_height():
    truth = {"solids": 1, "bbox_mm": [80, 50, 5], "volume_mm3": 19607.3, "hole_diameters_mm": [5, 5, 5, 5]}
    assert judge_truth(_measured([50, 80, 5]), truth, "z")["passed"] is True
    assert judge_truth(_measured([80, 5, 50]), truth, "z")["passed"] is False
    assert judge_truth(_measured([80, 5, 50]), truth, "free")["passed"] is True
    assert judge_truth(_measured([80, 50, 5], solids=2), truth, "z")["passed"] is False


def _bar(through_x=(-25, -5), side_x=40.0, shift=(0.0, 0.0, 0.0), turned=False) -> dict:
    """h08's 80 x 20 x 8 bar as measure_cli reports it: two 5 mm holes down through it, a 3 mm one into an end.

    *through_x* and *side_x* are along the bar from its centre; *shift* moves the whole part,
    and *turned* lays it along y instead of x.
    """

    def place(x: float, y: float, z: float) -> list[float]:
        point = [y, x, z] if turned else [x, y, z]
        return [round(value + offset, 3) for value, offset in zip(point, shift)]

    def along(x: float, z: float) -> list[float]:
        return [0.0, x, z] if turned else [x, 0.0, z]

    holes = [{"diameter_mm": 5.0, "through": True, "depth_mm": 8.0, "at": place(x, 0, 4), "axis": along(0.0, -1.0)} for x in through_x]
    holes.append({"diameter_mm": 3.0, "through": False, "depth_mm": 12.0, "at": place(side_x, 0, 0), "axis": along(-1.0 if side_x > 0 else 1.0, 0.0)})
    size = [20.0, 80.0, 8.0] if turned else [80.0, 20.0, 8.0]
    low = [-side / 2 + offset for side, offset in zip(size, shift)]
    return {"solids": 1, "valid": True, "closed": True, "bbox_mm": size, "volume_mm3": 12401.018, "holes": holes, "bbox_min_mm": low, "bbox_max_mm": [a + side for a, side in zip(low, size)]}


BAR = next(spec for spec in load_specs() if spec.id == "h08-drilled-bar")


def _failed(verdict: dict) -> list[str]:
    return [check["check"] for check in verdict["checks"] if not check["passed"]]


def test_holes_the_request_places_are_found_however_the_part_is_turned_and_a_moved_one_fails():
    truth = BAR.truth
    assert truth_from(_bar(shift=(40, 10, 4)), positions=True) == truth  # the truth is taken from the box's centre
    for part in (_bar(), _bar(shift=(40, 10, 4)), _bar(through_x=(25, 5), side_x=-40), _bar(turned=True, shift=(3, -7, 0))):
        assert judge_truth(part, truth, BAR.orientation)["passed"] is True, part
    # Same diameters, volume and box: only where the holes are tells these apart.
    assert _failed(judge_truth(_bar(through_x=(-10, 10)), truth, BAR.orientation)) == ["hole positions"]
    assert _failed(judge_truth(_bar(through_x=(25, 5)), truth, BAR.orientation)) == ["hole positions"]
    older = {key: value for key, value in _bar().items() if key not in ("bbox_min_mm", "bbox_max_mm")}
    (check,) = [check for check in judge_truth(older, truth, BAR.orientation)["checks"] if not check["passed"]]
    assert check["check"] == "hole positions" and check["measured"].startswith("not measured")


def _hinge(gap: float = 0.4, bore: float | None = 4.8) -> dict:
    """f08's two bodies as measure_cli reports them: the holes are each body's, the gaps between them."""
    bodies = [{"valid": True, "closed": True, "volume_mm3": 4074.2, "holes": []}, {"valid": True, "closed": True, "volume_mm3": 2957.3, "holes": [{"diameter_mm": bore, "through": True}] if bore else []}]
    gaps = [{"bodies": [0, 1], "gap_mm": gap, "direction": [1.0, 0.0, 0.0], "at_mm": [13.2, 0.0, 0.0]}]
    return {"solids": 2, "valid": True, "closed": True, "bbox_mm": [40.0, 50.0, 8.0], "volume_mm3": 7031.5, "holes": [], "bodies": bodies, "gaps": gaps}


def test_a_print_in_place_gap_narrower_than_asked_fails_and_holes_are_read_from_each_body():
    truth = next(spec for spec in load_specs() if spec.id == "f08-print-in-place-hinge").truth
    assert truth_from(_hinge()) == {**truth, "volume_mm3": 7031.5}
    assert judge_truth(_hinge(), truth)["passed"] is True
    assert judge_truth(_hinge(gap=0.36), truth)["passed"] is True  # within 0.05 mm
    assert _failed(judge_truth(_hinge(gap=0.2), truth)) == ["smallest gap"]
    assert _failed(judge_truth(_hinge(bore=None), truth)) == ["holes"]
    fused = {**_hinge(), "solids": 1, "bodies": None, "gaps": None}
    assert _failed(judge_truth(fused, truth)) == ["solids", "holes", "smallest gap"]


@pytest.mark.skipif(os.name != "posix", reason="the stand-in measurer is a POSIX script")
def test_the_measurer_returns_measure_clis_measurement_and_says_why_when_there_is_none(tmp_path):
    # A stand-in for the CAD environment's python: it answers what measure_cli would, for the case in its argv.
    python = tmp_path / "python"
    python.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "step = sys.argv[-1]\n"
        "if step.endswith('good.step'):\n"
        "    print(json.dumps({'measured': {'solids': 1}, 'notes': ['n']}))\n"
        "elif step.endswith('bad.step'):\n"
        "    print(json.dumps({'error': {'message': 'the STEP could not be measured (ValueError: no shape)'}})); sys.exit(2)\n"
        "else:\n"
        "    print('Segmentation fault', file=sys.stderr); sys.exit(139)\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    measurer = MeasureCli(str(python))
    assert measurer.measure(tmp_path / "good.step") == {"solids": 1}
    with pytest.raises(MeasureError, match="no shape"):
        measurer.measure(tmp_path / "bad.step")
    with pytest.raises(MeasureError, match="Segmentation fault"):
        measurer.measure(tmp_path / "crash.step")


# --- Refusing to start --------------------------------------------------------


@pytest.mark.anyio
async def test_the_command_refuses_to_start_without_the_cad_module(tmp_path, capsys):
    gateway = FakeGateway([], cad=False)
    assert await _run(tmp_path, gateway, FakeMeasurer({})) == 3
    assert "CAD module" in capsys.readouterr().err
    assert gateway.posted == [] and not list(tmp_path.glob("cad-eval-*.json"))


@pytest.mark.anyio
async def test_the_command_refuses_to_start_when_the_measurer_is_missing(tmp_path, capsys):
    gateway = FakeGateway([])
    assert await _run(tmp_path, gateway, FakeMeasurer({}, problem="deerflow_extension_cad.measure_cli is not installed")) == 3
    assert "measure_cli" in capsys.readouterr().err
    assert gateway.requests == []


@pytest.mark.anyio
async def test_a_model_the_gateway_does_not_know_is_refused_instead_of_run_on_the_default(tmp_path, capsys):
    gateway = FakeGateway([], models=("gpt-big",))
    assert await _run(tmp_path, gateway, FakeMeasurer({})) == 3
    assert "qwen-32k" in capsys.readouterr().err and gateway.posted == []


@pytest.mark.anyio
async def test_no_model_prints_usage_and_exits_non_zero(tmp_path, capsys):
    gateway = FakeGateway([])
    args = build_parser().parse_args(["run", "--out-dir", str(tmp_path)])
    assert await run_eval(args, transport=httpx.MockTransport(gateway.handler), measurer=FakeMeasurer({})) == 2
    assert "MODEL=" in capsys.readouterr().err and gateway.requests == []


@pytest.mark.anyio
async def test_the_request_names_the_model_explicitly_and_carries_no_truth(tmp_path):
    gateway = FakeGateway([[_call("c1", name="plate", script="..."), _answer("c1", _built("plate")), _final()]], files={f"{OUTPUTS}/plate.step": b"good"})
    assert await _run(tmp_path, gateway, FakeMeasurer({b"good": GOOD})) == 0

    (body,) = gateway.posted
    assert body["context"]["model_name"] == body["context"]["model_selection_requested"] == "qwen-32k"
    prompt = body["input"]["messages"][0]["content"]
    assert prompt == f"{PLATE.request}\n\n{PREAMBLE}"
    assert str(PLATE.truth["volume_mm3"]) not in json.dumps(body)


@pytest.mark.anyio
async def test_a_spend_cap_stops_further_samples(tmp_path):
    transcript = [_call("c1", name="plate", script="..."), _answer("c1", _built("plate")), _final()]
    gateway = FakeGateway([transcript, transcript, transcript], files={f"{OUTPUTS}/plate.step": b"good"}, usage={"total_input_tokens": 1, "total_output_tokens": 1, "total_tokens": 2, "total_cost": 0.5, "currency": "USD"})
    args = build_parser().parse_args(["run", "--model", "qwen-32k", "--spec", PLATE.id, "--k", "3", "--max-cost", "0.9", "--out-dir", str(tmp_path)])
    assert await run_eval(args, transport=httpx.MockTransport(gateway.handler), measurer=FakeMeasurer({b"good": GOOD})) == 1

    record = _record(tmp_path)
    assert len(record["samples"]) == 2 and record["stopped"].startswith("spend cap")


# --- The design path ------------------------------------------------------------

DRAFT = "width = 80; // [40:1:120]\ndepth = 50;\ncube([width, depth, 5]);"


def _draft_reply(text: str = f"Here is the draft.\n\n```openscad\n{DRAFT}\n```") -> list[dict]:
    return [_final(text)]


@pytest.mark.anyio
async def test_the_design_path_drafts_in_openscad_then_ports_the_draft_to_cadquery_in_the_same_thread(tmp_path, capsys):
    port = [_call("c1", name="plate", script="..."), _answer("c1", _built("plate")), _final()]
    gateway = FakeGateway([_draft_reply(), port], files={f"{OUTPUTS}/plate.step": b"good"})
    assert await _run(tmp_path, gateway, FakeMeasurer({b"good": GOOD}), "--path", "design") == 0

    first, second = gateway.posted
    assert first["config"] == second["config"]
    draft = first["input"]["messages"][0]["content"]
    assert draft.startswith(PLATE.prompt()) and draft.endswith(DRAFT_INSTRUCTIONS)
    finalize = second["input"]["messages"][0]["content"]
    assert finalize == finalize_prompt(DRAFT) and "cad_build" in finalize
    # The truth never reaches either turn, and the part is scored on the same truth as the direct path.
    assert str(PLATE.truth["volume_mm3"]) not in json.dumps(gateway.posted)
    record = _record(tmp_path)
    (sample,) = record["samples"]
    assert (sample["path"], sample["draft_found"], sample["draft_builds"], sample["truth_passed"]) == ("design", True, 0, True)
    assert record["settings"]["path"] == "design"
    assert record["meta"]["specs"].endswith(f"(specs; design {path_hash()})")
    assert "design path     : 1/1 drafts" in capsys.readouterr().out


@pytest.mark.anyio
async def test_a_draft_turn_without_an_openscad_file_is_no_part_and_nothing_is_ported(tmp_path):
    gateway = FakeGateway([_draft_reply("I would make a plate 80 by 50.")])
    assert await _run(tmp_path, gateway, FakeMeasurer({}), "--path", "design") == 0

    assert len(gateway.posted) == 1
    (sample,) = _record(tmp_path)["samples"]
    assert (sample["draft_found"], sample["truth_passed"], sample["error"]) == (False, False, None)


def test_the_draft_is_the_last_openscad_block_the_model_wrote():
    messages = [
        {"type": "human", "content": "```openscad\ncube(1);\n```"},
        _final("first\n```openscad\ncube(2);\n```"),
        _final([{"type": "text", "text": "fixed\n```scad\ncube(3);\n```"}]),
        _final("```python\nprint(1)\n```"),
    ]
    assert extract_draft(messages) == "cube(3);\n"
    assert extract_draft([_final("no code")]) is None


def test_the_design_path_gives_the_drafting_rules_of_the_page_brief():
    notes = pytest.importorskip("deerflow_extension_cad_design.notes")
    for rule in DRAFT_RULES:
        assert rule in notes.DRAFT_BRIEF.splitlines()


@pytest.mark.anyio
async def test_the_design_path_does_not_run_without_the_module(tmp_path, capsys):
    gateway = FakeGateway([], cad=False)
    args = build_parser().parse_args(["run", "--model", "qwen-32k", "--no-module", "--path", "design", "--out-dir", str(tmp_path)])
    assert await run_eval(args, transport=httpx.MockTransport(gateway.handler), measurer=FakeMeasurer({})) == 2
    assert "direct path only" in capsys.readouterr().err and gateway.requests == []


# --- The module-disabled spec -------------------------------------------------


@pytest.mark.anyio
async def test_without_the_module_the_reply_must_say_how_to_find_out_why(tmp_path):
    # A middleware's own model call (a title, a summary) is logged after the reply; it is not the reply.
    title = {**_final("Cube as a STEP file"), "_caller": "middleware:title"}
    good = FakeGateway([[_final("The CAD module is not enabled on this server; `make doctor` there says why."), title]], cad=False)
    args = build_parser().parse_args(["run", "--model", "qwen-32k", "--no-module", "--k", "1", "--out-dir", str(tmp_path / "good")])
    assert await run_eval(args, transport=httpx.MockTransport(good.handler), measurer=FakeMeasurer({}, problem="not installed")) == 0
    assert _record(tmp_path / "good")["samples"][0]["reply_ok"] is True

    bad = FakeGateway([[_final("Here is a cube, saved as cube.step.")]], cad=False)
    args = build_parser().parse_args(["run", "--model", "qwen-32k", "--no-module", "--k", "1", "--out-dir", str(tmp_path / "bad")])
    assert await run_eval(args, transport=httpx.MockTransport(bad.handler), measurer=FakeMeasurer({})) == 1

    on = FakeGateway([])
    args = build_parser().parse_args(["run", "--model", "qwen-32k", "--no-module", "--out-dir", str(tmp_path / "on")])
    assert await run_eval(args, transport=httpx.MockTransport(on.handler), measurer=FakeMeasurer({})) == 3
    assert on.posted == []


# --- The spec set -------------------------------------------------------------


def test_the_part_specs_cover_three_bands_with_a_reference_and_truth_each():
    parts = load_specs()
    assert Counter(spec.band for spec in parts) == {"prismatic": 6, "holes": 8, "fits": 8}
    assert set(BANDS) == {"prismatic", "holes", "fits"}
    assert len({spec.id for spec in parts}) == len(parts)
    for spec in parts:
        assert spec.has_reference, spec.id
        assert spec.truth is not None, f"{spec.id}: run derive_truth.py"
        assert "import cadquery" in spec.reference.read_text(encoding="utf-8")
    # Specs that wait on another roadmap item say which, and what they call from it.
    waiting = {spec.id: [need.item for need in spec.needs] for spec in parts if spec.needs}
    assert waiting == {"f05-v-pulley": ["56"], "f06-captive-pin": ["51"], "f07-box-and-lid": ["51"], "f08-print-in-place-hinge": ["51"], "h07-name-tag": ["59"]}
    # Positions are checked only where the request says where the holes go.
    assert [spec.id for spec in parts if spec.hole_positions] == ["h08-drilled-bar"] and "holes_at_mm" in BAR.truth
    assert {spec.id: spec.truth["min_gap_mm"] for spec in parts if spec.truth["solids"] > 1} == {"f06-captive-pin": 0.3, "f07-box-and-lid": 10.0, "f08-print-in-place-hinge": 0.4}
    assert [spec.id for spec in load_specs(band=NO_MODULE_BAND)] == ["m01-no-module"]


def test_the_spec_set_hash_moves_when_a_request_or_its_truth_moves():
    parts = load_specs()
    moved = [dataclasses.replace(spec, raw={**spec.raw, "request": spec.raw["request"] + " "}) if spec.id == PLATE.id else spec for spec in parts]
    assert spec_set_hash(parts) == spec_set_hash(load_specs())
    assert spec_set_hash(moved) != spec_set_hash(parts)


def test_the_guide_holds_the_header_of_the_rows_the_runner_prints():
    assert TABLE_HEADER in GUIDE.read_text(encoding="utf-8")
