import { describe, expect, it } from "@rstest/core";

import {
  chatTabsStorageKey,
  closeTab,
  closeTabByThreadId,
  deserializeChatTabs,
  findTabByKey,
  findTabByThreadId,
  isThreadPinned,
  MAX_CHAT_TABS,
  moveItem,
  pinTab,
  reorderTabsByKey,
  serializeChatTabs,
  setTabTitle,
  updateTabThreadId,
  type ChatTab,
} from "@/core/threads/chat-tabs";

function tab(key: string, threadId: string, title?: string): ChatTab {
  return { key, threadId, ...(title === undefined ? {} : { title }) };
}

describe("chat tabs model", () => {
  describe("chatTabsStorageKey", () => {
    it("scopes per user and falls back to anonymous", () => {
      expect(chatTabsStorageKey("user-1")).toBe("deerflow.chat-tabs.user-1");
      expect(chatTabsStorageKey(null)).toBe("deerflow.chat-tabs.anonymous");
      expect(chatTabsStorageKey(undefined)).toBe(
        "deerflow.chat-tabs.anonymous",
      );
    });
  });

  describe("pinTab", () => {
    it("appends a new tab", () => {
      const next = pinTab([], tab("k1", "t1"));
      expect(next).toEqual([tab("k1", "t1")]);
    });

    it("is idempotent by thread id and returns the same reference", () => {
      const tabs = [tab("k1", "t1")];
      const next = pinTab(tabs, tab("k2", "t1"));
      expect(next).toBe(tabs);
    });

    it("refuses to exceed the cap and returns the same reference", () => {
      const full = Array.from({ length: MAX_CHAT_TABS }, (_, i) =>
        tab(`k${i}`, `t${i}`),
      );
      const next = pinTab(full, tab("kx", "tx"));
      expect(next).toBe(full);
      expect(next).toHaveLength(MAX_CHAT_TABS);
    });

    it("honors a custom max", () => {
      const tabs = [tab("k1", "t1")];
      expect(pinTab(tabs, tab("k2", "t2"), 1)).toBe(tabs);
    });
  });

  describe("closeTab / closeTabByThreadId", () => {
    it("removes by key", () => {
      const tabs = [tab("k1", "t1"), tab("k2", "t2")];
      expect(closeTab(tabs, "k1")).toEqual([tab("k2", "t2")]);
    });

    it("removes by thread id", () => {
      const tabs = [tab("k1", "t1"), tab("k2", "t2")];
      expect(closeTabByThreadId(tabs, "t2")).toEqual([tab("k1", "t1")]);
    });

    it("returns the same reference when nothing matches", () => {
      const tabs = [tab("k1", "t1")];
      expect(closeTab(tabs, "nope")).toBe(tabs);
      expect(closeTabByThreadId(tabs, "nope")).toBe(tabs);
    });
  });

  describe("moveItem", () => {
    it("moves an item forward", () => {
      expect(moveItem([1, 2, 3, 4], 0, 2)).toEqual([2, 3, 1, 4]);
    });

    it("moves an item backward", () => {
      expect(moveItem([1, 2, 3, 4], 3, 1)).toEqual([1, 4, 2, 3]);
    });

    it("no-ops on equal / out-of-range indices", () => {
      const arr = [1, 2, 3];
      expect(moveItem(arr, 1, 1)).toBe(arr);
      expect(moveItem(arr, -1, 2)).toBe(arr);
      expect(moveItem(arr, 0, 5)).toBe(arr);
    });
  });

  describe("reorderTabsByKey", () => {
    it("drops the source into the target's slot", () => {
      const tabs = [tab("a", "ta"), tab("b", "tb"), tab("c", "tc")];
      expect(reorderTabsByKey(tabs, "a", "c")).toEqual([
        tab("b", "tb"),
        tab("c", "tc"),
        tab("a", "ta"),
      ]);
    });

    it("no-ops when the source equals the target or is unknown", () => {
      const tabs = [tab("a", "ta"), tab("b", "tb")];
      expect(reorderTabsByKey(tabs, "a", "a")).toBe(tabs);
      expect(reorderTabsByKey(tabs, "a", "zzz")).toBe(tabs);
    });
  });

  describe("updateTabThreadId (new → real promotion)", () => {
    it("renames a tab's thread id while keeping its stable key", () => {
      const tabs = [tab("k1", "new-uuid")];
      expect(updateTabThreadId(tabs, "k1", "real-id")).toEqual([
        tab("k1", "real-id"),
      ]);
    });

    it("drops a duplicate tab that already holds the promoted id", () => {
      const tabs = [tab("k1", "new-uuid"), tab("k2", "real-id")];
      const next = updateTabThreadId(tabs, "k1", "real-id");
      expect(next).toEqual([tab("k1", "real-id")]);
    });

    it("no-ops for an unknown key", () => {
      const tabs = [tab("k1", "t1")];
      expect(updateTabThreadId(tabs, "missing", "x")).toBe(tabs);
    });
  });

  describe("setTabTitle", () => {
    it("updates the cached title", () => {
      const tabs = [tab("k1", "t1")];
      expect(setTabTitle(tabs, "t1", "Hello")).toEqual([
        tab("k1", "t1", "Hello"),
      ]);
    });

    it("returns the same reference when the title is unchanged", () => {
      const tabs = [tab("k1", "t1", "Hello")];
      expect(setTabTitle(tabs, "t1", "Hello")).toBe(tabs);
    });
  });

  describe("lookups", () => {
    it("finds by thread id and key", () => {
      const tabs = [tab("k1", "t1"), tab("k2", "t2")];
      expect(findTabByThreadId(tabs, "t2")).toEqual(tab("k2", "t2"));
      expect(findTabByKey(tabs, "k1")).toEqual(tab("k1", "t1"));
      expect(isThreadPinned(tabs, "t1")).toBe(true);
      expect(isThreadPinned(tabs, "nope")).toBe(false);
    });
  });

  describe("serialize / deserialize round-trip", () => {
    it("round-trips a valid list", () => {
      const tabs = [tab("k1", "t1", "First"), tab("k2", "t2")];
      expect(deserializeChatTabs(serializeChatTabs(tabs))).toEqual(tabs);
    });

    it("returns an empty list for null / bad JSON / non-array", () => {
      expect(deserializeChatTabs(null)).toEqual([]);
      expect(deserializeChatTabs("")).toEqual([]);
      expect(deserializeChatTabs("{not json")).toEqual([]);
      expect(deserializeChatTabs('{"a":1}')).toEqual([]);
    });

    it("drops malformed entries and collapses duplicates", () => {
      const raw = JSON.stringify([
        { key: "k1", threadId: "t1" },
        { key: "k2" }, // missing threadId
        { key: "k3", threadId: "t1" }, // duplicate thread id
        { key: "k1", threadId: "t9" }, // duplicate key
        { key: "k4", threadId: "t4", title: 5 }, // bad title type
        { key: "k5", threadId: "t5", title: "ok" },
      ]);
      expect(deserializeChatTabs(raw)).toEqual([
        tab("k1", "t1"),
        tab("k5", "t5", "ok"),
      ]);
    });

    it("caps a tampered store at the ceiling", () => {
      const raw = JSON.stringify(
        Array.from({ length: MAX_CHAT_TABS + 5 }, (_, i) => ({
          key: `k${i}`,
          threadId: `t${i}`,
        })),
      );
      expect(deserializeChatTabs(raw)).toHaveLength(MAX_CHAT_TABS);
    });
  });
});
