# Fork notes for `frontend/src/`

Split out of [`AGENTS.md`](AGENTS.md) to keep it within its guidance budget
(`scripts/check_agent_guidance.py`); the pointer there is the entry point. Each
note is a fork feature whose rules break silently. Rationale and the tests that
pin them: [FORK.md](../../FORK.md).

## The image-generation page

`/workspace/image/new` has no sidebar entry (see
[`SIDEBAR.md`](components/workspace/SIDEBAR.md)) and reuses the Democracy
handoff wholesale — `core/threads/image-generation.ts` stash +
`IMAGE_LAUNCH_EVENT`, claimed in `chats/use-image-launch.ts`, delivered as
`InputBox`'s **`initialValue`** — so the same two traps apply: claim on mount
_and_ on the event (a same-route `router.push` remounts nothing), and never
`setInput` (the uncontrolled textarea's draft hydration runs after mount and
overwrites it). What differs is deliberate: it sets **no thread context**.
There is no "image mode" — the page seeds an ordinary instruction, because
which path can serve it (the local ComfyUI tools, the cloud `image-generation`
skill, the refine loop) is a runtime fact the agent resolves, and a mode flag
would have had to pick one at build time. The pixel size is written into the
seed rather than left to the model: asked for "landscape" it picks its own
numbers, and for a clip those are the ones that exhaust VRAM minutes in — it is
two editable numbers with the aspect names as presets, snapped to the latent
grid and shown snapped, because a shape name is not a size. The prompt-mode
toggle travels in the seed too: `direct` demands the prompt verbatim,
`assisted` asks for a positive _and_ negative prompt shown before generating,
and `supportsNegativePrompt` (a checkpoint-name rule that errs toward offering
the field) decides whether a negative prompt is asked for at all — a CFG-1
model ignores one silently. Seeded, never sent — a clip costs minutes per
attempt.

## PWA and Web Push

`public/manifest.webmanifest` + `public/icons/` + the `metadata`/`viewport`
block in `app/layout.tsx` make the app installable, which on iOS is the
_precondition_ for receiving push at all. `public/sw.js` handles `push` and
`notificationclick` and **caches nothing**: DeerFlow is a live, server-driven
app, so a stale cached shell after a backend upgrade produces bugs that look
like backend faults; adding asset caching later means adding a version/cleanup
strategy with it. `core/notification/push.ts` owns support detection,
subscribe/unsubscribe and the test push. Its `detectPushSupport` checks
**insecure context first** — a plain-HTTP LAN origin (the fork's documented
deployment) makes every other API absent too, so reporting "service workers
unavailable" there sends the user hunting for a browser setting that does not
exist; each case renders its own explanation and fix in the settings page
instead of a switch that silently does nothing. Tests:
`tests/unit/core/notification/push.test.ts`.

## Subscription model settings

`components/workspace/settings/subscription-settings.tsx` is mounted only for
administrators under Models. Its catalog/query keys include the account ID;
mutations invalidate the existing model picker. Poll Grok only at the
provider's returned interval and cancel pending polling on unmount. Credentials
never enter browser storage or error messages. ChatGPT starts server-owned
PKCE, opens the official browser authorization link and accepts the final
loopback return URL pasted by the user. The handoff is manual because the
remote server cannot receive that callback. Keep return URLs only in component
memory; clear them on close, restart and success. The helper download and JSON
import remain an advanced fallback. Kimi uses a subscription-key field with an
explicit interactive-use limit.

## Conversation file explorer (FORK.md §49)

The **Files** view of the artifacts panel lists `/mnt/user-data` through
`core/thread-files/` (`GET /api/threads/{id}/files`) and opens a file with the
artifacts context's `select(path)`, so previews and downloads stay in the
artifacts viewer; do not add a second file reader. The panel's view choice is
persisted with the rest of the panel state, and older persisted state without it
reads as the Artifacts view.
