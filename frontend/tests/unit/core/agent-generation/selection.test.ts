import { describe, expect, it } from "@rstest/core";

import {
  canAnalyze,
  isSelected,
  sourceKey,
  toggleSource,
} from "@/core/agent-generation/selection";
import type { GenerationSource } from "@/core/agent-generation/types";

const thread = (id: string): GenerationSource => ({ kind: "thread", id });
const task = (id: string): GenerationSource => ({ kind: "scheduled_task", id });

describe("sourceKey", () => {
  it("distinguishes a thread from a task with the same id", () => {
    expect(sourceKey(thread("a"))).not.toBe(sourceKey(task("a")));
  });
});

describe("isSelected", () => {
  it("matches on both kind and id", () => {
    const selection = [thread("a")];
    expect(isSelected(selection, thread("a"))).toBe(true);
    expect(isSelected(selection, task("a"))).toBe(false);
    expect(isSelected(selection, thread("b"))).toBe(false);
  });
});

describe("toggleSource", () => {
  it("adds an unselected source", () => {
    expect(toggleSource([], thread("a"), 5)).toEqual([thread("a")]);
  });

  it("removes an already-selected source", () => {
    expect(toggleSource([thread("a"), thread("b")], thread("a"), 5)).toEqual([
      thread("b"),
    ]);
  });

  it("keeps sources of different kinds with the same id apart", () => {
    const selection = toggleSource([thread("a")], task("a"), 5);
    expect(selection).toEqual([thread("a"), task("a")]);
  });

  it("refuses to add past the cap", () => {
    const selection = [thread("a"), thread("b")];
    expect(toggleSource(selection, thread("c"), 2)).toBe(selection);
  });

  it("still allows deselecting at the cap", () => {
    // Otherwise a full selection would be impossible to change.
    const selection = [thread("a"), thread("b")];
    expect(toggleSource(selection, thread("a"), 2)).toEqual([thread("b")]);
  });

  it("treats a non-positive cap as unbounded", () => {
    expect(toggleSource([thread("a")], thread("b"), 0)).toEqual([
      thread("a"),
      thread("b"),
    ]);
  });
});

describe("canAnalyze", () => {
  it("is false with an empty selection", () => {
    expect(canAnalyze([], 5)).toBe(false);
  });

  it("is true within the cap", () => {
    expect(canAnalyze([thread("a")], 5)).toBe(true);
  });

  it("is false past the cap", () => {
    expect(canAnalyze([thread("a"), thread("b")], 1)).toBe(false);
  });

  it("ignores a non-positive cap", () => {
    expect(canAnalyze([thread("a")], 0)).toBe(true);
  });
});
