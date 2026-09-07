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

import { env } from "@/env";

import {
  findSlotByThreadId,
  releaseSlot as releaseSlotModel,
  releaseSlotByThreadId,
  retainSlot,
  updateSlotThreadId,
  type ChatSlot,
} from "./live-chat-slots";

export type { ChatSlot } from "./live-chat-slots";

// Stable identity so an idle provider never hands consumers a fresh Set.
const EMPTY_BUSY_KEYS: ReadonlySet<string> = new Set<string>();

export type ChatRoute = {
  threadId: string;
  isNew: boolean;
};

export type LiveChatSlotsContextValue = {
  /** Whether workspace-level chat mounting is active (off in static-demo builds). */
  enabled: boolean;
  /** Chats kept mounted while they finish answering out of view. */
  background: ChatSlot[];
  /** The chat on screen. */
  current: ChatSlot | null;
  /** React key of the slot that should be visible right now. */
  activeKey: string | null;
  /** Report the current chat route so the host can mount the right instance. */
  syncRoute: (route: ChatRoute | null) => void;
  /** A slot's instance reports its new→real thread-id promotion. */
  promoteSlotThreadId: (slotKey: string, threadId: string) => void;
  /**
   * Slot keys whose chat currently has a run in flight. Keyed by slot (not
   * thread) because that is the identity the mounted instances address, and it
   * survives a new→real promotion.
   */
  busyKeys: ReadonlySet<string>;
  /** A slot's instance reports whether its chat is streaming right now. */
  reportBusy: (slotKey: string, busy: boolean) => void;
};

const LiveChatSlotsContext = createContext<LiveChatSlotsContextValue | null>(
  null,
);

// Delete flow (recent-chat-list) dispatches this; kept in sync with
// components/workspace/chats/use-thread-chat.ts.
const THREAD_CHAT_RESET_EVENT = "deer-flow:thread-chat-reset";

export function LiveChatSlotsProvider({ children }: { children: ReactNode }) {
  const enabled = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true";

  const [background, setBackground] = useState<ChatSlot[]>([]);
  const [current, setCurrent] = useState<ChatSlot | null>(null);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [busyKeys, setBusyKeys] =
    useState<ReadonlySet<string>>(EMPTY_BUSY_KEYS);

  // Latest-value refs so the stable callbacks below can read current state
  // without nested state updaters or churning their dependency arrays (the
  // tasksRef pattern used by core/tasks/context.tsx).
  const backgroundRef = useRef(background);
  backgroundRef.current = background;
  const currentRef = useRef(current);
  currentRef.current = current;
  const activeKeyRef = useRef(activeKey);
  activeKeyRef.current = activeKey;
  const busyKeysRef = useRef(busyKeys);
  busyKeysRef.current = busyKeys;

  const syncRoute = useCallback((route: ChatRoute | null) => {
    if (route === null) {
      // Left the chat routes; keep background instances mounted but show nothing.
      setActiveKey(null);
      return;
    }
    // Returning to a chat that is still answering in the background: adopt its
    // existing instance as the visible one rather than mounting a second one
    // for the same thread, which would show an empty transcript beside a run
    // already in flight.
    const backgrounded = findSlotByThreadId(
      backgroundRef.current,
      route.threadId,
    );
    if (backgrounded) {
      setBackground((slots) => releaseSlotModel(slots, backgrounded.key));
      setCurrent(backgrounded);
      setActiveKey(backgrounded.key);
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
    // Concurrent chats: the slot we are leaving is normally dropped, which
    // unmounts its instance and ends its live view. When that chat is still
    // streaming, keep it mounted in the background instead — reusing its key so
    // the instance is not torn down — so the answer keeps arriving while the
    // user writes the next prompt somewhere else. A full background set declines
    // the retention; the run itself still survives (`onDisconnect: "continue"`)
    // and is rejoined on return. A slot that has not been promoted to a real
    // thread id yet is left alone: it is addressed by thread id, which it does
    // not have.
    if (
      prevCurrent &&
      !prevCurrent.isNew &&
      busyKeysRef.current.has(prevCurrent.key)
    ) {
      setBackground((slots) => retainSlot(slots, prevCurrent));
    }
    setCurrent({ key, threadId: route.threadId, isNew: route.isNew });
    setActiveKey(key);
  }, []);

  const promoteSlotThreadId = useCallback(
    (slotKey: string, threadId: string) => {
      setBackground((slots) => updateSlotThreadId(slots, slotKey, threadId));
      setCurrent((prevCurrent) =>
        prevCurrent?.key === slotKey
          ? { ...prevCurrent, threadId, isNew: false }
          : prevCurrent,
      );
    },
    [],
  );

  const reportBusy = useCallback((slotKey: string, busy: boolean) => {
    setBusyKeys((prevKeys) => {
      if (prevKeys.has(slotKey) === busy) {
        return prevKeys;
      }
      const next = new Set(prevKeys);
      if (busy) {
        next.add(slotKey);
      } else {
        next.delete(slotKey);
      }
      return next;
    });
  }, []);

  // A background chat exists only for the run it is finishing. Once that run
  // lands, its instance has nothing left to receive, so it is released and
  // unmounted — the transcript is on the server and reloads on the next visit.
  // This runs as an effect, after the stream's own `onFinish` (which raises the
  // "conversation finished" notification), so releasing never pre-empts it.
  useEffect(() => {
    if (background.length === 0) {
      return;
    }
    const finished = background.filter((slot) => !busyKeys.has(slot.key));
    if (finished.length === 0) {
      return;
    }
    setBackground((slots) =>
      finished.reduce((rest, slot) => releaseSlotModel(rest, slot.key), slots),
    );
  }, [background, busyKeys]);

  // A deleted chat must drop its slot, background or current.
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
      const doomed = findSlotByThreadId(backgroundRef.current, deletedThreadId);
      if (activeKeyRef.current === doomed?.key) {
        setActiveKey(null);
      }
      setBackground((slots) => releaseSlotByThreadId(slots, deletedThreadId));
      setCurrent((prevCurrent) =>
        prevCurrent?.threadId === deletedThreadId ? null : prevCurrent,
      );
    };
    window.addEventListener(THREAD_CHAT_RESET_EVENT, handleReset);
    return () =>
      window.removeEventListener(THREAD_CHAT_RESET_EVENT, handleReset);
  }, [enabled]);

  const value = useMemo<LiveChatSlotsContextValue>(
    () => ({
      enabled,
      background,
      current,
      activeKey,
      syncRoute,
      promoteSlotThreadId,
      busyKeys,
      reportBusy,
    }),
    [
      enabled,
      background,
      current,
      activeKey,
      syncRoute,
      promoteSlotThreadId,
      busyKeys,
      reportBusy,
    ],
  );

  return (
    <LiveChatSlotsContext.Provider value={value}>
      {children}
    </LiveChatSlotsContext.Provider>
  );
}

export function useLiveChatSlots(): LiveChatSlotsContextValue {
  const context = useContext(LiveChatSlotsContext);
  if (context === null) {
    throw new Error(
      "useLiveChatSlots must be used within a LiveChatSlotsProvider",
    );
  }
  return context;
}

/** Non-throwing variant for components that may render outside the provider. */
export function useMaybeLiveChatSlots(): LiveChatSlotsContextValue | null {
  return useContext(LiveChatSlotsContext);
}
