"""Primary = the production ``analyze_document`` map-reduce, run directly.

This is the fast inner loop: no Gateway, no frontend, no uploads API. It calls
:func:`deerflow.documents.analysis.analyze_document_text` — the same function
the tool calls — so a result here is a statement about production code, not
about a reimplementation of it.

It follows the resumption the tool reports. ``max_chunks`` returns a prefix, so
a run that stops at the cap and reports "nothing found" has answered a question
about the first part of the document. Walking the ``start_part`` chain to the
end is what makes "the document does not contain this" a claim about the
document.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# A stop on the resumption chain. Long enough to walk a 300-page document at
# the shipped caps, short enough that a bug that never advances is bounded.
MAX_HOPS = 12


@dataclass
class PrimaryRun:
    """What the primary produced, and what it cost to get there."""

    answer: str
    coverage: str
    hops: int = 0
    parts_total: int = 0
    parts_read: int = 0
    pages_covered: tuple[int | None, int | None] = (None, None)
    fully_covered: bool = False
    per_hop: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "coverage": self.coverage,
            "hops": self.hops,
            "parts_total": self.parts_total,
            "parts_read": self.parts_read,
            "pages_covered": list(self.pages_covered),
            "fully_covered": self.fully_covered,
            "per_hop": self.per_hop,
            "error": self.error,
        }


async def load_markdown(pdf_path: Path) -> str:
    """Convert the PDF through the same converter the uploads path uses."""
    import asyncio

    from deerflow.utils.file_conversion import _do_convert, _get_pdf_converter

    return await asyncio.to_thread(_do_convert, pdf_path, _get_pdf_converter())


async def run_primary(
    model: Any,
    text: str,
    task: str,
    *,
    budget: Any = None,
    max_chunk_chars: int | None = None,
    max_chunks: int | None = None,
    concurrency: int = 2,
    follow_resumption: bool = True,
) -> PrimaryRun:
    """Answer *task* over *text*, following the resumption chain to the end.

    ``follow_resumption=False`` reproduces the pre-fix behaviour — take the
    first capped read and stop — which is what makes the difference visible as
    a number rather than an assertion.
    """
    from deerflow.documents.analysis import analyze_document_text

    answers: list[str] = []
    coverages: list[str] = []
    per_hop: list[dict[str, Any]] = []
    first_page: int | None = None
    last_page: int | None = None
    parts_total = 0
    parts_read = 0
    part: int | None = 1
    hops = 0

    while part is not None and hops < MAX_HOPS:
        try:
            result = await analyze_document_text(
                text,
                task,
                model,
                budget=budget,
                max_chunk_chars=max_chunk_chars,
                max_chunks=max_chunks,
                start_part=part,
                concurrency=concurrency,
            )
        except Exception as exc:
            logger.exception("Primary analysis failed at part %s", part)
            return PrimaryRun(
                answer="\n\n".join(answers),
                coverage="; ".join(coverages),
                hops=hops,
                parts_total=parts_total,
                parts_read=parts_read,
                pages_covered=(first_page, last_page),
                per_hop=per_hop,
                error=f"{type(exc).__name__}: {exc}",
            )

        hops += 1
        answers.append(result.answer)
        coverages.append(result.coverage_line())
        parts_total = result.chunks_total
        parts_read += result.chunks_read
        if first_page is None:
            first_page = result.first_page
        last_page = result.last_page or last_page
        per_hop.append(
            {
                "hop": hops,
                "start_part": result.start_part,
                "parts_read": result.chunks_read,
                "parts_relevant": result.chunks_relevant,
                "pages": [result.first_page, result.last_page],
                "truncated": result.truncated,
                "notes_truncated": result.notes_truncated,
                "answer": result.answer,
            }
        )
        part = result.next_part if follow_resumption else None

    return PrimaryRun(
        answer="\n\n".join(answers),
        coverage="; ".join(coverages),
        hops=hops,
        parts_total=parts_total,
        parts_read=parts_read,
        pages_covered=(first_page, last_page),
        fully_covered=part is None and parts_read >= parts_total > 0,
        per_hop=per_hop,
    )
