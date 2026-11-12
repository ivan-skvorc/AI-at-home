import { describe, expect, it } from "@rstest/core";

import { mergeLocalSettings, type LocalSettings } from "@/core/settings/local";
import { parsePreferences } from "@/core/settings/preferences-sync";
import {
  deriveModeContext,
  modeUsesSubagents,
} from "@/core/threads/run-context";
import {
  DEFAULT_ULTRACODE_LIMITS,
  isUltracodeAvailable,
  normalizeUltracodeLimits,
  ULTRACODE_NAMESPACE,
  ultracodePluginOptions,
} from "@/core/threads/ultracode";

describe("Double Plus Ultracode run context", () => {
  it("is an Ultra run plus the one plugin option the extension reads", () => {
    const derived = deriveModeContext({
      mode: "ultracode",
      ultracode_limits: { maxAgents: 12, maxParallel: 3, maxMinutes: 30 },
    });
    expect(derived).toMatchObject({
      thinking_enabled: true,
      is_plan_mode: true,
      subagent_enabled: true,
      reasoning_effort: "high",
    });
    expect(derived.plugin_options).toEqual({
      [ULTRACODE_NAMESPACE]: {
        mode: "ultracode",
        max_agents: 12,
        max_parallel: 3,
        max_minutes: 30,
      },
    });
  });

  it("sends double_ultracode the same way, which is what lifts automatic limits", () => {
    const derived = deriveModeContext({
      mode: "double_ultracode",
      ultracode_limits: { maxAgents: 12, maxParallel: 3, maxMinutes: 30 },
    });
    expect(derived).toMatchObject({
      thinking_enabled: true,
      is_plan_mode: true,
      subagent_enabled: true,
      reasoning_effort: "high",
    });
    expect(derived.plugin_options).toEqual({
      [ULTRACODE_NAMESPACE]: {
        mode: "double_ultracode",
        max_agents: 12,
        max_parallel: 3,
        max_minutes: 30,
      },
    });
  });

  it("carries the conversation's model and a switched-off internet to the extension", () => {
    // Workflow agents and the result turn are separate runs: without these two
    // keys they fall back to the server's default model with web tools on.
    for (const mode of ["ultracode", "double_ultracode"] as const) {
      const derived = deriveModeContext({
        mode,
        model_name: "chosen-model",
        internet_enabled: false,
        ultracode_limits: { maxAgents: 12, maxParallel: 3, maxMinutes: 30 },
      });
      expect(derived.plugin_options).toEqual({
        [ULTRACODE_NAMESPACE]: {
          mode,
          max_agents: 12,
          max_parallel: 3,
          max_minutes: 30,
          model: "chosen-model",
          internet_enabled: false,
        },
      });
    }
  });

  it("omits the model without an explicit one and the internet key while it is on", () => {
    // Absent means "no opinion" to the extension; `internet_enabled: true` or an
    // empty model would be a value it has to interpret.
    for (const internet_enabled of [true, undefined, "false"]) {
      for (const model_name of [undefined, ""]) {
        const options = deriveModeContext({
          mode: "double_ultracode",
          model_name,
          internet_enabled,
        }).plugin_options?.[ULTRACODE_NAMESPACE];
        expect(options).toBeDefined();
        expect("model" in options!).toBe(false);
        expect("internet_enabled" in options!).toBe(false);
      }
    }
    expect(
      ultracodePluginOptions({}, "ultracode", { internetEnabled: false })[
        ULTRACODE_NAMESPACE
      ],
    ).toEqual({
      mode: "ultracode",
      max_agents: DEFAULT_ULTRACODE_LIMITS.maxAgents,
      max_parallel: DEFAULT_ULTRACODE_LIMITS.maxParallel,
      max_minutes: DEFAULT_ULTRACODE_LIMITS.maxMinutes,
      internet_enabled: false,
    });
    expect(
      ultracodePluginOptions({}, "ultracode", { model: "chosen-model" })[
        ULTRACODE_NAMESPACE
      ],
    ).toEqual({
      mode: "ultracode",
      max_agents: DEFAULT_ULTRACODE_LIMITS.maxAgents,
      max_parallel: DEFAULT_ULTRACODE_LIMITS.maxParallel,
      max_minutes: DEFAULT_ULTRACODE_LIMITS.maxMinutes,
      model: "chosen-model",
    });
  });

  it("never sends the option on any other mode", () => {
    for (const mode of [
      "flash",
      "thinking",
      "pro",
      "ultra",
      "democracy",
    ] as const) {
      const derived = deriveModeContext({
        mode,
        ultracode_limits: { maxAgents: 12, maxParallel: 3 },
      });
      // Present-and-undefined is what overwrites a value left by the spread.
      expect("plugin_options" in derived).toBe(true);
      expect(derived.plugin_options).toBeUndefined();
    }
  });
});

