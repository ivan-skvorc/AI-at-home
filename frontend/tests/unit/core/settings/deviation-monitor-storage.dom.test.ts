import { beforeEach, describe, expect, it } from "@rstest/core";

import {
  LOCAL_SETTINGS_KEY,
  copyThreadContextOverride,
  getThreadContextOverride,
} from "@/core/settings/local";
import {
  getBaseSettingsSnapshot,
  resolveThreadContext,
  updateThreadSettings,
} from "@/core/settings/store";

/**
 * Where a conversation's deviation monitor is remembered (fork feature).
 *
 * Per conversation, in that thread's own override, like the model: watching
 * one chat must not start watching every other open chat, and a chat must not
 * forget its monitor when its draft id is promoted to the real thread id.
 */

const ON = {
  enabled: true,
  model: "judge-model",
  cadence: { mode: "turns" as const, every: 2 },
};

beforeEach(() => {
  window.localStorage.clear();
});

describe("the per-conversation monitor choice", () => {
  it("round-trips through the thread's own override", () => {
    updateThreadSettings("thread-a", "context", { deviation_monitor: ON });

    expect(getThreadContextOverride("thread-a")).toEqual({
      deviation_monitor: ON,
    });
    // Another chat, and the shared base every chat reads, stay untouched.
    expect(getThreadContextOverride("thread-b")).toEqual({});
    expect(getBaseSettingsSnapshot().context).not.toHaveProperty(
      "deviation_monitor",
    );
    expect(window.localStorage.getItem(LOCAL_SETTINGS_KEY) ?? "").not.toContain(
      "deviation_monitor",
    );
  });

  it("keeps a switched-off choice, so reopening the dialog starts from it", () => {
    updateThreadSettings("thread-a", "context", { deviation_monitor: ON });
    updateThreadSettings("thread-a", "context", {
      deviation_monitor: { ...ON, enabled: false },
    });
    expect(getThreadContextOverride("thread-a")).toEqual({
      deviation_monitor: { ...ON, enabled: false },
    });
  });

  it("merges with the chat's other choices instead of replacing them", () => {
    updateThreadSettings("thread-a", "context", { model_name: "chat-model" });
    updateThreadSettings("thread-a", "context", { deviation_monitor: ON });
    expect(getThreadContextOverride("thread-a")).toEqual({
      model_name: "chat-model",
      deviation_monitor: ON,
    });
  });

  it("follows the chat when its draft id is promoted to the real thread id", () => {
    updateThreadSettings("draft-id", "context", { deviation_monitor: ON });
    copyThreadContextOverride("draft-id", "real-id");
    expect(getThreadContextOverride("real-id")).toEqual({
      deviation_monitor: ON,
    });
  });

  it("never becomes a default for other chats through automatic resolution", () => {
    // The composer reports a chat's whole effective context when it resolves
    // the model on its own; keys the chat has not chosen land in the shared
    // in-memory base. A monitor there would watch every chat in this tab.
    resolveThreadContext("thread-x", {
      model_name: "chat-model",
      deviation_monitor: ON,
    });
    expect(getBaseSettingsSnapshot().context).not.toHaveProperty(
      "deviation_monitor",
    );
    expect(getThreadContextOverride("thread-x")).toEqual({});
  });
});
