import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  LedgerCreatedAttribution,
  LedgerEditOp,
  LedgerFolder,
  LedgerFolderDetail,
  LedgerFolderEvent,
  LedgerFolderRole,
  LedgerFolderThread,
  OrphanFolder,
  OrphanFolders,
  OrphanKeepReason,
  ThreadFolders,
} from "./types";

/** Thread ids one `POST /orphans` accepts; longer lists are split. */
export const MAX_ORPHAN_THREAD_IDS = 500;

/** A non-2xx answer from a folder-ledger route, with the Gateway's detail. */
export class FolderLedgerRequestError extends Error {
  readonly status: number;
  /** The refusal code of a structured detail (`in_use`, `not_creator`, …). */
  readonly code: string | null;

  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.name = "FolderLedgerRequestError";
    this.status = status;
    this.code = code;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : 0;
}

function asTimestamp(value: unknown): string | null {
  return typeof value === "string" && !Number.isNaN(Date.parse(value))
    ? value
    : null;
}

const ROLES: ReadonlySet<string> = new Set<LedgerFolderRole>([
  "created",
  "edited",
  "inherited",
]);
const ATTRIBUTIONS: ReadonlySet<string> = new Set<LedgerCreatedAttribution>([
  "observed_create",
  "preexisting",
  "inferred_shell",
]);
const OPS: ReadonlySet<string> = new Set<LedgerEditOp>([
  "write",
  "append",
  "edit",
  "shell",
]);
const KEEP_REASONS: ReadonlySet<string> = new Set<OrphanKeepReason>([
  "preexisting",
  "not_creator",
  "unsupported_platform",
  "mount_unavailable",
  "host_not_visible",
  "shell_inferred",
  "changed",
]);

function parseRole(value: unknown): LedgerFolderRole | null {
  return typeof value === "string" && ROLES.has(value)
    ? (value as LedgerFolderRole)
    : null;
}

function parseFolder(value: unknown): LedgerFolder | null {
  if (!isRecord(value)) {
    return null;
  }
  const id = asString(value.id);
  const path = asString(value.path);
  const name = asString(value.name);
  const mountPath = asString(value.mount_path);
  if (!id || !path || !name || !mountPath) {
    return null;
  }
  const attribution = asString(value.created_attribution);
  return {
    id,
    path,
    name,
    mount_path: mountPath,
    kind: value.kind === "file" ? "file" : "dir",
    role: parseRole(value.role),
    created_here: value.created_here === true,
    // An attribution this client does not know is treated as the cautious one.
    created_attribution:
      attribution && ATTRIBUTIONS.has(attribution)
        ? (attribution as LedgerCreatedAttribution)
        : "preexisting",
    first_at: asTimestamp(value.first_at),
    last_at: asTimestamp(value.last_at),
    writes: asCount(value.writes),
    edits: asCount(value.edits),
    shell_ops: asCount(value.shell_ops),
    other_live_threads: asCount(value.other_live_threads),
    host_visible: value.host_visible === true,
  };
}

function parseList<T>(
  values: unknown,
  parse: (value: unknown) => T | null,
  keyOf: (item: T) => string,
): T[] {
  if (!Array.isArray(values)) {
    return [];
  }
  const seen = new Set<string>();
  const items: T[] = [];
  for (const value of values) {
    const item = parse(value);
    if (item && !seen.has(keyOf(item))) {
      seen.add(keyOf(item));
      items.push(item);
    }
  }
  return items;
}

/** Narrow `GET /threads/{id}/folders`; null when the body is not one. */
export function parseThreadFolders(data: unknown): ThreadFolders | null {
  if (!isRecord(data) || typeof data.available !== "boolean") {
    return null;
  }
  return {
    available: data.available,
    folders: data.available
      ? parseList(data.folders, parseFolder, (folder) => folder.id)
      : [],
  };
}

function parseFolderThread(value: unknown): LedgerFolderThread | null {
  if (!isRecord(value)) {
    return null;
  }
  const threadId = asString(value.thread_id);
  const role = parseRole(value.role);
  if (!threadId || !role) {
    return null;
  }
  const title = asString(value.title);
  return {
    thread_id: threadId,
    own: value.own === true,
    title: title?.trim() ? title : null,
    role,
    first_at: asTimestamp(value.first_at),
    last_at: asTimestamp(value.last_at),
    deleted: value.deleted === true,
  };
}

function parseFolderEvent(value: unknown): LedgerFolderEvent | null {
  if (!isRecord(value)) {
    return null;
  }
  const threadId = asString(value.thread_id);
  const op = asString(value.op);
  const relPath = asString(value.rel_path);
  if (!threadId || !op || !OPS.has(op) || relPath === null) {
    return null;
  }
  return {
    thread_id: threadId,
    run_id: asString(value.run_id),
    op: op as LedgerEditOp,
    rel_path: relPath,
    ts: asTimestamp(value.ts),
  };
}

/** Narrow `GET /folders/{id}`; null when the body is not one. */
export function parseFolderDetail(data: unknown): LedgerFolderDetail | null {
  if (!isRecord(data)) {
    return null;
  }
  const folder = parseFolder(data.folder);
  if (!folder) {
    return null;
  }
  const events = Array.isArray(data.events)
    ? data.events
        .map(parseFolderEvent)
        .filter((event): event is LedgerFolderEvent => event !== null)
    : [];
  return {
    folder,
    threads: parseList(
      data.threads,
      parseFolderThread,
      (thread) => thread.thread_id,
    ),
    events,
  };
}

