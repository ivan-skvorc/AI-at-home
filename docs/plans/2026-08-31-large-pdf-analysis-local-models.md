# Analysing large PDFs with local and small cloud models

**Status:** research note + proposed solution stack. Nothing here is implemented.
**Date:** 2026-08-31

A large PDF that a frontier cloud model handles fine degrades badly — or fails outright —
when the same thread runs on a local Ollama model or a small cloud model. This note
separates the causes (most are not the model being "dumb"), maps them onto how this repo
is actually wired, and proposes fixes ordered by effort.

---

## 1. The failure modes, and what each one looks like

| Symptom | Layer at fault |
| --- | --- |
| Answers about content that is not in the document; invents section numbers | extraction produced little/no text (scanned or image-based PDF) |
| Numbers in tables are wrong, or belong to the neighbouring column | extraction flattened a complex table into Markdown |
| The model answers only from the first and last pages; misses the middle | context (lost-in-the-middle / context rot) |
| The model ignores the system prompt and output format once the doc is attached | provider-side prompt truncation (head dropped) |
| The turn dies with a context-length error, or the run stops mid-tool-call | window overflow |
| Tool calls degrade into loops — repeated `read_file` of the same range, no synthesis | small/quantized model losing instruction-following under long input |
| Works on 20 pages, collapses on 200 | none of the above individually; all of them compounding |

They have different fixes, so the first diagnostic step is always: **read the converted
Markdown yourself** (`/mnt/user-data/uploads/<name>.pdf.md`). If it is empty, garbled, or
the tables are mush, no amount of model or context tuning will help.

---

## 2. Root causes

### 2.1 Extraction: garbage in

- `pymupdf4llm` extracts the PDF's *text layer*. A scanned or image-only PDF has none, so
  the output is near-empty — and this repo's fallback (`MarkItDown`) does not OCR either
  unless configured with an LLM client. The result is a plausible-looking `.md` companion
  containing almost nothing, which the agent then confidently "summarises".
