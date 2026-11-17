import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
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

import { PROJECTS_QUERY_KEY } from "@/core/projects/api";
import { useArchiveThreads } from "@/core/threads/archive";
import {
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  useDeleteThreads,
  useMoveThreadsToFolder,
  type InfiniteThreadsData,
} from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

const LIST_KEY = [...INFINITE_THREADS_QUERY_KEY_PREFIX, { archived: false }];

function thread(id: string): AgentThread {
  return {
    thread_id: id,
    metadata: {},
    values: { title: id },
    updated_at: "2026-01-01T00:00:00Z",
  } as unknown as AgentThread;
}

function setup<T>(hook: () => T, threadIds: string[]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  client.setQueryData<InfiniteThreadsData>(LIST_KEY, {
    pages: [{ threads: threadIds.map(thread), hiddenCount: 0, hasMore: false }],
    pageParams: [0],
  });
  const invalidate = rs.spyOn(client, "invalidateQueries");
  const reset = rs.spyOn(client, "resetQueries");
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const rendered = renderHook(hook, { wrapper });
  const listIds = () =>
    client
      .getQueryData<InfiniteThreadsData>(LIST_KEY)
      ?.pages.flatMap((page) => page.threads.map((t) => t.thread_id));
  const callsFor = (spy: typeof invalidate | typeof reset, key: unknown[]) =>
    spy.mock.calls.filter(
      ([filters]) => JSON.stringify(filters?.queryKey) === JSON.stringify(key),
    ).length;
  return { client, invalidate, reset, listIds, callsFor, ...rendered };
}

beforeEach(() => {
  mocks.remove.mockReset().mockResolvedValue(undefined);
  mocks.search.mockReset().mockResolvedValue([]);
  mocks.fetch
    .mockReset()
    .mockImplementation(async () => new Response(null, { status: 204 }));
  mocks.notifyThreadsDeleted.mockReset();
});
afterEach(cleanup);

describe("useDeleteThreads", () => {
  test("a 409 fails that chat only; the rest go, with one invalidation and one ledger notice", async () => {
    mocks.remove.mockImplementation(async (threadId: string) => {
      if (threadId === "busy") {
        throw Object.assign(
          new Error('HTTP 409: {"detail":"Thread has work in flight"}'),
          { status: 409 },
        );
      }
    });
    mocks.search.mockImplementation(
      async ({ metadata }: { metadata: { parent_thread_id: string } }) =>
        metadata.parent_thread_id === "first"
          ? [
              {
                thread_id: "first-sidecar",
                metadata: {
                  deerflow_sidecar: true,
                  parent_thread_id: "first",
                },
              },
            ]
          : [],
    );
    const onDeleted = rs.fn();
    const onProgress = rs.fn();
    const { result, listIds, invalidate, callsFor, client } = setup(
      () => useDeleteThreads(),
      ["first", "busy", "last", "untouched"],
    );

    let outcome: Awaited<ReturnType<typeof result.current.mutateAsync>>;
    await act(async () => {
      outcome = await result.current.mutateAsync({
        threadIds: ["first", "busy", "last", "first"],
        onDeleted,
        onProgress,
      });
    });

    expect(outcome!.deleted).toEqual(["first", "last"]);
    expect(outcome!.deletedSidecarIds).toEqual(["first-sidecar"]);
    expect(
      outcome!.failed.map((failure) => [failure.threadId, failure.status]),
    ).toEqual([["busy", 409]]);
    // Each conversation is deleted once, in order, and the busy one never
    // reaches local cleanup.
    expect(mocks.remove.mock.calls.map(([id]) => id)).toEqual([
      "first-sidecar",
      "first",
      "busy",
      "last",
    ]);
    expect(
      mocks.fetch.mock.calls.some(([url]) =>
        String(url).endsWith("/api/threads/busy"),
      ),
    ).toBe(false);
    expect(onDeleted.mock.calls.map(([id]) => id)).toEqual(["first", "last"]);
    expect(onProgress.mock.calls).toEqual([
      [1, 3],
      [2, 3],
      [3, 3],
    ]);

    expect(listIds()).toEqual(["busy", "untouched"]);
    expect(callsFor(invalidate, [...INFINITE_THREADS_QUERY_KEY_PREFIX])).toBe(
      1,
    );
    expect(callsFor(invalidate, ["threads", "search"])).toBe(1);
    expect(callsFor(invalidate, [...PROJECTS_QUERY_KEY, "threads"])).toBe(1);
    expect(mocks.notifyThreadsDeleted).toHaveBeenCalledTimes(1);
    expect(mocks.notifyThreadsDeleted).toHaveBeenCalledWith([
      "first",
      "last",
      "first-sidecar",
    ]);
    client.clear();
  });

  test("nothing deleted means no ledger notice", async () => {
    mocks.remove.mockRejectedValue({ status: 403 });
    const { result, client } = setup(() => useDeleteThreads(), ["a"]);
    await act(async () => {
      await result.current.mutateAsync({ threadIds: ["a"] });
    });
    expect(mocks.notifyThreadsDeleted).not.toHaveBeenCalled();
    client.clear();
  });
});

