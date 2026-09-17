"""Page anchors and extraction-quality assessment for converted documents.

Two problems this solves, both invisible in the original pipeline:

**Locating content.** A converted PDF is one long Markdown file with no
relationship to the pages a human sees. The agent can quote it but cannot cite
it, and a chunk boundary means nothing. Conversion now emits an HTML-comment
anchor before each page (``<!-- page: 12 -->``), which renders as nothing,
survives every Markdown consumer, and gives both the chunker and the reader a
stable coordinate.

**Knowing the conversion failed.** ``pymupdf4llm`` extracts a PDF's *text
layer*; a scanned document has none, so conversion "succeeds" and produces a
near-empty file. Nothing downstream could tell that apart from a genuinely
short document, so the agent would summarise an empty file with total
confidence. ``assess_extraction`` turns that into a fact — characters per page —
that callers can act on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from deerflow.utils.context_budget import CHARS_PER_TOKEN

# ``<!-- page: N -->`` on a line of its own. Tolerant of surrounding whitespace
# so a reformatting pass over the Markdown cannot silently break page lookup.
PAGE_ANCHOR_RE = re.compile(r"^[ \t]*<!--\s*page:\s*(\d+)\s*-->[ \t]*$", re.MULTILINE)

# Below this, a page's text layer is empty in all but name. Normal prose pages
# yield 200-2000 characters; a scanned page yields close to zero. 50 leaves a
# wide margin for sparse pages (a title page, a full-page figure with a caption).
MIN_CHARS_PER_PAGE = 50

# Absolute floor used when the page count is unknown.
MIN_TOTAL_CHARS = 200


def page_anchor(page_number: int) -> str:
    """Render the anchor line for a 1-based page number."""
    return f"<!-- page: {page_number} -->"


def count_page_anchors(text: str) -> int:
    """Return how many page anchors *text* carries."""
    return len(PAGE_ANCHOR_RE.findall(text))


def first_page_in(text: str) -> int | None:
    """Return the first page number anchored in *text*, if any.

    Used to label a chunk with the page it starts on, so an answer drawn from
    it can cite a page a human can turn to.
    """
    match = PAGE_ANCHOR_RE.search(text)
    return int(match.group(1)) if match else None


def last_page_in(text: str) -> int | None:
    """Return the last page number anchored in *text*, if any.

    The pair with :func:`first_page_in`: together they turn "parts 1-60 were
    read" into "pages 1-120 were read", which is the only form of that
    statement a reader can check against the document in front of them.
    """
    last = None
    for match in PAGE_ANCHOR_RE.finditer(text):
        last = match
    return int(last.group(1)) if last is not None else None


@dataclass(frozen=True)
class ExtractionQuality:
    """What a conversion actually recovered from a document."""

    chars: int
    pages: int | None
    converter: str | None = None

    @property
    def chars_per_page(self) -> float | None:
        if not self.pages:
            return None
        return self.chars / self.pages

    @property
    def is_empty(self) -> bool:
        return self.chars == 0

    @property
    def approx_tokens(self) -> int:
        """Roughly what reading this document end to end would cost in context."""
        return self.chars // CHARS_PER_TOKEN

    @property
    def is_sparse(self) -> bool:
        """True when the text layer looks absent rather than merely short."""
        per_page = self.chars_per_page
        if per_page is not None:
            return per_page < MIN_CHARS_PER_PAGE
        return self.chars < MIN_TOTAL_CHARS

    def describe_extent(self) -> str:
        """One line stating how much text a full read would pull into context.

        The file size shown next to an upload is the *compressed* PDF on disk:
        a 200 KB PDF routinely extracts to more than a megabyte of Markdown, so
        the number the agent sees understates the cost of reading it by an
        order of magnitude. This is the number that actually decides whether a
        linear read fits.
        """
        size = f"{self.chars:,} characters (~{self.approx_tokens:,} tokens)"
        if self.pages:
            return f"{size} across {self.pages} pages"
        return size

    def describe(self) -> str:
        """One line the agent can be shown, in place of a silently empty file."""
        if self.is_empty:
            detail = "recovered no text at all"
        elif self.chars_per_page is not None:
            detail = f"recovered ~{self.chars_per_page:.0f} characters per page across {self.pages} pages"
        else:
            detail = f"recovered only {self.chars} characters"
        return f"Text extraction {detail} — this document is probably image-based (scanned) and needs OCR to be read."


def assess_extraction(text: str, *, pages: int | None = None, converter: str | None = None) -> ExtractionQuality:
    """Assess what a conversion recovered.

    The page count comes from the anchors when conversion emitted them, so no
    second parse of the source file is needed; *pages* is the fallback for
    documents converted before anchors existed, or by a converter that cannot
    report page boundaries.
    """
    anchored = count_page_anchors(text)
    stripped = PAGE_ANCHOR_RE.sub("", text).strip()
    return ExtractionQuality(chars=len(stripped), pages=anchored or pages, converter=converter)
