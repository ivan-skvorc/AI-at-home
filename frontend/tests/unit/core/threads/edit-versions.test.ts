import { describe, expect, test } from "@rstest/core";

import {
  addEditVersionToGroups,
  buildEditVersionThreadMetadata,
  CONVERSATION_START_BASE_MESSAGE_ID,
  EDIT_ACTIVE_VERSION_METADATA_KEY,
  isEditVersionThread,
  readActiveEditVersionThreadId,
  readEditVersionGroups,
  readEditVersionThreadInfo,
  resolveEditVersionLineage,
  resolveEditVersionRootThreadId,
  resolveEditVersionSwitchers,
  type EditVersionGroup,
} from "@/core/threads/edit-versions";

function versionMetadata({
  root = "root",
  parent = "root",
  base = "ai-1",
  turnIndex = 1,
  parentLineage = ["root"],
}: {
  root?: string;
  parent?: string;
  base?: string;
  turnIndex?: number;
  parentLineage?: string[];
} = {}) {
  return buildEditVersionThreadMetadata({
    rootThreadId: root,
    parentThreadId: parent,
    baseMessageId: base,
    turnIndex,
    parentLineage,
  });
}

describe("edit version thread metadata", () => {
  test("marks a version thread so the thread lists can hide it", () => {
    expect(isEditVersionThread({ metadata: versionMetadata() })).toBe(true);
    expect(isEditVersionThread({ metadata: {} })).toBe(false);
    expect(isEditVersionThread({ metadata: undefined })).toBe(false);
  });

  test("round-trips the fields the switcher needs", () => {
    expect(readEditVersionThreadInfo(versionMetadata())).toEqual({
      rootThreadId: "root",
      parentThreadId: "root",
      baseMessageId: "ai-1",
      turnIndex: 1,
      ancestorThreadIds: ["root"],
    });
  });

  test("treats a version with no root or parent as not a version at all", () => {
    // A half-written record must not resolve to a root of `undefined`, which
    // would point every switcher lookup at the wrong thread.
    expect(
      readEditVersionThreadInfo({ deerflow_edit_version: true }),
    ).toBeNull();
    expect(readEditVersionThreadInfo({})).toBeNull();
  });

  test("a thread that is not a version is its own root and lineage", () => {
    expect(resolveEditVersionRootThreadId("root", {})).toBe("root");
    expect(resolveEditVersionLineage("root", {})).toEqual(["root"]);
  });

  test("a version resolves to its family root and full ancestry", () => {
    const metadata = versionMetadata({
      parent: "v1",
      parentLineage: ["root", "v1"],
    });

    expect(resolveEditVersionRootThreadId("v2", metadata)).toBe("root");
    expect(resolveEditVersionLineage("v2", metadata)).toEqual([
      "root",
      "v1",
      "v2",
    ]);
  });
});

