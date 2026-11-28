# One model picker, everywhere (fork)

Moved out of `frontend/AGENTS.md` to keep that file under its guidance budget
(`scripts/check_agent_guidance.py`); the pointer there is the entry point.

Selecting a model is
`components/workspace/model-select.tsx` (`ModelSelect`) — or, inside the
composer (`composer-run-controls.tsx`, also mounted on plugin pages) and the
sidecar, the `ModelPickerControls` + `ModelPickerList` pair it is built from
(`components/workspace/model-picker-controls.tsx`). Do **not** map
`models` into `SelectItem`s: that is the state this feature existed to end, and
it is silent when reintroduced — a flat list in `config.yaml` order with a grey
price is not an error, it just makes a model impossible to find on that one
screen while every other screen sorts, groups, searches and colours. All the
pickers share the single `modelPicker` entry in `core/settings/local.ts`, so a
sort chosen in a conversation is already applied in Settings. Rows are
`ModelPickerRow` from the same file — provider, name, price pinned to the right
edge, and a local model's weights and context window under it, from
`modelRowParts` in `core/models/sorting.ts`. Hand-rolling that markup on one
screen is the same silent drift as a flat list: the row still renders, it just
lines up with nothing. Pinned by
`tests/unit/components/workspace/model-select.dom.test.tsx`,
`model-picker-sites.test.ts` and `tests/unit/core/models/sorting.test.ts`.

## The composer and Side Chat pickers are the fork's, not upstream's

Moved here from `frontend/src/AGENTS.md`, whose pointer is the entry point.

Both render `ModelSelector` (`components/ai-elements/model-selector.tsx`) around
`ModelPickerControls` + `ModelPickerList` + `ModelPickerRow`
(`components/workspace/model-picker-controls.tsx`); the composer's copy is
`ComposerModelPicker` in `composer-run-controls.tsx` — the search field, the
sort/group controls and the price column described above. Upstream replaced
that pair with a favorites-based `model-picker-content.tsx` and deleted
`ai-elements/model-selector.tsx`; this fork keeps its own picker and keeps
that file alive, because the fork's picker is the richer of the two and is
what FORK.md pins. `model-picker-content.tsx` is carried unchanged from
upstream and is **not** wired into the composer or Side Chat here — the
favorites feature it adds is not integrated yet. Do not "fix" the imports in
`composer-run-controls.tsx` or `sidecar-panel.tsx` to point at it: that silently trades
search, sorting, grouping and prices for favorites. For the same reason, the
model-picker bullet in `frontend/docs/conversation-ui-ownership.md` describes
upstream's picker, which this fork does not wire.

Upstream's `tests/e2e/model-favorites.spec.ts` came with the 2026-09-22 sync
and was **deleted**, because it drives a picker this fork does not render: its
trigger locator is `getByRole("button", { name: "Alpha", exact: true })` and
the fork's trigger also carries a "Main agent" / "Subagent" label, so all four
tests fail on the first line of `openMainModelPicker` before reaching a single
favorites assertion. Its row locator wants upstream's
`"<display name> (<id>)"` button; the fork renders cmdk `option` rows through
`ModelPickerRow`. It was deleted rather than skipped because a skipped spec
reads green and checks nothing. **A future sync will re-add it** — delete it
again, or, better, integrate favorites into `ModelPickerList`/`ModelPickerRow`
(the store landed intact: `core/models/favorites-store.ts`,
`favorites.ts`, `use-model-favorites.ts`) and write the spec against this
fork's DOM.

## Plugin pages use the composer's controls

A plugin page that lets the user choose a model (the Designs page) mounts
`SurfaceContext.composerControls` instead of drawing a list: the host renders
the composer's own mode menu, reasoning-effort menu and model pickers from
`composer-run-controls.tsx` (`ComposerModeMenu`, `ComposerReasoningEffortMenu`,
`ComposerModelPicker`, `ComposerSubagentModelPicker`) inside the plugin's
element, through `plugin-composer-controls.tsx`. `InputBox` renders the same
four components, so a change to a row, a mode or a capability rule reaches the
chat and every plugin page at once. A plugin `<select>` of `context.models` is
the flat list again on that one page, with no mode or effort. Pinned by
`model-picker-sites.test.ts`, `model-selector-overflow.test.ts` and
`plugin-composer-controls.dom.test.tsx`; the hook's contract is in
[full-stack plugins](../../../../docs/full-stack-plugins.md).

## Model price

Prices are no longer embedded in `display_name`. `GET /api/models` returns a
resolved `price` block (discount already expiry-filtered),
`core/models/sorting.ts::resolveModelPrice` reads it for sorting, and
`modelNameSegments` composes name + price into the same coloured segments the
old embedded pair produced — green for what you pay, red for the list price
beside a live promo. `ModelDisplayName` takes the `price` prop; every picker
(lead, subagent, sidecar) must pass it or the price silently disappears from
that dropdown. Parsing the name is retained as the fallback for a config
written before the move, and a name that still embeds a price has that copy
stripped so it is not rendered twice. Tests:
`tests/unit/core/models/sorting.test.ts`.
