import { describe, expect, it } from "@rstest/core";

import {
  addFolder,
  deserializeExpandedFolderIds,
  folderIdOfThread,
  groupThreadsByFolder,
  MAX_CHAT_FOLDERS,
  MAX_FOLDER_NAME_CHARS,
  normalizeChatFolders,
  normalizeFolderName,
  removeFolder,
  renameFolder,
  THREAD_FOLDER_METADATA_KEY,
  type ChatFolder,
} from "@/core/threads/chat-folders";
import type { AgentThread } from "@/core/threads/types";

function folder(id: string, name: string): ChatFolder {
  return { id, name };
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

  describe("removeFolder", () => {
    it("drops the folder and nothing else", () => {
      expect(
        removeFolder([folder("f1", "Work"), folder("f2", "Personal")], "f1"),
      ).toEqual([folder("f2", "Personal")]);
    });

    it("returns the same reference for an unknown id", () => {
      const folders = [folder("f1", "Work")];
      expect(removeFolder(folders, "nope")).toBe(folders);
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
      const { groups, ungrouped } = groupThreadsByFolder(
        [thread("t1", "f1"), thread("t2")],
        [folder("f1", "Work")],
      );
      expect(groups.map((group) => group.folder.id)).toEqual(["f1"]);
      expect(groups[0]!.threads.map((item) => item.thread_id)).toEqual(["t1"]);
      expect(ungrouped.map((item) => item.thread_id)).toEqual(["t2"]);
    });

    it("falls back to the root for a folder that no longer exists", () => {
      // Deleting a folder on another device must never swallow the chats that
      // still point at it.
      const { groups, ungrouped } = groupThreadsByFolder(
        [thread("t1", "gone"), thread("t2")],
        [folder("f1", "Work")],
      );
      expect(groups[0]!.threads).toEqual([]);
      expect(ungrouped.map((item) => item.thread_id)).toEqual(["t1", "t2"]);
    });

    it("shows every folder, including the empty ones", () => {
      const { groups } = groupThreadsByFolder(
        [thread("t1")],
        [folder("f1", "Work"), folder("f2", "Personal")],
      );
      expect(groups.map((group) => group.folder.id)).toEqual(["f1", "f2"]);
      expect(groups.every((group) => group.threads.length === 0)).toBe(true);
    });

    it("preserves the caller's order inside every partition", () => {
      const { groups, ungrouped } = groupThreadsByFolder(
        [thread("t1", "f1"), thread("t2"), thread("t3", "f1"), thread("t4")],
        [folder("f1", "Work")],
      );
      expect(groups[0]!.threads.map((item) => item.thread_id)).toEqual([
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
      ];
      const { groups, ungrouped } = groupThreadsByFolder(threads, [
        folder("f1", "Work"),
        folder("f2", "Personal"),
      ]);
      const seen = [
        ...groups.flatMap((group) => group.threads),
        ...ungrouped,
      ].map((item) => item.thread_id);
      expect(seen.sort()).toEqual(["t1", "t2", "t3", "t4"]);
      expect(new Set(seen).size).toBe(seen.length);
    });

    it("groups nothing when there are no folders", () => {
      const { groups, ungrouped } = groupThreadsByFolder(
        [thread("t1", "f1"), thread("t2")],
        [],
      );
      expect(groups).toEqual([]);
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