describe("edit version groups", () => {
  test("drops malformed entries instead of rendering a broken switcher", () => {
    expect(
      readEditVersionGroups({
        deerflow_edit_version_groups: [
          { base_message_id: "ai-1", turn_index: 1, thread_ids: ["a", "b"] },
          { base_message_id: "ai-2", turn_index: "1", thread_ids: ["a"] },
          { base_message_id: "ai-3", turn_index: 2 },
          { base_message_id: "ai-4", turn_index: 3, thread_ids: [] },
          null,
        ],
      }),
    ).toEqual([
      { base_message_id: "ai-1", turn_index: 1, thread_ids: ["a", "b"] },
    ]);
    expect(readEditVersionGroups({})).toEqual([]);
  });

  test("first edit of a turn records the edited thread as version 1", () => {
    expect(
      addEditVersionToGroups([], {
        baseMessageId: "ai-1",
        turnIndex: 1,
        parentThreadId: "root",
        versionThreadId: "v1",
      }),
    ).toEqual([
      { base_message_id: "ai-1", turn_index: 1, thread_ids: ["root", "v1"] },
    ]);
  });

  test("a second edit of the same turn joins the existing group", () => {
    const groups = addEditVersionToGroups(
      [{ base_message_id: "ai-1", turn_index: 1, thread_ids: ["root", "v1"] }],
      {
        baseMessageId: "ai-1",
        turnIndex: 1,
        parentThreadId: "root",
        versionThreadId: "v2",
      },
    );

    expect(groups).toEqual([
      {
        base_message_id: "ai-1",
        turn_index: 1,
        thread_ids: ["root", "v1", "v2"],
      },
    ]);
  });

  test("an edit at a different turn opens its own group", () => {
    const groups = addEditVersionToGroups(
      [{ base_message_id: "ai-1", turn_index: 1, thread_ids: ["root", "v1"] }],
      {
        baseMessageId: "ai-9",
        turnIndex: 4,
        parentThreadId: "v1",
        versionThreadId: "v2",
      },
    );

    expect(groups).toHaveLength(2);
    expect(groups[1]).toEqual({
      base_message_id: "ai-9",
      turn_index: 4,
      thread_ids: ["v1", "v2"],
    });
  });

  test("re-registering the same version is a no-op", () => {
    const existing: EditVersionGroup[] = [
      { base_message_id: "ai-1", turn_index: 1, thread_ids: ["root", "v1"] },
    ];

    expect(
      addEditVersionToGroups(existing, {
        baseMessageId: "ai-1",
        turnIndex: 1,
        parentThreadId: "root",
        versionThreadId: "v1",
      }),
    ).toEqual(existing);
  });

  test("editing the first message keys the group on the start of the conversation", () => {
    expect(
      addEditVersionToGroups([], {
        baseMessageId: CONVERSATION_START_BASE_MESSAGE_ID,
        turnIndex: 0,
        parentThreadId: "root",
        versionThreadId: "v1",
      })[0]?.base_message_id,
    ).toBe("");
  });
});

describe("switcher resolution", () => {
  const groups: EditVersionGroup[] = [
    { base_message_id: "ai-1", turn_index: 1, thread_ids: ["root", "v1"] },
    { base_message_id: "ai-9", turn_index: 4, thread_ids: ["v1", "v2"] },
  ];

  test("places each group at its own position for the thread being read", () => {
    const switchers = resolveEditVersionSwitchers(groups, ["root"]);

    expect(switchers.get("ai-1")).toEqual({
      baseMessageId: "ai-1",
      turnIndex: 1,
      threadIds: ["root", "v1"],
      currentIndex: 0,
    });
    // The root's turn 4 belongs to a different lineage than v1's, so it must not
    // borrow v1's switcher.
    expect(switchers.has("ai-9")).toBe(false);
  });

  test("a version reads as the later entry of its own group", () => {
    const switchers = resolveEditVersionSwitchers(groups, ["root", "v1"]);

    expect(switchers.get("ai-1")?.currentIndex).toBe(1);
    expect(switchers.get("ai-9")?.currentIndex).toBe(0);
  });

  test("a descendant inherits its ancestor's position in older groups", () => {
    // v2 branched from v1 at turn 4, so at turn 1 it *is* v1's version — the
    // deepest ancestor in the group is the one on screen.
    const switchers = resolveEditVersionSwitchers(groups, ["root", "v1", "v2"]);

    expect(switchers.get("ai-1")?.currentIndex).toBe(1);
    expect(switchers.get("ai-9")?.currentIndex).toBe(1);
  });

  test("ignores a group with a single member and one the thread is not part of", () => {
    expect(
      resolveEditVersionSwitchers(
        [{ base_message_id: "ai-1", turn_index: 1, thread_ids: ["root"] }],
        ["root"],
      ).size,
    ).toBe(0);
    expect(resolveEditVersionSwitchers(groups, ["other"]).size).toBe(0);
  });
});

test("the active version is only read when it names a thread", () => {
  expect(
    readActiveEditVersionThreadId({
      [EDIT_ACTIVE_VERSION_METADATA_KEY]: "v1",
    }),
  ).toBe("v1");
  expect(
    readActiveEditVersionThreadId({ [EDIT_ACTIVE_VERSION_METADATA_KEY]: "" }),
  ).toBeNull();
  expect(readActiveEditVersionThreadId({})).toBeNull();
});
