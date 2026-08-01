import { expect, test } from "@rstest/core";
import { QueryClient, QueryObserver } from "@tanstack/react-query";

import {
  formatCost,
  retainThreadTokenUsagePlaceholder,
  selectContextUsage,
  threadTokenUsageQueryKey,
  threadTokenUsageToCostSummary,
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
    memory: { tokens: 600, cost: 0.01 },
    suggestions: { tokens: 120, cost: null },
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
