"""Pure scoring: a run's transcript and a re-measured STEP in, numbers out.

``cad_build`` answers ``passed`` against the numbers the model chose, so a pass
there is self-graded. Here the STEP the run delivered is measured again and
held to ground truth the model never saw (``judge_truth``); ``passed`` is read
only to find which STEP was delivered and whether the model presented it.

Stdlib only: the CAD package's test loads this file by path to judge each
reference part with the same function that judges a model's part.
"""

from __future__ import annotations

import itertools
import json
import math
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

#: Ground truth tolerances. Looser than cad_build's own 0.01 mm: the request states a
#: part in round numbers, and a model that meets it within a millimetre and 2 % of its
#: volume built the part that was asked for. The hole check is what stops a plate that
#: forgot its holes from passing on volume alone.
TRUTH_BBOX_MM = 1.0
TRUTH_VOLUME_RATIO = 0.02
TRUTH_HOLE_MM = 0.1
#: A hole the spec places (``holes_at_mm``) is there when a measured hole of its diameter and kind
#: (through or blind) runs within 5 degrees of its direction, and passes within this distance of
#: the point: its axis for a through hole, its open end for a blind one, which has only that end.
TRUTH_POSITION_MM = 0.5
TRUTH_AXIS_COS = math.cos(math.radians(5))
#: The smallest gap between bodies may fall short of the truth's by 0.05 mm or 10 %, whichever is
#: larger: a print-in-place clearance asked for as 0.4 mm must not come back as 0.2.
TRUTH_GAP_MM = 0.05
TRUTH_GAP_RATIO = 0.1
#: Which axes of the truth may stand for which axes of the part, by orientation: as stated,
#: the footprint either way round, or any way round. Every mirror is allowed on top.
_PERMUTATIONS = {
    "fixed": ((0, 1, 2),),
    "z": ((0, 1, 2), (1, 0, 2)),
    "free": tuple(itertools.permutations(range(3))),
}

#: z for a two-sided 95 % interval.
Z_95 = 1.959963984540054

#: The CAD tool is registered as ext_cad_cad_build_<digest>; the skill finds it the same way.
CAD_TOOL = "cad_build"
VIEW_IMAGE_TOOL = "view_image"


# --- Ground truth -------------------------------------------------------------


