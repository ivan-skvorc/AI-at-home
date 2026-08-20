import { expect, test } from "@rstest/core";

import {
  buildCostChartGeometry,
  COST_CHART_DEFAULTS,
  stepValue,
} from "@/core/threads/cost-chart";
import {
  threadStepsToCostSteps,
  type ThreadCostStep,
} from "@/core/threads/token-usage";
import type { ThreadTokenUsageStepResponse } from "@/core/threads/types";

/**
 * The per-step cost chart plots money, so the maths gets tests rather than a
 * glance at a 64px-tall sparkline. The properties that matter:
 *
 * - The cumulative series ends on the thread total, so the chart cannot
 *   contradict the headline figure printed directly above it.
 * - An unpriced step is a gap, not a zero — "this turn was free" is a different
 *   claim from "nothing could price this turn".
 * - The y axis starts at zero, so near-identical turns look near-identical.
 */

function step(
  overrides: Partial<ThreadTokenUsageStepResponse> & { index: number },
): ThreadTokenUsageStepResponse {
  return {
    run_id: `r${overrides.index}`,
    created_at: null,
    tokens: 100,
    cost: null,
    promo_cost: null,
    ...overrides,
  };
}

test("cumulative series is the running total of the per-step costs", () => {
  const steps = threadStepsToCostSteps([
    step({ index: 1, cost: 1 }),
    step({ index: 2, cost: 2 }),
    step({ index: 3, cost: 0.5 }),
  ]);

  expect(steps.map((s) => s.cost)).toEqual([1, 2, 0.5]);
  expect(steps.map((s) => s.cumulativeCost)).toEqual([1, 3, 3.5]);
});

test("the last cumulative value equals the thread total", () => {
  // If these could diverge, the chart would quietly contradict the number in
  // the header right above it.
  const costs = [0.25, 1.75, 0.5, 3];
  const steps = threadStepsToCostSteps(
    costs.map((cost, i) => step({ index: i + 1, cost })),
  );
  const total = costs.reduce((sum, c) => sum + c, 0);
  expect(steps[steps.length - 1]!.cumulativeCost).toBeCloseTo(total, 10);
});

test("an unpriced step keeps a null per-step cost but does not break the running total", () => {
  const steps = threadStepsToCostSteps([
    step({ index: 1, cost: 2 }),
    // A local Ollama turn: nothing to price.
    step({ index: 2, cost: null }),
    step({ index: 3, cost: 1 }),
  ]);

  expect(steps[1]!.cost).toBeNull();
  // The running total stays flat across the gap rather than resetting.
  expect(steps.map((s) => s.cumulativeCost)).toEqual([2, 2, 3]);
});

test("a promo equal to the standard cost is not treated as a discount", () => {
  // Same rule as the headline pair: printing the same number twice in two
  // colours claims a discount that does not exist.
  const [only] = threadStepsToCostSteps([
    step({ index: 1, cost: 2, promo_cost: 2 }),
  ]);
  expect(only!.promoCost).toBeNull();
});

test("the promo running total bills an undiscounted step at its ordinary rate", () => {
  const steps = threadStepsToCostSteps([
    step({ index: 1, cost: 10, promo_cost: null }),
    step({ index: 2, cost: 4, promo_cost: 1 }),
  ]);
  expect(steps[1]!.cumulativeCost).toBe(14);
  // 10 (no discount available) + 1 (discounted) — so the two series stay
  // directly comparable and the saving is the discounted step's alone.
  expect(steps[1]!.cumulativePromoCost).toBe(11);
  expect(steps[1]!.cumulativeCost - steps[1]!.cumulativePromoCost).toBe(3);
});

test("stepValue reads the mode's series", () => {
  const [one] = threadStepsToCostSteps([
    step({ index: 1, cost: 4, promo_cost: 1 }),
  ]);
  // Per-step plots what you actually pay today.
  expect(stepValue(one!, "per-step")).toBe(1);
  expect(stepValue(one!, "cumulative")).toBe(1);
});

test("empty input yields an empty chart rather than throwing", () => {
  const geometry = buildCostChartGeometry([], "per-step");
  expect(geometry.points).toEqual([]);
  expect(geometry.linePath).toBe("");
  expect(geometry.areaPath).toBe("");
  expect(geometry.peak).toBeNull();
});

test("bars are capped rather than filling their slot", () => {
  const steps = threadStepsToCostSteps([step({ index: 1, cost: 1 })]);
  const geometry = buildCostChartGeometry(steps, "per-step");
  expect(geometry.points[0]!.barWidth).toBeLessThanOrEqual(
    COST_CHART_DEFAULTS.maxBarWidth,
  );
});

