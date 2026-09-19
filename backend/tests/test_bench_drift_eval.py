"""Offline tests for the mission-drift evaluation harness.

No network, no provider credentials, no generated PDF larger than a test can
afford. The properties that matter are the grading ones: a harness that scores
a drifted run as clean is worse than no harness, because it converts an unknown
into a false assurance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark.drift_eval.corpus import PlantedFact, build_corpus, default_facts, load_corpus
from scripts.benchmark.drift_eval.judge import grade_facts, judge_run, parse_judgement
from scripts.benchmark.drift_eval.rubric import DRIFT_KINDS, Verdict, render_judge_prompt


class _Response:
    def __init__(self, content):
        self.content = content


class _Judge:
    """A judge model that returns whatever verdict the test needs."""

    def __init__(self, reply, fail=False):
        self.reply = reply
        self.fail = fail
        self.prompts: list[str] = []

    async def ainvoke(self, messages):
        self.prompts.append(messages[-1].content)
        if self.fail:
            raise RuntimeError("judge unavailable")
        return _Response(self.reply)


def _clean_verdict(**overrides) -> str:
    body = {
        "goal_preserved": True,
        "drift_kind": "none",
        "coverage_honest": True,
        "answered_question": "the decommission date",
        "verdict": "PASS",
        "rationale": "answers the question asked",
    }
    body.update(overrides)
    return json.dumps(body)


class TestCorpus:
    def test_facts_are_placed_across_the_document_not_bunched(self):
        facts = default_facts(300)
        pages = sorted(fact.page for fact in facts)
        assert pages[0] < 100 < pages[1] < pages[-1]
        # The last fact must sit where a capped prefix read never reaches.
        assert pages[-1] > 290

    def test_a_generated_corpus_round_trips_through_its_manifest(self, tmp_path: Path):
        pytest.importorskip("pymupdf")
        corpus = build_corpus(tmp_path, pages=6)
        reloaded = load_corpus(corpus.manifest_path)
        assert reloaded.pages == 6
        assert [f.id for f in reloaded.facts] == [f.id for f in corpus.facts]
        assert reloaded.pdf_path.is_file()

    def test_the_corpus_identifies_itself_as_synthetic(self, tmp_path: Path):
        pytest.importorskip("pymupdf")
        corpus = build_corpus(tmp_path, pages=4)
        manifest = json.loads(corpus.manifest_path.read_text(encoding="utf-8"))
        assert manifest["synthetic"] is True
        assert "SYNTHETIC" in manifest["banner"]

    def test_an_unknown_fact_id_is_an_error_not_a_silent_none(self, tmp_path: Path):
        pytest.importorskip("pymupdf")
        corpus = build_corpus(tmp_path, pages=4)
        with pytest.raises(KeyError):
            corpus.fact("NEEDLE-OMEGA")


class TestFactGrading:
    """Recall is the objective half of the score, so its edges decide everything."""

    FACT = PlantedFact(id="F", page=9, sentence="s", question="q", expected="moved from 2029-11-02 to 2031-04-18")

    def test_a_rephrased_but_correct_answer_counts_as_recovered(self):
        answer = "The date moved to 2031-04-18, having previously been 2029-11-02."
        assert grade_facts(answer, [self.FACT]) == ["F"]

    def test_a_half_answer_is_not_counted_as_recovered(self):
        # Half a date range answered as if it were the whole one is exactly how
        # a truncated read starts scoring as a complete one.
        assert grade_facts("The decommission date is 2031-04-18.", [self.FACT]) == []

    def test_an_absent_fact_is_not_recovered(self):
        assert grade_facts("The report does not state a decommission date.", [self.FACT]) == []

    def test_an_empty_output_recovers_nothing(self):
        assert grade_facts("", [self.FACT]) == []

    def test_an_identifier_token_is_matched(self):
        fact = PlantedFact(id="G", page=1, sentence="s", question="q", expected="47.3 microsieverts at station K-9")
        assert grade_facts("47.3 microsieverts, measured at K-9.", [fact]) == ["G"]


class TestJudgeParsing:
    def test_a_fenced_verdict_is_still_read(self):
        assert parse_judgement("```json\n" + _clean_verdict() + "\n```") is not None

    def test_prose_around_the_object_is_tolerated(self):
        assert parse_judgement("Here is my verdict:\n" + _clean_verdict() + "\nHope that helps.") is not None

    def test_a_reply_with_no_object_is_none(self):
        assert parse_judgement("I think it did fine.") is None

    def test_malformed_json_is_none_rather_than_a_crash(self):
        assert parse_judgement('{"verdict": PASS,}') is None


class TestJudging:
    FACTS = [PlantedFact(id="F", page=9, sentence="s", question="q", expected="2031-04-18")]

    @pytest.mark.anyio
    async def test_a_clean_run_passes(self):
        verdict = await judge_run(_Judge(_clean_verdict()), task="t", output="The date is 2031-04-18.", coverage="read 3 of 3 parts", facts=self.FACTS)
        assert verdict.verdict == "PASS"
        assert verdict.facts_recovered == ["F"]
        assert not verdict.judge_disagrees_with_ground_truth

    @pytest.mark.anyio
    async def test_a_judge_that_passes_a_run_missing_the_fact_is_flagged(self):
        # The point of planting facts: a judge agreeing with a fluent wrong
        # answer is a judge failure, and must not read as a clean result.
        verdict = await judge_run(_Judge(_clean_verdict()), task="t", output="The report covers operations across all sections.", coverage="read 3 of 3 parts", facts=self.FACTS)
        assert verdict.verdict == "PASS"
        assert verdict.facts_missed == ["F"]
        assert verdict.judge_disagrees_with_ground_truth

    @pytest.mark.anyio
    async def test_an_unknown_drift_kind_does_not_become_a_new_category(self):
        verdict = await judge_run(_Judge(_clean_verdict(drift_kind="vibes")), task="t", output="2031-04-18", coverage="", facts=self.FACTS)
        assert verdict.drift_kind in DRIFT_KINDS

    @pytest.mark.anyio
    async def test_an_unknown_verdict_fails_closed(self):
        verdict = await judge_run(_Judge(_clean_verdict(verdict="probably fine")), task="t", output="2031-04-18", coverage="", facts=self.FACTS)
        assert verdict.verdict == "FAIL"

    @pytest.mark.anyio
    async def test_an_unparseable_judge_reply_is_recorded_not_swallowed(self):
        verdict = await judge_run(_Judge("looks good to me"), task="t", output="2031-04-18", coverage="", facts=self.FACTS)
        assert verdict.judge_error
        assert verdict.verdict == "FAIL"

    @pytest.mark.anyio
    async def test_a_judge_that_raises_is_recorded_not_swallowed(self):
        verdict = await judge_run(_Judge("", fail=True), task="t", output="2031-04-18", coverage="", facts=self.FACTS)
        assert verdict.judge_error and "RuntimeError" in verdict.judge_error
        # The ground-truth half still works when the judge is down.
        assert verdict.facts_recovered == ["F"]

    @pytest.mark.anyio
    async def test_the_judge_is_shown_the_coverage_line(self):
        judge = _Judge(_clean_verdict())
        await judge_run(judge, task="t", output="o", coverage="read 60 of 150 parts; pages 1-121 of 300", facts=self.FACTS)
        assert "pages 1-121 of 300" in judge.prompts[0]


class TestRubric:
    def test_the_prompt_separates_drift_from_correctness(self):
        prompt = render_judge_prompt("task", "output", "coverage")
        assert "NOT grading whether the answer is factually correct" in prompt

    def test_every_drift_kind_reaches_the_prompt(self):
        prompt = render_judge_prompt("t", "o", "c")
        for kind in DRIFT_KINDS:
            assert kind in prompt

    def test_an_empty_output_is_described_rather_than_left_blank(self):
        assert "(the primary produced no output)" in render_judge_prompt("t", "", "c")

    def test_recall_is_zero_not_a_crash_when_nothing_is_expected(self):
        assert Verdict().recall == 0.0
