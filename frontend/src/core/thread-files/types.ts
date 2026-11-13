/** Virtual root of a thread's sandbox user data. */
export const THREAD_FILES_ROOT = "/mnt/user-data";

export type ThreadFileKind = "directory" | "file" | "symlink" | "other";

/** One row of `GET /api/threads/{id}/files`, after validation. */
export interface ThreadFileEntry {
  name: string;
  /** Virtual path: always the listed directory plus `/` plus `name`. */
  path: string;
  kind: ThreadFileKind;
  /** Bytes for regular files, otherwise null. */
  size: number | null;
  /** ISO 8601 timestamp, or null when the server has none. */
  modified_at: string | null;
}

export interface ThreadFileListing {
  path: string;
  /** False only for a root the sandbox has not created yet. */
  exists: boolean;
  /** Server order: directories first. */
  entries: ThreadFileEntry[];
  /** The server cut the listing at its per-call limit. */
  truncated: boolean;
  /** Every visible entry of the directory, including the ones not returned. */
  total: number;
}

/**
 * The Files view's tree. The chat panel keeps it, rather than the explorer,
 * so it survives the explorer unmounting while a file preview is open.
 */
export interface ThreadFileTreeState {
  /** Expanded directories, including ones under a collapsed parent. */
  expanded: string[];
  /** The tree item that holds the tab stop; null means the first item. */
  activeKey: string | null;
  /**
   * Focus the active item when the tree next shows it. Opening a file sets
   * it, so closing the preview returns keyboard focus to that file's row.
   */
  restoreFocus: boolean;
}

export const EMPTY_THREAD_FILE_TREE: ThreadFileTreeState = {
  expanded: [],
  activeKey: null,
  restoreFocus: false,
};
