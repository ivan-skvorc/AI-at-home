"""Read a scanned PDF by looking at it.

``pymupdf4llm`` extracts a PDF's *text layer*. A scanned document has none, so
conversion succeeds and produces a near-empty Markdown file that an agent will
happily summarise into fiction. The remedy is to stop treating the pages as
text and treat them as what they are — images — and hand them to a
vision-capable model one page at a time.

The pipeline is deliberately two-staged:

1. **Transcribe.** Each page is rendered to a PNG and sent to a vision model on
   its own, with an instruction to transcribe rather than summarise. One page
   per call keeps the prompt small enough for a local VLM and keeps a failure
   local to the page that caused it.
2. **Reduce.** Summarising is a *separate* step over the transcript
   (``deerflow.documents.analysis``), never folded into transcription. A model
   asked to summarise while reading is a model choosing what to drop before
   anyone has seen the whole document.

The transcript is written next to the source as ``<name>.ocr.md`` with page
anchors, so the expensive part happens once and every later question reads the
cache.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from pathlib import Path

from deerflow.documents.extraction import page_anchor

logger = logging.getLogger(__name__)

# 150 DPI renders body text legibly for current vision models while keeping a
# page around 200-400 KB. 300 DPI quadruples the payload for little accuracy on
# printed text, and a local VLM pays for every one of those tokens.
DEFAULT_DPI = 150

TRANSCRIBE_PROMPT = (
    "Transcribe this page of a scanned document into Markdown.\n"
    "\n"
    "Rules:\n"
    "- Reproduce the text as it appears. Do not summarise, shorten, or comment.\n"
    "- Preserve headings, lists and reading order. Render tables as Markdown tables.\n"
    "- If a region is illegible, write [illegible] rather than guessing at it.\n"
    "- If the page is blank, reply with exactly: [blank page]\n"
    "- Output only the transcription."
)

# Marker left in place of a page whose transcription failed, so a gap is
# visible in the transcript instead of silently closing up.
FAILED_PAGE_MARKER = "[transcription failed for this page]"


@dataclass(frozen=True)
class RenderedPage:
    """One page of a PDF, rendered to an image on disk."""

    page_number: int
    path: Path


@dataclass(frozen=True)
class OcrResult:
    """The transcript of a scanned document."""

    text: str
    pages_transcribed: int
    pages_failed: int
    cache_path: Path | None = None

    @property
    def complete(self) -> bool:
        return self.pages_failed == 0


def render_pdf_pages(
    pdf_path: Path,
    out_dir: Path,
    *,
    dpi: int = DEFAULT_DPI,
    max_pages: int | None = None,
) -> list[RenderedPage]:
    """Render PDF pages to PNGs in *out_dir*.

    Raises ``RuntimeError`` when pymupdf is not installed, because the caller
    needs to tell the user to install it rather than silently reading nothing.
    """
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - exercised via the caller's error path
        raise RuntimeError("pymupdf is required to render PDF pages for OCR (install the 'pymupdf' extra)") from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[RenderedPage] = []
    doc = pymupdf.open(str(pdf_path))
    try:
        limit = len(doc) if max_pages is None else min(len(doc), max_pages)
        for index in range(limit):
            page = doc[index]
            pixmap = page.get_pixmap(dpi=dpi)
            image_path = out_dir / f"page-{index + 1:04d}.png"
            pixmap.save(str(image_path))
            rendered.append(RenderedPage(page_number=index + 1, path=image_path))
    finally:
        doc.close()
    return rendered


def _data_url(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _page_message(image_path: Path, prompt: str):
    from langchain_core.messages import HumanMessage

    return HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _data_url(image_path)}},
        ]
    )


def _text_of(response) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "".join(parts)
    return str(content)


async def transcribe_page(model, page: RenderedPage, *, prompt: str = TRANSCRIBE_PROMPT) -> str | None:
    """Transcribe one rendered page, or return None when the call fails.

    A failure is per-page on purpose: one unreadable page in a 200-page scan
    should cost that page, not the document.
    """
    try:
        response = await model.ainvoke([_page_message(page.path, prompt)])
    except Exception:
        logger.exception("Vision transcription failed for page %d", page.page_number)
        return None
    text = _text_of(response).strip()
    return text or None


async def transcribe_pages(
    model,
    pages: list[RenderedPage],
    *,
    concurrency: int = 2,
    prompt: str = TRANSCRIBE_PROMPT,
) -> tuple[str, int, int]:
    """Transcribe pages and join them into anchored Markdown.

    Concurrency defaults to 2 because the target deployment is one local GPU:
    more parallel vision calls than the daemon has slots simply queue, and each
    one holds its image payload in memory while it waits.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(page: RenderedPage) -> tuple[RenderedPage, str | None]:
        async with semaphore:
            return page, await transcribe_page(model, page, prompt=prompt)

    results = await asyncio.gather(*(_one(page) for page in pages))

    parts: list[str] = []
    transcribed = failed = 0
    for page, text in results:
        if text is None:
            failed += 1
            body = FAILED_PAGE_MARKER
        else:
            transcribed += 1
            body = text
        parts.append(f"{page_anchor(page.page_number)}\n{body}")
    return "\n\n".join(parts), transcribed, failed


async def ocr_pdf_to_markdown(
    pdf_path: Path,
    model,
    *,
    work_dir: Path,
    cache_path: Path | None = None,
    dpi: int = DEFAULT_DPI,
    max_pages: int | None = None,
    concurrency: int = 2,
) -> OcrResult:
    """Render, transcribe and cache a scanned PDF as anchored Markdown.

    An existing cache is returned as-is: transcription is the expensive step in
    the whole pipeline, and a second question about the same document should not
    pay for it again.
    """
    if cache_path is not None and cache_path.is_file():
        cached = cache_path.read_text(encoding="utf-8", errors="replace")
        if cached.strip():
            logger.info("Using cached OCR transcript for %s", pdf_path.name)
            return OcrResult(text=cached, pages_transcribed=cached.count("<!-- page:"), pages_failed=0, cache_path=cache_path)

    pages = await asyncio.to_thread(render_pdf_pages, pdf_path, work_dir, dpi=dpi, max_pages=max_pages)
    if not pages:
        return OcrResult(text="", pages_transcribed=0, pages_failed=0, cache_path=None)

    text, transcribed, failed = await transcribe_pages(model, pages, concurrency=concurrency)

    if cache_path is not None and transcribed:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")
        except OSError:
            logger.warning("Could not cache OCR transcript at %s", cache_path)
            cache_path = None
    return OcrResult(text=text, pages_transcribed=transcribed, pages_failed=failed, cache_path=cache_path if transcribed else None)
