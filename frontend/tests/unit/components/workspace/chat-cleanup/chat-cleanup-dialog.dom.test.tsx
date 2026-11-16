import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

/**
 * The clean-up dialog end to end over a mocked Gateway (fork feature).
 *
 * What only the assembled dialog can show: the read-only calls run first and
 * nothing is written until Apply; Apply writes new folders in one PUT, moves
 * with the placement-only PATCH and renames with `preserve_recency`; Cancel and
 * closing abort the calls in flight; a spend-cap refusal stops the pass after
 * one call and says why.
 */

type Recorded = {
  url: string;
  method: string;
  body: unknown;
  signal: AbortSignal | undefined;
};

const mocks = rs.hoisted(() => ({
  fetch: rs.fn(),
  capability: { enabled: true, modelName: null as string | null },
}));

rs.mock("@/core/api/fetcher", () => ({
  fetch: mocks.fetch,
  getCsrfHeaders: () => ({}),
}));
rs.mock("@/core/api", () => ({
  getAPIClient: () => ({
    threads: { get: rs.fn(), search: rs.fn() },
  }),
}));
rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({
    // A local model (weights on disk): the pass reads one chat at a time.
    models: [
      {
        id: "local-model",
        name: "local-model",
        model: "local-model",
        display_name: "Local Model",
        size_bytes: 4_000_000_000,
      },
    ],
    tokenUsageEnabled: false,
  }),
}));
rs.mock("@/core/features", () => ({
  useAutoTitleCapability: () => ({ ...mocks.capability, isLoading: false }),
}));

import { ChatCleanupDialog } from "@/components/workspace/chat-cleanup/chat-cleanup-dialog";
import { I18nProvider } from "@/core/i18n/context";
import {
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  type InfiniteThreadsData,
} from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";
import { CHAT_FOLDERS_QUERY_KEY } from "@/core/threads/use-chat-folders";

const recorded: Recorded[] = [];
let handle: (request: Recorded) => Promise<Response> | Response;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function thread(id: string, title: string, folderId?: string): AgentThread {
  return {
    thread_id: id,
    created_at: "2026-10-05T12:00:00Z",
    updated_at: "2026-10-05T12:00:00Z",
    metadata: folderId ? { deerflow_folder: folderId } : {},
    status: "idle",
    values: { title },
  } as unknown as AgentThread;
}

const clients: QueryClient[] = [];

function renderDialog({
  threadIds,
  threads,
  open = true,
}: {
  threadIds: string[] | null;
  threads: AgentThread[];
  open?: boolean;
}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
  clients.push(queryClient);
  queryClient.setQueryData<InfiniteThreadsData>(
    [...INFINITE_THREADS_QUERY_KEY_PREFIX, { archived: false }],
    { pages: [{ threads, hiddenCount: 0, hasMore: false }], pageParams: [0] },
  );
  queryClient.setQueryData(CHAT_FOLDERS_QUERY_KEY, [
    { id: "home", name: "Home" },
  ]);
  const onOpenChange = rs.fn();
  const view = (isOpen: boolean) => (
    <I18nProvider initialLocale="en-US">
      <QueryClientProvider client={queryClient}>
        <ChatCleanupDialog
          open={isOpen}
          onOpenChange={onOpenChange}
          threadIds={threadIds}
        />
      </QueryClientProvider>
    </I18nProvider>
  );
  const result = render(view(open));
  return {
    onOpenChange,
    queryClient,
    rerender: (isOpen: boolean) => result.rerender(view(isOpen)),
  };
}

function requestsTo(fragment: string, method?: string) {
  return recorded.filter(
    (request) =>
      request.url.includes(fragment) && (!method || request.method === method),
  );
}

beforeEach(() => {
  document.cookie = "locale=en-US; path=/";
  window.localStorage.clear();
  recorded.length = 0;
  mocks.capability.enabled = true;
  mocks.capability.modelName = null;
  handle = () => json({ detail: "Not mocked" }, 404);
  mocks.fetch.mockImplementation(
    async (url: string, init: RequestInit | undefined) => {
      const request: Recorded = {
        url,
        method: init?.method ?? "GET",
        body: init?.body ? JSON.parse(init.body as string) : undefined,
        signal: init?.signal ?? undefined,
      };
      recorded.push(request);
      return handle(request);
    },
  );
});

afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) {
    client.clear();
  }
  mocks.fetch.mockReset();
});

