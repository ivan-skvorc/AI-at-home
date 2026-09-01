import { describe, expect, it } from "@rstest/core";

import {
  DEFAULT_MODEL_PICKER_PREFS,
  formatContextWindow,
  formatModelSize,
  groupModelsByProvider,
  modelNameSegments,
  modelPriceSortValue,
  modelRowParts,
  compactModelDisplayName,
  parseModelPrice,
  parseModelProvider,
  parseModelProviderLabel,
  resolveModelPrice,
  sortModels,
  splitModelNamePriceSegments,
} from "@/core/models/sorting";
import type { Model, ModelPrice } from "@/core/models/types";

function model(name: string, display_name: string): Model {
  return { id: name, name, model: name, display_name };
}

function priced(
  name: string,
  display_name: string,
  price: ModelPrice | null,
): Model {
  return { id: name, name, model: name, display_name, price };
}

describe("modelNameSegments", () => {
  // Prices left `display_name` and moved into their own field. The rendered
  // result must be indistinguishable from before, or the dropdown silently
  // loses the price it has always shown.
  it("renders the price from the field, coloured, when the name has none", () => {
    const m = priced("m", "Claude Sonnet 5 (Anthropic)", {
      currency: "USD",
      input: 3,
      output: 15,
    });
    expect(modelNameSegments(m)).toEqual([
      { text: "Claude Sonnet 5 (Anthropic) ", kind: "text" },
      { text: "($3/15)", kind: "price" },
    ]);
  });

  it("renders a live discount as list-then-promo, matching the old pair", () => {
    const m = priced("m", "Claude Sonnet 5 (Anthropic)", {
      currency: "USD",
      input: 3,
      output: 15,
      discount_input: 2,
      discount_output: 10,
    });
    expect(modelNameSegments(m)).toEqual([
      { text: "Claude Sonnet 5 (Anthropic) ", kind: "text" },
      { text: "($3/15", kind: "listPrice" },
      { text: " → $2/10*)", kind: "promoPrice" },
    ]);
  });

  it("shows no promo once the server has dropped an expired discount", () => {
    const m = priced("m", "GLM-5.2 (OpenRouter)", {
      currency: "USD",
      input: 1.15,
      output: 3.6,
    });
    expect(modelNameSegments(m).some((s) => s.kind === "promoPrice")).toBe(
      false,
    );
  });

  it("keeps fractional rates and trims trailing zeros", () => {
    const m = priced("m", "M", {
      currency: "USD",
      input: 1.15,
      output: 3.6,
    });
    expect(modelNameSegments(m)[1]!.text).toBe("($1.15/3.6)");
  });

  it("does not render the price twice for a legacy name that still embeds it", () => {
    // A config written before the move carries the pair in the name *and* may
    // now also resolve a price; rendering both would read as two prices.
    const m = priced("m", "Claude Sonnet 5 ($3/15) (Anthropic)", {
      currency: "USD",
      input: 3,
      output: 15,
    });
    const text = modelNameSegments(m)
      .map((s) => s.text)
      .join("");
    expect(text).toBe("Claude Sonnet 5 (Anthropic) ($3/15)");
  });

  it("falls back to parsing the name when no price is configured", () => {
    const m = priced("m", "Legacy ($5/25) (Anthropic)", null);
    expect(modelNameSegments(m).some((s) => s.kind === "price")).toBe(true);
  });

  it("renders an unpriced model's name verbatim", () => {
    const m = priced("m", "Qwen3 8B (Ollama)", null);
    expect(modelNameSegments(m)).toEqual([
      { text: "Qwen3 8B (Ollama)", kind: "text" },
    ]);
  });
});

