# Workspace UI

## Token usage dashboard

Open **Token usage** in the workspace sidebar (`/workspace/usage`) to review
your recorded tokens over the last 7 or 30 days, daily input/output totals,
cache-hit input tokens by model, and paginated run history with failure filters.
Run history covers all dates independently of the selected chart period.
Conversation links use each run's recorded assistant to open the default or
matching custom-agent chat.
Periods with no recorded runs show an empty message without a date axis or
zero-filled daily details; runs with zero reported tokens still show details.

Reporting requires `runs:read` permission and a SQLite or PostgreSQL database;
it is unavailable in the static demo. Counts reflect persisted provider usage,
may be incomplete during active runs or when providers omit usage, and are not
a provider bill. Cache hits are included in input tokens. Daily buckets use the
browser's current UTC offset and attribute a run to its creation date.
The page reuses the existing `/api/console` APIs; their optional cost and currency
fields and server-side pricing configuration remain supported.
See [dashboard behavior and design](../../frontend/docs/token-usage-dashboard.md).

## Workspace

The workspace keeps a collapsed icon sidebar visible on narrow screens. Its
toggle opens the full navigation drawer; closing the drawer returns to the icon
bar without changing your saved desktop sidebar preference. Navigating to another
page also closes the mobile drawer and preserves the destination page's focus.
Dismissing the drawer returns keyboard focus to the control that opened it.
The Agents gallery header wraps to the available width so its import and create
actions remain visible beside the compact sidebar on narrow screens.

## Search conversations and messages

Use **Search** in the sidebar or **⌘K / Ctrl+K** to find conversation titles and
visible user/assistant message text, including code. Filter by conversations or
messages and include archived chats. Results show matching excerpts; selecting a
message opens its historical context, with earlier/later navigation and a **Return
to latest messages** button. Type `>` for new chat, settings and keyboard commands.
Title search is built in. Enable message search with the packaged
[workspace search extension](../../examples/deerflow-extension-workspace-search/README.md).
Its first search backfills existing history and shows progress while indexing.

## Chat Archive

