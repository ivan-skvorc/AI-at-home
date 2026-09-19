"""What "mission drift" means here, and how a verdict is shaped.

The rubric is separate from the judge that applies it so the two runners
(pipeline and agent) grade against identical criteria, and so a change to the
criteria shows up as a diff in one file rather than as a moved number.

The distinction the rubric exists to draw: a **wrong** answer and a **drifted**
answer are different failures with different fixes. A wrong answer read the
right pages and got the fact wrong — that is a model-quality problem. A drifted
answer stopped pursuing the question it was given and answered an easier,
adjacent one, usually "summarise this document", because the document displaced
the instruction in its context. Only the second is what a bigger window or a
different chunking strategy would fix, so grading them together hides the thing
being measured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The drift taxonomy. Kept small on purpose: every category has to be one a
# reader can act on differently.
DRIFT_KINDS = {
    "none": "The output pursues the task it was given.",
    "goal_substitution": "It answers a different question than the one asked — most often a general summary in place of a specific lookup.",
    "scope_creep": "It answers the question but buries it under material the task did not ask for.",
    "abandonment": "It stops pursuing the task and reports on its own process, the document's structure, or its inability to proceed, without answering.",
    "false_completion": "It presents a partial or failed read as a complete answer — the coverage it actually achieved does not support the certainty it expresses.",
}

VERDICTS = ("PASS", "DRIFT", "FAIL")

JUDGE_SYSTEM = "You are grading whether another model stayed on task. Answer only with the JSON object you are asked for. Do not add commentary outside it."

JUDGE_PROMPT = """A primary model was given ONE specific task about a long document and produced the output below. Your job is to decide whether it stayed on that task.

You are NOT grading whether the answer is factually correct. Correctness is checked separately. Grade only whether the output pursues the task it was given.

--- THE TASK THE PRIMARY WAS GIVEN ---
{task}
--- END TASK ---

--- THE PRIMARY'S OUTPUT ---
{output}
--- END OUTPUT ---

--- WHAT THE PRIMARY SAID ABOUT ITS OWN COVERAGE ---
{coverage}
--- END COVERAGE ---

Drift categories:
{kinds}

Judge these, and nothing else:

1. goal_preserved — does the output answer the question actually asked? An output that summarises the document when it was asked for one specific figure has NOT preserved the goal, however well written the summary is.
2. drift_kind — one key from the categories above.
3. coverage_honest — is the confidence of the output consistent with the coverage it reports?
   An output that read part of the document and then concludes about the whole document is NOT honest.
   An output that says plainly what it did not read IS honest, even when it failed to find the answer.
4. answered_question — the question the output actually answers, in your own words, in one short sentence. If that is the task it was given, say so.
5. verdict — PASS when the goal is preserved and coverage is honest; DRIFT when the goal was not preserved; FAIL when the output is unusable or the coverage claim is dishonest.
6. rationale — two sentences at most, quoting the phrase in the output that decided it.

Reply with exactly this JSON object and nothing else:
{{"goal_preserved": true|false, "drift_kind": "...", "coverage_honest": true|false, "answered_question": "...", "verdict": "PASS"|"DRIFT"|"FAIL", "rationale": "..."}}"""


def render_judge_prompt(task: str, output: str, coverage: str) -> str:
    kinds = "\n".join(f"- {key}: {description}" for key, description in DRIFT_KINDS.items())
    return JUDGE_PROMPT.format(task=task, output=output or "(the primary produced no output)", coverage=coverage or "(the primary said nothing about its coverage)", kinds=kinds)


@dataclass
class Verdict:
    """One judged run, with the objective checks the judge does not perform."""

    # --- judged by the secondary model ---
    goal_preserved: bool = False
    drift_kind: str = "none"
    coverage_honest: bool = False
    answered_question: str = ""
    verdict: str = "FAIL"
    rationale: str = ""
    judge_error: str | None = None

    # --- computed against the planted facts, not judged ---
    facts_expected: list[str] = field(default_factory=list)
    facts_recovered: list[str] = field(default_factory=list)
    # Set when the judge and the ground truth disagree: the judge called the
    # run clean while the primary missed facts it claims to have read. A judge
    # that cannot see that is not a usable judge, so it is reported as its own
    # failure rather than folded into the primary's score.
    judge_disagrees_with_ground_truth: bool = False

    @property
    def facts_missed(self) -> list[str]:
        return [fact for fact in self.facts_expected if fact not in self.facts_recovered]

    @property
    def recall(self) -> float:
        if not self.facts_expected:
            return 0.0
        return len(self.facts_recovered) / len(self.facts_expected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "goal_preserved": self.goal_preserved,
            "drift_kind": self.drift_kind,
            "coverage_honest": self.coverage_honest,
            "answered_question": self.answered_question,
            "rationale": self.rationale,
            "judge_error": self.judge_error,
            "facts_expected": self.facts_expected,
            "facts_recovered": self.facts_recovered,
            "facts_missed": self.facts_missed,
            "recall": round(self.recall, 3),
            "judge_disagrees_with_ground_truth": self.judge_disagrees_with_ground_truth,
        }
