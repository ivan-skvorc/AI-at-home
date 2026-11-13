# Sidebar rules that break silently

Split out of [`frontend/AGENTS.md`](../../../AGENTS.md) to keep it within its
guidance budget (`scripts/check_agent_guidance.py`). Every rule here is a fork
feature (FORK.md §26, §32, §35), and none fails a build when broken.

**No image-generation entry in the sidebar.** `workspace-header.tsx` carries
exactly two entries under _New chat_: Democracy, and nothing else. Image
generation still works — the media tools are bound, `/workspace/image/new`
still renders, and asking for a picture in chat is unchanged — but the feature
is deliberately **unadvertised** (FORK.md §26), because the entry appeared on
every install including the many with no GPU behind it. Re-adding a
`SidebarMenuButton` pointing at `/workspace/image` compiles, type-checks and
renders perfectly, so the only thing standing between that and a silent revert
is `tests/unit/components/workspace/workspace-header.dom.test.tsx`, which
asserts on the link's **route** rather than its label. If you need the entry
back, change the test in the same commit so the decision is visible.

**One sidebar chat row, everywhere.** `ThreadSidebarItem` in
`components/workspace/recent-chat-list.tsx` renders every chat row the sidebar shows —
the fork's folder-aware root list _and_ upstream's per-project groups in
`projects-section.tsx`, which imports it. Do **not** grow a second copy for one of those
lists: the row's action menu (pin, move to folder, move to project, rename, share,
export, archive, delete) is the whole feature, and a copy that is missing an entry still
renders perfectly — the action is simply unreachable from that one list, with nothing
failing. The folder half (FORK.md §32) rides in as an optional `folderMenu` node the
caller builds, so a project group passes nothing and the submenu does not render, rather
than the row having to know which list it is in. The link is **always** `draggable`
(§32's one-drag-one-payload rule), because the same payload serves every drop target.

The two notes below moved here from `frontend/src/AGENTS.md`, whose pointer is
their entry point.

**Sidebar chat folders (FORK.md §32)** — `components/workspace/recent-chat-list.tsx`
and `chat-folder-row.tsx`, over the pure model in `core/threads/chat-folders.ts`.
Two properties in `groupThreadsByFolder` are the feature and are silent when
broken: a filed conversation appears **exactly once** (inside its folder, _not_
also at the root, and _not_ repeated in a parent when it sits in a subfolder — a
"helpful" merge that keeps it in both duplicates the whole list), and a thread
naming a folder that no longer exists falls back to the **root list** rather
than vanishing, which is what makes folder deletion safe before any metadata
cleanup lands. **Folders nest via an optional `parentId`, and the same
never-hide rule applies one level up:** `normalizeChatFolders` (mirrored by
`normalize_chat_folders` on the server) repairs a dangling parent, a cycle and
an over-depth chain by moving the folder to the **top level**, never by
dropping it — a dropped folder takes its conversations out of their folder with
no way back, and a cycle is unreachable from every root, so a renderer that
walks down from the roots loses the branch and every chat in it with no error.
Do not take `parentId` on trust anywhere. `canMoveFolderUnder` is the other
half: a folder into itself or its own descendant detaches the subtree, so the
drop target refuses the drag and the menu entry is greyed rather than hidden. A
nested row renders **inside** its parent's drop zone (which is what makes
collapse-the-branch free), so `ChatFolderRow` must `stopPropagation` on
`dragstart`/`dragover`/`drop` or the parent claims the drop and files the chat
one level too high. Branches are flattened **per partition**, after grouping,
so a branch whose parent is in another folder just renders top-level in its
own. The folder registry (id, name, order) is per-user server state
(`/api/settings/chat-folders`); membership rides on each thread's own
`deerflow_folder` metadata, so a rename is one write, not one per conversation —
do not move membership into the registry. Filing a chat must not reorder the
sidebar: the Gateway exempts a **placement-only** metadata PATCH
(`deerflow_pinned`/`deerflow_archived`/`deerflow_folder`/`deerflow_workflow`,
shape-guarded per key) from bumping `updated_at`. Sidebar rows are **always**
draggable and carry `CHAT_DND_THREAD_MIME` (`core/threads/dnd.ts`), so one drag
serves every drop target; every folder action also has a menu path because
HTML5 DnD is unreachable by keyboard. Tests:
`tests/unit/core/threads/chat-folders.test.ts`,
`tests/e2e/sidebar-chat-folders.spec.ts`.

**The sidebar's chat lists virtualize inside a scroll container they do not own
(FORK.md §35).** Past 60 rows `VirtualThreadList` mounts a window, but the
scrolling ancestor is the sidebar's single `[data-sidebar="content"]` — shared
with the nav list, the channels list and every open folder — so each list has
to hand the virtualizer its own offset into it (`scrollMargin`). Measuring that
once is the bug that hid the middle of a long history: a stale offset picks the
wrong rows while positioning them correctly, so the band the reader is looking
at is simply empty and nothing errors. `useThreadListScrollMargin` re-measures
from three signals that fail in different directions — every render (an opening
folder), a ResizeObserver/MutationObserver pair over the container's sections (a
sibling settling on a cold load, which re-renders _it_, not this list), and a
passive scroll listener as the backstop. Do not reduce them to one, and do not
give the layout effect a dependency list. Tests:
`tests/unit/components/workspace/thread-list-scroll-margin.dom.test.tsx`,
`tests/e2e/sidebar-long-chat-list.spec.ts`.
