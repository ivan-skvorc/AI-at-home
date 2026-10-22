### Data Flow

Scope local-turn ordering to `displayThreadId ?? threadId`, the displayed
conversation identity. Confirming a new chat changes the SDK `threadId` from
undefined to its existing display ID; preserve the human anchor across that
transition and clear it only on a displayed-conversation switch or the existing
failure/replay-gap paths. Draft and confirmation regressions live in
`tests/unit/core/threads/local-turn-order.dom.test.tsx`.

Answer details use `workspace/message-details` descriptors; skill run scoping
is documented in `docs/skill-usage-ui.md`.

Encode raw paths preserving literal percent escapes. Decode Markdown once;
match image names to raw paths.
Sanitize URLs; key Streamdown by file/thread/mock context and scroll key.
Detect file types by basename, including Dockerfile/Makefile.
Language maps use own properties; `constructor`/`__proto__` keep fallback.
HTML bases skip DOM without base text; inert templates ignore comments/scripts
and templates. `preview-base.dom.test.ts` (happy-dom); RCDATA needs
browser checks; other helpers use node.
HTML assets: credential GET, no 401 navigation; current-thread only, no redirects,
bound bytes/count/CSS depth/time/expansion; keep doctype, rewrite SVG style.
Keep opaque sandbox/data URLs; external refs stay browser-loaded.
Abort stale work; revoke URLs; gate content/URL/scroll.
Tests: `html-assets.dom.test.ts`, `artifact-file-preview.dom.test.tsx`,
`tests/e2e/artifact-preview.spec.ts`.

The thread/streaming data flow — run lifecycle, SSE frames, optimistic
messages, grouping and the ordering repair — is long enough to dominate this
file's guidance budget, so it lives beside it in
[`DATA_FLOW.md`](DATA_FLOW.md). Read that before changing anything under
`core/threads/` or `core/messages/`.

### Key Patterns

REST `core/api/fetcher.ts`: preserve Request; CSRF uses effective method/headers.

Conversation exports read every persisted message page through
`fetchThreadExportMessages` (200 rows/page). Run `mergeMessages` after history
deduplication to restore earliest trusted positions for identities repeated across runs.
Never export only the loaded UI window or compacted checkpoint. Fail the whole
export on a page error or non-advancing cursor; demos keep their fixture path.

- **Server Components by default**, `"use client"` only for interactive components
- **Static root boundary** — `src/app/layout.tsx` must not read cookies or import
  chat-only KaTeX/Streamdown styles. Auth and workspace layouts own the cookie-derived
  locale provider; docs derive locale from their route, and blog owns its preference
  cookie. Public server routes load one dictionary at a time through
  `core/i18n/translations.ts`; the interactive auth/workspace client provider owns both
  formatter-bearing dictionaries because functions cannot cross the RSC boundary.
  Keep public `/` static and keep rich-content CSS on the routes that render it.
