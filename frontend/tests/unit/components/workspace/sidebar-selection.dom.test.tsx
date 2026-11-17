import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
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
import type { ReactNode } from "react";

const nav = rs.hoisted(() => ({
  activeThreadId: null as string | null,
  replace: rs.fn(),
}));
const mocks = rs.hoisted(() => ({
  remove: rs.fn(),
  search: rs.fn(),
  fetch: rs.fn(),
  notifyThreadsDeleted: rs.fn(),
  saveChatFolders: rs.fn(),
  cleanupProps: [] as Array<{ open: boolean; threadIds: string[] | null }>,
  toast: { success: rs.fn(), error: rs.fn(), info: rs.fn() },
}));

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: nav.replace, refresh: rs.fn() }),
  usePathname: () =>
    nav.activeThreadId
      ? `/workspace/chats/${nav.activeThreadId}`
      : "/workspace/chats",
  useSearchParams: () => new URLSearchParams(),
  useParams: () =>
    nav.activeThreadId ? { thread_id: nav.activeThreadId } : {},
}));
rs.mock("sonner", () => ({ toast: mocks.toast }));
rs.mock("@/core/api", () => ({
  getAPIClient: () => ({
    threads: { delete: mocks.remove, search: mocks.search },
  }),
}));
rs.mock("@/core/api/fetcher", () => ({
  fetch: mocks.fetch,
  getCsrfHeaders: () => ({}),
}));
rs.mock("@/core/folder-ledger/events", () => ({
  notifyThreadsDeleted: mocks.notifyThreadsDeleted,
}));
rs.mock("@/core/threads/chat-folders-api", () => ({
  fetchChatFolders: async () => null,
  saveChatFolders: mocks.saveChatFolders,
}));
rs.mock("@/components/workspace/chat-cleanup/chat-cleanup-dialog", () => ({
  ChatCleanupDialog: (props: { open: boolean; threadIds: string[] | null }) => {
    mocks.cleanupProps.push({ open: props.open, threadIds: props.threadIds });
    return props.open ? (
      <div data-testid="cleanup-dialog-stub">
        {props.threadIds === null ? "all" : props.threadIds.join(",")}
      </div>
    ) : null;
  },
}));

import { SidebarProvider } from "@/components/ui/sidebar";
import { RecentChatList } from "@/components/workspace/recent-chat-list";
import { SidebarSelectionProvider } from "@/components/workspace/sidebar-selection";
import { ThreadDeleteDialogProvider } from "@/components/workspace/thread-delete-dialog";
import { AuthProvider } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import { I18nProvider } from "@/core/i18n/context";
import { CHAT_FOLDERS_EXPANDED_STORAGE_KEY } from "@/core/threads/chat-folders";
import {
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  type InfiniteThreadsData,
} from "@/core/threads/hooks";
import { THREAD_SELECTING_ATTRIBUTE } from "@/core/threads/thread-selection";
import type { AgentThread } from "@/core/threads/types";
import { CHAT_FOLDERS_QUERY_KEY } from "@/core/threads/use-chat-folders";

const WORK = "folder-work";

function thread(
  id: string,
  title: string,
  folderId: string | null = null,
): AgentThread {
  return {
    thread_id: id,
    created_at: "2026-10-05T12:00:00Z",
    updated_at: "2026-10-05T12:00:00Z",
    metadata: folderId ? { deerflow_folder: folderId } : {},
    status: "idle",
    values: { title },
  } as unknown as AgentThread;
}

// Recency order is the list order; the folder's chats render above the root.
const THREADS = [
  thread("r1", "Root one"),
  thread("w1", "Work one", WORK),
  thread("r2", "Root two"),
  thread("w2", "Work two", WORK),
  thread("r3", "Root three"),
];

const clients: QueryClient[] = [];

function renderSidebar({
  withProvider = true,
  permissions,
}: { withProvider?: boolean; permissions?: string[] } = {}) {
  document.cookie = "locale=en-US; path=/";
  window.localStorage.setItem(
    CHAT_FOLDERS_EXPANDED_STORAGE_KEY,
    JSON.stringify([WORK]),
  );
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
  clients.push(queryClient);
  queryClient.setQueryData<InfiniteThreadsData>(
    [...INFINITE_THREADS_QUERY_KEY_PREFIX, { archived: false }],
    {
      pages: [{ threads: THREADS, hiddenCount: 0, hasMore: false }],
      pageParams: [0],
    },
  );
  queryClient.setQueryData(CHAT_FOLDERS_QUERY_KEY, [
    { id: WORK, name: "Work" },
  ]);
  const user = {
    id: "user-1",
    email: "user@example.test",
    system_role: "user",
    ...(permissions ? { permissions } : {}),
  } as User;
  const list: ReactNode = withProvider ? (
    <SidebarSelectionProvider>
      <RecentChatList />
    </SidebarSelectionProvider>
  ) : (
    <RecentChatList />
  );
  return render(
    <I18nProvider initialLocale="en-US">
      <QueryClientProvider client={queryClient}>
        <AuthProvider initialUser={user}>
          <SidebarProvider>
            <ThreadDeleteDialogProvider>{list}</ThreadDeleteDialogProvider>
          </SidebarProvider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>,
  );
}