test("setup, run, preview and apply: nothing is written before Apply, then one folder write", async () => {
  let folders = [{ id: "home", name: "Home" }];
  handle = (request) => {
    if (request.url.endsWith("/api/threads/t1/organize/suggest")) {
      return json({
        thread_id: "t1",
        current_title: "Pasta recipe chat",
        title: "Weeknight pasta",
        title_changed: true,
        category: "Cooking",
        summary: "Pasta recipes.",
      });
    }
    if (request.url.endsWith("/api/threads/t2/organize/suggest")) {
      return json({
        thread_id: "t2",
        current_title: "garden",
        title: "Garden plans",
        title_changed: true,
        category: "Home",
      });
    }
    if (request.url.endsWith("/api/chat-organize/consolidate")) {
      return json({
        folders: [
          { name: "Cooking", existing_folder_id: null, thread_ids: ["t1"] },
          { name: "Home", existing_folder_id: "home", thread_ids: ["t2"] },
        ],
        unfiled: [],
        model_name: "local-model",
      });
    }
    if (request.url.endsWith("/api/settings/chat-folders")) {
      if (request.method === "PUT") {
        folders = (request.body as { chat_folders: typeof folders })
          .chat_folders;
      }
      return json({ chat_folders: folders });
    }
    if (request.method === "PATCH") {
      return json({
        thread_id: "t1",
        metadata: (request.body as { metadata: unknown }).metadata,
      });
    }
    if (request.url.endsWith("/state")) {
      return json({ values: {} });
    }
    return json({ detail: "Not mocked" }, 404);
  };

  renderDialog({
    threadIds: ["t1", "t2"],
    threads: [
      thread("t1", "Pasta recipe chat"),
      thread("t2", "garden", "home"),
    ],
  });

  expect(await screen.findByText("2 selected conversations")).toBeTruthy();
  // The shared picker (FORK.md §8), on its server-default row.
  expect(screen.getByTestId("chat-cleanup-model-select").textContent).toContain(
    "Server default",
  );
  expect(
    screen.getByText("Local model: conversations are read one at a time."),
  ).toBeTruthy();

  await act(async () => {
    fireEvent.click(screen.getByTestId("chat-cleanup-start"));
  });
  await screen.findByTestId("chat-cleanup-preview");

  // Read-only so far: two suggest calls and one consolidation, no writes.
  expect(requestsTo("/organize/suggest").map((r) => r.body)).toEqual([
    { rename: true, mode: "auto", existing: [{ id: "home", name: "Home" }] },
    { rename: true, mode: "auto", existing: [{ id: "home", name: "Home" }] },
  ]);
  expect(requestsTo("/api/chat-organize/consolidate")[0]!.body).toMatchObject({
    items: [
      { thread_id: "t1", category: "Cooking" },
      { thread_id: "t2", category: "Home" },
    ],
    existing: [{ id: "home", name: "Home" }],
    max_new_folders: 8,
    min_group_size: 1,
  });
  expect(
    recorded.filter((r) => r.method === "PUT" || r.method === "PATCH"),
  ).toEqual([]);
  expect(requestsTo("/state")).toEqual([]);

  const rows = screen.getAllByTestId("chat-cleanup-row");
  expect(rows).toHaveLength(2);
  const firstTitle = within(rows[0]!).getByTestId<HTMLInputElement>(
    "chat-cleanup-row-title",
  );
  expect(firstTitle.value).toBe("Weeknight pasta");
  fireEvent.change(firstTitle, { target: { value: "Pasta nights" } });
  expect(screen.getByTestId("chat-cleanup-proposed-folder")).toBeTruthy();

  await act(async () => {
    fireEvent.click(screen.getByTestId("chat-cleanup-apply"));
  });
  await screen.findByTestId("chat-cleanup-result");

  const puts = requestsTo("/api/settings/chat-folders", "PUT");
  expect(puts).toHaveLength(1);
  const saved = (
    puts[0]!.body as { chat_folders: { id: string; name: string }[] }
  ).chat_folders;
  expect(saved.map((folder) => folder.name)).toEqual(["Home", "Cooking"]);
  const cookingId = saved[1]!.id;

  // t2 already sits in Home: no PATCH for it. t1 moves into the new folder,
  // with nothing but the placement key.
  expect(
    requestsTo("/api/threads/", "PATCH").map((r) => [r.url, r.body]),
  ).toEqual([
    [
      expect.stringContaining("/api/threads/t1"),
      { metadata: { deerflow_folder: cookingId } },
    ],
  ]);
  // Writes run a few at a time, so their order is not fixed.
  const renames = requestsTo("/state").map((r) => r.body);
  expect(renames).toHaveLength(2);
  expect(renames).toEqual(
    expect.arrayContaining([
      { values: { title: "Pasta nights" }, preserve_recency: true },
      { values: { title: "Garden plans" }, preserve_recency: true },
    ]),
  );
  const result = screen.getByTestId("chat-cleanup-result");
  expect(result.textContent).toContain("2 conversations renamed");
  expect(result.textContent).toContain("1 conversation moved");
  expect(result.textContent).toContain("1 folder created");

  // The model, mode and rename choice are remembered for the next pass.
  const stored = JSON.parse(
    window.localStorage.getItem("deerflow.local-settings") ?? "{}",
  ) as { chatCleanup?: unknown };
  expect(stored.chatCleanup).toMatchObject({
    rename: true,
    folderMode: "auto",
    maxNewFolders: 8,
  });
});

