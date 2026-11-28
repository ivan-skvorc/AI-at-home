import { describe, expect, it } from "@rstest/core";

import {
  composerControlsScope,
  type ComposerContext,
  pluginRunContext,
  resolveComposerSelection,
} from "@/core/extensions/composer-controls";
import type { Model } from "@/core/models/types";
import { deriveModeContext } from "@/core/threads/run-context";
import { ULTRACODE_NAMESPACE } from "@/core/threads/ultracode";

/**
 * A plugin page's composer controls send what the main chat would send for the
 * same selection (`buildRunContext`): the model, the mode string and the keys
 * `deriveModeContext` derives. A page that drifted from that would run its
 * design turns in a different mode than the label it shows.
 */

const model = (name: string, extra: Partial<Model> = {}) =>
  ({ id: name, name, model: name, display_name: name, ...extra }) as Model;
const SMART = model("smart", {
  supports_thinking: true,
  supports_reasoning_effort: true,
});
const PLAIN = model("plain");
const MODELS = [SMART, PLAIN];
const LOADED = { loaded: true, available: false };
const WITH_WORKFLOWS = { loaded: true, available: true };

const context = (extra: Partial<ComposerContext> = {}): ComposerContext => ({
  model_name: undefined,
  mode: undefined,
  ...extra,
});

describe("the page's storage scope", () => {
  it("is namespaced by account, plugin, page and key", () => {
    expect(composerControlsScope("alice", "cad-design", "designs")).toBe(
      "plugin:alice:cad-design/designs/default",
    );
    expect(
      composerControlsScope("alice", "cad-design", "designs", "side.panel-2"),
    ).toBe("plugin:alice:cad-design/designs/side.panel-2");
  });

  it.each(["", "a/b", "x".repeat(65), 3, "../up"])(
    "refuses the storage key %p",
    (key) => {
      expect(() =>
        composerControlsScope("alice", "cad-design", "designs", key),
      ).toThrow(TypeError);
    },
  );
});

describe("the selection, resolved as the composer resolves it", () => {
  it("falls back to the first model when the stored one is gone", () => {
    const selection = resolveComposerSelection(
      context({ model_name: "removed", mode: "pro" }),
      MODELS,
      LOADED,
    );
    expect(selection.model_name).toBe("smart");
    expect(selection.mode).toBe("pro");
  });

  it("without thinking only `thinking` falls back to `flash`", () => {
    for (const [mode, expected] of [
      ["thinking", "flash"],
      ["pro", "pro"],
      ["ultra", "ultra"],
    ] as const) {
      expect(
        resolveComposerSelection(
          context({ model_name: "plain", mode }),
          MODELS,
          LOADED,
        ).mode,
      ).toBe(expected);
    }
  });

  it("reads a remembered Democracy as Ultra: the dropdown has no roster", () => {
    const selection = resolveComposerSelection(
      context({ model_name: "smart", mode: "democracy" }),
      MODELS,
      LOADED,
    );
    expect(selection.mode).toBe("ultra");
    expect(selection.reasoning_effort).toBe("high");
  });

  it("moves both Ultracodes to Ultra only once the extensions loaded without Script workflows", () => {
    const stored = context({ model_name: "smart", mode: "double_ultracode" });
    expect(resolveComposerSelection(stored, MODELS, LOADED).mode).toBe(
      "ultra",
    );
    expect(
      resolveComposerSelection(stored, MODELS, WITH_WORKFLOWS).mode,
    ).toBe("double_ultracode");
    expect(
      resolveComposerSelection(stored, MODELS, {
        loaded: false,
        available: false,
      }).mode,
    ).toBe("double_ultracode");
  });

  it("keeps the stored model name while the list is still empty", () => {
    const selection = resolveComposerSelection(
      context({ model_name: "smart", mode: "pro" }),
      [],
      LOADED,
    );
    expect(selection.model).toBeUndefined();
    expect(selection.model_name).toBe("smart");
  });
});

describe("the run context", () => {
  it.each(["flash", "thinking", "pro", "ultra"] as const)(
    "%s carries the keys deriveModeContext derives",
    (mode) => {
      const run = pluginRunContext(
        context({ model_name: "smart", mode }),
        MODELS,
        LOADED,
      );
      const derived = deriveModeContext({ mode, model_name: "smart" });
      expect(run).toEqual({
        model_name: "smart",
        mode,
        thinking_enabled: derived.thinking_enabled,
        is_plan_mode: derived.is_plan_mode,
        subagent_enabled: derived.subagent_enabled,
        ...(derived.reasoning_effort
          ? { reasoning_effort: derived.reasoning_effort }
          : {}),
      });
    },
  );

  it("sends the subagent model only on a run that can delegate", () => {
    const stored = { model_name: "smart", subagent_model_name: "plain" };
    expect(
      pluginRunContext(context({ ...stored, mode: "ultra" }), MODELS, LOADED)
        .subagent_model_name,
    ).toBe("plain");
    expect(
      pluginRunContext(context({ ...stored, mode: "pro" }), MODELS, LOADED),
    ).not.toHaveProperty("subagent_model_name");
  });

  it("puts Plus Ultracode's plugin option, limits and model on the run", () => {
    const run = pluginRunContext(
      context({ model_name: "smart", mode: "ultracode" }),
      MODELS,
      WITH_WORKFLOWS,
      { maxAgents: 10, maxParallel: 20, maxMinutes: 30 },
    );
    expect(run.mode).toBe("ultracode");
    expect(run.subagent_enabled).toBe(true);
    expect(run.plugin_options).toEqual({
      [ULTRACODE_NAMESPACE]: {
        mode: "ultracode",
        max_agents: 10,
        max_parallel: 10,
        max_minutes: 30,
        model: "smart",
      },
    });
  });

  it("is a fresh copy every time", () => {
    const stored = context({ model_name: "smart", mode: "ultracode" });
    const first = pluginRunContext(stored, MODELS, WITH_WORKFLOWS);
    first.plugin_options![ULTRACODE_NAMESPACE]!.mode = "tampered";
    first.mode = "flash";
    const second = pluginRunContext(stored, MODELS, WITH_WORKFLOWS);
    expect(second.mode).toBe("ultracode");
    expect(second.plugin_options![ULTRACODE_NAMESPACE]!.mode).toBe(
      "ultracode",
    );
  });

  it("names no model while none is known, so the server default applies", () => {
    expect(pluginRunContext(context(), [], LOADED)).toEqual({
      mode: "flash",
      thinking_enabled: false,
      is_plan_mode: false,
      subagent_enabled: false,
    });
  });
});
