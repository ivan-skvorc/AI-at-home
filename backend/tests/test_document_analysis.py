"""Tests for map-reduce document analysis (fork feature).

The agent loop asks the model to navigate a long document itself, which is the
first thing a small quantized model loses under long input. This module inverts
that: no model call ever sees more than one chunk.

The properties under test:
- no single call receives the whole document, whatever its length;
- an irrelevant chunk costs one sentinel token, not a paragraph;
- the reduce is hierarchical, so notes that outgrow the window are merged in
  rounds rather than overflowing it;
- coverage is reported honestly — a part that could not be read is counted and
  said out loud, never quietly dropped from the answer.
"""

from __future__ import annotations

import pytest

from deerflow.documents.analysis import (
    FAILED_NOTE,
    NOTHING_RELEVANT,
    AnalysisResult,
    ChunkNote,
    analyze_document_text,
    map_chunks,
    reduce_notes,
)
from deerflow.documents.chunking import chunk_document
from deerflow.utils.context_budget import ContextBudget


class _Response:
    def __init__(self, content):
        self.content = content


class _Model:
    """Records every prompt it is given."""

    def __init__(self, reply="a note", replies=None, fail_on=()):
        self.reply = reply
        self.replies = replies or {}
        self.fail_on = set(fail_on)
        self.prompts: list[str] = []

    async def ainvoke(self, messages):
        prompt = messages[0].content
        self.prompts.append(prompt)
        index = len(self.prompts)
        if index in self.fail_on:
            raise RuntimeError("model call failed")
        for needle, reply in self.replies.items():
            if needle in prompt:
                return _Response(reply)
        return _Response(self.reply)


def _document(sections: int = 30) -> str:
    return "\n\n".join(f"## Section {n}\n\n" + ("word " * 200).strip() for n in range(1, sections + 1))


class TestMapStage:
    @pytest.mark.anyio
    async def test_each_call_sees_one_chunk_only(self):
        text = _document(sections=20)
        chunks = chunk_document(text, chunk_chars=2_000)
        model = _Model()
        await map_chunks(model, chunks, "what is here?", concurrency=1)
        assert len(model.prompts) == len(chunks)
        assert all(len(prompt) < len(text) for prompt in model.prompts)

    @pytest.mark.anyio
    async def test_the_prompt_carries_the_chunk_coordinate(self):
        chunks = chunk_document(_document(sections=6), chunk_chars=2_000)
        model = _Model()
        await map_chunks(model, chunks, "q", concurrency=1)
        assert chunks[0].label in model.prompts[0]

    @pytest.mark.anyio
    async def test_a_failed_chunk_is_marked_not_dropped(self):
        chunks = chunk_document(_document(sections=6), chunk_chars=2_000)
        notes = await map_chunks(_Model(fail_on={1}), chunks, "q", concurrency=1)
        assert notes[0].failed
        assert notes[0].text == FAILED_NOTE
        assert len(notes) == len(chunks)


class TestChunkNoteRelevance:
    def _note(self, text, failed=False):
        chunk = chunk_document("# H\n\nbody", chunk_chars=1_000)[0]
        return ChunkNote(chunk=chunk, text=text, failed=failed)

    def test_the_sentinel_marks_a_chunk_irrelevant(self):
        assert not self._note(NOTHING_RELEVANT).relevant
        assert not self._note("nothing relevant").relevant

    def test_a_real_note_is_relevant(self):
        assert self._note("Revenue was $4.2m on page 12.").relevant

    def test_a_failed_note_is_never_relevant(self):
        assert not self._note(FAILED_NOTE, failed=True).relevant

    def test_an_empty_note_is_not_relevant(self):
        assert not self._note("   ").relevant


