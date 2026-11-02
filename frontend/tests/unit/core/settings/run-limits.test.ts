import { describe, expect, it } from "@rstest/core";

import {
  buildOverrides,
  draftFromLimits,
  mergeDraft,
  sectionOverride,
  type EffectiveRunLimits,
  type RunLimitsDraft,
} from "@/core/settings/run-limits";

const EFFECTIVE: EffectiveRunLimits = {
  spend_budget: {
    enabled: false,
    daily_limit: null,
    weekly_limit: 20,
    monthly_limit: null,
    currency: "USD",
  },
  loop_detection: {
    enabled: true,
    warn_threshold: 3,
    hard_limit: 5,
    tool_freq_warn: 30,
    tool_freq_hard_limit: 50,
    tool_freq_overrides: {},
  },
  token_budget: { enabled: false, max_tokens: 200_000 },
  subagent_token_budget: { enabled: true, max_tokens: 1_000_000 },
  recursion_limit: 250,
  max_recursion_limit: 1000,
};

const draft = (edit: (value: RunLimitsDraft) => void = () => undefined) => {
  const value = draftFromLimits(EFFECTIVE);
  edit(value);
  return value;
};

describe("run limits draft", () => {
  it("pre-fills every input from what runs enforce, blank for no cap", () => {
    expect(draft().spend_budget).toEqual({
      enabled: false,
      daily_limit: "",
      weekly_limit: "20",
      monthly_limit: "",
    });
    expect(draft().recursion_limit).toBe("250");
  });

  it("turns a section into the override the Gateway stores", () => {
    expect(
      sectionOverride(
        draft((d) => (d.spend_budget.daily_limit = " 2.5 ")),
        "spend_budget",
      ),
    ).toEqual({
      value: {
        enabled: false,
        daily_limit: 2.5,
        weekly_limit: 20,
        monthly_limit: null,
      },
    });
    expect(
      sectionOverride(
        draft((d) => (d.loop_detection.enabled = false)),
        "loop_detection",
      ),
    ).toEqual({
      value: {
        enabled: false,
        warn_threshold: 3,
        hard_limit: 5,
        tool_freq_warn: 30,
        tool_freq_hard_limit: 50,
      },
    });
  });

  it.each([
    [
      "spend_budget",
      (d: RunLimitsDraft) => {
        d.spend_budget = {
          enabled: true,
          daily_limit: "",
          weekly_limit: "",
          monthly_limit: "",
        };
      },
      "spendNeedsAmount",
    ],
    [
      "spend_budget",
      (d: RunLimitsDraft) => (d.spend_budget.daily_limit = "-1"),
      "notPositiveNumber",
    ],
    [
      "loop_detection",
      (d: RunLimitsDraft) => (d.loop_detection.tool_freq_hard_limit = "10"),
      "stopBeforeWarn",
    ],
    [
      "loop_detection",
      (d: RunLimitsDraft) => (d.loop_detection.hard_limit = "2.5"),
      "notWholeNumber",
    ],
    [
      "token_budget",
      (d: RunLimitsDraft) => (d.token_budget.max_tokens = "500"),
      "tooFewTokens",
    ],
    [
      "recursion_limit",
      (d: RunLimitsDraft) => (d.recursion_limit = "0"),
      "notWholeNumber",
    ],
    [
      "recursion_limit",
      (d: RunLimitsDraft) => (d.recursion_limit = "999999"),
      "tooLarge",
    ],
  ] as const)("rejects an invalid %s", (section, edit, error) => {
    expect(sectionOverride(draft(edit), section)).toEqual({ error });
  });

  it("saves edited sections and keeps every other stored override", () => {
    const stored = { recursion_limit: 600, token_budget: null };
    const built = buildOverrides(
      stored,
      draft((d) => (d.loop_detection.enabled = false)),
      new Set(["loop_detection"] as const),
    );
    expect(built).toEqual({
      value: {
        recursion_limit: 600,
        token_budget: null,
        loop_detection: {
          enabled: false,
          warn_threshold: 3,
          hard_limit: 5,
          tool_freq_warn: 30,
          tool_freq_hard_limit: 50,
        },
      },
    });
  });

  it("refreshes from the server without discarding sections still being edited", () => {
    const editing = draft((d) => (d.recursion_limit = "700"));
    const fresh = draftFromLimits({
      ...EFFECTIVE,
      recursion_limit: 300,
      token_budget: { enabled: true, max_tokens: 5000 },
    });
    const merged = mergeDraft(editing, fresh, new Set(["recursion_limit"]));
    expect(merged.recursion_limit).toBe("700");
    expect(merged.token_budget).toEqual({ enabled: true, max_tokens: "5000" });
  });
});
