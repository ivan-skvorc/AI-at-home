"""Configuration for long-document analysis and scanned-PDF OCR (fork feature)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentOcrConfig(BaseModel):
    """Reading a scanned PDF by rendering its pages and looking at them.

    Never runs on its own: OCR is attempted only when a document's text layer
    is missing *and* the agent was asked to analyse that document, so enabling
    it cannot silently start spending vision calls.
    """

    enabled: bool = Field(default=True, description="Allow OCR fallback when a PDF has no usable text layer.")
    model_name: str | None = Field(default=None, description="Vision model used to transcribe pages. Null selects the first vision-capable model in `models`.")
    dpi: int = Field(default=150, ge=72, le=600, description="Render resolution. 150 is legible for printed text; higher multiplies the image payload for little gain.")
    max_pages: int = Field(default=100, ge=1, description="Hard ceiling on pages transcribed in one call — a bound on cost, not on document size.")
    concurrency: int = Field(default=2, ge=1, le=16, description="Parallel page transcriptions. The target is one local GPU, where extra parallelism only queues.")


class DocumentsConfig(BaseModel):
    """Map-reduce analysis of documents that do not fit the context window."""

    enabled: bool = Field(default=True, description="Expose the `analyze_document` tool.")
    model_name: str | None = Field(default=None, description="Model used for the map and reduce steps. Null uses the default chat model.")
    max_chunks: int = Field(default=60, ge=1, description="Maximum parts read in one call. Bounds cost on a very long document; the answer says when it applied.")
    max_chunk_chars: int = Field(default=60_000, ge=1_000, description="Ceiling on the derived chunk size, however large the model's window is.")
    concurrency: int = Field(default=2, ge=1, le=16, description="Parallel map calls.")
    answer_max_chars: int = Field(default=8_000, ge=500, description="Cap on the answer returned into the agent's context. The full notes are always written to a file.")
    ocr: DocumentOcrConfig = Field(default_factory=DocumentOcrConfig, description="Scanned-PDF OCR fallback.")
