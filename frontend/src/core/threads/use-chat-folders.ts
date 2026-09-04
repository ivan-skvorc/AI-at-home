"use client";

/**
 * React state for the sidebar's chat folders (fork feature).
 *
 * The server list is the source of truth (see `chat-folders-api.ts`); this hook
 * owns the optimistic edit, the write-back, and the per-browser expanded set.
 * Every mutation replaces the whole list — it is at most
 * {@link MAX_CHAT_FOLDERS} short records, so a diffing protocol would buy
 * nothing and cost a merge conflict.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import {
  addFolder,
  CHAT_FOLDERS_EXPANDED_STORAGE_KEY,
  deserializeExpandedFolderIds,
  removeFolder,
  renameFolder,
  type ChatFolder,
} from "./chat-folders";
import { fetchChatFolders, saveChatFolders } from "./chat-folders-api";

export const CHAT_FOLDERS_QUERY_KEY = ["settings", "chat-folders"] as const;

const EMPTY_FOLDERS: readonly ChatFolder[] = [];

/** A random, collision-free folder id, with a fallback for insecure origins. */
export function newFolderId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  // `crypto.randomUUID` is unavailable on a plain-HTTP LAN deployment — the
  // fork's documented setup — so folders must still be creatable there.
  return `folder-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function readExpandedFolderIds(): Set<string> {
  if (typeof window === "undefined") {
    return new Set();
  }
  try {
    return deserializeExpandedFolderIds(
      window.localStorage.getItem(CHAT_FOLDERS_EXPANDED_STORAGE_KEY),
    );
  } catch {
    return new Set();
  }
}

export function useChatFolders() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: CHAT_FOLDERS_QUERY_KEY,
    // `fetchChatFolders` answers `null` for "unknown" (gateway unreachable).
    // Treat that as "no folders known yet" for rendering, but never write it
    // back — the mutations below always start from the last good list.
    queryFn: async () => (await fetchChatFolders()) ?? [],
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const folders = data ?? EMPTY_FOLDERS;

  const { mutate: persist } = useMutation({
    mutationFn: async (next: readonly ChatFolder[]) => saveChatFolders(next),
    onSuccess(stored) {
      // The server's normalized value is authoritative; a failed write (`null`)
      // leaves the optimistic list in place so the user's edit is not yanked
      // back on a transient error.
      if (stored) {
        queryClient.setQueryData(CHAT_FOLDERS_QUERY_KEY, stored);
      }
    },
  });

  const commit = useCallback(
    (next: readonly ChatFolder[]) => {
      if (next === folders) {
        return;
      }
      queryClient.setQueryData(CHAT_FOLDERS_QUERY_KEY, next);
      persist(next);
    },
    [folders, persist, queryClient],
  );

  // Expanded/collapsed is per browser, not per account: hydrate after mount so
  // SSR and the first client render agree, then mirror every change back.
  const [expandedFolderIds, setExpandedFolderIds] = useState<Set<string>>(
    () => new Set(),
  );
  useEffect(() => {
    setExpandedFolderIds(readExpandedFolderIds());
  }, []);

  const writeExpanded = useCallback((next: Set<string>) => {
    setExpandedFolderIds(next);
    try {
      window.localStorage.setItem(
        CHAT_FOLDERS_EXPANDED_STORAGE_KEY,
        JSON.stringify([...next]),
      );
    } catch {
      // A browser with storage blocked still gets working folders — the
      // expanded set just resets on reload.
    }
  }, []);

  const toggleFolderExpanded = useCallback(
    (folderId: string) => {
      const next = new Set(expandedFolderIds);
      if (!next.delete(folderId)) {
        next.add(folderId);
      }
      writeExpanded(next);
    },
    [expandedFolderIds, writeExpanded],
  );

  const expandFolder = useCallback(
    (folderId: string) => {
      if (expandedFolderIds.has(folderId)) {
        return;
      }
      writeExpanded(new Set(expandedFolderIds).add(folderId));
    },
    [expandedFolderIds, writeExpanded],
  );

  const createFolder = useCallback(
    (name: string) => {
      const id = newFolderId();
      const next = addFolder(folders, { id, name });
      if (next === folders) {
        return null;
      }
      commit(next);
      // A brand-new folder opens, so the drop the user is about to make has a
      // visible target.
      writeExpanded(new Set(expandedFolderIds).add(id));
      return id;
    },
    [commit, expandedFolderIds, folders, writeExpanded],
  );

  const rename = useCallback(
    (folderId: string, name: string) => {
      commit(renameFolder(folders, folderId, name));
    },
    [commit, folders],
  );

  const remove = useCallback(
    (folderId: string) => {
      commit(removeFolder(folders, folderId));
    },
    [commit, folders],
  );

  return {
    folders,
    expandedFolderIds,
    createFolder,
    renameFolder: rename,
    removeFolder: remove,
    toggleFolderExpanded,
    expandFolder,
  };
}
