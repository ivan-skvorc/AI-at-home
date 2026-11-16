/**
 * Shared plumbing for the sidebar's bulk chat actions (move, archive, delete).
 *
 * There is no bulk endpoint: each action is a client-side loop over the
 * single-thread routes. The loop is bounded so a 200-chat selection does not
 * open 200 connections at once, reports each item's outcome, and never
 * retries a write on its own (workspace AGENTS.md) — a chat that failed stays
 * selected and the user decides.
 */

/** How many single-thread writes a bulk action keeps in flight. */
export const BULK_THREAD_CONCURRENCY = 4;

export type BulkThreadFailure = {
  threadId: string;
  error: unknown;
  /** HTTP status when the error carried one (409 = a run is in flight). */
  status: number | undefined;
};

export type BulkThreadResult = {
  succeeded: string[];
  failed: BulkThreadFailure[];
};

/** The HTTP status an SDK `HTTPError`, a fetch wrapper or a plain object carries. */
export function httpStatusOf(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null) {
    return undefined;
  }
  const status = Reflect.get(error, "status");
  if (typeof status === "number") {
    return status;
  }
  const response = Reflect.get(error, "response");
  if (typeof response === "object" && response !== null) {
    const responseStatus = Reflect.get(response, "status");
    if (typeof responseStatus === "number") {
      return responseStatus;
    }
  }
  return undefined;
}

/**
 * Run `task` over `items` with at most `limit` in flight, answering every
 * outcome in input order. A rejection never stops the others.
 */
export async function settleWithConcurrency<T, R>(
  items: readonly T[],
  limit: number,
  task: (item: T) => Promise<R>,
): Promise<PromiseSettledResult<R>[]> {
  const results = new Array<PromiseSettledResult<R>>(items.length);
  let next = 0;
  const worker = async () => {
    while (next < items.length) {
      const index = next;
      next += 1;
      try {
        results[index] = {
          status: "fulfilled",
          value: await task(items[index]!),
        };
      } catch (reason) {
        results[index] = { status: "rejected", reason };
      }
    }
  };
  const workers = Array.from(
    { length: Math.max(1, Math.min(limit, items.length)) },
    worker,
  );
  await Promise.all(workers);
  return results;
}

/** Split settled per-thread outcomes into the ids that worked and the failures. */
export function partitionBulkResults(
  threadIds: readonly string[],
  results: readonly PromiseSettledResult<unknown>[],
): BulkThreadResult {
  const succeeded: string[] = [];
  const failed: BulkThreadFailure[] = [];
  results.forEach((result, index) => {
    const threadId = threadIds[index]!;
    if (result.status === "fulfilled") {
      succeeded.push(threadId);
    } else {
      failed.push({
        threadId,
        error: result.reason,
        status: httpStatusOf(result.reason),
      });
    }
  });
  return { succeeded, failed };
}

/** Each id once, in first-seen order. */
export function uniqueThreadIds(threadIds: Iterable<string>): string[] {
  return [...new Set(threadIds)];
}
