import { beforeEach, describe, expect, it } from "@rstest/core";

import {
  LOCAL_SETTINGS_KEY,
  copyThreadContextOverride,
  getThreadContextOverride,
} from "@/core/settings/local";
import {
  getBaseSettingsSnapshot,
  getThreadContextSnapshot,
  promoteThreadContext,
  resolveThreadContext,
  seedThreadContext,
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

  it("holds a new chat's seeded default in this tab until the chat is sent", () => {
    // Every visit to a new chat has a fresh draft id: one left without a
    // message must not leave a record in this browser for good.
    seedThreadContext("draft-1", { deviation_monitor: ON });
    seedThreadContext("draft-2", { deviation_monitor: ON });
    expect(getThreadContextSnapshot("draft-2")).toEqual({
      deviation_monitor: ON,
    });
    // The composer's automatic context report does not save it either.
    resolveThreadContext("draft-2", {
      model_name: "chat-model",
      deviation_monitor: ON,
    });
    expect(
      Object.keys(window.localStorage).filter((key) =>
        key.startsWith("deerflow.thread-context."),
      ),
    ).toEqual([]);

    // Sent: the real thread keeps it, in storage.
    promoteThreadContext("draft-2", "real-2");
    expect(getThreadContextOverride("real-2")).toEqual({
      deviation_monitor: ON,
    });
    // A thread created under its draft id is saved in place.
    seedThreadContext("project-thread", { deviation_monitor: ON });
    promoteThreadContext("project-thread", "project-thread");
    expect(getThreadContextOverride("project-thread")).toEqual({
      deviation_monitor: ON,
    });
  });

  it("saves a held seed with the user's first explicit choice in that chat", () => {
    seedThreadContext("draft-3", { deviation_monitor: ON });
    updateThreadSettings("draft-3", "context", { model_name: "chat-model" });
    expect(getThreadContextOverride("draft-3")).toEqual({
      deviation_monitor: ON,
      model_name: "chat-model",
    });
  });
});
