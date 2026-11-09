import { type ReactNode } from "react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { Translations } from "@/core/i18n/locales/types";
import {
  formatTokenShare,
  formatUsageDate,
  modelUsageRows,
  splitTokens,
  type TokenSplit,
} from "@/core/usage/format";
import type { UsageSummary } from "@/core/usage/types";
import { cn } from "@/lib/utils";

const cell = "px-4 py-3 text-right whitespace-nowrap tabular-nums";

// Bars stack bottom-up in this order; the legend reads top-down in reverse.
const SEGMENTS = [
  { key: "unattributed", className: "bg-muted-foreground/40" },
  { key: "output", className: "bg-chart-2" },
  { key: "uncached", className: "bg-chart-1" },
  { key: "cached", className: "bg-chart-1/50" },
] as const;

function sum(values: number[]) {
  return values.reduce((total, value) => total + value, 0);
}

export function UsageOverview({
  usage,
  locale,
  text,
}: {
  usage: UsageSummary;
  locale: string;
  text: Translations["usage"];
}) {
  const count = (value: number) => value.toLocaleString(locale);
  const models = modelUsageRows(usage.by_model).map((model) => ({
    ...model,
    split: splitTokens({
      total: model.tokens,
      input: model.input_tokens,
      output: model.output_tokens,
      cached: model.cache_read_tokens,
    }),
  }));
  const days = usage.days.map((day) => ({
    ...day,
    split: splitTokens({
      total: day.total_tokens,
      input: day.input_tokens,
      output: day.output_tokens,
      cached: day.cache_read_tokens,
    }),
  }));
  // Gateways before roadmap 39 send only the per-day split; sum it instead.
  const headline = splitTokens({
    total: usage.total_tokens,
    input: usage.total_input_tokens ?? sum(days.map((day) => day.input_tokens)),
    output:
      usage.total_output_tokens ?? sum(days.map((day) => day.output_tokens)),
    cached:
      usage.total_cache_read_tokens ??
      sum(days.map((day) => day.cache_read_tokens ?? 0)),
  });
  const peak = Math.max(1, ...days.map((day) => day.split.total));
  const hasRuns = usage.total_runs > 0;
  const anyUnattributed = (splits: TokenSplit[]) =>
    splits.some((split) => split.unattributed > 0);
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <Summary
          label={text.tokens}
          value={count(headline.total)}
          testId="usage-total-tokens"
        >
          <TokenSplitList split={headline} locale={locale} text={text} />
        </Summary>
        <Summary
          label={text.runs}
          value={count(usage.total_runs)}
          testId="usage-total-runs"
        />
      </div>

      <Card>
        <CardHeader>
          <h2 className="font-semibold">{text.daily}</h2>
          <p className="text-muted-foreground text-sm">{text.timezoneNote}</p>
          {hasRuns && (
            <ul
              aria-label={text.tokenSplit}
              className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs"
              data-testid="usage-chart-legend"
            >
              <LegendItem className="bg-chart-1" label={text.inputTokens} />
              <LegendItem className="bg-chart-1/50" label={text.cachedTokens} />
              <LegendItem className="bg-chart-2" label={text.outputTokens} />
              {anyUnattributed(days.map((day) => day.split)) && (
                <LegendItem
                  className="bg-muted-foreground/40"
                  label={text.unattributedTokens}
                />
              )}
            </ul>
          )}
        </CardHeader>
        <CardContent className="space-y-5">
          {!hasRuns ? (
            <p className="text-muted-foreground py-8 text-center text-sm">
              {text.noUsage}
            </p>
          ) : (
            <div
              aria-hidden="true"
              className="flex h-40 items-end gap-1 border-b px-1"
            >
              {days.map(({ date, split }) => {
                const parts = {
                  unattributed: split.unattributed,
                  output: split.output,
                  uncached: split.input - split.cached,
                  cached: split.cached,
                };
                return (
                  <div
                    key={date}
                    className="flex h-full min-w-0 flex-1 items-end"
                    title={`${formatUsageDate(date, locale)}: ${count(split.total)} · ${text.inputTokens} ${count(split.input)} · ${text.outputTokens} ${count(split.output)}`}
                  >
                    <div
                      className="flex w-full flex-col overflow-hidden rounded-t-sm opacity-80 transition-opacity hover:opacity-100"
                      data-testid="usage-day-bar"
                      style={{
                        height: `${Math.max(split.total > 0 ? 2 : 0, (split.total / peak) * 100)}%`,
                      }}
                    >
                      {SEGMENTS.map(({ key, className }) => (
                        <div
                          key={key}
                          className={className}
                          data-segment={key}
                          style={{ flexGrow: parts[key], flexBasis: 0 }}
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          {hasRuns && days.length > 0 && (
            <div
              className="text-muted-foreground flex justify-between text-xs"
              aria-hidden="true"
            >
              <span>{formatUsageDate(days[0]!.date, locale)}</span>
              <span>
                {formatUsageDate(days[days.length - 1]!.date, locale)}
              </span>
            </div>
          )}
          {hasRuns && (
            <details>
              <summary className="cursor-pointer text-sm font-medium">
                {text.dailyDetails}
              </summary>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-sm" aria-label={text.daily}>
                  <thead>
                    <tr className="text-muted-foreground border-b">
                      <th scope="col" className="px-4 py-3 text-left">
                        {text.date}
                      </th>
                      <th scope="col" className={cell}>
                        {text.inputTokens}
                      </th>
                      <th scope="col" className={cell}>
                        {text.outputTokens}
                      </th>
                      <th scope="col" className={cell}>
                        {text.runs}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {days.map((day) => (
                      <tr key={day.date} className="border-b last:border-0">
                        <th
                          scope="row"
                          className="px-4 py-3 text-left font-normal whitespace-nowrap"
                        >
                          {formatUsageDate(day.date, locale)}
                        </th>
                        <td className={cell}>{count(day.input_tokens)}</td>
                        <td className={cell}>{count(day.output_tokens)}</td>
                        <td className={cell}>{count(day.runs)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="font-semibold">{text.models}</h2>
        </CardHeader>
        <CardContent>
          {models.length === 0 ? (
            <p className="text-muted-foreground py-4 text-sm">
              {text.noModels}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" aria-label={text.models}>
                <thead>
                  <tr className="text-muted-foreground border-b">
                    <th scope="col" className="px-4 py-3 text-left">
                      {text.model}
                    </th>
                    <th scope="col" className={cell}>
                      {text.tokens}
                    </th>
                    <th scope="col" className={cell}>
                      {text.inputTokens}
                    </th>
                    <th scope="col" className={cell}>
                      {text.cachedTokens}
                    </th>
                    <th scope="col" className={cell}>
                      {text.outputTokens}
                    </th>
                    {anyUnattributed(models.map((model) => model.split)) && (
                      <th
                        scope="col"
                        className={cell}
                        title={text.unattributedHint}
                      >
                        {text.unattributedTokens}
                      </th>
                    )}
                    <th scope="col" className={cell}>
                      {text.runs}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((model) => (
                    <tr key={model.name} className="border-b last:border-0">
                      <th
                        scope="row"
                        className="max-w-60 px-4 py-3 text-left font-medium break-words"
                      >
                        {model.name}
                      </th>
                      <td className={cell}>{count(model.split.total)}</td>
                      <td className={cell}>{count(model.split.input)}</td>
                      <td className={cell}>{count(model.split.cached)}</td>
                      <td className={cell}>{count(model.split.output)}</td>
                      {anyUnattributed(models.map((row) => row.split)) && (
                        <td className={cell}>
                          {count(model.split.unattributed)}
                        </td>
                      )}
                      <td className={cell}>{count(model.runs)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/** Input (with its cached part), output and any unattributed rest, each with its share. */
function TokenSplitList({
  split,
  locale,
  text,
}: {
  split: TokenSplit;
  locale: string;
  text: Translations["usage"];
}) {
  const count = (value: number) => value.toLocaleString(locale);
  const share = (value: number) => {
    const formatted = formatTokenShare(value, split.total, locale);
    return formatted ? ` · ${formatted}` : "";
  };
  const rows = [
    {
      key: "input",
      label: text.inputTokens,
      value: split.input,
      note: split.cached > 0 ? text.cachedPart(count(split.cached)) : null,
      title: undefined,
    },
    {
      key: "output",
      label: text.outputTokens,
      value: split.output,
      note: null,
      title: undefined,
    },
    ...(split.unattributed > 0
      ? [
          {
            key: "unattributed",
            label: text.unattributedTokens,
            value: split.unattributed,
            note: null,
            title: text.unattributedHint,
          },
        ]
      : []),
  ];
  return (
    <dl
      aria-label={text.tokenSplit}
      className="text-muted-foreground mt-2 space-y-1 text-sm font-normal"
      data-testid="usage-token-split"
    >
      {rows.map((row) => (
        <div
          key={row.key}
          className="flex flex-wrap justify-between gap-x-3"
          data-split={row.key}
          title={row.title}
        >
          <dt>{row.label}</dt>
          <dd className="text-foreground tabular-nums">
            {count(row.value)}
            {share(row.value)}
            {row.note && (
              <span className="text-muted-foreground block text-right text-xs">
                {row.note}
              </span>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function LegendItem({
  className,
  label,
}: {
  className: string;
  label: string;
}) {
  return (
    <li className="flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className={cn("inline-block size-2.5 rounded-sm", className)}
      />
      {label}
    </li>
  );
}

function Summary({
  label,
  value,
  testId,
  children,
}: {
  label: string;
  value: string;
  testId: string;
  children?: ReactNode;
}) {
  return (
    <Card className="gap-2">
      <CardHeader className="text-muted-foreground text-sm">{label}</CardHeader>
      <CardContent>
        <div
          className="text-2xl font-semibold tabular-nums"
          data-testid={testId}
        >
          {value}
        </div>
        {children}
      </CardContent>
    </Card>
  );
}
