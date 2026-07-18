import { expect, test } from "@rstest/core";

import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";

test("defaults token usage to header total plus per-turn breakdown", () => {
  expect(DEFAULT_LOCAL_SETTINGS.tokenUsage).toEqual({
    headerTotal: true,
    inlineMode: "per_turn",
  });
});

test("defaults follow-up suggestions to off, following the workflow model", () => {
  // Off by default so a fresh install does not pay for the extra per-turn
  // suggestions call; undefined model = follow the workflow's selected model.
  expect(DEFAULT_LOCAL_SETTINGS.suggestions).toEqual({
    enabled: false,
    modelName: undefined,
  });
});
