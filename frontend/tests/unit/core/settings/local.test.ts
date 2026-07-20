import { expect, test } from "@rstest/core";

import {
  DEFAULT_LOCAL_SETTINGS,
  mergeLocalSettings,
} from "@/core/settings/local";

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

test("defaults decorative animations to reduced", () => {
  // Reduced by default to keep the UI calm and cheap on GPU/CPU; users can
  // re-enable the full motion from Settings → Appearance, and the OS
  // prefers-reduced-motion signal is honored separately at read time.
  expect(DEFAULT_LOCAL_SETTINGS.appearance).toEqual({
    reduceAnimations: true,
  });
});

test("fills in the appearance section when older settings are missing it", () => {
  // Settings persisted before this flag existed must not crash reads and adopt
  // the reduced-motion default.
  const merged = mergeLocalSettings({ notification: { enabled: false } });
  expect(merged.appearance).toEqual({ reduceAnimations: true });
  expect(merged.notification).toEqual({ enabled: false });
});

test("preserves an explicit opt-in to full motion over the default", () => {
  // Turning the toggle off must survive the merge so users who want the full
  // motion are not silently pushed back onto the reduced default.
  const merged = mergeLocalSettings({
    appearance: { reduceAnimations: false },
  });
  expect(merged.appearance.reduceAnimations).toBe(false);
});
