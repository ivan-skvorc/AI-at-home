import { describe, expect, test } from "@rstest/core";

import {
  getResolvedMode,
  lacksToolSupport,
  sortModelsByToolSupport,
} from "@/core/models/capabilities";
import type { Model } from "@/core/models/types";

function makeModel(overrides: Partial<Model> & { name: string }): Model {
  return {
    id: overrides.name,
    model: overrides.name,
    display_name: overrides.name,
    ...overrides,
  } as Model;
}

describe("getResolvedMode", () => {
  test("keeps pro and ultra selectable on models without thinking support", () => {
    // Regression: every non-flash mode used to snap back to "flash" when the
    // selected model lacked supports_thinking, locking cloud models (which
    // default to supports_thinking=false) out of pro/ultra entirely.
    expect(getResolvedMode("pro", false)).toBe("pro");
    expect(getResolvedMode("ultra", false)).toBe("ultra");
  });

  test("downgrades thinking mode to flash when the model lacks thinking", () => {
    expect(getResolvedMode("thinking", false)).toBe("flash");
  });

  test("keeps thinking mode on thinking-capable models", () => {
    expect(getResolvedMode("thinking", true)).toBe("thinking");
  });

  test("keeps flash regardless of capability", () => {
    expect(getResolvedMode("flash", true)).toBe("flash");
    expect(getResolvedMode("flash", false)).toBe("flash");
  });

  test("defaults undefined mode by thinking capability", () => {
    expect(getResolvedMode(undefined, true)).toBe("pro");
    expect(getResolvedMode(undefined, false)).toBe("flash");
  });
});

describe("lacksToolSupport", () => {
  test("only an explicit supports_tools: false counts as lacking tools", () => {
    expect(lacksToolSupport({ supports_tools: false })).toBe(true);
    expect(lacksToolSupport({ supports_tools: true })).toBe(false);
    // Unknown (models without the flag in config.yaml, e.g. hand-added
    // cloud models) must be treated as tool-capable.
    expect(lacksToolSupport({})).toBe(false);
    expect(lacksToolSupport({ supports_tools: undefined })).toBe(false);
  });
});

describe("sortModelsByToolSupport", () => {
  test("puts tool-capable models first, alphabetical within groups", () => {
    const models = [
      makeModel({ name: "zeta", supports_tools: false }),
      makeModel({ name: "beta" }),
      makeModel({ name: "alpha", supports_tools: false }),
      makeModel({ name: "delta", supports_tools: true }),
    ];
    expect(sortModelsByToolSupport(models).map((m) => m.name)).toEqual([
      "beta",
      "delta",
      "alpha",
      "zeta",
    ]);
  });

  test("does not mutate the input array", () => {
    const models = [
      makeModel({ name: "b", supports_tools: false }),
      makeModel({ name: "a" }),
    ];
    const before = models.map((m) => m.name);
    sortModelsByToolSupport(models);
    expect(models.map((m) => m.name)).toEqual(before);
  });
});
