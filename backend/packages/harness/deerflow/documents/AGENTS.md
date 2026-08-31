# Long-document handling (`deerflow/documents/`)

Fork feature. Everything here exists so a document larger than the serving
model's context window is **read in bounded pieces**, and so a PDF whose text
layer is empty is **reported** rather than summarised into fiction.

The sibling module `deerflow/utils/context_budget.py` is the shared dependency:
it resolves the serving model's usable window and is what makes every size here
follow the model instead of a constant.

## Why this exists

Uploads were already handled the right shape — the agent gets a heading outline
and is told to `read_file` ranges and `grep`, not handed the document body. But
every size limit around that was a fixed character constant calibrated for a
200K-token cloud model, and the navigation itself is a multi-step tool loop,
which is the first capability a small quantized model loses under long input. So
the documents that most need help were the ones where the loop broke down first.

Three failures, three modules:

| Failure | Module |
| --- | --- |
| A 50,000-char `read_file` result is ~40% of a 32K window in one call | `utils/context_budget.py` (+ the sandbox tools and `ToolOutputBudgetMiddleware`) |
| A scanned PDF converts "successfully" to a near-empty file | `extraction.py` (detect), `ocr.py` (read it anyway) |
| The model has to navigate 200 pages itself | `chunking.py` + `analysis.py`, surfaced as the `analyze_document` tool |

## The four modules

- **`extraction.py`** — page anchors (`<!-- page: 12 -->`, emitted by
  `utils/file_conversion.py` from pymupdf4llm's `page_chunks=True`) and
  `assess_extraction`, which turns "did the conversion work?" into a number:
  characters per page. Anchors are excluded from that character count, so a scan
  of 200 blank pages does not look like 4KB of content.
- **`chunking.py`** — splits on structure (heading → page anchor → blank line →
  line break), never mid-sentence if it can help it, with a small overlap. Size
  comes from `chunk_chars_for(budget)`; every chunk carries line range, start
  page and enclosing heading so an answer can cite it.
- **`ocr.py`** — renders pages with pymupdf and transcribes each one on its own
  with a vision model. **Transcription never summarises** (see
  `TRANSCRIBE_PROMPT`): a model asked to summarise while reading is a model
  choosing what to drop before anyone has seen the document. A failed page
  leaves `FAILED_PAGE_MARKER` in place so the gap is visible. The transcript is
  cached as `<name>.ocr.md`; an all-failed run is deliberately **not** cached,
  which would make the failure permanent.
- **`analysis.py`** — map (one chunk per call, `NOTHING_RELEVANT` sentinel for
  the rest) then reduce. The reduce is **hierarchical**: notes that outgrow the
  window are merged in rounds, otherwise a long document just moves the overflow
  from the map stage to the reduce stage. `AnalysisResult.coverage_line()` states
  what was actually read — unread and unreadable parts are always said out loud.

## Rules that are load-bearing

- **A configured limit is a ceiling, never a floor.** `clamp_to_context` only
  lowers. An unknown window (`resolve_context_budget` returns `None`) leaves
  today's behaviour byte-identical, and an explicit `0` ("no limit") is never
  turned back on.
- **Transcribe and summarise are separate passes.** Folding them together is the
  cheaper implementation and the one that silently loses content.
- **Coverage is reported, not implied.** Every path that reads less than the
  whole document says so in the string the agent gets back.
- **OCR never runs on its own.** Only when a text layer is missing *and* the
  agent called `analyze_document` on that file. Enabling it cannot start
  spending vision calls by itself.

## Wiring

- `analyze_document` (`tools/builtins/analyze_document_tool.py`) is registered in
  `tools/tools.py` alongside `list_uploaded_files`, gated on `documents.enabled`.
  It resolves the upload, converts, checks quality, routes a scan through OCR,
  runs the map-reduce, writes per-part notes to
  `/mnt/user-data/outputs/document-analysis/`, and returns a bounded answer.
- `UploadsMiddleware` calls `_extraction_warning` per file, so a scanned upload
  announces itself in `<current_uploads>` and points at the tool.
- Config lives in `config/documents_config.py` (`documents:` in
  `config.example.yaml`).

Tests: `backend/tests/test_context_budget.py`,
`test_context_aware_tool_output.py`, `test_document_extraction.py`,
`test_document_chunking.py`, `test_document_ocr.py`,
`test_document_analysis.py`, `test_analyze_document_tool.py`.
