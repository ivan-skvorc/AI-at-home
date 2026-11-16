import { readFileSync } from "node:fs";
import path from "node:path";

import { afterEach, describe, expect, it, rs } from "@rstest/core";

import {
  autoTitlePreferenceBody,
  parseAutoTitlePreference,
} from "@/core/settings/auto-title-api";
import {
  DEFAULT_LOCAL_SETTINGS,
  LOCAL_SETTINGS_KEY,
  getLocalSettings,
  mergeLocalSettings,
  saveLocalSettings,
} from "@/core/settings/local";
import {
  getBaseSettingsSnapshot,
  updateLocalSettings,
} from "@/core/settings/store";
import { autoTitleRunContext } from "@/core/threads/run-context";

/**
 * Automatic conversation renaming (fork feature, FORK.md §33).
 *
 * The failures these guard against are silent: the sidebar still fills in with
 * names, so nothing looks broken — the run just ignores the preference, or
 * spends a model call the user asked it not to.
 */

const FRONTEND_ROOT = path.resolve(__dirname, "../../../..");
const read = (relativePath: string) =>
  readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");

/**
 * Set the preference the way the Settings switch and picker do: through the
 * settings store, whose snapshot is what they render. Both keys every time —
 * the store merges, and a model left over from an earlier case would leak in.
 */
function withPreference(autoTitle: {
  enabled: boolean;
  modelName: string | undefined;
}) {
  updateLocalSettings("autoTitle", autoTitle);
}

/** A browser whose localStorage refuses writes (quota, blocked site data). */
function withStorageThatRejectsWrites() {
  const store = new Map<string, string>();
  rs.stubGlobal("window", {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: () => {
        throw new DOMException("Quota exceeded", "QuotaExceededError");
      },
      removeItem: (key: string) => void store.delete(key),
    },
    addEventListener: () => undefined,
  });
  return store;
}

afterEach(() => {
  rs.unstubAllGlobals();
});

describe("what reaches the backend", () => {
  it("distinguishes 'server default' from 'no model call'", () => {
    // The two are one keystroke apart in the picker and opposite on the wire.
    // An OMITTED key means "keep config.yaml's title.model_name"; an empty
    // string means "clear it, rename without spending a model call". Collapsing
    // them — sending "" for both, or omitting for both — silently either starts
    // paying for a title model the user declined, or ignores the one they
    // configured server-side.
    withPreference({ enabled: true, modelName: undefined });
    expect(autoTitleRunContext()).toEqual({ auto_title_enabled: true });

    withPreference({ enabled: true, modelName: "" });
    expect(autoTitleRunContext()).toEqual({
      auto_title_enabled: true,
      auto_title_model_name: "",
    });
  });

  it("sends a chosen model by name", () => {
    withPreference({ enabled: true, modelName: "cheap-model" });
    expect(autoTitleRunContext()).toEqual({
      auto_title_enabled: true,
      auto_title_model_name: "cheap-model",
    });
  });

  it("sends no model key at all when renaming is off", () => {
    // Nothing is going to write a title, so naming a model for it is noise the
    // backend would have to reason about.
    withPreference({ enabled: false, modelName: "cheap-model" });
    expect(autoTitleRunContext()).toEqual({ auto_title_enabled: false });
  });

  it("sends what the switch shows even when the browser cannot store it", () => {
    // The switch renders the in-memory settings snapshot. A run that read
    // localStorage instead sent the stale stored "on" after a write failed
    // without a sound (quota, blocked site data) — the switch said off, and
    // the conversation was renamed anyway.
    const stored = withStorageThatRejectsWrites();
    withPreference({ enabled: true, modelName: undefined });
    withPreference({ enabled: false, modelName: undefined });

    expect(getBaseSettingsSnapshot().autoTitle.enabled).toBe(false);
    expect(stored.has(LOCAL_SETTINGS_KEY)).toBe(false);
    expect(autoTitleRunContext()).toEqual({ auto_title_enabled: false });
  });

  it("is sent on the send, regenerate and approval-resume paths", () => {
    // Regenerating the first turn can still be the run that names the
    // conversation. Since the 2026-09-22 upstream sync both paths build their
    // run context through one `buildRunContext`, so the helper is spread once,
    // there — and the property is that no path builds a context without it,
    // which a refactor re-inlining one call site would break. The 2026-11-10
    // sync added the third: resuming a run after a tool-call approval.
    const hooks = read("src/core/threads/hooks.ts");
    expect(hooks.match(/\.\.\.autoTitleRunContext\(\)/g)).toHaveLength(1);
    expect(hooks.match(/context: buildRunContext\(/g)).toHaveLength(3);
  });
});

describe("where the preference is stored", () => {
  it("defaults to on, following the operator's configured model", () => {
    // A fresh install must behave exactly as it did before the switch existed:
    // renaming on, and no opinion about which model does it.
    expect(DEFAULT_LOCAL_SETTINGS.autoTitle).toEqual({
      enabled: true,
      modelName: undefined,
    });
  });

  it("fills the section in for settings written before the toggle existed", () => {
    const merged = mergeLocalSettings({ notification: { enabled: false } });
    expect(merged.autoTitle).toEqual({ enabled: true, modelName: undefined });
  });

  it("preserves an explicit opt-out over the default", () => {
    expect(
      mergeLocalSettings({ autoTitle: { enabled: false } }).autoTitle.enabled,
    ).toBe(false);
  });

  it("survives a round trip through this browser's cache", () => {
    // The local copy is what a reload renders before the account answers, and
    // what a static demo has instead of an account.
    const store = new Map<string, string>();
    rs.stubGlobal("window", {
      localStorage: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => void store.set(key, value),
        removeItem: (key: string) => void store.delete(key),
      },
    });
    saveLocalSettings(
      mergeLocalSettings({ autoTitle: { enabled: false, modelName: "" } }),
    );
    expect(getLocalSettings().autoTitle).toEqual({
      enabled: false,
      modelName: "",
    });
  });
});