test("Cancel aborts the calls in flight and returns to the setup", async () => {
  handle = (request) =>
    new Promise<Response>((_resolve, reject) => {
      request.signal?.addEventListener("abort", () =>
        reject(new DOMException("aborted", "AbortError")),
      );
    });
  renderDialog({
    threadIds: ["t1", "t2"],
    threads: [thread("t1", "One"), thread("t2", "Two")],
  });
  await screen.findByText("2 selected conversations");

  await act(async () => {
    fireEvent.click(screen.getByTestId("chat-cleanup-start"));
  });
  await screen.findByTestId("chat-cleanup-running");
  await waitFor(() => expect(requestsTo("/organize/suggest")).toHaveLength(1));
  const inFlight = requestsTo("/organize/suggest")[0]!;
  expect(inFlight.signal?.aborted).toBe(false);

  await act(async () => {
    fireEvent.click(screen.getByTestId("chat-cleanup-cancel-run"));
  });
  expect(inFlight.signal?.aborted).toBe(true);
  expect(await screen.findByTestId("chat-cleanup-setup")).toBeTruthy();
  // The aborted pass never reaches a second conversation.
  expect(requestsTo("/organize/suggest")).toHaveLength(1);
});

test("closing the dialog aborts the calls in flight", async () => {
  handle = (request) =>
    new Promise<Response>((_resolve, reject) => {
      request.signal?.addEventListener("abort", () =>
        reject(new DOMException("aborted", "AbortError")),
      );
    });
  const view = renderDialog({
    threadIds: ["t1"],
    threads: [thread("t1", "One")],
  });
  await screen.findByText("1 selected conversation");
  await act(async () => {
    fireEvent.click(screen.getByTestId("chat-cleanup-start"));
  });
  await waitFor(() => expect(requestsTo("/organize/suggest")).toHaveLength(1));

  await act(async () => {
    view.rerender(false);
  });
  expect(requestsTo("/organize/suggest")[0]!.signal?.aborted).toBe(true);
});

test("a spend-cap refusal stops the pass after one call and says why", async () => {
  handle = (request) =>
    request.url.includes("/organize/suggest")
      ? json({ detail: "Spend cap reached for today." }, 402)
      : json({ detail: "Not mocked" }, 404);
  renderDialog({
    threadIds: ["t1", "t2", "t3"],
    threads: [thread("t1", "One"), thread("t2", "Two"), thread("t3", "Three")],
  });
  await screen.findByText("3 selected conversations");

  await act(async () => {
    fireEvent.click(screen.getByTestId("chat-cleanup-start"));
  });

  const notice = await screen.findByTestId("chat-cleanup-notice");
  expect(notice.textContent).toContain("Spend cap reached for today.");
  expect(requestsTo("/organize/suggest")).toHaveLength(1);
  expect(requestsTo("/consolidate")).toEqual([]);
  // Back on the setup, where another model can be picked.
  expect(screen.getByTestId("chat-cleanup-setup")).toBeTruthy();
});

test("with renaming off on the server, the switch is greyed and nothing-to-do blocks the start", async () => {
  mocks.capability.enabled = false;
  renderDialog({
    threadIds: ["t1"],
    threads: [thread("t1", "One")],
  });
  await screen.findByText("1 selected conversation");

  const renameSwitch = screen.getByTestId("chat-cleanup-rename");
  expect(renameSwitch.getAttribute("aria-checked")).toBe("false");
  expect((renameSwitch as HTMLButtonElement).disabled).toBe(true);
  expect(
    screen.getByText("Renaming is turned off on this server."),
  ).toBeTruthy();

  fireEvent.click(screen.getByTestId("chat-cleanup-mode-none"));
  expect(
    screen.getByTestId<HTMLButtonElement>("chat-cleanup-start").disabled,
  ).toBe(true);
});
