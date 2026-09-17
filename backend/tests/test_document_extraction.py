"""Tests for page anchors and extraction-quality assessment (fork feature).

Two silent failures motivated this module, and each has tests here:

- a converted PDF had no relationship to the pages a human sees, so nothing
  downstream could cite a page or align a chunk to one;
- a scanned PDF converts "successfully" into a file with no text in it, and
  nothing could tell that apart from a genuinely short document — so the agent
  summarised an empty file rather than reporting that OCR was needed.
"""

from __future__ import annotations

from pathlib import Path

from deerflow.documents.extraction import (
    MIN_CHARS_PER_PAGE,
    ExtractionQuality,
    assess_extraction,
    count_page_anchors,
    first_page_in,
    page_anchor,
)
from deerflow.utils.file_conversion import _anchor_page_chunks, assess_converted_markdown


class TestPageAnchors:
    def test_anchor_is_an_invisible_html_comment(self):
        assert page_anchor(12) == "<!-- page: 12 -->"

    def test_anchors_are_counted(self):
        text = f"{page_anchor(1)}\nfirst\n\n{page_anchor(2)}\nsecond\n"
        assert count_page_anchors(text) == 2

    def test_first_page_is_read_back(self):
        assert first_page_in(f"noise\n{page_anchor(7)}\nbody") == 7

    def test_no_anchor_reads_back_as_none(self):
        assert first_page_in("just prose") is None

    def test_an_inline_lookalike_is_not_an_anchor(self):
        # Only a line of its own counts, so prose that mentions the syntax
        # cannot fabricate a page number.
        assert count_page_anchors("see <!-- page: 3 --> in the text") == 0

    def test_leading_whitespace_is_tolerated(self):
        assert count_page_anchors("   <!-- page: 4 -->  ") == 1


class TestAnchorPageChunks:
    def test_page_numbers_come_from_chunk_metadata(self):
        chunks = [
            {"text": "one", "metadata": {"page": 1}},
            {"text": "two", "metadata": {"page": 2}},
        ]
        out = _anchor_page_chunks(chunks)
        assert out is not None
        assert out.startswith("<!-- page: 1 -->\none")
        assert "<!-- page: 2 -->\ntwo" in out

    def test_missing_metadata_falls_back_to_ordinal_position(self):
        out = _anchor_page_chunks([{"text": "solo"}])
        assert out == "<!-- page: 1 -->\nsolo"

    def test_an_unrecognised_shape_returns_none_rather_than_wrong_pages(self):
        # A pymupdf4llm whose contract differs must degrade to the flat string,
        # never emit page numbers that do not correspond to pages.
        assert _anchor_page_chunks(["plain string"]) is None
        assert _anchor_page_chunks([{"no_text_key": 1}]) is None


class TestExtractionQuality:
    def test_a_normal_document_is_not_sparse(self):
        quality = ExtractionQuality(chars=1_500, pages=3)
        assert quality.chars_per_page == 500
        assert not quality.is_sparse

    def test_a_scanned_document_is_sparse(self):
        quality = ExtractionQuality(chars=12, pages=40)
        assert quality.is_sparse
        assert not quality.is_empty

    def test_the_boundary_is_the_documented_threshold(self):
        assert not ExtractionQuality(chars=MIN_CHARS_PER_PAGE * 10, pages=10).is_sparse
        assert ExtractionQuality(chars=MIN_CHARS_PER_PAGE * 10 - 1, pages=10).is_sparse

    def test_short_document_with_known_pages_is_judged_per_page(self):
        # A one-page memo with 300 characters is a real document, not a failure;
        # an absolute threshold would have to choose between missing this and
        # missing a 40-page scan.
        assert not ExtractionQuality(chars=300, pages=1).is_sparse

    def test_unknown_page_count_falls_back_to_an_absolute_floor(self):
        assert ExtractionQuality(chars=10, pages=None).is_sparse
        assert not ExtractionQuality(chars=5_000, pages=None).is_sparse

    def test_empty_extraction_is_reported_as_empty(self):
        quality = ExtractionQuality(chars=0, pages=20)
        assert quality.is_empty
        assert "no text at all" in quality.describe()

    def test_description_names_ocr_as_the_remedy(self):
        assert "OCR" in ExtractionQuality(chars=12, pages=40).describe()


class TestAssessExtraction:
    def test_pages_are_taken_from_the_anchors(self):
        text = "\n".join(f"{page_anchor(n)}\nbody text here" for n in range(1, 6))
        assert assess_extraction(text).pages == 5

    def test_anchors_do_not_count_towards_the_character_total(self):
        # Otherwise a scan of 200 blank pages would look like 4KB of content.
        text = "\n".join(page_anchor(n) for n in range(1, 51))
        quality = assess_extraction(text)
        assert quality.chars == 0
        assert quality.is_empty

    def test_supplied_page_count_is_used_when_there_are_no_anchors(self):
        assert assess_extraction("short", pages=9).pages == 9

    def test_converter_is_carried_through(self):
        assert assess_extraction("x", converter="markitdown").converter == "markitdown"


