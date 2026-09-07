import { describe, expect, it } from "@rstest/core";

import {
  addFolder,
  canMoveFolderUnder,
  canNestUnder,
  deserializeExpandedFolderIds,
  flattenFolderTree,
  folderDepth,
  folderIdOfThread,
  folderSubtreeIds,
  groupThreadsByFolder,
  MAX_CHAT_FOLDERS,
  MAX_FOLDER_DEPTH,
  MAX_FOLDER_NAME_CHARS,
  moveFolder,
  normalizeChatFolders,
  normalizeFolderName,
  removeFolder,
  renameFolder,
  THREAD_FOLDER_METADATA_KEY,
  type ChatFolder,
  type ChatFolderNode,
} from "@/core/threads/chat-folders";
import type { AgentThread } from "@/core/threads/types";

function folder(id: string, name: string, parentId?: string): ChatFolder {
  return parentId === undefined ? { id, name } : { id, name, parentId };
}

/** A chain `f1 > f2 > … > fN`, for the depth rules. */
function chain(length: number): ChatFolder[] {
  return Array.from({ length }, (_, index) =>
    folder(
      `f${index + 1}`,
      `Level ${index + 1}`,
      index === 0 ? undefined : `f${index}`,
    ),
  );
}

/** Ids of a rendered tree, parents before children. */
function treeIds(tree: readonly ChatFolderNode[]): string[] {
  return flattenFolderTree(tree).map((node) => node.folder.id);
}

function thread(threadId: string, folderId?: string | null): AgentThread {
  return {
    thread_id: threadId,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    status: "idle",
    metadata:
      folderId === undefined ? {} : { [THREAD_FOLDER_METADATA_KEY]: folderId },
    values: { title: threadId, messages: [] },
  } as unknown as AgentThread;
}