def holes_of(measured: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Every measured hole: the part's own, or each body's in turn.

    The module measures a hole against its own body, so a captive pin does not fill
    its bore, and keeps the part's ``holes`` empty when there is more than one body.
    """
    bodies = measured.get("bodies")
    holes = [hole for body in bodies if isinstance(body, Mapping) for hole in body.get("holes") or []] if isinstance(bodies, list) else measured.get("holes") or []
    return [hole for hole in holes if isinstance(hole, Mapping) and isinstance(hole.get("diameter_mm"), (int, float))]


def _sides(box: Sequence[float], orientation: str) -> list[float]:
    if orientation == "free":
        return sorted(box)
    if orientation == "z":
        return [*sorted(box[:2]), box[2]]
    return list(box)


def _centre(measured: Mapping[str, Any]) -> list[float] | None:
    low, high = measured.get("bbox_min_mm"), measured.get("bbox_max_mm")
    if not (isinstance(low, list) and isinstance(high, list) and len(low) == len(high) == 3):
        return None
    return [(a + b) / 2 for a, b in zip(low, high)]


def _off_axis(point: Sequence[float], at: Sequence[float], axis: Sequence[float]) -> float:
    """How far *point* lies from the line through *at* along the unit vector *axis*."""
    offset = [p - a for p, a in zip(point, at)]
    along = sum(o * d for o, d in zip(offset, axis))
    return math.sqrt(sum((o - along * d) ** 2 for o, d in zip(offset, axis)))


def _matched(fits: list[list[int]]) -> int:
    """The size of a maximum one-to-one matching, *fits[i]* listing what expected entry i may take."""
    owner: dict[int, int] = {}

    def claim(i: int, seen: set[int]) -> bool:
        for k in fits[i]:
            if k not in seen:
                seen.add(k)
                if k not in owner or claim(owner[k], seen):
                    owner[k] = i
                    return True
        return False

    return sum(claim(i, set()) for i in range(len(fits)))


def _placed(expected: Sequence[Mapping[str, Any]], measured: Mapping[str, Any], orientation: str) -> tuple[bool, str | None]:
    """Whether every hole the truth places is on the part, under some turn and mirror its box allows.

    Points are compared from the centre of each bounding box, so the part may sit anywhere,
    and a part built mirrored or turned the way the orientation allows is the same part.
    """
    centre = _centre(measured)
    if centre is None:
        return False, "not measured: this module reports no bounding-box corners"
    holes = [hole for hole in holes_of(measured) if isinstance(hole.get("at"), list) and isinstance(hole.get("axis"), list)]
    located = [{**hole, "at": [a - c for a, c in zip(hole["at"], centre)]} for hole in holes]

    def there(entry: Mapping[str, Any], point: list[float], direction: list[float], hole: Mapping[str, Any]) -> bool:
        if abs(hole["diameter_mm"] - entry["diameter_mm"]) > TRUTH_HOLE_MM or abs(sum(a * b for a, b in zip(hole["axis"], direction))) < TRUTH_AXIS_COS:
            return False
        through = entry.get("through", True)
        if hole.get("through", True) != through:
            return False
        if through:
            return _off_axis(point, hole["at"], hole["axis"]) <= TRUTH_POSITION_MM
        return math.dist(point, hole["at"]) <= TRUTH_POSITION_MM

    for order in _PERMUTATIONS[orientation]:
        for signs in itertools.product((1, -1), repeat=3):

            def turned(vector: Sequence[float]) -> list[float]:
                return [sign * vector[index] for sign, index in zip(signs, order)]

            fits = [[k for k, hole in enumerate(located) if there(entry, turned(entry["at"]), turned(entry["axis"]), hole)] for entry in expected]
            if _matched(fits) == len(expected):
                return True, None
    return False, f"{len(located)} located hole(s); no turn or mirror of the part puts a hole at every expected point"


def judge_truth(measured: Mapping[str, Any], truth: Mapping[str, Any], orientation: str = "z") -> dict[str, Any]:
    """Hold a re-measured part to the spec's truth. Every check must pass."""
    checks: list[dict[str, Any]] = []
    solids = measured.get("solids")
    checks.append(
        {
            "check": "solids",
            "expected": truth["solids"],
            "measured": solids,
            "passed": solids == truth["solids"] and measured.get("valid") is True and measured.get("closed") is True,
        }
    )
    box = measured.get("bbox_mm") or []
    expected_box = _sides(truth["bbox_mm"], orientation)
    measured_box = _sides(box, orientation) if len(box) == 3 else list(box)
    checks.append(
        {
            "check": "bbox",
            "expected": expected_box,
            "measured": measured_box,
            "passed": len(measured_box) == 3 and all(abs(e - m) <= TRUTH_BBOX_MM for e, m in zip(expected_box, measured_box)),
        }
    )
    volume = measured.get("volume_mm3")
    checks.append(
        {
            "check": "volume",
            "expected": truth["volume_mm3"],
            "measured": volume,
            "passed": isinstance(volume, (int, float)) and abs(volume - truth["volume_mm3"]) <= TRUTH_VOLUME_RATIO * truth["volume_mm3"],
        }
    )
    if truth.get("hole_diameters_mm") is not None:
        expected = sorted(truth["hole_diameters_mm"])
        found = sorted(hole["diameter_mm"] for hole in holes_of(measured))
        checks.append(
            {
                "check": "holes",
                "expected": expected,
                "measured": found,
                "passed": len(expected) == len(found) and all(abs(e - m) <= TRUTH_HOLE_MM for e, m in zip(expected, found)),
            }
        )
    if truth.get("holes_at_mm"):
        placed, why = _placed(truth["holes_at_mm"], measured, orientation)
        checks.append({"check": "hole positions", "expected": [[entry["diameter_mm"], *entry["at"]] for entry in truth["holes_at_mm"]], "measured": why or "every expected hole found", "passed": placed})
    if truth.get("min_gap_mm") is not None:
        gaps = [gap["gap_mm"] for gap in measured.get("gaps") or [] if isinstance(gap, Mapping) and isinstance(gap.get("gap_mm"), (int, float))]
        smallest = min(gaps) if gaps else None
        least = truth["min_gap_mm"] - max(TRUTH_GAP_MM, TRUTH_GAP_RATIO * truth["min_gap_mm"])
        checks.append({"check": "smallest gap", "expected": f">= {round(least, 3)}", "measured": smallest, "passed": smallest is not None and smallest >= least})
    return {"passed": all(check["passed"] for check in checks), "checks": checks}


def truth_from(measured: Mapping[str, Any], *, positions: bool = False) -> dict[str, Any]:
    """The truth a reference part stands for: what was measured on it, nothing typed in beside it.

    Every part gets its hole diameters (each body's, for several bodies) and a part of
    several bodies the smallest gap between them. With *positions*, each hole's point and
    direction are kept too, from the centre of the bounding box, for a request that says
    where its holes go.
    """
    truth: dict[str, Any] = {"solids": measured["solids"], "bbox_mm": list(measured["bbox_mm"]), "volume_mm3": measured["volume_mm3"]}
    holes = sorted(holes_of(measured), key=lambda hole: hole["diameter_mm"])
    truth["hole_diameters_mm"] = [hole["diameter_mm"] for hole in holes]
    if positions:
        centre = _centre(measured)
        if centre is None:
            raise ValueError("hole positions need a module that reports bounding-box corners (item 57)")
        truth["holes_at_mm"] = [{"diameter_mm": hole["diameter_mm"], "through": hole.get("through", True), "at": [round(a - c, 3) for a, c in zip(hole["at"], centre)], "axis": list(hole["axis"])} for hole in holes]
    if measured["solids"] > 1:
        gaps = [gap["gap_mm"] for gap in measured.get("gaps") or [] if isinstance(gap, Mapping) and isinstance(gap.get("gap_mm"), (int, float))]
        if gaps:
            truth["min_gap_mm"] = min(gaps)
    return truth


def wilson(successes: int, trials: int, z: float = Z_95) -> tuple[float, float]:
    """The Wilson score interval for a pass rate. With no trials there is no information: (0, 1)."""
    if trials <= 0:
        return (0.0, 1.0)
    p = successes / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


# --- Reading a run ------------------------------------------------------------


@dataclass
class Build:
    """One cad_build call and its answer, in the order the model made them."""

    call_id: str
    name: str
    answer: dict[str, Any] | None
    passed: bool = False
    #: What the reader refused: error.refused, or error.construct from a module before item 55.
    refused: str | None = None
    step: str | None = None
    report: str | None = None


@dataclass
class Transcript:
    builds: list[Build] = field(default_factory=list)
    view_image_calls: int = 0
    final_text: str = ""
    #: cad_build results that were not an answer of the tool (the host refused the call).
    tool_errors: int = 0

    @property
    def delivered(self) -> Build | None:
        """The newest build that passed: the part the run hands over."""
        return next((build for build in reversed(self.builds) if build.passed), None)

    @property
    def builds_to_pass(self) -> int | None:
        return next((index for index, build in enumerate(self.builds, 1) if build.passed), None)

    @property
    def presented(self) -> bool:
        """The run ended on a build that passed and answered the user: the part is presented as finished."""
        return bool(self.builds) and self.builds[-1].passed and bool(self.final_text.strip())

    @property
    def refusals(self) -> Counter:
        return Counter(build.refused for build in self.builds if build.refused)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, Mapping) else part if isinstance(part, str) else "" for part in content)
    return ""