class TestAssessConvertedMarkdown:
    def test_reads_a_companion_file_from_disk(self, tmp_path: Path):
        md = tmp_path / "report.pdf.md"
        md.write_text("\n".join(f"{page_anchor(n)}\n{'w' * 400}" for n in range(1, 4)), encoding="utf-8")
        quality = assess_converted_markdown(md)
        assert quality is not None
        assert quality.pages == 3
        assert not quality.is_sparse

    def test_a_scanned_companion_is_reported_as_sparse(self, tmp_path: Path):
        md = tmp_path / "scan.pdf.md"
        md.write_text("\n".join(page_anchor(n) for n in range(1, 31)), encoding="utf-8")
        quality = assess_converted_markdown(md)
        assert quality is not None
        assert quality.is_sparse

    def test_a_missing_file_returns_none(self, tmp_path: Path):
        assert assess_converted_markdown(tmp_path / "nope.md") is None


class TestUploadsMiddlewareWarning:
    """A scanned upload must announce itself in the prompt, not go quiet.

    Without this the agent sees a converted file with no headings and no
    preview — indistinguishable from a short document — and answers from
    nothing.
    """

    def _entry(self, tmp_path: Path, md_body: str) -> list[str]:
        from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware, _extraction_warning

        source = tmp_path / "scan.pdf"
        source.write_bytes(b"%PDF-1.4")
        (tmp_path / "scan.pdf.md").write_text(md_body, encoding="utf-8")
        lines: list[str] = []
        UploadsMiddleware(base_dir=str(tmp_path))._format_file_entry(
            {
                "filename": "scan.pdf",
                "size": 1024,
                "path": "/mnt/user-data/uploads/scan.pdf",
                "extraction_warning": _extraction_warning(source),
            },
            lines,
        )
        return lines

    def test_a_scanned_upload_is_flagged_and_routed_to_the_tool(self, tmp_path: Path):
        lines = self._entry(tmp_path, "\n".join(page_anchor(n) for n in range(1, 41)))
        rendered = "\n".join(lines)
        assert "image-based" in rendered
        assert "analyze_document" in rendered

    def test_a_readable_upload_is_not_flagged(self, tmp_path: Path):
        body = "\n".join(f"{page_anchor(n)}\n## Section {n}\n\n" + ("word " * 200) for n in range(1, 5))
        rendered = "\n".join(self._entry(tmp_path, body))
        assert "image-based" not in rendered

    def test_no_companion_file_means_no_warning(self, tmp_path: Path):
        from deerflow.agents.middlewares.uploads_middleware import _extraction_warning

        source = tmp_path / "lonely.pdf"
        source.write_bytes(b"%PDF-1.4")
        assert _extraction_warning(source) is None


class TestUploadsMiddlewareExtent:
    """The size next to an upload is the compressed file, not what reading costs.

    A 212 KB PDF of 300 pages extracts to ~1.1 MB of Markdown — roughly 280K
    tokens. An agent shown only "212.0 KB" has every reason to believe it can
    read the file, and the window is gone before it notices otherwise. That is
    the concrete path from a large PDF to a run that forgets its own task, so
    the extracted extent is stated and the large case is routed away from a
    linear read.
    """

    def _entry(self, tmp_path: Path, md_body: str) -> str:
        from deerflow.agents.middlewares.uploads_middleware import (
            UploadsMiddleware,
            _document_quality,
            _large_document_chars,
        )

        source = tmp_path / "report.pdf"
        source.write_bytes(b"%PDF-1.4")
        (tmp_path / "report.pdf.md").write_text(md_body, encoding="utf-8")
        quality = _document_quality(source)
        sparse = quality is not None and quality.is_sparse
        lines: list[str] = []
        UploadsMiddleware(base_dir=str(tmp_path))._format_file_entry(
            {
                "filename": "report.pdf",
                "size": 216_605,
                "path": "/mnt/user-data/uploads/report.pdf",
                "extraction_warning": quality.describe() if sparse else None,
                "document_extent": quality.describe_extent() if quality is not None and not sparse else None,
                "document_is_large": bool(quality is not None and not sparse and quality.chars >= _large_document_chars()),
            },
            lines,
        )
        return "\n".join(lines)

    def _body(self, pages: int) -> str:
        return "\n".join(f"{page_anchor(n)}\n## Section {n}\n\n" + ("word " * 200) for n in range(1, pages + 1))

    def test_the_extracted_size_is_stated_not_just_the_file_size(self, tmp_path: Path):
        rendered = self._entry(tmp_path, self._body(4))
        assert "Extracted text:" in rendered
        assert "tokens" in rendered
        assert "across 4 pages" in rendered

    def test_a_document_past_the_window_is_routed_to_analyze_document(self, tmp_path: Path):
        rendered = self._entry(tmp_path, self._body(300))
        assert "does not fit in one context window" in rendered
        assert "analyze_document" in rendered

    def test_a_small_document_is_not_routed_away_from_a_normal_read(self, tmp_path: Path):
        rendered = self._entry(tmp_path, self._body(4))
        assert "does not fit in one context window" not in rendered
        assert "analyze_document" not in rendered

    def test_a_scan_keeps_the_ocr_warning_rather_than_an_extent(self, tmp_path: Path):
        # A scan is sparse, not large: it must be sent to OCR, and reporting
        # "1,200 characters" next to it would be a second, contradictory story.
        rendered = self._entry(tmp_path, "\n".join(page_anchor(n) for n in range(1, 41)))
        assert "image-based" in rendered
        assert "Extracted text:" not in rendered

    def test_the_threshold_falls_back_when_no_config_is_loaded(self):
        from deerflow.agents.middlewares.uploads_middleware import (
            _DEFAULT_LARGE_DOCUMENT_CHARS,
            _large_document_chars,
        )

        assert _large_document_chars() >= 1_000
        assert _DEFAULT_LARGE_DOCUMENT_CHARS == 120_000