describe("chat folders model", () => {
  describe("normalizeFolderName", () => {
    it("trims and caps, and rejects a name that is only whitespace", () => {
      expect(normalizeFolderName("  Work  ")).toBe("Work");
      expect(normalizeFolderName("   ")).toBeNull();
      expect(normalizeFolderName("")).toBeNull();
      expect(normalizeFolderName("n".repeat(500))).toHaveLength(
        MAX_FOLDER_NAME_CHARS,
      );
    });
  });

  describe("addFolder", () => {
    it("appends so list order stays display order", () => {
      const folders = addFolder(
        [folder("f1", "Work")],
        folder("f2", "Personal"),
      );
      expect(folders).toEqual([folder("f1", "Work"), folder("f2", "Personal")]);
    });

    it("returns the same reference when nothing can change", () => {
      const folders = [folder("f1", "Work")];
      expect(addFolder(folders, folder("f1", "Duplicate"))).toBe(folders);
      expect(addFolder(folders, folder("f2", "   "))).toBe(folders);
      expect(addFolder(folders, folder("  ", "Nameless id"))).toBe(folders);
    });

    it("refuses to grow past the cap the server also enforces", () => {
      const full = Array.from({ length: MAX_CHAT_FOLDERS }, (_, index) =>
        folder(`f${index}`, `Folder ${index}`),
      );
      expect(addFolder(full, folder("extra", "Extra"))).toBe(full);
    });

    it("nests under an existing parent and keeps the link", () => {
      expect(
        addFolder([folder("f1", "Work")], folder("f2", "Invoices", "f1")),
      ).toEqual([folder("f1", "Work"), folder("f2", "Invoices", "f1")]);
    });

    it("refuses an unknown parent rather than silently creating at the top", () => {
      // Quietly dropping the parent would put the folder somewhere the user did
      // not ask for, which looks exactly like the create having worked.
      const folders = [folder("f1", "Work")];
      expect(addFolder(folders, folder("f2", "Invoices", "nope"))).toBe(
        folders,
      );
    });

    it("refuses a parent that is already at the depth limit", () => {
      const deepest = chain(MAX_FOLDER_DEPTH);
      expect(
        addFolder(deepest, folder("extra", "Extra", `f${MAX_FOLDER_DEPTH}`)),
      ).toBe(deepest);
      // One level shallower still has room.
      const shallower = chain(MAX_FOLDER_DEPTH - 1);
      expect(
        addFolder(
          shallower,
          folder("extra", "Extra", `f${MAX_FOLDER_DEPTH - 1}`),
        ),
      ).not.toBe(shallower);
    });
  });

  describe("folderDepth / canNestUnder", () => {
    it("counts the top level as 1 and answers 0 for an unknown folder", () => {
      const folders = chain(3);
      expect(folderDepth(folders, "f1")).toBe(1);
      expect(folderDepth(folders, "f3")).toBe(3);
      expect(folderDepth(folders, "nope")).toBe(0);
    });

    it("allows the top level and refuses an unknown or maxed-out parent", () => {
      const folders = chain(MAX_FOLDER_DEPTH);
      expect(canNestUnder(folders, null)).toBe(true);
      expect(canNestUnder(folders, "nope")).toBe(false);
      expect(canNestUnder(folders, `f${MAX_FOLDER_DEPTH}`)).toBe(false);
      expect(canNestUnder(folders, `f${MAX_FOLDER_DEPTH - 1}`)).toBe(true);
    });
  });

  describe("renameFolder", () => {
    it("renames in place and leaves order alone", () => {
      expect(
        renameFolder(
          [folder("f1", "Work"), folder("f2", "Personal")],
          "f2",
          "  Home  ",
        ),
      ).toEqual([folder("f1", "Work"), folder("f2", "Home")]);
    });

    it("is a no-op for a blank name, an unknown id, or the same name", () => {
      const folders = [folder("f1", "Work")];
      expect(renameFolder(folders, "f1", "   ")).toBe(folders);
      expect(renameFolder(folders, "nope", "Other")).toBe(folders);
      expect(renameFolder(folders, "f1", "Work")).toBe(folders);
    });
  });

  describe("removeFolder / folderSubtreeIds", () => {
    it("drops the folder and nothing else", () => {
      expect(
        removeFolder([folder("f1", "Work"), folder("f2", "Personal")], "f1"),
      ).toEqual([folder("f2", "Personal")]);
    });

    it("returns the same reference for an unknown id", () => {
      const folders = [folder("f1", "Work")];
      expect(removeFolder(folders, "nope")).toBe(folders);
    });

    it("takes the subfolders with it and leaves the siblings alone", () => {
      // A subfolder left behind would be an orphan pointing at a folder that no
      // longer exists — visible only because the normalizer promotes it, which
      // is a repair, not the behaviour anyone asked for.
      const folders = [
        folder("f1", "Work"),
        folder("f2", "Invoices", "f1"),
        folder("f3", "2026", "f2"),
        folder("f4", "Personal"),
      ];
      expect(folderSubtreeIds(folders, "f1")).toEqual(["f1", "f2", "f3"]);
      expect(removeFolder(folders, "f1")).toEqual([folder("f4", "Personal")]);
    });

    it("answers an empty subtree for an unknown folder", () => {
      expect(folderSubtreeIds([folder("f1", "Work")], "nope")).toEqual([]);
    });
  });

  describe("moveFolder / canMoveFolderUnder", () => {
    const nested = () => [
      folder("f1", "Work"),
      folder("f2", "Invoices", "f1"),
      folder("f3", "2026", "f2"),
      folder("f4", "Personal"),
    ];

    it("re-parents a folder and carries its subtree along", () => {
      const moved = moveFolder(nested(), "f2", "f4");
      expect(moved).toEqual([
        folder("f1", "Work"),
        folder("f2", "Invoices", "f4"),
        // The child follows because it points at f2, not at a path.
        folder("f3", "2026", "f2"),
        folder("f4", "Personal"),
      ]);
    });

    it("promotes to the top level, dropping the parent key entirely", () => {
      expect(moveFolder(nested(), "f3", null)).toEqual([
        folder("f1", "Work"),
        folder("f2", "Invoices", "f1"),
        folder("f3", "2026"),
        folder("f4", "Personal"),
      ]);
    });

    it("refuses to move a folder into itself or its own descendant", () => {
      // Both detach the whole subtree from the tree: the folders stop
      // rendering, the chats inside them fall back to the root list, and
      // nothing says why. The rule is the only thing standing between the user
      // and that state.
      const folders = nested();
      expect(canMoveFolderUnder(folders, "f1", "f1")).toBe(false);
      expect(canMoveFolderUnder(folders, "f1", "f2")).toBe(false);
      expect(canMoveFolderUnder(folders, "f1", "f3")).toBe(false);
      expect(moveFolder(folders, "f1", "f3")).toBe(folders);
    });

    it("refuses a move that would push a descendant past the depth limit", () => {
      // f1 > f2 with one level of headroom; moving that pair under the deepest
      // folder that could still take a *leaf* would put f2 out of range.
      const folders = [
        ...chain(MAX_FOLDER_DEPTH - 1),
        folder("a1", "Branch"),
        folder("a2", "Sub", "a1"),
      ];
      expect(
        canMoveFolderUnder(folders, "a1", `f${MAX_FOLDER_DEPTH - 1}`),
      ).toBe(false);
      expect(
        canMoveFolderUnder(folders, "a2", `f${MAX_FOLDER_DEPTH - 1}`),
      ).toBe(true);
      expect(moveFolder(folders, "a1", `f${MAX_FOLDER_DEPTH - 1}`)).toBe(
        folders,
      );
    });

    it("is a no-op when the folder is already there", () => {
      const folders = nested();
      expect(moveFolder(folders, "f2", "f1")).toBe(folders);
      expect(moveFolder(folders, "f4", null)).toBe(folders);
      expect(moveFolder(folders, "nope", null)).toBe(folders);
    });
  });

  describe("normalizeChatFolders", () => {
    it("drops malformed entries rather than throwing", () => {
      expect(
        normalizeChatFolders([
          "not-an-object",
          null,
          { id: "f1" },
          { name: "no id" },
          { id: "  ", name: "blank id" },
          { id: "f2", name: "   " },
          { id: "  f3  ", name: "  Work  " },
        ]),
      ).toEqual([folder("f3", "Work")]);
    });

    it("collapses duplicate ids first-wins and caps the list", () => {
      expect(
        normalizeChatFolders([
          { id: "f1", name: "First" },
          { id: "f1", name: "Second" },
        ]),
      ).toEqual([folder("f1", "First")]);
      expect(
        normalizeChatFolders(
          Array.from({ length: MAX_CHAT_FOLDERS * 3 }, (_, index) => ({
            id: `f${index}`,
            name: `Folder ${index}`,
          })),
        ),
      ).toHaveLength(MAX_CHAT_FOLDERS);
    });

    it("degrades a non-array to an empty list", () => {
      expect(normalizeChatFolders({ f1: "Work" })).toEqual([]);
      expect(normalizeChatFolders(undefined)).toEqual([]);
    });

    it("keeps a valid parent link and omits the key at the top level", () => {
      // The absent key is the property: a stored `parentId: null` would make a
      // flat list stop round-tripping byte-for-byte through the tree feature.
      const normalized = normalizeChatFolders([
        { id: "f1", name: "Work" },
        { id: "f2", name: "Invoices", parentId: "f1" },
      ]);
      expect(normalized).toEqual([
        folder("f1", "Work"),
        folder("f2", "Invoices", "f1"),
      ]);
      expect("parentId" in normalized[0]!).toBe(false);
    });

    it("promotes a folder whose parent is unknown rather than dropping it", () => {
      // Dropping it would take the chats inside it out of their folder with no
      // way back; promoting it leaves them visible, named, and one drag away.
      expect(
        normalizeChatFolders([
          { id: "f2", name: "Invoices", parentId: "gone" },
        ]),
      ).toEqual([folder("f2", "Invoices")]);
    });

    it("breaks a parent cycle instead of hanging or hiding the branch", () => {
      // A cycle is unreachable from every root, so a renderer that walks down
      // from the roots silently loses every folder in it.
      const normalized = normalizeChatFolders([
        { id: "f1", name: "One", parentId: "f2" },
        { id: "f2", name: "Two", parentId: "f1" },
        { id: "f3", name: "Self", parentId: "f3" },
      ]);
      expect(normalized.map((entry) => entry.id).sort()).toEqual([
        "f1",
        "f2",
        "f3",
      ]);
      expect(treeIds(groupThreadsByFolder([], normalized).tree).sort()).toEqual(
        ["f1", "f2", "f3"],
      );
    });

    it("pulls an over-deep chain back into range from the top of the breach", () => {
      const normalized = normalizeChatFolders(chain(MAX_FOLDER_DEPTH + 2));
      // Nothing is lost, and nothing is left deeper than the limit.
      expect(normalized).toHaveLength(MAX_FOLDER_DEPTH + 2);
      for (const entry of normalized) {
        expect(folderDepth(normalized, entry.id)).toBeLessThanOrEqual(
          MAX_FOLDER_DEPTH,
        );
      }
      // Orphaning the *shallowest* offender is what fixes the whole tail in one
      // move: the folder just past the limit becomes a new top-level root.
      expect(folderDepth(normalized, `f${MAX_FOLDER_DEPTH + 1}`)).toBe(1);
      expect(folderDepth(normalized, `f${MAX_FOLDER_DEPTH + 2}`)).toBe(2);
    });
  });

  describe("folderIdOfThread", () => {
    it("reads the metadata key, treating blank and non-string as the root", () => {
      expect(folderIdOfThread(thread("t1", "f1"))).toBe("f1");
      expect(folderIdOfThread(thread("t2"))).toBeNull();
      expect(folderIdOfThread(thread("t3", null))).toBeNull();
      expect(folderIdOfThread(thread("t4", "   "))).toBeNull();
    });
  });

  describe("groupThreadsByFolder", () => {
    it("lists a filed chat inside its folder and NOT at the root", () => {
      const { tree, ungrouped } = groupThreadsByFolder(
        [thread("t1", "f1"), thread("t2")],
        [folder("f1", "Work")],
      );
      expect(treeIds(tree)).toEqual(["f1"]);
      expect(tree[0]!.threads.map((item) => item.thread_id)).toEqual(["t1"]);
      expect(ungrouped.map((item) => item.thread_id)).toEqual(["t2"]);
    });

    it("lists a chat filed in a subfolder there and NOT in its parent", () => {
      // The exactly-once rule has to survive nesting: a chat two levels down
      // that is *also* listed in the parent duplicates it in the sidebar, and a
      // chat listed only in the parent is filed in a folder it is not in.
      const { tree, ungrouped } = groupThreadsByFolder(
        [thread("t1", "f2"), thread("t2", "f1"), thread("t3")],
        [folder("f1", "Work"), folder("f2", "Invoices", "f1")],
      );
      expect(treeIds(tree)).toEqual(["f1", "f2"]);
      const work = tree[0]!;
      expect(work.threads.map((item) => item.thread_id)).toEqual(["t2"]);
      expect(work.children[0]!.threads.map((item) => item.thread_id)).toEqual([
        "t1",
      ]);
      expect(ungrouped.map((item) => item.thread_id)).toEqual(["t3"]);
    });

    it("counts the whole subtree, so a collapsed parent never reads empty", () => {
      const { tree } = groupThreadsByFolder(
        [thread("t1", "f3"), thread("t2", "f2"), thread("t3", "f1")],
        [
          folder("f1", "Work"),
          folder("f2", "Invoices", "f1"),
          folder("f3", "2026", "f2"),
        ],
      );
      const work = tree[0]!;
      expect(work.totalThreadCount).toBe(3);
      expect(work.children[0]!.totalThreadCount).toBe(2);
      expect(work.children[0]!.children[0]!.totalThreadCount).toBe(1);
      // The direct membership is untouched by the roll-up.
      expect(work.threads.map((item) => item.thread_id)).toEqual(["t3"]);
    });

    it("falls back to the root for a folder that no longer exists", () => {
      // Deleting a folder on another device must never swallow the chats that
      // still point at it.
      const { tree, ungrouped } = groupThreadsByFolder(
        [thread("t1", "gone"), thread("t2")],
        [folder("f1", "Work")],
      );
      expect(tree[0]!.threads).toEqual([]);
      expect(ungrouped.map((item) => item.thread_id)).toEqual(["t1", "t2"]);
    });

    it("renders a folder whose parent is gone, at the top level", () => {
      // A branch detached from the tree would stop rendering entirely, taking
      // the chats inside it out of every list — including the root one, which
      // is the fallback that is supposed to catch exactly this.
      const { tree } = groupThreadsByFolder(
        [thread("t1", "f2")],
        [folder("f2", "Invoices", "vanished")],
      );
      expect(treeIds(tree)).toEqual(["f2"]);
      expect(tree[0]!.threads.map((item) => item.thread_id)).toEqual(["t1"]);
    });

    it("shows every folder, including the empty ones", () => {
      const { tree } = groupThreadsByFolder(
        [thread("t1")],
        [folder("f1", "Work"), folder("f2", "Personal")],
      );
      expect(treeIds(tree)).toEqual(["f1", "f2"]);
      expect(
        flattenFolderTree(tree).every((node) => node.threads.length === 0),
      ).toBe(true);
    });

    it("preserves the caller's order inside every partition", () => {
      const { tree, ungrouped } = groupThreadsByFolder(
        [thread("t1", "f1"), thread("t2"), thread("t3", "f1"), thread("t4")],
        [folder("f1", "Work")],
      );
      expect(tree[0]!.threads.map((item) => item.thread_id)).toEqual([
        "t1",
        "t3",
      ]);
      expect(ungrouped.map((item) => item.thread_id)).toEqual(["t2", "t4"]);
    });

    it("accounts for every thread exactly once", () => {
      const threads = [
        thread("t1", "f1"),
        thread("t2", "f2"),
        thread("t3", "unknown"),
        thread("t4"),
        thread("t5", "f3"),
      ];
      const { tree, ungrouped } = groupThreadsByFolder(threads, [
        folder("f1", "Work"),
        folder("f2", "Personal"),
        folder("f3", "Invoices", "f1"),
      ]);
      const seen = [
        ...flattenFolderTree(tree).flatMap((node) => node.threads),
        ...ungrouped,
      ].map((item) => item.thread_id);
      expect(seen.sort()).toEqual(["t1", "t2", "t3", "t4", "t5"]);
      expect(new Set(seen).size).toBe(seen.length);
    });

    it("groups nothing when there are no folders", () => {
      const { tree, ungrouped } = groupThreadsByFolder(
        [thread("t1", "f1"), thread("t2")],
        [],
      );
      expect(tree).toEqual([]);
      expect(ungrouped.map((item) => item.thread_id)).toEqual(["t1", "t2"]);
    });
  });

  describe("deserializeExpandedFolderIds", () => {
    it("parses an id array and degrades on anything else", () => {
      expect([...deserializeExpandedFolderIds('["f1","f2"]')]).toEqual([
        "f1",
        "f2",
      ]);
      expect(deserializeExpandedFolderIds("not json").size).toBe(0);
      expect(deserializeExpandedFolderIds('{"f1":true}').size).toBe(0);
      expect(deserializeExpandedFolderIds(null).size).toBe(0);
      expect([...deserializeExpandedFolderIds('["f1",7,"",null]')]).toEqual([
        "f1",
      ]);
    });
  });
});
