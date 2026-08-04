"use client";

import { PinIcon, XIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import {
  CHAT_TAB_DND_TAB_MIME,
  CHAT_TAB_DND_THREAD_MIME,
  type ChatTab,
} from "@/core/threads/chat-tabs";
import { useChatTabs } from "@/core/threads/chat-tabs-context";
import { useInfiniteThreads } from "@/core/threads/hooks";
import { buildThreadListModel } from "@/core/threads/thread-list-model";
import { pathOfThread, titleOfThread } from "@/core/threads/utils";
import { cn } from "@/lib/utils";

/**
 * The browser-style chat tab strip (fork feature). Renders pinned keep-alive
 * tabs plus a preview chip for the current unpinned chat, and is the drop target
 * for chats dragged out of the sidebar. Reordering is native drag-and-drop
 * between chips; clicking a chip switches to its always-mounted instance without
 * a navigation remount (see KeepAliveChatViewport).
 */
export function ChatTabsBar() {
  const { t } = useI18n();
  const router = useRouter();
  const {
    tabs,
    current,
    activeKey,
    activateTab,
    pinThread,
    closeTab,
    reorderTabs,
  } = useChatTabs();

  const { data } = useInfiniteThreads();
  const byId = useMemo(
    () => buildThreadListModel(data?.pages ?? []).byId,
    [data?.pages],
  );

  const [dropActive, setDropActive] = useState(false);

  const titleFor = useCallback(
    (threadId: string, cached?: string): string => {
      const thread = byId.get(threadId);
      if (thread) {
        return titleOfThread(thread);
      }
      return cached ?? t.chatTabs.untitled;
    },
    [byId, t.chatTabs.untitled],
  );

  const navigateTo = useCallback((threadId: string) => {
    // Native history (not the Next router) so switching tabs never remounts the
    // mounted instances — matches the chat page's own new→real replaceState.
    window.history.replaceState(null, "", pathOfThread(threadId));
  }, []);

  const handleActivate = useCallback(
    (tab: ChatTab) => {
      activateTab(tab.key);
      navigateTo(tab.threadId);
    },
    [activateTab, navigateTo],
  );

  const handleClose = useCallback(
    (event: React.MouseEvent, tab: ChatTab) => {
      event.preventDefault();
      event.stopPropagation();
      const wasActive = tab.key === activeKey;
      const { nextThreadId } = closeTab(tab.key);
      if (!wasActive) {
        return;
      }
      if (nextThreadId) {
        navigateTo(nextThreadId);
      } else {
        // No neighbor left: fall back to a fresh chat via a real navigation so
        // the route registrar seeds a new current slot.
        router.push("/workspace/chats/new");
      }
    },
    [activeKey, closeTab, navigateTo, router],
  );

  const handleTabDrop = useCallback(
    (event: React.DragEvent, targetKey: string) => {
      event.preventDefault();
      event.stopPropagation();
      setDropActive(false);
      const draggedTabKey = event.dataTransfer.getData(CHAT_TAB_DND_TAB_MIME);
      if (draggedTabKey) {
        reorderTabs(draggedTabKey, targetKey);
        return;
      }
      const threadId = event.dataTransfer.getData(CHAT_TAB_DND_THREAD_MIME);
      if (threadId) {
        pinThread(threadId, byId.get(threadId) && titleFor(threadId));
        navigateTo(threadId);
      }
    },
    [byId, navigateTo, pinThread, reorderTabs, titleFor],
  );

  const handleStripDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      setDropActive(false);
      const draggedTabKey = event.dataTransfer.getData(CHAT_TAB_DND_TAB_MIME);
      if (draggedTabKey) {
        const last = tabs[tabs.length - 1];
        if (last) {
          reorderTabs(draggedTabKey, last.key);
        }
        return;
      }
      const threadId = event.dataTransfer.getData(CHAT_TAB_DND_THREAD_MIME);
      if (threadId) {
        pinThread(threadId, byId.get(threadId) && titleFor(threadId));
        navigateTo(threadId);
      }
    },
    [byId, navigateTo, pinThread, reorderTabs, tabs, titleFor],
  );

  const dragCarriesChatPayload = useCallback((event: React.DragEvent) => {
    const types = event.dataTransfer.types;
    return (
      types.includes(CHAT_TAB_DND_TAB_MIME) ||
      types.includes(CHAT_TAB_DND_THREAD_MIME)
    );
  }, []);

  const handleDragOver = useCallback(
    (event: React.DragEvent) => {
      if (!dragCarriesChatPayload(event)) {
        return;
      }
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      setDropActive(true);
    },
    [dragCarriesChatPayload],
  );

  // The current chat gets a preview chip only when it is not already pinned.
  const showCurrentChip = current !== null && !current.isNew;

  if (tabs.length === 0 && !showCurrentChip) {
    // Nothing to show yet, but the strip stays available as a drop target once a
    // chat exists; render nothing to avoid an empty bar on a brand-new chat.
    return null;
  }

  return (
    <div
      role="tablist"
      aria-label={t.chatTabs.ariaLabel}
      data-testid="chat-tabs-bar"
      onDragOver={handleDragOver}
      onDragLeave={() => setDropActive(false)}
      onDrop={handleStripDrop}
      className={cn(
        "flex h-9 w-full shrink-0 items-stretch gap-1 overflow-x-auto border-b px-2 py-1",
        "[scrollbar-width:thin]",
        dropActive && "bg-primary/5",
      )}
    >
      {tabs.map((tab) => {
        const isActive = tab.key === activeKey;
        return (
          <div
            key={tab.key}
            role="tab"
            aria-selected={isActive}
            data-testid="chat-tab"
            draggable
            onDragStart={(event) => {
              event.dataTransfer.setData(CHAT_TAB_DND_TAB_MIME, tab.key);
              event.dataTransfer.effectAllowed = "move";
            }}
            onDragOver={handleDragOver}
            onDrop={(event) => handleTabDrop(event, tab.key)}
            onClick={() => handleActivate(tab)}
            className={cn(
              "group/chat-tab flex max-w-48 min-w-24 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border px-2 text-xs transition-colors",
              isActive
                ? "border-border bg-background text-foreground shadow-xs"
                : "text-muted-foreground hover:bg-background/60 border-transparent",
            )}
          >
            <span className="min-w-0 flex-1 truncate">
              {titleFor(tab.threadId, tab.title)}
            </span>
            <button
              type="button"
              aria-label={t.chatTabs.closeTab}
              data-testid="chat-tab-close"
              onClick={(event) => handleClose(event, tab)}
              className="text-muted-foreground/70 hover:bg-muted hover:text-foreground grid size-4 shrink-0 place-items-center rounded opacity-0 transition-opacity group-hover/chat-tab:opacity-100 focus-visible:opacity-100"
            >
              <XIcon className="size-3" />
            </button>
          </div>
        );
      })}

      {showCurrentChip && current && (
        <div
          data-testid="chat-tab-current"
          className={cn(
            "flex max-w-48 min-w-24 shrink-0 items-center gap-1.5 rounded-md border border-dashed px-2 text-xs",
            activeKey === current.key
              ? "border-border/70 bg-background/40 text-foreground"
              : "text-muted-foreground border-transparent",
          )}
        >
          <span className="min-w-0 flex-1 truncate italic">
            {titleFor(current.threadId)}
          </span>
          <Tooltip content={t.chatTabs.pinTab}>
            <button
              type="button"
              aria-label={t.chatTabs.pinTab}
              data-testid="chat-tab-pin-current"
              onClick={() =>
                pinThread(current.threadId, titleFor(current.threadId))
              }
              className="text-muted-foreground/70 hover:bg-muted hover:text-foreground grid size-4 shrink-0 place-items-center rounded"
            >
              <PinIcon className="size-3" />
            </button>
          </Tooltip>
        </div>
      )}
    </div>
  );
}
