/**
 * Pure model for the sidebar's chat folders (fork feature: a folder tree in the
 * side list). A folder is a name, a stable id and an optional parent;
 * **membership is not stored here** — each conversation records its folder in
 * its own thread metadata (`deerflow_folder`), so renaming a folder is one
 * small write instead of one write per conversation inside it.
 *
 * Nothing React, nothing route-aware, so the grouping rules are exhaustively
 * unit-testable. Server reconciliation lives in `chat-folders-api.ts`, the React
 * state in `use-chat-folders.ts`.
 */

import type { AgentThread } from "./types";

export type ChatFolder = {
  id: string;
  name: string;
  /** The folder this one sits in; absent/null for a top-level folder. */
  parentId?: string | null;
};

/** A folder, the conversations filed directly into it, and its subfolders. */
export type ChatFolderNode = {
  folder: ChatFolder;
  /** Conversations filed into *this* folder, not into a subfolder of it. */
  threads: AgentThread[];
  children: ChatFolderNode[];
  /** Conversations in this folder **and** every folder below it. */
  totalThreadCount: number;
};

/**
 * The whole side list, partitioned. `ungrouped` is the root level: it holds
 * every conversation that is not in a folder — and, deliberately, every
 * conversation pointing at a folder that no longer exists.
 */
export type GroupedThreadList = {
  tree: ChatFolderNode[];
  ungrouped: AgentThread[];
};

// Mirrors ``MAX_CHAT_FOLDERS`` / ``MAX_FOLDER_NAME_CHARS`` / ``MAX_FOLDER_DEPTH``
// in ``backend/packages/harness/deerflow/config/user_ui_state.py``. Enforced on
// both sides: the API is untrusted input, and a sidebar is still a sidebar.
export const MAX_CHAT_FOLDERS = 50;
export const MAX_FOLDER_NAME_CHARS = 80;
// Nesting depth, counting the top level as 1. The sidebar indents one step per
// level inside a fixed-width column, so this is a legibility bound as much as a
// data one — five levels of indent already leave a filed chat's title nearly
// unreadable.
export const MAX_FOLDER_DEPTH = 5;

// Namespaced like the other internal metadata keys (``deerflow_pinned``,
// ``deerflow_branch``) so it cannot collide with a future feature or a
// client-supplied key. Keep in sync with the backend
// ``THREAD_FOLDER_METADATA_KEY`` and the E2E mock-api constant.
export const THREAD_FOLDER_METADATA_KEY = "deerflow_folder";

// Which folders are expanded is a per-browser convenience (the same chat tree
// can reasonably be open on the desktop and collapsed on the laptop), so unlike
// the folder list itself it never leaves localStorage.
export const CHAT_FOLDERS_EXPANDED_STORAGE_KEY =
  "deerflow.chat-folders.expanded";

// A folder row advertises its own id under this MIME so folders can be dragged
// into each other. Deliberately *not* the thread MIME: a drop target reads the
// type list to decide what it accepts, so keeping the two separate is what lets
// the root list accept both while a folder refuses to swallow itself.
export const CHAT_FOLDER_DND_MIME = "application/x-deerflow-folder-id";

/**
 * Trim and cap a user-typed folder name. Returns `null` for a name that is not
 * usable at all (empty or whitespace only), which every caller treats as "make
 * no change" rather than "store a blank folder".
 */
export function normalizeFolderName(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) {
    return null;
  }
  return trimmed.slice(0, MAX_FOLDER_NAME_CHARS);
}

/** The folder's own `parentId`, normalized to `null` for "top level". */
export function parentIdOfFolder(folder: ChatFolder): string | null {
  const raw = folder.parentId;
  if (typeof raw !== "string") {
    return null;
  }
  return raw.trim() || null;
}

/** Build a folder record without a `parentId` key when it sits at the top. */
function withParent(
  id: string,
  name: string,
  parentId: string | null,
): ChatFolder {
  return parentId === null ? { id, name } : { id, name, parentId };
}

/**
 * How deep a folder sits, counting the top level as 1. Unknown ids answer 0,
 * and a chain that loops answers the depth reached before the loop closed —
 * this is a display/limit helper, not a validator; {@link normalizeChatFolders}
 * is what guarantees the list has no loops in the first place.
 */
