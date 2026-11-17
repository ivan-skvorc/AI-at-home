"use client";

/**
 * React state for the sidebar's chat folders (fork feature: a folder *tree* —
 * folders nest, see `chat-folders.ts` for the rules that keep it a forest).
 *
 * The server list is the source of truth (see `chat-folders-api.ts`); this hook
 * owns the optimistic edit, the write-back, and the per-browser expanded set.
 * Every mutation replaces the whole list — it is at most
 * {@link MAX_CHAT_FOLDERS} short records, so a diffing protocol would buy
 * nothing and cost a merge conflict.
 */

import {
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  addFolder,
  CHAT_FOLDERS_EXPANDED_STORAGE_KEY,
  deserializeExpandedFolderIds,
  folderSubtreeIds,
  moveFolder,
  removeFolder,
  renameFolder,
  type ChatFolder,
} from "./chat-folders";
import { fetchChatFolders, saveChatFolders } from "./chat-folders-api";

export const CHAT_FOLDERS_QUERY_KEY = ["settings", "chat-folders"] as const;

/**
 * Mutation scope of every whole-list folder write. TanStack runs mutations that
 * share a scope one after another, so PUTs land in the order they were made.
 * Exported for any other writer of the list (clean-up mode's apply step), which
 * must queue behind the sidebar's writes rather than race them.
 */
export const CHAT_FOLDERS_MUTATION_SCOPE = "chat-folders";

const EMPTY_FOLDERS: readonly ChatFolder[] = [];

/**
 * The number of the latest folder edit, per query client, shared by every
 * mounted `useChatFolders`. A write's response is applied only while its edit
 * is still the latest one. The cache cannot answer that by identity: React
 * Query structurally shares `setQueryData`, so the cache holds a copy of the
 * list an edit wrote, never the array itself.
 */
const latestFolderEdit = new WeakMap<QueryClient, number>();

