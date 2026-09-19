"""CLI for the mission-drift evaluation.

# one command: generate a 300-page PDF, run it, judge it
PYTHONPATH=. uv run python -m scripts.benchmark.drift_eval run --pages 300

# the same, through the whole agent loop (needs `make dev` up)
PYTHONPATH=. uv run python -m scripts.benchmark.drift_eval run --mode agent

# show what a capped read looked like before it could be resumed
PYTHONPATH=. uv run python -m scripts.benchmark.drift_eval run --no-follow-resumption
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from .corpus import Corpus, build_corpus, load_corpus
from .judge import judge_run
from .rubric import Verdict

logger = logging.getLogger("drift_eval")

DEFAULT_OUT_DIR = Path("/tmp/deer-flow-drift-eval")


def _task_for(corpus: Corpus, fact_id: str) -> str:
    """The instruction given to the primary.

    Deliberately narrow and explicit about its own shape. Drift is only
    measurable against a task that has one right form of answer: "summarise
    this report" cannot drift, because every output satisfies it.
    """
    fact = corpus.fact(fact_id)
    return (
        f"{fact.question}\n\n"
        "Answer with that specific information and nothing else. Do not summarise the document, "
        "do not describe its structure, and do not list what other sections contain. "
        "If the document does not state it, say so plainly and say which pages you checked."
    )


def _model(name: str | None):
    from deerflow.config.app_config import get_app_config
    from deerflow.models import create_chat_model

    return create_chat_model(name, app_config=get_app_config())


def _budget_for(model, explicit_window: int | None):
    from deerflow.config.app_config import get_app_config
    from deerflow.utils.context_budget import ContextBudget, resolve_context_budget

    if explicit_window:
        # An explicit window is how you reproduce a small-model failure without
        # owning the small model: the caps that bind at 8K bind the same way
        # whoever is serving the tokens.
        return ContextBudget(context_window=explicit_window, reserved_output=explicit_window // 4)
    return resolve_context_budget(model, get_app_config())


async def _run_pipeline(args, corpus: Corpus, task: str) -> dict:
    from .pipeline import load_markdown, run_primary

    primary = _model(args.primary_model)
    text = await load_markdown(corpus.pdf_path)
    budget = _budget_for(primary, args.context_window)
    run = await run_primary(
        primary,
        text,
        task,
        budget=budget,
        max_chunk_chars=args.max_chunk_chars,
        max_chunks=args.max_chunks,
        concurrency=args.concurrency,
        follow_resumption=not args.no_follow_resumption,
    )
    return run.to_dict() | {"markdown_chars": len(text)}


async def _run_agent(args, corpus: Corpus, task: str) -> dict:
    from .agent import run_agent_primary

    run = await run_agent_primary(corpus.pdf_path, task, base_url=args.base_url, timeout=args.timeout)
    return run.to_dict()


async def _main(args) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.manifest:
        corpus = load_corpus(Path(args.manifest))
    else:
        print(f"building a {args.pages}-page synthetic PDF in {out_dir} ...", file=sys.stderr)
        corpus = build_corpus(out_dir, pages=args.pages)
    print(f"corpus: {corpus.pdf_path} ({corpus.pages} pages, {len(corpus.facts)} planted facts)", file=sys.stderr)

    if args.command == "build-corpus":
        print(json.dumps({"pdf": str(corpus.pdf_path), "manifest": str(corpus.manifest_path), "pages": corpus.pages}, indent=2))
        return 0

    task = _task_for(corpus, args.fact)
    target = corpus.fact(args.fact)
    print(f"task    : {target.question}", file=sys.stderr)
    print(f"target  : {target.expected} (planted on page {target.page} of {corpus.pages})", file=sys.stderr)
    print(f"mode    : {args.mode}", file=sys.stderr)

    primary_result = await (_run_agent(args, corpus, task) if args.mode == "agent" else _run_pipeline(args, corpus, task))

    verdict = Verdict(judge_error="the judge was not run (--no-judge)", facts_expected=[f.id for f in corpus.facts])
    if not args.no_judge:
        from .judge import grade_facts

        verdict = await judge_run(
            _model(args.judge_model),
            task=task,
            output=primary_result.get("answer", ""),
            coverage=primary_result.get("coverage", ""),
            facts=corpus.facts,
        )
        # Only the targeted fact was asked for; the others are placement
        # controls, so recall is reported against the one that was requested.
        verdict.facts_expected = [target.id]
        verdict.facts_recovered = [fid for fid in grade_facts(primary_result.get("answer", ""), [target]) if fid]
        verdict.judge_disagrees_with_ground_truth = verdict.verdict == "PASS" and bool(verdict.facts_missed)

    record = {
        "generated_at": datetime.now(UTC).isoformat(),
        "synthetic": True,
        "mode": args.mode,
        "corpus": {"pdf": str(corpus.pdf_path), "manifest": str(corpus.manifest_path), "pages": corpus.pages},
        "task": task,
        "target_fact": {"id": target.id, "page": target.page, "expected": target.expected},
        "settings": {
            "primary_model": args.primary_model,
            "judge_model": args.judge_model,
            "context_window": args.context_window,
            "max_chunks": args.max_chunks,
            "max_chunk_chars": args.max_chunk_chars,
            "follow_resumption": not args.no_follow_resumption,
        },
        "primary": primary_result,
        "judge": verdict.to_dict(),
    }

    record_path = out_dir / f"drift-eval-{args.mode}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    _report(record)
    print(f"\nfull record: {record_path}", file=sys.stderr)

    # Exit non-zero on drift so this can gate a change rather than only inform.
    return 0 if verdict.verdict == "PASS" and not verdict.judge_disagrees_with_ground_truth else 1


def _report(record: dict) -> None:
    primary = record["primary"]
    judge = record["judge"]
    target = record["target_fact"]

    print("")
    print(f"VERDICT: {judge['verdict']}")
    print(f"  goal preserved     : {'yes' if judge['goal_preserved'] else 'no'}    ({judge['drift_kind']})")
    print(f"  coverage honest    : {'yes' if judge['coverage_honest'] else 'no'}")
    print(f"  answered           : {judge['answered_question'] or '(not stated)'}")
    print(f"  target fact        : {'RECOVERED' if target['id'] in judge['facts_recovered'] else 'MISSED'} — {target['expected']} (page {target['page']})")
    if primary.get("parts_total"):
        pages = primary.get("pages_covered") or [None, None]
        print(f"  coverage           : {primary['parts_read']}/{primary['parts_total']} parts, pages {pages[0]}-{pages[1]}, {primary['hops']} hop(s), complete={primary.get('fully_covered')}")
    if "used_analyze_document" in primary:
        print(f"  used analyze_document: {'yes' if primary['used_analyze_document'] else 'no'}    tools: {', '.join(primary.get('tool_calls') or []) or '(none)'}")
    if judge.get("rationale"):
        print(f"  rationale          : {judge['rationale']}")
    if judge.get("judge_disagrees_with_ground_truth"):
        print("  !! the judge passed a run that missed the planted fact — the JUDGE failed here, not just the primary")
    for problem in (primary.get("error"), judge.get("judge_error")):
        if problem:
            print(f"  !! {problem}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.benchmark.drift_eval", description="Measure mission drift when a model analyses a large PDF.")
    parser.add_argument("command", choices=("run", "build-corpus"), nargs="?", default="run")
    parser.add_argument("--mode", choices=("pipeline", "agent"), default="pipeline", help="pipeline: the analyze_document map-reduce directly. agent: the whole loop through a running Gateway.")
    parser.add_argument("--pages", type=int, default=300, help="Pages in the generated PDF (default: 300).")
    parser.add_argument("--manifest", help="Reuse a corpus already generated, instead of building a new one.")
    parser.add_argument("--fact", default="NEEDLE-GAMMA", help="Which planted fact to ask about. GAMMA sits near the end, where a capped read never reaches.")
    parser.add_argument("--primary-model", default=None, help="Model doing the work. Default: the first model in config.yaml.")
    parser.add_argument("--judge-model", default=None, help="Model grading the drift. Default: the first model in config.yaml — set this to a different, stronger model for a meaningful judgement.")
    parser.add_argument("--context-window", type=int, default=None, help="Pretend the primary has this window, to reproduce a small-model failure on any model.")
    parser.add_argument("--max-chunks", type=int, default=60, help="Parts read per call, mirroring documents.max_chunks (default: 60).")
    parser.add_argument("--max-chunk-chars", type=int, default=60_000, help="Ceiling on the derived chunk size (default: 60000).")
    parser.add_argument("--concurrency", type=int, default=2, help="Parallel map calls (default: 2).")
    parser.add_argument("--no-follow-resumption", action="store_true", help="Stop at the first capped read instead of resuming — reproduces the pre-fix behaviour.")
    parser.add_argument("--no-judge", action="store_true", help="Run the primary only; skip the secondary model.")
    parser.add_argument("--base-url", default="http://localhost:8001", help="Gateway base URL for --mode agent.")
    parser.add_argument("--timeout", type=float, default=3_600, help="Seconds to wait for an agent run (default: 3600).")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help=f"Where the corpus and run records go (default: {DEFAULT_OUT_DIR}).")
    return parser


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(_main(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
