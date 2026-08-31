"""Answer a question about a document too large to read into context.

``read_file`` plus ``grep`` asks the model to navigate the document itself. That
works on a frontier model and fails on the models this fork exists to run: a
small quantized model loses instruction-following exactly when the input gets
long, so the documents that most need help are the ones where the navigation
breaks down first.

This tool does the navigating instead. The document is split into parts sized
for the model that will read them, each part is read on its own, and the notes
are combined in a separate pass — so no model call ever holds more than one
part. A PDF whose text layer is missing is routed through OCR first
(:mod:`deerflow.documents.ocr`), which transcribes page images, and *then* the
same summarisation pass runs over the transcript.

The full per-part notes are always written to the thread's outputs directory:
the answer that comes back into the agent's context is bounded, and the working
is preserved where it can be read.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any

from langchain.tools import tool
from langgraph.config import get_config

from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags
from deerflow.config.paths import get_paths
from deerflow.documents.analysis import AnalysisResult, analyze_document_text
from deerflow.documents.extraction import assess_extraction
from deerflow.documents.ocr import ocr_pdf_to_markdown
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.tools.types import Runtime
from deerflow.utils.context_budget import resolve_context_budget
from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown

logger = logging.getLogger(__name__)

_UPLOADS_PREFIX = "/mnt/user-data/uploads/"
_NOTES_DIRNAME = "document-analysis"


def _resolve_thread_id(runtime: Runtime | None) -> str | None:
    if runtime is not None:
        thread_id = runtime.context.get("thread_id") if runtime.context else None
        if thread_id:
            return thread_id
        runtime_config = getattr(runtime, "config", None) or {}
        thread_id = runtime_config.get("configurable", {}).get("thread_id")
        if thread_id:
            return thread_id
    try:
        return get_config().get("configurable", {}).get("thread_id")
    except RuntimeError:
        return None


def _resolve_user_id(runtime: Runtime | None) -> str:
    if runtime is None:
        return get_effective_user_id()
    from deerflow.runtime.user_context import resolve_runtime_user_id

    return resolve_runtime_user_id(runtime) or get_effective_user_id()


def _filename_from(path: str) -> str | None:
    """Reduce a caller-supplied path to a single filename inside uploads.

    Accepts the virtual upload path or a bare name and rejects anything that
    would escape the uploads directory — the tool reads whatever it is pointed
    at, so the containment check belongs here rather than in the caller.
    """
    candidate = path.strip()
    if not candidate:
        return None
    if candidate.startswith(_UPLOADS_PREFIX):
        candidate = candidate[len(_UPLOADS_PREFIX) :]
    candidate = candidate.lstrip("/")
    name = Path(candidate).name
    if not name or name != candidate or name in {".", ".."}:
        return None
    return name


def _companion_markdown(source: Path) -> Path | None:
    """Return the converted Markdown companion for *source*, if one exists."""
    for candidate in (source.with_name(source.name + ".md"), source.with_suffix(".md")):
        if candidate.is_file():
            return candidate
    return None


def _model_for(name: str | None, app_config: Any):
    from deerflow.models import create_chat_model

    if name is None and app_config.models:
        name = app_config.models[0].name
    return create_chat_model(name, app_config=app_config)


def _vision_model_name(app_config: Any) -> str | None:
    configured = app_config.documents.ocr.model_name
    if configured:
        return configured
    for entry in app_config.models or []:
        if getattr(entry, "supports_vision", False):
            return entry.name
    return None


def _write_notes(result: AnalysisResult, outputs_dir: Path, source_name: str) -> str | None:
    """Persist the per-part notes and return the virtual path to them."""
    try:
        notes_dir = outputs_dir / _NOTES_DIRNAME
        notes_dir.mkdir(parents=True, exist_ok=True)
        notes_path = notes_dir / f"{source_name}.notes.md"
        body = "\n\n".join(note.render() for note in result.notes)
        notes_path.write_text(f"# Notes for {source_name}\n\n{result.coverage_line()}\n\n{body}\n", encoding="utf-8")
        return f"/mnt/user-data/outputs/{_NOTES_DIRNAME}/{notes_path.name}"
    except OSError:
        logger.warning("Could not write analysis notes for %s", source_name)
        return None


async def _analyze_document_impl(
    path: str,
    question: str,
    max_pages: int | None = None,
    runtime: Runtime | None = None,
    *,
    _paths: Any | None = None,
    _app_config: Any | None = None,
) -> str:
    """Core implementation — testable without the @tool wrapper."""
    from deerflow.config.app_config import get_app_config

    app_config = _app_config or get_app_config()
    settings = app_config.documents

    thread_id = _resolve_thread_id(runtime)
    if thread_id is None:
        return "Error: no thread context is available, so uploaded files cannot be located."

    filename = _filename_from(path)
    if filename is None:
        return f"Error: {neutralize_untrusted_tags(path)!r} is not a file in /mnt/user-data/uploads/."

    user_id = _resolve_user_id(runtime)
    paths = _paths or get_paths()
    uploads_dir = paths.sandbox_uploads_dir(thread_id, user_id=user_id)
    source = uploads_dir / filename
    if not source.is_file():
        return f"Error: {neutralize_untrusted_tags(filename)} is not in this thread's uploads."

    # 1. Get Markdown for the document: an existing companion, a fresh
    #    conversion, or the file itself when it is already text.
    text, origin = await _load_text(source, settings)

    quality = assess_extraction(text)
    ocr_note = ""
    # 2. A missing text layer is not a short document — it is a scan. Route it
    #    through page images before concluding anything about the content.
    if quality.is_sparse and source.suffix.lower() == ".pdf":
        text, ocr_note = await _ocr_text(source, paths, thread_id, user_id, app_config, max_pages)
        origin = "OCR transcript of the page images"
        if not text.strip():
            return f"{quality.describe()} {ocr_note}".strip()

    if not text.strip():
        return f"{neutralize_untrusted_tags(filename)} contains no readable text. {quality.describe()}"

    # 3. Map-reduce over the text, with the chunk size set by the model that
    #    will actually read it.
    model = _model_for(settings.model_name, app_config)
    result = await analyze_document_text(
        text,
        question,
        model,
        budget=resolve_context_budget(model, app_config),
        max_chunk_chars=settings.max_chunk_chars,
        max_chunks=settings.max_chunks,
        concurrency=settings.concurrency,
    )

    outputs_dir = paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    notes_path = _write_notes(result, outputs_dir, filename)

    answer = result.answer
    if len(answer) > settings.answer_max_chars:
        answer = answer[: settings.answer_max_chars] + "\n\n[answer truncated]"

    lines = [answer, "", f"— source: {neutralize_untrusted_tags(filename)} ({origin}); {result.coverage_line()}."]
    if ocr_note:
        lines.append(f"— {ocr_note}")
    if notes_path:
        lines.append(f"— per-part notes: {notes_path}")
    return "\n".join(lines)


async def _load_text(source: Path, settings: Any) -> tuple[str, str]:
    """Return the document's Markdown and a short description of where it came from."""
    companion = _companion_markdown(source)
    if companion is not None:
        return companion.read_text(encoding="utf-8", errors="replace"), "converted Markdown"

    if source.suffix.lower() in CONVERTIBLE_EXTENSIONS:
        converted = await convert_file_to_markdown(source)
        if converted is not None and converted.is_file():
            return converted.read_text(encoding="utf-8", errors="replace"), "converted Markdown"
        return "", "conversion failed"

    try:
        return source.read_text(encoding="utf-8", errors="replace"), "plain text"
    except OSError:
        return "", "unreadable"


