"""The secondary model, and the ground-truth checks that keep it honest.

A judge model asked "did this drift?" will agree with a confident, fluent
answer more often than it should. So the judged verdict is only half of a
result: the other half is :func:`grade_facts`, which checks the primary's
output against the facts planted at known pages. When the judge calls a run
clean and the primary silently missed a fact it claims to have read, that
disagreement is recorded as a *judge* failure, not smoothed away.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .corpus import PlantedFact
from .rubric import DRIFT_KINDS, JUDGE_SYSTEM, VERDICTS, Verdict, render_judge_prompt

logger = logging.getLogger(__name__)

# A fenced or bare JSON object anywhere in the reply. Small models wrap JSON in
# prose and fences no matter how the prompt is worded, so the parse tolerates
# both rather than failing a run over formatting.
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _text_of(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content)


def parse_judgement(reply: str) -> dict[str, Any] | None:
    """Pull the verdict object out of a judge reply, or None if there isn't one."""
    match = _JSON_RE.search(reply or "")
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalise(parsed: dict[str, Any]) -> dict[str, Any]:
    """Coerce a judge reply into the rubric's vocabulary.

    A judge that invents a drift category or a verdict spelling has not
    followed the rubric, and quietly accepting the invention would make two
    runs incomparable. Unknown values fall back to the safe reading — that
    something is wrong — rather than to PASS.
    """
    verdict = str(parsed.get("verdict", "")).strip().upper()
    kind = str(parsed.get("drift_kind", "")).strip().lower()
    return {
        "goal_preserved": bool(parsed.get("goal_preserved", False)),
        "drift_kind": kind if kind in DRIFT_KINDS else "none",
        "coverage_honest": bool(parsed.get("coverage_honest", False)),
        "answered_question": str(parsed.get("answered_question", "")).strip(),
        "verdict": verdict if verdict in VERDICTS else "FAIL",
        "rationale": str(parsed.get("rationale", "")).strip(),
    }


def grade_facts(output: str, facts: list[PlantedFact]) -> list[str]:
    """Return the ids of planted facts the output actually recovered.

    Matching is on the expected value's distinctive tokens rather than the
    whole string: a correct answer rephrases ("EUR 2,150,000", "2.15 million
    euro") and an exact-match check would score those as misses and make the
    whole measurement useless. Tokens are the figures and identifiers, which
    a correct answer has to carry in some form.
    """
    haystack = (output or "").lower()
    recovered: list[str] = []
    for fact in facts:
        tokens = [token.lower() for token in re.findall(r"[0-9][0-9,\.\-]*[0-9]|[A-Z]-?[0-9]+", fact.expected)]
        if not tokens:
            tokens = [fact.expected.lower()]
        # Every distinctive token has to appear: a date range answered with one
        # of its two dates is a partial recall, and counting it as a hit is how
        # a truncated read starts looking complete.
        if all(token in haystack for token in tokens):
            recovered.append(fact.id)
    return recovered


async def judge_run(
    model: Any,
    *,
    task: str,
    output: str,
    coverage: str,
    facts: list[PlantedFact],
) -> Verdict:
    """Grade one primary run: judged verdict plus the ground-truth check."""
    from langchain_core.messages import HumanMessage, SystemMessage

    recovered = grade_facts(output, facts)
    expected = [fact.id for fact in facts]

    reply = ""
    error: str | None = None
    try:
        response = await model.ainvoke([SystemMessage(content=JUDGE_SYSTEM), HumanMessage(content=render_judge_prompt(task, output, coverage))])
        reply = _text_of(response)
    except Exception as exc:
        logger.exception("Judge model call failed")
        error = f"{type(exc).__name__}: {exc}"

    parsed = parse_judgement(reply)
    if parsed is None and error is None:
        error = "the judge did not return a parseable JSON verdict"

    fields = _normalise(parsed) if parsed is not None else {}
    verdict = Verdict(**fields, judge_error=error, facts_expected=expected, facts_recovered=recovered)

    # The judge said the run was clean; the document says facts were missed.
    # Recording this as a judge failure is the whole reason the planted facts
    # exist — otherwise the evaluation is one model's opinion of another's.
    verdict.judge_disagrees_with_ground_truth = verdict.verdict == "PASS" and bool(verdict.facts_missed)
    return verdict