describe("resolveModelPrice", () => {
  it("prefers the server-resolved price over the display name", () => {
    // The name is a label; `price` is data. When they disagree the field wins,
    // so the picker agrees with what the cost overview actually bills.
    const m = priced("m", "M ($99/99)", {
      currency: "USD",
      input: 3,
      output: 15,
    });
    expect(resolveModelPrice(m)).toEqual({
      input: 3,
      output: 15,
      discounted: false,
      currency: "USD",
    });
  });

  it("reports an active discount as the current price", () => {
    const m = priced("m", "M ($3/15)", {
      currency: "USD",
      input: 3,
      output: 15,
      discount_input: 1.5,
      discount_output: 7.5,
    });
    expect(resolveModelPrice(m)).toEqual({
      input: 1.5,
      output: 7.5,
      discounted: true,
      currency: "USD",
    });
  });

  it("shows no discount once the server has dropped an expired one", () => {
    // The server applies `until`, so an expired discount simply is not in the
    // payload. The client must not resurrect it from the display name's
    // starred pair, which is static text nobody updates.
    const m = priced("m", "M ($3/15 → $1.5/7.5*)", {
      currency: "USD",
      input: 3,
      output: 15,
    });
    expect(resolveModelPrice(m)).toEqual({
      input: 3,
      output: 15,
      discounted: false,
      currency: "USD",
    });
  });

  it("falls back to the display name when no price is configured", () => {
    expect(resolveModelPrice(priced("m", "M ($3/15)", null))).toEqual({
      input: 3,
      output: 15,
      discounted: false,
      currency: "USD",
    });
  });

  it("is null when neither source carries a price", () => {
    expect(resolveModelPrice(priced("m", "Qwen3 8B", null))).toBeNull();
  });

  it("ignores a malformed price payload rather than rendering NaN", () => {
    const m = priced("m", "M ($3/15)", {
      currency: "USD",
      input: Number.NaN,
      output: 15,
    });
    expect(resolveModelPrice(m)?.input).toBe(3);
  });

  it("sorts by the server price when one is present", () => {
    const cheap = priced("cheap", "Cheap ($99/99)", {
      currency: "USD",
      input: 1,
      output: 2,
    });
    expect(modelPriceSortValue(cheap)).toBe(2);
  });
});

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

describe("splitModelNamePriceSegments", () => {
  it("picks out the single price of an ordinary model", () => {
    expect(
      splitModelNamePriceSegments("Claude Opus 4.8 ($5/25) (Anthropic)"),
    ).toEqual([
      { text: "Claude Opus 4.8 (", kind: "text" },
      { text: "$5/25", kind: "price" },
      { text: ") (Anthropic)", kind: "text" },
    ]);
  });

  it("splits a promo pair into list price then promo price", () => {
    expect(
      splitModelNamePriceSegments(
        "GLM-5.2 ($1.15/3.6 → $0.28/0.87*) (OpenRouter) (p)",
      ),
    ).toEqual([
      { text: "GLM-5.2 (", kind: "text" },
      { text: "$1.15/3.6", kind: "listPrice" },
      { text: " → ", kind: "text" },
      { text: "$0.28/0.87", kind: "promoPrice" },
      { text: "*) (OpenRouter) (p)", kind: "text" },
    ]);
  });

  it("reassembles to the original name in every case", () => {
    // The picker renders these segments in place of the raw string, so losing
    // or duplicating a character would silently corrupt a model's name.
    for (const name of [
      "Claude Opus 4.8 ($5/25) (Anthropic)",
      "GLM-5.2 ($1.15/3.6 → $0.28/0.87*) (OpenRouter) (p)",
      "qwen3:32b (Ollama)",
      "Doubao-Seed-1.8",
      "$3/15",
    ]) {
      expect(
        splitModelNamePriceSegments(name)
          .map((segment) => segment.text)
          .join(""),
      ).toBe(name);
    }
  });

  it("returns one plain text segment when there is no price", () => {
    expect(splitModelNamePriceSegments("qwen3:32b (Ollama)")).toEqual([
      { text: "qwen3:32b (Ollama)", kind: "text" },
    ]);
    // A bare version number is not a price — same anchor rule as parseModelPrice.
    expect(splitModelNamePriceSegments("Gemini 3.6 Flash")).toEqual([
      { text: "Gemini 3.6 Flash", kind: "text" },
    ]);
  });

  it("handles an empty or missing name without throwing", () => {
    expect(splitModelNamePriceSegments("")).toEqual([]);
    expect(splitModelNamePriceSegments(null)).toEqual([]);
    expect(splitModelNamePriceSegments(undefined)).toEqual([]);
  });

  it("does not share regex state between calls", () => {
    const promo = "GLM-5.2 ($1.15/3.6 → $0.28/0.87*) (OpenRouter)";
    expect(splitModelNamePriceSegments(promo)).toEqual(
      splitModelNamePriceSegments(promo),
    );
  });

  it("leaves a third price run as plain text rather than guessing", () => {
    const segments = splitModelNamePriceSegments(
      "Odd ($1/2 → $0.5/1* was $9/9)",
    );
    expect(segments.filter((s) => s.kind !== "text")).toEqual([
      { text: "$1/2", kind: "listPrice" },
      { text: "$0.5/1", kind: "promoPrice" },
    ]);
    expect(segments.map((s) => s.text).join("")).toBe(
      "Odd ($1/2 → $0.5/1* was $9/9)",
    );
  });
});

