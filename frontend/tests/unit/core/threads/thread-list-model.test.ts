import { describe, expect, it } from "@rstest/core";

import {
  buildThreadListModel,
  canAutoLoadMoreThreads,
  MAX_AUTO_LOADED_ROOT_THREADS,
  MAX_AUTO_SCANNED_THREADS,
} from "@/core/threads/thread-list-model";
import type { AgentThread } from "@/core/threads/types";

function thread(id: string, updatedAt: string): AgentThread {
  return {
    thread_id: id,
    updated_at: updatedAt,
    created_at: updatedAt,
    metadata: {},
    status: "idle",
    values: {},
  } as AgentThread;
}

function pinnedThread(id: string, updatedAt: string): AgentThread {
  return {
    ...thread(id, updatedAt),
    metadata: { deerflow_pinned: true },
  };
}

describe("thread list model", () => {
  it("sorts the full thread list with pinned threads first", () => {
    const unpinned = thread("unpinned", "2026-01-02T00:00:00.000Z");
    const pinned = pinnedThread("pinned", "2026-01-01T00:00:00.000Z");

    const model = buildThreadListModel([[unpinned, pinned]]);

    expect(model.threads).toEqual([pinned, unpinned]);
  });

  it("deduplicates across pages without dropping a loaded conversation", () => {
    const pages = Array.from({ length: 5 }, (_, page) =>
      Array.from({ length: 50 }, (_, index) => {
        const id = String(page * 50 + index);
        return thread(id, new Date(2026, 0, 1, 0, 0, Number(id)).toISOString());
      }),
    );
    pages[1]![0] = pages[0]![0]!;

    const model = buildThreadListModel(pages);

    // 249 unique of 250 fetched, and every one of them stays in the model: the
    // sidebar virtualizes, so truncating at 200 only hid loaded conversations
    // (a folder's members among them) with no way left to ask for them.
    expect(model.threads).toHaveLength(249);
    expect(model.byId.size).toBe(249);
    expect(model.threads.at(-1)).toBe(pages[4]!.at(-1));
  });

  it("returns the same normalized model for unchanged page identity", () => {
    const pages = [[thread("a", "2026-01-01T00:00:00.000Z")]];
    expect(buildThreadListModel(pages)).toBe(buildThreadListModel(pages));
  });
});

describe("canAutoLoadMoreThreads", () => {
  it("keeps paging while the root list is under the budget", () => {
    const rootThreads = Array.from(
      { length: MAX_AUTO_LOADED_ROOT_THREADS - 1 },
      (_, index) =>
        thread(
          `root-${index}`,
          new Date(2026, 0, 1, 0, 0, index).toISOString(),
        ),
    );

    expect(canAutoLoadMoreThreads(rootThreads, rootThreads.length)).toBe(true);
  });

  it("stops paging on its own once the root list is full", () => {
    const rootThreads = Array.from(
      { length: MAX_AUTO_LOADED_ROOT_THREADS },
      (_, index) =>
        thread(
          `root-${index}`,
          new Date(2026, 0, 1, 0, 0, index).toISOString(),
        ),
    );

    expect(canAutoLoadMoreThreads(rootThreads, rootThreads.length)).toBe(false);
  });

  it("does not spend the budget on pinned conversations", () => {
    const rootThreads = [
      ...Array.from({ length: MAX_AUTO_LOADED_ROOT_THREADS }, (_, index) =>
        pinnedThread(`pinned-${index}`, "2026-01-01T00:00:00.000Z"),
      ),
      thread("recent", "2026-01-02T00:00:00.000Z"),
    ];

    expect(canAutoLoadMoreThreads(rootThreads, rootThreads.length)).toBe(true);
  });

  it("is asked about the root list only, so filed chats never starve it", () => {
    // The regression this exists for: a user who files their history into
    // folders leaves a nearly empty root list, and a budget counting *every*
    // loaded conversation stops pagination there — the sidebar looks empty and
    // refuses to load the older chats that would fill it.
    const filedCount = MAX_AUTO_LOADED_ROOT_THREADS;
    const rootThreads = [thread("only-root", "2026-01-02T00:00:00.000Z")];

    expect(
      canAutoLoadMoreThreads(rootThreads, rootThreads.length + filedCount),
    ).toBe(true);
  });

  it("stops digging once it has scanned deep enough for root rows", () => {
    // The other half of that budget. Filed conversations do not bring the row
    // target closer, so a history filed away almost entirely would otherwise be
    // paged through end to end on every load, hunting for rows that are not
    // there.
    const rootThreads = [thread("only-root", "2026-01-02T00:00:00.000Z")];

    expect(
      canAutoLoadMoreThreads(rootThreads, MAX_AUTO_SCANNED_THREADS - 1),
    ).toBe(true);
    expect(canAutoLoadMoreThreads(rootThreads, MAX_AUTO_SCANNED_THREADS)).toBe(
      false,
    );
  });
});