describe("what the account stores", () => {
  it("keeps 'server default' and 'no model call' apart on the account too", () => {
    // Same distinction as the run context: an omitted `model_name` follows
    // config.yaml, `""` renames without a model call. Collapsing them on the
    // way to the account would hand every other device the wrong one.
    expect(
      autoTitlePreferenceBody({ enabled: true, modelName: undefined }),
    ).toEqual({ enabled: true });
    expect(autoTitlePreferenceBody({ enabled: true, modelName: "" })).toEqual({
      enabled: true,
      model_name: "",
    });
    expect(parseAutoTitlePreference({ enabled: true })).toEqual({
      enabled: true,
      modelName: undefined,
    });
    expect(parseAutoTitlePreference({ enabled: true, model_name: "" })).toEqual(
      { enabled: true, modelName: "" },
    );
    expect(
      parseAutoTitlePreference({ enabled: false, model_name: "cheap-model" }),
    ).toEqual({ enabled: false, modelName: "cheap-model" });
  });

  it.each([
    ["no body", null],
    ["an error body", { detail: "Not Found" }],
    ["a non-boolean switch", { enabled: "false" }],
    ["a non-string model", { enabled: true, model_name: 3 }],
  ])("reads %s as unknown, never as a setting", (_label, body) => {
    // An answer that is not a preference must not be adopted as one: reading
    // it as the default would switch renaming back on for someone who turned
    // it off, and reading it as "off" would do the opposite.
    expect(parseAutoTitlePreference(body)).toBeNull();
  });
});

describe("the settings page", () => {
  it("uses the shared model picker rather than a flat list", () => {
    // FORK.md §8's rule: every model choice in the app goes through the one
    // picker, or this screen alone loses sorting, grouping, search and prices.
    const source = read(
      "src/components/workspace/settings/auto-title-settings-page.tsx",
    );
    expect(source).toContain("<ModelSelect");
    expect(source).not.toContain("SelectItem");
  });

  it("explains a server-disabled toggle instead of silently ignoring it", () => {
    const source = read(
      "src/components/workspace/settings/auto-title-settings-page.tsx",
    );
    expect(source).toContain("serverDisabledHint");
    expect(source).toContain("disabled={!serverEnabled}");
  });
});
