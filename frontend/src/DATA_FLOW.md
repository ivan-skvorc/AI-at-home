# Frontend data flow

Split out of [`AGENTS.md`](AGENTS.md) to keep the effective guidance chain
within its budget (`scripts/check_agent_guidance.py`). It is reference
material for `core/threads/` and `core/messages/`, not optional reading.

### Data Flow

1. Optional composer helpers such as `core/input-polish` can rewrite the local draft before submission, and `core/voice-input` can transcribe browser microphone input into that same local draft; confirmed user input then flows to thread hooks (`core/threads/hooks.ts`) → LangGraph SDK streaming
2. Stream events update thread state (messages, artifacts, todos, goal). The main thread stream uses the LangGraph SDK's `throttle: true` mode so updates received in the same macrotask coalesce before React is notified; do not replace it with a numeric delay without validating the SDK's trailing-debounce behavior on a continuous stream.
   File-tool artifact auto-open work must run in an effect with timer cleanup; never schedule timers while rendering streamed `write_file` or `str_replace` updates.
   `ThreadState.artifacts` remains the authoritative artifact list. The artifacts provider persists only thread-scoped panel UI state (`open`, selected path, and a refresh bootstrap cache) in session storage; an initial empty stream value must not overwrite that restored state before history finishes loading.
   Formal artifact content is refreshed once when the run finishes; transient `write-file:` previews remain message-driven.
   The detail view exposes explicit editing only for an already-opened formal UTF-8 text artifact under `/mnt/user-data/outputs`. Drafts stay in provider memory until Save so switching right-side panels cannot discard them, render in Markdown/HTML preview, and are protected from remote refreshes by the loaded SHA-256 revision. Saving is disabled during an active run; a changed revision preserves the draft and surfaces a conflict instead of overwriting agent output.
   Regular artifact text loads request at most the first 1 MiB through an HTTP
   byte range. A truncated preview must stay lightweight and expose an explicit
   full-file action; do not mount CodeMirror for that artifact until the user
   requests and receives the complete content. The Gateway retains range
   ownership and returns 206/416 through `FileResponse`.
