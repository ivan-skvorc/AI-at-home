import { afterEach, expect, rs, test } from "@rstest/core";

import {
  applyThreadContextOverride,
  DEFAULT_LOCAL_SETTINGS,
  getLocalSettings,
  getThreadContextOverride,
  mergeLocalSettings,
  pickThreadScopedContext,
  saveLocalSettings,
  saveThreadContextOverride,
} from "@/core/settings/local";

afterEach(() => {
  rs.unstubAllGlobals();
});

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

test("defaults long-term memory to off on a fresh install", () => {
  // Off by default so a fresh install does not learn from / inject conversation
  // context until the user opts in from Settings → Memory.
  expect(DEFAULT_LOCAL_SETTINGS.memory).toEqual({ enabled: false });
});

test("fills in the memory section when older settings are missing it", () => {
  // Settings persisted before the memory toggle existed must not crash reads and
  // adopt the off-by-default.
  const merged = mergeLocalSettings({ notification: { enabled: false } });
  expect(merged.memory).toEqual({ enabled: false });
});

test("preserves an explicit opt-in to memory over the default", () => {
  const merged = mergeLocalSettings({ memory: { enabled: true } });
  expect(merged.memory.enabled).toBe(true);
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

test("falls back when localStorage access is blocked", () => {
  rs.stubGlobal("window", {
    get localStorage() {
      throw new DOMException("Blocked", "SecurityError");
    },
  });

  expect(getLocalSettings()).toEqual(DEFAULT_LOCAL_SETTINGS);
  expect(getThreadContextOverride("thread-1")).toEqual({});
  expect(() => saveLocalSettings(DEFAULT_LOCAL_SETTINGS)).not.toThrow();
  expect(() =>
    saveThreadContextOverride("thread-1", { model_name: "model-1" }),
  ).not.toThrow();
});

test("pickThreadScopedContext keeps only per-conversation workflow keys", () => {
  // agent_name is route-derived and must not leak into the per-thread override.
  const picked = pickThreadScopedContext({
    model_name: "ollama:llama3",
    subagent_model_name: "claude-opus",
    mode: "ultra",
    reasoning_effort: "high",
    agent_name: "researcher",
  });
  expect(picked).toEqual({
    model_name: "ollama:llama3",
    subagent_model_name: "claude-opus",
    mode: "ultra",
    reasoning_effort: "high",
  });
});

test("pickThreadScopedContext preserves an explicit undefined reset", () => {
  // Sending the subagent model back to "follow lead" clears the override, which
  // must survive as an own `undefined` key rather than being dropped.
  const picked = pickThreadScopedContext({ subagent_model_name: undefined });
  expect(
    Object.prototype.hasOwnProperty.call(picked, "subagent_model_name"),
  ).toBe(true);
  expect(picked.subagent_model_name).toBeUndefined();
});

test("applyThreadContextOverride layers the thread selection over base settings", () => {
  const base = mergeLocalSettings({});
  const applied = applyThreadContextOverride(base, {
    model_name: "ollama:llama3",
    mode: "flash",
  });
  expect(applied.context.model_name).toBe("ollama:llama3");
  expect(applied.context.mode).toBe("flash");
  // The base settings object is never mutated.
  expect(base.context.model_name).toBeUndefined();
});
