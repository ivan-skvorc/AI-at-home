"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import { uuid } from "@/core/utils/uuid";
import { env } from "@/env";

import {
  chatTabsStorageKey,
  closeTab as closeTabModel,
  closeTabByThreadId,
  deserializeChatTabs,
  findTabByThreadId,
  isThreadPinned,
  pinTab,
  reorderTabsByKey,
  serializeChatTabs,
  setTabTitle,
  updateTabThreadId,
  type ChatTab,
} from "./chat-tabs";

export type { ChatTab } from "./chat-tabs";

// The transient, non-pinned chat the user is currently viewing. Exactly one
// exists at a time; it is replaced whenever the route moves to a different
// unpinned chat. Only pinned tabs are keep-alive — the current slot is the
// classic "one live chat" and is allowed to remount on navigation.
export type CurrentSlot = {
  key: string;
  threadId: string;
  isNew: boolean;
};

export type ChatRoute = {
  threadId: string;
  isNew: boolean;
};

export type ChatTabsContextValue = {
  /** Whether the tab strip feature is active (off in static-demo builds). */
  enabled: boolean;
  tabs: ChatTab[];
  current: CurrentSlot | null;
  /** React key of the slot that should be visible right now. */
  activeKey: string | null;
  /** Report the current chat route so the strip can track what is active. */
  syncRoute: (route: ChatRoute | null) => void;
  /** Make an already-pinned tab the visible one. */
  activateTab: (key: string) => void;
  isPinned: (threadId: string) => boolean;
  /**
   * Pin a chat as a keep-alive tab. When the pinned chat is the one currently
   * being viewed, its live slot key is reused so the mounted instance survives
   * the pin (a streaming chat you pin keeps streaming).
   */
  pinThread: (threadId: string, title?: string) => void;
  /** Close a pinned tab; returns the thread to navigate to next (or null). */
  closeTab: (key: string) => { nextThreadId: string | null };
  reorderTabs: (sourceKey: string, targetKey: string) => void;
  /** A slot's instance reports its new→real thread-id promotion. */
  promoteSlotThreadId: (slotKey: string, threadId: string) => void;
  /** A slot's instance reports the thread's resolved title (cached on tabs). */
  reportTitle: (threadId: string, title: string) => void;
};

const ChatTabsContext = createContext<ChatTabsContextValue | null>(null);

// Delete flow (recent-chat-list) dispatches this; kept in sync with
// components/workspace/chats/use-thread-chat.ts.
const THREAD_CHAT_RESET_EVENT = "deer-flow:thread-chat-reset";

