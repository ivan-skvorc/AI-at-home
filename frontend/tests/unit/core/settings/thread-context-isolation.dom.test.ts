import { beforeEach, expect, test } from "@rstest/core";

import {
  LOCAL_SETTINGS_KEY,
  THREAD_CONTEXT_KEY_PREFIX,
  getThreadContextOverride,
  saveThreadContextOverride,
} from "@/core/settings/local";

beforeEach(() => {
  window.localStorage.clear();
});

test("a thread's model selection is written to its own key, not the shared blob", () => {
  saveThreadContextOverride("thread-a", { model_name: "ollama:llama3" });

  // The per-thread key holds the selection...
  expect(
    window.localStorage.getItem(`${THREAD_CONTEXT_KEY_PREFIX}thread-a`),
  ).toBe(JSON.stringify({ model_name: "ollama:llama3" }));
  // ...and the shared settings blob is never touched by a model selection, so
  // it cannot leak into other conversations.
  expect(window.localStorage.getItem(LOCAL_SETTINGS_KEY)).toBeNull();
});

test("selecting a model in one conversation does not change another", () => {
  // Two conversations open at once, each picking a different model.
  saveThreadContextOverride("thread-a", { model_name: "ollama:llama3" });
  saveThreadContextOverride("thread-b", { model_name: "claude-opus" });

  expect(getThreadContextOverride("thread-a")).toEqual({
    model_name: "ollama:llama3",
  });
  expect(getThreadContextOverride("thread-b")).toEqual({
    model_name: "claude-opus",
  });

  // Re-selecting in A must leave B untouched.
  saveThreadContextOverride("thread-a", { model_name: "gpt-5" });
  expect(getThreadContextOverride("thread-a")).toEqual({ model_name: "gpt-5" });
  expect(getThreadContextOverride("thread-b")).toEqual({
    model_name: "claude-opus",
  });
});

test("a conversation with no selection reports an empty override", () => {
  saveThreadContextOverride("thread-a", { model_name: "ollama:llama3" });
  expect(getThreadContextOverride("thread-untouched")).toEqual({});
});

test("round-trips the full workflow selection", () => {
  saveThreadContextOverride("thread-a", {
    model_name: "ollama:llama3",
    subagent_model_name: "claude-haiku",
    mode: "ultra",
    reasoning_effort: "high",
  });
  expect(getThreadContextOverride("thread-a")).toEqual({
    model_name: "ollama:llama3",
    subagent_model_name: "claude-haiku",
    mode: "ultra",
    reasoning_effort: "high",
  });
});

test("drops undefined values and clears the key when nothing remains", () => {
  saveThreadContextOverride("thread-a", {
    model_name: "ollama:llama3",
    subagent_model_name: undefined,
  });
  // undefined subagent model is not persisted...
  expect(getThreadContextOverride("thread-a")).toEqual({
    model_name: "ollama:llama3",
  });

  // ...and an all-undefined override removes the key entirely.
  saveThreadContextOverride("thread-a", { model_name: undefined });
  expect(
    window.localStorage.getItem(`${THREAD_CONTEXT_KEY_PREFIX}thread-a`),
  ).toBeNull();
  expect(getThreadContextOverride("thread-a")).toEqual({});
});

test("migrates a legacy model-only per-thread key", () => {
  // A chat pinned under the old scheme keeps its model after the upgrade.
  window.localStorage.setItem("deerflow.thread-model.thread-legacy", "gpt-5");
  expect(getThreadContextOverride("thread-legacy")).toEqual({
    model_name: "gpt-5",
  });
});
