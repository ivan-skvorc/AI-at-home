import { describe, expect, it } from "@rstest/core";

import { formatFileSize } from "@/core/thread-files/format";
import {
  settleThreadFileActiveKey,
  toggleThreadFileDirectory,
} from "@/core/thread-files/tree";
import {
  EMPTY_THREAD_FILE_TREE,
  type ThreadFileEntry,
} from "@/core/thread-files/types";

const ROOT = "/mnt/user-data";

function entry(path: string, kind: ThreadFileEntry["kind"] = "file") {
  return {
    name: path.slice(path.lastIndexOf("/") + 1),
    path,
    kind,
    size: null,
    modified_at: null,
  } satisfies ThreadFileEntry;
}

describe("toggleThreadFileDirectory", () => {
  it("collapses without forgetting nested expansion and keeps the tab stop visible", () => {
    const expanded = toggleThreadFileDirectory(
      toggleThreadFileDirectory(EMPTY_THREAD_FILE_TREE, `${ROOT}/outputs`),
      `${ROOT}/outputs/charts`,
    );
    const collapsed = toggleThreadFileDirectory(
      { ...expanded, activeKey: `${ROOT}/outputs/charts/a.png` },
      `${ROOT}/outputs`,
    );

    expect(collapsed.expanded).toEqual([`${ROOT}/outputs/charts`]);
    expect(collapsed.activeKey).toBe(`${ROOT}/outputs`);
    // A sibling whose name starts the same is not inside the directory.
    expect(
      toggleThreadFileDirectory(
        {
          ...expanded,
          activeKey: `${ROOT}/outputs-old/a.txt`,
        },
        `${ROOT}/outputs`,
      ).activeKey,
    ).toBe(`${ROOT}/outputs-old/a.txt`);
  });
});

describe("settleThreadFileActiveKey", () => {
  const state = {
    ...EMPTY_THREAD_FILE_TREE,
    expanded: [`${ROOT}/outputs`],
    activeKey: `${ROOT}/outputs/report.md`,
  };

  it("returns the same state while the active row is still listed", () => {
    expect(
      settleThreadFileActiveKey(
        state,
        `${ROOT}/outputs`,
        [entry(`${ROOT}/outputs/report.md`)],
        `${ROOT}/outputs`,
      ),
    ).toBe(state);
    // The expanded child's own listing settles the rows below it.
    expect(
      settleThreadFileActiveKey(
        state,
        ROOT,
        [entry(`${ROOT}/outputs`, "directory")],
        null,
      ),
    ).toBe(state);
  });

  it("moves the tab stop off a row that disappeared or failed to list", () => {
    expect(
      settleThreadFileActiveKey(state, `${ROOT}/outputs`, [], `${ROOT}/outputs`)
        .activeKey,
    ).toBe(`${ROOT}/outputs`);
    expect(
      settleThreadFileActiveKey(state, ROOT, [], null).activeKey,
    ).toBeNull();
    expect(
      settleThreadFileActiveKey(
        state,
        `${ROOT}/outputs`,
        null,
        `${ROOT}/outputs`,
      ).activeKey,
    ).toBe(`${ROOT}/outputs`);
  });

  it("moves the tab stop to a listed ancestor that is collapsed", () => {
    expect(
      settleThreadFileActiveKey(
        { ...state, expanded: [] },
        ROOT,
        [entry(`${ROOT}/outputs`, "directory")],
        null,
      ).activeKey,
    ).toBe(`${ROOT}/outputs`);
  });
});

describe("formatFileSize", () => {
  it.each([
    [0, "0 B"],
    [1023, "1023 B"],
    [1536, "1.5 KiB"],
    [1024 * 1024 - 1, "1.0 MiB"],
    [5 * 1024 ** 3, "5.0 GiB"],
  ])("formats %d bytes as %s", (bytes, expected) => {
    expect(formatFileSize(bytes)).toBe(expected);
  });
});