3. `useThreadHistory` loads persisted conversation pages from `GET /api/threads/{id}/messages/page`, preserving the backend's thread-global event `seq`; rendering overlays checkpoint/live copies at their matching canonical identities (a summarized checkpoint may contain a protected early input plus a recent tail). Context-compaction rescue diffs every retained visible identity rather than slicing at the first anchor, and keeps a run-scoped ledger of committed visible messages so replacement updates and repeated rolling checkpoint windows cannot erase an already displayed step. A checkpoint/transient prefix whose canonical position is still behind an unloaded cursor page is woven in before the first shared anchor, not discarded: both the checkpoint and seq-sorted history place it earlier, so that position is known even when the pages between are not. Position authority is seq-first and lives in `core/threads/message-order.ts` (re-exported through `hooks.ts`): every normalized identity tracks latest visible content and trusted position separately; a valid `deerflow_seq` (positive safe integer, earliest value wins per identity, hidden control copies contribute a position only when no visible copy carries one) joins an ascending skeleton that outranks identity-anchor weaving, which remains the fallback for no-seq segments whose internal order is preserved. Live-only and rescued messages with trusted seq also serve as anchors for adjacent no-seq segments. A trailing segment follows its last live-only positioned anchor within the loaded window; after a shared anchor or a rescued prefix before the window, it stays at the tail. Optimistic messages remain last; the transient bridge inserts positioned rows before weaving so the insertion cannot reverse previously displayed steps. Rescued sequence anchors preserve preceding captured steps even before React has rendered them; only a leading prefix anchored to loaded history requires previously rendered ordering to cross an unloaded cursor gap. Content replacement never drops the known seq, `run_id`, or `turn_duration`, and the compaction transient bridge plus rendered ledger share the same position priority. `deerflow_seq` is server-owned display metadata and is never written back into a checkpoint. It must never be appended to the tail (#4065) — the tail is provably wrong — but suppressing it entirely is how a user's own question vanished from a long thread once the first 50-row history page no longer reached back to it (#4666). A collapsed unloaded gap is recoverable by paging; a dropped message is not. Weaving alone restores the message but not its exact position — after compaction the live window carries too few anchors — so both sides now carry the backend's thread-global `additional_kwargs.deerflow_seq`: `buildVisibleHistoryMessages` copies each row's `seq`, and the Gateway stamps it onto `values` frame messages it has already persisted. A live message whose seq is below the loaded window's lower bound is placed ahead of everything on screen instead of before the nearest anchor, which is what puts a compaction-rescued first user turn back at the head rather than mid-transcript. That split happens _before_ the anchor walk, not inside it: a compacted checkpoint can share no identity at all with the loaded page — it keeps only the current run's recent tail, while the page on screen was fetched turns earlier — and the anchor walk then never runs at all, which is precisely when a rescued turn most needs its seq. Doing the split inside the walk left that case appending the message after the whole window (#4666), the one arrangement #4065 proved wrong. A message without a seq (still streaming, so not in the feed yet) keeps the weaving path — the tail is already its correct position. Optimistic messages are then added without timestamp re-sorting. History invalidation preserves already-loaded pages so their established ordering positions are not discarded. Dynamic context re-keys each submitted user message from the client-generated `local-human-*` identity `X` to the visible server echo `X__user`; UI identity matching normalizes that reserved suffix only for human messages so the optimistic input and checkpoint replacement remain one visible turn. At dispatch, a local-turn anchor snapshots the checkpoint identity baseline, canonical history identities and maximum trusted seq, and any pre-existing transient-bridge identities. Render repair uses `confirmedHistoryIdentities` plus `preSubmitMaxSeq` to restore baseline or history-confirmed messages above that exact human anchor, while moving only speculative non-baseline AI/tool steps behind it; `currentTurnRunIds` keeps already-persisted steps of the active turn below their human. Keep the anchor scoped to its originating thread through finish, stop, and stream error because the SDK's settled frame can retain transient event order; replace it on the next local submit and clear it on thread switch or replay-gap recovery.
4. Stop actions call the LangGraph SDK stream stop path; `core/threads/hooks.ts` invalidates current-thread, thread-history, token-usage, and sidebar/search caches immediately and schedules one follow-up refetch because SDK stop may finish via abort + fire-and-forget cancel before backend title finalization commits
5. TanStack Query manages server state. `UserPreferencesBoundary` preserves
   workspace SSR and initializes the account cache before browser paint; only
   subsequent account switches gate consumers until the new cache is active. Four allowlisted
   settings sync through `/api/v1/auth/preferences`; confirmed caches are
   account-scoped in localStorage and pending patches are account-scoped in
   tab-local sessionStorage. A stopped account cannot apply late responses, and
   each request carries its expected user ID to fence shared-cookie switches.
   Storage events refresh from the server without echo-writing unchanged data;
   failed reads and writes retry with capped backoff and focus/online wakeups.
   Legacy unscoped settings are never automatically uploaded. Display settings
   and thread overrides remain local. Shared local-only fields still merge
   across tabs on storage changes/removal/clear, preserving account preferences.
   **Fork: nothing a conversation selects is ever uploaded as an account
   preference.** Upstream scopes only `model_name` per thread and syncs
   mode/effort account-wide; this fork scopes every `THREAD_SCOPED_CONTEXT_KEYS`
   entry (model, subagent model, mode, effort, internet switch, the Democracy
   roster) per conversation, so `updateThreadSettings` writes that thread's own
   override for `context` and never calls the preference hook — uploading one
   would make one chat's choice the default for every other chat, on every
   device, with nothing failing. Settings-page edits (`updateLocalSettings`) are
   the account-wide path. InputBox marks automatic model/mode resolution
   separately from user choices on both normal and Custom Agent chat pages;
   `resolveThreadContext` must neither enqueue account writes nor create a
   fallback thread override that masks a later server preference — or the
   workflow the conversation recorded on another device (FORK.md §36), which
   `applyWorkflow` adopts only while the chat has no override. That holds in
   passwordless mode too, where no account sync is active: it refreshes only
   keys the conversation already overrides and merges the rest into the
   in-memory base, never the chat's own overrides (an offline switch there
   would otherwise reach every chat). The fork's
   `democracy` mode must stay in both preference schemas (`preferences-sync.ts`
   and the Gateway's `Preferences` model): a narrowed union drops it silently on
   the way out and 422s on the way in. Pinned by
   `tests/unit/core/settings/thread-context-account-boundary.dom.test.ts`. The
   Settings > Tools MCP switch calls the targeted `PATCH /api/mcp/config`
   Explicit InputBox selections pass only fields changed by the action, so a
   mode/effort edit cannot upload an unrelated thread model override.
   InputBox marks automatic model/mode
   resolution separately from user choices on both normal and Custom Agent chat
   pages; `resolveThreadContext` must neither
   enqueue account writes nor create a fallback thread override that masks a
   later server preference. The
   Capability Center > Plugins MCP switch calls the targeted `PATCH /api/mcp/config`
   mutation, disables switches until that mutation's success refetch completes,
   displays the backend error `detail` through a toast, and invalidates
   `["mcpConfig"]` only after success.
   Server management uses targeted `POST /api/mcp/config/servers`,
   `PUT /api/mcp/config/server`, and bodyless
   `DELETE /api/mcp/config/servers/{server_name}` mutations. Delete names are
   percent-encoded, including legacy empty and slash-containing names; every
   successful mutation invalidates `["mcpConfig"]` only after the response.
   Current-chat MCP background tasks use `core/background-tasks`: the header
   trigger is hidden for new/mock/static-demo threads and unless `/api/features`
   reports the startup-scoped `mcp_tasks` capability; the list query is disabled
   while that capability is unavailable, so default-disabled and memory-backend
   deployments never poll an endpoint that cannot serve tasks. It lists at most
   20 local task records, refreshes every 3 seconds while any task is active
   (15 seconds otherwise), fetches bounded task details only while a user expands
   a card, and cancels through the thread-scoped local-ID endpoint. The expanded view
   shows result/preview, artifact metadata, input requests, and the latest poll,
   notification-delivery, or cancellation error without exposing the persisted remote handle. A
   persisted cancel request remains "Cancelling…" only while the task status is
   still active; if remote cancellation keeps failing, the active card remains
   expandable and shows the attempt count plus the latest bounded error while
   the backend continues retrying. Notification delivery failures expose their
   bounded error and attempt count; retryable failures use backend backoff,
   while a permanent rejection or exhausted five-attempt budget is shown as
   stopped rather than implying that retries will continue.
   Explicit durable native-subagent batches use `core/subagent-batches` and
   `ThreadSubagentBatches`. `/api/features` reports SQL-repository availability
   separately from the startup worker. A running worker exposes the trigger on
   both default and Custom Agent chat pages; a stopped worker keeps threads with
   durable history visible in read-only mode for inspection and JSONL export,
   while deployments with neither a worker nor history keep the trigger hidden.
   The panel renders bounded progress and incrementally paged item previews, controls pause/resume/cancel,
   retries failed items, and exports JSONL. Worker-dependent mutations stay
   disabled in read-only history mode, and persisted progress is normalized to
   a bounded percentage before reaching the UI primitive. Item pagination uses a
   fixed page size and an explicit load-more control; full results remain available
   only through JSONL export. The panel must not infer batch mode from prompt text
   or inject the complete result set into chat state.
   Capability Center > Plugins > Lark uses a local generation only to suppress stale React
   callbacks; server-issued Lark flow generations must be passed through every
   config/auth completion and across switch-or-register to authorization chains
   so backend cross-tab ordering remains authoritative.
   Settings > Subagents reads one catalog for built-in, config, and managed
   definitions. Only administrators see managed-definition mutation controls;
   Custom Agent settings consume the same query and preserve stale selected names
   as removable "missing" entries instead of silently widening the allowlist.
6. Components subscribe to thread state and render updates

AI message grouping uses `extractContentFromMessage()` to identify visible answer content. A non-empty content array may contain only Anthropic thinking blocks; keep it in `assistant:processing` until answer content arrives. Cover both streamed snapshots in `tests/unit/core/messages/utils.test.ts`.

Inline `<think>` extraction scans code and reasoning openers in source order. Code tags stay in answer/copy data, including unfinished streaming spans. Blank lines, headings, thematic breaks, interrupting lists and fences end inline spans; ATX spans also end at the heading's newline. Fenced/indented code stays protected; indentation cannot interrupt a paragraph. Fences opened after list markers scan to a matching closer or the end of the list item, with tab-aware container indentation; their closers must not open a new top-level fence. Outside inline code, a backslash escapes one backtick, not the whole run. Real reasoning closes independently of Markdown inside it. Preserve the content-keyed cache and no-tag fast path.

Project moves in `core/threads/hooks.ts` cancel all per-thread metadata query
variants after the write succeeds, merge only `deerflow_project_id`, then
invalidate/refetch that metadata prefix. This fences delayed pre-move reads and
restarts initial reads that have no cached snapshot. Search and project-thread
lists are invalidated on settlement. Keep the delayed-read regression in
`tests/unit/core/threads/move-thread.dom.test.tsx` for moves and removal.

The chat header's context-window control is intentionally persistent: while `context_usage` is unavailable, `ContextUsageBadge` renders a gauge placeholder rather than unmounting; once data arrives, the same position shows the percentage. `useThreadTokenUsage` retains placeholder data only when the response `thread_id` still matches the active route, so same-thread refetches do not flicker and cross-thread navigation never displays the previous chat's usage.

Settings skill uploads reject archives larger than 100 MiB before starting the
request and disable the hidden file input while an install is pending. The API
client preserves structured SkillScan findings on `SkillRequestError`, and the
settings page renders a compact file/rule/line summary so security rejections
remain actionable; a proxy-generated 413 is mapped to the localized size error.

Run duration is run-scoped UI metadata even though the compatibility field `additional_kwargs.turn_duration` is repeated on historical AI messages. `core/messages/run-duration.ts` folds those copies into one display anchored after the run's last visible message group. `MessageList` owns the temporary client-side duration for a just-completed live turn until authoritative history arrives. The duration is total run wall-clock time, not per-message reasoning time; reasoning disclosure and run activity/duration are rendered separately.

The workspace-change card follows the same rule: it is resolved from `(threadId, runId)` alone, so every AI message of a run would render an identical copy. A run ends in more than one terminal assistant bubble whenever the model emits answer text that never gains a tool call, so `core/messages/workspace-change-anchor.ts` picks the run's last assistant bubble and `MessageListItem` renders the badge only for that anchor (#4555). Any future run-scoped display belongs in the same place — do not hang one off every message. The two anchor helpers deliberately differ in which group types they accept as a run's last position, because an anchor is only useful where the display is actually rendered: run duration is emitted by `MessageList` around every group, so it accepts any type, while the workspace-change card comes from `MessageListItem` and so restricts to `assistant`. Keep a new helper's candidate set matched to its own render site rather than unifying them.

Composer drafts are tab-scoped browser state. `core/threads/composer-draft.ts` stores only text plus the selected slash-skill name in `sessionStorage`, keyed by user, agent, and logical conversation scope. New-chat pages pass the stable scope `"new"` because their runtime `threadId` is a fresh UUID on every reload; established conversations use their real thread ID. `InputBox` waits for enabled skills before restoring a skill chip, degrades a missing/disabled skill back to editable slash text, and clears the stored draft through `SendMessageOptions.onSent` only after the send passes the in-flight guard. Attachments, sidecar quotes, voice state, and polish undo state are not persisted.

Conversation references (`read_conversation`, opt-in on the backend) are attached from the composer. `ReferenceConversationsButton` (`components/workspace/conversation-references/`) renders only while `/api/features` reports `conversation_references.enabled`, opens a picker over the same `useThreads()` list the sidebar uses (the current thread excluded, capped at `max_references`), and shows removable chips in the composer header. On submit the thread IDs ride `InputBoxSubmitOptions.conversationReferences` → `SendMessageOptions.conversationReferences` → run `context.conversation_references`, which the Gateway consumes at admission; the LangGraph SDK drops unknown top-level body fields, so the top-level request field is not reachable from the web UI. `core/conversation-references` also writes display-only `additional_kwargs.conversation_references` (`{thread_id, title, agent_name?}`) on the visible human message so `message-list-item.tsx` can render read-only chips linking to the source — through `pathOfThread`, so custom-agent sources route to `/workspace/agents/{agent}/chats/{id}`; that metadata grants nothing. References are per message: they are not persisted with the draft, clear on send or thread switch, and regenerate/edit of a turn runs without them unless attached again.

Auth UI note: the login page's "keep me signed in" option submits only `remember_me` to the Gateway and may persist only the email address through `core/auth/remember-login.ts`. Passwords and tokens must never be stored in frontend storage; the `HttpOnly access_token` and readable `csrf_token` cookies remain Gateway-owned.

`/goal` and `/compact` are built-in composer commands, not skill activations. `src/components/workspace/input-box.tsx` intercepts `/goal`, `/goal clear`, and `/goal <condition>` before normal chat submission, calling Gateway `GET/PUT/DELETE /api/threads/{thread_id}/goal`. Setting `/goal <condition>` also submits the condition text as the next user task so the agent starts running immediately; status and clear do not start a run. On a project-scoped new chat (`/workspace/chats/new?project=…`), the chat page's project pre-create runs before the goal PUT via the composer's `onPrepareThread` callback: the goal endpoint materializes a missing thread row itself, and an unassigned row would make the later idempotent thread create return it without assigning the project. Goal and compact requests are tied to the current `threadId` with an `AbortController`, so switching threads or unmounting the composer aborts in-flight requests and stale responses cannot update the new thread's composer state. The chat pages render `GoalStatus` above the composer from `AgentThreadState.goal`, with local optimistic state until an incremental goal update or final state reload arrives. `/compact` calls `POST /api/threads/{thread_id}/compact` to summarize older active context while leaving the full visible chat history intact; it is skipped on new/empty threads and blocked server-side while a run is in flight. Thread rename uses the same serialized state-write route; the rename dialog stays open and surfaces the server error when an active run returns 409.

Composer `runs:create` gating belongs in `InputBox.handleSubmit` after command classification and before dispatch. Reject message and goal-set actions before `onPrepareThread`, goal persistence, success feedback, or draft clearing. Goal status/clear and compact do not start runs; preserve their endpoint-specific gates. Regression coverage lives in `input-box-send-gating.dom.test.tsx`.

The `/` skill list stays reachable after a skill is selected: typing `/` in the editable text beside the chip reopens it, and picking an entry swaps the chip rather than adding a second one, because the wire format carries exactly one leading `/skill`. That list offers skills only while a chip is selected — a builtin command owns the whole composer line, so `/goal` behind a selected skill would submit as chat text instead of running the command. The trigger itself is unchanged: a slash only opens the list at the start of the input (`getLeadingSlashSkillQuery`), pinned by `tests/e2e/chat.spec.ts`.

Human input requests are a structured message protocol layered on normal chat history. The backend writes request payloads to `ToolMessage.artifact.human_input`, `src/core/messages/human-input.ts` owns the runtime validators/types, and `src/components/workspace/messages/human-input-card.tsx` renders the reusable card. The protocol is versioned on the request side only: v1 covers `free_text` / `choice_with_other`, and v2 adds `form` (typed fields — text/textarea/number/select/multi_select/checkbox/date — with required-field validation in the card). Replies deliberately stay on the v1 response protocol: the form card submits a `response_kind: "text"` reply whose value is the human-readable summary plus one JSON block keyed by stable field names (`buildHumanInputFormSubmissionValue` — the readable part alone is ambiguous because labels/values may contain the separators), so the model can reconstruct the submitted mapping without a structured response kind. The validators reject unknown versions/modes (and field names colliding with JS `Object.prototype` members) so future protocol bumps degrade to the plain-text ToolMessage fallback rather than rendering a broken card. Form values are read through own-property access only (`readHumanInputFormValue`); select fields stay controlled from their empty-string placeholder state through selection; checkbox fields are native `<input type="checkbox">` controls seeded to an explicit `false` (`buildInitialHumanInputFormValues`) so an untouched checkbox submits as "no" while a `required` checkbox keeps must-agree semantics (no HTML `required` attribute — native constraint validation would intercept the custom submit path), and form controls carry label/`htmlFor`, `aria-required` plus a visually-hidden localized "required" marker, and `aria-invalid`/error associations whose error node stays mounted while any field is still invalid. Composer-bypass closure: `deriveHumanInputThreadState` treats a visible plain human message as answering the latest unanswered request opened before it (only the latest — nothing guarantees a single outstanding request across runs, and closing all would silently swallow older decisions; an older request left open simply becomes the active card again). This lets current users bypass a structured form through the normal composer and preserves compatibility with old v1-only frontends that degrade a v2 request to plain text. `MessageList` owns answered/latest/pending state for visible cards, but derives answered responses from raw `thread.messages` because replies are hidden; pending cards clear when the hidden reply appears, when dispatch is dropped, or when a new `thread.error` reports an async stream failure. Page-level card submit callbacks must send a normal human message and put `hide_from_ui: true` plus the response payload in the fourth `sendMessage(..., options)` argument as `options.additionalKwargs`; the third argument remains run context such as `{ agent_name }`. Composer entry points remain enabled while a human-input request is open; a normal visible message intentionally bypasses the card and starts the next run without structured response metadata.

Tool-calling AI messages can contain user-visible text as well as `tool_calls`. `core/messages/utils.ts` keeps these turns in an `assistant:processing` group, and `components/workspace/messages/message-group.tsx` must render the visible text as a processing step instead of treating the message as only tool metadata. This preserves provider text such as error explanations or "trying another approach" notes during tool-heavy runs.
While the current turn is still loading, a content-only AI message after the latest visible human input also stays in that processing group until the turn settles: a provider may append tool-call chunks to the same message later, and classifying it as a final assistant bubble too early makes the text jump into the steps panel. `MessageGroup` therefore renders processing text even before the first tool call arrives.
The same rule applies after an earlier tool call: a later content-only AI message remains visible after the current last tool-call step while streaming, because that message may itself gain another tool call before the turn settles.
Because the same message is rendered by two different components over its lifetime, reasoning must sit above the answer text in both. `MessageListItem` paints the settled bubble's `<Reasoning>` disclosure above its content, so `MessageGroup` puts the trailing reasoning disclosure above the assistant text that follows it and `convertToSteps` emits a message's reasoning step before its content step — otherwise the two swap places the instant the turn settles (#4576). Assistant text emitted _before_ that reasoning keeps its earlier position; only the answer the reasoning produced moves below it.

Editing a user message forks the conversation instead of rewriting it. `core/messages/utils.ts::getHumanTurnEditPoints()` gives every visible user message its turn ordinal plus the terminal assistant message of the _previous_ turn — the point an edited version branches from (the first turn branches from the start of the conversation, so it is always editable). `components/workspace/chats/use-edit-versions.ts` then drives `core/threads/hooks.ts::useCreateEditVersion()`, which branches through `POST /api/threads/{id}/branches` (or `POST /api/threads` for the first turn), stamps the new thread as a hidden version, registers it in the root's `deerflow_edit_version_groups`, and parks the edited text in session storage for `usePendingEditSend()` to replay once the version thread mounts. The model and its invariants live in `core/threads/edit-versions.ts`; the `‹ n/m ›` control is `components/workspace/messages/message-version-switcher.tsx`. The older latest-turn-only in-place path (`editAndRegenerateMessage()` → `POST /api/threads/{id}/runs/edit-regenerate/prepare`) is still exported by `useThreadStream` and still backed by the Gateway, but no surface wires it any more.

`MessageGroup` builds its tool-result and browser-preview lookups once per processing group before converting messages to steps. The lookup preserves the first non-empty result and first screenshot-bearing browser view for each tool-call ID, matching the streamed-message display semantics without repeatedly scanning the full group for every tool call.

Generic tool details receive the explicit Debug flag from `MessageGroup`, independent of token statistics. `tool-call-details.tsx` mounts payload previews only while expanded; `core/messages/tool-detail-preview.ts` caps text output at 12,000 characters, visits at most 12,000 values, and limits nesting to six levels. Serialization budgets include escaped strings, punctuation, indentation, closing delimiters, and truncation markers so structured previews remain valid JSON without a final mid-token slice. Generic calls keep the original ToolMessage content/status. Text is displayed verbatim (or as a bounded prefix), never passed through JSON.parse: reparsing can round numeric IDs, discard duplicate keys, and alter quoted strings. Objects/arrays are formatted only on expansion; specialized renderers retain their existing result conversion. An empty received payload is distinct from a missing message, and neither implies a running/completed state. Copy actions use the shared clipboard fallback, copy the displayed preview, and reset feedback after two seconds. Truncated containers include an inline ellipsis unless an object has already emitted a real ellipsis key; in that case, only the external truncation notice is guaranteed. Arrays stop after a child collapses because the text budget is exhausted, avoiding repeated trailing markers while preserving literal ellipsis elements. Cycle, accessor, and depth-limit markers do not suppress later siblings. Truncated string prefixes preserve complete UTF-16 surrogate pairs. Object traversal stops before a key exceeds the remaining text budget; never shorten property names, since shortened keys can collide with real data. Renderer routing and result conversion share `getToolCallKind`. Disclosure accessible names include the tool name and call ID.

Array previews coalesce consecutive generated markers only at the end into one omitted-suffix notice. The serializer tracks marker provenance and complete entry boundaries; it must not deduplicate literal ellipsis values or shift the indices of later real elements. A cycle/accessor/depth-limit tail can therefore share one notice while the same markers in the middle retain their positions.
