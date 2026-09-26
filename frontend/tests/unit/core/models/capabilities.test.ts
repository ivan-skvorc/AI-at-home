import { describe, expect, test } from "@rstest/core";

import { lacksToolSupport } from "@/core/models/capabilities";
import { getResolvedMode } from "@/core/models/reasoning";
import type { Model } from "@/core/models/types";

function model(supportsThinking: boolean): Model {
  return {
    id: "m",
    name: "m",
    model: "m",
    display_name: "M",
    supports_thinking: supportsThinking,
  };
}

const plain = model(false);
const thinking = model(true);

// The fork's mode rule, which upstream's `getResolvedMode` (moved into
// core/models/reasoning.ts in the 2026-09-26 sync) does not share.
describe("getResolvedMode", () => {
  test("keeps pro, ultra and democracy selectable on models without thinking support", () => {
    // Regression: every non-flash mode used to snap back to "flash" when the
    // selected model lacked supports_thinking, locking cloud models (which
    // default to supports_thinking=false) out of pro/ultra entirely.
    expect(getResolvedMode("pro", plain)).toBe("pro");
    expect(getResolvedMode("ultra", plain)).toBe("ultra");
    expect(getResolvedMode("democracy", plain)).toBe("democracy");
  });

  test("downgrades thinking mode to flash when the model lacks thinking", () => {
    expect(getResolvedMode("thinking", plain)).toBe("flash");
  });

  test("keeps thinking mode on thinking-capable models", () => {
    expect(getResolvedMode("thinking", thinking)).toBe("thinking");
  });

  test("keeps flash regardless of capability", () => {
    expect(getResolvedMode("flash", thinking)).toBe("flash");
    expect(getResolvedMode("flash", plain)).toBe("flash");
  });

  test("defaults undefined mode by thinking capability", () => {
    expect(getResolvedMode(undefined, thinking)).toBe("pro");
    expect(getResolvedMode(undefined, plain)).toBe("flash");
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