function rowLink(threadId: string): HTMLElement {
  const link = document.querySelector<HTMLElement>(
    `a[data-sidebar="menu-button"][href="/workspace/chats/${threadId}"]`,
  );
  expect(link).not.toBeNull();
  return link!;
}

function checkbox(title: string): HTMLInputElement {
  const box = screen.getByRole("checkbox", { name: `Select “${title}”` });
  expect(box).toBeInstanceOf(HTMLInputElement);
  return box as HTMLInputElement;
}

function selectedCount(): string {
  return screen.getByTestId("chat-selection-count").textContent ?? "";
}

async function startSelecting() {
  fireEvent.click(await screen.findByTestId("chat-selection-toggle"));
  await screen.findByTestId("chat-selection-toolbar");
}

/** Radix menus open on pointerdown, not click (verified in happy-dom). */
function openMenu(trigger: HTMLElement) {
  fireEvent.pointerDown(trigger, { button: 0, pointerType: "mouse" });
  fireEvent.click(trigger);
}

/** The request bodies in these tests are always JSON strings. */
function jsonBody(init: RequestInit | undefined): {
  metadata?: Record<string, unknown>;
} {
  return typeof init?.body === "string" ? JSON.parse(init.body) : {};
}

function patchBodies(): Array<[string, unknown]> {
  return (mocks.fetch.mock.calls as Array<[string, RequestInit | undefined]>)
    .filter(([, init]) => init?.method === "PATCH")
    .map(([url, init]) => [url.split("/").pop() ?? "", jsonBody(init)]);
}

/**
 * A small Gateway for the thread routes: PATCH merges metadata (or answers
 * with what `answer` returns for that call), and the list reads what the
 * PATCHes left, so a list refetched after an action still shows every chat.
 */
function serveThreads(
  answer: (
    threadId: string,
    metadata: Record<string, unknown>,
  ) => Response | null | Promise<Response | null> = () => null,
) {
  const metadataById = new Map(
    THREADS.map((item) => [item.thread_id, { ...item.metadata }]),
  );
  mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    if (init?.method === "PATCH") {
      const threadId = url.split("/").pop() ?? "";
      const metadata = jsonBody(init).metadata ?? {};
      const response = await answer(threadId, metadata);
      if (response) {
        return response;
      }
      metadataById.set(threadId, {
        ...metadataById.get(threadId),
        ...metadata,
      });
      return new Response(JSON.stringify({ metadata }));
    }
    if (url.endsWith("/api/threads/search")) {
      const { archived } = jsonBody(init) as { archived?: boolean };
      return new Response(
        JSON.stringify(
          THREADS.map((item) => ({
            ...item,
            metadata: metadataById.get(item.thread_id) ?? {},
          })).filter(
            (item) =>
              Boolean(item.metadata.deerflow_archived) === Boolean(archived),
          ),
        ),
      );
    }
    return new Response(null, { status: 204 });
  });
}

const busy = () =>
  new Response(JSON.stringify({ detail: "busy" }), { status: 409 });

beforeEach(() => {
  nav.activeThreadId = null;
  nav.replace.mockReset();
  mocks.toast.success.mockReset();
  mocks.toast.error.mockReset();
  mocks.toast.info.mockReset();
  mocks.remove.mockReset().mockResolvedValue(undefined);
  mocks.search.mockReset().mockResolvedValue([]);
  mocks.notifyThreadsDeleted.mockReset();
  mocks.cleanupProps.length = 0;
  mocks.saveChatFolders
    .mockReset()
    .mockImplementation(async (folders: unknown) => folders);
  mocks.fetch
    .mockReset()
    .mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") {
        return new Response(
          JSON.stringify({ metadata: jsonBody(init).metadata }),
        );
      }
      return new Response(null, { status: 204 });
    });
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  document.cookie = "locale=; max-age=0; path=/";
  clients.splice(0).forEach((client) => client.clear());
});

