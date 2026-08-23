import { describe, expect, it } from "@rstest/core";

import {
  canRefine,
  goalLength,
  isGoalWithinCap,
  normalizeGoal,
} from "@/core/agent-generation/goal";

describe("goalLength", () => {
  it("measures the trimmed length, as the server does", () => {
    expect(goalLength("  hello  ")).toBe(5);
  });

  it("is zero for whitespace only", () => {
    expect(goalLength(" \n\t ")).toBe(0);
  });
});

describe("isGoalWithinCap", () => {
  it("accepts a goal at the cap", () => {
    expect(isGoalWithinCap("x".repeat(10), 10)).toBe(true);
  });

  it("rejects a goal past the cap", () => {
    expect(isGoalWithinCap("x".repeat(11), 10)).toBe(false);
  });

  it("ignores surrounding whitespace, matching the server", () => {
    expect(isGoalWithinCap(`  ${"x".repeat(10)}  `, 10)).toBe(true);
  });

  it("treats a non-positive cap as unbounded", () => {
    expect(isGoalWithinCap("x".repeat(1000), 0)).toBe(true);
  });
});

describe("normalizeGoal", () => {
  it("returns null for a blank box", () => {
    // Blank and absent mean the same thing to the server; "" would read as a
    // stated intent.
    expect(normalizeGoal("   ")).toBeNull();
  });

  it("trims a real goal", () => {
    expect(normalizeGoal("  write my reports ")).toBe("write my reports");
  });
});

describe("canRefine", () => {
  it("is false with no guidance", () => {
    expect(canRefine("  ", 100)).toBe(false);
  });

  it("is true with guidance within the cap", () => {
    expect(canRefine("make it shorter", 100)).toBe(true);
  });

  it("is false past the cap", () => {
    expect(canRefine("x".repeat(101), 100)).toBe(false);
  });
});
