# Runtime: fork notes

Reference detail for [AGENTS.md](AGENTS.md), which holds the rules. Fork
run-path invariants that span the Gateway are in
[`backend/docs/RUNTIME.md`](../../../../docs/RUNTIME.md); each feature's
rationale is in FORK.md.

## Auxiliary token accounting (`aux_usage.py`)

**Anything a conversation spends must be priced against that conversation.** The
chat header's cost figure is built from the `runs` table, so any LLM call that
does **not** become a graph run is invisible to it. `CHAT_AUX_CATEGORIES` names
those calls: memory extraction, follow-up suggestions, the composer's
prompt-polish rewrite, the per-turn goal check, and the header's on-demand
rename (FORK.md §38).

**The rule: a new non-graph LLM call that takes a `thread_id` gets a category in
`CHAT_AUX_CATEGORIES` and a `record_aux_usage_metadata` call in the same change
set.** This failure mode does not raise, log, or render a `—`. The header simply
prints a total lower than the money that left the account, and nothing on screen
distinguishes that from a cheap conversation. Both `input_polish` and `goal`
shipped uncounted and were found by an audit rather than by a bug report;
`input_polish` was `enabled: true` by default, so it was the one sink a user paid
for without opting into anything.

- **Use the shared unpacking.** `usage_metadata_kwargs` reads the response shape
  once, including the cache-hit count nested under
  `input_token_details.cache_read`. That nesting is what a hand-written copy
  drops, and a dropped cache-read count bills a cached prompt at the full input
  rate. Call `record_aux_usage_metadata` / `arecord_aux_usage_metadata`, not
  `record_aux_usage` with hand-unpacked fields.
- **Key the bucket on the provider-reported model ID**, normalized through
  `deerflow.model_ids.normalize_reported_model_name`. That is what
  `lookup_pricing` resolves a price from, and a stream-doubled ID (`m-1m-1`)
  matches nothing and prices at **zero**. The goal evaluator reads it off
  `response_metadata` because it usually runs on the configured default, so the
  requested name is `None`.
- **Sync vs. async is not a style choice.** Memory extraction records from the
  updater's `threading.Timer` debounce worker, which has no event loop; that is
  the whole reason the durable store is a dedicated SQLite file rather than the
  async runs engine. Everything on the request loop uses the `a*` wrappers, which
  offload the file I/O. `tests/blocking_io/test_aux_usage.py` is the strict
  anchor, and the fix for a failure there is to restore the offload, never to
  mark the anchor `allow_blocking_io`.
- **Keep the caller's own `try/except`** around the recording call even though
  the helper already swallows store failures. "A broken counter never breaks the
  feature it is counting" has to hold when a layer *beneath* the call site
  changes, not only when the store is down.
- **`agent_generation` is the deliberate exception.** It reads several
  conversations and belongs to none, so it is billed to a synthetic thread ID and
  shows on the spend page's feature table rather than in a chat header.

Tests: `tests/test_aux_usage.py` (registry and durability),
`tests/test_aux_usage_wiring.py` (every sink records; the new-sink cases go red
when a recording call is dropped), `tests/test_thread_token_usage.py` (each sink
priced at its own model, and durability through the real endpoint),
`tests/blocking_io/test_aux_usage.py`.