export function folderDepth(
  folders: readonly ChatFolder[],
  folderId: string,
): number {
  const byId = new Map(folders.map((folder) => [folder.id, folder]));
  let current = byId.get(folderId);
  if (!current) {
    return 0;
  }
  const seen = new Set<string>([folderId]);
  let depth = 1;
  let parentId = parentIdOfFolder(current);
  while (parentId && !seen.has(parentId)) {
    const parent = byId.get(parentId);
    if (!parent) {
      break;
    }
    seen.add(parentId);
    depth += 1;
    current = parent;
    parentId = parentIdOfFolder(parent);
  }
  return depth;
}

/**
 * A folder plus every folder below it, parents before children.
 *
 * Deleting a folder deletes what is *in* it — the subfolders go with it, the
 * way a file manager works. The conversations never do: the caller clears their
 * `deerflow_folder`, and anything it misses is caught by the unknown-folder
 * fallback in {@link groupThreadsByFolder}.
 */
export function folderSubtreeIds(
  folders: readonly ChatFolder[],
  folderId: string,
): string[] {
  if (!folders.some((folder) => folder.id === folderId)) {
    return [];
  }
  const childrenOf = new Map<string, string[]>();
  for (const folder of folders) {
    const parentId = parentIdOfFolder(folder);
    if (parentId === null) {
      continue;
    }
    const siblings = childrenOf.get(parentId);
    if (siblings) {
      siblings.push(folder.id);
    } else {
      childrenOf.set(parentId, [folder.id]);
    }
  }
  const ids: string[] = [];
  const queue = [folderId];
  const seen = new Set<string>([folderId]);
  while (queue.length > 0) {
    const id = queue.shift()!;
    ids.push(id);
    for (const childId of childrenOf.get(id) ?? []) {
      if (!seen.has(childId)) {
        seen.add(childId);
        queue.push(childId);
      }
    }
  }
  return ids;
}

/** How many levels the subtree rooted at *folderId* is tall (itself = 1). */
function subtreeHeight(
  folders: readonly ChatFolder[],
  folderId: string,
): number {
  const subtree = new Set(folderSubtreeIds(folders, folderId));
  let height = 0;
  for (const folder of folders) {
    if (subtree.has(folder.id)) {
      height = Math.max(height, folderDepth(folders, folder.id));
    }
  }
  const base = folderDepth(folders, folderId);
  return base === 0 ? 0 : height - base + 1;
}

/**
 * Can a folder be created directly under *parentId*?
 *
 * `null` (the top level) always can, up to the count cap. Otherwise the parent
 * has to exist and still have a level left underneath it. The UI asks this to
 * *disable* the "New subfolder" entry rather than letting the user name a
 * folder and then be told no.
 */
export function canNestUnder(
  folders: readonly ChatFolder[],
  parentId: string | null,
): boolean {
  if (folders.length >= MAX_CHAT_FOLDERS) {
    return false;
  }
  if (parentId === null) {
    return true;
  }
  const depth = folderDepth(folders, parentId);
  return depth > 0 && depth < MAX_FOLDER_DEPTH;
}

/**
 * Append a folder. Returns the same array reference when nothing changed (a
 * blank name, a duplicate id, a full list, or a parent that cannot take it) so
 * callers can skip the write.
 */
export function addFolder(
  folders: readonly ChatFolder[],
  folder: ChatFolder,
): ChatFolder[] | readonly ChatFolder[] {
  const name = normalizeFolderName(folder.name);
  const id = folder.id.trim();
  if (!name || !id) {
    return folders;
  }
  if (folders.some((existing) => existing.id === id)) {
    return folders;
  }
  const parentId = parentIdOfFolder(folder);
  if (!canNestUnder(folders, parentId)) {
    return folders;
  }
  return [...folders, withParent(id, name, parentId)];
}

/** Rename in place, preserving display order. Same-reference = no change. */
export function renameFolder(
  folders: readonly ChatFolder[],
  folderId: string,
  rawName: string,
): ChatFolder[] | readonly ChatFolder[] {
  const name = normalizeFolderName(rawName);
  if (!name) {
    return folders;
  }
  if (
    !folders.some((folder) => folder.id === folderId && folder.name !== name)
  ) {
    return folders;
  }
  return folders.map((folder) =>
    folder.id === folderId ? { ...folder, name } : folder,
  );
}

/**
 * Can *folderId* be moved under *parentId*?
 *
 * Three ways it cannot, and all three are silent disasters if allowed: moving a
 * folder into itself or into one of its own descendants detaches the whole
 * subtree from the tree (the folders stop rendering, the chats inside them fall
 * back to the root list, and nothing says why), and a move that pushes the
 * deepest descendant past {@link MAX_FOLDER_DEPTH} indents a chat title out of
 * the sidebar.
 */
