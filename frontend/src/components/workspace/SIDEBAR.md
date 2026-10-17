# Sidebar rules that break silently

Split out of [`frontend/AGENTS.md`](../../../AGENTS.md) to keep it within its
guidance budget (`scripts/check_agent_guidance.py`). Both rules are fork
features (FORK.md §26, §32); neither fails a build when broken.

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
