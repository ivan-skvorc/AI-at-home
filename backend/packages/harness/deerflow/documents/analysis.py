"""Map-reduce analysis over a document that does not fit in the context window.

The agent loop asks a model to navigate a long document itself: read the
outline, grep, read a range, synthesise. That is a multi-step tool-use loop, and
it is the first capability a small quantized model loses under long input — so
the documents that most need help are exactly the ones where the navigation
breaks down.

This module inverts that. The document is split into chunks sized for the
serving model (:mod:`deerflow.documents.chunking`), each chunk is read on its
own against the question, and the notes are combined in a separate pass. No
model call ever sees more than one chunk, so "can this model hold 200 pages?"
(no) becomes "can it handle a few pages at a time?" (yes, reliably).

The reduce is **hierarchical**: when the notes themselves outgrow the window
they are combined in rounds until one answer remains. Without that, a long
document simply moves the overflow from the map stage to the reduce stage.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from deerflow.documents.chunking import DocumentChunk, chunk_document
from deerflow.utils.context_budget import ContextBudget, chunk_chars_for

logger = logging.getLogger(__name__)

# A chunk that contributes nothing must say so in one unmistakable token, or
# every irrelevant chunk contributes a paragraph of "this section does not
# discuss..." and the reduce stage drowns in it.
NOTHING_RELEVANT = "NOTHING RELEVANT"

MAP_PROMPT = """You are reading ONE PART of a long document in order to answer a question about the whole.

Question: {question}

Part: {label}
--- BEGIN PART ---
{chunk}
--- END PART ---

Write down only what this part contributes to the answer. Quote exact figures and wording where they matter, and cite the page number when the part shows one. Do not speculate about what other parts might say.

If this part contributes nothing to the question, reply with exactly: {nothing_relevant}"""

REDUCE_PROMPT = """You are combining notes taken from separate parts of ONE long document in order to answer a question.

Question: {question}

--- BEGIN NOTES ---
{notes}
--- END NOTES ---

Answer the question from these notes alone, keeping page citations where the notes carry them. If the notes do not contain the answer, say so plainly and describe what they do cover — do not fill the gap from your own knowledge."""

MERGE_PROMPT = """You are consolidating notes taken from separate parts of ONE long document. There are too many notes to use at once, so this is an intermediate step.

Question the notes are being collected for: {question}

--- BEGIN NOTES ---
{notes}
--- END NOTES ---

Merge these into a single set of notes that preserves every fact, figure and page citation relevant to the question. Do not answer the question yet, and do not add anything the notes do not contain."""

# Failure marker for a chunk whose model call failed, so a gap in coverage is
# visible in the notes instead of silently narrowing the answer.
FAILED_NOTE = "[this part could not be read]"


@dataclass(frozen=True)
class ChunkNote:
    """What one chunk contributed."""

    chunk: DocumentChunk
    text: str
    failed: bool = False

    @property
    def relevant(self) -> bool:
        return not self.failed and bool(self.text.strip()) and NOTHING_RELEVANT not in self.text.upper()

    def render(self) -> str:
        return f"[{self.chunk.label}]\n{self.text.strip()}"


@dataclass
class AnalysisResult:
    """The answer, and an honest account of how much of the document produced it."""

    answer: str
    notes: list[ChunkNote] = field(default_factory=list)
    chunks_total: int = 0
    chunks_read: int = 0
    chunks_failed: int = 0
    chunks_relevant: int = 0
    reduce_rounds: int = 0
    truncated: bool = False

    def coverage_line(self) -> str:
        """One line stating what was actually read — never implied, always said."""
        parts = [f"read {self.chunks_read} of {self.chunks_total} parts"]
        if self.chunks_relevant:
            parts.append(f"{self.chunks_relevant} contributed")
        if self.chunks_failed:
            parts.append(f"{self.chunks_failed} could not be read")
        if self.truncated:
            parts.append("stopped early at the configured part limit")
        return "; ".join(parts)


def _text_of(response) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content)


async def _ask(model, prompt: str) -> str | None:
    from langchain_core.messages import HumanMessage

    try:
        response = await model.ainvoke([HumanMessage(content=prompt)])
    except Exception:
        logger.exception("Document analysis model call failed")
        return None
    text = _text_of(response).strip()
    return text or None


async def map_chunks(model, chunks: list[DocumentChunk], question: str, *, concurrency: int = 2) -> list[ChunkNote]:
    """Read each chunk on its own and note what it contributes."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(chunk: DocumentChunk) -> ChunkNote:
        async with semaphore:
            prompt = MAP_PROMPT.format(question=question, label=chunk.label, chunk=chunk.text, nothing_relevant=NOTHING_RELEVANT)
            answer = await _ask(model, prompt)
        if answer is None:
            return ChunkNote(chunk=chunk, text=FAILED_NOTE, failed=True)
        return ChunkNote(chunk=chunk, text=answer)

    return list(await asyncio.gather(*(_one(chunk) for chunk in chunks)))