describe("Double Plus Ultracode limits", () => {
  it("keeps whole numbers within the extension's ceilings", () => {
    expect(
      normalizeUltracodeLimits({
        maxAgents: 40,
        maxParallel: 6,
        maxMinutes: 90,
      }),
    ).toEqual({
      maxAgents: 40,
      maxParallel: 6,
      maxMinutes: 90,
    });
    for (const bad of [0, -1, 2.5, "8", 10_000, Number.NaN, null]) {
      expect(
        normalizeUltracodeLimits({
          maxAgents: bad,
          maxParallel: bad,
          maxMinutes: bad,
        }),
      ).toEqual(DEFAULT_ULTRACODE_LIMITS);
    }
    expect(normalizeUltracodeLimits("garbage")).toEqual(
      DEFAULT_ULTRACODE_LIMITS,
    );
  });

  it("never asks for more at once than in total", () => {
    expect(
      ultracodePluginOptions({ maxAgents: 2, maxParallel: 8 })[
        ULTRACODE_NAMESPACE
      ],
    ).toEqual({
      mode: "ultracode",
      max_agents: 2,
      max_parallel: 2,
      max_minutes: DEFAULT_ULTRACODE_LIMITS.maxMinutes,
    });
  });

  it("defaults to the extension's ceilings", () => {
    expect(DEFAULT_ULTRACODE_LIMITS).toEqual({
      maxAgents: 256,
      maxParallel: 16,
      maxMinutes: 240,
    });
  });

  it("moves the old saved defaults to the new ones, but keeps a chosen pair", () => {
    // Every browser saved {64, 8} whole before maxMinutes existed (FORK.md §46).
    expect(normalizeUltracodeLimits({ maxAgents: 64, maxParallel: 8 })).toEqual(
      DEFAULT_ULTRACODE_LIMITS,
    );
    expect(
      normalizeUltracodeLimits({
        maxAgents: 64,
        maxParallel: 8,
        maxMinutes: 60,
      }),
    ).toEqual({ maxAgents: 64, maxParallel: 8, maxMinutes: 60 });
    expect(normalizeUltracodeLimits({ maxAgents: 20, maxParallel: 8 })).toEqual(
      {
        maxAgents: 20,
        maxParallel: 8,
        maxMinutes: DEFAULT_ULTRACODE_LIMITS.maxMinutes,
      },
    );
  });

  it("loads stored settings through the same normalization", () => {
    expect(mergeLocalSettings({}).ultracode).toEqual(DEFAULT_ULTRACODE_LIMITS);
    expect(
      mergeLocalSettings({
        ultracode: { maxAgents: 999, maxParallel: 4 },
      } as Partial<LocalSettings>).ultracode,
    ).toEqual({
      maxAgents: DEFAULT_ULTRACODE_LIMITS.maxAgents,
      maxParallel: 4,
      maxMinutes: DEFAULT_ULTRACODE_LIMITS.maxMinutes,
    });
    // The upgrade must see the stored object, not one pre-merged with defaults.
    expect(
      mergeLocalSettings({
        ultracode: { maxAgents: 64, maxParallel: 8 },
      } as Partial<LocalSettings>).ultracode,
    ).toEqual(DEFAULT_ULTRACODE_LIMITS);
  });

  it("round-trips the mode through the account preference", () => {
    expect(parsePreferences({ mode: "ultracode" })).toEqual({
      mode: "ultracode",
    });
    expect(parsePreferences({ mode: "double_ultracode" })).toEqual({
      mode: "double_ultracode",
    });
  });
});

describe("Double Plus Ultracode availability", () => {
  it("is offered only when Script workflows is installed and enabled", () => {
    expect(isUltracodeAvailable(undefined)).toBe(false);
    expect(isUltracodeAvailable([])).toBe(false);
    expect(
      isUltracodeAvailable([
        { namespace: ULTRACODE_NAMESPACE, settings: { enabled: false } },
      ]),
    ).toBe(false);
    expect(
      isUltracodeAvailable([
        { namespace: "community.other", settings: { enabled: true } },
      ]),
    ).toBe(false);
    expect(
      isUltracodeAvailable([
        { namespace: ULTRACODE_NAMESPACE, settings: { enabled: true } },
      ]),
    ).toBe(true);
  });
});

describe("modeUsesSubagents", () => {
  // The chat pages refused a per-task model choice with "Enable Ultra mode
  // first" in Plus/Double Plus Ultracode and Democracy, which all delegate.
  it("covers every mode that turns task delegation on, and only those", () => {
    for (const mode of [
      "ultra",
      "democracy",
      "ultracode",
      "double_ultracode",
    ] as const) {
      expect(modeUsesSubagents(mode)).toBe(true);
      expect(deriveModeContext({ mode }).subagent_enabled).toBe(true);
    }
    for (const mode of ["flash", "thinking", "pro", undefined] as const) {
      expect(modeUsesSubagents(mode)).toBe(false);
      expect(deriveModeContext({ mode }).subagent_enabled).toBe(false);
    }
  });
});