describe("compactModelDisplayName", () => {
  it("drops the provider suffix but keeps the price pair and (p)", () => {
    expect(
      compactModelDisplayName(
        "GLM-5.2 ($1.15/3.6 → $0.28/0.87*) (OpenRouter) (p)",
      ),
    ).toBe("GLM-5.2 ($1.15/3.6 → $0.28/0.87*) (p)");
    expect(
      compactModelDisplayName("Claude Sonnet 5 ($3/15 → $2/10*) (Anthropic)"),
    ).toBe("Claude Sonnet 5 ($3/15 → $2/10*)");
  });

  it("handles the first-party home suffixes without a hardcoded list", () => {
    // Each lab's "home" block adds its own suffix, so the rule is structural
    // (a trailing group with no `$`), not an enumeration of provider names.
    expect(compactModelDisplayName("GPT-5.6 Sol ($1.25/10) (OpenAI)")).toBe(
      "GPT-5.6 Sol ($1.25/10)",
    );
    expect(compactModelDisplayName("Grok 5 ($3/15) (xAI)")).toBe(
      "Grok 5 ($3/15)",
    );
  });

  it("never strips the price group itself", () => {
    for (const name of [
      "Claude Opus 4.8 ($5/25) (Anthropic)",
      "MiniMax M3 ($0.6/2.4 → $0.24/0.96*) (OpenRouter) (p)",
    ]) {
      expect(compactModelDisplayName(name)).toContain("$");
    }
  });

  it("leaves a name with no trailing suffix untouched", () => {
    expect(compactModelDisplayName("Doubao-Seed-1.8")).toBe("Doubao-Seed-1.8");
    expect(compactModelDisplayName("qwen3:32b (Ollama)")).toBe("qwen3:32b");
  });

  it("returns the original when stripping would leave nothing", () => {
    // A hand-added model named only "(local)" must still render something.
    expect(compactModelDisplayName("(local)")).toBe("(local)");
    expect(compactModelDisplayName("(OpenRouter) (p)")).toBe(
      "(OpenRouter) (p)",
    );
  });

  it("handles empty and missing names", () => {
    expect(compactModelDisplayName("")).toBe("");
    expect(compactModelDisplayName(null)).toBe("");
    expect(compactModelDisplayName(undefined)).toBe("");
  });

  it("keeps the promo pair intact for every discounted bundled model", () => {
    // The whole point of the compact form: the trigger button is ~160-224px, so
    // both halves of the pair must survive the shortening.
    for (const name of [
      "Claude Sonnet 5 ($3/15 → $2/10*) (Anthropic)",
      "MiniMax M3 ($0.6/2.4 → $0.24/0.96*) (OpenRouter) (p)",
      "GLM-5.2 ($1.15/3.6 → $0.28/0.87*) (OpenRouter) (p)",
    ]) {
      const segments = splitModelNamePriceSegments(
        compactModelDisplayName(name),
      );
      expect(segments.map((s) => s.kind)).toContain("listPrice");
      expect(segments.map((s) => s.kind)).toContain("promoPrice");
    }
  });
});

