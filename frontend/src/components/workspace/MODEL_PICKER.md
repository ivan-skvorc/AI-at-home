# One model picker, everywhere (fork)

Moved out of `frontend/AGENTS.md` to keep that file under its guidance budget
(`scripts/check_agent_guidance.py`); the pointer there is the entry point.

Selecting a model is
`components/workspace/model-select.tsx` (`ModelSelect`) — or, inside the
composer and sidecar, the `ModelPickerControls` + `ModelPickerList` pair it is
built from (`components/workspace/model-picker-controls.tsx`). Do **not** map
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