class TestHierarchicalReduce:
    @pytest.mark.anyio
    async def test_notes_that_fit_are_reduced_in_one_call(self):
        model = _Model()
        answer, rounds = await reduce_notes(model, ["note one", "note two"], "q", limit=10_000)
        assert rounds == 0
        assert len(model.prompts) == 1
        assert answer == "a note"

    @pytest.mark.anyio
    async def test_notes_that_overflow_are_merged_in_rounds(self):
        model = _Model(reply="merged")
        notes = ["x" * 400 for _ in range(12)]
        answer, rounds = await reduce_notes(model, notes, "q", limit=1_000)
        assert rounds >= 1
        # More calls than a single reduce: the intermediate merges happened.
        assert len(model.prompts) > 1
        assert answer == "merged"

    @pytest.mark.anyio
    async def test_no_reduce_prompt_ever_exceeds_the_limit_by_much(self):
        model = _Model(reply="m")
        notes = ["y" * 900 for _ in range(20)]
        await reduce_notes(model, notes, "q", limit=1_000)
        # The prompt template adds a fixed preamble; the notes payload itself is
        # what must stay bounded.
        assert all(len(p) < 4_000 for p in model.prompts)

    @pytest.mark.anyio
    async def test_a_failed_merge_falls_back_to_the_raw_notes(self):
        model = _Model(reply="ok", fail_on={1})
        answer, _ = await reduce_notes(model, ["a" * 600 for _ in range(6)], "q", limit=1_000)
        assert answer == "ok"


class TestAnalyzeDocumentText:
    @pytest.mark.anyio
    async def test_a_local_window_produces_more_map_calls_than_a_cloud_one(self):
        text = _document(sections=400)
        local = _Model()
        cloud = _Model()
        await analyze_document_text(text, "q", local, budget=ContextBudget(context_window=32_768, reserved_output=8_192))
        await analyze_document_text(text, "q", cloud, budget=ContextBudget(context_window=200_000, reserved_output=32_000))
        assert len(local.prompts) > len(cloud.prompts)

    @pytest.mark.anyio
    async def test_an_empty_document_says_so(self):
        result = await analyze_document_text("   ", "q", _Model())
        assert "empty" in result.answer.lower()

    @pytest.mark.anyio
    async def test_irrelevant_chunks_do_not_reach_the_reduce_stage(self):
        model = _Model(reply=NOTHING_RELEVANT)
        result = await analyze_document_text(_document(sections=10), "q", model, chunk_chars=2_000)
        assert result.chunks_relevant == 0
        assert "Nothing in the parts that were read" in result.answer

    @pytest.mark.anyio
    async def test_unreadable_parts_are_admitted_in_the_answer(self):
        model = _Model(reply=NOTHING_RELEVANT, fail_on={1, 2})
        result = await analyze_document_text(_document(sections=10), "q", model, chunk_chars=2_000)
        assert result.chunks_failed == 2
        assert "could not be read" in result.answer

    @pytest.mark.anyio
    async def test_max_chunks_stops_early_and_says_so(self):
        result = await analyze_document_text(_document(sections=60), "q", _Model(), chunk_chars=1_000, max_chunks=3)
        assert result.truncated
        assert result.chunks_read == 3
        assert result.chunks_total > 3
        assert "stopped early" in result.coverage_line()

    @pytest.mark.anyio
    async def test_coverage_line_states_what_was_read(self):
        result = await analyze_document_text(_document(sections=8), "q", _Model(), chunk_chars=2_000)
        assert "read" in result.coverage_line()
        assert "contributed" in result.coverage_line()

    @pytest.mark.anyio
    async def test_a_failed_synthesis_keeps_the_notes(self):
        # Map calls succeed, the final reduce fails: the answer must admit it
        # rather than return an empty string.
        model = _Model()
        chunks = len(chunk_document(_document(sections=6), chunk_chars=2_000))
        model.fail_on = {chunks + 1}
        result = await analyze_document_text(_document(sections=6), "q", model, chunk_chars=2_000)
        assert "synthesis step failed" in result.answer
        assert result.notes


class TestAnalysisResultReporting:
    def test_a_clean_run_reports_no_failures(self):
        result = AnalysisResult(answer="x", chunks_total=4, chunks_read=4, chunks_relevant=2)
        line = result.coverage_line()
        assert "read 4 of 4 parts" in line
        assert "could not be read" not in line