def _group_by_size(rendered: list[str], limit: int) -> list[list[str]]:
    """Group rendered notes so each group stays under *limit* characters."""
    groups: list[list[str]] = []
    current: list[str] = []
    size = 0
    for item in rendered:
        item_size = len(item)
        if current and size + item_size > limit:
            groups.append(current)
            current, size = [], 0
        current.append(item)
        size += item_size
    if current:
        groups.append(current)
    return groups


async def reduce_notes(model, rendered: list[str], question: str, *, limit: int, max_rounds: int = 4) -> tuple[str | None, int]:
    """Combine notes into one answer, merging in rounds when they do not fit.

    Returns the answer and the number of intermediate merge rounds it took.
    """
    rounds = 0
    while rounds < max_rounds:
        groups = _group_by_size(rendered, limit)
        if len(groups) <= 1:
            break
        merged: list[str] = []
        for group in groups:
            summary = await _ask(model, MERGE_PROMPT.format(question=question, notes="\n\n".join(group)))
            merged.append(summary if summary is not None else "\n\n".join(group)[:limit])
        rendered = merged
        rounds += 1

    notes = "\n\n".join(rendered)
    if len(notes) > limit:
        # Every merge round is spent and it still does not fit: truncate rather
        # than send a prompt the model will reject or silently cut from the head.
        notes = notes[:limit] + "\n\n[notes truncated to fit the model's context]"
    return await _ask(model, REDUCE_PROMPT.format(question=question, notes=notes)), rounds


async def analyze_document_text(
    text: str,
    question: str,
    model,
    *,
    budget: ContextBudget | None = None,
    chunk_chars: int | None = None,
    max_chunk_chars: int | None = None,
    max_chunks: int | None = None,
    concurrency: int = 2,
) -> AnalysisResult:
    """Answer *question* about *text* without ever holding all of it in context.

    ``max_chunk_chars`` caps the derived size however large the window is: a
    128K-window model would otherwise be handed ~55K tokens per map call, which
    is well past where long-input accuracy starts degrading regardless of what
    the window advertises.
    """
    size = chunk_chars if chunk_chars is not None else chunk_chars_for(budget, maximum=max_chunk_chars)
    chunks = chunk_document(text, chunk_chars=size)
    if not chunks:
        return AnalysisResult(answer="The document is empty — there is nothing to analyse.")

    total = len(chunks)
    truncated = False
    if max_chunks is not None and total > max_chunks:
        chunks = chunks[:max_chunks]
        truncated = True

    notes = await map_chunks(model, chunks, question, concurrency=concurrency)
    relevant = [note for note in notes if note.relevant]
    failed = sum(1 for note in notes if note.failed)

    if not relevant:
        answer = "Nothing in the parts that were read addresses this question."
        if failed:
            answer += f" {failed} of {len(notes)} parts could not be read, so the document may still contain an answer."
        return AnalysisResult(
            answer=answer,
            notes=notes,
            chunks_total=total,
            chunks_read=len(notes),
            chunks_failed=failed,
            truncated=truncated,
        )

    # The reduce prompt has to hold the notes plus its own instructions, so it
    # gets the same per-call budget the map stage used.
    answer, rounds = await reduce_notes(model, [note.render() for note in relevant], question, limit=size)
    return AnalysisResult(
        answer=answer if answer is not None else "The final synthesis step failed; the per-part notes are preserved below.",
        notes=notes,
        chunks_total=total,
        chunks_read=len(notes),
        chunks_failed=failed,
        chunks_relevant=len(relevant),
        reduce_rounds=rounds,
        truncated=truncated,
    )
