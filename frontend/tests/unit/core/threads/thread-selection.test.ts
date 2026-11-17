import { describe, expect, it } from "@rstest/core";

import {
  partitionBulkResults,
  settleWithConcurrency,
  uniqueThreadIds,
} from "@/core/threads/bulk";
import {
  combineSelectionOrder,
  EMPTY_THREAD_SELECTION,
  pruneSelection,
  recentListSelectionOrder,
  removeFromSelection,
  replaceSelection,
  selectAll,
  selectRange,
  toggleThread,
  type SelectionFolderNode,
  type ThreadSelection,
} from "@/core/threads/thread-selection";

function selection(ids: string[], anchorId: string | null): ThreadSelection {
  return { ids: new Set(ids), anchorId };
}

const ids = (value: ThreadSelection) => [...value.ids].sort();

const ORDER = ["a", "b", "c", "d", "e"];

describe("toggleThread", () => {
  it("adds, removes and moves the anchor to the toggled row", () => {
    const one = toggleThread(EMPTY_THREAD_SELECTION, "b");
    expect(ids(one)).toEqual(["b"]);
    expect(one.anchorId).toBe("b");
    const two = toggleThread(one, "d");
    expect(ids(two)).toEqual(["b", "d"]);
    const three = toggleThread(two, "b");
    expect(ids(three)).toEqual(["d"]);
    expect(three.anchorId).toBe("b");
    // The input is never mutated: a store compares snapshots by reference.
    expect(ids(one)).toEqual(["b"]);
  });
});

describe("selectRange", () => {
  it("selects the inclusive run between anchor and target, in either direction", () => {
    expect(ids(selectRange(selection(["b"], "b"), ORDER, "d"))).toEqual([
      "b",
      "c",
      "d",
    ]);
    expect(ids(selectRange(selection(["d"], "d"), ORDER, "a"))).toEqual([
      "a",
      "b",
      "c",
      "d",
    ]);
  });

  it("keeps rows selected outside the run and moves the anchor to the target", () => {
    const next = selectRange(selection(["a", "c"], "c"), ORDER, "e");
    expect(ids(next)).toEqual(["a", "c", "d", "e"]);
    expect(next.anchorId).toBe("e");
  });

  it("clears the run when the clicked row was already selected", () => {
    const next = selectRange(selection(["a", "b", "c", "d"], "a"), ORDER, "c");
    expect(ids(next)).toEqual(["d"]);
  });

  it("falls back to a toggle without a usable anchor", () => {
    // Never anchored.
    expect(ids(selectRange(EMPTY_THREAD_SELECTION, ORDER, "c"))).toEqual(["c"]);
    // The anchor sits in a folder that has since collapsed.
    const stale = selectRange(selection(["x"], "x"), ORDER, "c");
    expect(ids(stale)).toEqual(["c", "x"]);
    expect(stale.anchorId).toBe("c");
    // The target is not rendered either.
    expect(ids(selectRange(selection(["a"], "a"), ORDER, "zz"))).toEqual([
      "a",
      "zz",
    ]);
  });
});

describe("selectAll, replaceSelection, removeFromSelection and pruneSelection", () => {
  it("selectAll adds the rendered rows and keeps hidden selected ones", () => {
    const next = selectAll(selection(["hidden"], "hidden"), ORDER);
    expect(ids(next)).toEqual(["a", "b", "c", "d", "e", "hidden"]);
    expect(next.anchorId).toBe("hidden");
  });

  it("answers the same reference when nothing changes", () => {
    const all = selection(ORDER, "a");
    expect(selectAll(all, ORDER)).toBe(all);
    expect(replaceSelection(all, [...ORDER].reverse())).toBe(all);
    expect(pruneSelection(all, () => true)).toBe(all);
    expect(removeFromSelection(all, ["elsewhere"])).toBe(all);
  });

  it("removeFromSelection unticks only the given rows, and their anchor", () => {
    // A finished action unticks what it handled; "c", ticked while it ran,
    // and "d", left out of it, stay.
    const next = removeFromSelection(selection(["a", "b", "c", "d"], "c"), [
      "a",
      "b",
      "unticked-meanwhile",
    ]);
    expect(ids(next)).toEqual(["c", "d"]);
    expect(next.anchorId).toBe("c");
    expect(removeFromSelection(selection(["a", "b"], "a"), ["a"])).toEqual(
      selection(["b"], null),
    );
  });

  it("replaceSelection keeps the anchor only while it is still selected", () => {
    expect(replaceSelection(selection(["a", "b"], "a"), ["a"]).anchorId).toBe(
      "a",
    );
    const next = replaceSelection(selection(["a", "b"], "a"), ["b"]);
    expect(ids(next)).toEqual(["b"]);
    expect(next.anchorId).toBeNull();
  });

  it("pruneSelection drops ids that are gone, and a gone anchor", () => {
    const present = new Set(["a", "c"]);
    const next = pruneSelection(selection(["a", "b", "c"], "b"), (id) =>
      present.has(id),
    );
    expect(ids(next)).toEqual(["a", "c"]);
    expect(next.anchorId).toBeNull();
  });
});

