"use client";

import { useMemo, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import {
  buildCostChartGeometry,
  type CostChartMode,
} from "@/core/threads/cost-chart";
import { formatCost, type ThreadCostStep } from "@/core/threads/token-usage";
import { cn } from "@/lib/utils";

/**
 * What each turn of the conversation cost, as a small chart in the cost dropdown.
 *
 * The header already answers "what has this cost so far". This answers the
 * question a mixed-model thread actually raises — *which turn* got expensive —
 * which the running total structurally cannot show.
 *
 * Design decisions worth stating:
 *
 * - **The form changes with the mode, because the job does.** "Each step" is a
 *   magnitude comparison across discrete turns → columns. "Running total" is a
 *   trend → a line with an area wash. Drawing a running total as columns would
 *   imply each bar is an independent quantity; drawing discrete turns as a line
 *   would imply the cost moved continuously between them.
 * - **One series, so no legend.** The heading names what is plotted. The
 *   promo/standard pair stays in the totals above, where it has room to be
 *   labelled; the chart plots the single number you actually pay.
 * - **The y axis always starts at zero.** A non-zero baseline exaggerates the
 *   difference between turns, which is exactly how a spend chart misleads.
 */

/**
 * Emerald-600. Chosen rather than the emerald-500 used for the cost text
 * because it is the step that passes the lightness band, chroma floor, and 3:1
 * contrast against *both* the light and dark chart surfaces — 500 fails the
 * band on dark. One validated step serves both themes, so the mark needs no
 * theme-conditional colour.
 */
const SERIES_COLOR = "#059669";

interface CostPerStepChartProps {
  steps: ThreadCostStep[];
  currency: string;
  className?: string;
}

export function CostPerStepChart({
  steps,
  currency,
  className,
}: CostPerStepChartProps) {
  const { t } = useI18n();
  const [mode, setMode] = useState<CostChartMode>("per-step");

  const geometry = useMemo(
    () => buildCostChartGeometry(steps, mode),
    [steps, mode],
  );

  const hasPricedStep = geometry.points.some((point) => point.value != null);

  return (
    <div className={cn("mt-2 border-t pt-2", className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-muted-foreground text-[11px] font-medium">
          {t.tokenUsage.chartTitle}
        </span>
        {/* The toggle sits above the plot, one row, as filters do. */}
        <div
          role="group"
          aria-label={t.tokenUsage.chartModeLabel}
          className="bg-muted/60 flex items-center gap-0.5 rounded-md p-0.5"
        >
          {(
            [
              ["per-step", t.tokenUsage.chartPerStep],
              ["cumulative", t.tokenUsage.chartCumulative],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              data-testid={`cost-chart-mode-${value}`}
              aria-pressed={mode === value}
              // The dropdown closes on item selection; this is a plain button
              // inside the content, so stop the event reaching the menu.
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                setMode(value);
              }}
              className={cn(
                "rounded px-1.5 py-0.5 text-[10px] leading-none transition-colors",
                mode === value
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {hasPricedStep ? (
        <>
          <svg
            data-testid="cost-per-step-chart"
            data-mode={mode}
            role="img"
            aria-label={t.tokenUsage.chartTitle}
            viewBox={`0 0 ${geometry.width} ${geometry.height}`}
            width="100%"
            height={geometry.height}
            className="mt-1.5 overflow-visible"
            preserveAspectRatio="none"
          >
            {/* Recessive hairline baseline; the only rule the chart needs. */}
            <line
              x1={0}
              x2={geometry.width}
              y1={geometry.height - 10}
              y2={geometry.height - 10}
              className="stroke-border"
              strokeWidth={1}
            />

            {mode === "cumulative" ? (
              <>
                {geometry.areaPath && (
                  <path
                    d={geometry.areaPath}
                    fill={SERIES_COLOR}
                    fillOpacity={0.1}
                  />
                )}
                {geometry.linePath && (
                  <path
                    d={geometry.linePath}
                    fill="none"
                    stroke={SERIES_COLOR}
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    vectorEffect="non-scaling-stroke"
                  />
                )}
                {/* End marker: r=4 (an 8px dot) with a 2px surface ring so it
                    stays legible where it sits on the line. */}
                {geometry.last?.y != null && (
                  <circle
                    cx={geometry.last.x}
                    cy={geometry.last.y}
                    r={4}
                    fill={SERIES_COLOR}
                    className="stroke-background"
                    strokeWidth={2}
                  />
                )}
              </>
            ) : (
              geometry.points.map((point) =>
                point.value == null ? null : (
                  // 4px rounded data-end, square at the baseline: drawn as a
                  // fully rounded rect clipped by the baseline overlay below is
                  // fussy at this size, so a small uniform radius reads the same
                  // and keeps the column square where it meets the axis.
                  <rect
                    key={point.index}
                    data-testid={`cost-chart-bar-${point.index}`}
                    x={point.barX}
                    y={point.barY}
                    width={point.barWidth}
                    height={Math.max(point.barHeight, 1)}
                    rx={Math.min(2, point.barWidth / 2)}
                    fill={SERIES_COLOR}
                  >
                    <title>
                      {t.tokenUsage.chartStepLabel(
                        point.index,
                        formatCost(point.value, currency),
                      )}
                    </title>
                  </rect>
                ),
              )
            )}
          </svg>

          <div className="text-muted-foreground mt-1 flex items-baseline justify-between gap-2 text-[10px] leading-none">
            <span>{t.tokenUsage.chartAxisHint}</span>
            {/* One direct label, on the value the mode is about: the most
                expensive turn, or where the running total ended. Never a number
                on every point. */}
            {mode === "per-step"
              ? geometry.peak?.value != null && (
                  <span data-testid="cost-chart-peak" className="font-mono">
                    {t.tokenUsage.chartStepLabel(
                      geometry.peak.index,
                      formatCost(geometry.peak.value, currency),
                    )}
                  </span>
                )
              : geometry.last?.value != null && (
                  <span data-testid="cost-chart-last" className="font-mono">
                    {formatCost(geometry.last.value, currency)}
                  </span>
                )}
          </div>
        </>
      ) : (
        <div className="text-muted-foreground mt-1 text-[11px] leading-snug">
          {t.tokenUsage.chartEmpty}
        </div>
      )}
    </div>
  );
}