function nextFolderEdit(queryClient: QueryClient): number {
  const edit = (latestFolderEdit.get(queryClient) ?? 0) + 1;
  latestFolderEdit.set(queryClient, edit);
  return edit;
}

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

  // Every edit starts from the list in the query cache, not from `folders`:
  // the render closure goes stale the moment one handler makes a second edit,
  // so two folders created in one go used to compute the second from the old
  // list and overwrite the first. The cache already holds the first one.
  const readFolders = useCallback(
    (): readonly ChatFolder[] =>
      queryClient.getQueryData<readonly ChatFolder[]>(CHAT_FOLDERS_QUERY_KEY) ??
      EMPTY_FOLDERS,
    [queryClient],
  );

  const { mutate: persist } = useMutation({
    mutationFn: async ({
      next,
    }: {
      next: readonly ChatFolder[];
      edit: number;
    }) => saveChatFolders(next),
    // One write at a time, in order. Two whole-list PUTs racing could resolve
    // out of order, and the older response would then overwrite the newer
    // list in `onSuccess` below.
    scope: { id: CHAT_FOLDERS_MUTATION_SCOPE },
    onSuccess(stored, { edit }) {
      // The server's normalized value is authoritative, and it also repairs
      // the cache when a list read landed on top of the optimistic edit. A
      // failed write (`null`) leaves the optimistic list in place so the
      // user's edit is not yanked back on a transient error. Applied only for
      // the latest edit: after a newer one, the response describes an older
      // list, and showing it would make the newer folder blink out until its
      // own write lands.
      if (stored && edit === latestFolderEdit.get(queryClient)) {
        queryClient.setQueryData(CHAT_FOLDERS_QUERY_KEY, stored);
      }
    },
  });

  const commit = useCallback(
    (current: readonly ChatFolder[], next: readonly ChatFolder[]) => {
      if (next === current) {
        return;
      }
      const edit = nextFolderEdit(queryClient);
      // A list read already in flight answers with the list before this edit;
      // landing after it, it would drop the new folder, and the next edit
      // would then save the list without it. Cancelling reverts that read at
      // once, so the optimistic write below is the last word.
      void queryClient.cancelQueries({ queryKey: CHAT_FOLDERS_QUERY_KEY });
      queryClient.setQueryData(CHAT_FOLDERS_QUERY_KEY, next);
      persist({ next, edit });
    },
    [persist, queryClient],
  );

  // Expanded/collapsed is per browser, not per account: hydrate after mount so
  // SSR and the first client render agree, then mirror every change back. The
  // ref is the same fix as `readFolders`: a handler that creates a folder and
  // then expands its target must see the first write.
  const [expandedFolderIds, setExpandedFolderIds] = useState<Set<string>>(
    () => new Set(),
  );
  const expandedRef = useRef<ReadonlySet<string>>(expandedFolderIds);
  useEffect(() => {
    const stored = readExpandedFolderIds();
    expandedRef.current = stored;
    setExpandedFolderIds(stored);
  }, []);

  const writeExpanded = useCallback((next: Set<string>) => {
    expandedRef.current = next;
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
      const next = new Set(expandedRef.current);
      if (!next.delete(folderId)) {
        next.add(folderId);
      }
      writeExpanded(next);
    },
    [writeExpanded],
  );

  const expandFolder = useCallback(
    (folderId: string) => {
      if (expandedRef.current.has(folderId)) {
        return;
      }
      writeExpanded(new Set(expandedRef.current).add(folderId));
    },
    [writeExpanded],
  );

  /**
   * Create several folders in one write, all under `parentId`, answering one
   * entry per name: the new id, or `null` for a name the model refused (blank,
   * over the {@link MAX_CHAT_FOLDERS} cap, or nested too deep). A refusal does
   * not stop the names after it — a blank one in the middle still lets the
   * rest through.
   */
  const createFolders = useCallback(
    (
      names: readonly string[],
      parentId: string | null = null,
    ): Array<string | null> => {
      const current = readFolders();
      let next = current;
      const ids = names.map((name) => {
        const id = newFolderId();
        const added = addFolder(next, { id, name, parentId });
        if (added === next) {
          return null;
        }
        next = added;
        return id;
      });
      if (next === current) {
        return ids;
      }
      commit(current, next);
      // A brand-new folder opens, so the drop the user is about to make has a
      // visible target — and so does the folder it was created inside, or the
      // new subfolder would be created into a collapsed row and look like
      // nothing happened.
      const expanded = new Set(expandedRef.current);
      for (const id of ids) {
        if (id) {
          expanded.add(id);
        }
      }
      if (parentId) {
        expanded.add(parentId);
      }
      writeExpanded(expanded);
      return ids;
    },
    [commit, readFolders, writeExpanded],
  );

  const createFolder = useCallback(
    (name: string, parentId: string | null = null) =>
      createFolders([name], parentId)[0] ?? null,
    [createFolders],
  );

  const rename = useCallback(
    (folderId: string, name: string) => {
      const current = readFolders();
      commit(current, renameFolder(current, folderId, name));
    },
    [commit, readFolders],
  );

  /**
   * Delete a folder and the folders inside it, answering with every id that
   * went — the caller clears `deerflow_folder` on the conversations that named
   * any of them, so a chat two levels down comes back to the root list rather
   * than pointing at a folder nobody can see.
   */
  const remove = useCallback(
    (folderId: string) => {
      const current = readFolders();
      const removedIds = folderSubtreeIds(current, folderId);
      commit(current, removeFolder(current, folderId));
      return removedIds;
    },
    [commit, readFolders],
  );

  const move = useCallback(
    (folderId: string, parentId: string | null) => {
      const current = readFolders();
      const next = moveFolder(current, folderId, parentId);
      if (next === current) {
        return false;
      }
      commit(current, next);
      if (parentId) {
        // Same reason a new subfolder opens its parent: a folder dragged into a
        // collapsed row would simply vanish from the tree.
        writeExpanded(new Set(expandedRef.current).add(parentId));
      }
      return true;
    },
    [commit, readFolders, writeExpanded],
  );

  return {
    folders,
    expandedFolderIds,
    createFolder,
    createFolders,
    renameFolder: rename,
    removeFolder: remove,
    moveFolder: move,
    toggleFolderExpanded,
    expandFolder,
  };
}