export function ChatTabsProvider({ children }: { children: ReactNode }) {
  const enabled = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true";
  const { user } = useAuth();
  const storageKey = chatTabsStorageKey(user?.id ?? null);

  const [tabs, setTabs] = useState<ChatTab[]>([]);
  const [current, setCurrent] = useState<CurrentSlot | null>(null);
  const [activeKey, setActiveKey] = useState<string | null>(null);

  // Latest-value refs so the stable callbacks below can read current state
  // without nested state updaters or churning their dependency arrays (the
  // tasksRef pattern used by core/tasks/context.tsx).
  const tabsRef = useRef(tabs);
  tabsRef.current = tabs;
  const currentRef = useRef(current);
  currentRef.current = current;
  const activeKeyRef = useRef(activeKey);
  activeKeyRef.current = activeKey;

  // Hydrate persisted tabs once the storage key (user) is known. Kept out of the
  // initial state so server render and first client render agree (no hydration
  // mismatch); the strip briefly renders empty then fills in.
  const hydratedKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (!enabled || typeof window === "undefined") {
      return;
    }
    if (hydratedKeyRef.current === storageKey) {
      return;
    }
    hydratedKeyRef.current = storageKey;
    try {
      setTabs(deserializeChatTabs(window.localStorage.getItem(storageKey)));
    } catch {
      setTabs([]);
    }
  }, [enabled, storageKey]);

  // Persist on every change, once hydrated for this key.
  useEffect(() => {
    if (!enabled || typeof window === "undefined") {
      return;
    }
    if (hydratedKeyRef.current !== storageKey) {
      return;
    }
    try {
      window.localStorage.setItem(storageKey, serializeChatTabs(tabs));
    } catch {
      // Storage may be full/disabled; the strip keeps working in memory.
    }
  }, [enabled, storageKey, tabs]);

  const syncRoute = useCallback((route: ChatRoute | null) => {
    if (route === null) {
      // Left the chat routes; keep pinned instances mounted but show nothing.
      setActiveKey(null);
      return;
    }
    const pinned = findTabByThreadId(tabsRef.current, route.threadId);
    if (pinned) {
      setActiveKey(pinned.key);
      return;
    }
    // The slot key encodes the *original* route identity and is stable across a
    // new→real promotion (the id changes, the key does not). Matching on the key
    // — not the mutable threadId/isNew — means re-reporting the same route after
    // its chat was sent re-selects the promoted slot instead of clobbering it
    // with a fresh empty one (Next keeps the pre-replaceState params).
    const key = route.isNew
      ? `new:${route.threadId}`
      : `route:${route.threadId}`;
    const prevCurrent = currentRef.current;
    if (prevCurrent?.key === key) {
      setActiveKey(prevCurrent.key);
      return;
    }
    setCurrent({ key, threadId: route.threadId, isNew: route.isNew });
    setActiveKey(key);
  }, []);

  const activateTab = useCallback((key: string) => {
    setActiveKey(key);
  }, []);

  const isPinned = useCallback(
    (threadId: string) => isThreadPinned(tabs, threadId),
    [tabs],
  );

  const pinThread = useCallback((threadId: string, title?: string) => {
    const prevCurrent = currentRef.current;
    // Reuse the live slot's key when pinning the chat we're viewing so the
    // mounted instance is not torn down by the pin.
    const reusedKey =
      prevCurrent?.threadId === threadId
        ? prevCurrent.key
        : undefined;
    const prevTabs = tabsRef.current;
    const existing = findTabByThreadId(prevTabs, threadId);
    if (existing) {
      setActiveKey(existing.key);
      return;
    }
    const key = reusedKey ?? uuid();
    const next = pinTab(prevTabs, { key, threadId, title });
    if (next === prevTabs) {
      // Strip is full; leave state untouched.
      return;
    }
    setTabs(next);
    setActiveKey(key);
    if (reusedKey) {
      setCurrent(null);
    }
  }, []);

  const closeTab = useCallback(
    (key: string): { nextThreadId: string | null } => {
      const prevTabs = tabsRef.current;
      const index = prevTabs.findIndex((tab) => tab.key === key);
      if (index === -1) {
        return { nextThreadId: null };
      }
      const neighbor = prevTabs[index + 1] ?? prevTabs[index - 1];
      let nextThreadId: string | null = null;
      if (activeKeyRef.current === key) {
        if (neighbor) {
          nextThreadId = neighbor.threadId;
          setActiveKey(neighbor.key);
        } else {
          setActiveKey(null);
        }
      }
      setTabs(closeTabModel(prevTabs, key));
      return { nextThreadId };
    },
    [],
  );

  const reorderTabs = useCallback((sourceKey: string, targetKey: string) => {
    setTabs((prevTabs) => reorderTabsByKey(prevTabs, sourceKey, targetKey));
  }, []);

  const promoteSlotThreadId = useCallback(
    (slotKey: string, threadId: string) => {
      setTabs((prevTabs) => updateTabThreadId(prevTabs, slotKey, threadId));
      setCurrent((prevCurrent) =>
        prevCurrent?.key === slotKey
          ? { ...prevCurrent, threadId, isNew: false }
          : prevCurrent,
      );
    },
    [],
  );

  const reportTitle = useCallback((threadId: string, title: string) => {
    if (!title) {
      return;
    }
    setTabs((prevTabs) => setTabTitle(prevTabs, threadId, title));
  }, []);

  // A deleted chat must drop its pinned tab (and its transient slot).
  useEffect(() => {
    if (!enabled || typeof window === "undefined") {
      return;
    }
    const handleReset = (event: Event) => {
      const detail = (event as CustomEvent<{ deletedThreadId?: string }>)
        .detail;
      const deletedThreadId = detail?.deletedThreadId;
      if (!deletedThreadId) {
        return;
      }
      const doomed = findTabByThreadId(tabsRef.current, deletedThreadId);
      if (activeKeyRef.current === doomed?.key) {
        setActiveKey(null);
      }
      setTabs((prevTabs) => closeTabByThreadId(prevTabs, deletedThreadId));
      setCurrent((prevCurrent) =>
        prevCurrent?.threadId === deletedThreadId
          ? null
          : prevCurrent,
      );
    };
    window.addEventListener(THREAD_CHAT_RESET_EVENT, handleReset);
    return () =>
      window.removeEventListener(THREAD_CHAT_RESET_EVENT, handleReset);
  }, [enabled]);

  const value = useMemo<ChatTabsContextValue>(
    () => ({
      enabled,
      tabs,
      current,
      activeKey,
      syncRoute,
      activateTab,
      isPinned,
      pinThread,
      closeTab,
      reorderTabs,
      promoteSlotThreadId,
      reportTitle,
    }),
    [
      enabled,
      tabs,
      current,
      activeKey,
      syncRoute,
      activateTab,
      isPinned,
      pinThread,
      closeTab,
      reorderTabs,
      promoteSlotThreadId,
      reportTitle,
    ],
  );

  return (
    <ChatTabsContext.Provider value={value}>
      {children}
    </ChatTabsContext.Provider>
  );
}

export function useChatTabs(): ChatTabsContextValue {
  const context = useContext(ChatTabsContext);
  if (context === null) {
    throw new Error("useChatTabs must be used within a ChatTabsProvider");
  }
  return context;
}

/** Non-throwing variant for components that may render outside the provider. */
export function useMaybeChatTabs(): ChatTabsContextValue | null {
  return useContext(ChatTabsContext);
}
