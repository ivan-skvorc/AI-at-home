import { useQuery } from "@tanstack/react-query";

import { fetchThreadFiles } from "./api";
import type { ThreadFileListing } from "./types";

/** Every cached listing of one thread, for refreshing them all at once. */
export function threadFilesQueryPrefix(threadId: string | undefined) {
  return ["thread-files", threadId] as const;
}

export function threadFilesQueryKey(
  threadId: string | undefined,
  path: string,
) {
  return ["thread-files", threadId, path] as const;
}

/** One directory listing; the explorer mounts one per expanded directory. */
export function useThreadFiles(
  threadId: string | undefined,
  path: string,
  {
    enabled = true,
    refetchInterval = false,
  }: { enabled?: boolean; refetchInterval?: number | false } = {},
) {
  return useQuery<ThreadFileListing>({
    queryKey: threadFilesQueryKey(threadId, path),
    queryFn: ({ signal }) => {
      if (!threadId) {
        throw new Error("threadId is required");
      }
      return fetchThreadFiles({ threadId, path, signal });
    },
    enabled: enabled && Boolean(threadId),
    refetchInterval,
    // The explorer shows the failure with its own retry control.
    retry: false,
  });
}
