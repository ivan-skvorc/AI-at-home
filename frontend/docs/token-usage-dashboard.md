# Token usage dashboard

The workspace page at `/workspace/usage` presents the existing current-user
reporting APIs introduced in upstream PR #3920. It adds no database tables,
permissions, provider calls, billing logic or dependencies. The fork's input /
output split (FORK.md §48) added only optional, zero-defaulted response fields.

## Extension-first evaluation

A packaged extension can register a page and sidebar navigation through
`PluginContribution` and `BrowserAssets`. That is a viable alternative when
operators want an optional, independently distributed reporting product.

This contribution proposes a built-in view of DeerFlow's existing console APIs.
It is presentation of an existing core capability, with shared React components,
locale types, authenticated fetch and account-scoped query caching. The page
does not introduce a second reporting service or token collector. A packaged
implementation would additionally need its installation/lifecycle and a browser
module or namespaced backend action adapter; the page mount context currently
exposes `callBackend` for plugin actions rather than a typed console reader.

Both approaches can express the feature. The built-in proposal keeps the existing
API and its authorization boundary unchanged and makes its reports discoverable
without an extra deployment installation. Maintainer agreement on this product
placement is still needed before upstream submission; this rationale does not
claim that extension hooks are incapable of supporting it.

The author's fork associated with #3920 already contains a console UI. This
contribution complements the merged API; it does not claim to introduce token
accounting or the first dashboard implementation.

## Reporting contract

- `GET /api/console/usage` supplies 7/30-day totals, daily buckets and per-model
  counts. Browser UTC offset is sent as `tz_offset_minutes`. Existing fixed-offset
  semantics apply across the whole window, including daylight-saving transitions.
- The API attributes all recorded tokens in a run to its creation date, rather
  than the wall-clock date of each individual model call. Active runs may still
  have partial persisted counters; providers that omit usage can leave gaps.
- Cache-hit input tokens are a subset of input tokens, not an additional amount
  to add to total tokens. Model run counts are non-exclusive for multi-model runs.
- Every total is split by `splitTokens` (`core/usage/format.ts`): input, output
  and unattributed always add up to the total, and cached never exceeds input.
  "Unattributed" is what a provider reported as a total without its split; it is
  never folded into input or output. The headline uses `total_input_tokens` /
  `total_output_tokens` / `total_cache_read_tokens`, falling back to the sum of
  the daily buckets for a Gateway that predates them. Bars stack cached input, the
  rest of input, output and unattributed; the per-day table keeps its columns.
- `GET /api/console/runs` supplies 20 rows per page and a `has_more` sentinel.
  All/error/timeout filters reset pagination. This history is independent of the
  chart's period. Offset pagination is live, not a snapshot.
- Run links reuse `pathOfThread` and the recorded `assistant_id`. The built-in
  `lead_agent` and absent/empty legacy IDs open normal chats. Custom assistant
  aliases are trimmed, lowercased and have underscores changed to hyphens,
  matching the Gateway identity convention; they open that agent's chat route.
  Thread IDs are encoded as opaque path segments by the shared route helper.
- Counts are provider-reported usage recorded by DeerFlow, not provider invoices.
  The view displays no estimated prices. Existing optional `cost`, `total_cost`
  and `currency` response fields, configuration and tests remain unchanged.

## Access and failure behavior

The sidebar entry and queries require a current user with `runs:read`. Static
demos issue no usage requests. The Gateway enforces authorization and owner scope;
the frontend does not grant access. Memory-only storage reports 503 and the page
explains the SQLite/PostgreSQL requirement. Forbidden, unavailable, loading and
empty reports remain distinct; failed requests never become fabricated zeroes.

Query keys include owner and report filters. The authenticated workspace owns
cache lifetime; consumed AbortSignals cancel obsolete reads. Switching period
does not display the previous period as placeholder data. Only the first run
page refreshes on focus/reconnect. Refresh explicitly reloads both panels.

## Verification

Run `pnpm check`, `pnpm rstest run tests/unit/core/usage` and
`pnpm exec playwright test tests/e2e/usage-dashboard.spec.ts` from `frontend/`.
The browser suite uses mocked APIs and exercises navigation, periods, timezone,
failure recovery, filtering, pagination, English and Chinese mobile layout.
The dashboard tests deliberately include the upstream monetary response fields
to prove that token-only presentation does not require removing those fields.