describe("useMoveThreadsToFolder", () => {
  test("placement-only PATCHes, bounded in flight, one invalidation, per-item failure", async () => {
    let inFlight = 0;
    let peak = 0;
    mocks.fetch.mockImplementation(async (url: string) => {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 5));
      inFlight -= 1;
      if (url.endsWith("/api/threads/c")) {
        return new Response(JSON.stringify({ detail: "Gone wrong" }), {
          status: 500,
        });
      }
      return new Response(
        JSON.stringify({ metadata: { deerflow_folder: "folder-1" } }),
      );
    });
    const ids = ["a", "b", "c", "d", "e", "f"];
    const { result, client, invalidate, callsFor } = setup(
      () => useMoveThreadsToFolder(),
      ids,
    );

    let outcome: Awaited<ReturnType<typeof result.current.mutateAsync>>;
    await act(async () => {
      outcome = await result.current.mutateAsync({
        threadIds: ids,
        folderId: "folder-1",
      });
    });

    expect(outcome!.succeeded).toEqual(["a", "b", "d", "e", "f"]);
    expect(outcome!.failed.map((failure) => failure.threadId)).toEqual(["c"]);
    expect(peak).toBeLessThanOrEqual(4);
    expect(mocks.fetch).toHaveBeenCalledTimes(6);
    for (const [, init] of mocks.fetch.mock.calls as [string, RequestInit][]) {
      expect(init.method).toBe("PATCH");
      // Only the folder key: the Gateway's placement-only shape, which does
      // not bump `updated_at` and so does not reorder the sidebar.
      expect(init.body).toBe(
        JSON.stringify({ metadata: { deerflow_folder: "folder-1" } }),
      );
    }
    const folderOf = (id: string) =>
      client
        .getQueryData<InfiniteThreadsData>(LIST_KEY)
        ?.pages[0]?.threads.find((t) => t.thread_id === id)?.metadata
        ?.deerflow_folder;
    expect(folderOf("a")).toBe("folder-1");
    expect(folderOf("c")).toBeUndefined();
    expect(callsFor(invalidate, [...INFINITE_THREADS_QUERY_KEY_PREFIX])).toBe(
      1,
    );
    expect(callsFor(invalidate, ["threads", "search"])).toBe(1);
    client.clear();
  });
});

describe("useArchiveThreads", () => {
  test("one list reset and one callback for the batch, failures reported", async () => {
    mocks.fetch.mockImplementation(async (url: string) =>
      url.endsWith("/api/threads/b")
        ? new Response(
            JSON.stringify({ detail: "Thread has work in flight" }),
            {
              status: 409,
            },
          )
        : new Response(
            JSON.stringify({ metadata: { deerflow_archived: true } }),
          ),
    );
    const onSettled = rs.fn();
    const { result, client, reset, callsFor } = setup(
      () => useArchiveThreads({ onSettled }),
      ["a", "b", "c"],
    );
    await act(async () => {
      await result.current.mutateAsync({
        threadIds: ["a", "b", "c"],
        archived: true,
      });
    });
    expect(callsFor(reset, [...INFINITE_THREADS_QUERY_KEY_PREFIX])).toBe(1);
    expect(onSettled).toHaveBeenCalledTimes(1);
    const [batch, variables] = onSettled.mock.calls[0]!;
    expect(batch.succeeded).toEqual(["a", "c"]);
    expect(
      batch.failed.map((failure: { threadId: string }) => failure.threadId),
    ).toEqual(["b"]);
    expect(variables).toEqual({ threadIds: ["a", "b", "c"], archived: true });
    client.clear();
  });
});
