import { expect, test } from "@rstest/core";

import {
  buildPendingEditSendKey,
  takePendingEditSend,
  writePendingEditSend,
  type PendingEditSendStorage,
} from "@/core/threads/pending-edit-send";

function memoryStorage(): PendingEditSendStorage & { size: () => number } {
  const entries = new Map<string, string>();
  return {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => {
      entries.set(key, value);
    },
    removeItem: (key) => {
      entries.delete(key);
    },
    size: () => entries.size,
  };
}

test("the edited message survives the navigation to its version thread", () => {
  const storage = memoryStorage();

  writePendingEditSend(storage, "thread-1", { text: "edited prompt" });

  expect(takePendingEditSend(storage, "thread-1")).toEqual({
    text: "edited prompt",
  });
});

test("reading consumes the entry so an edit can never be replayed twice", () => {
  const storage = memoryStorage();
  writePendingEditSend(storage, "thread-1", { text: "edited prompt" });

  takePendingEditSend(storage, "thread-1");

  expect(takePendingEditSend(storage, "thread-1")).toBeNull();
  expect(storage.size()).toBe(0);
});

test("entries are scoped per thread", () => {
  const storage = memoryStorage();
  writePendingEditSend(storage, "thread-1", { text: "one" });

  expect(takePendingEditSend(storage, "thread-2")).toBeNull();
  expect(takePendingEditSend(storage, "thread-1")).toEqual({ text: "one" });
});

test("a thread id with URL-hostile characters still yields one stable key", () => {
  expect(buildPendingEditSendKey("a/b?c")).toBe(
    "deerflow:pending-edit-send:v1:a%2Fb%3Fc",
  );
});

test("a foreign or corrupted entry is ignored rather than sent", () => {
  const storage = memoryStorage();
  storage.setItem(
    buildPendingEditSendKey("thread-1"),
    JSON.stringify({ version: 99, text: "from a future format" }),
  );
  storage.setItem(buildPendingEditSendKey("thread-2"), "{not json");

  expect(takePendingEditSend(storage, "thread-1")).toBeNull();
  expect(takePendingEditSend(storage, "thread-2")).toBeNull();
});

test("missing storage is survivable in both directions", () => {
  expect(() =>
    writePendingEditSend(null, "thread-1", { text: "one" }),
  ).not.toThrow();
  expect(takePendingEditSend(null, "thread-1")).toBeNull();
});
