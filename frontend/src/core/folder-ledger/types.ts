/**
 * The folder ledger (`/api/folder-ledger`): which conversations created or
 * edited the top-level folders of writable shared mounts. A conversation's own
 * folder (`/mnt/user-data`) is not tracked here: it belongs to that one
 * conversation and is deleted with it.
 */

export type LedgerFolderKind = "dir" | "file";

/** How this conversation relates to a folder. */
export type LedgerFolderRole = "created" | "edited" | "inherited";

/**
 * How the ledger knows who created a folder: a write was seen creating it, it
 * existed before any recorded write, or a shell command most likely made it.
 */
export type LedgerCreatedAttribution =
  | "observed_create"
  | "preexisting"
  | "inferred_shell";

export type LedgerEditOp = "write" | "append" | "edit" | "shell";

/** One folder as `GET /threads/{id}/folders` reports it, after validation. */
export interface LedgerFolder {
  id: string;
  /** Container path, e.g. `/mnt/projects/acme`. */
  path: string;
  name: string;
  mount_path: string;
  kind: LedgerFolderKind;
  /** Absent in the folder detail, which is not about one conversation. */
  role: LedgerFolderRole | null;
  created_here: boolean;
  created_attribution: LedgerCreatedAttribution;
  first_at: string | null;
  last_at: string | null;
  writes: number;
  edits: number;
  shell_ops: number;
  /** Live conversations of any user, other than this one, that use it. */
  other_live_threads: number;
  /** The Gateway can see the mount's host directory. */
  host_visible: boolean;
}

export interface ThreadFolders {
  /** False when the deployment has no SQL persistence: nothing is tracked. */
  available: boolean;
  folders: LedgerFolder[];
}

/** A conversation that worked on a folder, in the folder detail. */
export interface LedgerFolderThread {
  /** The real id for the caller's own conversations, a pseudonym otherwise. */
  thread_id: string;
  own: boolean;
  /** Only for the caller's own conversations. */
  title: string | null;
  role: LedgerFolderRole;
  first_at: string | null;
  last_at: string | null;
  deleted: boolean;
}

/** One entry of a folder's edit log. */
export interface LedgerFolderEvent {
  thread_id: string;
  run_id: string | null;
  op: LedgerEditOp;
  /** Relative to the mount root, starting with the folder name. */
  rel_path: string;
  ts: string | null;
}

export interface LedgerFolderDetail {
  folder: LedgerFolder;
  threads: LedgerFolderThread[];
  /** Newest first, capped by the Gateway. */
  events: LedgerFolderEvent[];
}

/** Why an orphaned folder cannot be deleted from the UI. */
export type OrphanKeepReason =
  | "preexisting"
  | "not_creator"
  | "unsupported_platform"
  | "mount_unavailable"
  | "host_not_visible"
  | "unknown";

/** A folder that no live conversation uses any more. */
export interface OrphanFolder {
  id: string;
  path: string;
  name: string;
  mount_path: string;
  created_by_thread_id: string | null;
  last_at: string | null;
  writes: number;
  edits: number;
  deletable: boolean;
  /** Set when `deletable` is false. */
  reason: OrphanKeepReason | null;
}

export interface OrphanFolders {
  available: boolean;
  orphans: OrphanFolder[];
}
