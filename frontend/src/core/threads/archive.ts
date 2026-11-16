import { useMutation, useQueryClient } from "@tanstack/react-query";

import { PROJECTS_QUERY_KEY } from "../projects/api";

import { patchThreadMetadata, type ThreadMetadataPatchResponse } from "./api";
import {
  BULK_THREAD_CONCURRENCY,
  partitionBulkResults,
  settleWithConcurrency,
  uniqueThreadIds,
  type BulkThreadResult,
} from "./bulk";
import {
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  setThreadMetadataInCaches,
} from "./hooks";
import { THREAD_ARCHIVED_METADATA_KEY } from "./utils";

export type ArchiveThreadVariables = {
  threadId: string;
  archived: boolean;
};

export type ArchiveThreadOptions = {
  onSuccess?: (
    data: ThreadMetadataPatchResponse,
    variables: ArchiveThreadVariables,
  ) => void;
  onError?: (error: Error, variables: ArchiveThreadVariables) => void;
};

export function useArchiveThread(options: ArchiveThreadOptions = {}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ threadId, archived }: ArchiveThreadVariables) =>
      patchThreadMetadata(threadId, {
        [THREAD_ARCHIVED_METADATA_KEY]: archived,
      }),
    // The callback is registered at the mutation level, not per `mutate` call:
    // per-call handlers are dropped when the originating row unmounts (the
    // archived chat leaves the sidebar list mid-flight), which silently lost
    // the success toast before.
    async onSuccess(_response, { threadId, archived }) {
      // A response started before the write must not put the old state back.
      await Promise.all([
        queryClient.cancelQueries({
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
        }),
        queryClient.cancelQueries({ queryKey: ["threads", "search"] }),
        queryClient.cancelQueries({
          queryKey: ["thread", "metadata", threadId],
        }),
      ]);
      setThreadMetadataInCaches(queryClient, threadId, {
        [THREAD_ARCHIVED_METADATA_KEY]: archived,
      });
      // Membership changed, so discard old offsets in both views. The current
      // conversation snapshot stays mounted and its files remain accessible.
      await Promise.all([
        queryClient.resetQueries({
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
        }),
        queryClient.invalidateQueries({ queryKey: ["threads", "search"] }),
        queryClient.invalidateQueries({
          queryKey: ["thread", "metadata", threadId],
        }),
        // The project page's own thread list
        // ([...PROJECTS_QUERY_KEY, "threads", id, ...]) changes membership
        // with the archive flag; every other thread mutation (pin, rename,
        // delete, move, stop) invalidates this prefix, so archive must too.
        queryClient.invalidateQueries({
          queryKey: [...PROJECTS_QUERY_KEY, "threads"],
        }),
      ]);
      options.onSuccess?.(_response, { threadId, archived });
    },
    onError: (error, variables) => {
      options.onError?.(error, variables);
    },
  });
}

export type ArchiveThreadsVariables = {
  threadIds: readonly string[];
  archived: boolean;
};

export type ArchiveThreadsOptions = {
  /** Fires once per batch, after the lists were reset — also on a partial failure. */
  onSettled?: (
    result: BulkThreadResult,
    variables: ArchiveThreadsVariables,
  ) => void;
};

/**
 * Archive (or restore) several conversations — the bulk form of
 * {@link useArchiveThread}.
 *
 * The single hook resets the whole infinite list after every write; N of
 * those would drop and refetch every loaded page N times. This one writes a
 * few at a time, applies each success to the caches, and resets the lists
 * once. A failed item is reported in the result, never retried. Like the
 * single hook, the callback is registered at the hook level: the archived
 * rows leave the sidebar mid-flight, and a per-`mutate` callback registered
 * from one of them would be dropped with it.
 */
export function useArchiveThreads(options: ArchiveThreadsOptions = {}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      threadIds,
      archived,
    }: ArchiveThreadsVariables): Promise<BulkThreadResult> => {
      const ids = uniqueThreadIds(threadIds);
      const results = await settleWithConcurrency(
        ids,
        BULK_THREAD_CONCURRENCY,
        (threadId) =>
          patchThreadMetadata(threadId, {
            [THREAD_ARCHIVED_METADATA_KEY]: archived,
          }),
      );
      return partitionBulkResults(ids, results);
    },
    async onSuccess(result, variables) {
      const { succeeded } = result;
      if (succeeded.length > 0) {
        await Promise.all([
          queryClient.cancelQueries({
            queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
          }),
          queryClient.cancelQueries({ queryKey: ["threads", "search"] }),
          ...succeeded.map((threadId) =>
            queryClient.cancelQueries({
              queryKey: ["thread", "metadata", threadId],
            }),
          ),
        ]);
        for (const threadId of succeeded) {
          setThreadMetadataInCaches(queryClient, threadId, {
            [THREAD_ARCHIVED_METADATA_KEY]: variables.archived,
          });
        }
        await Promise.all([
          queryClient.resetQueries({
            queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
          }),
          queryClient.invalidateQueries({ queryKey: ["threads", "search"] }),
          ...succeeded.map((threadId) =>
            queryClient.invalidateQueries({
              queryKey: ["thread", "metadata", threadId],
            }),
          ),
          queryClient.invalidateQueries({
            queryKey: [...PROJECTS_QUERY_KEY, "threads"],
          }),
        ]);
      }
      options.onSettled?.(result, variables);
    },
  });
}
