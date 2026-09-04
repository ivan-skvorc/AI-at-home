"use client";

import {
  ChevronRight,
  Folder as FolderIcon,
  FolderOpen,
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
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import type { ChatFolder } from "@/core/threads/chat-folders";
import { CHAT_TAB_DND_THREAD_MIME } from "@/core/threads/chat-tabs";
import { cn } from "@/lib/utils";

/**
 * One folder header in the sidebar tree: a disclosure arrow, the folder name,
 * how many conversations are inside, and the same kind of options menu the
 * conversation rows carry.
 *
 * It is also the drop target for filing a chat: a sidebar chat row advertises
 * its thread id under {@link CHAT_TAB_DND_THREAD_MIME} (the same payload the
 * keep-alive tab strip accepts), so one drag serves both targets.
 */
export function ChatFolderRow({
  count,
  folder,
  isExpanded,
  onDropThread,
  onRename,
  onDelete,
  onToggle,
}: {
  count: number;
  folder: ChatFolder;
  isExpanded: boolean;
  onDropThread: (threadId: string) => void;
  onRename: () => void;
  onDelete: () => void;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const [isDropTarget, setIsDropTarget] = useState(false);

  const handleDragOver = useCallback((event: React.DragEvent) => {
    // `getData` is unreadable during a drag; only the type list is exposed, so
    // that is what decides whether this row accepts the drop.
    if (!event.dataTransfer.types.includes(CHAT_TAB_DND_THREAD_MIME)) {
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setIsDropTarget(true);
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      const threadId = event.dataTransfer.getData(CHAT_TAB_DND_THREAD_MIME);
      setIsDropTarget(false);
      if (!threadId) {
        return;
      }
      event.preventDefault();
      onDropThread(threadId);
    },
    [onDropThread],
  );

  return (
    <SidebarMenuItem
      className="group/side-menu-item"
      data-testid="chat-folder-row"
      data-folder-id={folder.id}
      data-drop-target={isDropTarget || undefined}
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
