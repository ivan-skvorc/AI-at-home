"""CLI for the CAD eval.

# every part spec, three samples each, against the running agent (needs `make dev` up)
PYTHONPATH=. uv run python -m scripts.benchmark.cad_eval run --model qwen3-32k

# one band, or named specs
PYTHONPATH=. uv run python -m scripts.benchmark.cad_eval run --model qwen3-32k --band holes --k 1
PYTHONPATH=. uv run python -m scripts.benchmark.cad_eval run --model qwen3-32k --spec h01-mounting-plate

# the one spec for a Gateway with the CAD module turned off
PYTHONPATH=. uv run python -m scripts.benchmark.cad_eval run --model qwen3-32k --no-module

# the spec set, without running anything
PYTHONPATH=. uv run python -m scripts.benchmark.cad_eval list
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .agent import DEFAULT_BASE_URL, DEFAULT_TIMEOUT_SECONDS, MeasureCli, SpendCapReached, StartRefused, check_gateway, download, headers, run_request, token_usage
from .score import TABLE_HEADER, Build, SampleResult, Transcript, format_row, judge_truth, read_transcript, summarize
from .specs import BANDS, NO_MODULE_BAND, Spec, SpecError, load_specs, spec_set_hash

logger = logging.getLogger("cad_eval")

DEFAULT_OUT_DIR = Path("/tmp/deer-flow-cad-eval")
SKILL_DIR = Path(__file__).resolve().parents[4] / "skills" / "public" / "cad-modeling"
USAGE = "cad-eval needs a model: make cad-eval MODEL=<a model name from config.yaml> [K=3] [BAND=prismatic|holes|fits] [SPEC=<id,...>]"
#: Exit statuses: a completed run, a run with samples that produced nothing to score, usage, refused to start.
EXIT_OK, EXIT_INCOMPLETE, EXIT_USAGE, EXIT_REFUSED = 0, 1, 2, 3


def skill_version(directory: Path = SKILL_DIR) -> str | None:
    """Twelve hex digits over the CAD skill's files: the procedure the model was given."""
    if not directory.is_dir():
        return None
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8") + b"\0" + path.read_bytes())
    return digest.hexdigest()[:12]


async def _judge(client: httpx.AsyncClient, measurer, result: SampleResult, build: Build, spec: Spec, directory: Path) -> dict[str, Any]:
    step = await download(client, result.thread_id, build.step, directory)
    measured = await asyncio.to_thread(measurer.measure, step)
    return judge_truth(measured, spec.truth, spec.orientation)


async def _provenance(client: httpx.AsyncClient, result: SampleResult, build: Build, directory: Path) -> dict[str, Any]:
    if not build.report:
        return {}
    try:
        report = json.loads((await download(client, result.thread_id, build.report, directory)).read_text(encoding="utf-8"))
    except (httpx.HTTPError, ValueError, OSError):
        return {}
    return {key: report[key] for key in ("module_version", "cadquery_version") if isinstance(report, dict) and report.get(key)}


def _facts(result: SampleResult, transcript: Transcript) -> None:
    result.builds = len(transcript.builds)
    result.builds_to_pass = transcript.builds_to_pass
    result.self_passed = transcript.delivered is not None
    result.presented = transcript.presented
    result.refusals = dict(transcript.refusals)
    result.view_image_calls = transcript.view_image_calls
    result.tool_errors = transcript.tool_errors


async def evaluate_sample(client: httpx.AsyncClient, spec: Spec, sample: int, *, model: str, measurer, out_dir: Path, timeout: float) -> SampleResult:
    """One request, one run, one score. Only a re-measured STEP decides the truth pass."""
    thread_id = f"cad-eval-{spec.id}-{sample}-{uuid.uuid4().hex[:8]}"
    result = SampleResult(spec=spec.id, band=spec.band, sample=sample, thread_id=thread_id)
    record = await run_request(client, prompt=spec.prompt(), model=model, thread_id=thread_id, timeout=timeout)
    result.error = record.error
    directory = out_dir / thread_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "messages.json").write_text(json.dumps(record.messages, indent=1, default=str), encoding="utf-8")

    transcript = read_transcript(record.messages)
    _facts(result, transcript)
    usage = await token_usage(client, thread_id)
    result.input_tokens = int(usage.get("total_input_tokens") or 0)
    result.output_tokens = int(usage.get("total_output_tokens") or 0)
    result.total_tokens = int(usage.get("total_tokens") or 0)
    result.cost = usage.get("total_cost")
    result.currency = usage.get("currency")

    if spec.band == NO_MODULE_BAND:
        reply = transcript.final_text.lower()
        result.reply_ok = not transcript.builds and all(phrase.lower() in reply for phrase in spec.reply_mentions)
        return result
    if spec.expected_refused is not None:
        result.expected_refused_seen = spec.expected_refused in result.refusals

    delivered = transcript.delivered
    if delivered is None or delivered.step is None or spec.truth is None:
        return result
    try:
        result.truth = await _judge(client, measurer, result, delivered, spec, directory)
        result.truth_passed = result.truth["passed"]
        first = transcript.builds[0]
        if first is delivered:
            result.single_shot = result.truth_passed
        elif first.passed and first.step:
            result.single_shot = (await _judge(client, measurer, result, first, spec, directory))["passed"]
    except Exception as exc:  # a download or measuring failure is this sample's result, not the run's end
        logger.debug("measuring %s failed", thread_id, exc_info=True)
        result.error = f"the delivered STEP could not be measured: {type(exc).__name__}: {exc}"
        result.truth_passed = False
    result.provenance = await _provenance(client, result, delivered, directory)
    return result


