# Delimited artifact preview

Split out of [`frontend/AGENTS.md`](../../../../AGENTS.md) to keep it within its
guidance budget (`scripts/check_agent_guidance.py`). Upstream keeps this text
inline in that file; port its edits here.

CSV/TSV previews share `artifact-table-preview.tsx` between the panel and standalone viewer. Papa Parse runs only inside `delimited-preview.worker.ts`; `use-delimited-preview.ts` bounds input before transfer, cancels stale work, and enforces a five-second timeout. The parser detects the first record separator outside quoted fields and passes it explicitly to Papa Parse, so embedded newlines in an incomplete quoted field cannot corrupt newline detection. It retains at most 202 logical records and 50 columns, discarding an incomplete final record from truncated input. UI pagination displays at most 200 data rows in pages of 50. Keep the table mounted but inactive when switching to source so header/pagination state survives; changing file identity resets it. Pending `write_file` content stays in source mode until success.

For a truncated sample whose first separator is LF or CRLF, strip a terminal CR
before parsing so a split CRLF separator cannot make a quoted final field
invalidate the whole preview, including LF-first files with later CRLF records.
The terminal record remains incomplete and is discarded; complete CR-only files
and malformed quotes retain their existing behavior.
