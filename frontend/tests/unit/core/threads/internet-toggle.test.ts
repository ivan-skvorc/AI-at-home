import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

import {
  DEFAULT_LOCAL_SETTINGS,
  THREAD_SCOPED_CONTEXT_KEYS,
  mergeLocalSettings,
  pickThreadScopedContext,
} from "@/core/settings/local";
import { resolveInternetEnabled } from "@/core/threads/run-context";

/**
 * The conversation's internet switch (fork feature, FORK.md §27).
 *
 * The failures these guard against are silent: the composer still renders a
 * globe, the chat still answers — the run just quietly has its web tools back.
 */

const FRONTEND_ROOT = path.resolve(__dirname, "../../../..");
const read = (relativePath: string) =>
  readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");

describe("what reaches the backend", () => {
  it("sends the strict boolean the backend opts out on", () => {
    // The backend treats ONLY an explicit `false` as offline. A truthy
    // `"false"` out of a hand-edited localStorage blob would read as *enabled*
    // and hand an offline conversation its web tools back.
    expect(resolveInternetEnabled({ internet_enabled: false })).toBe(false);
    expect(resolveInternetEnabled({ internet_enabled: "false" })).toBe(true);
    expect(resolveInternetEnabled({ internet_enabled: true })).toBe(true);
    expect(resolveInternetEnabled({})).toBe(true);
  });

  it("is sent on both the send and the regenerate path", () => {
    // Regenerating a turn under different rules than sending it is the kind of
    // divergence `deriveModeContext` was extracted to end; the switch must not
    // reintroduce it. Two call sites, both explicit rather than riding the
    // `...context` spread, which a refactor can drop without a type error.
    const hooks = read("src/core/threads/hooks.ts");
    const occurrences = hooks.match(
      /internet_enabled: resolveInternetEnabled\(context\)/g,
    );
    expect(occurrences).toHaveLength(2);
  });
});

describe("where the switch is stored", () => {
  it("defaults to on, so the feature is an opt-out", () => {
    // A fresh install must behave exactly as it did before the switch existed.
    expect(DEFAULT_LOCAL_SETTINGS.context.internet_enabled).toBe(true);
    expect(mergeLocalSettings({}).context.internet_enabled).toBe(true);
    expect(resolveInternetEnabled(DEFAULT_LOCAL_SETTINGS.context)).toBe(true);
  });

  it("is scoped to the conversation, not shared across every chat", () => {
    expect(THREAD_SCOPED_CONTEXT_KEYS).toContain("internet_enabled");
    expect(pickThreadScopedContext({ internet_enabled: false })).toEqual({
      internet_enabled: false,
    });
  });
});

describe("the composer control's test contract", () => {
  it("publishes its own data-slot rather than relying on a button role", () => {
    // FORK.md's shared-control rule: a spec locates this by the control's own
    // contract, so swapping the primitive underneath cannot silently make every
    // spec that clicks it match nothing.
    const source = read("src/components/workspace/input-box.tsx");
    expect(source).toContain('data-slot="internet-toggle"');
    expect(source).toContain('data-testid="internet-toggle-button"');
  });

  it("treats a conversation that never touched the switch as online", () => {
    // `undefined` is not `false`: a chat that predates the feature keeps its
    // web tools rather than silently going offline on upgrade.
    const source = read("src/components/workspace/input-box.tsx");
    expect(source).toContain("context.internet_enabled !== false");
  });
});
