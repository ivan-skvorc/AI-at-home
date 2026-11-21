import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import type * as FeaturesApi from "@/core/features/api";
import { fetchFeatures, type FeaturesResponse } from "@/core/features/api";
import {
  useConversationReferencesCapability,
  useMcpTasksEnabled,
  useScheduledTasksFeature,
} from "@/core/features/hooks";

rs.mock("@/core/features/api", () => ({
  ...rs.requireActual<typeof FeaturesApi>("@/core/features/api"),
  fetchFeatures: rs.fn(),
}));
const mockedFetchFeatures = rs.mocked(fetchFeatures);
const capability = (enabled: boolean, maxReferences: number) =>
  ({
    agents_api: { enabled: true },
    conversation_references: { enabled, max_references: maxReferences },
  }) satisfies FeaturesResponse;
function renderCapability() {
  return renderWithClient(useConversationReferencesCapability);
}
function renderWithClient<T>(hook: () => T) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return renderHook(hook, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}
afterEach(() => {
  cleanup();
  mockedFetchFeatures.mockReset();
});

describe("conversation reference discovery", () => {
  it("distinguishes an initial failure from a confirmed disable and supports retry", async () => {
    mockedFetchFeatures.mockRejectedValueOnce(new Error("503 temporary"));
    const { result } = renderCapability();
    expect(result.current.isLoading).toBe(true);
    expect(result.current.isSuccess).toBe(false);
    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.isLoading).toBe(false);
    expect(result.current.isSuccess).toBe(false);
    mockedFetchFeatures.mockResolvedValueOnce(capability(true, 4));
    await result.current.refetch();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current).toMatchObject({
      enabled: true,
      maxReferences: 4,
      error: null,
    });
  });
  it("marks a successful disabled response as authoritative", async () => {
    mockedFetchFeatures.mockResolvedValueOnce(capability(false, 0));
    const { result } = renderCapability();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current).toMatchObject({
      enabled: false,
      isLoading: false,
      error: null,
    });
  });
  it("does not expose a cached enabled capability after a failed refresh", async () => {
    mockedFetchFeatures.mockResolvedValueOnce(capability(true, 3));
    const { result } = renderCapability();
    await waitFor(() => expect(result.current.enabled).toBe(true));
    mockedFetchFeatures.mockRejectedValueOnce(new Error("network unavailable"));
    await result.current.refetch();
    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current).toMatchObject({
      enabled: false,
      isSuccess: false,
      isLoading: false,
    });
  });
});

describe("shared features query", () => {
  it("serves every feature hook from one /api/features request", async () => {
    mockedFetchFeatures.mockResolvedValueOnce({
      ...capability(true, 2),
      mcp_tasks: { enabled: true },
    });
    const { result } = renderWithClient(() => ({
      references: useConversationReferencesCapability(),
      mcpTasks: useMcpTasksEnabled(),
      scheduledTasks: useScheduledTasksFeature(),
    }));
    await waitFor(() => expect(result.current.mcpTasks.enabled).toBe(true));
    expect(result.current.references).toMatchObject({
      enabled: true,
      maxReferences: 2,
    });
    expect(result.current.scheduledTasks.minIntervalSeconds).toBe(60);
    expect(mockedFetchFeatures).toHaveBeenCalledTimes(1);
  });
});
