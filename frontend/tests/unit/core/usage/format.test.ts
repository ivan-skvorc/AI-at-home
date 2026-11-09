import { expect, test } from "@rstest/core";

import {
  formatTokenShare,
  modelUsageRows,
  splitTokens,
} from "@/core/usage/format";

test("model breakdown sorts by usage without mutating server data", () => {
  const models = {
    flash: {
      tokens: 30,
      runs: 1,

      input_tokens: 20,
      cache_read_tokens: 10,
    },
    pro: {
      tokens: 50,
      runs: 2,

      input_tokens: 40,
      cache_read_tokens: 0,
    },
  };
  expect(modelUsageRows(models).map((row) => row.name)).toEqual([
    "pro",
    "flash",
  ]);
  expect(Object.keys(models)).toEqual(["flash", "pro"]);
});

test.each([
  ["day", { total: 3000, input: 2900, output: 100, cached: 500 }],
  ["model", { total: 1500, input: 1000, output: 500, cached: 500 }],
  ["run", { total: 1200, input: 800, output: 400, cached: 0 }],
])("a %s's split adds up to its total", (_label, usage) => {
  const split = splitTokens(usage);
  expect(split.input + split.output + split.unattributed).toBe(split.total);
  expect(split.total).toBe(usage.total);
  expect(split.unattributed).toBe(0);
  expect(split.cached).toBe(usage.cached);
});

test("a total reported without its split stays unattributed, not input or output", () => {
  expect(splitTokens({ total: 999, input: 0, output: 0 })).toEqual({
    total: 999,
    input: 0,
    cached: 0,
    output: 0,
    unattributed: 999,
  });
  // An older Gateway omits the fields entirely.
  expect(splitTokens({ total: 42 }).unattributed).toBe(42);
});

test("cached is a part of input and never exceeds it", () => {
  const split = splitTokens({ total: 100, input: 60, output: 40, cached: 90 });
  expect(split.cached).toBe(60);
  expect(split.input + split.output + split.unattributed).toBe(100);
});

test("parts larger than the reported total raise the total instead of going negative", () => {
  const split = splitTokens({ total: 50, input: 40, output: 30 });
  expect(split).toMatchObject({ total: 70, unattributed: 0 });
});

test("junk counters count as zero", () => {
  expect(
    splitTokens({ total: Number.NaN, input: -5, output: null, cached: 3 }),
  ).toEqual({ total: 0, input: 0, cached: 0, output: 0, unattributed: 0 });
});

test("shares are whole percentages and absent for an empty total", () => {
  expect(formatTokenShare(2900, 3000, "en-US")).toBe("97%");
  expect(formatTokenShare(0, 0, "en-US")).toBeNull();
});
