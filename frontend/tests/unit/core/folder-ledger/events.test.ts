import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";

import {
  listenForDeletedThreads,
  notifyThreadsDeleted,
  THREADS_DELETED_COALESCE_MS,
  THREADS_DELETED_EVENT,
} from "@/core/folder-ledger/events";

beforeEach(() => {
  rs.useFakeTimers();
  // The seam is a window event; node has EventTarget but no window.
  rs.stubGlobal("window", new EventTarget());
});

afterEach(() => {
  rs.useRealTimers();
  rs.unstubAllGlobals();
});

describe("deleted-conversation notifications", () => {
  it("coalesces a burst of deletions into one batch after a quiet period", () => {
    const onBatch = rs.fn();
    const stop = listenForDeletedThreads(onBatch);

    notifyThreadsDeleted(["a", "sidecar-a"]);
    rs.advanceTimersByTime(THREADS_DELETED_COALESCE_MS - 1);
    notifyThreadsDeleted(["b", "a"]);
    rs.advanceTimersByTime(THREADS_DELETED_COALESCE_MS - 1);
    expect(onBatch).not.toHaveBeenCalled();

    rs.advanceTimersByTime(1);
    expect(onBatch).toHaveBeenCalledTimes(1);
    expect(onBatch).toHaveBeenCalledWith(["a", "sidecar-a", "b"]);

    // The next deletion starts a new batch.
    notifyThreadsDeleted(["c"]);
    rs.advanceTimersByTime(THREADS_DELETED_COALESCE_MS);
    expect(onBatch).toHaveBeenLastCalledWith(["c"]);
    stop();
  });

  it("ignores empty or malformed notifications", () => {
    const onBatch = rs.fn();
    const stop = listenForDeletedThreads(onBatch);
    notifyThreadsDeleted([]);
    notifyThreadsDeleted([""]);
    window.dispatchEvent(
      new CustomEvent(THREADS_DELETED_EVENT, { detail: { threadIds: "a" } }),
    );
    window.dispatchEvent(new Event(THREADS_DELETED_EVENT));
    rs.advanceTimersByTime(THREADS_DELETED_COALESCE_MS * 2);
    expect(onBatch).not.toHaveBeenCalled();
    stop();
  });

  it("drops an undelivered batch and stops listening on unsubscribe", () => {
    const onBatch = rs.fn();
    const stop = listenForDeletedThreads(onBatch);
    notifyThreadsDeleted(["a"]);
    stop();
    rs.advanceTimersByTime(THREADS_DELETED_COALESCE_MS);
    notifyThreadsDeleted(["b"]);
    rs.advanceTimersByTime(THREADS_DELETED_COALESCE_MS);
    expect(onBatch).not.toHaveBeenCalled();
  });
});
