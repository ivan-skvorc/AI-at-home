"use client";

import {
  Archive,
  ChevronDown,
  FolderInput,
  FolderPlus,
  ListChecks,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/core/auth/AuthProvider";
import { hasPermission, PERMISSIONS } from "@/core/auth/permissions";
import { useI18n } from "@/core/i18n/hooks";
import type { BulkThreadResult } from "@/core/threads/bulk";
import type { ChatFolder } from "@/core/threads/chat-folders";
import type { AgentThread } from "@/core/threads/types";

import {
  useSidebarSelection,
  useSidebarSelectionState,
} from "./sidebar-selection";
import { useThreadsArchiveAction } from "./use-thread-archive-action";

export type SelectionFolderTarget = {
  folder: ChatFolder;
  /** 1 for a top-level folder; each level indents the menu entry. */
  depth: number;
};

/**
 * The bar the sidebar shows while selecting: how many chats are ticked, and
 * what can be done with them.
 *
 * Rendered by `RecentChatList`, which owns the folder tree, the folder dialog
 * and the move handler; the selection itself, the delete confirmation and the
 * clean-up dialog belong to `SidebarSelectionProvider`. Every action is a
 * button or a menu entry, so all of it works from the keyboard — a drag is
 * never the only path. The count includes chats ticked inside a folder that
 * has since collapsed: they are still selected, just out of sight.
 */
export function SidebarSelectionToolbar({
  folderTargets,
  threadsById,
  recentThreadId,
  isMoving,
  onMoveToFolder,
  onNewFolderFromSelection,
}: {
  folderTargets: readonly SelectionFolderTarget[];
  threadsById: ReadonlyMap<string, AgentThread>;
  recentThreadId: string | undefined;
  isMoving: boolean;
  onMoveToFolder: (
    threadIds: readonly string[],
    folder: ChatFolder | null,
  ) => void;
  onNewFolderFromSelection: (threadIds: readonly string[]) => void;
}) {
  const { t } = useI18n();
  const { user } = useAuth();
  const api = useSidebarSelection();
  const { selection } = useSidebarSelectionState();
  const count = selection.ids.size;
  const canDelete = hasPermission(user, PERMISSIONS.THREADS_DELETE);

  const handleArchiveSettled = useCallback(
    ({ succeeded }: BulkThreadResult, archived: boolean) => {
      // The toast's Undo restores through the same mutation; that restore is
      // not a selection action and leaves the current ticks alone. Failures
      // stay ticked; rows ticked meanwhile stay ticked too.
      if (archived) {
        api?.store.remove(succeeded);
      }
    },
    [api],
  );
  const archive = useThreadsArchiveAction({ onSettled: handleArchiveSettled });

  if (!api) {
    return null;
  }
  // Read when an action runs, in sidebar order, so the dialogs list the
  // chats the way the user sees them rather than in the order they were ticked.
  const selectedIds = () => api.store.selectedIdsInOrder();

  const busy = isMoving || archive.isPending;
  const nothingSelected = count === 0;

  return (
    <div
      aria-label={t.chats.selection.toolbarLabel}
      className="bg-sidebar border-sidebar-border sticky top-0 z-10 mx-2 mb-2 flex flex-col gap-1.5 rounded-md border p-1.5"
      data-testid="chat-selection-toolbar"
      role="toolbar"
    >
      <div className="flex min-w-0 items-center gap-1">
        <span
          aria-live="polite"
          className="text-sidebar-foreground min-w-0 flex-1 truncate px-1 text-xs font-medium"
          data-testid="chat-selection-count"
        >
          {t.chats.selection.count(count)}
        </span>
        <Button
          className="h-7 px-2 text-xs"
          data-testid="chat-selection-select-all"
          onClick={() => api.store.selectAll()}
          size="sm"
          title={t.chats.selection.selectAllHint}
          variant="ghost"
        >
          <ListChecks />
          {t.chats.selection.selectAll}
        </Button>
        <Button
          aria-label={t.common.cancel}
          className="size-7"
          data-testid="chat-selection-cancel"
          onClick={() => api.store.exit()}
          size="icon"
          title={t.common.cancel}
          variant="ghost"
        >
          <X />
        </Button>
      </div>
      {nothingSelected && (
        <p className="text-muted-foreground px-1 text-xs">
          {t.chats.selection.emptyHint}
        </p>
      )}
      <div className="flex flex-wrap gap-1">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              className="h-7 gap-1 px-2 text-xs"
              data-testid="chat-selection-move"
              disabled={nothingSelected || busy}
              size="sm"
              variant="outline"
            >
              <FolderInput />
              {t.chats.selection.moveTo}
              <ChevronDown className="size-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56 rounded-lg">
            {/* Parents before children, indented one step per level, like
                the row menu's **Move to folder ▸**. */}
            {folderTargets.map(({ folder, depth }) => (
              <DropdownMenuItem
                key={folder.id}
                onSelect={() => onMoveToFolder(selectedIds(), folder)}
              >
                <span
                  className="truncate"
                  style={{ paddingLeft: `${(depth - 1) * 12}px` }}
                >
                  {folder.name}
                </span>
              </DropdownMenuItem>
            ))}
            {folderTargets.length > 0 && <DropdownMenuSeparator />}
            <DropdownMenuItem
              onSelect={() => onMoveToFolder(selectedIds(), null)}
            >
              <span>{t.chats.folders.none}</span>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() => onNewFolderFromSelection(selectedIds())}
            >
              <FolderPlus className="text-muted-foreground" />
              <span>{t.chats.selection.newFolderFromSelection}</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button
          className="h-7 gap-1 px-2 text-xs"
          data-testid="chat-selection-archive"
          disabled={nothingSelected || busy}
          onClick={() => archive.setArchived(selectedIds(), true)}
          size="sm"
          variant="outline"
        >
          <Archive />
          {t.chats.selection.archive}
        </Button>
        {canDelete && (
          <Button
            className="text-destructive hover:text-destructive h-7 gap-1 px-2 text-xs"
            data-testid="chat-selection-delete"
            disabled={nothingSelected || busy}
            onClick={() =>
              api.requestDelete({
                threads: selectedIds().flatMap((id) => {
                  const thread = threadsById.get(id);
                  return thread ? [thread] : [];
                }),
                recentThreadId,
              })
            }
            size="sm"
            variant="outline"
          >
            <Trash2 />
            {t.chats.selection.delete}
          </Button>
        )}
        <Button
          className="h-7 gap-1 px-2 text-xs"
          data-testid="chat-selection-cleanup"
          disabled={busy}
          onClick={() =>
            api.openCleanup(nothingSelected ? null : selectedIds())
          }
          size="sm"
          variant="outline"
        >
          <Sparkles />
          {nothingSelected
            ? t.chats.selection.cleanUpAll
            : t.chats.selection.cleanUp}
        </Button>
      </div>
    </div>
  );
}
