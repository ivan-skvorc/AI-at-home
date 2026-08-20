import { afterEach, expect, rs, test } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      tokenUsage: {
        chartTitle: "Cost per step",
        chartPerStep: "Each step",
        chartCumulative: "Running total",
        chartModeLabel: "Cost chart mode",
        chartStepLabel: (step: number, amount: string) =>
          `Step ${step}: ${amount}`,
        chartEmpty: "No priced steps yet.",
        chartAxisHint: "Steps (your messages)",
      },
    },
    changeLocale: rs.fn(),
  }),
}));

import { CostPerStepChart } from "@/components/workspace/cost-per-step-chart";
import {
  threadStepsToCostSteps,
  type ThreadCostStep,
} from "@/core/threads/token-usage";

afterEach(cleanup);

function steps(costs: (number | null)[]): ThreadCostStep[] {
  return threadStepsToCostSteps(
    costs.map((cost, i) => ({
      index: i + 1,
      run_id: `r${i + 1}`,
      created_at: null,
      tokens: 100,
      cost,
      promo_cost: null,
    })),
  );
}

test("renders one column per step in per-step mode", () => {
  render(<CostPerStepChart steps={steps([1, 2, 3])} currency="USD" />);
  expect(
    screen.getByTestId("cost-per-step-chart").getAttribute("data-mode"),
  ).toBe("per-step");
  expect(screen.getByTestId("cost-chart-bar-1")).toBeTruthy();
  expect(screen.getByTestId("cost-chart-bar-3")).toBeTruthy();
});

test("the toggle switches the chart to the running total", () => {
  render(<CostPerStepChart steps={steps([1, 2, 3])} currency="USD" />);

  fireEvent.click(screen.getByTestId("cost-chart-mode-cumulative"));

  expect(
    screen.getByTestId("cost-per-step-chart").getAttribute("data-mode"),
  ).toBe("cumulative");
  // Columns give way to the line+area form, which is the right shape for a
  // running total rather than a set of independent quantities.
  expect(screen.queryByTestId("cost-chart-bar-1")).toBeNull();
});

test("the toggle reports its pressed state to assistive tech", () => {
  render(<CostPerStepChart steps={steps([1])} currency="USD" />);
  const perStep = screen.getByTestId("cost-chart-mode-per-step");
  const cumulative = screen.getByTestId("cost-chart-mode-cumulative");

  expect(perStep.getAttribute("aria-pressed")).toBe("true");
  expect(cumulative.getAttribute("aria-pressed")).toBe("false");

  fireEvent.click(cumulative);
  expect(perStep.getAttribute("aria-pressed")).toBe("false");
  expect(cumulative.getAttribute("aria-pressed")).toBe("true");
});

test("labels the most expensive step in per-step mode, and the total in cumulative", () => {
  // One direct label per mode — never a number on every point.
  render(<CostPerStepChart steps={steps([1, 9, 3])} currency="USD" />);
  expect(screen.getByTestId("cost-chart-peak").textContent).toContain("Step 2");

  fireEvent.click(screen.getByTestId("cost-chart-mode-cumulative"));
  // 1 + 9 + 3 = 13
  expect(screen.getByTestId("cost-chart-last").textContent).toContain("13");
});

test("a thread with no priced step says so instead of drawing empty axes", () => {
  render(<CostPerStepChart steps={steps([null, null])} currency="USD" />);
  expect(screen.queryByTestId("cost-per-step-chart")).toBeNull();
  expect(screen.getByText("No priced steps yet.")).toBeTruthy();
});

test("an unpriced step leaves a gap rather than a zero-height column", () => {
  render(<CostPerStepChart steps={steps([2, null, 1])} currency="USD" />);
  expect(screen.getByTestId("cost-chart-bar-1")).toBeTruthy();
  // Step 2 could not be priced: no mark at all, rather than a bar on the floor
  // that would read as "this turn was free".
  expect(screen.queryByTestId("cost-chart-bar-2")).toBeNull();
  expect(screen.getByTestId("cost-chart-bar-3")).toBeTruthy();
});
