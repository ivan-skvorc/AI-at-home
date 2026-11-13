import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import {
  THREAD_FILES_ROOT,
  type ThreadFileEntry,
  type ThreadFileKind,
  type ThreadFileListing,
} from "./types";

/** A non-2xx answer from the listing route, with the Gateway's detail. */
export class ThreadFilesRequestError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ThreadFilesRequestError";
    this.status = status;
  }
}

const KNOWN_KINDS: ReadonlySet<string> = new Set<ThreadFileKind>([
  "directory",
  "file",
  "symlink",
  "other",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** True for `/mnt/user-data` and paths below it without `.` or `..` steps. */
export function isThreadFilesPath(path: string): boolean {
  if (path !== THREAD_FILES_ROOT && !path.startsWith(`${THREAD_FILES_ROOT}/`)) {
    return false;
  }
  return path
    .slice(THREAD_FILES_ROOT.length + 1)
    .split("/")
    .every((segment) => segment !== "." && segment !== "..");
}

function parseEntry(
  value: unknown,
  parentPath: string,
): ThreadFileEntry | null {
  if (!isRecord(value)) {
    return null;
  }
  const { name, path, kind, size, modified_at: modifiedAt } = value;
  if (
    typeof name !== "string" ||
    name === "" ||
    name === "." ||
    name === ".." ||
    name.includes("/")
  ) {
    return null;
  }
  // The entry's path is what the explorer lists next and opens, so it must be
  // exactly the listed directory plus the name; anything else is malformed.
  if (path !== `${parentPath}/${name}` || typeof kind !== "string") {
    return null;
  }
  return {
    name,
    path,
    // A kind this client does not know is shown as an entry it cannot open.
    kind: KNOWN_KINDS.has(kind) ? (kind as ThreadFileKind) : "other",
    size:
      typeof size === "number" && Number.isFinite(size) && size >= 0
        ? size
        : null,
    modified_at:
      typeof modifiedAt === "string" && !Number.isNaN(Date.parse(modifiedAt))
        ? modifiedAt
        : null,
  };
}

/**
 * Narrow a listing response. Returns null when the body is not a listing at
 * all; malformed or duplicate entries are dropped and the rest kept.
 */
export function parseThreadFileListing(
  data: unknown,
): ThreadFileListing | null {
  if (!isRecord(data)) {
    return null;
  }
  const { path, exists, entries, truncated, total } = data;
  if (
    typeof path !== "string" ||
    !isThreadFilesPath(path) ||
    !Array.isArray(entries)
  ) {
    return null;
  }
  const seen = new Set<string>();
  const parsedEntries: ThreadFileEntry[] = [];
  for (const value of entries) {
    const entry = parseEntry(value, path);
    if (entry && !seen.has(entry.path)) {
      seen.add(entry.path);
      parsedEntries.push(entry);
    }
  }
  return {
    path,
    exists: typeof exists === "boolean" ? exists : true,
    entries: parsedEntries,
    truncated: truncated === true,
    total:
      typeof total === "number" && Number.isFinite(total)
        ? Math.max(Math.floor(total), parsedEntries.length)
        : parsedEntries.length,
  };
}

async function readErrorDetail(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => null);
  if (isRecord(body) && typeof body.detail === "string" && body.detail) {
    return body.detail;
  }
  return `HTTP ${response.status}`;
}

export function urlOfThreadFiles(threadId: string, path: string): string {
  return `${getBackendBaseURL()}/api/threads/${encodeURIComponent(
    threadId,
  )}/files?path=${encodeURIComponent(path)}`;
}

/** List one directory of the thread's `/mnt/user-data` tree. */
export async function fetchThreadFiles({
  threadId,
  path = THREAD_FILES_ROOT,
  signal,
}: {
  threadId: string;
  path?: string;
  signal?: AbortSignal;
}): Promise<ThreadFileListing> {
  const response = await fetch(urlOfThreadFiles(threadId, path), { signal });
  if (!response.ok) {
    throw new ThreadFilesRequestError(
      response.status,
      await readErrorDetail(response),
    );
  }
  const listing = parseThreadFileListing(await response.json());
  if (!listing) {
    throw new Error("The Gateway returned a malformed file listing.");
  }
  return listing;
}
