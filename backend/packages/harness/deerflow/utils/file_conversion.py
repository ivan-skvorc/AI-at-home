"""File conversion utilities.

Converts document files (PDF, PPT, Excel, Word) to Markdown.

PDF conversion strategy (auto mode):
  1. Try pymupdf4llm if installed — better heading detection, faster on most files.
  2. If output is suspiciously short (< _MIN_CHARS_PER_PAGE chars/page, or < 200 chars
     total when page count is unavailable), treat as image-based and fall back to MarkItDown.
  3. If pymupdf4llm is not installed, use MarkItDown directly (existing behaviour).

Converted PDFs carry ``<!-- page: N -->`` anchors (see
``deerflow.documents.extraction``) so a chunk or a quoted passage can be traced
back to a page, and every conversion reports what it actually recovered so a
scanned PDF is named as such instead of silently producing an empty file.

Large files (> ASYNC_THRESHOLD_BYTES) are converted in a thread pool via
asyncio.to_thread() to avoid blocking the event loop (fixes #1569).

No FastAPI or HTTP dependencies — pure utility functions.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from deerflow.config.app_config import get_app_config
from deerflow.documents.extraction import ExtractionQuality, assess_extraction, page_anchor

# Backward-compat re-exports — outline extraction moved to file_outline.py.
from deerflow.utils.file_outline import (  # noqa: F401
    MAX_OUTLINE_ENTRIES,
    extract_outline,
)

logger = logging.getLogger(__name__)

# File extensions that should be converted to markdown
CONVERTIBLE_EXTENSIONS = {
    ".pdf",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
}

# Files larger than this threshold are converted in a background thread.
# Small files complete in < 1s synchronously; spawning a thread adds unnecessary
# scheduling overhead for them.
_ASYNC_THRESHOLD_BYTES = 1 * 1024 * 1024  # 1 MB

# If pymupdf4llm produces fewer characters *per page* than this threshold,
# the PDF is likely image-based or encrypted — fall back to MarkItDown.
# Rationale: normal text PDFs yield 200-2000 chars/page; image-based PDFs
# yield close to 0. 50 chars/page gives a wide safety margin.
# Falls back to absolute 200-char check when page count is unavailable.
_MIN_CHARS_PER_PAGE = 50


def _pymupdf_output_too_sparse(text: str, file_path: Path) -> bool:
    """Return True if pymupdf4llm output is suspiciously short (image-based PDF).

    Uses chars-per-page rather than an absolute threshold so that both short
    documents (few pages, few chars) and long documents (many pages, many chars)
    are handled correctly.
    """
    chars = len(text.strip())
    doc = None
    pages: int | None = None
    try:
        import pymupdf

        doc = pymupdf.open(str(file_path))
        pages = len(doc)
    except Exception:
        pass
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
    if pages is not None and pages > 0:
        return (chars / pages) < _MIN_CHARS_PER_PAGE
    # Fallback: absolute threshold when page count is unavailable
    return chars < 200


def _anchor_page_chunks(chunks: list) -> str | None:
    """Join pymupdf4llm page chunks into Markdown with page anchors.

    ``page_chunks=True`` yields one dict per page with a ``metadata.page``
    number. Returns None when the payload does not have that shape (a
    pymupdf4llm version whose contract differs), so the caller can fall back to
    the plain string form rather than emitting wrong page numbers.
    """
    parts: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict) or not isinstance(chunk.get("text"), str):
            return None
        metadata = chunk.get("metadata")
        page = metadata.get("page") if isinstance(metadata, dict) else None
        parts.append(f"{page_anchor(int(page) if isinstance(page, int) else index)}\n{chunk['text'].strip()}")
    return "\n\n".join(parts)


def _convert_pdf_with_pymupdf4llm(file_path: Path) -> str | None:
    """Attempt PDF conversion with pymupdf4llm.

    Returns the markdown text, or None if pymupdf4llm is not installed or
    if conversion fails (e.g. encrypted/corrupt PDF).

    Extraction is requested per page so the output can carry page anchors; a
    payload that is not shaped like page chunks degrades to the flat string.
    """
    try:
        import pymupdf4llm
    except ImportError:
        return None

    try:
        chunks = pymupdf4llm.to_markdown(str(file_path), page_chunks=True)
    except TypeError:
        # Older pymupdf4llm without page_chunks — no anchors, same text.
        try:
            return pymupdf4llm.to_markdown(str(file_path))
        except Exception:
            logger.exception("pymupdf4llm failed to convert %s; falling back to MarkItDown", file_path.name)
            return None
    except Exception:
        logger.exception("pymupdf4llm failed to convert %s; falling back to MarkItDown", file_path.name)
        return None

    if isinstance(chunks, str):
        return chunks
    if isinstance(chunks, list):
        anchored = _anchor_page_chunks(chunks)
        if anchored is not None:
            return anchored
        logger.warning("pymupdf4llm returned an unrecognised page-chunk shape for %s; page anchors omitted", file_path.name)
        try:
            return pymupdf4llm.to_markdown(str(file_path))
        except Exception:
            logger.exception("pymupdf4llm failed to convert %s; falling back to MarkItDown", file_path.name)
            return None
    return None


def _convert_with_markitdown(file_path: Path) -> str:
    """Convert any supported file to markdown text using MarkItDown."""
    from markitdown import MarkItDown

    md = MarkItDown()
    return md.convert(str(file_path)).text_content


def _do_convert(file_path: Path, pdf_converter: str) -> str:
    """Synchronous conversion — called directly or via asyncio.to_thread.

    Args:
        file_path: Path to the file.
        pdf_converter: "auto" | "pymupdf4llm" | "markitdown"
    """
    is_pdf = file_path.suffix.lower() == ".pdf"

    if is_pdf and pdf_converter != "markitdown":
        # Try pymupdf4llm first (auto or explicit)
        pymupdf_text = _convert_pdf_with_pymupdf4llm(file_path)

        if pymupdf_text is not None:
            # pymupdf4llm is installed
            if pdf_converter == "pymupdf4llm":
                # Explicit — use as-is regardless of output length
                return pymupdf_text
            # auto mode: fall back if output looks like a failed parse.
            # Use chars-per-page to distinguish image-based PDFs (near 0) from
            # legitimately short documents.
            if not _pymupdf_output_too_sparse(pymupdf_text, file_path):
                return pymupdf_text
            logger.warning(
                "pymupdf4llm produced only %d chars for %s (likely image-based PDF); falling back to MarkItDown",
                len(pymupdf_text.strip()),
                file_path.name,
            )
        # pymupdf4llm not installed or fallback triggered → use MarkItDown

    return _convert_with_markitdown(file_path)


async def convert_file_to_markdown(file_path: Path, output_path: Path | None = None) -> Path | None:
    """Convert a supported document file to Markdown.

    PDF files are handled with a two-converter strategy (see module docstring).
    Large files (> 1 MB) are offloaded to a thread pool to avoid blocking the
    event loop.

    Args:
        file_path: Path to the file to convert.
        output_path: Optional destination for the generated ``.md`` file.
            When omitted, writes to ``file_path`` with a ``.md`` suffix.
            Callers that track per-request filename uniqueness should pass a
            pre-claimed path so companion markdown cannot clobber other uploads.

    Returns:
        Path to the generated .md file, or None if conversion failed.
    """
    report = await convert_file_to_markdown_reported(file_path, output_path)
    return report.md_path if report is not None else None


@dataclass(frozen=True)
class ConversionReport:
    """Where the Markdown landed, and what the conversion actually recovered."""

    md_path: Path
    quality: ExtractionQuality


async def convert_file_to_markdown_reported(file_path: Path, output_path: Path | None = None) -> ConversionReport | None:
    """Convert a document and report the quality of the extraction.

    Same work as :func:`convert_file_to_markdown`, but the caller learns whether
    the text layer was actually there. A scanned PDF converts "successfully" to
    a file with no text in it; without this the only signal is an agent
    confidently summarising nothing.
    """
    try:
        pdf_converter = _get_pdf_converter()
        file_size = file_path.stat().st_size

        if file_size > _ASYNC_THRESHOLD_BYTES:
            text = await asyncio.to_thread(_do_convert, file_path, pdf_converter)
        else:
            text = _do_convert(file_path, pdf_converter)

        md_path = output_path if output_path is not None else file_path.with_suffix(".md")
        md_path.write_text(text, encoding="utf-8")
        # Belt-and-suspenders: also write <original_filename_with_extension>.md
        # so agents that hallucinate either naming convention find the file.
        dual_path = file_path.with_name(file_path.name + ".md")
        if dual_path != md_path:
            dual_path.write_text(text, encoding="utf-8")

        quality = assess_extraction(text, pages=_page_count(file_path))
        if quality.is_sparse:
            logger.warning("Converted %s to %s but %s", file_path.name, md_path.name, quality.describe())
        else:
            logger.info("Converted %s to markdown: %s (%d chars)", file_path.name, md_path.name, len(text))
        return ConversionReport(md_path=md_path, quality=quality)
    except Exception as e:
        logger.error("Failed to convert %s to markdown: %s", file_path.name, e)
        return None


def _page_count(file_path: Path) -> int | None:
    """Page count of a PDF, or None when it cannot be determined.

    Only consulted as a fallback: a conversion that emitted page anchors
    already carries the count in the Markdown itself.
    """
    if file_path.suffix.lower() != ".pdf":
        return None
    doc = None
    try:
        import pymupdf

        doc = pymupdf.open(str(file_path))
        return len(doc) or None
    except Exception:
        return None
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def assess_converted_markdown(md_path: Path, source_path: Path | None = None) -> ExtractionQuality | None:
    """Assess an already-converted Markdown companion.

    Lets a caller that did not run the conversion — the uploads middleware
    describing a file uploaded in an earlier turn — reach the same verdict.
    """
    try:
        text = md_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return assess_extraction(text, pages=_page_count(source_path) if source_path is not None else None)


# Regex for bold-only lines that look like section headings.
# Targets SEC filing structural headings that pymupdf4llm renders as **bold**
# rather than # Markdown headings (because they use same font size as body text,
# distinguished only by bold+caps formatting).
#
# Pattern requires ALL of:
#   1. Entire line is a single **...** block (no surrounding prose)
#   2. Starts with a recognised structural keyword:
#      - ITEM / PART / SECTION (with optional number/letter after)
#      - SCHEDULE, EXHIBIT, APPENDIX, ANNEX, CHAPTER

_ALLOWED_PDF_CONVERTERS = {"auto", "pymupdf4llm", "markitdown"}


def _get_uploads_config_value(key: str, default: object) -> object:
    """Read a value from the uploads config, supporting dict and attribute access."""
    cfg = get_app_config()
    uploads_cfg = getattr(cfg, "uploads", None)
    if isinstance(uploads_cfg, dict):
        return uploads_cfg.get(key, default)
    return getattr(uploads_cfg, key, default)


def _get_pdf_converter() -> str:
    """Read pdf_converter setting from app config, defaulting to 'auto'.

    Normalizes the value to lowercase and validates it against the allowed set
    so that values like 'AUTO' or 'MarkItDown' from config.yaml don't silently
    fall through to unexpected behaviour.
    """
    try:
        raw = str(_get_uploads_config_value("pdf_converter", "auto")).strip().lower()
        if raw not in _ALLOWED_PDF_CONVERTERS:
            logger.warning("Invalid pdf_converter value %r; falling back to 'auto'", raw)
            return "auto"
        return raw
    except Exception:
        pass
    return "auto"
