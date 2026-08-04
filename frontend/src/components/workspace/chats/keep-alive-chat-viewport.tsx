"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { useChatTabs } from "@/core/threads/chat-tabs-context";
import { cn } from "@/lib/utils";

import { ChatInstance } from "./chat-instance";
import { ChatTabsBar } from "./chat-tabs-bar";

type Slot = {
  key: string;
  threadId: string;
  isNew: boolean;
};

/**
 * The persistent, workspace-level host for live chats (fork feature: keep-alive
 * chat tabs). It mounts one <ChatInstance> per pinned tab plus one for the
 * current unpinned chat, and only the active slot is displayed — the rest stay
 * mounted (display:none preserves scroll and keeps their streams running), so
 * switching tabs never remounts a chat.
 *
 * It lives above the route in the workspace shell, so navigating between chats
 * (or away to another workspace page) leaves the pinned instances untouched.
 * On non-chat routes the whole host is hidden but still mounted. In static-demo
 * builds the feature is off and the route renders the classic inline chat.
 */
export function KeepAliveChatViewport() {
  const { enabled, tabs, current, activeKey, promoteSlotThreadId } =
    useChatTabs();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const isMock = searchParams.get("mock") === "true";

  const onChatRoute = pathname?.startsWith("/workspace/chats/") ?? false;

  const slots = useMemo<Slot[]>(() => {
    const pinnedSlots = tabs.map((tab) => ({
      key: tab.key,
      threadId: tab.threadId,
      isNew: false,
    }));
    // The current chat gets its own slot unless it is already pinned (in which
    // case the pinned instance owns that thread — never mount it twice).
    if (
      current &&
      !tabs.some((tab) => tab.threadId === current.threadId)
    ) {
      pinnedSlots.push({
        key: current.key,
        threadId: current.threadId,
        isNew: current.isNew,
      });
    }
    return pinnedSlots;
  }, [tabs, current]);

  if (!enabled || slots.length === 0) {
    return null;
  }

  return (
    <div
      data-testid="keep-alive-chat-viewport"
      className={cn(
        "min-h-0 flex-1 flex-col",
        onChatRoute ? "flex" : "hidden",
      )}
    >
      <ChatTabsBar />
      <div className="relative min-h-0 flex-1">
        {slots.map((slot) => {
          const isActive = slot.key === activeKey;
          return (
            <div
              key={slot.key}
              data-slot-key={slot.key}
              className={cn(
                "absolute inset-0 min-h-0",
                isActive ? "block" : "hidden",
              )}
            >
              <ChatInstance
                slotKey={slot.key}
                threadId={slot.threadId}
                isNewThread={slot.isNew}
                isMock={isMock}
                isActive={isActive && onChatRoute}
                onThreadStarted={promoteSlotThreadId}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