def _kind(message: Mapping[str, Any]) -> str:
    return str(message.get("type") or message.get("role") or "")


def _answer(content: Any) -> dict[str, Any] | None:
    try:
        value = json.loads(_text(content))
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def read_transcript(messages: Iterable[Mapping[str, Any]]) -> Transcript:
    """What the model did in one run, from its messages in order (event store rows' content or state messages)."""
    transcript = Transcript()
    builds: dict[str, Build] = {}
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        kind = _kind(message)
        if kind in ("ai", "assistant"):
            calls = [call for call in message.get("tool_calls") or [] if isinstance(call, Mapping)]
            for call in calls:
                name = str(call.get("name") or "")
                if name == VIEW_IMAGE_TOOL:
                    transcript.view_image_calls += 1
                elif CAD_TOOL in name:
                    args = call.get("args") if isinstance(call.get("args"), Mapping) else {}
                    build = Build(call_id=str(call.get("id") or len(transcript.builds)), name=str(args.get("name") or ""), answer=None)
                    builds[build.call_id] = build
                    transcript.builds.append(build)
            text = _text(message.get("content"))
            if not calls and text.strip():
                transcript.final_text = text
        elif kind == "tool":
            build = builds.get(str(message.get("tool_call_id") or ""))
            if build is None:
                continue
            answer = _answer(message.get("content"))
            if answer is None:
                transcript.tool_errors += 1
                continue
            build.answer = answer
            build.passed = answer.get("passed") is True
            error = answer.get("error") if isinstance(answer.get("error"), Mapping) else {}
            refused = error.get("refused") or error.get("construct")
            build.refused = str(refused) if refused else None
            files = [path for path in answer.get("files") or [] if isinstance(path, str)]
            build.step = next((path for path in files if path.endswith(".step")), None)
            build.report = next((path for path in files if path.endswith(".report.json")), None)
    return transcript