test("adjacent columns leave a surface gap between them", () => {
  const steps = threadStepsToCostSteps(
    Array.from({ length: 4 }, (_, i) => step({ index: i + 1, cost: 1 })),
  );
  const geometry = buildCostChartGeometry(steps, "per-step");
  const [first, second] = geometry.points;
  const gap = second!.barX - (first!.barX + first!.barWidth);
  expect(gap).toBeGreaterThanOrEqual(COST_CHART_DEFAULTS.barGap - 0.001);
});

test("the y scale starts at zero so near-identical turns look near-identical", () => {
  // With a non-zero baseline these two would render dramatically different.
  const steps = threadStepsToCostSteps([
    step({ index: 1, cost: 100 }),
    step({ index: 2, cost: 101 }),
  ]);
  const geometry = buildCostChartGeometry(steps, "per-step");
  const [a, b] = geometry.points;
  const ratio = b!.barHeight / a!.barHeight;
  expect(ratio).toBeGreaterThan(0.98);
  expect(ratio).toBeLessThan(1.02);
});

test("the tallest column reaches the top of the plot area", () => {
  const steps = threadStepsToCostSteps([
    step({ index: 1, cost: 1 }),
    step({ index: 2, cost: 4 }),
  ]);
  const geometry = buildCostChartGeometry(steps, "per-step");
  const tallest = geometry.points[1]!;
  expect(tallest.barY).toBeCloseTo(COST_CHART_DEFAULTS.paddingTop, 5);
  // And the shorter one is proportional: a quarter of the tall one.
  expect(geometry.points[0]!.barHeight / tallest.barHeight).toBeCloseTo(
    0.25,
    5,
  );
});

test("an unpriced step draws no column", () => {
  const steps = threadStepsToCostSteps([
    step({ index: 1, cost: 2 }),
    step({ index: 2, cost: null }),
  ]);
  const geometry = buildCostChartGeometry(steps, "per-step");
  expect(geometry.points[1]!.value).toBeNull();
  expect(geometry.points[1]!.barHeight).toBe(0);
});

test("cumulative mode produces a line and an area, per-step mode does not", () => {
  const steps = threadStepsToCostSteps([
    step({ index: 1, cost: 1 }),
    step({ index: 2, cost: 1 }),
  ]);
  const cumulative = buildCostChartGeometry(steps, "cumulative");
  expect(cumulative.linePath).toMatch(/^M[\d.]+,[\d.]+ L/);
  // The area closes back down to the baseline.
  expect(cumulative.areaPath.endsWith("Z")).toBe(true);

  const perStep = buildCostChartGeometry(steps, "per-step");
  expect(perStep.linePath).toBe("");
});

test("the cumulative line never descends", () => {
  // A running total is monotonic; a dip would mean the maths is wrong.
  const steps = threadStepsToCostSteps([
    step({ index: 1, cost: 3 }),
    step({ index: 2, cost: 0.1 }),
    step({ index: 3, cost: 5 }),
  ]);
  const geometry = buildCostChartGeometry(steps, "cumulative");
  const ys = geometry.points.map((p) => p.y!);
  // SVG y grows downward, so a non-descending value is a non-increasing y.
  for (let i = 1; i < ys.length; i++) {
    expect(ys[i]!).toBeLessThanOrEqual(ys[i - 1]! + 0.001);
  }
});

test("a single step is centred rather than pinned to the left edge", () => {
  const steps = threadStepsToCostSteps([step({ index: 1, cost: 1 })]);
  const geometry = buildCostChartGeometry(steps, "per-step");
  expect(geometry.points[0]!.x).toBeCloseTo(COST_CHART_DEFAULTS.width / 2, 5);
});

test("peak names the most expensive step", () => {
  const steps = threadStepsToCostSteps([
    step({ index: 1, cost: 1 }),
    step({ index: 2, cost: 9 }),
    step({ index: 3, cost: 3 }),
  ]);
  const geometry = buildCostChartGeometry(steps, "per-step");
  expect(geometry.peak?.index).toBe(2);
  expect(geometry.peak?.value).toBe(9);
});

test("a thread where nothing is priced still lays out without dividing by zero", () => {
  const steps: ThreadCostStep[] = threadStepsToCostSteps([
    step({ index: 1, cost: null }),
    step({ index: 2, cost: null }),
  ]);
  const geometry = buildCostChartGeometry(steps, "per-step");
  expect(geometry.maxValue).toBe(0);
  expect(geometry.points.every((p) => Number.isFinite(p.x))).toBe(true);
  expect(geometry.peak).toBeNull();
});
