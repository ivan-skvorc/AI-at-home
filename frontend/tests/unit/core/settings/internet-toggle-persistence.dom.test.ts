import { beforeEach, describe, expect, it } from "@rstest/core";

import {
  getThreadContextOverride,
  saveThreadContextOverride,
} from "@/core/settings/local";

/**
 * Where an offline conversation is remembered (fork feature, FORK.md §27).
 *
 * The switch is per conversation and lives in that thread's own localStorage
 * key, for the same reason the model selection does: two open chats are two
 * workflows, and taking one offline must not unplug the other.
 */

beforeEach(() => {
  window.localStorage.clear();
});

describe("the per-conversation internet switch", () => {
  it("persists `false` rather than dropping it as an empty value", () => {
    // `saveThreadContextOverride` strips `undefined` so a reset thread falls
    // back to the app default. A filter that also stripped *falsy* values would
    // silently forget every offline conversation on reload — the one state this
    // feature exists to remember.
    saveThreadContextOverride("thread-offline", { internet_enabled: false });
    expect(getThreadContextOverride("thread-offline")).toEqual({
      internet_enabled: false,
    });
  });

  it("keeps one offline conversation from unplugging another", () => {
    saveThreadContextOverride("thread-a", { internet_enabled: false });
    saveThreadContextOverride("thread-b", { model_name: "m1" });
    expect(getThreadContextOverride("thread-a")).toEqual({
      internet_enabled: false,
    });
    expect(getThreadContextOverride("thread-b")).toEqual({ model_name: "m1" });
  });

  it("reports no override for a conversation that never touched the switch", () => {
    // Absent is not `false`: the run context then carries "no opinion", which
    // the backend reads as the operator's configured tools, unchanged.
    saveThreadContextOverride("thread-a", { internet_enabled: false });
    expect(getThreadContextOverride("thread-untouched")).toEqual({});
  });
});