async def _ocr_text(
    source: Path,
    paths: Any,
    thread_id: str,
    user_id: str,
    app_config: Any,
    max_pages: int | None,
) -> tuple[str, str]:
    """Transcribe a scanned PDF, returning the text and a note about the attempt."""
    ocr_settings = app_config.documents.ocr
    if not ocr_settings.enabled:
        return "", "OCR is disabled (`documents.ocr.enabled`), so a scanned document cannot be read."

    vision_model_name = _vision_model_name(app_config)
    if vision_model_name is None:
        return "", "no vision-capable model is configured, so the scanned pages cannot be transcribed. Add a model with `supports_vision: true`."

    try:
        model = _model_for(vision_model_name, app_config)
    except Exception:
        logger.exception("Could not build the OCR vision model %s", vision_model_name)
        return "", f"the configured vision model ({vision_model_name}) could not be loaded."

    work_dir = paths.sandbox_work_dir(thread_id, user_id=user_id) / ".ocr" / source.stem
    cache_path = source.with_name(source.name + ".ocr.md")
    try:
        result = await ocr_pdf_to_markdown(
            source,
            model,
            work_dir=work_dir,
            cache_path=cache_path,
            dpi=ocr_settings.dpi,
            max_pages=min(max_pages, ocr_settings.max_pages) if max_pages else ocr_settings.max_pages,
            concurrency=ocr_settings.concurrency,
        )
    except RuntimeError as exc:
        return "", str(exc)
    except Exception:
        logger.exception("OCR failed for %s", source.name)
        return "", "the OCR pass failed; see the Gateway log."

    note = f"text layer was empty, so {result.pages_transcribed} page(s) were transcribed with {vision_model_name}"
    if result.pages_failed:
        note += f" ({result.pages_failed} page(s) could not be transcribed)"
    return result.text, note


@tool(parse_docstring=False)
async def analyze_document(
    runtime: Runtime,
    path: Annotated[str, "The uploaded file to analyse, e.g. '/mnt/user-data/uploads/report.pdf' or just 'report.pdf'."],
    question: Annotated[str, "What you need to know from the document. Be specific — every part of the document is read against this question."],
    max_pages: Annotated[int | None, "For scanned PDFs only: cap how many pages are transcribed. Omit to use the configured limit."] = None,
) -> str:
    """Answer a question about a document that is too large to read into context.

    The document is split into parts sized for the model reading them; each part
    is read separately and the findings are combined. Scanned PDFs (no text
    layer) are transcribed from page images first, then summarised.

    Use this tool when:
    - the document is long (tens of pages or more) and the question spans it,
      rather than pointing at one known section;
    - `read_file` returned little or nothing for a PDF, which means the text
      layer is missing and the pages need to be looked at as images;
    - you are working on a model with a small context window.

    Skip this tool when:
    - you already know which section answers the question — `grep` for it and
      `read_file` that range, which is one call instead of many;
    - the document is short enough to read directly.
    """
    return await _analyze_document_impl(path=path, question=question, max_pages=max_pages, runtime=runtime)
