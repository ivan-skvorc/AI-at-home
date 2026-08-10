import { expect, test } from "@rstest/core";
import { QueryClient, QueryObserver } from "@tanstack/react-query";

import {
  formatCost,
  retainThreadTokenUsagePlaceholder,
  selectContextUsage,
  threadTokenUsageQueryKey,
  threadTokenUsageToCostSummary,
  threadTokenUsageToSpendBudget,
  threadTokenUsageToTokenUsage,
} from "@/core/threads/token-usage";
import type { ThreadTokenUsageResponse } from "@/core/threads/types";

test("maps backend thread token usage to UI token usage", () => {
  const response: ThreadTokenUsageResponse = {
    thread_id: "thread-1",
    total_input_tokens: 90,
    total_output_tokens: 60,
    total_tokens: 150,
    total_runs: 2,
    by_model: { unknown: { tokens: 150, runs: 2 } },
    by_caller: {
      lead_agent: 120,
      subagent: 25,
      middleware: 5,
    },
  };

  expect(threadTokenUsageToTokenUsage(response)).toEqual({
    inputTokens: 90,
    outputTokens: 60,
    totalTokens: 150,
  });
});

test("returns null when backend thread token usage is unavailable", () => {
  expect(threadTokenUsageToTokenUsage(null)).toBeNull();
  expect(threadTokenUsageToTokenUsage(undefined)).toBeNull();
});

function baseResponse(
  overrides: Partial<ThreadTokenUsageResponse> = {},
): ThreadTokenUsageResponse {
  return {
    thread_id: "t1",
    total_input_tokens: 100,
    total_output_tokens: 50,
    total_tokens: 150,
    total_runs: 1,
    by_model: {},
    by_caller: { lead_agent: 150, subagent: 0, middleware: 0 },
    ...overrides,
  };
}

test("cost summary is null when no currency (no pricing configured)", () => {
  expect(threadTokenUsageToCostSummary(baseResponse())).toBeNull();
  expect(
    threadTokenUsageToCostSummary(baseResponse({ currency: null })),
  ).toBeNull();
  expect(threadTokenUsageToCostSummary(null)).toBeNull();
});

test("cost summary surfaces models that ran without a configured price", () => {
  // The reason a cost renders as "—": tokens were spent on models with no
  // `pricing:` block. Carrying the names lets the UI say which one to fix
  // instead of showing an unexplained dash.
  const noneP = threadTokenUsageToCostSummary(
    baseResponse({
      total_cost: null,
      currency: "USD",
      unpriced_models: ["gpt-5.6-sol", "grok-4.5"],
    }),
  );
  expect(noneP!.totalCost).toBeNull();
  expect(noneP!.unpricedModels).toEqual(["gpt-5.6-sol", "grok-4.5"]);

  // A partial total is real but understates the spend — same signal, cost set.
  const partial = threadTokenUsageToCostSummary(
    baseResponse({
      total_cost: 1.25,
      currency: "USD",
      unpriced_models: ["grok-4.5"],
    }),
  );
  expect(partial!.totalCost).toBe(1.25);
  expect(partial!.unpricedModels).toEqual(["grok-4.5"]);

  // Absent / malformed entries degrade to an empty list rather than rendering
  // a note about "undefined".
  expect(
    threadTokenUsageToCostSummary(baseResponse({ currency: "USD" }))!
      .unpricedModels,
  ).toEqual([]);
  expect(
    threadTokenUsageToCostSummary(
      baseResponse({
        currency: "USD",
        unpriced_models: ["ok", "", null, 7] as unknown as string[],
      }),
    )!.unpricedModels,
  ).toEqual(["ok"]);
});

