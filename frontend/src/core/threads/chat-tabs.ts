/**
 * Pure model for the browser-style chat tab strip (fork feature: keep-alive
 * chat tabs). A "pinned" tab is a chat the user has explicitly dragged (or
 * added via the row menu) onto the tab strip so it stays mounted and alive
 * across navigation. This module owns only the ordered set of pinned tabs and
 * its persistence — nothing React, nothing route-aware — so it is exhaustively
 * unit-testable. Active-tab / route coordination lives in the context provider.
 */

// A pinned tab. `key` is a stable identity assigned once when the tab is
// pinned and never changed afterwards — it backs the React key of the mounted
// chat instance, so it must survive a "new chat becomes real" promotion where
// only `threadId` changes. `title` is a cached display hint so a reloaded strip
// can render immediately before the live thread title resolves.
export type ChatTab = {
  key: string;
  threadId: string;
  title?: string;
};

// Cap on simultaneously-pinned tabs. Keep-alive means every pinned tab holds a
// live chat instance (its own stream, artifact panel, subtasks), so the ceiling
// is a deliberate resource guard, not just visual tidiness.
export const MAX_CHAT_TABS = 8;

export const CHAT_TABS_STORAGE_PREFIX = "deerflow.chat-tabs.";

// Drag-and-drop MIME types for the tab strip. A sidebar chat row advertises its
// thread id (drop onto the strip to pin the chat as a keep-alive tab); a tab
// chip advertises its stable key (drop onto another chip to reorder).
export const CHAT_TAB_DND_THREAD_MIME = "application/x-deerflow-thread-id";
export const CHAT_TAB_DND_TAB_MIME = "application/x-deerflow-tab-key";

/** Per-user localStorage key so pinned tabs never bleed across logins. */
export function chatTabsStorageKey(userId: string | null | undefined): string {
  return `${CHAT_TABS_STORAGE_PREFIX}${userId ?? "anonymous"}`;
}

/** Whether a thread is currently pinned as a tab. */
export function isThreadPinned(tabs: ChatTab[], threadId: string): boolean {
  return tabs.some((tab) => tab.threadId === threadId);
}

export function findTabByThreadId(
  tabs: ChatTab[],
  threadId: string,
): ChatTab | undefined {
  return tabs.find((tab) => tab.threadId === threadId);
}

export function findTabByKey(
  tabs: ChatTab[],
  key: string,
): ChatTab | undefined {
  return tabs.find((tab) => tab.key === key);
}

/**
 * Pin a tab. Idempotent by thread id (dragging an already-pinned chat is a
 * no-op) and capped at {@link MAX_CHAT_TABS} (a full strip rejects the add and
 * returns the same array reference so callers can detect "nothing changed").
 */
export function pinTab(
  tabs: ChatTab[],
  tab: ChatTab,
  max: number = MAX_CHAT_TABS,
): ChatTab[] {
  if (isThreadPinned(tabs, tab.threadId)) {
    return tabs;
  }
  if (tabs.length >= max) {
    return tabs;
  }
  return [...tabs, tab];
}

/** Remove a tab by its stable key. */
export function closeTab(tabs: ChatTab[], key: string): ChatTab[] {
  const next = tabs.filter((tab) => tab.key !== key);
  return next.length === tabs.length ? tabs : next;
}

/** Remove a tab by its (possibly promoted) thread id. */
export function closeTabByThreadId(
  tabs: ChatTab[],
  threadId: string,
): ChatTab[] {
  const next = tabs.filter((tab) => tab.threadId !== threadId);
  return next.length === tabs.length ? tabs : next;
}

/** Move the item at `fromIndex` so it sits at `toIndex`, preserving order. */
export function moveItem<T>(items: T[], fromIndex: number, toIndex: number): T[] {
  if (
    fromIndex === toIndex ||
    fromIndex < 0 ||
    toIndex < 0 ||
    fromIndex >= items.length ||
    toIndex >= items.length
  ) {
    return items;
  }
  const next = [...items];
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved!);
  return next;
}

/**
 * Reorder by key: drop the `sourceKey` tab into the slot currently held by
 * `targetKey`. This is the shape native drag-and-drop produces (we know which
 * chip was dragged and which chip it was dropped on, not raw indices).
 */
export function reorderTabsByKey(
  tabs: ChatTab[],
  sourceKey: string,
  targetKey: string,
): ChatTab[] {
  if (sourceKey === targetKey) {
    return tabs;
  }
  const fromIndex = tabs.findIndex((tab) => tab.key === sourceKey);
  const toIndex = tabs.findIndex((tab) => tab.key === targetKey);
  if (fromIndex === -1 || toIndex === -1) {
    return tabs;
  }
  return moveItem(tabs, fromIndex, toIndex);
}

/**
 * Promote a tab's thread id in place (a brand-new chat that was pinned before
 * its first send later gains its real backend id). The stable `key` is
 * unchanged, so the mounted instance is never remounted. If the promoted id is
 * already held by a different tab, the duplicate is dropped to keep thread ids
 * unique.
 */
export function updateTabThreadId(
  tabs: ChatTab[],
  key: string,
  threadId: string,
): ChatTab[] {
  if (!tabs.some((tab) => tab.key === key)) {
    return tabs;
  }
  return tabs
    .filter((tab) => tab.threadId !== threadId || tab.key === key)
    .map((tab) => (tab.key === key ? { ...tab, threadId } : tab));
}

/** Update a tab's cached title hint (no-op when the thread is not pinned). */
export function setTabTitle(
  tabs: ChatTab[],
  threadId: string,
  title: string,
): ChatTab[] {
  if (!tabs.some((tab) => tab.threadId === threadId && tab.title !== title)) {
    return tabs;
  }
  return tabs.map((tab) =>
    tab.threadId === threadId ? { ...tab, title } : tab,
  );
}

function isValidTab(value: unknown): value is ChatTab {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const tab = value as Record<string, unknown>;
  return (
    typeof tab.key === "string" &&
    tab.key.length > 0 &&
    typeof tab.threadId === "string" &&
    tab.threadId.length > 0 &&
    (tab.title === undefined || typeof tab.title === "string")
  );
}

export function serializeChatTabs(tabs: ChatTab[]): string {
  return JSON.stringify(
    tabs.map((tab) => ({
      key: tab.key,
      threadId: tab.threadId,
      ...(tab.title === undefined ? {} : { title: tab.title }),
    })),
  );
}

/**
 * Parse persisted tabs defensively: bad JSON, non-arrays, and malformed entries
 * degrade to an empty / filtered list rather than throwing. Duplicate thread
 * ids and keys are collapsed (first wins) and the result is capped so a
 * tampered store can never exceed the resource ceiling.
 */
export function deserializeChatTabs(
  raw: string | null | undefined,
  max: number = MAX_CHAT_TABS,
): ChatTab[] {
  if (!raw) {
    return [];
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) {
    return [];
  }
  const seenThreads = new Set<string>();
  const seenKeys = new Set<string>();
  const tabs: ChatTab[] = [];
  for (const entry of parsed) {
    if (!isValidTab(entry)) {
      continue;
    }
    if (seenThreads.has(entry.threadId) || seenKeys.has(entry.key)) {
      continue;
    }
    seenThreads.add(entry.threadId);
    seenKeys.add(entry.key);
    tabs.push({
      key: entry.key,
      threadId: entry.threadId,
      ...(entry.title === undefined ? {} : { title: entry.title }),
    });
    if (tabs.length >= max) {
      break;
    }
  }
  return tabs;
}
