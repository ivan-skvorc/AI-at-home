/**
 * Pure model for the sidebar's chat folders (fork feature: a folder tree in the
 * side list). A folder is a name and a stable id; **membership is not stored
 * here** — each conversation records its folder in its own thread metadata
 * (`deerflow_folder`), so renaming a folder is one small write instead of one
 * write per conversation inside it.
 *
 * Nothing React, nothing route-aware, so the grouping rules are exhaustively
 * unit-testable. Server reconciliation lives in `chat-folders-api.ts`, the React
 * state in `use-chat-folders.ts`.
 */

import type { AgentThread } from "./types";

export type ChatFolder = {
  id: string;
  name: string;
};

/** A folder plus the conversations filed into it, in list order. */
export type ChatFolderGroup = {
  folder: ChatFolder;
  threads: AgentThread[];
};

/**
 * The whole side list, partitioned. `ungrouped` is the root level: it holds
 * every conversation that is not in a folder — and, deliberately, every
 * conversation pointing at a folder that no longer exists.
 */
export type GroupedThreadList = {
  groups: ChatFolderGroup[];
  ungrouped: AgentThread[];
};

// Mirrors ``MAX_CHAT_FOLDERS`` / ``MAX_FOLDER_NAME_CHARS`` in
// ``backend/packages/harness/deerflow/config/user_ui_state.py``. Enforced on
// both sides: the API is untrusted input, and a sidebar is still a sidebar.
export const MAX_CHAT_FOLDERS = 50;
export const MAX_FOLDER_NAME_CHARS = 80;

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

/**
 * Append a folder. Returns the same array reference when nothing changed (a
 * blank name, a duplicate id, or a full list) so callers can skip the write.
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
  if (folders.length >= MAX_CHAT_FOLDERS) {
    return folders;
  }
  if (folders.some((existing) => existing.id === id)) {
    return folders;
  }
  return [...folders, { id, name }];
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

/** Drop a folder. The conversations inside it are never touched here. */
export function removeFolder(
  folders: readonly ChatFolder[],
  folderId: string,
): ChatFolder[] | readonly ChatFolder[] {
  const next = folders.filter((folder) => folder.id !== folderId);
  return next.length === folders.length ? folders : next;
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
 * Parse a persisted/served folder list defensively: a non-array, malformed
 * entries and duplicate ids degrade to a filtered list rather than throwing,
 * and the result is capped. Mirrors ``normalize_chat_folders`` on the server.
 */
export function normalizeChatFolders(parsed: unknown): ChatFolder[] {
  if (!Array.isArray(parsed)) {
    return [];
  }
  const folders: ChatFolder[] = [];
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
    folders.push({ id, name });
    if (folders.length >= MAX_CHAT_FOLDERS) {
      break;
    }
  }
  return folders;
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
 * Partition the side list into folders plus the root level.
 *
 * Two properties are load-bearing and must survive any refactor:
 *
 * 1. **A conversation appears exactly once.** A chat inside a folder is *not*
 *    also listed at the root — that is the Windows-explorer behaviour this
 *    feature exists for, and a duplicate would make the list unreadable.
 * 2. **A conversation is never hidden by bad data.** A thread whose
 *    `deerflow_folder` names a folder that no longer exists (deleted on another
 *    device, or dropped by the store's normalization) falls back to the root
 *    list. Deleting a folder therefore cannot swallow the chats inside it, even
 *    before their metadata is cleared.
 *
 * Relative order inside each partition is the caller's order, untouched.
 */
export function groupThreadsByFolder(
  threads: readonly AgentThread[],
  folders: readonly ChatFolder[],
): GroupedThreadList {
  const groups: ChatFolderGroup[] = folders.map((folder) => ({
    folder,
    threads: [],
  }));
  const groupById = new Map(groups.map((group) => [group.folder.id, group]));
  const ungrouped: AgentThread[] = [];
  for (const thread of threads) {
    const folderId = folderIdOfThread(thread);
    const group = folderId ? groupById.get(folderId) : undefined;
    if (group) {
      group.threads.push(thread);
    } else {
      ungrouped.push(thread);
    }
  }
  return { groups, ungrouped };
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
