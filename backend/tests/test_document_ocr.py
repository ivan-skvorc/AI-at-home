"""Tests for the scanned-PDF OCR path (fork feature).

A scanned PDF has no text layer, so the existing converter produces a nearly
empty file and the agent summarises nothing at all. This path renders each page
to an image and hands it to a vision model one page at a time.

The properties under test:
- transcription and summarisation are separate steps — this module transcribes
  and nothing else, so no model decides what to drop before the whole document
  has been read;
- a page that fails leaves a visible gap rather than silently closing up;
- the transcript is anchored per page, so a later answer can cite one;
- the expensive step is cached, because a second question about the same
  document must not pay for it again.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.documents.ocr import (
    FAILED_PAGE_MARKER,
    TRANSCRIBE_PROMPT,
    OcrResult,
    RenderedPage,
    ocr_pdf_to_markdown,
    transcribe_page,
    transcribe_pages,
)


class _Response:
    def __init__(self, content):
        self.content = content


class _VisionModel:
    """Records the messages it is asked to transcribe."""

    def __init__(self, replies=None, fail_on=()):
        self._replies = replies or {}
        self._fail_on = set(fail_on)
        self.calls: list = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        index = len(self.calls)
        if index in self._fail_on:
            raise RuntimeError("vision call failed")
        return _Response(self._replies.get(index, f"page {index} text"))


def _pages(tmp_path: Path, count: int) -> list[RenderedPage]:
    pages = []
    for n in range(1, count + 1):
        path = tmp_path / f"page-{n}.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([n]))
        pages.append(RenderedPage(page_number=n, path=path))
    return pages


class TestTranscribePage:
    @pytest.mark.anyio
    async def test_sends_the_image_and_the_transcription_instruction(self, tmp_path: Path):
        model = _VisionModel()
        page = _pages(tmp_path, 1)[0]
        await transcribe_page(model, page)
        content = model.calls[0][0].content
        assert content[0]["text"] == TRANSCRIBE_PROMPT
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")

    @pytest.mark.anyio
    async def test_the_instruction_forbids_summarising(self):
        # Summarising is the reduce step's job; a model that summarises while
        # transcribing drops content before anyone has seen the document.
        assert "Do not summarise" in TRANSCRIBE_PROMPT

    @pytest.mark.anyio
    async def test_a_failed_call_returns_none_rather_than_raising(self, tmp_path: Path):
        model = _VisionModel(fail_on={1})
        assert await transcribe_page(model, _pages(tmp_path, 1)[0]) is None

    @pytest.mark.anyio
    async def test_content_blocks_are_flattened_to_text(self, tmp_path: Path):
        model = _VisionModel(replies={1: [{"type": "text", "text": "hello"}]})
        assert await transcribe_page(model, _pages(tmp_path, 1)[0]) == "hello"

    @pytest.mark.anyio
    async def test_an_empty_reply_counts_as_a_failure(self, tmp_path: Path):
        model = _VisionModel(replies={1: "   "})
        assert await transcribe_page(model, _pages(tmp_path, 1)[0]) is None


class TestTranscribePages:
    @pytest.mark.anyio
    async def test_pages_are_anchored_in_order(self, tmp_path: Path):
        text, transcribed, failed = await transcribe_pages(_VisionModel(), _pages(tmp_path, 3), concurrency=1)
        assert transcribed == 3 and failed == 0
        assert text.index("<!-- page: 1 -->") < text.index("<!-- page: 2 -->") < text.index("<!-- page: 3 -->")

    @pytest.mark.anyio
    async def test_order_is_kept_even_when_calls_finish_out_of_order(self, tmp_path: Path):
        text, _, _ = await transcribe_pages(_VisionModel(), _pages(tmp_path, 4), concurrency=4)
        positions = [text.index(f"<!-- page: {n} -->") for n in range(1, 5)]
        assert positions == sorted(positions)

    @pytest.mark.anyio
    async def test_a_failed_page_leaves_a_visible_gap(self, tmp_path: Path):
        text, transcribed, failed = await transcribe_pages(_VisionModel(fail_on={2}), _pages(tmp_path, 3), concurrency=1)
        assert (transcribed, failed) == (2, 1)
        assert FAILED_PAGE_MARKER in text
        # The page is still anchored, so the gap is locatable rather than lost.
        assert "<!-- page: 2 -->" in text


class TestOcrPdfToMarkdown:
    @pytest.mark.anyio
    async def test_a_cached_transcript_skips_every_model_call(self, tmp_path: Path):
        cache = tmp_path / "scan.pdf.ocr.md"
        cache.write_text("<!-- page: 1 -->\ncached body", encoding="utf-8")
        model = _VisionModel()
        result = await ocr_pdf_to_markdown(tmp_path / "scan.pdf", model, work_dir=tmp_path / "work", cache_path=cache)
        assert result.text.endswith("cached body")
        assert model.calls == []

    @pytest.mark.anyio
    async def test_an_empty_cache_file_is_ignored(self, tmp_path: Path, monkeypatch):
        cache = tmp_path / "scan.pdf.ocr.md"
        cache.write_text("   ", encoding="utf-8")
        monkeypatch.setattr("deerflow.documents.ocr.render_pdf_pages", lambda *a, **k: _pages(tmp_path, 1))
        result = await ocr_pdf_to_markdown(tmp_path / "scan.pdf", _VisionModel(), work_dir=tmp_path / "work", cache_path=cache)
        assert "page 1 text" in result.text

    @pytest.mark.anyio
    async def test_the_transcript_is_written_to_the_cache(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("deerflow.documents.ocr.render_pdf_pages", lambda *a, **k: _pages(tmp_path, 2))
        cache = tmp_path / "out" / "scan.pdf.ocr.md"
        result = await ocr_pdf_to_markdown(tmp_path / "scan.pdf", _VisionModel(), work_dir=tmp_path / "work", cache_path=cache)
        assert cache.is_file()
        assert result.cache_path == cache
        assert result.complete

    @pytest.mark.anyio
    async def test_a_pdf_with_no_pages_returns_an_empty_result(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("deerflow.documents.ocr.render_pdf_pages", lambda *a, **k: [])
        result = await ocr_pdf_to_markdown(tmp_path / "scan.pdf", _VisionModel(), work_dir=tmp_path / "work")
        assert result == OcrResult(text="", pages_transcribed=0, pages_failed=0, cache_path=None)

    @pytest.mark.anyio
    async def test_a_fully_failed_document_is_not_cached(self, tmp_path: Path, monkeypatch):
        # Caching an all-failed transcript would make the failure permanent.
        monkeypatch.setattr("deerflow.documents.ocr.render_pdf_pages", lambda *a, **k: _pages(tmp_path, 2))
        cache = tmp_path / "scan.pdf.ocr.md"
        result = await ocr_pdf_to_markdown(tmp_path / "scan.pdf", _VisionModel(fail_on={1, 2}), work_dir=tmp_path / "work", cache_path=cache)
        assert not cache.exists()
        assert result.pages_failed == 2
        assert not result.complete

    @pytest.mark.anyio
    async def test_max_pages_is_passed_to_the_renderer(self, tmp_path: Path, monkeypatch):
        seen: dict[str, object] = {}

        def fake_render(pdf_path, out_dir, *, dpi, max_pages):
            seen["max_pages"] = max_pages
            seen["dpi"] = dpi
            return _pages(tmp_path, 1)

        monkeypatch.setattr("deerflow.documents.ocr.render_pdf_pages", fake_render)
        await ocr_pdf_to_markdown(tmp_path / "scan.pdf", _VisionModel(), work_dir=tmp_path / "work", max_pages=5, dpi=200)
        assert seen == {"max_pages": 5, "dpi": 200}


class TestRenderPdfPages:
    def test_a_missing_pymupdf_is_reported_as_an_actionable_error(self, tmp_path: Path, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == "pymupdf":
                raise ImportError("no pymupdf")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked)
        from deerflow.documents.ocr import render_pdf_pages

        with pytest.raises(RuntimeError, match="pymupdf"):
            render_pdf_pages(tmp_path / "x.pdf", tmp_path / "out")
