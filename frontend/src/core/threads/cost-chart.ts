import type { ThreadCostStep } from "./token-usage";

/**
 * Geometry for the per-step cost chart in the header's cost dropdown.
 *
 * Kept out of the component so the maths is unit-testable: an off-by-one in a
 * scale is invisible in a 60px-tall sparkline but makes the chart lie, and a
 * chart that lies about money is worse than no chart.
 */

/** Which question the chart is answering. */
export type CostChartMode = "per-step" | "cumulative";

export interface CostChartPoint {
  /** 1-based step number — the nth user message. */
  index: number;
  /** The value plotted in the current mode; null when this step is unpriced. */
  value: number | null;
  /** Centre of this step's slot on the x axis, in SVG user units. */
  x: number;
  /** y for `value`; null when there is nothing to plot. */
  y: number | null;
  /** Column geometry — per-step mode only. */
  barX: number;
  barWidth: number;
  barY: number;
  barHeight: number;
  tokens: number;
  createdAt: string | null;
  runId: string;
}

export interface CostChartGeometry {
  width: number;
  height: number;
  points: CostChartPoint[];
  /** Largest plotted value; the y axis runs 0 → this. */
  maxValue: number;
  /** `d` for the cumulative line, or "" when there is nothing to draw. */
  linePath: string;
  /** `d` for the area wash under that line. */
  areaPath: string;
  /** The step with the highest value — the one worth a direct label. */
  peak: CostChartPoint | null;
  /** The final point, which is the one the cumulative story ends on. */
  last: CostChartPoint | null;
}

export const COST_CHART_DEFAULTS = {
  width: 268,
  height: 64,
  /** Room for the baseline and a direct label above the tallest mark. */
  paddingTop: 12,
  paddingBottom: 10,
  paddingX: 2,
  /** Mark spec: bars are capped rather than filling their slot. */
  maxBarWidth: 24,
  /** The surface gap that separates touching columns. */
  barGap: 2,
} as const;

/**
 * Value a step contributes in the given mode.
 *
 * Per-step keeps `null` for an unpriced turn so the chart can leave a gap
 * instead of drawing a real column at zero. The cumulative series has no such
 * hole — a running total is defined at every step — so it always has a number.
 */
export function stepValue(
  step: ThreadCostStep,
  mode: CostChartMode,
): number | null {
  if (mode === "cumulative") {
    return step.cumulativePromoCost;
  }
  return step.promoCost ?? step.cost;
}

/**
 * Build the SVG geometry for a set of steps.
 *
 * The y scale always starts at zero. A cost chart with a non-zero baseline
 * exaggerates differences between turns, which is the classic way a spend chart
 * misleads — so the floor is fixed even when every step is nearly identical.
 */
export function buildCostChartGeometry(
  steps: ThreadCostStep[],
  mode: CostChartMode,
  options: Partial<typeof COST_CHART_DEFAULTS> = {},
): CostChartGeometry {
  const cfg = { ...COST_CHART_DEFAULTS, ...options };
  const plotTop = cfg.paddingTop;
  const plotBottom = cfg.height - cfg.paddingBottom;
  const plotHeight = Math.max(plotBottom - plotTop, 1);
  const plotLeft = cfg.paddingX;
  const plotWidth = Math.max(cfg.width - cfg.paddingX * 2, 1);

  const values = steps.map((step) => stepValue(step, mode));
  const maxValue = values.reduce<number>(
    (max, value) => (value != null && value > max ? value : max),
    0,
  );
  // A thread whose every step is unpriced (or free) has no scale to speak of;
  // use 1 so the maths stays finite and everything lands on the baseline.
  const scaleMax = maxValue > 0 ? maxValue : 1;
  const slotWidth = plotWidth / Math.max(steps.length, 1);
  const barWidth = Math.max(
    Math.min(slotWidth - cfg.barGap, cfg.maxBarWidth),
    1,
  );

  const points: CostChartPoint[] = steps.map((step, i) => {
    const value = values[i] ?? null;
    const x =
      steps.length === 1
        ? plotLeft + plotWidth / 2
        : plotLeft + slotWidth * i + slotWidth / 2;
    const y =
      value == null ? null : plotBottom - (value / scaleMax) * plotHeight;
    const barHeight =
      value == null ? 0 : Math.max(plotBottom - (y ?? plotBottom), 0);
    return {
      index: step.index,
      value,
      x,
      y,
      barX: x - barWidth / 2,
      barWidth,
      barY: y ?? plotBottom,
      barHeight,
      tokens: step.tokens,
      createdAt: step.createdAt,
      runId: step.runId,
    };
  });

  // The cumulative line is continuous by construction, so no gap handling is
  // needed here; per-step mode draws columns and never uses these paths.
  const drawable =
    mode === "cumulative" ? points.filter((p) => p.y != null) : [];
  const linePath = drawable
    .map((p, i) => `${i === 0 ? "M" : "L"}${round(p.x)},${round(p.y!)}`)
    .join(" ");
  const areaPath =
    drawable.length > 0
      ? `${linePath} L${round(drawable[drawable.length - 1]!.x)},${round(plotBottom)} L${round(drawable[0]!.x)},${round(plotBottom)} Z`
      : "";

  const priced = points.filter((p) => p.value != null);
  const peak =
    priced.length > 0
      ? priced.reduce((best, p) =>
          (p.value ?? 0) > (best.value ?? 0) ? p : best,
        )
      : null;

  return {
    width: cfg.width,
    height: cfg.height,
    points,
    maxValue,
    linePath,
    areaPath,
    peak,
    last: points.length > 0 ? (points[points.length - 1] ?? null) : null,
  };
}

/** Trim float noise out of path data so the DOM stays small and diffs stay readable. */
function round(value: number): number {
  return Math.round(value * 100) / 100;
}
