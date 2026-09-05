"use client";

import {
  Download,
  FileJson,
  FileText,
  FolderInput,
  FolderPlus,
  MoreHorizontal,
  PanelTop,
  Pencil,
  Pin,
  PinOff,
  Share2,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { resetThreadChatAfterDelete } from "@/components/workspace/chats/use-thread-chat";
import { getAPIClient } from "@/core/api";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import {
  folderIdOfThread,
  groupThreadsByFolder,
  MAX_CHAT_FOLDERS,
  type ChatFolder,
} from "@/core/threads/chat-folders";
import { CHAT_TAB_DND_THREAD_MIME } from "@/core/threads/chat-tabs";
import { useMaybeChatTabs } from "@/core/threads/chat-tabs-context";
import { exportThread, type ThreadExportFormat } from "@/core/threads/export";
import {
  useDeleteThread,
  useInfiniteThreads,
  useMoveThreadToFolder,
  usePinThread,
  useRenameThread,
} from "@/core/threads/hooks";
import {
  flattenThreadBranches,
  type ThreadBranchEntry,
} from "@/core/threads/thread-branch-tree";
import {
  buildThreadListModel,
  canAutoLoadMoreThreads,
} from "@/core/threads/thread-list-model";
import type { AgentThread, AgentThreadState } from "@/core/threads/types";
import { useChatFolders } from "@/core/threads/use-chat-folders";
import {
  channelSourceOfThread,
  isThreadPinned,
  pathOfThread,
  titleOfThread,
} from "@/core/threads/utils";
import { env } from "@/env";
import { isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

import { ChatFolderRow } from "./chat-folder-row";
import { ThreadChannelIcon } from "./thread-channel-source";
import { VirtualThreadList } from "./thread-list-virtualizer";

type BranchList = {
  entriesById: Map<string, ThreadBranchEntry>;
  threads: AgentThread[];
};

/**
 * Project one partition of the side list into its branch lineage.
 *
 * Called per folder *after* the threads are partitioned, not once over the
 * whole list: a branch whose parent lives in a different folder simply renders
 * top-level in its own folder, which keeps the "a conversation appears exactly
 * once" rule intact without teaching the branch tree about folders.
 */
function buildBranchList(threads: readonly AgentThread[]): BranchList {
  const entries = flattenThreadBranches(threads);
  return {
    entriesById: new Map(
      entries.map((entry) => [entry.thread.thread_id, entry]),
    ),
    threads: entries.map((entry) => entry.thread),
  };
}

/** State for the create/rename folder dialog; `null` while it is closed. */
type FolderDialogState =
  | { mode: "create" }
  | { mode: "rename"; folder: ChatFolder };

export function RecentChatList() {
  const { t } = useI18n();
  const router = useRouter();
  const pathname = usePathname();
  const { thread_id: threadIdFromPath, agent_name: agentNameFromPath } =
    useParams<{
      thread_id: string;
      agent_name?: string;
    }>();
  const {
    data: infiniteThreads,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteThreads();
  const threadListModel = useMemo(
    () => buildThreadListModel(infiniteThreads?.pages ?? []),
    [infiniteThreads?.pages],
  );
  const { threads } = threadListModel;

  const {
    folders,
    expandedFolderIds,
    createFolder,
    renameFolder: renameChatFolder,
    removeFolder,
    toggleFolderExpanded,
    expandFolder,
  } = useChatFolders();

  // Partition first, then flatten each partition's branches. A chat inside a
  // folder is deliberately absent from the root list, and a chat pointing at a
  // folder that no longer exists falls back to the root list rather than
  // disappearing (see `groupThreadsByFolder`).
  const grouped = useMemo(
    () => groupThreadsByFolder(threads, folders),
    [folders, threads],
  );
  // The scroll sentinel pages against the *root* list, not the whole loaded set:
  // conversations filed into a folder are not rows here, and counting them used
  // to stop pagination while this list was still nearly empty. The loaded count
  // is the other half of the budget — it stops the search for root rows that a
  // fully filed-away history does not have.
  const canAutoLoadMore = useMemo(
    () => canAutoLoadMoreThreads(grouped.ungrouped, threads.length),
    [grouped.ungrouped, threads.length],
  );
  const rootList = useMemo(
    () => buildBranchList(grouped.ungrouped),
    [grouped.ungrouped],
  );
  const folderLists = useMemo(
    () =>
      grouped.groups.map((group) => ({
        folder: group.folder,
        list: buildBranchList(group.threads),
      })),
    [grouped.groups],
  );

  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = sentinelRef.current;
    if (!element || !hasNextPage || !canAutoLoadMore) {
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      { rootMargin: "120px 0px 120px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [canAutoLoadMore, fetchNextPage, hasNextPage, isFetchingNextPage]);

  const { mutate: deleteThread } = useDeleteThread();
  const { mutate: renameThread } = useRenameThread();
  const { mutate: updatePinnedThread } = usePinThread();
  const { mutate: moveThreadToFolder } = useMoveThreadToFolder();
  const chatTabs = useMaybeChatTabs();

  // Rename dialog state
  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameThreadId, setRenameThreadId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  // Create/rename folder dialog state
  const [folderDialog, setFolderDialog] = useState<FolderDialogState | null>(
    null,
  );
  const [folderNameValue, setFolderNameValue] = useState("");
  const [isRootDropTarget, setIsRootDropTarget] = useState(false);

  const handleDelete = useCallback(
    (thread: AgentThread) => {
      const currentPathname =
        typeof window === "undefined" ? pathname : window.location.pathname;
      const threadPath = pathOfThread(thread);
      const nextThreadPath = pathOfThread("new", {
        agent_name: agentNameFromPath,
      });
      const isNewThreadPath = currentPathname === nextThreadPath;
      const isCurrentThread =
        thread.thread_id === threadIdFromPath ||
        threadPath === currentPathname ||
        (isNewThreadPath && threads[0]?.thread_id === thread.thread_id);

      deleteThread({
        threadId: thread.thread_id,
        onRemoteDeleted: isCurrentThread
          ? () => {
              resetThreadChatAfterDelete({
                deletedThreadId: thread.thread_id,
                nextPath: nextThreadPath,
                force: true,
              });
              void router.replace(nextThreadPath);
            }
          : undefined,
      });
    },
    [
      agentNameFromPath,
      deleteThread,
      pathname,
      router,
      threadIdFromPath,
      threads,
    ],
  );

  const handleRenameClick = useCallback(
    (threadId: string, currentTitle: string) => {
      setRenameThreadId(threadId);
      setRenameValue(currentTitle);
      setRenameDialogOpen(true);
    },
    [],
  );

  const handleRenameSubmit = useCallback(() => {
    if (renameThreadId && renameValue.trim()) {
      renameThread(
        { threadId: renameThreadId, title: renameValue.trim() },
        {
          onSuccess: () => {
            setRenameDialogOpen(false);
            setRenameThreadId(null);
            setRenameValue("");
          },
          onError: (error) => {
            toast.error(
              error instanceof Error && error.message
                ? error.message
                : t.common.renameFailed,
            );
          },
        },
      );
    }
  }, [renameThread, renameThreadId, renameValue, t.common.renameFailed]);

  const handleTogglePin = useCallback(
    (thread: AgentThread) => {
      updatePinnedThread(
        {
          threadId: thread.thread_id,
          pinned: !isThreadPinned(thread),
        },
        {
          onError: (err) => {
            toast.error(
              err instanceof Error ? err.message : t.chats.pinChatFailed,
            );
          },
        },
      );
    },
    [t.chats.pinChatFailed, updatePinnedThread],
  );

  const handleMoveToFolder = useCallback(
    (threadId: string, folderId: string | null) => {
      const current = threadListModel.byId.get(threadId);
      if (current && folderIdOfThread(current) === folderId) {
        return;
      }
      if (folderId) {
        // The drop had a target the user could see; keep it visible so the
        // conversation does not appear to vanish into a collapsed folder.
        expandFolder(folderId);
      }
      moveThreadToFolder(
        { threadId, folderId },
        {
          onError: (err) => {
            toast.error(
              err instanceof Error && err.message
                ? err.message
                : t.chats.folders.moveFailed,
            );
          },
        },
      );
    },
    [
      expandFolder,
      moveThreadToFolder,
      t.chats.folders.moveFailed,
      threadListModel.byId,
    ],
  );

  const handleFolderDialogSubmit = useCallback(() => {
    const name = folderNameValue.trim();
    if (!folderDialog || !name) {
      return;
    }
    if (folderDialog.mode === "create") {
      if (createFolder(name) === null) {
        toast.error(t.chats.folders.limitReached(MAX_CHAT_FOLDERS));
        return;
      }
    } else {
      renameChatFolder(folderDialog.folder.id, name);
    }
    setFolderDialog(null);
    setFolderNameValue("");
  }, [
    createFolder,
    folderDialog,
    folderNameValue,
    renameChatFolder,
    t.chats.folders,
  ]);

  const handleDeleteFolder = useCallback(
    (folder: ChatFolder) => {
      // Conversations are never deleted with their folder. Clear the pointer on
      // the ones currently loaded so their metadata does not keep naming a
      // folder that is gone; anything not loaded is covered by the grouping
      // fallback, which lists an unknown folder id at the root.
      const members = threads.filter(
        (thread) => folderIdOfThread(thread) === folder.id,
      );
      removeFolder(folder.id);
      for (const thread of members) {
        moveThreadToFolder({ threadId: thread.thread_id, folderId: null });
      }
      toast.success(t.chats.folders.deleted(folder.name));
    },
    [moveThreadToFolder, removeFolder, t.chats.folders, threads],
  );

  const handleShare = useCallback(
    async (thread: AgentThread) => {
      // Always use Vercel URL for sharing so others can access
      const VERCEL_URL = "https://deer-flow-v2.vercel.app";
      const isLocalhost =
        window.location.hostname === "localhost" ||
        window.location.hostname === "127.0.0.1";
      // On localhost: use Vercel URL; On production: use current origin
      const baseUrl = isLocalhost ? VERCEL_URL : window.location.origin;
      const shareUrl = `${baseUrl}${pathOfThread(thread)}`;
      try {
        const didCopy = await writeTextToClipboard(shareUrl);
        if (!didCopy) {
          toast.error(t.clipboard.failedToCopyToClipboard);
          return;
        }

        toast.success(t.clipboard.linkCopied);
      } catch {
        toast.error(t.clipboard.failedToCopyToClipboard);
      }
    },
    [t],
  );

  const handleExport = useCallback(
    async (thread: AgentThread, format: ThreadExportFormat) => {
      try {
        const apiClient = getAPIClient();
        const state = await apiClient.threads.getState<AgentThreadState>(
          thread.thread_id,
        );
        const messages = state.values?.messages ?? [];
        if (messages.length === 0) {
          toast.error(t.conversation.noMessages);
          return;
        }
        exportThread(thread, messages, format);
        toast.success(t.common.exportSuccess);
      } catch {
        toast.error(t.common.exportFailed);
      }
    },
    [t],
  );

  const renderThreadRow = useCallback(
    (thread: AgentThread, branchList: BranchList) => {
      const isActive = pathOfThread(thread) === pathname;
      const channelSource = channelSourceOfThread(thread);
      const pinned = isThreadPinned(thread);
      const branchEntry = branchList.entriesById.get(thread.thread_id);
      const parentTitle = branchEntry?.parentThread
        ? titleOfThread(branchEntry.parentThread)
        : null;
      const title = titleOfThread(thread);
      const branchLabel = parentTitle
        ? t.chats.branchLabel(title, parentTitle)
        : undefined;
      const currentFolderId = folderIdOfThread(thread);
      return (
        <SidebarMenuItem
          key={thread.thread_id}
          className="group/side-menu-item"
        >
          <SidebarMenuButton isActive={isActive} asChild>
            <Link
              aria-label={branchLabel}
              className="text-muted-foreground min-w-0 whitespace-nowrap group-hover/side-menu-item:overflow-hidden"
              data-branch-depth={
                branchEntry && branchEntry.depth > 0
                  ? branchEntry.depth
                  : undefined
              }
              data-branch-parent-id={branchEntry?.parentThread?.thread_id}
              href={pathOfThread(thread)}
              // Always draggable: the same payload files the chat into a
              // sidebar folder and (when the feature is on) pins it as a
              // keep-alive tab, so one drag serves both drop targets.
              draggable
              onDragStart={(event) => {
                event.dataTransfer.setData(
                  CHAT_TAB_DND_THREAD_MIME,
                  thread.thread_id,
                );
                event.dataTransfer.setData("text/plain", titleOfThread(thread));
                event.dataTransfer.effectAllowed = "copyMove";
              }}
              title={branchLabel}
            >
              {branchEntry && branchEntry.depth > 0 && (
                <span
                  aria-hidden="true"
                  className="text-muted-foreground/70 shrink-0 font-mono text-[10px] leading-none"
                  data-testid="thread-branch-stem"
                  style={{
                    marginLeft: `${Math.min(branchEntry.depth - 1, 1) * 8}px`,
                  }}
                >
                  {branchEntry.isLastSibling ? "└─" : "├─"}
                </span>
              )}
              <ThreadChannelIcon source={channelSource} />
              {pinned && (
                <Pin
                  aria-hidden="true"
                  className="text-muted-foreground size-3.5 shrink-0"
                />
              )}
              <span className="min-w-0 truncate">{title}</span>
              {channelSource && (
                <span
                  className="bg-muted text-muted-foreground ml-auto inline-flex h-5 max-w-14 shrink-0 items-center rounded-md px-1.5 text-[10px] font-medium"
                  title={`${channelSource.label} channel`}
                >
                  <span className="truncate">{channelSource.label}</span>
                </span>
              )}
            </Link>
          </SidebarMenuButton>
          {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuAction
                  showOnHover
                  className="bg-background/50 hover:bg-background after:left-0!"
                >
                  <MoreHorizontal />
                  <span className="sr-only">{t.common.more}</span>
                </SidebarMenuAction>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className="w-48 rounded-lg"
                side={"right"}
                align={"start"}
              >
                {chatTabs?.enabled && (
                  <DropdownMenuItem
                    onSelect={() => {
                      chatTabs.pinThread(
                        thread.thread_id,
                        titleOfThread(thread),
                      );
                      // Sync the URL to the pinned tab without a
                      // Next navigation (keep-alive: no remount).
                      window.history.replaceState(
                        null,
                        "",
                        pathOfThread(thread),
                      );
                    }}
                  >
                    <PanelTop className="text-muted-foreground" />
                    <span>{t.chatTabs.openInTab}</span>
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onSelect={() => handleTogglePin(thread)}>
                  {pinned ? (
                    <PinOff className="text-muted-foreground" />
                  ) : (
                    <Pin className="text-muted-foreground" />
                  )}
                  <span>{pinned ? t.chats.unpinChat : t.chats.pinChat}</span>
                </DropdownMenuItem>
                {/* Keyboard-reachable equivalent of the drag: drag-and-drop is
                    the fast path, not the only path. */}
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>
                    <FolderInput className="text-muted-foreground" />
                    <span>{t.chats.folders.moveTo}</span>
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    {folders.map((folder) => (
                      <DropdownMenuItem
                        key={folder.id}
                        disabled={folder.id === currentFolderId}
                        onSelect={() =>
                          handleMoveToFolder(thread.thread_id, folder.id)
                        }
                      >
                        <span className="truncate">{folder.name}</span>
                      </DropdownMenuItem>
                    ))}
                    {folders.length > 0 && <DropdownMenuSeparator />}
                    <DropdownMenuItem
                      disabled={currentFolderId === null}
                      onSelect={() =>
                        handleMoveToFolder(thread.thread_id, null)
                      }
                    >
                      <span>{t.chats.folders.none}</span>
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onSelect={() => {
                        setFolderNameValue("");
                        setFolderDialog({ mode: "create" });
                      }}
                    >
                      <FolderPlus className="text-muted-foreground" />
                      <span>{t.chats.folders.new}</span>
                    </DropdownMenuItem>
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuItem
                  onSelect={() =>
                    handleRenameClick(thread.thread_id, titleOfThread(thread))
                  }
                >
                  <Pencil className="text-muted-foreground" />
                  <span>{t.common.rename}</span>
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => handleShare(thread)}>
                  <Share2 className="text-muted-foreground" />
                  <span>{t.common.share}</span>
                </DropdownMenuItem>
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>
                    <Download className="text-muted-foreground" />
                    <span>{t.common.export}</span>
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    <DropdownMenuItem
                      onSelect={() => handleExport(thread, "markdown")}
                    >
                      <FileText className="text-muted-foreground" />
                      <span>{t.common.exportAsMarkdown}</span>
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={() => handleExport(thread, "json")}
                    >
                      <FileJson className="text-muted-foreground" />
                      <span>{t.common.exportAsJSON}</span>
                    </DropdownMenuItem>
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => handleDelete(thread)}>
                  <Trash2 className="text-muted-foreground" />
                  <span>{t.common.delete}</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </SidebarMenuItem>
      );
    },
    [
      chatTabs,
      folders,
      handleDelete,
      handleExport,
      handleMoveToFolder,
      handleRenameClick,
      handleShare,
      handleTogglePin,
      pathname,
      t,
    ],
  );

  const handleRootDragOver = useCallback((event: React.DragEvent) => {
    if (!event.dataTransfer.types.includes(CHAT_TAB_DND_THREAD_MIME)) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setIsRootDropTarget(true);
  }, []);

  const handleRootDrop = useCallback(
    (event: React.DragEvent) => {
      const threadId = event.dataTransfer.getData(CHAT_TAB_DND_THREAD_MIME);
      setIsRootDropTarget(false);
      if (!threadId) {
        return;
      }
      event.preventDefault();
      handleMoveToFolder(threadId, null);
    },
    [handleMoveToFolder],
  );

  // A folder with nothing in it is still a folder: keep the group rendered so
  // it does not disappear the moment it is created on an empty workspace.
  if (threads.length === 0 && folders.length === 0) {
    return null;
  }
  const isStaticWebsite = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
  return (
    <>
      <SidebarGroup>
        <SidebarGroupLabel>
          {!isStaticWebsite ? t.sidebar.recentChats : t.sidebar.demoChats}
        </SidebarGroupLabel>
        {!isStaticWebsite && (
          <SidebarGroupAction
            data-testid="chat-folder-create"
            onClick={() => {
              setFolderNameValue("");
              setFolderDialog({ mode: "create" });
            }}
            title={t.chats.folders.new}
          >
            <FolderPlus />
            <span className="sr-only">{t.chats.folders.new}</span>
          </SidebarGroupAction>
        )}
        <SidebarGroupContent className="group-data-[collapsible=icon]:pointer-events-none group-data-[collapsible=icon]:-mt-8 group-data-[collapsible=icon]:opacity-0">
          <SidebarMenu>
            {folderLists.length > 0 && (
              <div
                className="flex w-full flex-col gap-1 pb-1"
                data-testid="chat-folder-list"
              >
                {folderLists.map(({ folder, list }) => {
                  const isExpanded = expandedFolderIds.has(folder.id);
                  return (
                    <div key={folder.id} className="flex w-full flex-col gap-1">
                      <ChatFolderRow
                        count={list.threads.length}
                        folder={folder}
                        isExpanded={isExpanded}
                        onDelete={() => handleDeleteFolder(folder)}
                        onDropThread={(threadId) =>
                          handleMoveToFolder(threadId, folder.id)
                        }
                        onRename={() => {
                          setFolderNameValue(folder.name);
                          setFolderDialog({ mode: "rename", folder });
                        }}
                        onToggle={() => toggleFolderExpanded(folder.id)}
                      />
                      {isExpanded && (
                        <div
                          className="border-sidebar-border ml-3 flex w-[calc(100%-0.75rem)] flex-col gap-1 border-l pl-1"
                          data-folder-id={folder.id}
                          data-testid="chat-folder-children"
                          onDragOver={(event) => {
                            if (
                              !event.dataTransfer.types.includes(
                                CHAT_TAB_DND_THREAD_MIME,
                              )
                            ) {
                              return;
                            }
                            event.preventDefault();
                            event.dataTransfer.dropEffect = "move";
                          }}
                          onDrop={(event) => {
                            const threadId = event.dataTransfer.getData(
                              CHAT_TAB_DND_THREAD_MIME,
                            );
                            if (!threadId) {
                              return;
                            }
                            event.preventDefault();
                            handleMoveToFolder(threadId, folder.id);
                          }}
                        >
                          {list.threads.length === 0 ? (
                            <p className="text-muted-foreground/70 px-2 py-1 text-xs">
                              {t.chats.folders.empty}
                            </p>
                          ) : (
                            <VirtualThreadList
                              estimateSize={36}
                              gap={4}
                              items={list.threads}
                              scrollParentSelector='[data-sidebar="content"]'
                              renderItem={(thread) =>
                                renderThreadRow(thread, list)
                              }
                            />
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            {/* Keep pagination at the old list boundary when this switches to virtual rows. */}
            <div
              className={cn(
                "flex w-full flex-col gap-1 rounded-md",
                isRootDropTarget && "bg-sidebar-accent/50",
              )}
              data-testid="chat-root-list"
              onDragOver={handleRootDragOver}
              onDragLeave={() => setIsRootDropTarget(false)}
              onDrop={handleRootDrop}
              style={{ overflowAnchor: "none" }}
            >
              <VirtualThreadList
                estimateSize={36}
                gap={4}
                items={rootList.threads}
                scrollParentSelector='[data-sidebar="content"]'
                renderItem={(thread) => renderThreadRow(thread, rootList)}
              />
              {rootList.threads.length === 0 && folderLists.length > 0 && (
                <p
                  className="text-muted-foreground/70 border-sidebar-border mx-2 my-1 rounded-md border border-dashed px-2 py-3 text-center text-xs"
                  data-testid="chat-root-list-empty-hint"
                >
                  {t.chats.folders.rootDropHint}
                </p>
              )}
              {/* The button follows the backend, the sentinel follows the
                  budget: past it the list stops chasing pages on its own, but
                  older conversations stay one click away rather than becoming
                  unreachable. */}
              {hasNextPage && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mx-2 my-1 w-[calc(100%-1rem)] justify-center text-xs"
                    onClick={() => void fetchNextPage()}
                    disabled={isFetchingNextPage}
                    data-testid="recent-chat-list-load-more"
                  >
                    {isFetchingNextPage
                      ? t.chats.loadingMore
                      : t.chats.loadOlderChats}
                  </Button>
                  {canAutoLoadMore && (
                    <div
                      ref={sentinelRef}
                      aria-hidden="true"
                      className="h-px w-full"
                      data-testid="recent-chat-list-sentinel"
                    />
                  )}
                </>
              )}
            </div>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>

      {/* Rename Dialog */}
      <Dialog open={renameDialogOpen} onOpenChange={setRenameDialogOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.common.rename}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Input
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              placeholder={t.common.rename}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !isIMEComposing(e)) {
                  e.preventDefault();
                  handleRenameSubmit();
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRenameDialogOpen(false)}
            >
              {t.common.cancel}
            </Button>
            <Button onClick={handleRenameSubmit}>{t.common.save}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create / rename folder dialog */}
      <Dialog
        open={folderDialog !== null}
        onOpenChange={(open) => {
          if (!open) {
            setFolderDialog(null);
            setFolderNameValue("");
          }
        }}
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>
              {folderDialog?.mode === "rename"
                ? t.chats.folders.rename
                : t.chats.folders.new}
            </DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Input
              autoFocus
              data-testid="chat-folder-name-input"
              value={folderNameValue}
              onChange={(e) => setFolderNameValue(e.target.value)}
              placeholder={t.chats.folders.namePlaceholder}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !isIMEComposing(e)) {
                  e.preventDefault();
                  handleFolderDialogSubmit();
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setFolderDialog(null);
                setFolderNameValue("");
              }}
            >
              {t.common.cancel}
            </Button>
            <Button
              disabled={folderNameValue.trim().length === 0}
              onClick={handleFolderDialogSubmit}
            >
              {t.common.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