describe("parseModelProviderLabel", () => {
  // `parseModelProvider` buckets a model for sorting; this names it for the eye.
  // The two are deliberately different: nine first-party labs share the "Other"
  // bucket, and a row that called Grok "Other" would be worse than no label.
  it("reads the literal suffix, not the four-way sort bucket", () => {
    expect(parseModelProviderLabel("Claude Opus 5 (Anthropic)")).toBe(
      "Anthropic",
    );
    expect(parseModelProviderLabel("Grok 5 (xAI)")).toBe("xAI");
    expect(parseModelProviderLabel("qwen3:8b (Ollama)")).toBe("Ollama");
    // ...where the sort bucket for the same name is "Other".
    expect(parseModelProvider("Grok 5 (xAI)")).toBe("Other");
  });

  it("skips the privacy marker rather than reporting `p` as a provider", () => {
    // `(p)` rides *after* the provider suffix, so a naive last-group read finds
    // the marker on exactly the models that most need their provider shown.
    expect(parseModelProviderLabel("MiniMax M3 (OpenRouter) (p)")).toBe(
      "OpenRouter",
    );
    expect(parseModelProviderLabel("Local Thing (p)")).toBe(null);
  });

  it("stops at a price group instead of reading it as a provider", () => {
    expect(parseModelProviderLabel("Claude Opus 4.8 ($5/25)")).toBe(null);
    expect(parseModelProviderLabel("Claude Opus 4.8 ($5/25) (Anthropic)")).toBe(
      "Anthropic",
    );
  });

  it("has no provider for a bare name, an empty name, or a name in brackets", () => {
    expect(parseModelProviderLabel("Doubao-Seed-1.8")).toBe(null);
    expect(parseModelProviderLabel("")).toBe(null);
    expect(parseModelProviderLabel(null)).toBe(null);
    // A hand-added model called only "(local)" is its own name, not a provider.
    expect(parseModelProviderLabel("(local)")).toBe(null);
  });
});

describe("formatModelSize", () => {
  it("reports weights in binary units, matching the VRAM budget they compete with", () => {
    // `ollama.vram_gb` is read as GiB (FORK.md §1). Quoting weights in GB would
    // put the two figures ~7% apart in the one comparison the number is for.
    expect(formatModelSize(5 * 1024 ** 3)).toBe("5 GiB");
    expect(formatModelSize(9.3 * 1024 ** 3)).toBe("9.3 GiB");
    expect(formatModelSize(300 * 1024 ** 2)).toBe("300 MiB");
  });

  it("has nothing to show for a hosted model", () => {
    // Every cloud model takes this path; a "0 B" chip on all of them would be
    // noise on the rows the size cannot apply to.
    expect(formatModelSize(null)).toBe(null);
    expect(formatModelSize(undefined)).toBe(null);
    expect(formatModelSize(0)).toBe(null);
    expect(formatModelSize(Number.NaN)).toBe(null);
    expect(formatModelSize(-1)).toBe(null);
  });
});

describe("formatContextWindow", () => {
  it("abbreviates with whichever convention the number is exact in", () => {
    // A window is advertised in both: 32768 is "32K" everywhere, 200000 is
    // "200K". One fixed divisor renders one of the two ~5% off its own name.
    expect(formatContextWindow(32768)).toBe("32K");
    expect(formatContextWindow(131072)).toBe("128K");
    expect(formatContextWindow(200000)).toBe("200K");
    expect(formatContextWindow(1000000)).toBe("1M");
    expect(formatContextWindow(1048576)).toBe("1M");
    expect(formatContextWindow(900)).toBe("900");
  });

  it("shows nothing when the deployment configured no window", () => {
    expect(formatContextWindow(null)).toBe(null);
    expect(formatContextWindow(undefined)).toBe(null);
    expect(formatContextWindow(0)).toBe(null);
  });
});

