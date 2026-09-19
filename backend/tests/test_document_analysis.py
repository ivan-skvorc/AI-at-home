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
from deerflow.documents.extraction import page_anchor
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


def _paged_document(pages: int = 30) -> str:
    """A document carrying the page anchors a converted PDF would carry."""
    return "\n\n".join(f"{page_anchor(n)}\n## Section {n}\n\n" + ("word " * 200).strip() for n in range(1, pages + 1))


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
        answer, rounds, notes_truncated = await reduce_notes(model, ["note one", "note two"], "q", limit=10_000)
        assert not notes_truncated
        assert rounds == 0
        assert len(model.prompts) == 1
        assert answer == "a note"

    @pytest.mark.anyio
    async def test_notes_that_overflow_are_merged_in_rounds(self):
        model = _Model(reply="merged")
        notes = ["x" * 400 for _ in range(12)]
        answer, rounds, _ = await reduce_notes(model, notes, "q", limit=1_000)
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
        answer, _, _ = await reduce_notes(model, ["a" * 600 for _ in range(6)], "q", limit=1_000)
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


class TestChunkCeiling:
    """`documents.max_chunk_chars` must actually bind.

    A 128K-window model derives ~55K tokens per map call from its window alone,
    which is well past where long-input accuracy degrades whatever the window
    advertises — so the ceiling is the setting that keeps a large window from
    recreating the problem this feature exists to solve. It was documented and
    unread once; this pins the wiring, not just the helper.
    """

    @staticmethod
    def _map_calls(model) -> int:
        return sum(1 for prompt in model.prompts if "BEGIN PART" in prompt)

    @pytest.mark.anyio
    async def test_the_ceiling_bounds_a_large_window(self):
        # ~128K characters against a 128K-token window: unbounded, that is one
        # map call holding the whole document — the exact failure this feature
        # exists to remove. The ceiling must break it into many.
        model = _Model()
        big = ContextBudget(context_window=131_072, reserved_output=8_192)
        await analyze_document_text(_document(sections=200), "q", model, budget=big, max_chunk_chars=8_000)
        assert self._map_calls(model) >= 12, f"the ceiling did not bind: {self._map_calls(model)} map call(s)"

    @pytest.mark.anyio
    async def test_no_ceiling_leaves_the_window_in_charge(self):
        model = _Model()
        big = ContextBudget(context_window=131_072, reserved_output=8_192)
        await analyze_document_text(_document(sections=200), "q", model, budget=big)
        assert self._map_calls(model) == 1


class TestTruncationIsResumable:
    """A cap that returns a prefix must say which prefix, and how to continue.

    ``max_chunks`` binds hardest on exactly the models this feature exists for:
    a 300-page PDF chunks into ~150 parts against an 8K window, so the shipped
    cap of 60 reads the first 40% of the document. Against a cloud window the
    same document is ~21 parts and the cap never fires, which is why this is
    invisible until someone runs it on the small model.
    """

    @pytest.mark.anyio
    async def test_the_coverage_line_names_the_pages_that_were_read(self):
        result = await analyze_document_text(_paged_document(pages=30), "q", _Model(), chunk_chars=2_000)
        line = result.coverage_line()
        assert "pages" in line
        assert result.first_page == 1
        assert result.pages_total == 30

    @pytest.mark.anyio
    async def test_a_capped_read_reports_the_page_range_it_actually_covered(self):
        result = await analyze_document_text(_paged_document(pages=40), "q", _Model(), chunk_chars=2_000, max_chunks=3)
        assert result.truncated
        # The pages named are the ones read, not the whole document.
        assert result.last_page is not None
        assert result.last_page < 40
        assert f"of {result.pages_total}" in result.coverage_line()

    @pytest.mark.anyio
    async def test_a_capped_read_hands_back_the_part_to_resume_from(self):
        result = await analyze_document_text(_document(sections=60), "q", _Model(), chunk_chars=1_000, max_chunks=3)
        assert result.next_part == 4
        assert "start_part=4" in result.coverage_line()
        assert result.parts_unread == result.chunks_total - 3

    @pytest.mark.anyio
    async def test_resuming_reads_the_next_parts_not_the_first_ones_again(self):
        text = _document(sections=60)
        first = await analyze_document_text(text, "q", _Model(), chunk_chars=1_000, max_chunks=3)
        second = await analyze_document_text(text, "q", _Model(), chunk_chars=1_000, max_chunks=3, start_part=first.next_part)
        assert second.start_part == 4
        assert [n.chunk.index for n in second.notes] == [4, 5, 6]
        assert second.chunks_total == first.chunks_total

    @pytest.mark.anyio
    async def test_the_last_resumed_call_is_not_marked_truncated(self):
        text = _document(sections=10)
        total = len(chunk_document(text, chunk_chars=2_000))
        result = await analyze_document_text(text, "q", _Model(), chunk_chars=2_000, max_chunks=total, start_part=1)
        assert not result.truncated
        assert result.next_part is None

    @pytest.mark.anyio
    async def test_an_empty_capped_read_still_says_the_rest_is_unexamined(self):
        # "Nothing relevant" over the first 40% of a document is not the same
        # claim as "nothing relevant", and must not be returned as if it were.
        model = _Model(reply=NOTHING_RELEVANT)
        result = await analyze_document_text(_document(sections=60), "q", model, chunk_chars=1_000, max_chunks=3)
        assert "unexamined" in result.answer
        assert "start_part=" in result.coverage_line()


class TestReduceTruncationIsReported:
    @pytest.mark.anyio
    async def test_notes_dropped_at_the_reduce_stage_are_admitted(self):
        # Merging cannot shrink the notes here (the model echoes them back), so
        # the reduce stage runs out of rounds and has to drop content. Content
        # that was read but never reached the answer is a coverage gap.
        model = _Model(replies={"consolidating": "z" * 4_000}, reply="final")
        _, _, notes_truncated = await reduce_notes(model, ["z" * 4_000 for _ in range(8)], "q", limit=1_000)
        assert notes_truncated

    def test_the_coverage_line_says_so(self):
        result = AnalysisResult(answer="x", chunks_total=4, chunks_read=4, chunks_relevant=4, notes_truncated=True)
        assert "not in this answer" in result.coverage_line()

    def test_a_reduce_that_fits_reports_nothing(self):
        result = AnalysisResult(answer="x", chunks_total=4, chunks_read=4, chunks_relevant=4)
        assert "not in this answer" not in result.coverage_line()
