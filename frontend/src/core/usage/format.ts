import type { ModelUsage } from "./types";

export function modelUsageRows(models: Record<string, ModelUsage>) {
  return Object.entries(models)
    .map(([name, usage]) => ({ name, ...usage }))
    .sort((a, b) => b.tokens - a.tokens || a.name.localeCompare(b.name));
}

/** Day buckets are calendar dates, not UTC instants to shift a second time. */
export function formatUsageDate(date: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${date}T12:00:00Z`));
}

export function formatRunDuration(
  seconds: number | null,
  locale: string,
  unknown: string,
): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0)
    return unknown;
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: seconds >= 60 ? "minute" : "second",
    unitDisplay: "short",
    maximumFractionDigits: 1,
  }).format(seconds >= 60 ? seconds / 60 : seconds);
}

/** One total split into the parts the usage page shows beneath it. */
export interface TokenSplit {
  total: number;
  input: number;
  /** The cache-hit part of `input`, never an amount on top of it. */
  cached: number;
  output: number;
  /** Reported as total without an input/output split; never folded into either. */
  unattributed: number;
}

function tokenCount(value: number | null | undefined): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : 0;
}

/**
 * Split a reported total so the parts always add up to the total shown:
 * input + output + unattributed === total, and cached <= input. A provider that
 * reports parts larger than its total raises the total to their sum rather
 * than showing a negative remainder.
 */
export function splitTokens(usage: {
  total: number | null | undefined;
  input?: number | null;
  output?: number | null;
  cached?: number | null;
}): TokenSplit {
  const input = tokenCount(usage.input);
  const output = tokenCount(usage.output);
  const total = Math.max(tokenCount(usage.total), input + output);
  return {
    total,
    input,
    cached: Math.min(tokenCount(usage.cached), input),
    output,
    unattributed: total - input - output,
  };
}

/** A part's share of its total as a whole percentage, or null for an empty total. */
export function formatTokenShare(
  part: number,
  total: number,
  locale: string,
): string | null {
  if (total <= 0) return null;
  return new Intl.NumberFormat(locale, {
    style: "percent",
    maximumFractionDigits: 0,
  }).format(part / total);
}