def _line(result: SampleResult) -> str:
    if result.reply_ok is not None:
        verdict = "PASS" if result.reply_ok else "FAIL"
    else:
        verdict = "TRUTH PASS" if result.truth_passed else "self-pass, truth FAIL" if result.self_passed else "no part"
    refusals = f", refused {sum(result.refusals.values())}" if result.refusals else ""
    error = f" !! {result.error}" if result.error else ""
    return f"  {result.spec} #{result.sample}: {verdict} ({result.builds} build(s){refusals}, {result.total_tokens} tokens){error}"


def _meta(args, facts, specs: list[Spec], results: list[SampleResult], now: datetime) -> dict[str, Any]:
    provenance = next((result.provenance for result in results if result.provenance), {})
    scope = args.band or ("specs" if args.spec else "all")
    return {
        "date": now.date().isoformat(),
        "model": args.model,
        "quant": args.quant,
        "window": facts.context_window,
        "module_version": provenance.get("module_version"),
        "cadquery_version": provenance.get("cadquery_version"),
        "skill": skill_version(),
        "specs": f"{spec_set_hash(specs)} ({scope})",
        "k": args.k,
    }


def _report(summary, row: str, stopped: str | None) -> None:
    print("")
    low, high = summary.interval
    print(f"truth pass      : {summary.truth_passes}/{summary.samples}  (95% CI {low:.0%}–{high:.0%})")
    print(f"self-pass       : {summary.self_passes}/{summary.samples}  (cad_build's own verdict on its own numbers)")
    precision = f"{summary.claim_precision:.0%}" if summary.claim_precision is not None else "—"
    print(f"claim precision : {summary.presented_and_true}/{summary.presented}  {precision}")
    print(f"single-shot     : {summary.single_shot}/{summary.samples}")
    if summary.repair_rounds_mean is not None:
        print(f"repair rounds   : {summary.repair_rounds_mean:.1f} on average before a build passed")
    print(f"refusals        : {json.dumps(summary.refusals)}")
    print("by band         : " + ", ".join(f"{band} {passed}/{total}" for band, (passed, total) in summary.by_band.items()))
    if summary.errors:
        print(f"!! {summary.errors} sample(s) produced nothing to score; see the record")
    if stopped:
        print(f"!! stopped early: {stopped}")
    print("")
    print(TABLE_HEADER)
    print(row)