- **Thread hooks** (`useThreadStream`, `useSubmitThread`, `useThreads`) are the primary API interface
- **Thread routes** — construct Web UI chat paths through `core/threads/utils.ts::pathOfThread()`, which percent-encodes both custom agent names and thread IDs before inserting them into route segments
- **LangGraph client** is a singleton obtained via `getAPIClient()` in `core/api/`
- **Run creation retries** are disabled only for the initial `POST /runs/stream` in `core/api/api-client.ts`, because an ambiguous failure can otherwise create duplicate runs. Automatic SSE recovery keeps the SDK's normal HTTP retry budget for `GET` requests to the server-provided `Location`, including transient 5xx responses, and forwards `Last-Event-ID`. Reads and explicit SSE joins keep their normal retry behavior. Regression tests cover both a failed creation POST and POST success → stream interruption → GET 504 → GET success.
- **Run stream options** are sanitized by `core/api/stream-mode.ts`: the Gateway-supported set is `values`, `messages-tuple`, `updates`, `debug`, `tasks`, `checkpoints`, and `custom`; any request containing an unsupported mode throws before HTTP instead of being partially forwarded or silently defaulting to `values`. `streamResumable` is retained by thread hooks only for SDK-side reconnect bookkeeping but stripped before the HTTP request because the Gateway does not accept that request option; actual replay uses the SSE `Last-Event-ID` cursor. The main chat client's initial and rejoined streams are forced to incremental `messages-tuple`, `updates`, and `custom` modes so SDK lazy tracking cannot add repeated full-state `values` snapshots; explicitly requested non-snapshot modes such as `debug`, `tasks`, and `checkpoints` are preserved. `values` remains supported outside this chat wrapper for explicit state inspection and by the replay-gap durable-state reload below. The backend file-tool chunk batcher is keyed to `messages-tuple`, not `values`, so omitting snapshots must not regress `write_file` / `str_replace` streaming into one SSE frame per model token. `core/threads/stream-state.ts` folds the user-visible non-message fields from `updates` with the matching DeerFlow reducer semantics, including `tool_artifacts` capture/consumption updates (same-handle replacement preserves order, retention directives trim the oldest entries, and the absolute ceiling is 1000) and rejects irrelevant frames before calling the SDK mutator, while the SDK's `messages-tuple` manager remains the sole owner of live message chunk assembly and deduplication. Keep this boundary aligned with the backend request schema; `messages` and `events` are not supported and must not be forwarded.
- **Active-run recovery** in `core/threads/hooks.ts` discovers pending/running runs when a reopened chat has no tab-local reconnect pointer. Remember SDK-completed run IDs for the mounted hook, including submitted and natively reconnected runs: stale or delayed runs reads must not rejoin a completed run and interrupt follow-up suggestions. Keep recovery retries bounded and continue allowing a different active run to reconnect. The SDK's same-tab reconnect keeps its pointer on error and never retries, so a failed reconnect (not a failed submit) releases the pointer and recovery takes over with its own bounded retries.
- **SSE replay gaps** (`core/api/api-client.ts`) wrap initial/joined streams as a lazy
  async iterable: the SDK ignores unknown events. An id-less `gap` clears stale
  reconnect metadata, emits a `stream_replay_gap` custom event, reloads durable values,
  then rejoins after the server-provided retained tail (without a cursor for an empty
  buffer). Allow five recovery rejoins after the original stream (six calls total).
  `core/threads/hooks.ts` clears optimistic/transient/subtask state, invalidates durable
  history caches and shows the localized warning; never finish normally on a gap or
  cancel the running backend run. Merge submitted initial-stream input or saved
  joined-stream input into each recovered values frame: the first checkpoint may not
  yet contain the human message.
  Restore the tab-local run pointer only if empty or still owned by this run, never
  over another run's pointer after a durable-state read. A foreign pointer can cost
  an extra lookup/rejoin on reload; add no server probe. The hooks' same-named
  `rememberReconnectRun` remains unconditional: active-run rejoin claims ownership.