describe("recentListSelectionOrder", () => {
  // work > (reports, drafts); personal (collapsed)
  const tree: SelectionFolderNode[] = [
    {
      folder: { id: "work" },
      children: [
        { folder: { id: "reports" }, children: [] },
        { folder: { id: "drafts" }, children: [] },
      ],
    },
    { folder: { id: "personal" }, children: [] },
  ];
  const folderThreadIds = new Map<string, string[]>([
    ["work", ["w1", "w2"]],
    ["reports", ["r1"]],
    ["drafts", ["d1"]],
    ["personal", ["p1"]],
  ]);

  it("mirrors the render: subfolders before the folder's own chats, then the root", () => {
    expect(
      recentListSelectionOrder({
        tree,
        expandedFolderIds: new Set(["work", "reports", "drafts"]),
        folderThreadIds,
        rootThreadIds: ["root1", "root2"],
      }),
    ).toEqual(["r1", "d1", "w1", "w2", "root1", "root2"]);
  });

  it("leaves out everything under a collapsed folder, subfolders included", () => {
    expect(
      recentListSelectionOrder({
        // `reports` is open, but its parent is not, so it is not on screen.
        tree,
        expandedFolderIds: new Set(["reports", "personal"]),
        folderThreadIds,
        rootThreadIds: ["root1"],
      }),
    ).toEqual(["p1", "root1"]);
  });
});

describe("combineSelectionOrder", () => {
  it("stacks sections by rank and counts a doubly listed row once", () => {
    expect(
      combineSelectionOrder([
        { rank: [1], ids: ["r1", "shared"] },
        { rank: [0, 1], ids: ["p2"] },
        { rank: [0, 0], ids: ["p1", "shared"] },
      ]),
    ).toEqual(["p1", "shared", "p2", "r1"]);
  });
});

describe("bulk helpers", () => {
  it("settleWithConcurrency keeps input order, bounds the work in flight and survives rejections", async () => {
    let inFlight = 0;
    let peak = 0;
    const results = await settleWithConcurrency(
      [1, 2, 3, 4, 5, 6, 7],
      3,
      async (value) => {
        inFlight += 1;
        peak = Math.max(peak, inFlight);
        await new Promise((resolve) => setTimeout(resolve, 8 - value));
        inFlight -= 1;
        if (value === 4) {
          throw new Error("four");
        }
        return value * 10;
      },
    );
    expect(peak).toBe(3);
    expect(
      results.map((result) =>
        result.status === "fulfilled" ? result.value : "rejected",
      ),
    ).toEqual([10, 20, 30, "rejected", 50, 60, 70]);
  });

  it("partitionBulkResults reads the HTTP status off a failure", () => {
    const { succeeded, failed } = partitionBulkResults(
      ["a", "b", "c"],
      [
        { status: "fulfilled", value: null },
        { status: "rejected", reason: { status: 409 } },
        { status: "rejected", reason: new Error("offline") },
      ],
    );
    expect(succeeded).toEqual(["a"]);
    expect(failed.map((failure) => [failure.threadId, failure.status])).toEqual(
      [
        ["b", 409],
        ["c", undefined],
      ],
    );
  });

  it("uniqueThreadIds keeps first-seen order", () => {
    expect(uniqueThreadIds(["b", "a", "b", "c", "a"])).toEqual(["b", "a", "c"]);
  });
});
