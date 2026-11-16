import { useQuery } from "@tanstack/react-query";

import { fetchFolderDetail, fetchThreadFolders } from "./api";
import type { LedgerFolderDetail, ThreadFolders } from "./types";

/** Every folder-ledger query, for refreshing them all after a change. */
export const FOLDER_LEDGER_QUERY_PREFIX = ["folder-ledger"] as const;

export function threadFoldersQueryKey(threadId: string | undefined) {
  return [...FOLDER_LEDGER_QUERY_PREFIX, "thread", threadId] as const;
}

export function folderDetailQueryKey(folderId: string | null) {
  return [...FOLDER_LEDGER_QUERY_PREFIX, "folder", folderId] as const;
}

/** The shared folders one conversation created, edited or inherited. */
export function useThreadFolders(
  threadId: string | undefined,
  { enabled = true }: { enabled?: boolean } = {},
) {
  return useQuery<ThreadFolders>({
    queryKey: threadFoldersQueryKey(threadId),
    queryFn: ({ signal }) => {
      if (!threadId) {
        throw new Error("threadId is required");
      }
      return fetchThreadFolders(threadId, { signal });
    },
    enabled: enabled && Boolean(threadId),
    // The section shows the failure with its own retry control.
    retry: false,
  });
}

/** One folder's detail: the conversations involved and its edit log. */
export function useFolderDetail(
  folderId: string | null,
  { enabled = true }: { enabled?: boolean } = {},
) {
  return useQuery<LedgerFolderDetail>({
    queryKey: folderDetailQueryKey(folderId),
    queryFn: ({ signal }) => {
      if (!folderId) {
        throw new Error("folderId is required");
      }
      return fetchFolderDetail(folderId, { signal });
    },
    enabled: enabled && Boolean(folderId),
    retry: false,
  });
}