test("cost summary carries total, currency and non-zero aux counters", () => {
  const summary = threadTokenUsageToCostSummary(
    baseResponse({
      total_cost: 0.42,
      currency: "USD",
      aux: {
        memory: {
          tokens: 600,
          input_tokens: 500,
          output_tokens: 100,
          calls: 2,
          cost: 0.01,
        },
        suggestions: {
          tokens: 120,
          input_tokens: 100,
          output_tokens: 20,
          calls: 3,
          cost: null,
        },
        // Zero-token category is dropped so an enabled-but-unused feature adds no row.
        empty: {
          tokens: 0,
          input_tokens: 0,
          output_tokens: 0,
          calls: 0,
          cost: null,
        },
      },
    }),
  );
  expect(summary).not.toBeNull();
  expect(summary!.totalCost).toBe(0.42);
  expect(summary!.currency).toBe("USD");
  expect(summary!.aux).toEqual({
    memory: { tokens: 600, cost: 0.01, promoCost: null },
    suggestions: { tokens: 120, cost: null, promoCost: null },
  });
});

test("formatCost keeps precision for sub-cent amounts", () => {
  // A whole-dollar amount uses 2 decimals; a fraction-of-a-cent amount keeps
  // more so it does not round away to $0.00.
  expect(formatCost(12.5, "USD")).toBe("$12.50");
  expect(formatCost(0.0012, "USD")).toBe("$0.0012");
  expect(formatCost(0, "USD")).toBe("$0.00");
});

test("formatCost falls back to a plain code for a malformed currency", () => {
  // A malformed (non 3-letter) code makes Intl throw; formatCost must not crash.
  expect(formatCost(1.5, "BADCODE")).toBe("BADCODE 1.50");
});

test("retains placeholder usage only for the current thread", () => {
  const response: ThreadTokenUsageResponse = {
    thread_id: "thread-1",
    total_input_tokens: 90,
    total_output_tokens: 60,
    total_tokens: 150,
    total_runs: 2,
    by_model: { unknown: { tokens: 150, runs: 2 } },
    by_caller: {
      lead_agent: 120,
      subagent: 25,
      middleware: 5,
    },
  };

  expect(retainThreadTokenUsagePlaceholder(response, "thread-1")).toBe(
    response,
  );
  expect(
    retainThreadTokenUsagePlaceholder(response, "thread-2"),
  ).toBeUndefined();
  expect(retainThreadTokenUsagePlaceholder(null, undefined)).toBeUndefined();
});

test("query observer keeps same-thread data but drops it while a new thread is pending", async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const threadA: ThreadTokenUsageResponse = {
    thread_id: "thread-a",
    total_input_tokens: 90,
    total_output_tokens: 60,
    total_tokens: 150,
    total_runs: 2,
    by_model: { unknown: { tokens: 150, runs: 2 } },
    by_caller: { lead_agent: 120, subagent: 25, middleware: 5 },
  };
  const threadB: ThreadTokenUsageResponse = {
    ...threadA,
    thread_id: "thread-b",
    total_tokens: 200,
  };
  let queryResult = Promise.resolve(threadA);
  let resolveRefresh: (value: ThreadTokenUsageResponse) => void = () =>
    undefined;
  let resolveThreadB: (value: ThreadTokenUsageResponse) => void = () =>
    undefined;
  const observer = new QueryObserver<ThreadTokenUsageResponse | null>(
    queryClient,
    {
      queryKey: threadTokenUsageQueryKey("thread-a"),
      queryFn: () => queryResult,
      placeholderData: (previous) =>
        retainThreadTokenUsagePlaceholder(previous, "thread-a"),
    },
  );
  const unsubscribe = observer.subscribe(() => undefined);

  try {
    await observer.refetch();
    expect(observer.getCurrentResult().data).toBe(threadA);

    queryResult = new Promise((resolve) => {
      resolveRefresh = resolve;
    });
    const sameThreadRefetch = observer.refetch();
    expect(observer.getCurrentResult().data).toBe(threadA);
    resolveRefresh(threadA);
    await sameThreadRefetch;

    const pendingThreadB = new Promise<ThreadTokenUsageResponse>((resolve) => {
      resolveThreadB = resolve;
    });
    observer.setOptions({
      queryKey: threadTokenUsageQueryKey("thread-b"),
      queryFn: () => pendingThreadB,
      retry: false,
      placeholderData: (previous) =>
        retainThreadTokenUsagePlaceholder(previous, "thread-b"),
    });
    expect(observer.getCurrentResult().data).toBeUndefined();
    expect(observer.getCurrentResult().isPlaceholderData).toBe(false);

    resolveThreadB(threadB);
    await observer.refetch();
    expect(observer.getCurrentResult().data).toBe(threadB);
  } finally {
    resolveRefresh(threadA);
    resolveThreadB(threadB);
    unsubscribe();
    queryClient.clear();
  }
});

