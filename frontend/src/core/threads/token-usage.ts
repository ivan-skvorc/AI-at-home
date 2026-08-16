import type { TokenUsage } from "@/core/messages/usage";

import type { ThreadTokenUsageResponse } from "./types";

export function threadTokenUsageQueryKey(threadId?: string | null) {
  return ["thread-token-usage", threadId] as const;
}

export function retainThreadTokenUsagePlaceholder(
  previous: ThreadTokenUsageResponse | null | undefined,
  threadId?: string | null,
): ThreadTokenUsageResponse | undefined {
  return previous && previous.thread_id === threadId ? previous : undefined;
}

export function threadTokenUsageToTokenUsage(
  usage: ThreadTokenUsageResponse | null | undefined,
): TokenUsage | null {
  if (!usage) {
    return null;
  }
  return {
    inputTokens: usage.total_input_tokens ?? 0,
    outputTokens: usage.total_output_tokens ?? 0,
    totalTokens: usage.total_tokens ?? 0,
  };
}

export interface AuxCostEntry {
  tokens: number;
  cost: number | null;
  /** Spend at live promo rates; null when this sink is undiscounted. */
  promoCost: number | null;
}

export interface SpendBudgetLimit {
  /** "daily" | "weekly" | "monthly". */
  period: string;
  limit: number;
  spent: number;
  remaining: number;
  /** spent / limit, so the UI can colour by proximity. */
  fraction: number;
}

export interface SpendBudgetSummary {
  currency: string | null;
  limits: SpendBudgetLimit[];
  /**
   * The window with the least headroom. A budget can have three windows; the
   * one about to bite is the only one worth a line in the header.
   */
  tightest: SpendBudgetLimit | null;
  /** A cap is spent — new runs are refused (HTTP 402) until the window rolls. */
  exceeded: boolean;
  /** Fraction at which the agent starts getting in-context warnings. */
  warnThreshold: number;
}

/**
 * Remaining spend budget, or null when the cap is off or unenforceable.
 *
 * A spend cap is denominated in the pricing currency, so it can only be active
 * when pricing is configured — which is why this rides inside the cost summary
 * rather than needing its own prop through every chat page.
 */
export function threadTokenUsageToSpendBudget(
  usage: ThreadTokenUsageResponse | null | undefined,
): SpendBudgetSummary | null {
  const budget = usage?.spend_budget;
  if (!budget) {
    return null;
  }
  const limits: SpendBudgetLimit[] = (budget.limits ?? [])
    .filter(
      (entry) => entry && typeof entry.limit === "number" && entry.limit > 0,
    )
    .map((entry) => ({
      period: entry.period,
      limit: entry.limit,
      spent: entry.spent ?? 0,
      remaining:
        entry.remaining ?? Math.max(entry.limit - (entry.spent ?? 0), 0),
      fraction: entry.fraction ?? (entry.spent ?? 0) / entry.limit,
    }));
  if (limits.length === 0) {
    return null;
  }
  const tightest = limits.reduce((least, entry) =>
    entry.remaining < least.remaining ? entry : least,
  );
  return {
    currency: budget.currency ?? null,
    limits,
    tightest,
    exceeded: budget.exceeded === true,
    warnThreshold: budget.warn_threshold ?? 0.8,
  };
}

export interface ThreadCostSummary {
  /** Estimated spend across the thread's runs, or null when unpriced. */
  totalCost: number | null;
  /**
   * The same total billed at the live promotional/introductory rates — what the
   * thread costs *now*. Null when no model in it is currently discounted, which
   * is the signal to show one price instead of the same number twice.
   */
  promoTotalCost: number | null;
  /** ISO currency code from config pricing, or null when unpriced. */
  currency: string | null;
  /** Separate memory / suggestions counters, present only when non-zero. */
  aux: Record<string, AuxCostEntry>;
  /**
   * Models that ran in this thread with no `pricing:` block configured. When
   * `totalCost` is null this is the reason it is null; when `totalCost` is set
   * the figure covers only the priced models and understates the real spend.
   */
  unpricedModels: string[];
  /** Remaining currency spend cap, when one is configured and enforceable. */
  spendBudget: SpendBudgetSummary | null;
}

/**
 * Extract the real-cost overview from a thread token-usage response.
 *
 * Returns null when the backend reported no currency — i.e. no
 * `models[*].pricing` is configured — so the sidebar can hide the cost line
 * entirely rather than showing a misleading "$0".
 */
export function threadTokenUsageToCostSummary(
  usage: ThreadTokenUsageResponse | null | undefined,
): ThreadCostSummary | null {
  if (!usage?.currency) {
    return null;
  }
  const aux: Record<string, AuxCostEntry> = {};
  for (const [category, entry] of Object.entries(usage.aux ?? {})) {
    if (!entry || entry.tokens <= 0) {
      continue;
    }
    const cost = entry.cost ?? null;
    const promoCost = entry.promo_cost ?? null;
    aux[category] = {
      tokens: entry.tokens,
      cost,
      // Same rule as the headline: an equal pair is not a discount.
      promoCost: promoCost != null && promoCost !== cost ? promoCost : null,
    };
  }
  const totalCost = usage.total_cost ?? null;
  const promoTotalCost = usage.promo_total_cost ?? null;
  return {
    totalCost,
    // A promo total that matches the standard one carries no information, so
    // treat it as "no discount" and let the UI render a single figure.
    promoTotalCost:
      promoTotalCost != null && promoTotalCost !== totalCost
        ? promoTotalCost
        : null,
    currency: usage.currency,
    aux,
    unpricedModels: (usage.unpriced_models ?? []).filter(
      (name): name is string => typeof name === "string" && name.length > 0,
    ),
    spendBudget: threadTokenUsageToSpendBudget(usage),
  };
}

/**
 * Format a spend amount in its currency. Small amounts keep more precision so a
 * fraction-of-a-cent conversation cost is not rounded away to "$0.00".
 */
export function formatCost(amount: number, currency: string): string {
  const abs = Math.abs(amount);
  // 0 -> 2 digits; sub-cent -> up to 4; sub-milli-cent -> up to 6.
  const maximumFractionDigits =
    abs === 0 ? 2 : abs < 0.01 ? (abs < 0.0001 ? 6 : 4) : 2;
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits,
      minimumFractionDigits: 2,
    }).format(amount);
  } catch {
    // Unknown/invalid currency code: fall back to a plain "<CODE> <amount>".
    return `${currency} ${amount.toFixed(maximumFractionDigits)}`;
  }
}

export interface ContextUsage {
  tokenCount: number;
  maxContextTokens: number | null;
  percentage: number | null;
}

export function selectContextUsage(
  usage: ThreadTokenUsageResponse | null | undefined,
): ContextUsage | null {
  if (!usage?.context_usage) {
    return null;
  }
  const { token_count, max_context_tokens, percentage } = usage.context_usage;
  return {
    tokenCount: token_count ?? 0,
    maxContextTokens: max_context_tokens ?? null,
    percentage: percentage ?? null,
  };
}