- Markdown tables cannot express merged cells, nested headers, or irregular grids, so
  financial statements and scientific tables are routinely corrupted in conversion — and
  the corruption is silent, with no confidence signal attached
  ([unstract](https://unstract.com/blog/why-pdf-to-markdown-ocr-fails-for-ai-document-processing/),
  [themenonlab comparison](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026)).
- Multi-column layouts (papers, filings) can interleave columns into a single reading
  order, so sentences from adjacent columns fuse.
- Attention weights tokens by *distance*; in a table, meaning comes from *position* in a
  grid. Even a correctly converted table is a weak representation for an LLM
  ([Daloopa](https://daloopa.com/blog/analyst-best-practices/processing-tabular-financial-data-with-large-language-models)).

A frontier model tolerates a mediocre conversion because it has the headroom to
reconstruct meaning from context. A small model does not — the same conversion that is
"good enough" for Opus is below the floor for an 8B.

### 2.2 Context: the advertised window is not the usable window

- **Context rot.** Chroma's study across 18 models (GPT-4.1, Claude 4, Gemini 2.5, Qwen3)
  found reliability falls as input grows *even on trivial retrieval and text-replication
  tasks* — degradation is a property of long input, not of task difficulty
  ([Chroma](https://www.trychroma.com/research/context-rot),
  [summary](https://www.morphllm.com/context-rot)).
- **Lost in the middle.** Accuracy follows a U-curve: strong at the start and end of the
  input, 30%+ worse in the middle — which is exactly where page 40 of an 80-page PDF lands
  ([Atlan](https://atlan.com/know/llm/lost-in-the-middle-problem/)).
- **Advertised vs. effective length.** Independent testing puts reliable capacity at
  roughly 60–70% of the stated maximum, with the largest windows degrading earliest
  ([elvex](https://www.elvex.com/blog/context-length-comparison-ai-models-2026)). A model
  advertising 128K is not a model that can analyse 128K of PDF.
- **Silent truncation.** Ollama loads models at a default `num_ctx` of 2048–4096 tokens
  regardless of what the model supports, and truncates over-long prompts **without any
  error** — HTTP 200, normal `finish_reason`, nothing in the body. Worse, it keeps the
  *tail*, so the system prompt, the instructions and the output schema are the first
  things discarded; the model then receives a slab of document with no instructions
  attached. The OpenAI-compatible endpoint makes this easy to hit, because `num_ctx` is
  not an OpenAI parameter and is dropped by many clients
  ([RepoFold](https://repofold.dev/blog/ollama-silently-truncates-your-prompts),
  [SSD Nodes](https://www.ssdnodes.com/learn/ollama-context-length-num-ctx)).
  This single cause explains most "the local model ignored my instructions" reports.

### 2.3 The model itself

- **4-bit quantization hurts long context specifically.** Across FP8/GPTQ-int8/AWQ-int4/
  GPTQ-int4/BNB-nf4 on Llama-3.1 and Qwen-2.5, 8-bit stays within ~0.8% of baseline while
  4-bit loses substantially, *with the largest drops on long-context tasks* (up to 59%),
  and instruction-following (IFEval) loses >10%
  ([arXiv 2505.20276](https://arxiv.org/abs/2505.20276)). Instruction-following and
  multilingual ability are the first capabilities to break — which is why a quantized model
  stops obeying the agent loop precisely when the document gets big.
- **Quantized KV cache compounds it.** `q4_0` KV cache halves memory but degrades quality
  where attention precision matters most — long context — and adds per-token dequantization
  overhead that gets *worse* as the window fills (~37% slower decode at 110K vs `f16`)
  ([llama.cpp discussion](https://github.com/ggml-org/llama.cpp/discussions/20969),
  [vLLM docs](https://docs.vllm.ai/en/latest/features/quantization/quantized_kvcache/)).
  So the usual local recipe for "fit a longer context" — quantize the KV cache — buys
  window at the cost of the exact capability the window was for.
- **Agentic navigation is a capability, not a given.** This repo's design asks the model to
  *drive*: read the outline, `grep`, `read_file` a range, synthesise. That is a multi-step
  tool-use loop, and it is the first thing an 8B quantized model loses under long input.

### 2.4 Workflow: nothing between "whole document" and "the model figures it out"

The long-document literature converged on structure, not bigger windows: map-reduce
(summarise chunks in parallel, then reduce), hierarchical/RAPTOR (cluster → summarise →
recurse, retrieve at any level), and GraphRAG for global questions
([FutureAGI](https://futureagi.com/blog/rag-summarization/),
[Galileo](https://galileo.ai/blog/llm-summarization-strategies)). The consensus failure
diagnosis is that chunking, retrieval and reduction get treated as implementation details
rather than design choices. This repo currently has none of those three as a first-class
step for uploads.

---

## 3. How this repo is wired today

**What is already right:**

- Conversion has a two-converter strategy with an image-based-PDF detector —
  `backend/packages/harness/deerflow/utils/file_conversion.py:55` uses chars-per-page
  (`_MIN_CHARS_PER_PAGE = 50`) rather than an absolute threshold.
- The agent is *not* handed the document body. `UploadsMiddleware`
  (`backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py`) injects a
  heading outline with line numbers and tells the model to use `read_file` ranges and
  `grep` — the right shape for a small window.
- `read_file` supports `start_line`/`end_line`; `grep` and `glob` exist; oversized tool
  results are externalised to disk with a synopsis (`tool_output` in `config.example.yaml`).
- `scripts/sync-ollama-models.py` writes an explicit `num_ctx` per model (VRAM-aware, capped
  at `DEFAULT_NUM_CTX_CAP = 32768`), which is precisely the defence against §2.2's silent
  truncation.
- `model_fallback` already treats a context-length rejection as a fallback trigger.

**What is mis-sized for a 32K local model** — the defaults are calibrated for a 200K cloud
model, and nothing derives them from the model actually serving the run:

| Setting | Value | On a 32K local model |
| --- | --- | --- |
| `sandbox.read_file_output_max_chars` | `50000` chars | ≈12.5K tokens in **one** tool result — ~40% of the window per call, and larger than the entire window of an 8K model |
| `tool_output.exempt_tools` | includes `read_file` | the one tool most likely to return a document slab is exempt from externalisation (correct, to avoid persist→read→persist loops — but it means the char cap above is the *only* guard) |
| `summarization.trigger` | `32000` tokens | equals the whole window of a synced Ollama model: compaction fires only *after* the window has already overflowed |
| `summarization.trim_tokens_to_summarize` | `15564` | the compaction call itself is a large prompt on a small model |
| `token_budget.max_tokens` | `200000` | meaningless as a guard here; it is a cost cap, not a context cap |

Two further concrete gaps:

1. **`num_predict` eats the window.** `render_entry` (`scripts/sync-ollama-models.py:587`)
   writes `num_ctx: 32768` with `num_predict: 8192`. Ollama's `num_ctx` covers prompt *and*
   generation, so usable prompt space is ~24K, not 32K — and no budget in the repo knows it.
2. **Synced Ollama entries carry no `context_window`.** `render_entry` writes `num_ctx` but
   never `context_window`, so the field that drives the UI's "% context used" indicator and
   the `model_routing` guard (`backend/packages/harness/deerflow/subagents/routing.py:98`:
   `if context_window and requirements.estimated_context > context_window`) is unset. The
   guard short-circuits on `None` — meaning cost-aware routing can hand a large-document
   subagent to a local model whose window cannot hold the prompt, which is the exact trade
   `config.example.yaml` says it refuses to make.

Also worth stating plainly: `uploads.auto_convert_documents` defaults to `false`, so on a
default install the agent may be looking at a raw `.pdf` with no `.md` companion at all.

---

## 4. Proposed solutions

### Tier 0 — configuration only, no code (do these first)

1. **Verify the real prompt space.** Confirm `num_ctx` on the served model
   (`ollama show <model>` / the daemon log) matches the config entry. If a model is reached
   over an OpenAI-compatible endpoint rather than `langchain_ollama:ChatOllama`, assume
   `num_ctx` is being dropped and the prompt silently truncated.
2. **Scale the budgets to the window.** For a 32K model, roughly:
   `sandbox.read_file_output_max_chars: 12000` (~3K tokens/call),
   `sandbox.bash_output_max_chars: 6000`, `tool_output.externalize_min_chars: 6000`,
   `summarization.trigger: {type: tokens, value: 18000}`,
   `summarization.trim_tokens_to_summarize: 8000`. The `fraction` trigger type is the
   principled version, but it resolves against the model profile's max input tokens, which
   local providers frequently do not publish — verify it resolves before relying on it.
3. **Add `context_window:` to local model entries by hand** (`num_ctx` minus `num_predict`),
   so the UI indicator and the routing guard have a number to work with.
4. **Prefer 8-bit over 4-bit for document work**, and keep the KV cache at `f16`. Per
   §2.3 this is the highest-leverage single change for long-input quality, and it costs
   VRAM rather than engineering.
5. **Turn on `model_fallback`** with a cheap cloud model in the chain, so a context-length
   rejection degrades instead of losing the turn.
6. **Split the work by hand for now:** ask per-section rather than "summarise this
   80-page PDF". This is the manual version of what Tier 2 automates.

### Tier 1 — small, contained code changes

7. **Derive tool-output budgets from the serving model's context window** instead of fixed
   character constants. A `read_file` cap of ~10% of the window, computed at call time, is
   the fix that makes every other default portable across a 32K local model and a 200K
   cloud one. This is the single highest-value code change in this list.
8. **Emit page anchors during conversion.** Have `file_conversion.py` write
   `<!-- page: N -->` markers per page. This gives the agent citable locations, makes
   "which page did that come from" answerable, and makes chunking page-aligned later.
9. **Surface conversion quality instead of hiding it.** `_pymupdf_output_too_sparse`
   already computes chars-per-page; when both converters come back sparse, say so in the
   `<current_uploads>` block ("this PDF appears to be image-based; text extraction
   recovered ~3 chars/page — OCR required") rather than letting the agent narrate an empty
   file. Silent low-quality extraction is the worst of the failure modes because it is
   indistinguishable from a bad answer.
10. **Extend the outline into a section map with sizes.** Today the agent gets headings and
    line numbers (capped at `MAX_OUTLINE_ENTRIES = 50`). Adding per-section line spans and
    token estimates lets a small model plan reads that fit its window instead of
    discovering the limit by overflowing it.

### Tier 2 — real features

11. **A map-reduce document skill.** A `skills/public/` skill that owns the loop: walk the
    section map, `read_file` one bounded section at a time, write a per-section note to
    `/mnt/user-data/outputs/`, then reduce the notes into the final answer. Each model call
    sees one section plus its own notes — never the document. This converts "can the model
    hold 200 pages" (no) into "can the model handle 4 pages at a time" (yes, reliably), and
    it is the standard map-reduce/hierarchical pattern from §2.4. It also fits this fork's
    economics: the map stage is embarrassingly parallel and tool-free, so `model_routing`
    can push it to local models while a stronger model does the reduce.
12. **Local retrieval over uploads.** Chunk the converted Markdown (512–1024 tokens, 50–100
    overlap, page- and heading-aligned), embed locally, and expose a `search_uploads` tool.
    Today the only retrieval over uploads is `grep` — exact lexical match — so a question
    phrased differently from the document finds nothing. This overlaps with roadmap item 21
    (local embedding retrieval for DeerMem); the same embedding backend serves both.
13. **A real OCR / layout path for scanned PDFs.** Add an optional third converter tier —
    [Docling](https://docling.org/) (standard pipeline with RapidOCR, or its VLM pipeline)
    or [Marker](https://pypi.org/project/marker-pdf/) — behind the existing
    `uploads.pdf_converter` setting, triggered automatically when the sparse-output detector
    fires. Both run locally on a laptop, which matches the fork's no-data-leaves-the-house
    thesis. Note the tradeoff: a VLM-based converter can hallucinate, omit, or truncate
    without raising an error, so page anchors (#8) and a quality signal (#9) matter more,
    not less, once OCR is in play.
14. **Page-image fallback for a vision-capable local model.** The repo already tracks
    `supports_vision` and has `view_image`; rendering a page to an image and asking a local
    VLM directly is the last resort when text extraction fails and OCR is unavailable.
15. **Measure it.** None of the above should be judged by feel. A small fixture set — a
    text PDF, a multi-column paper, a scanned page, a financial table — with known answers,
    run across one local and one cloud model, turns this from taste into a regression test.
    This is what roadmap item 25 (behavioural regression suite) is for.

### Ordering

Tier 0 items 1, 2 and 4 are the diagnosis and probably recover most of the gap on
text-layer PDFs. Item 7 makes that fix permanent and portable. Items 8–9 stop the silent
failures. Item 11 (map-reduce skill) is the structural fix and delivers the most per unit
of work; item 12 (local retrieval) is the natural follow-on; item 13 (OCR) is only urgent
if scanned documents are actually in scope.

---

## Sources

- [Context Rot: How Increasing Input Tokens Impacts LLM Performance — Chroma](https://www.trychroma.com/research/context-rot) · [summary](https://www.morphllm.com/context-rot)
- [Lost-in-the-Middle Problem: Why Context Position Matters — Atlan](https://atlan.com/know/llm/lost-in-the-middle-problem/)
- [AI Model Context Window Comparison 2026: Advertised vs. Real — elvex](https://www.elvex.com/blog/context-length-comparison-ai-models-2026)
- [Ollama silently truncates your prompts — RepoFold](https://repofold.dev/blog/ollama-silently-truncates-your-prompts) · [Ollama context length: setting num_ctx — SSD Nodes](https://www.ssdnodes.com/learn/ollama-context-length-num-ctx)
- [Does quantization affect models' performance on long-context tasks? — arXiv 2505.20276](https://arxiv.org/abs/2505.20276)
- [TurboQuant — Extreme KV Cache Quantization (llama.cpp discussion #20969)](https://github.com/ggml-org/llama.cpp/discussions/20969) · [Quantized KV Cache — vLLM](https://docs.vllm.ai/en/latest/features/quantization/quantized_kvcache/)
- [Why PDF-to-Markdown OCR fails for AI document processing — Unstract](https://unstract.com/blog/why-pdf-to-markdown-ocr-fails-for-ai-document-processing/)
- [Best Open-Source PDF-to-Markdown Tools in 2026: Marker vs Docling vs MinerU vs pdf-craft vs PyMuPDF4LLM](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026)
- [Docling — document processing, Granite-Docling VLM & OCR engines](https://docling.org/) · [marker-pdf](https://pypi.org/project/marker-pdf/)
- [Processing tabular financial data with LLMs — Daloopa](https://daloopa.com/blog/analyst-best-practices/processing-tabular-financial-data-with-large-language-models)
- [RAG Summarization 2026: patterns and long-context tradeoffs — Future AGI](https://futureagi.com/blog/rag-summarization/) · [LLM summarization strategies — Galileo](https://galileo.ai/blog/llm-summarization-strategies)