function parseOrphan(value: unknown): OrphanFolder | null {
  if (!isRecord(value)) {
    return null;
  }
  const id = asString(value.id);
  const path = asString(value.path);
  const name = asString(value.name);
  const mountPath = asString(value.mount_path);
  if (!id || !path || !name || !mountPath) {
    return null;
  }
  const deletable = value.deletable === true;
  const reason = asString(value.reason);
  return {
    id,
    path,
    name,
    mount_path: mountPath,
    created_by_thread_id: asString(value.created_by_thread_id),
    last_at: asTimestamp(value.last_at),
    writes: asCount(value.writes),
    edits: asCount(value.edits),
    deletable,
    reason: deletable
      ? null
      : reason && KEEP_REASONS.has(reason)
        ? (reason as OrphanKeepReason)
        : "unknown",
  };
}

/** Narrow `POST /orphans`; null when the body is not one. */
export function parseOrphanFolders(data: unknown): OrphanFolders | null {
  if (!isRecord(data) || typeof data.available !== "boolean") {
    return null;
  }
  return {
    available: data.available,
    orphans: data.available
      ? parseList(data.orphans, parseOrphan, (orphan) => orphan.id)
      : [],
  };
}

async function requestError(
  response: Response,
): Promise<FolderLedgerRequestError> {
  const body: unknown = await response.json().catch(() => null);
  const detail = isRecord(body) ? body.detail : null;
  if (typeof detail === "string" && detail) {
    return new FolderLedgerRequestError(response.status, detail);
  }
  if (isRecord(detail)) {
    const message = asString(detail.message);
    return new FolderLedgerRequestError(
      response.status,
      message ?? `HTTP ${response.status}`,
      asString(detail.code),
    );
  }
  return new FolderLedgerRequestError(
    response.status,
    `HTTP ${response.status}`,
  );
}

function ledgerURL(path: string): string {
  return `${getBackendBaseURL()}/api/folder-ledger${path}`;
}

/** The shared folders one conversation created, edited or inherited. */
export async function fetchThreadFolders(
  threadId: string,
  { signal }: { signal?: AbortSignal } = {},
): Promise<ThreadFolders> {
  const response = await fetch(
    ledgerURL(`/threads/${encodeURIComponent(threadId)}/folders`),
    { signal },
  );
  if (!response.ok) {
    throw await requestError(response);
  }
  const parsed = parseThreadFolders(await response.json());
  if (!parsed) {
    throw new Error("The Gateway returned a malformed folder list.");
  }
  return parsed;
}

/** One folder, the conversations that worked on it and its edit log. */
export async function fetchFolderDetail(
  folderId: string,
  { signal }: { signal?: AbortSignal } = {},
): Promise<LedgerFolderDetail> {
  const response = await fetch(
    ledgerURL(`/folders/${encodeURIComponent(folderId)}`),
    { signal },
  );
  if (!response.ok) {
    throw await requestError(response);
  }
  const parsed = parseFolderDetail(await response.json());
  if (!parsed) {
    throw new Error("The Gateway returned a malformed folder.");
  }
  return parsed;
}

/**
 * The shared folders the given (deleted) conversations leave with no live
 * user. Longer lists than one request accepts are asked in chunks and merged.
 */
export async function fetchOrphanFolders(
  threadIds: readonly string[],
  { signal }: { signal?: AbortSignal } = {},
): Promise<OrphanFolders> {
  const ids = [...new Set(threadIds.filter((id) => id !== ""))];
  if (ids.length === 0) {
    return { available: true, orphans: [] };
  }
  let available = true;
  const orphans = new Map<string, OrphanFolder>();
  for (let start = 0; start < ids.length; start += MAX_ORPHAN_THREAD_IDS) {
    const response = await fetch(ledgerURL("/orphans"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        thread_ids: ids.slice(start, start + MAX_ORPHAN_THREAD_IDS),
      }),
      signal,
    });
    if (!response.ok) {
      throw await requestError(response);
    }
    const parsed = parseOrphanFolders(await response.json());
    if (!parsed) {
      throw new Error("The Gateway returned a malformed orphan list.");
    }
    if (!parsed.available) {
      // Without persistence nothing is tracked; later chunks say the same.
      available = false;
      break;
    }
    for (const orphan of parsed.orphans) {
      if (!orphans.has(orphan.id)) {
        orphans.set(orphan.id, orphan);
      }
    }
  }
  return { available, orphans: available ? [...orphans.values()] : [] };
}

/**
 * Delete a folder no live conversation uses. `confirmName` must equal the
 * folder's name; the Gateway refuses anything else. Never retried.
 */
export async function deleteLedgerFolder(
  folderId: string,
  confirmName: string,
  { signal }: { signal?: AbortSignal } = {},
): Promise<void> {
  const response = await fetch(
    `${ledgerURL(`/folders/${encodeURIComponent(folderId)}`)}?confirm_name=${encodeURIComponent(confirmName)}`,
    { method: "DELETE", signal },
  );
  if (!response.ok) {
    throw await requestError(response);
  }
}

/** Keep a folder and stop offering it for deletion. */
export async function dismissLedgerFolder(
  folderId: string,
  { signal }: { signal?: AbortSignal } = {},
): Promise<void> {
  const response = await fetch(
    ledgerURL(`/folders/${encodeURIComponent(folderId)}/dismiss`),
    { method: "POST", signal },
  );
  if (!response.ok) {
    throw await requestError(response);
  }
}
