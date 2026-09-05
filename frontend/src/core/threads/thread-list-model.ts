import type { AgentThread } from "./types";
import { isThreadPinned, sortPinnedThreads } from "./utils";

/**
 * How many unpinned **root-level** rows the sidebar will chase pages for on its
 * own before it stops and waits to be asked.
 *
 * It bounds the automatic work, not what the reader may reach: the explicit
 * "Load older chats" button stays for as long as the backend has more, so a
 * long history is never a dead end. Two things it deliberately does not count:
 * pinned conversations (they are kept out of the recency window entirely) and
 * conversations filed into a folder (they are not root rows — counting them
 * used to stop pagination while the visible list was still nearly empty).
 */
export const MAX_AUTO_LOADED_ROOT_THREADS = 200;

/**
 * How deep the sidebar will dig for those rows on its own — the second half of
 * the budget, and the one that keeps the first from being unbounded.
 *
 * Filed conversations do not count toward the row target, so a history filed
 * away almost entirely would otherwise be paged through end to end on every
 * load, one request per 50 conversations, hunting for root rows that are not
 * there. The scan ceiling stops that at a fixed number of requests; the button
 * still reaches everything past it.
 */
export const MAX_AUTO_SCANNED_THREADS = 500;

const modelCache = new WeakMap<object, ThreadListModel>();

export type ThreadListModel = {
  byId: ReadonlyMap<string, AgentThread>;
  threads: readonly AgentThread[];
};

/**
 * Every loaded conversation, deduplicated across pages and sorted pinned-first.
 *
 * There is no display cap here on purpose. The sidebar virtualizes past
 * `VIRTUALIZATION_THRESHOLD` rows, so a truncation buys no rendering work — all
 * it did was hide loaded conversations (including the members of a folder) with
 * no way to ask for them.
 */
export function buildThreadListModel(
  pages: readonly (readonly AgentThread[])[],
): ThreadListModel {
  const cacheKey = pages as object;
  const cached = modelCache.get(cacheKey);
  if (cached) return cached;

  const byId = new Map<string, AgentThread>();
  for (const page of pages) {
    for (const thread of page) {
      if (!byId.has(thread.thread_id)) {
        byId.set(thread.thread_id, thread);
      }
    }
  }
  const model: ThreadListModel = {
    byId,
    threads: sortPinnedThreads([...byId.values()]),
  };
  modelCache.set(cacheKey, model);
  return model;
}

/**
 * Whether the sidebar may fetch another page *by itself* (the scroll sentinel).
 *
 * Takes the root-level partition — what is actually listed outside the folders
 * — so filing conversations away never starves the list that is still on
 * screen, and the total loaded count, so it cannot chase root rows that do not
 * exist. See {@link MAX_AUTO_LOADED_ROOT_THREADS} and
 * {@link MAX_AUTO_SCANNED_THREADS}.
 */
export function canAutoLoadMoreThreads(
  rootThreads: readonly AgentThread[],
  loadedCount: number,
): boolean {
  if (loadedCount >= MAX_AUTO_SCANNED_THREADS) {
    return false;
  }
  let unpinned = 0;
  for (const thread of rootThreads) {
    if (!isThreadPinned(thread)) {
      unpinned += 1;
    }
  }
  return unpinned < MAX_AUTO_LOADED_ROOT_THREADS;
}