# --- One sample, and a run of them -------------------------------------------


@dataclass
class SampleResult:
    spec: str
    band: str
    sample: int
    thread_id: str = ""
    #: Why the run produced nothing to score: the Gateway failed, the run timed out.
    error: str | None = None
    builds: int = 0
    builds_to_pass: int | None = None
    self_passed: bool = False
    presented: bool = False
    truth_passed: bool = False
    truth: dict[str, Any] | None = None
    single_shot: bool = False
    refusals: dict[str, int] = field(default_factory=dict)
    view_image_calls: int = 0
    tool_errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float | None = None
    currency: str | None = None
    #: module_version and cadquery_version from the delivered report, when the module writes them (item 57).
    provenance: dict[str, Any] = field(default_factory=dict)
    expected_refused_seen: bool | None = None
    #: The no-module spec: the reply carried every phrase it must.
    reply_ok: bool | None = None
    #: ``direct``, or ``design``: an OpenSCAD draft first, then the port to CadQuery (design_path.py).
    path: str = "direct"
    #: The design path: the draft turn returned an OpenSCAD file, and how many builds it made anyway.
    draft_found: bool | None = None
    draft_builds: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Summary:
    samples: int
    truth_passes: int
    interval: tuple[float, float]
    self_passes: int
    presented: int
    presented_and_true: int
    single_shot: int
    builds_to_pass_mean: float | None
    repair_rounds_mean: float | None
    refusals: dict[str, int]
    view_image_calls: int
    total_tokens: int
    cost: float | None
    currency: str | None
    errors: int
    by_band: dict[str, list[int]]

    @property
    def claim_precision(self) -> float | None:
        return self.presented_and_true / self.presented if self.presented else None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"claim_precision": self.claim_precision}


