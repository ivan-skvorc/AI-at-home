"""Tests for context-aware document chunking (fork feature).

The chunk is the unit of work for the map stage, so its size is what lets one
code path serve a local 8B and a frontier cloud model. Three properties carry
the design:

- the size follows the serving model's window — bigger on cloud, smaller on
  local — without anyone configuring it per model;
- boundaries are structural (heading, then page anchor, then blank line), so a
  chunk stays self-describing instead of starting mid-sentence;
- every chunk carries the coordinates needed to cite it: line range, and the
  page it starts on when the document was anchored.
"""

from __future__ import annotations

from deerflow.documents.chunking import chunk_document
from deerflow.documents.extraction import page_anchor
from deerflow.utils.context_budget import ContextBudget

LOCAL = ContextBudget(context_window=32_768, reserved_output=8_192)
CLOUD = ContextBudget(context_window=200_000, reserved_output=32_000)


def _document(sections: int = 400, body_chars: int = 600) -> str:
    parts = []
    for n in range(1, sections + 1):
        parts.append(f"{page_anchor(n)}\n## Section {n}\n\n" + ("word " * (body_chars // 5)).strip())
    return "\n\n".join(parts)


class TestSizingFollowsTheModel:
    def test_a_cloud_window_produces_fewer_larger_chunks_than_a_local_one(self):
        text = _document()
        local = chunk_document(text, budget=LOCAL)
        cloud = chunk_document(text, budget=CLOUD)
        assert len(cloud) < len(local)
        assert max(len(c.text) for c in cloud) > max(len(c.text) for c in local)

    def test_an_unknown_window_still_chunks(self):
        # A provider that does not declare its window must not degrade to
        # "send the whole document" — that is the failure being fixed.
        chunks = chunk_document(_document(), budget=None)
        assert len(chunks) > 1

    def test_an_explicit_size_overrides_the_budget(self):
        chunks = chunk_document(_document(sections=10), chunk_chars=2_000)
        assert all(len(c.text) < 4_000 for c in chunks)

    def test_a_maximum_caps_even_a_huge_window(self):
        huge = ContextBudget(context_window=2_000_000, reserved_output=32_000)
        chunks = chunk_document(_document(sections=60), budget=huge, maximum=8_000)
        assert len(chunks) > 1


class TestBoundaries:
    def test_chunks_begin_at_a_structural_boundary(self):
        # Each chunk starts a short overlap *before* the boundary that was
        # chosen, so the boundary itself lands within the first few hundred
        # characters rather than exactly at position zero.
        chunks = chunk_document(_document(sections=30), chunk_chars=3_000)
        assert len(chunks) > 2
        for chunk in chunks[1:]:
            head = chunk.text[:400]
            assert "## Section" in head or "<!-- page:" in head

    def test_no_content_is_dropped_between_chunks(self):
        text = _document(sections=12)
        chunks = chunk_document(text, chunk_chars=2_500)
        # Overlap means the concatenation is longer than the source, but every
        # marker must appear at least once.
        joined = "".join(c.text for c in chunks)
        for n in range(1, 13):
            assert f"Section {n}" in joined

    def test_consecutive_chunks_overlap(self):
        chunks = chunk_document(_document(sections=12), chunk_chars=2_500)
        assert len(chunks) > 1
        tail = chunks[0].text[-200:]
        assert any(fragment and fragment in chunks[1].text for fragment in [tail[-60:]])

    def test_text_without_structure_still_splits(self):
        chunks = chunk_document("x" * 10_000, chunk_chars=1_000)
        assert len(chunks) > 1

    def test_empty_input_yields_no_chunks(self):
        assert chunk_document("   \n\n  ", chunk_chars=1_000) == []

    def test_a_document_smaller_than_one_chunk_is_a_single_chunk(self):
        chunks = chunk_document("# Title\n\nshort body", chunk_chars=50_000)
        assert len(chunks) == 1
        assert chunks[0].index == 1
        assert chunks[0].total == 1


class TestChunkCoordinates:
    def test_indices_are_contiguous_and_total_is_consistent(self):
        chunks = chunk_document(_document(sections=20), chunk_chars=2_500)
        assert [c.index for c in chunks] == list(range(1, len(chunks) + 1))
        assert all(c.total == len(chunks) for c in chunks)

    def test_line_ranges_advance(self):
        chunks = chunk_document(_document(sections=20), chunk_chars=2_500)
        assert all(c.end_line >= c.start_line for c in chunks)
        assert chunks[1].start_line > chunks[0].start_line

    def test_start_page_comes_from_the_anchor(self):
        chunks = chunk_document(_document(sections=20), chunk_chars=2_500)
        assert chunks[0].start_page == 1
        assert any(c.start_page and c.start_page > 1 for c in chunks[1:])

    def test_heading_is_recorded_for_citation(self):
        chunks = chunk_document(_document(sections=20), chunk_chars=2_500)
        assert any(c.heading and c.heading.startswith("Section") for c in chunks)

    def test_label_reads_as_a_coordinate(self):
        chunk = chunk_document(_document(sections=6), chunk_chars=2_500)[0]
        assert "chunk 1/" in chunk.label
        assert "lines" in chunk.label