Deleting a chat from the sidebar requires confirmation showing its title. Deletion removes the conversation and its own folder (`/mnt/user-data`, with every file in it) and cannot be undone. Folders it used in a writable custom mount are kept; see [Shared folders](sandbox.md#shared-folders-in-writable-mounts).

Use **Archive chat** in a recent chat's sidebar menu to hide completed work while keeping its messages, files, and original link. The success message offers **Undo**. Open **Chats → Archived** to find archived conversations and restore them individually; an open archived conversation also shows a restore button in its header. Search filters the titles of loaded conversations, with **Load more** for older entries.

Archive and restore preserve the chat's activity time and pinned state. Archiving does not stop a running task or pause its schedules, and new activity does not automatically restore it. Use the existing Delete action when you intend to remove a conversation and its files.

## Chat folders

The sidebar's chat list is a tree. **New folder** in the *Recent chats* header
creates one; drag conversations onto it, or use **Move to folder** in a chat's
**⋯** menu. A folder's own **⋯** menu holds **New subfolder**, **Move folder
to**, **Rename** and **Delete**, and folders can be dragged onto each other.
Folders nest up to five levels. The count beside a folder's name covers
everything below it, so a collapsed folder never reads as empty, and collapsing
a folder collapses its whole branch.

A filed conversation is listed inside its folder and nowhere else. Deleting a
folder deletes its subfolders but never the conversations, which return to the
main list at once. A conversation whose folder no longer exists (deleted from
another browser, say) is shown in the main list, and a folder whose parent is
gone reappears at the top level, so no branch can hide the chats inside it.

Folder names, their order and which chat is in which folder are stored per user
on the server and follow you to other browsers and devices; only which folders
are expanded is per browser. There are at most 50 folders. Filing a chat does not
count as activity, so it keeps its place in the recency order. Nothing to
configure.

## Selecting several chats

**Select** beside **New folder** in the *Recent chats* header, or **Select** in a
chat's sidebar menu, puts a checkbox on every chat row. Click a row or its
checkbox to tick it, Shift-click (or Shift+Space on a checkbox) to tick the run
between it and the last row you toggled, in the order the sidebar shows them,
including rows in other open folders and project groups. **Select all** ticks
every chat the sidebar is showing; chats in a collapsed folder or not yet loaded
are not included. Escape, **Cancel** or **Done** leaves selection mode; Escape
typed into a text field, or one that closes a menu or dialog, does not.

The toolbar moves the ticked chats into a folder, out of their folders (**No
folder**) or into a **New folder from selection…**; archives them with one
**Undo** for the batch; deletes them after a confirmation that names the count
and up to five titles; or opens [chat clean-up](#chat-clean-up). Delete is shown
only with the `threads:delete` permission. Moving never changes the sidebar's
recency order. Each chat is a separate request: moves and archives at most four
at a time, deletes one at a time. A chat that fails stays ticked with its reason
(a chat whose run is still going cannot be deleted until it ends), the rest
proceed, and nothing is retried automatically. Deleting the open chat takes you to a new chat.

## Chat clean-up

**Clean up…** in the selection toolbar, or **Clean up all…** with nothing ticked
(the 200 most recent unarchived chats), has a model propose a title and a folder
for each conversation. Choose the model (**Server default** is the server's title
model), whether to rename, and how to file: **Don't file**, **Into my folders**
(folders you tick or name; a typed name is created only if the model used it),
or **Auto-generate folders** (1–20 new folders, default 8, reusing an existing
folder whose name matches). The setup is remembered per browser.

**Analyze** reads without writing: one model call per conversation, one at a time
on a local model and three at a time on a hosted one, plus at most one grouping
call in auto mode. The review screen lets you edit titles and folders, untick
rows, and rename or merge proposed folders. **Apply** then creates new folders in one write
(never past the 50-folder limit), moves chats and renames them without changing
their place in the recency order. Failed rows stay ticked under **Review again**;
nothing is retried automatically, and applying the same plan again writes
nothing.

The model sees the first two and the last visible exchange plus a compacted
conversation's summary, cut to a few hundred characters per message; with
`pii_redaction.enabled` personal data is redacted first. Each call is billed to
its conversation under **Chat clean-up**, and the grouping call is split across
the conversations it grouped. A spend-cap refusal, an unknown model or a model
you may not use stops the whole pass; per-conversation failures (empty, timed
out, unusable reply) are listed. With `title.enabled: false` in `config.yaml`
renaming is unavailable and filing still works. The routes are documented in
[API.md](../../backend/docs/API.md#chat-clean-up).

## Conversation files

The labelled **Files** button in a chat's header, right after the token counter,
opens the side panel on the conversation's file tree (`/mnt/user-data`). Below a
header width of about 32rem it shows only its icon. **Show files** in a chat's
sidebar menu opens the chat on that tab through `?panel=files`; the parameter is
removed once the panel opens. The tab notes that this folder is deleted together
with the conversation, and lists the [shared folders](sandbox.md#shared-folders-in-writable-mounts)
the conversation created or edited.

The tree covers the agent's scratch work in `workspace/` (a cloned repository, a
virtual environment, intermediate data), your attachments in `uploads/` and the
deliverables in `outputs/`, opened one directory at a time with each file's size
and last change. Any file previews in the artifacts viewer or downloads,
including files the agent never presented, and open folders refresh every few
seconds while a run is working.

- **Read-only, and confined to the conversation.** The listing comes from
  `GET /api/threads/{thread_id}/files?path=…`, which applies the artifacts
  endpoint's owner check and path confinement: nothing outside the
  conversation's own folder is listed, and a symbolic link is shown as a link,
  never followed. Editing stays where it was, for text files in `outputs/`.
- **Large folders say they were cut.** A listing returns at most 500 entries (a
  `node_modules` folder ends with "N more not shown"), and in-flight upload and
  edit temporary files are hidden.
- **The folder has to be on the host.** With the local sandbox and in
  per-conversation container mode it is. A shared external sandbox container
  (`make sandbox-up`) keeps the workspace inside the container, where the
  explorer, like the artifacts panel, cannot see it.

## Conversation titles

A new conversation is renamed once, at the end of its first turn. The Gateway
refuses a rename while a run is in flight (which is why **Rename** does nothing
mid-answer), so the title is written once the answer exists and describes it
too; a first turn that ends by asking you a clarifying question is renamed as
well. **Settings → Conversation titles** turns this off and picks the **Title
model**: **No model call** (your first message, shortened; the shipped default),
a configured model (it reads at most 500 characters of the first question and of
the answer), or **Server default** (`title.model_name` in `config.yaml`).
`title.max_words` and `title.max_chars` bound the title, the shortened first
message included. `title.enabled: false` turns renaming off for everyone and
greys out the switch with an explanation.

**Settings → Conversation titles** is stored per account
(`GET`/`PUT /api/settings/auto-title`) and applied by the Gateway to every run
you own: other devices and browsers, IM channels, scheduled tasks, workflow and
extension child runs. A switch turned off anywhere wins over a browser that still
sends "on". The browser keeps a copy for the switch and reloads it from the
account once per workspace session; a failed save puts the switch back with an
error. The terminal UI and the embedded client do not use the Gateway and follow
`config.yaml` only. The first time an updated browser connects to an account
that has never saved the setting, it copies its own earlier choice there.

**Auto rename** in the chat header renames one conversation on demand from what
is in it now, on a model you pick per press; **Server default** uses the model
`config.yaml` names, and the choice is remembered in your account and shared with
the settings page. It reads the first two exchanges as you saw them: tool
results, hidden scaffolding and an Ultra or Democracy panel's deliberation are
left out, and a turn's answer is the final reply. It spends one call, counted in
the conversation's cost under **Chat rename**, and is refused while a run is in
flight or for a model removed from `config.yaml`. With the switch off it still
renames one conversation on request and says so; with `title.enabled: false` it
is not shown.
