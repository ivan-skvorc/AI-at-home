import { afterEach, expect, it, rs } from "@rstest/core";

import { safeLocalStorage } from "@/core/settings/local";
import {
  getBaseSettingsSnapshot,
  getThreadModelSnapshot,
  selectThreadModel,
  updateLocalSettings,
} from "@/core/settings/store";

afterEach(() => {
  rs.restoreAllMocks();
});

it("does not claim to save a default when browser storage rejects the write", () => {
  rs.spyOn(safeLocalStorage, "setItem").mockReturnValue(false);
  expect(() => selectThreadModel("blocked-write-thread", "model-B")).toThrow();
  expect(getThreadModelSnapshot("blocked-write-thread")).toBeUndefined();
});

it("persists only the selected conversation without editing account preferences", () => {
  updateLocalSettings("context", { model_name: "parent-A" });
  const before = getBaseSettingsSnapshot();
  selectThreadModel("selection-test-thread", "model-B");
  expect(getThreadModelSnapshot("selection-test-thread")).toBe("model-B");
  expect(getBaseSettingsSnapshot()).toBe(before);
  expect(getThreadModelSnapshot("unrelated-test-thread")).toBeUndefined();
  // Fork: the conversation's model lives in its per-thread context override
  // (FORK.md §36), the record the composer's picker writes, not in upstream's
  // separate per-thread model key.
  expect(
    JSON.parse(
      localStorage.getItem("deerflow.thread-context.selection-test-thread") ??
        "{}",
    ),
  ).toMatchObject({ model_name: "model-B" });
});