describe("modelRowParts", () => {
  const rowModel = (
    display_name: string,
    extra: Partial<Model> = {},
  ): Model => ({ id: "m", name: "m", model: "m", display_name, ...extra });

  it("splits a bundled model into provider, bare name, and a pinned price", () => {
    // The row positions these three independently — provider first, price at
    // the far edge — which a single rendered string cannot express.
    expect(
      modelRowParts(
        rowModel("Claude Sonnet 5 (Anthropic)", {
          price: { currency: "USD", input: 3, output: 15 },
        }),
      ),
    ).toEqual({
      provider: "Anthropic",
      name: "Claude Sonnet 5",
      price: [{ text: "($3/15)", kind: "price" }],
      size: null,
      contextWindow: null,
    });
  });

  it("keeps the discounted pair's colours: list price red, promo green", () => {
    const parts = modelRowParts(
      rowModel("MiniMax M3 (OpenRouter) (p)", {
        price: {
          currency: "USD",
          input: 0.6,
          output: 2.4,
          discount_input: 0.24,
          discount_output: 0.96,
        },
      }),
    );
    // The privacy marker belongs to the name and must survive; the provider is
    // lifted out from behind it.
    expect(parts.name).toBe("MiniMax M3 (p)");
    expect(parts.provider).toBe("OpenRouter");
    expect(parts.price).toEqual([
      { text: "($0.6/2.4", kind: "listPrice" },
      { text: " → $0.24/0.96*)", kind: "promoPrice" },
    ]);
  });

  it("prices a legacy name from the name, without leaving a half-stripped bracket", () => {
    // A config written before §17 carries the pair inside `display_name`. The
    // group is removed whole, so the name never comes back as "GLM-5.2 ( → )".
    const parts = modelRowParts(
      rowModel("GLM-5.2 ($1.15/3.6 → $0.28/0.87*) (OpenRouter) (p)"),
    );
    expect(parts.name).toBe("GLM-5.2 (p)");
    expect(parts.price).toEqual([
      { text: "($1.15/3.6", kind: "listPrice" },
      { text: " → $0.28/0.87*)", kind: "promoPrice" },
    ]);
    expect(
      modelRowParts(rowModel("Claude Opus 4.8 ($5/25) (Anthropic)")),
    ).toMatchObject({
      name: "Claude Opus 4.8",
      price: [{ text: "($5/25)", kind: "price" }],
    });
  });

  it("prefers the structured price and does not render the name's copy twice", () => {
    const parts = modelRowParts(
      rowModel("Claude Opus 4.8 ($5/25) (Anthropic)", {
        price: { currency: "USD", input: 4, output: 20 },
      }),
    );
    expect(parts.name).toBe("Claude Opus 4.8");
    expect(parts.price).toEqual([{ text: "($4/20)", kind: "price" }]);
  });

  it("surfaces a local model's weights and window, and nothing for a hosted one", () => {
    // The reason the fields exist: how much of the GPU the weights take decides
    // how much room is left for the window the entry asks for.
    expect(
      modelRowParts(
        rowModel("qwen3:8b (Ollama)", {
          size_bytes: 5.2 * 1024 ** 3,
          context_window: 32768,
        }),
      ),
    ).toEqual({
      provider: "Ollama",
      name: "qwen3:8b",
      price: [],
      size: "5.2 GiB",
      contextWindow: "32K",
    });
    expect(modelRowParts(rowModel("Claude Opus 5 (Anthropic)"))).toMatchObject({
      size: null,
      contextWindow: null,
    });
  });

  it("renders an unrecognized name verbatim rather than swallowing half of it", () => {
    // Total, like every other parser here: nothing the row cannot classify is
    // dropped — it stays in the name, where the user can still read it.
    expect(modelRowParts(rowModel("Doubao-Seed-1.8"))).toEqual({
      provider: null,
      name: "Doubao-Seed-1.8",
      price: [],
      size: null,
      contextWindow: null,
    });
    // A `$` pair the group regex does not recognize is left in the name rather
    // than being lifted out and rendered twice.
    const odd = modelRowParts(rowModel("Odd $1/2 model (Anthropic)"));
    expect(odd.price).toEqual([]);
    expect(odd.name).toBe("Odd $1/2 model");
    expect(modelRowParts(rowModel(""))).toMatchObject({
      provider: null,
      name: "",
    });
  });
});