- **Streaming Markdown rendering** is owned by `core/streamdown`: Streamdown's `animated` / `isAnimating` API handles incremental word animation, while the shared `streamdownRenderingPlugins` config registers the named code-highlighting and Mermaid plugins required by Streamdown 2.5. Keep wrappers and derived configs wired to that shared object; do not reintroduce a rehype plugin that wraps every word, because reparsing a growing block remounts old words and replays their animation.
- Citation links in message and artifact Markdown must derive their `citation:` label from the full `ReactNode` children tree, since Streamdown may provide element or array children during streaming rather than a plain string.
- Web-search steps accept either a provider result array or a Webz-style `{ query, returned_results, results }` envelope. Unwrap only in the web-search renderer; skip entries without string titles/URLs, preserve other tool payloads and apply the same link allowlist to both formats. UI regressions pin source titles/links and browser reloads, including malformed neighboring entries.
- Tool-step links in `message-group.tsx` (`web_fetch` args, `web_search` / `image_search` result URLs) are model- or provider-controlled, so they pass the markdown `isSafeHref` allowlist; every surface renders a rejected href through the shared `UnsafeLink` marker.
- **Environment validation** uses `@t3-oss/env-nextjs` with Zod schemas (`src/env.js`). Skip with `SKIP_ENV_VALIDATION=1`
- **Subtask step history and runtime metadata** (`core/tasks/`) — cards interleave subagent reasoning and tool steps (#3779). Task `description` is optional progress text; `MessageList` titles use the required `prompt`, then a localized generic label, so valid calls never show a blank title. `Subtask.steps[]` appends live `task_running` events via `mergeSteps`. On historical-card expansion, `fetchSubtaskSteps` backfills task-scoped events (GET `/runs/{runId}/events?event_types=subagent.step&task_id=…&after_seq=…`) until a short page or a non-advancing full page; run-wide limits must not truncate the timeline. `task_started` carries the effective `model_name`; `task_running` carries a cumulative usage snapshot after each completed LLM call. `core/tasks/lifecycle.ts` normalizes these additive events, and `computeNextSubtask` keeps the largest cumulative total so replayed or late SSE frames cannot double-count or roll the folded card backward. Terminal ToolMessage metadata (`subagent_model_name` / `subagent_token_usage`) restores the same values from normal history after reload; no per-card event fetch is needed. `core/tasks/steps.ts` is the pure step model: `messageToStep` (live), `eventsToSteps` (reload), `mergeSteps` (dedup by `message_index`), and `stepsForDisplay` (what the card renders — keeps tool steps + AI steps with text, drops the trailing final-answer AI step when completed since it's shown as `result`). `core/tasks/context.tsx`'s `useUpdateSubtask` applies updates against a `tasksRef` mirroring the latest state (not a closure snapshot), so a late-resolving `fetchSubtaskSteps` backfill merges into current state instead of clobbering SSE steps or sibling subtasks that arrived meanwhile. The owning `run_id` is carried onto history content messages in `buildVisibleHistoryMessages` so the card can resolve the events endpoint.
- Structured subtask status parsing in `core/tasks/subtask-result.ts` accepts only
  own keys of the status mapping. Prototype names such as `constructor`,
  `toString`, and `__proto__` use the same `in_progress` fallback as other unknown
  statuses; structured metadata prevents falling back to legacy result text.
- **Subtask render synchronization** (`core/tasks/subtask-render.ts`) — `MessageList` derives message-backed task snapshots in `useMemo` and publishes them to task context from an effect, never during render. Current message arguments own the card title and prompt; live task state retains lifecycle and runtime metadata until a terminal message snapshot supplies status/result/error. Cards receive the same snapshot as a render fallback so effect timing cannot leave streamed arguments stale.

### Interaction Ownership

- **The composer and Side Chat pickers are the fork's, not upstream's.** Both
  render `ModelSelector` (`components/ai-elements/model-selector.tsx`) around
  `ModelPickerControls` + `ModelPickerList` + `ModelPickerRow`
  (`components/workspace/model-picker-controls.tsx`) — the search field, the
  sort/group controls and the price column described under _One model picker,
  everywhere_ in [`../AGENTS.md`](../AGENTS.md). Upstream replaced that pair
  with a favorites-based `model-picker-content.tsx` and deleted
  `ai-elements/model-selector.tsx`; this fork keeps its own picker and keeps
  that file alive, because the fork's picker is the richer of the two and is
  what FORK.md pins. `model-picker-content.tsx` is carried unchanged from
  upstream and is **not** wired into the composer or Side Chat here — the
  favorites feature it adds is not integrated yet. Do not "fix" the imports in
  `input-box.tsx` or `sidecar-panel.tsx` to point at it: that silently trades
  search, sorting, grouping and prices for favorites.

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

Model picker, chat entry pages, branch tree, and browser-control ownership are
detailed in `frontend/docs/conversation-ui-ownership.md` (its model-picker bullet
describes upstream's picker, which this fork does not wire — see above).

- `core/threads/hooks.ts` owns uploads/sends. Both optimistic and submitted humans use `buildHumanMessageAdditionalKwargs` to retain quote/reference metadata and staged project files.
- `core/uploads/api.ts` rejects `success: false` before send or composer clear. Keep the existing retry path; accepted files are not rolled back.
- `src/components/workspace/chats/chat-box.tsx` owns the desktop right-panel layout, and **all three** right panels (artifacts, sidecar, browser) share one `ResizablePanelGroup` — do not fork a non-resizable branch per panel kind, which is how the artifacts divider silently lost its drag handle (#4465). Open/close is `collapse()` / `resize()` on the side panel's imperative handle, not conditional rendering, so the width can animate. Three constraints hold that together: the size transition is applied from the group as `[&>[data-panel]]:transition-[flex-grow]` because the sized flex item is the library's own `[data-panel]` element rather than the child `className` lands on; it is applied only while an open/close is in flight, so a drag is not interpolated frame by frame; and during the animation the panel content is held at its final width in `cqw` and clipped, because a reflowing message list re-runs its scroll-to-bottom (pinned by `tests/e2e/sidecar-chat.spec.ts`'s no-animated-scroll test) and a re-wrapping composer changes which responsive labels it shows. Because the panel is `collapsible`, the library can also collapse it to `0%` on its own when a drag crosses `minSize`, without going through the state that owns it. `onResize` records the last positive size while the pointer moves, but the owning `sidecar` / `browserView` / `artifactsOpen` state must only mirror a final `0%` layout from `onLayoutChanged`, after pointer release; closing on the first `0%` resize frame breaks a continuous drag that reaches the edge and then reverses before release.

## Fork-specific frontend notes

Live chat slots, concurrent chats, the shared right-panel resize group, Democracy
panels, the per-conversation internet switch and the image-generation entry each have
invariants that are silent when broken. They live beside the components they constrain, in
[`components/workspace/chats/AGENTS.md`](components/workspace/chats/AGENTS.md); rationale
and the tests that pin them are in [FORK.md](../../FORK.md).

More specific `AGENTS.md` files under `src/` contain the frontend sections split from this file.

## Code Style

- **The image-generation entry (fork feature)** is the sidebar's third item and reuses the Democracy handoff wholesale — `core/threads/image-generation.ts` stash + `IMAGE_LAUNCH_EVENT`, claimed in `chats/use-image-launch.ts`, delivered as `InputBox`'s **`initialValue`** — so the same two traps apply: claim on mount _and_ on the event (a same-route `router.push` remounts nothing), and never `setInput` (the uncontrolled textarea's draft hydration runs after mount and overwrites it). What differs is deliberate: it sets **no thread context**. There is no "image mode" — the page seeds an ordinary instruction, because which path can serve it (the local ComfyUI tools, the cloud `image-generation` skill, the refine loop) is a runtime fact the agent resolves, and a mode flag would have had to pick one at build time. The pixel size is written into the seed rather than left to the model: asked for "landscape" it picks its own numbers, and for a clip those are the ones that exhaust VRAM minutes in — it is two editable numbers with the aspect names as presets, snapped to the latent grid and shown snapped, because a shape name is not a size. The prompt-mode toggle travels in the seed too: `direct` demands the prompt verbatim, `assisted` asks for a positive _and_ negative prompt shown before generating, and `supportsNegativePrompt` (a checkpoint-name rule that errs toward offering the field) decides whether a negative prompt is asked for at all — a CFG-1 model ignores one silently. Seeded, never sent — a clip costs minutes per attempt.
- **Sidebar chat folders (fork feature)** — `components/workspace/recent-chat-list.tsx` + `chat-folder-row.tsx`, over the pure model in `core/threads/chat-folders.ts`. Two properties in `groupThreadsByFolder` are the feature and are silent when broken: a filed conversation appears **exactly once** (inside its folder, _not_ also at the root, and _not_ repeated in a parent when it sits in a subfolder — a "helpful" merge that keeps it in both duplicates the whole list), and a thread naming a folder that no longer exists falls back to the **root list** rather than vanishing, which is what makes folder deletion safe before any metadata cleanup lands. **Folders nest via an optional `parentId`, and the same never-hide rule applies one level up:** `normalizeChatFolders` (mirrored by `normalize_chat_folders` on the server) repairs a dangling parent, a cycle and an over-depth chain by moving the folder to the **top level**, never by dropping it — a dropped folder takes its conversations out of their folder with no way back, and a cycle is unreachable from every root, so a renderer that walks down from the roots loses the branch and every chat in it with no error. Do not take `parentId` on trust anywhere. `canMoveFolderUnder` is the other half: a folder into itself or its own descendant detaches the subtree, so the drop target refuses the drag and the menu entry is greyed rather than hidden. A nested row renders **inside** its parent's drop zone (which is what makes collapse-the-branch free), so `ChatFolderRow` must `stopPropagation` on `dragstart`/`dragover`/`drop` or the parent claims the drop and files the chat one level too high. Branches are flattened **per partition**, after grouping, so a branch whose parent is in another folder just renders top-level in its own. The folder registry (id, name, order) is per-user server state (`/api/settings/chat-folders`); membership rides on each thread's own `deerflow_folder` metadata, so a rename is one write, not one per conversation — do not move membership into the registry. Filing a chat must not reorder the sidebar: the Gateway exempts a **placement-only** metadata PATCH (`deerflow_pinned`/`deerflow_archived`/`deerflow_folder`/`deerflow_workflow`, shape-guarded per key) from bumping `updated_at`. Sidebar rows are **always** draggable and carry `CHAT_DND_THREAD_MIME` (`core/threads/dnd.ts`), so one drag serves every drop target; every folder action also has a menu path because HTML5 DnD is unreachable by keyboard. Tests: `tests/unit/core/threads/chat-folders.test.ts`, `tests/e2e/sidebar-chat-folders.spec.ts`; rationale in [FORK.md](../../FORK.md) §32.
- **The sidebar's chat lists virtualize inside a scroll container they do not own.** Past 60 rows `VirtualThreadList` mounts a window, but the scrolling ancestor is the sidebar's single `[data-sidebar="content"]` — shared with the nav list, the channels list and every open folder — so each list has to hand the virtualizer its own offset into it (`scrollMargin`). Measuring that once is the bug that hid the middle of a long history: a stale offset picks the wrong rows while positioning them correctly, so the band the reader is looking at is simply empty and nothing errors. `useThreadListScrollMargin` re-measures from three signals that fail in different directions — every render (an opening folder), a ResizeObserver/MutationObserver pair over the container's sections (a sibling settling on a cold load, which re-renders _it_, not this list), and a passive scroll listener as the backstop. Do not reduce them to one, and do not give the layout effect a dependency list. Tests: `tests/unit/components/workspace/thread-list-scroll-margin.dom.test.tsx`, `tests/e2e/sidebar-long-chat-list.spec.ts`; rationale in [FORK.md](../../FORK.md) §35.
- **PWA + Web Push (fork feature)** — `public/manifest.webmanifest` + `public/icons/` + the `metadata`/`viewport` block in `app/layout.tsx` make the app installable, which on iOS is the _precondition_ for receiving push at all. `public/sw.js` handles `push` and `notificationclick` and **caches nothing**: DeerFlow is a live, server-driven app, so a stale cached shell after a backend upgrade produces bugs that look like backend faults; adding asset caching later means adding a version/cleanup strategy with it. `core/notification/push.ts` owns support detection, subscribe/unsubscribe and the test push. Its `detectPushSupport` checks **insecure context first** — a plain-HTTP LAN origin (the fork's documented deployment) makes every other API absent too, so reporting "service workers unavailable" there sends the user hunting for a browser setting that does not exist; each case renders its own explanation and fix in the settings page instead of a switch that silently does nothing. Tests: `tests/unit/core/notification/push.test.ts`.

- **Model price (fork feature)** — prices are no longer embedded in `display_name`. `GET /api/models` returns a resolved `price` block (discount already expiry-filtered), `core/models/sorting.ts::resolveModelPrice` reads it for sorting, and `modelNameSegments` composes name + price into the same coloured segments the old embedded pair produced — green for what you pay, red for the list price beside a live promo. `ModelDisplayName` takes the `price` prop; every picker (lead, subagent, sidecar) must pass it or the price silently disappears from that dropdown. Parsing the name is retained as the fallback for a config written before the move, and a name that still embeds a price has that copy stripped so it is not rendered twice. Tests: `tests/unit/core/models/sorting.test.ts`.

`ask_clarification` ToolMessages delimit runs despite hidden human replies; skill
usage splits after the clarification group. Keep the tool call in its processing
group and render accompanying text outside the execution panel, including mixed
tool calls. `findCurrentTurnStartIndex` owns full and incremental grouping:
split incremental prefix/tail only at human boundaries, then stabilize
clarification references from full grouping.

### Knowledge source citations

`KnowledgeSourcesProvider` scopes source records to the current message list.
Only versioned native `knowledge_search`/`task` tool artifacts supply evidence;
AI/human text and metadata cannot create a source. `CitationLink` resolves
`#knowledge-…` citations through that context and renders unavailable text when
there is no matching record. `KnowledgeSourcesPanel` lists only sources cited
outside code/images. Dialog excerpts render as plain text, never HTML or nested
Markdown. Source records retain retrieval-time evidence, not live documents.
Resolve knowledge destinations before testing the label in message and artifact
link renderers: Sources lists use ordinary titles without a `citation:` prefix.

Custom Agents save edited `knowledge_scope` defaults; removing knowledge access
clears them atomically. `knowledgeScopeToSelection` keeps IDs, using IDs for
missing labels. Catalog needs saved/draft access and exact-Agent capabilities.
`catalog` + `dataset_filter` enable bases; `documents` + `document_filter` files.
Pending/failed capabilities block queries and unsupported Apply; keep old file
filters. Chats seed defaults; local overrides survive new-thread replacement and
reset per conversation. Gateway supplies defaults and enforces scope.

MCP hooks and the editor default to personal scope. Mutation-option builders require an explicit scope. MCP control accessible names include the localized ownership section, so same-named shared and personal connections remain distinct without region context. Query keys include scope and authenticated user ID; remount each editor when that ID changes. Platform provided uses the deployment editor only for administrators outside static mode, restoring add, edit, toggle and delete through the existing admin-only MCP API. Ordinary users see shared entries read-only. My plugins contains personal configuration templates, Lark account authorization and the personal MCP editor; a deployment installation must not mark a personal template configured.

Plugin mention providers extend the existing composer picker via
`core/extensions/use-mentions.ts`. Keep provider queries bounded and fenced by
viewer, thread, query, and installed snapshot.
Provider and page-surface IDs must be strings before slug validation; JavaScript
coercion is not validation. A settled snapshot with no enabled, viewer-visible
mention providers returns an empty result immediately without a search timer.
Settled results may remain visible during query/retry refreshes only within the
same viewer, thread, locale and installed snapshot; stale responses stay fenced.
Inline plugin references serialize into human-message
`additional_kwargs.extension_mentions`; these IDs and labels
are untrusted input, never a routing or permission grant. Built-in mentions must
remain usable when a provider fails or times out.

### Subscription model settings

`components/workspace/settings/subscription-settings.tsx` is mounted only for administrators under
Models. Its catalog/query keys include the account ID; mutations invalidate the
existing model picker. Poll Grok only at the provider's returned interval and
cancel pending polling on unmount. Credentials never enter browser storage or
error messages. ChatGPT starts server-owned PKCE, opens the official browser
authorization link and accepts the final loopback return URL pasted by the user.
The handoff is manual because the remote server cannot receive that callback.
Keep return URLs only in component memory; clear them on close, restart and
success. The helper download and JSON import remain an advanced fallback.
Kimi uses a subscription-key field with an explicit interactive-use limit.