export function canMoveFolderUnder(
  folders: readonly ChatFolder[],
  folderId: string,
  parentId: string | null,
): boolean {
  if (!folders.some((folder) => folder.id === folderId)) {
    return false;
  }
  if (parentId === null) {
    return true;
  }
  if (parentId === folderId) {
    return false;
  }
  if (!folders.some((folder) => folder.id === parentId)) {
    return false;
  }
  if (folderSubtreeIds(folders, folderId).includes(parentId)) {
    return false;
  }
  return (
    folderDepth(folders, parentId) + subtreeHeight(folders, folderId) <=
    MAX_FOLDER_DEPTH
  );
}

/**
 * Re-parent a folder, carrying its subtree with it. Returns the same reference
 * when the move is a no-op or {@link canMoveFolderUnder} refuses it.
 */
export function moveFolder(
  folders: readonly ChatFolder[],
  folderId: string,
  parentId: string | null,
): ChatFolder[] | readonly ChatFolder[] {
  const current = folders.find((folder) => folder.id === folderId);
  if (!current || parentIdOfFolder(current) === parentId) {
    return folders;
  }
  if (!canMoveFolderUnder(folders, folderId, parentId)) {
    return folders;
  }
  return folders.map((folder) =>
    folder.id === folderId
      ? withParent(folder.id, folder.name, parentId)
      : folder,
  );
}

/**
 * Drop a folder **and every folder inside it**. The conversations are never
 * touched here — see {@link folderSubtreeIds}.
 */
export function removeFolder(
  folders: readonly ChatFolder[],
  folderId: string,
): ChatFolder[] | readonly ChatFolder[] {
  const doomed = new Set(folderSubtreeIds(folders, folderId));
  if (doomed.size === 0) {
    return folders;
  }
  return folders.filter((folder) => !doomed.has(folder.id));
}

function isValidFolder(value: unknown): value is ChatFolder {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const folder = value as Record<string, unknown>;
  return (
    typeof folder.id === "string" &&
    folder.id.trim().length > 0 &&
    typeof folder.name === "string" &&
    folder.name.trim().length > 0
  );
}

/**
 * Force a parent list into a real forest: every `parentId` names an existing
 * folder, no chain loops, and nothing sits deeper than
 * {@link MAX_FOLDER_DEPTH}.
 *
 * Violations are repaired by **moving the offending folder to the top level**,
 * never by dropping it — a folder that disappears takes the chats inside it out
 * of their folder with no way back, while a folder that surfaces at the top is
 * visible, named, and one drag from where it belongs.
 *
 * Repaired one folder at a time, re-deriving depths after each fix, because a
 * single repair can resolve several violations at once (orphaning the middle of
 * an over-deep chain brings everything below it back into range).
 */
function repairFolderTree(
  entries: { id: string; name: string; parentId: string | null }[],
): void {
  const byId = new Map(entries.map((entry) => [entry.id, entry]));
  for (const entry of entries) {
    if (entry.parentId !== null && !byId.has(entry.parentId)) {
      entry.parentId = null;
    }
    if (entry.parentId === entry.id) {
      entry.parentId = null;
    }
  }
  // Bounded by the number of folders: every pass orphans exactly one folder,
  // and an all-root list has no violations left to find.
  for (let pass = 0; pass <= entries.length; pass += 1) {
    const depths = new Map<string, number>();
    let frontier = entries.filter((entry) => entry.parentId === null);
    let depth = 1;
    while (frontier.length > 0) {
      for (const entry of frontier) {
        depths.set(entry.id, depth);
      }
      depth += 1;
      const parents = new Set(frontier.map((entry) => entry.id));
      frontier = entries.filter(
        (entry) =>
          !depths.has(entry.id) &&
          entry.parentId !== null &&
          parents.has(entry.parentId),
      );
    }
    // Too deep first, shallowest of them: orphaning the highest offender is
    // what pulls a whole over-long chain back into range in one move. A folder
    // no walk reached is in a cycle.
    const tooDeep = entries
      .filter((entry) => (depths.get(entry.id) ?? 0) > MAX_FOLDER_DEPTH)
      .sort((a, b) => (depths.get(a.id) ?? 0) - (depths.get(b.id) ?? 0));
    const violator =
      tooDeep[0] ?? entries.find((entry) => !depths.has(entry.id));
    if (!violator) {
      return;
    }
    violator.parentId = null;
  }
}

/**
 * Parse a persisted/served folder list defensively: a non-array, malformed
 * entries and duplicate ids degrade to a filtered list rather than throwing,
 * the result is capped, and the parent links are repaired into a real forest.
 * Mirrors ``normalize_chat_folders`` on the server.
 */
