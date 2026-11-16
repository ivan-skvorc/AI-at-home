/**
 * The seam between conversation deletion and the folder-ledger orphan offer.
 *
 * Every delete path (the single-delete dialog, bulk delete, any future one)
 * announces the conversations that are gone with {@link notifyThreadsDeleted};
 * one workspace-level host listens, coalesces bursts into one batch and asks
 * the Gateway which shared folders those conversations left without a user.
 * A window event keeps the delete hooks free of any dependency on the host,
 * which lives above the routes.
 */

export const THREADS_DELETED_EVENT = "deerflow:threads-deleted";

/** How long the host waits for more deletions before it asks once. */
export const THREADS_DELETED_COALESCE_MS = 300;

export interface ThreadsDeletedDetail {
  threadIds: string[];
}

function uniqueIds(threadIds: readonly unknown[]): string[] {
  const seen = new Set<string>();
  for (const id of threadIds) {
    if (typeof id === "string" && id !== "") {
      seen.add(id);
    }
  }
  return [...seen];
}

/**
 * Announce conversations that were deleted (including their Side Chat
 * threads). Call it once per user action: a bulk delete passes every id in one
 * call rather than one call per conversation.
 */
export function notifyThreadsDeleted(threadIds: readonly string[]): void {
  if (typeof window === "undefined") {
    return;
  }
  const ids = uniqueIds(threadIds);
  if (ids.length === 0) {
    return;
  }
  window.dispatchEvent(
    new CustomEvent<ThreadsDeletedDetail>(THREADS_DELETED_EVENT, {
      detail: { threadIds: ids },
    }),
  );
}

export interface ThreadsDeletedListenerOptions {
  /** Quiet period before a batch is delivered. */
  delayMs?: number;
  /** Where to listen; the browser window by default. */
  target?: EventTarget;
}

/**
 * Listen for {@link notifyThreadsDeleted} and deliver the ids in coalesced
 * batches: every notification restarts a quiet-period timer, and when it runs
 * out the ids seen since the last batch (deduplicated, in arrival order) go to
 * `onBatch` in one call. Returns the unsubscribe function, which also drops a
 * batch that has not been delivered yet.
 */
export function listenForDeletedThreads(
  onBatch: (threadIds: string[]) => void,
  {
    delayMs = THREADS_DELETED_COALESCE_MS,
    target,
  }: ThreadsDeletedListenerOptions = {},
): () => void {
  const eventTarget =
    target ?? (typeof window === "undefined" ? undefined : window);
  if (!eventTarget) {
    return () => undefined;
  }
  let pending: string[] = [];
  let timer: ReturnType<typeof setTimeout> | null = null;

  const flush = () => {
    timer = null;
    const batch = pending;
    pending = [];
    if (batch.length > 0) {
      onBatch(batch);
    }
  };

  const handle = (event: Event) => {
    const detail: unknown = (event as CustomEvent<unknown>).detail;
    const ids =
      typeof detail === "object" &&
      detail !== null &&
      Array.isArray((detail as { threadIds?: unknown }).threadIds)
        ? uniqueIds((detail as { threadIds: unknown[] }).threadIds)
        : [];
    if (ids.length === 0) {
      return;
    }
    pending = uniqueIds([...pending, ...ids]);
    if (timer !== null) {
      clearTimeout(timer);
    }
    timer = setTimeout(flush, delayMs);
  };

  eventTarget.addEventListener(THREADS_DELETED_EVENT, handle);
  return () => {
    eventTarget.removeEventListener(THREADS_DELETED_EVENT, handle);
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    pending = [];
  };
}