describe("sidebar multi-select", () => {
  test("no checkbox and no Select button without a provider; no checkbox before selecting", async () => {
    const view = renderSidebar({ withProvider: false });
    await screen.findByRole("link", { name: /Root one/ });
    expect(screen.queryByTestId("chat-selection-toggle")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    view.unmount();

    renderSidebar();
    expect(
      (await screen.findByTestId("chat-selection-toggle")).textContent,
    ).toBe("Select");
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(rowLink("r1").hasAttribute(THREAD_SELECTING_ATTRIBUTE)).toBe(false);
    expect(screen.queryByTestId("chat-selection-toolbar")).toBeNull();
  });

  test("a checkbox sits beside the link, and a click on the row toggles instead of navigating", async () => {
    renderSidebar();
    await startSelecting();
    expect(selectedCount()).toBe("0 selected");

    const box = checkbox("Root one");
    const link = rowLink("r1");
    // A sibling of the link in the same <li>: never inside the <a>, never
    // wrapping it.
    expect(box.parentElement).toBe(link.parentElement);
    expect(link.contains(box)).toBe(false);
    expect(link.getAttribute("draggable")).toBe("true");

    // The mobile drawer reads this marker to leave a selecting row's click to
    // the row (workspace-sidebar-frame.tsx).
    expect(link.getAttribute(THREAD_SELECTING_ATTRIBUTE)).toBe("true");

    fireEvent.click(box);
    expect(box.checked).toBe(true);
    expect(selectedCount()).toBe("1 selected");

    // The row's own click cancels the navigation and toggles.
    const notCancelled = fireEvent.click(rowLink("r2"));
    expect(notCancelled).toBe(false);
    expect(checkbox("Root two").checked).toBe(true);
    // Ctrl/Cmd-click would open a tab outside selection mode; here it toggles.
    expect(fireEvent.click(rowLink("r2"), { metaKey: true })).toBe(false);
    expect(checkbox("Root two").checked).toBe(false);
    expect(selectedCount()).toBe("1 selected");

    // Escape leaves selection mode and forgets the selection.
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByTestId("chat-selection-toolbar")).toBeNull(),
    );
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(rowLink("r1").hasAttribute(THREAD_SELECTING_ATTRIBUTE)).toBe(false);
  });

  test("shift-click selects the rendered run from a folder into the root list", async () => {
    renderSidebar();
    await startSelecting();
    // Rendered order: Work (w1, w2), then the root list (r1, r2, r3).
    fireEvent.click(checkbox("Work one"));
    fireEvent.click(checkbox("Root two"), { shiftKey: true });
    expect(selectedCount()).toBe("4 selected");
    for (const title of ["Work one", "Work two", "Root one", "Root two"]) {
      expect(checkbox(title).checked).toBe(true);
    }
    expect(checkbox("Root three").checked).toBe(false);

    // A shift-click on the link draws the range too.
    fireEvent.click(rowLink("r3"), { shiftKey: true });
    expect(selectedCount()).toBe("5 selected");

    // Select all ticks everything shown.
    fireEvent.click(checkbox("Root one"));
    expect(selectedCount()).toBe("4 selected");
    fireEvent.click(screen.getByTestId("chat-selection-select-all"));
    expect(selectedCount()).toBe("5 selected");
  });

  test("the row menu starts selection with that row, and links to its files", async () => {
    renderSidebar();
    const row = rowLink("w2").parentElement!;
    openMenu(within(row).getByRole("button", { name: "More" }));
    const files = await screen.findByRole("menuitem", { name: "Show files" });
    expect(files.getAttribute("href")).toBe("/workspace/chats/w2?panel=files");
    fireEvent.click(screen.getByRole("menuitem", { name: "Select" }));
    await screen.findByTestId("chat-selection-toolbar");
    expect(checkbox("Work two").checked).toBe(true);
    expect(selectedCount()).toBe("1 selected");
  });

  test("Move files the selection with placement-only PATCHes", async () => {
    renderSidebar();
    await startSelecting();
    fireEvent.click(checkbox("Root one"));
    fireEvent.click(checkbox("Root three"));
    openMenu(screen.getByTestId("chat-selection-move"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Work" }));
    await waitFor(() => expect(patchBodies()).toHaveLength(2));
    expect(patchBodies().sort()).toEqual([
      ["r1", { metadata: { deerflow_folder: WORK } }],
      ["r3", { metadata: { deerflow_folder: WORK } }],
    ]);
    // Done: the selection empties, selection mode stays for the next batch.
    await waitFor(() => expect(selectedCount()).toBe("0 selected"));
  });

  test("a move unticks only what it handled; ticks changed while it ran stay", async () => {
    let releaseFirst: () => void = () => undefined;
    serveThreads((threadId) => {
      if (threadId === "r1") {
        return new Promise<null>((resolve) => {
          releaseFirst = () => resolve(null);
        });
      }
      return threadId === "r3" ? busy() : null;
    });
    renderSidebar();
    await startSelecting();
    fireEvent.click(checkbox("Root one"));
    fireEvent.click(checkbox("Root three"));
    openMenu(screen.getByTestId("chat-selection-move"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Work" }));
    await waitFor(() => expect(patchBodies()).toHaveLength(2));

    // While the move runs: tick another chat, and untick the one that is
    // about to fail.
    fireEvent.click(checkbox("Root two"));
    fireEvent.click(checkbox("Root three"));
    await act(async () => {
      releaseFirst();
    });
    await waitFor(() => expect(mocks.toast.error).toHaveBeenCalled());

    await waitFor(() => expect(selectedCount()).toBe("1 selected"));
    expect(checkbox("Root two").checked).toBe(true);
    expect(checkbox("Root three").checked).toBe(false);
    expect(checkbox("Root one").checked).toBe(false);
  });

  test("New folder from selection creates the folder and files every selected chat", async () => {
    renderSidebar();
    await startSelecting();
    fireEvent.click(checkbox("Root two"));
    fireEvent.click(checkbox("Work one"));
    openMenu(screen.getByTestId("chat-selection-move"));
    fireEvent.click(
      await screen.findByRole("menuitem", {
        name: "New folder from selection…",
      }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain(
      "The 2 selected chats move into the new folder.",
    );
    fireEvent.change(within(dialog).getByTestId("chat-folder-name-input"), {
      target: { value: "Q3" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(mocks.saveChatFolders).toHaveBeenCalled());
    const saved = mocks.saveChatFolders.mock.calls.at(-1)![0] as Array<{
      id: string;
      name: string;
    }>;
    const created = saved.find((folder) => folder.name === "Q3");
    expect(created).toBeDefined();
    await waitFor(() => expect(patchBodies()).toHaveLength(2));
    expect(patchBodies().sort()).toEqual([
      ["r2", { metadata: { deerflow_folder: created!.id } }],
      ["w1", { metadata: { deerflow_folder: created!.id } }],
    ]);
  });

  test("Archive archives the batch through one bulk call", async () => {
    renderSidebar();
    await startSelecting();
    fireEvent.click(checkbox("Root one"));
    fireEvent.click(checkbox("Work two"));
    fireEvent.click(screen.getByTestId("chat-selection-archive"));
    await waitFor(() => expect(patchBodies()).toHaveLength(2));
    expect(patchBodies().sort()).toEqual([
      ["r1", { metadata: { deerflow_archived: true } }],
      ["w2", { metadata: { deerflow_archived: true } }],
    ]);
  });

  test("one toast for the batch; its Undo restores exactly the archived chats and leaves the selection alone", async () => {
    serveThreads((threadId, metadata) =>
      threadId === "w2" && metadata.deerflow_archived === true ? busy() : null,
    );
    renderSidebar();
    await startSelecting();
    fireEvent.click(checkbox("Root one"));
    fireEvent.click(checkbox("Root three"));
    fireEvent.click(checkbox("Work two"));
    fireEvent.click(screen.getByTestId("chat-selection-archive"));

    await waitFor(() => expect(mocks.toast.success).toHaveBeenCalledTimes(1));
    expect(mocks.toast.success.mock.calls[0]![0]).toBe("Archived 2 chats");
    expect(mocks.toast.error).toHaveBeenCalledTimes(1);
    expect(mocks.toast.error.mock.calls[0]![0]).toBe(
      "1 chat could not be archived. It is still selected.",
    );
    // The failure stays ticked; the archived chats leave the selection.
    await waitFor(() => expect(selectedCount()).toBe("1 selected"));
    expect(checkbox("Work two").checked).toBe(true);

    // A new tick, then Undo from the toast.
    fireEvent.click(checkbox("Root two"));
    expect(selectedCount()).toBe("2 selected");
    const archivePatches = patchBodies().length;
    const { action } = mocks.toast.success.mock.calls[0]![1] as {
      action: { onClick: () => void };
    };
    await act(async () => {
      action.onClick();
    });
    await waitFor(() =>
      expect(mocks.toast.success).toHaveBeenCalledWith("Restored 2 chats"),
    );
    expect(patchBodies().slice(archivePatches).sort()).toEqual([
      ["r1", { metadata: { deerflow_archived: false } }],
      ["r3", { metadata: { deerflow_archived: false } }],
    ]);
    // The restore is not a selection action: both ticks are still there.
    expect(selectedCount()).toBe("2 selected");
    expect(checkbox("Root two").checked).toBe(true);
    expect(checkbox("Work two").checked).toBe(true);
  });

  test("Delete confirms with the titles, deletes the batch and leaves the open chat", async () => {
    nav.activeThreadId = "r2";
    renderSidebar();
    await startSelecting();
    fireEvent.click(checkbox("Root two"));
    fireEvent.click(checkbox("Work one"));
    fireEvent.click(screen.getByTestId("chat-selection-delete"));

    const dialog = await screen.findByTestId("thread-bulk-delete-dialog");
    expect(within(dialog).getByText("Delete 2 chats?")).not.toBeNull();
    expect(dialog.textContent).toContain("cannot be undone");
    expect(dialog.textContent).toContain("Root two");
    expect(dialog.textContent).toContain("Work one");
    expect(dialog.textContent).toContain("the chat that is open now");
    expect(mocks.remove).not.toHaveBeenCalled();

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Delete 2 chats" }),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("thread-bulk-delete-dialog")).toBeNull(),
    );
    expect(mocks.remove.mock.calls.map(([id]) => id).sort()).toEqual([
      "r2",
      "w1",
    ]);
    expect(nav.replace).toHaveBeenCalledTimes(1);
    expect(nav.replace).toHaveBeenCalledWith("/workspace/chats/new");
    expect(mocks.notifyThreadsDeleted).toHaveBeenCalledTimes(1);
  });

  test("a chat that fails to delete stays selected and in the dialog for a retry", async () => {
    mocks.remove.mockImplementation(async (threadId: string) => {
      if (threadId === "w1") {
        throw Object.assign(new Error("HTTP 409: busy"), { status: 409 });
      }
    });
    renderSidebar();
    await startSelecting();
    fireEvent.click(checkbox("Root one"));
    fireEvent.click(checkbox("Work one"));
    fireEvent.click(screen.getByTestId("chat-selection-delete"));
    const dialog = await screen.findByTestId("thread-bulk-delete-dialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Delete 2 chats" }),
    );

    await within(dialog).findByText("1 chat could not be deleted");
    expect(dialog.textContent).toContain("A run is still in progress");
    expect(dialog.textContent).not.toContain("Root one");
    expect(selectedCount()).toBe("1 selected");

    mocks.remove.mockResolvedValue(undefined);
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(screen.queryByTestId("thread-bulk-delete-dialog")).toBeNull(),
    );
    // Deleted in sidebar order (the folder's chat first), then only the
    // failed one again.
    expect(mocks.remove.mock.calls.map(([id]) => id)).toEqual([
      "w1",
      "r1",
      "w1",
    ]);
  });

  test("Delete is not offered without threads:delete", async () => {
    renderSidebar({ permissions: ["threads:read", "threads:write"] });
    await startSelecting();
    expect(screen.queryByTestId("chat-selection-delete")).toBeNull();
    expect(screen.getByTestId("chat-selection-archive")).not.toBeNull();
  });

  test("Clean up opens the clean-up dialog with the selection, or with everything", async () => {
    renderSidebar();
    await startSelecting();
    const cleanupButton = screen.getByTestId("chat-selection-cleanup");
    expect(cleanupButton.textContent).toBe("Clean up all…");
    fireEvent.click(cleanupButton);
    expect((await screen.findByTestId("cleanup-dialog-stub")).textContent).toBe(
      "all",
    );
    expect(mocks.cleanupProps.at(-1)?.threadIds).toBeNull();
  });

  test("Clean up passes the selected ids", async () => {
    renderSidebar();
    await startSelecting();
    fireEvent.click(checkbox("Root three"));
    fireEvent.click(checkbox("Work two"));
    const cleanupButton = screen.getByTestId("chat-selection-cleanup");
    expect(cleanupButton.textContent).toBe("Clean up…");
    fireEvent.click(cleanupButton);
    const stub = await screen.findByTestId("cleanup-dialog-stub");
    expect(stub.textContent?.split(",").sort()).toEqual(["r3", "w2"]);
  });
});
