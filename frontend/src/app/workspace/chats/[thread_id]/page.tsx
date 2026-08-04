"use client";

import { useCallback, useEffect } from "react";

import { ChatInstance, useThreadChat } from "@/components/workspace/chats";
import { useChatTabs } from "@/core/threads/chat-tabs-context";
import { env } from "@/env";

/**
 * Chat route entry point. Two rendering modes:
 *
 * - **Static-demo** builds pre-render specific chat pages and enforce route
 *   asset budgets, and the keep-alive tab viewport is client-only — so the demo
 *   keeps the classic inline single-chat rendering.
 * - **App** builds render the live chat inside a persistent, workspace-level
 *   keep-alive viewport (see `KeepAliveChatViewport`). Here the route page is a
 *   thin registrar: it reports the current chat route to the tab strip and
 *   renders nothing itself, so navigating between chats never remounts them.
 */
export default function ChatPage() {
  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    return <ClassicChatPage />;
  }
  return <ChatRouteRegistrar />;
}

function ClassicChatPage() {
  const { threadId, isNewThread, isMock, setThreadId, setIsNewThread } =
    useThreadChat();
  const handleThreadStarted = useCallback(
    (_slotKey: string, realThreadId: string) => {
      setThreadId(realThreadId);
      setIsNewThread(false);
    },
    [setThreadId, setIsNewThread],
  );
  return (
    <ChatInstance
      slotKey="classic"
      threadId={threadId}
      isNewThread={isNewThread}
      isMock={isMock}
      isActive
      onThreadStarted={handleThreadStarted}
    />
  );
}

function ChatRouteRegistrar() {
  const { threadId, isNewThread } = useThreadChat();
  const { syncRoute } = useChatTabs();
  useEffect(() => {
    syncRoute({ threadId, isNew: isNewThread });
  }, [threadId, isNewThread, syncRoute]);
  return null;
}