def summarize(results: Sequence[SampleResult]) -> Summary:
    passes = sum(result.truth_passed for result in results)
    to_pass = [result.builds_to_pass for result in results if result.builds_to_pass]
    refusals: Counter = Counter()
    by_band: dict[str, list[int]] = {}
    for result in results:
        refusals.update(result.refusals)
        band = by_band.setdefault(result.band, [0, 0])
        band[0] += result.truth_passed
        band[1] += 1
    costs = [result.cost for result in results if result.cost is not None]
    currencies = {result.currency for result in results if result.currency}
    return Summary(
        samples=len(results),
        truth_passes=passes,
        interval=wilson(passes, len(results)),
        self_passes=sum(result.self_passed for result in results),
        presented=sum(result.presented for result in results),
        presented_and_true=sum(result.presented and result.truth_passed for result in results),
        single_shot=sum(result.single_shot for result in results),
        builds_to_pass_mean=statistics.fmean(to_pass) if to_pass else None,
        repair_rounds_mean=statistics.fmean(count - 1 for count in to_pass) if to_pass else None,
        refusals=dict(refusals.most_common()),
        view_image_calls=sum(result.view_image_calls for result in results),
        total_tokens=sum(result.total_tokens for result in results),
        # Spend is summed only in one currency; mixed currencies have no total.
        cost=round(sum(costs), 6) if costs and len(currencies) <= 1 else None,
        currency=next(iter(currencies)) if len(currencies) == 1 else None,
        errors=sum(result.error is not None for result in results),
        by_band=by_band,
    )


# --- The results table --------------------------------------------------------

TABLE_COLUMNS = (
    "Date",
    "Model",
    "Quant",
    "Window",
    "Module",
    "CadQuery",
    "Skill",
    "Specs",
    "k",
    "Truth pass (95% CI)",
    "Self-pass",
    "Claim precision",
    "Single-shot",
    "Repair rounds",
    "Refusals",
    "view_image",
    "Tokens / sample",
    "Spend",
)
TABLE_HEADER = "| " + " | ".join(TABLE_COLUMNS) + " |\n|" + "|".join(" --- " for _ in TABLE_COLUMNS) + "|"


def _percent(value: float) -> str:
    return f"{100 * value:.0f}%"


def _cell(value: Any) -> str:
    text = "—" if value in (None, "") else str(value)
    return text.replace("|", "/").replace("\n", " ")


def format_row(summary: Summary, meta: Mapping[str, Any]) -> str:
    """One dated row of the results table in docs/guide/cad-eval.md."""
    low, high = summary.interval
    n = summary.samples
    truth = f"{summary.truth_passes}/{n} {_percent(summary.truth_passes / n) if n else '—'} [{_percent(low)}–{_percent(high)}]"
    precision = f"{summary.presented_and_true}/{summary.presented}" + (f" {_percent(summary.claim_precision)}" if summary.claim_precision is not None else "")
    top = ", ".join(f"{name} {count}" for name, count in list(summary.refusals.items())[:3])
    refusals = f"{sum(summary.refusals.values())}" + (f" ({top})" if top else "")
    repair = f"{summary.repair_rounds_mean:.1f}" if summary.repair_rounds_mean is not None else None
    tokens = round(summary.total_tokens / n) if n else None
    spend = f"{summary.cost:.4f} {summary.currency or ''}".strip() if summary.cost is not None else None
    cells = (
        meta.get("date"),
        meta.get("model"),
        meta.get("quant"),
        meta.get("window"),
        meta.get("module_version"),
        meta.get("cadquery_version"),
        meta.get("skill"),
        meta.get("specs"),
        meta.get("k"),
        truth,
        f"{summary.self_passes}/{n}",
        precision,
        f"{summary.single_shot}/{n}",
        repair,
        refusals,
        summary.view_image_calls,
        tokens,
        spend,
    )
    return "| " + " | ".join(_cell(value) for value in cells) + " |"