const _baseResponse = {
  thread_id: "thread-1",
  total_input_tokens: 0,
  total_output_tokens: 0,
  total_tokens: 0,
  total_runs: 0,
  by_model: {},
  by_caller: { lead_agent: 0, subagent: 0, middleware: 0 },
} satisfies ThreadTokenUsageResponse;

test("selectContextUsage projects the backend block to UI shape", () => {
  const response: ThreadTokenUsageResponse = {
    ..._baseResponse,
    context_usage: {
      token_count: 350,
      max_context_tokens: 1000,
      percentage: 35,
    },
  };

  expect(selectContextUsage(response)).toEqual({
    tokenCount: 350,
    maxContextTokens: 1000,
    percentage: 35,
  });
});

test("selectContextUsage preserves nullable capacity and percentage", () => {
  const response: ThreadTokenUsageResponse = {
    ..._baseResponse,
    context_usage: {
      token_count: 200,
      max_context_tokens: null,
      percentage: null,
    },
  };

  expect(selectContextUsage(response)).toEqual({
    tokenCount: 200,
    maxContextTokens: null,
    percentage: null,
  });
});

test("selectContextUsage returns null when context_usage is missing", () => {
  expect(selectContextUsage(_baseResponse)).toBeNull();
  expect(
    selectContextUsage({ ..._baseResponse, context_usage: null }),
  ).toBeNull();
  expect(selectContextUsage(null)).toBeNull();
  expect(selectContextUsage(undefined)).toBeNull();
});

const PROMO_BASE: ThreadTokenUsageResponse = {
  thread_id: "t",
  total_tokens: 0,
  total_input_tokens: 0,
  total_output_tokens: 0,
  total_runs: 0,
  by_model: {},
  by_caller: { lead_agent: 0, subagent: 0, middleware: 0 },
  currency: "USD",
};

test("cost summary carries the promo total alongside the standard one", () => {
  const summary = threadTokenUsageToCostSummary({
    ...PROMO_BASE,
    total_cost: 34.75,
    promo_total_cost: 31.15,
  });
  expect(summary?.totalCost).toBe(34.75);
  expect(summary?.promoTotalCost).toBe(31.15);
});

test("cost summary promo total is null when the backend reports none", () => {
  const summary = threadTokenUsageToCostSummary({
    ...PROMO_BASE,
    total_cost: 30,
  });
  expect(summary?.promoTotalCost).toBeNull();
});

test("cost summary drops a promo total identical to the standard total", () => {
  // Printing the same figure twice in green and red claims a discount that does
  // not exist, so an equal pair collapses back to a single price.
  const summary = threadTokenUsageToCostSummary({
    ...PROMO_BASE,
    total_cost: 30,
    promo_total_cost: 30,
  });
  expect(summary?.promoTotalCost).toBeNull();
});

test("aux rows carry their own promo cost, per sink", () => {
  // Memory and suggestions can each run on a different model from the
  // conversation, so a discount applies per sink rather than thread-wide.
  const summary = threadTokenUsageToCostSummary({
    ...PROMO_BASE,
    total_cost: 30,
    aux: {
      memory: {
        tokens: 600,
        input_tokens: 500,
        output_tokens: 100,
        calls: 2,
        cost: 1.15,
        promo_cost: 0.28,
      },
      suggestions: {
        tokens: 120,
        input_tokens: 100,
        output_tokens: 20,
        calls: 1,
        cost: 5,
        promo_cost: null,
      },
    },
  });
  expect(summary!.aux.memory!).toEqual({
    tokens: 600,
    cost: 1.15,
    promoCost: 0.28,
  });
  expect(summary!.aux.suggestions!).toEqual({
    tokens: 120,
    cost: 5,
    promoCost: null,
  });
});