export function normalizeChatFolders(parsed: unknown): ChatFolder[] {
  if (!Array.isArray(parsed)) {
    return [];
  }
  const entries: { id: string; name: string; parentId: string | null }[] = [];
  const seen = new Set<string>();
  for (const entry of parsed) {
    if (!isValidFolder(entry)) {
      continue;
    }
    const id = entry.id.trim();
    const name = normalizeFolderName(entry.name);
    if (!name || seen.has(id)) {
      continue;
    }
    seen.add(id);
    entries.push({ id, name, parentId: parentIdOfFolder(entry) });
    if (entries.length >= MAX_CHAT_FOLDERS) {
      break;
    }
  }
  repairFolderTree(entries);
  return entries.map((entry) =>
    withParent(entry.id, entry.name, entry.parentId),
  );
}

/** The folder a conversation was filed into, or `null` for the root list. */
export function folderIdOfThread(
  thread: Pick<AgentThread, "metadata">,
): string | null {
  const raw = thread.metadata?.[THREAD_FOLDER_METADATA_KEY];
  if (typeof raw !== "string") {
    return null;
  }
  return raw.trim() || null;
}

/**
 * Partition the side list into a folder **tree** plus the root level.
 *
 * Three properties are load-bearing and must survive any refactor:
 *
 * 1. **A conversation appears exactly once.** A chat inside a folder is *not*
 *    also listed at the root — that is the Windows-explorer behaviour this
 *    feature exists for, and a duplicate would make the list unreadable. A chat
 *    in a subfolder is likewise listed only there, not repeated in its parent.
 * 2. **A conversation is never hidden by bad data.** A thread whose
 *    `deerflow_folder` names a folder that no longer exists (deleted on another
 *    device, or dropped by the store's normalization) falls back to the root
 *    list. Deleting a folder therefore cannot swallow the chats inside it, even
 *    before their metadata is cleared.
 * 3. **A collapsed parent still reports what is under it.** `totalThreadCount`
 *    counts the whole subtree, so filing a chat two levels down never reads as
 *    an empty folder from the outside.
 *
 * Relative order inside each partition is the caller's order, untouched.
 * Folders keep their list order at every level.
 */
export function groupThreadsByFolder(
  threads: readonly AgentThread[],
  folders: readonly ChatFolder[],
): GroupedThreadList {
  // Normalize first: a caller-supplied list with a dangling parent or a loop
  // would otherwise silently drop whole branches out of the rendered tree.
  const safeFolders = normalizeChatFolders(folders);
  const nodes = new Map<string, ChatFolderNode>(
    safeFolders.map((folder) => [
      folder.id,
      { folder, threads: [], children: [], totalThreadCount: 0 },
    ]),
  );
  const tree: ChatFolderNode[] = [];
  for (const folder of safeFolders) {
    const node = nodes.get(folder.id)!;
    const parentId = parentIdOfFolder(folder);
    const parent = parentId ? nodes.get(parentId) : undefined;
    if (parent) {
      parent.children.push(node);
    } else {
      tree.push(node);
    }
  }

  const ungrouped: AgentThread[] = [];
  for (const thread of threads) {
    const folderId = folderIdOfThread(thread);
    const node = folderId ? nodes.get(folderId) : undefined;
    if (node) {
      node.threads.push(thread);
    } else {
      ungrouped.push(thread);
    }
  }

  const total = (node: ChatFolderNode): number => {
    node.totalThreadCount =
      node.threads.length +
      node.children.reduce((sum, child) => sum + total(child), 0);
    return node.totalThreadCount;
  };
  for (const node of tree) {
    total(node);
  }
  return { tree, ungrouped };
}

/** Every node of the tree, parents before children — for flat iteration. */
export function flattenFolderTree(
  tree: readonly ChatFolderNode[],
): ChatFolderNode[] {
  const flat: ChatFolderNode[] = [];
  const walk = (nodes: readonly ChatFolderNode[]) => {
    for (const node of nodes) {
      flat.push(node);
      walk(node.children);
    }
  };
  walk(tree);
  return flat;
}

/** Parse the per-browser expanded-folder set; unusable storage reads as empty. */
export function deserializeExpandedFolderIds(
  raw: string | null | undefined,
): Set<string> {
  if (!raw) {
    return new Set();
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return new Set();
    }
    return new Set(
      parsed.filter(
        (value): value is string =>
          typeof value === "string" && value.trim().length > 0,
      ),
    );
  } catch {
    return new Set();
  }
}
