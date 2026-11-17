import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({
  remove: rs.fn(),
  search: rs.fn(),
  fetch: rs.fn(),
  notifyThreadsDeleted: rs.fn(),
}));
rs.mock("@/core/api", () => ({
  getAPIClient: () => ({
    threads: { delete: mocks.remove, search: mocks.search },
  }),
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/folder-ledger/events", () => ({
  notifyThreadsDeleted: mocks.notifyThreadsDeleted,
}));

import { useDeleteThread } from "@/core/threads/hooks";

beforeEach(() => {
  mocks.remove.mockReset().mockResolvedValue(undefined);
  mocks.search.mockReset().mockResolvedValue([]);
  mocks.fetch
    .mockReset()
    .mockImplementation(async () => new Response(null, { status: 204 }));
  mocks.notifyThreadsDeleted.mockReset();
});
afterEach(cleanup);

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useDeleteThread(), { wrapper });
}

test("cleanup failure does not invoke completion and a remote 404 retry finishes cleanup", async () => {
  const onDeleted = rs.fn();
  const { result } = setup();
  mocks.fetch.mockResolvedValueOnce(
    new Response(JSON.stringify({ detail: "Cleanup unavailable" }), {
      status: 500,
    }),
  );
  await act(async () => {
    await expect(
      result.current.mutateAsync({ threadId: "parent", onDeleted }),
    ).rejects.toThrow("Cleanup unavailable");
  });
  expect(onDeleted).not.toHaveBeenCalled();
  mocks.remove.mockRejectedValueOnce(
    Object.assign(new Error("Thread not found"), { status: 404 }),
  );
  await act(async () => {
    await result.current.mutateAsync({ threadId: "parent", onDeleted });
  });
  expect(mocks.fetch).toHaveBeenCalledTimes(2);
  expect(onDeleted).toHaveBeenCalledTimes(1);
  // Only the completed delete reaches the folder ledger's orphan offer.
  expect(mocks.notifyThreadsDeleted).toHaveBeenCalledTimes(1);
  expect(mocks.notifyThreadsDeleted).toHaveBeenCalledWith(["parent"]);
});

for (const status of [403, 500]) {
  test(`remote ${status} stays an error and never starts local cleanup`, async () => {
    const onDeleted = rs.fn();
    mocks.remove.mockRejectedValueOnce({ status });
    const { result } = setup();
    await act(async () => {
      await expect(
        result.current.mutateAsync({ threadId: "parent", onDeleted }),
      ).rejects.toEqual({ status });
    });
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(onDeleted).not.toHaveBeenCalled();
    expect(mocks.notifyThreadsDeleted).not.toHaveBeenCalled();
  });
}

test("already-deleted sidecars still receive local cleanup", async () => {
  mocks.search.mockResolvedValueOnce([
    {
      thread_id: "sidecar",
      metadata: { deerflow_sidecar: true, parent_thread_id: "parent" },
    },
  ]);
  mocks.remove.mockRejectedValueOnce(
    Object.assign(new Error("Thread not found"), { response: { status: 404 } }),
  );
  const { result } = setup();
  await act(async () => {
    await expect(
      result.current.mutateAsync({ threadId: "parent" }),
    ).resolves.toEqual(["sidecar"]);
  });
  expect(mocks.fetch).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/sidecar"),
    { method: "DELETE" },
  );
  expect(mocks.fetch).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/parent"),
    { method: "DELETE" },
  );
  // One notification for the conversation and its Side Chat threads.
  expect(mocks.notifyThreadsDeleted).toHaveBeenCalledTimes(1);
  expect(mocks.notifyThreadsDeleted).toHaveBeenCalledWith([
    "parent",
    "sidecar",
  ]);
});

test("Side Chat threads deleted before a refused parent delete still reach the folder ledger", async () => {
  mocks.search.mockResolvedValueOnce([
    {
      thread_id: "sidecar",
      metadata: { deerflow_sidecar: true, parent_thread_id: "parent" },
    },
  ]);
  mocks.remove.mockImplementation(async (threadId: string) => {
    if (threadId === "parent") {
      throw Object.assign(new Error("Thread has work in flight"), {
        status: 409,
      });
    }
  });
  const onDeleted = rs.fn();
  const { result } = setup();
  await act(async () => {
    await expect(
      result.current.mutateAsync({ threadId: "parent", onDeleted }),
    ).rejects.toThrow("Thread has work in flight");
  });
  expect(onDeleted).not.toHaveBeenCalled();
  // The retry will not find the sidecar again, so its folders are offered now.
  expect(mocks.notifyThreadsDeleted).toHaveBeenCalledTimes(1);
  expect(mocks.notifyThreadsDeleted).toHaveBeenCalledWith(["sidecar"]);
});
