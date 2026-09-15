import { beforeEach, describe, expect, it } from "@rstest/core";

import {
  DEFAULT_LOCAL_SETTINGS,
  LOCAL_SETTINGS_KEY,
  THREAD_CONTEXT_KEY_PREFIX,
  type LocalSettings,
} from "@/core/settings/local";
import { parsePreferences } from "@/core/settings/preferences-sync";
import {
  activatePreferences,
  getBaseSettingsSnapshot,
  getThreadModelSnapshot,
  updateLocalSettings,
  updateThreadSettings,
} from "@/core/settings/store";

/**
 * The seam between this fork's per-conversation context and upstream's account
 * preferences (#5397), which sync the model, mode and reasoning effort to the
 * server so they follow the user across browsers.
 *
 * Those two features want opposite things from the same three fields, and the
 * collision is silent in both directions:
 *
 *  - If a per-conversation selection is uploaded as an account preference,
 *    picking a model in one chat becomes the default for every other chat —
 *    on every device. Nothing throws; the other conversations just quietly
 *    change model.
 *  - If the fork's `democracy` mode is not in the sync schema, `parsePreferences`
 *    keeps only the fields that parse, so the mode is dropped on the way to the
 *    server rather than rejected. The user's selection disappears on the next
 *    load with no error anywhere.
 *
 * Both are one "simplification" away from being reintroduced, which is why they
 * are asserted here rather than left to review.
 */

function trackedPreferences() {
  const uploads: LocalSettings[] = [];
  const stop = activatePreferences({}, (_before, after) => {
    uploads.push(after);
  });
  return { uploads, stop: () => stop.stop() };
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("per-conversation context vs. account preferences", () => {
  it("never uploads a conversation's own model choice as an account preference", () => {
    const { uploads, stop } = trackedPreferences();
    try {
      updateThreadSettings("thread-a", "context", {
        model_name: "ollama:llama3",
      });

      expect(uploads).toEqual([]);
      expect(getThreadModelSnapshot("thread-a")).toBe("ollama:llama3");
      // The account-wide default is untouched, so every other conversation
      // keeps whatever the account said.
      expect(getBaseSettingsSnapshot().context.model_name).toBe(
        DEFAULT_LOCAL_SETTINGS.context.model_name,
      );
      expect(
        window.localStorage.getItem(`${THREAD_CONTEXT_KEY_PREFIX}thread-a`),
      ).toContain("ollama:llama3");
    } finally {
      stop();
    }
  });

  it("still uploads a genuinely global setting edited from a thread page", () => {
    const { uploads, stop } = trackedPreferences();
    try {
      updateThreadSettings("thread-a", "notification", { enabled: false });
      expect(uploads.at(-1)?.notification.enabled).toBe(false);
    } finally {
      stop();
    }
  });

  it("uploads a model chosen in Settings, which is account-wide by definition", () => {
    const { uploads, stop } = trackedPreferences();
    try {
      updateLocalSettings("context", { model_name: "claude-opus" });
      expect(uploads.at(-1)?.context.model_name).toBe("claude-opus");
      // ...and it is the shared blob that changed, not one conversation's key.
      expect(window.localStorage.getItem(LOCAL_SETTINGS_KEY)).not.toBeNull();
    } finally {
      stop();
    }
  });
});

describe("the sync schema knows this fork's modes", () => {
  it("carries `democracy` through instead of silently dropping it", () => {
    expect(parsePreferences({ mode: "democracy" })).toEqual({
      mode: "democracy",
    });
  });

  it("still drops a value that is not a mode at all", () => {
    expect(parsePreferences({ mode: "not-a-mode" })).toEqual({});
  });
});