async def run_eval(args, *, transport: httpx.AsyncBaseTransport | None = None, measurer=None, now: datetime | None = None) -> int:
    if not args.model:
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    if args.k < 1:
        print("cad-eval: --k must be at least 1", file=sys.stderr)
        return EXIT_USAGE
    try:
        if args.no_module:
            specs = load_specs(band=NO_MODULE_BAND)
        else:
            specs = load_specs(band=args.band, ids=args.spec.split(",") if args.spec else None)
    except SpecError as exc:
        print(f"cad-eval: {exc}", file=sys.stderr)
        return EXIT_USAGE
    pending = [spec for spec in specs if spec.band != NO_MODULE_BAND and spec.truth is None]
    for spec in pending:
        print(f"cad-eval: skipping {spec.id}: its truth is not derived yet (derive_truth.py)", file=sys.stderr)
    specs = [spec for spec in specs if spec not in pending]
    if not specs:
        print("cad-eval: no spec to run", file=sys.stderr)
        return EXIT_REFUSED

    measurer = measurer or MeasureCli(args.measure_python)
    if not args.no_module:
        problem = measurer.problem()
        if problem:
            print(f"cad-eval: not starting: {problem}", file=sys.stderr)
            return EXIT_REFUSED

    out_dir = Path(args.out_dir)
    results: list[SampleResult] = []
    stopped: str | None = None
    async with httpx.AsyncClient(base_url=args.base_url, headers=headers(), timeout=60, transport=transport) as client:
        try:
            facts = await check_gateway(client, args.model, module_on=not args.no_module)
        except StartRefused as exc:
            print(f"cad-eval: not starting: {exc}", file=sys.stderr)
            return EXIT_REFUSED
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"cad-eval: {len(specs)} spec(s) x {args.k} sample(s) on {args.model} at {args.base_url}", file=sys.stderr)
        spent = 0.0
        for spec in specs:
            for sample in range(1, args.k + 1):
                try:
                    result = await evaluate_sample(client, spec, sample, model=args.model, measurer=measurer, out_dir=out_dir, timeout=args.timeout)
                except SpendCapReached as exc:
                    stopped = f"the Gateway's spend cap refused the run (HTTP 402): {exc}"
                    break
                results.append(result)
                print(_line(result), file=sys.stderr)
                spent += result.cost or 0.0
                if args.max_cost is not None and spent >= args.max_cost:
                    stopped = f"spend cap of {args.max_cost:g} reached after {len(results)} sample(s) ({spent:g} spent)"
                    break
            if stopped:
                break

    now = now or datetime.now(UTC)
    summary = summarize(results)
    meta = _meta(args, facts, specs, results, now)
    row = format_row(summary, meta)
    record = {
        "generated_at": now.isoformat(),
        "settings": {"model": args.model, "provider_model": facts.provider_model, "k": args.k, "band": args.band, "spec": args.spec, "no_module": args.no_module, "base_url": args.base_url, "max_cost": args.max_cost},
        "meta": meta,
        "stopped": stopped,
        "summary": summary.to_dict(),
        "row": row,
        "samples": [result.to_dict() for result in results],
    }
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", args.model).strip("-") or "model"
    record_path = out_dir / f"cad-eval-{slug}-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    record_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

    if args.no_module:
        ok = bool(results) and all(result.reply_ok for result in results)
        print(f"\nno-module: {'PASS' if ok else 'FAIL'} ({sum(bool(result.reply_ok) for result in results)}/{len(results)} replies said how to find out why)")
        print(f"full record: {record_path}", file=sys.stderr)
        return EXIT_OK if ok and not stopped else EXIT_INCOMPLETE
    _report(summary, row, stopped)
    print(f"\nfull record: {record_path}", file=sys.stderr)
    # A measurement, not a gate: a low pass rate is a result. A run that could not score every sample is not.
    return EXIT_INCOMPLETE if stopped or summary.errors else EXIT_OK


def _list() -> int:
    for spec in [*load_specs(), *load_specs(band=NO_MODULE_BAND)]:
        needs = "; ".join(f"needs item {need.item} ({need.why})" for need in spec.needs)
        truth = "" if spec.truth or spec.band == NO_MODULE_BAND else " [truth not derived]"
        print(f"{spec.id:24} {spec.band:10} {spec.title}{truth}" + (f"  - {needs}" if needs else ""))
    print(f"\nspec set {spec_set_hash(load_specs())}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.benchmark.cad_eval", description="Score a model's CAD parts against ground truth it never saw.")
    parser.add_argument("command", choices=("run", "list"), nargs="?", default="run")
    parser.add_argument("--model", default=None, help="Model to run, by its name in config.yaml. Required for run.")
    parser.add_argument("--k", type=int, default=3, help="Samples per spec (default: 3; one sample of 20 specs has a standard error near 11%%).")
    parser.add_argument("--band", choices=BANDS, default=None, help="Run one band only.")
    parser.add_argument("--spec", default=None, help="Comma-separated spec ids to run.")
    parser.add_argument("--no-module", action="store_true", help="Run the one spec for a Gateway with the CAD module turned off.")
    parser.add_argument("--quant", default=None, help="Quantisation of a local model, recorded in the row (for example Q4_K_M).")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"Gateway base URL (default: {DEFAULT_BASE_URL}).")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help=f"Seconds to wait for one run (default: {DEFAULT_TIMEOUT_SECONDS}).")
    parser.add_argument("--max-cost", type=float, default=None, help="Stop starting samples once this much has been spent, in the Gateway's pricing currency.")
    parser.add_argument("--measure-python", default=sys.executable, help="Python with the CAD module installed, for measure_cli (default: this one).")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help=f"Where transcripts, STEP files and the run record go (default: {DEFAULT_OUT_DIR}).")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    if args.command == "list":
        return _list()
    return asyncio.run(run_eval(args))


if __name__ == "__main__":
    raise SystemExit(main())