test("an aux promo cost equal to its standard cost collapses to null", () => {
  const summary = threadTokenUsageToCostSummary({
    ...PROMO_BASE,
    total_cost: 30,
    aux: {
      memory: {
        tokens: 600,
        input_tokens: 500,
        output_tokens: 100,
        calls: 2,
        cost: 1.15,
        promo_cost: 1.15,
      },
    },
  });
  expect(summary!.aux.memory!.promoCost).toBeNull();
});

// ---------------------------------------------------------------------------
// Spend budget (roadmap item 2) — the header's "budget left" line
// ---------------------------------------------------------------------------

const BUDGET_BASE: ThreadTokenUsageResponse = {
  thread_id: "thread-budget",
  total_input_tokens: 0,
  total_output_tokens: 0,
  total_tokens: 0,
  total_runs: 0,
  by_model: {},
  by_caller: { lead_agent: 0, subagent: 0, middleware: 0 },
  currency: "USD",
};

test("no spend budget block yields no budget summary", () => {
  expect(threadTokenUsageToSpendBudget(BUDGET_BASE)).toBeNull();
  expect(threadTokenUsageToSpendBudget(undefined)).toBeNull();
});

test("a budget with no usable limit yields no budget summary", () => {
  expect(
    threadTokenUsageToSpendBudget({
      ...BUDGET_BASE,
      spend_budget: { currency: "USD", limits: [] },
    }),
  ).toBeNull();
});

test("the tightest window is the one surfaced", () => {
  const budget = threadTokenUsageToSpendBudget({
    ...BUDGET_BASE,
    spend_budget: {
      currency: "USD",
      limits: [
        { period: "daily", limit: 10, spent: 1, remaining: 9, fraction: 0.1 },
        {
          period: "weekly",
          limit: 50,
          spent: 48,
          remaining: 2,
          fraction: 0.96,
        },
      ],
      warn_threshold: 0.8,
      hard_stop_threshold: 1,
      exceeded: false,
    },
  });
  expect(budget!.tightest!.period).toBe("weekly");
  expect(budget!.tightest!.remaining).toBe(2);
  expect(budget!.limits).toHaveLength(2);
  expect(budget!.exceeded).toBe(false);
  expect(budget!.warnThreshold).toBe(0.8);
});

test("an exhausted cap is reported as exceeded", () => {
  const budget = threadTokenUsageToSpendBudget({
    ...BUDGET_BASE,
    spend_budget: {
      currency: "USD",
      limits: [
        { period: "daily", limit: 10, spent: 12, remaining: 0, fraction: 1.2 },
      ],
      exceeded: true,
    },
  });
  expect(budget!.exceeded).toBe(true);
  expect(budget!.tightest!.remaining).toBe(0);
});

test("the cost summary carries the spend budget so no extra prop is threaded", () => {
  const summary = threadTokenUsageToCostSummary({
    ...BUDGET_BASE,
    total_cost: 1.5,
    spend_budget: {
      currency: "USD",
      limits: [
        {
          period: "daily",
          limit: 10,
          spent: 1.5,
          remaining: 8.5,
          fraction: 0.15,
        },
      ],
    },
  });
  expect(summary!.spendBudget!.tightest!.remaining).toBe(8.5);
});

test("a cost summary without a budget keeps the field null", () => {
  const summary = threadTokenUsageToCostSummary({
    ...BUDGET_BASE,
    total_cost: 1.5,
  });
  expect(summary!.spendBudget).toBeNull();
});
