"""Split a converted document into model-sized pieces.

The chunk is the unit of work for the map stage of document analysis, so its
size is the setting that decides whether one code path can serve both a local
8B and a frontier cloud model. It is derived from the serving model's context
window rather than configured by hand: a 200K-token model reads a chapter per
step, a 32K local model reads a few pages, and neither needs to know about the
other.

Boundaries are chosen structurally, not by character count. In order of
preference a chunk breaks at a Markdown heading, then a page anchor, then a
blank line, and only then mid-paragraph. A split through the middle of a
sentence costs a small model more than the few hundred characters it saves,
because the fragment on either side is no longer self-describing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from deerflow.documents.extraction import PAGE_ANCHOR_RE, first_page_in
from deerflow.utils.context_budget import ContextBudget, chunk_chars_for

# A Markdown ATX heading at the start of a line.
_HEADING_RE = re.compile(r"^#{1,6} +\S", re.MULTILINE)
# Overlap carried into the next chunk so a fact split across a boundary is
# still whole in one of them. Deliberately small: overlap is duplicated work in
# the map stage, and every duplicated token is paid for on every chunk.
OVERLAP_RATIO = 0.06
MAX_OVERLAP_CHARS = 1_500


@dataclass(frozen=True)
class DocumentChunk:
    """One unit of the map stage."""

    index: int
    total: int
    text: str
    start_line: int
    end_line: int
    start_page: int | None = None
    heading: str | None = None

    @property
    def label(self) -> str:
        """Human-readable coordinate, used in prompts and in the final notes."""
        parts = [f"chunk {self.index}/{self.total}", f"lines {self.start_line}-{self.end_line}"]
        if self.start_page is not None:
            parts.append(f"from page {self.start_page}")
        if self.heading:
            parts.append(f"under {self.heading!r}")
        return ", ".join(parts)


def _last_boundary(text: str, lower: int) -> int | None:
    """Return the best split point in ``text`` at or after ``lower``.

    Preference order: heading, page anchor, blank line. Returns None when the
    window holds none of them, leaving the caller to split on a line break.
    """
    for pattern in (_HEADING_RE, PAGE_ANCHOR_RE):
        best = None
        for match in pattern.finditer(text, lower):
            best = match.start()
        if best is not None and best > lower:
            return best
    blank = text.rfind("\n\n", lower)
    return blank + 2 if blank > lower else None


def _heading_before(text: str, position: int) -> str | None:
    """Return the nearest heading title at or before ``position``."""
    best = None
    for match in _HEADING_RE.finditer(text, 0, max(position, 1)):
        best = match
    if best is None:
        return None
    line_end = text.find("\n", best.start())
    line = text[best.start() : line_end if line_end != -1 else len(text)]
    return line.lstrip("#").strip() or None


def chunk_document(
    text: str,
    *,
    budget: ContextBudget | None = None,
    chunk_chars: int | None = None,
    maximum: int | None = None,
) -> list[DocumentChunk]:
    """Split *text* into chunks sized for the model described by *budget*.

    ``chunk_chars`` overrides the derived size (a caller that already resolved
    it, or a test); ``maximum`` caps it however large the window is.
    """
    size = chunk_chars if chunk_chars is not None else chunk_chars_for(budget, maximum=maximum)
    size = max(1, size)
    if not text.strip():
        return []

    overlap = min(MAX_OVERLAP_CHARS, int(size * OVERLAP_RATIO))
    spans: list[tuple[int, int]] = []
    start = 0
    length = len(text)
    while start < length:
        end = start + size
        if end >= length:
            spans.append((start, length))
            break
        # Look for a structural boundary in the last third of the window, so a
        # chunk is never shortened to a stub in pursuit of a clean break.
        boundary = _last_boundary(text[:end], start + (size * 2) // 3)
        if boundary is None:
            newline = text.rfind("\n", start + (size * 2) // 3, end)
            boundary = newline + 1 if newline != -1 else end
        spans.append((start, boundary))
        start = boundary if overlap == 0 else max(start + 1, boundary - overlap)

    chunks: list[DocumentChunk] = []
    total = len(spans)
    for index, (span_start, span_end) in enumerate(spans, start=1):
        body = text[span_start:span_end]
        if not body.strip():
            continue
        start_line = text.count("\n", 0, span_start) + 1
        chunks.append(
            DocumentChunk(
                index=index,
                total=total,
                text=body,
                start_line=start_line,
                end_line=start_line + body.count("\n"),
                start_page=first_page_in(body),
                heading=_heading_before(text, span_start + 1),
            )
        )
    # Renumber after dropping blank spans so index/total stay consistent.
    return [
        DocumentChunk(
            index=position,
            total=len(chunks),
            text=chunk.text,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            start_page=chunk.start_page,
            heading=chunk.heading,
        )
        for position, chunk in enumerate(chunks, start=1)
    ]
