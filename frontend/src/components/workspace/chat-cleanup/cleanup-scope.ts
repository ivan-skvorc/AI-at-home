/**
 * Which conversations a clean-up pass reads.
 *
 * "All conversations" pages through the same thread search the sidebar uses
 * (unarchived, sidecars and hidden edit versions filtered out) and stops at
 * {@link MAX_ORGANIZE_THREADS}. A selection is resolved from the thread caches
 * the sidebar already holds, so selecting fifty rows does not cost fifty
 * requests; only an id no cache knows is fetched, and one that is gone is
 * reported rather than silently dropped.
 */

import type { QueryClient } from "@tanstack/react-query";

import { getAPIClient } from "@/core/api";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import {
  BULK_THREAD_CONCURRENCY,
  settleWithConcurrency,
  uniqueThreadIds,
} from "@/core/threads/bulk";
import {
  MAX_ORGANIZE_THREADS,
  toOrganizeThreadInfo,
  type OrganizeThreadInfo,
} from "@/core/threads/chat-organize";
import {
  fetchInfiniteThreadsPage,
  INFINITE_THREADS_PAGE_SIZE,
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  type InfiniteThreadsData,
} from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

export type CleanupScope = {
  threads: OrganizeThreadInfo[];
  /** More conversations exist than the pass takes. */
  capped: boolean;
  /** Selected ids no longer found. */
  missing: string[];
};

type ScopeClient = Pick<ReturnType<typeof getAPIClient>, "threads">;

function throwIfAborted(signal: AbortSignal | undefined) {
  if (signal?.aborted) {
    throw new DOMException("The scope load was cancelled.", "AbortError");
  }
}

/** A thread the sidebar's caches already hold, newest cache first. */
export function findCachedThread(
  queryClient: QueryClient,
  threadId: string,
): AgentThread | null {
  for (const [, data] of queryClient.getQueriesData<InfiniteThreadsData>({
    queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
  })) {
    for (const page of data?.pages ?? []) {
      const found = page.threads?.find(
        (thread) => thread.thread_id === threadId,
      );
      if (found) {
        return found;
      }
    }
  }
  for (const [, data] of queryClient.getQueriesData<AgentThread[]>({
    queryKey: ["threads", "search"],
  })) {
    const found = Array.isArray(data)
      ? data.find((thread) => thread.thread_id === threadId)
      : undefined;
    if (found) {
      return found;
    }
  }
  const metadata = queryClient.getQueriesData<AgentThread | null>({
    queryKey: ["thread", "metadata", threadId],
  });
  for (const [, data] of metadata) {
    if (data?.thread_id === threadId) {
      return data;
    }
  }
  return null;
}

/** Every conversation the sidebar lists, most recent first, up to the cap. */
export async function loadAllConversations({
  apiClient = getAPIClient(),
  signal,
  max = MAX_ORGANIZE_THREADS,
}: {
  apiClient?: ScopeClient;
  signal?: AbortSignal;
  max?: number;
} = {}): Promise<CleanupScope> {
  const params = { archived: isStaticWebsiteOnly() ? undefined : false };
  const seen = new Set<string>();
  const threads: OrganizeThreadInfo[] = [];
  let offset = 0;
  let hasMore = true;
  while (hasMore && threads.length < max) {
    throwIfAborted(signal);
    const page = await fetchInfiniteThreadsPage(
      apiClient,
      params,
      offset,
      INFINITE_THREADS_PAGE_SIZE,
    );
    for (const thread of page.threads) {
      if (!seen.has(thread.thread_id)) {
        seen.add(thread.thread_id);
        threads.push(toOrganizeThreadInfo(thread));
      }
    }
    offset += page.threads.length + page.hiddenCount;
    hasMore = page.hasMore && page.threads.length + page.hiddenCount > 0;
  }
  throwIfAborted(signal);
  return {
    threads: threads.slice(0, max),
    capped: threads.length > max || (hasMore && threads.length >= max),
    missing: [],
  };
}

/** The selected conversations, from the caches first, fetched when unknown. */
export async function loadSelectedConversations({
  threadIds,
  queryClient,
  apiClient = getAPIClient(),
  signal,
  max = MAX_ORGANIZE_THREADS,
}: {
  threadIds: readonly string[];
  queryClient: QueryClient;
  apiClient?: ScopeClient;
  signal?: AbortSignal;
  max?: number;
}): Promise<CleanupScope> {
  const unique = uniqueThreadIds(threadIds);
  const ids = unique.slice(0, max);
  const known = new Map<string, AgentThread>();
  const unknown: string[] = [];
  for (const id of ids) {
    const cached = findCachedThread(queryClient, id);
    if (cached) {
      known.set(id, cached);
    } else {
      unknown.push(id);
    }
  }
  if (unknown.length > 0) {
    throwIfAborted(signal);
    const fetched = await settleWithConcurrency(
      unknown,
      BULK_THREAD_CONCURRENCY,
      async (id) => (await apiClient.threads.get(id)) as AgentThread,
    );
    fetched.forEach((result, index) => {
      if (result.status === "fulfilled" && result.value?.thread_id) {
        known.set(unknown[index]!, result.value);
      }
    });
  }
  throwIfAborted(signal);
  const threads: OrganizeThreadInfo[] = [];
  const missing: string[] = [];
  for (const id of ids) {
    const thread = known.get(id);
    if (thread) {
      threads.push(toOrganizeThreadInfo(thread));
    } else {
      missing.push(id);
    }
  }
  return { threads, capped: unique.length > max, missing };
}
