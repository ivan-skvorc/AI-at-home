"use client";

import {
  ChevronRight,
  Folder as FolderIcon,
  FolderInput,
  FolderOpen,
  FolderPlus,
  MoreHorizontal,
  Pencil,
  Trash2,
} from "lucide-react";
import { useCallback, useState } from "react";

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
import {
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import {
  CHAT_FOLDER_DND_MIME,
  type ChatFolder,
} from "@/core/threads/chat-folders";
import { CHAT_TAB_DND_THREAD_MIME } from "@/core/threads/chat-tabs";
import { cn } from "@/lib/utils";

/** One entry of the folder row's **Move folder to ▸** submenu. */
export type FolderMoveTarget = {
  folder: ChatFolder;
  /** Nesting level, so the submenu reads as the tree it is picking from. */
  depth: number;
  disabled: boolean;
};

/**
 * One folder header in the sidebar tree: a disclosure arrow, the folder name,
 * how many conversations are inside (**including its subfolders** — a collapsed
 * parent that read "0" while holding twenty chats would be a lie), and the same
 * kind of options menu the conversation rows carry.
 *
 * It is also a drop target *and* a drag source. As a target it accepts a chat
 * (filed into this folder) and another folder (nested inside this one); a
 * sidebar chat row advertises its thread id under
 * {@link CHAT_TAB_DND_THREAD_MIME} — the same payload the keep-alive tab strip
 * accepts, so one drag serves both targets — and a folder row advertises its
 * own id under {@link CHAT_FOLDER_DND_MIME}. The two MIMEs are separate so a
 * target can accept one and refuse the other, which is what stops a folder from
 * being dropped into itself.
 */
export function ChatFolderRow({
  canNest,
  count,
  depth,
  folder,
  isExpanded,
  moveTargets,
  onDropFolder,
  onDropThread,
  onMoveFolder,
  onNewSubfolder,
  onRename,
  onDelete,
  onToggle,
}: {
  canNest: boolean;
  count: number;
  depth: number;
  folder: ChatFolder;
  isExpanded: boolean;
  moveTargets: readonly FolderMoveTarget[];
  onDropFolder: (folderId: string) => void;
  onDropThread: (threadId: string) => void;
  onMoveFolder: (parentId: string | null) => void;
  onNewSubfolder: () => void;
  onRename: () => void;
  onDelete: () => void;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const [isDropTarget, setIsDropTarget] = useState(false);

  const handleDragStart = useCallback(
    (event: React.DragEvent) => {
      event.dataTransfer.setData(CHAT_FOLDER_DND_MIME, folder.id);
      event.dataTransfer.effectAllowed = "move";
      event.stopPropagation();
    },
    [folder.id],
  );

  const handleDragOver = useCallback(
    (event: React.DragEvent) => {
      // `getData` is unreadable during a drag; only the type list is exposed, so
      // that is what decides whether this row accepts the drop. A folder that
      // cannot take another folder (it is already at the depth limit) simply
      // does not accept the drag, rather than accepting it and dropping it.
      const types = event.dataTransfer.types;
      const accepts =
        types.includes(CHAT_TAB_DND_THREAD_MIME) ||
        (canNest && types.includes(CHAT_FOLDER_DND_MIME));
      if (!accepts) {
        return;
      }
      event.preventDefault();
      // A nested row sits *inside* its parent's drop zone, so without this the
      // parent lights up at the same time and then claims the drop — the chat
      // lands one level too high, which looks like the drag simply missed.
      event.stopPropagation();
      event.dataTransfer.dropEffect = "move";
      setIsDropTarget(true);
    },
    [canNest],
  );

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      const threadId = event.dataTransfer.getData(CHAT_TAB_DND_THREAD_MIME);
      const draggedFolderId = event.dataTransfer.getData(CHAT_FOLDER_DND_MIME);
      setIsDropTarget(false);
      if (threadId) {
        event.preventDefault();
        // The innermost target owns the drop; see `handleDragOver`.
        event.stopPropagation();
        onDropThread(threadId);
        return;
      }
      // Dropping a folder onto itself is a no-op, not an error — the model
      // refuses it too, this just avoids the pointless write.
      if (!draggedFolderId || draggedFolderId === folder.id) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      onDropFolder(draggedFolderId);
    },
    [folder.id, onDropFolder, onDropThread],
  );

  return (
    <SidebarMenuItem
      className="group/side-menu-item"
      data-testid="chat-folder-row"
      data-folder-id={folder.id}
      data-folder-depth={depth}
      data-drop-target={isDropTarget || undefined}
      draggable
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragLeave={() => setIsDropTarget(false)}
      onDrop={handleDrop}
    >
      <SidebarMenuButton
        aria-expanded={isExpanded}
        className={cn(
          "text-muted-foreground min-w-0 whitespace-nowrap",
          isDropTarget && "bg-sidebar-accent text-sidebar-accent-foreground",
        )}
        onClick={onToggle}
        title={folder.name}
      >
        <ChevronRight
          aria-hidden="true"
          className={cn(
            "size-3.5 shrink-0 transition-transform",
            isExpanded && "rotate-90",
          )}
          data-testid="chat-folder-chevron"
        />
        {isExpanded ? (
          <FolderOpen aria-hidden="true" className="size-4 shrink-0" />
        ) : (
          <FolderIcon aria-hidden="true" className="size-4 shrink-0" />
        )}
        <span className="min-w-0 truncate">{folder.name}</span>
        <span
          aria-hidden="true"
          className="text-muted-foreground/70 ml-auto shrink-0 pr-1 text-[10px] tabular-nums"
          data-testid="chat-folder-count"
        >
          {count}
        </span>
        <span className="sr-only">
          {isExpanded ? t.chats.folders.collapse : t.chats.folders.expand}
        </span>
      </SidebarMenuButton>
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
          {/* Keyboard-reachable equivalents of the folder drag: native HTML5
              drag-and-drop is unusable by keyboard and by screen readers, so
              nesting exists in a menu too. */}
          <DropdownMenuItem disabled={!canNest} onSelect={onNewSubfolder}>
            <FolderPlus className="text-muted-foreground" />
            <span>{t.chats.folders.newSubfolder}</span>
          </DropdownMenuItem>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <FolderInput className="text-muted-foreground" />
              <span>{t.chats.folders.moveFolderTo}</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              {moveTargets.map((target) => (
                <DropdownMenuItem
                  key={target.folder.id}
                  disabled={target.disabled}
                  onSelect={() => onMoveFolder(target.folder.id)}
                >
                  <span
                    className="truncate"
                    style={{ paddingLeft: `${(target.depth - 1) * 12}px` }}
                  >
                    {target.folder.name}
                  </span>
                </DropdownMenuItem>
              ))}
              {moveTargets.length > 0 && <DropdownMenuSeparator />}
              <DropdownMenuItem
                disabled={depth === 1}
                onSelect={() => onMoveFolder(null)}
              >
                <span>{t.chats.folders.topLevel}</span>
              </DropdownMenuItem>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={onRename}>
            <Pencil className="text-muted-foreground" />
            <span>{t.common.rename}</span>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={onDelete}>
            <Trash2 className="text-muted-foreground" />
            <span>{t.common.delete}</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </SidebarMenuItem>
  );
}
