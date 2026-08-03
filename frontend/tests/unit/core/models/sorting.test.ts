import { describe, expect, it } from "@rstest/core";

import {
  DEFAULT_MODEL_PICKER_PREFS,
  groupModelsByProvider,
  modelPriceSortValue,
  parseModelPrice,
  parseModelProvider,
  sortModels,
} from "@/core/models/sorting";
import type { Model } from "@/core/models/types";

function model(name: string, display_name: string): Model {
  return { id: name, name, model: name, display_name };
}

describe("parseModelPrice", () => {
  it("reads a single price pair", () => {
    expect(parseModelPrice("Claude Opus 4.8 ($5/25) (Anthropic)")).toEqual({
      input: 5,
      output: 25,
      discounted: false,
      currency: "USD",
    });
  });

  it("reads decimal prices", () => {
    expect(
      parseModelPrice("GPT-5.3 Codex ($1.75/14) (OpenRouter) (p)"),
    ).toEqual({ input: 1.75, output: 14, discounted: false, currency: "USD" });
  });

  it("returns the discounted (current) pair, not the list price", () => {
    // Anthropic intro pricing: list $3/15, current (starred) $2/10.
    expect(
      parseModelPrice("Claude Sonnet 5 ($3/15 → $2/10*) (Anthropic)"),
    ).toEqual({ input: 2, output: 10, discounted: true, currency: "USD" });
    // OpenRouter promo with decimals.
    expect(
      parseModelPrice("GLM-5.2 ($1.15/3.6 → $0.28/0.87*) (OpenRouter) (p)"),
    ).toEqual({ input: 0.28, output: 0.87, discounted: true, currency: "USD" });
  });

  it("returns null when there is no price (Ollama / unpriced)", () => {
    expect(parseModelPrice("qwen3:32b (Ollama)")).toBeNull();
    expect(parseModelPrice("Doubao-Seed-1.8")).toBeNull();
    expect(parseModelPrice("")).toBeNull();
    expect(parseModelPrice(undefined)).toBeNull();
  });

  it("does not misread bare version numbers as a price", () => {
    // No leading `$`, so `4.8` / `3.6` are not prices.
    expect(parseModelPrice("Gemini 3.6 Flash")).toBeNull();
    expect(parseModelPrice("Claude Opus 4.8")).toBeNull();
  });
});

describe("parseModelProvider", () => {
  it("detects the three bundled providers from the suffix", () => {
    expect(parseModelProvider("Claude Opus 4.8 ($5/25) (Anthropic)")).toBe(
      "Anthropic",
    );
    expect(parseModelProvider("Grok 4.5 ($2/6) (OpenRouter) (p)")).toBe(
      "OpenRouter",
    );
    expect(parseModelProvider("qwen3:32b (Ollama)")).toBe("Ollama");
  });

  it("falls back to Other for anything without a known suffix", () => {
    expect(parseModelProvider("Doubao-Seed-1.8")).toBe("Other");
    expect(parseModelProvider(undefined)).toBe("Other");
  });
});

describe("modelPriceSortValue", () => {
  it("uses the current output price, null when unpriced", () => {
    expect(
      modelPriceSortValue(
        model("s5", "Claude Sonnet 5 ($3/15 → $2/10*) (Anthropic)"),
      ),
    ).toBe(10);
    expect(modelPriceSortValue(model("q", "qwen3:32b (Ollama)"))).toBeNull();
  });
});

describe("sortModels", () => {
  const opus = model("opus", "Claude Opus 4.8 ($5/25) (Anthropic)");
  const haiku = model("haiku", "Claude Haiku 4.5 ($1/5) (Anthropic)");
  const gemini = model(
    "gemini",
    "Gemini 3.6 Flash ($1.5/7.5) (OpenRouter) (p)",
  );
  const local = model("local", "qwen3:32b (Ollama)");
  const models = [opus, haiku, gemini, local];

  it("default keeps the incoming order", () => {
    expect(
      sortModels(models, { sortKey: "default", sortDir: "asc" }).map(
        (m) => m.name,
      ),
    ).toEqual(["opus", "haiku", "gemini", "local"]);
  });

  it("sorts by name ascending and descending", () => {
    expect(
      sortModels(models, { sortKey: "name", sortDir: "asc" }).map(
        (m) => m.display_name,
      ),
    ).toEqual([
      "Claude Haiku 4.5 ($1/5) (Anthropic)",
      "Claude Opus 4.8 ($5/25) (Anthropic)",
      "Gemini 3.6 Flash ($1.5/7.5) (OpenRouter) (p)",
      "qwen3:32b (Ollama)",
    ]);
    expect(
      sortModels(models, { sortKey: "name", sortDir: "desc" }).map(
        (m) => m.name,
      ),
    ).toEqual(["local", "gemini", "opus", "haiku"]);
  });

  it("sorts by current output price with unpriced last in both directions", () => {
    // asc: haiku(5) < gemini(7.5) < opus(25), local unpriced last.
    expect(
      sortModels(models, { sortKey: "price", sortDir: "asc" }).map(
        (m) => m.name,
      ),
    ).toEqual(["haiku", "gemini", "opus", "local"]);
    // desc: opus(25) > gemini(7.5) > haiku(5), local still last.
    expect(
      sortModels(models, { sortKey: "price", sortDir: "desc" }).map(
        (m) => m.name,
      ),
    ).toEqual(["opus", "gemini", "haiku", "local"]);
  });

  it("does not mutate the input array", () => {
    const input = [opus, haiku];
    sortModels(input, { sortKey: "name", sortDir: "asc" });
    expect(input.map((m) => m.name)).toEqual(["opus", "haiku"]);
  });

  it("demoteLast keeps matching models last, ordered by the key within partitions", () => {
    // `local` is demoted; the priced models sort by name above it.
    const demoteLast = (m: { name: string }) => m.name === "local";
    // Name-asc among the priced models: "Claude Haiku" < "Claude Opus" < "Gemini".
    expect(
      sortModels(
        models,
        { sortKey: "name", sortDir: "asc" },
        { demoteLast },
      ).map((m) => m.name),
    ).toEqual(["haiku", "opus", "gemini", "local"]);
    // Under the default key, demoteLast still partitions while preserving order.
    expect(
      sortModels(
        [local, opus, haiku],
        { sortKey: "default", sortDir: "asc" },
        { demoteLast },
      ).map((m) => m.name),
    ).toEqual(["opus", "haiku", "local"]);
  });
});

describe("groupModelsByProvider", () => {
  const opus = model("opus", "Claude Opus 4.8 ($5/25) (Anthropic)");
  const haiku = model("haiku", "Claude Haiku 4.5 ($1/5) (Anthropic)");
  const grok = model("grok", "Grok 4.5 ($2/6) (OpenRouter) (p)");
  const local = model("local", "qwen3:32b (Ollama)");

  it("buckets by provider in a stable order and sorts within", () => {
    const groups = groupModelsByProvider([local, grok, opus, haiku], {
      sortKey: "price",
      sortDir: "asc",
    });
    expect(groups.map((g) => g.provider)).toEqual([
      "Anthropic",
      "OpenRouter",
      "Ollama",
    ]);
    // Anthropic group is price-sorted: haiku(5) before opus(25).
    expect(groups[0]!.models.map((m) => m.name)).toEqual(["haiku", "opus"]);
  });

  it("omits empty provider buckets", () => {
    const groups = groupModelsByProvider([grok], DEFAULT_MODEL_PICKER_PREFS);
    expect(groups.map((g) => g.provider)).toEqual(["OpenRouter"]);
  });
});
