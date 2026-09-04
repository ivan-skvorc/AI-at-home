import { readFileSync } from "node:fs";
import path from "node:path";

import { afterEach, describe, expect, it, rs } from "@rstest/core";

import {
  DEFAULT_LOCAL_SETTINGS,
  LOCAL_SETTINGS_KEY,
  mergeLocalSettings,
  saveLocalSettings,
} from "@/core/settings/local";
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

function withStoredSettings(autoTitle: Record<string, unknown>) {
  const store = new Map<string, string>();
  rs.stubGlobal("window", {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
    },
  });
  store.set(
    LOCAL_SETTINGS_KEY,
    JSON.stringify({ ...DEFAULT_LOCAL_SETTINGS, autoTitle }),
  );
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
    withStoredSettings({ enabled: true, modelName: undefined });
    expect(autoTitleRunContext()).toEqual({ auto_title_enabled: true });

    withStoredSettings({ enabled: true, modelName: "" });
    expect(autoTitleRunContext()).toEqual({
      auto_title_enabled: true,
      auto_title_model_name: "",
    });
  });

  it("sends a chosen model by name", () => {
    withStoredSettings({ enabled: true, modelName: "cheap-model" });
    expect(autoTitleRunContext()).toEqual({
      auto_title_enabled: true,
      auto_title_model_name: "cheap-model",
    });
  });

  it("sends no model key at all when renaming is off", () => {
    // Nothing is going to write a title, so naming a model for it is noise the
    // backend would have to reason about.
    withStoredSettings({ enabled: false, modelName: "cheap-model" });
    expect(autoTitleRunContext()).toEqual({ auto_title_enabled: false });
  });

  it("is sent on both the send and the regenerate path", () => {
    // Regenerating the first turn can still be the run that names the
    // conversation. Both call sites spread the helper explicitly rather than
    // riding the `...context` spread, which a refactor can drop with no type
    // error and no failing test anywhere else.
    const hooks = read("src/core/threads/hooks.ts");
    expect(hooks.match(/\.\.\.autoTitleRunContext\(\)/g)).toHaveLength(2);
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

  it("survives a round trip through localStorage", () => {
    withStoredSettings({ enabled: true, modelName: undefined });
    saveLocalSettings(
      mergeLocalSettings({ autoTitle: { enabled: false, modelName: "" } }),
    );
    expect(autoTitleRunContext()).toEqual({ auto_title_enabled: false });
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
