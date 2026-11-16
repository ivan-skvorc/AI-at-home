import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
} from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { toast } from "sonner";

import {
  ThreadDeleteDialogProvider,
  useThreadDeleteDialog,
} from "@/components/workspace/thread-delete-dialog";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";

const { deleteThread } = rs.hoisted(() => ({ deleteThread: rs.fn() }));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ replace: rs.fn() }),
  usePathname: () => "/workspace/chats/new",
  useParams: () => ({}),
}));
rs.mock("sonner", () => ({ toast: { error: rs.fn() } }));
rs.mock("@/components/workspace/chats/use-thread-chat", () => ({
  resetThreadChatAfterDelete: rs.fn(),
}));
rs.mock("@/core/threads/hooks", () => ({
  useDeleteThread: () => useMutation({ mutationFn: deleteThread }),
}));

function Trigger() {
  const requestDelete = useThreadDeleteDialog();
  return (
    <button
      onClick={() =>
        requestDelete({
          thread: {
            thread_id: "thread-1",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
            metadata: {},
            status: "idle",
            values: { title: "Keep me", messages: [] },
            interrupts: {},
          },
        })
      }
    >
      Open deletion
    </button>
  );
}

// The folder ledger's answer for the conversation being deleted.
let ledger: unknown = { available: false, folders: [] };

beforeEach(() => {
  ledger = { available: false, folders: [] };
  rs.stubGlobal(
    "fetch",
    rs.fn(async (url: string) =>
      url.includes("/api/folder-ledger/threads/thread-1/folders")
        ? Response.json(ledger)
        : new Response(null, { status: 404 }),
    ),
  );
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  rs.unstubAllGlobals();
});

function renderDialog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <QueryClientProvider client={client}>
        <ThreadDeleteDialogProvider>
          <Trigger />
        </ThreadDeleteDialogProvider>
      </QueryClientProvider>
    </I18nProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Open deletion" }));
  return client;
}

describe("thread deletion confirmation copy", () => {
  it("says the own folder goes and names the shared folders that are kept", async () => {
    ledger = {
      available: true,
      folders: ["acme", "data", "logs", "notes"].map((name) => ({
        id: `id-${name}`,
        path: `/mnt/projects/${name}`,
        name,
        mount_path: "/mnt/projects",
        kind: "dir",
        role: "edited",
        created_here: false,
        created_attribution: "observed_create",
        first_at: null,
        last_at: null,
        writes: 1,
        edits: 0,
        shell_ops: 0,
        other_live_threads: 0,
        host_visible: true,
      })),
    };
    const client = renderDialog();
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain(
      "This deletes the conversation and its own folder (/mnt/user-data)",
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("thread-delete-shared-folders").textContent,
      ).toBe(
        "It used these shared folders, which are kept: acme, data, logs and 1 more. If no other conversation still uses one, you will be offered to delete it.",
      ),
    );
    client.clear();
  });

  it("promises no offer where folders are not tracked", async () => {
    const client = renderDialog();
    await screen.findByRole("dialog");
    await waitFor(() =>
      expect(
        screen.getByTestId("thread-delete-shared-folders").textContent,
      ).toBe("Shared folders it used outside /mnt/user-data are kept."),
    );
    client.clear();
  });
});

describe("thread deletion failure feedback", () => {
  for (const [name, error, message] of [
    ["specific error", new Error("Permission denied"), "Permission denied"],
    ["empty error", new Error(""), "Failed to delete chat. Please try again."],
    ["non-Error rejection", null, "Failed to delete chat. Please try again."],
  ] as const) {
    it(`reports ${name} and restores Cancel focus`, async () => {
      deleteThread.mockRejectedValueOnce(error);
      const log = rs
        .spyOn(console, "error")
        .mockImplementation(() => undefined);
      const client = new QueryClient({
        defaultOptions: { mutations: { retry: false } },
      });
      render(
        <I18nProvider initialLocale={DEFAULT_LOCALE}>
          <QueryClientProvider client={client}>
            <ThreadDeleteDialogProvider>
              <Trigger />
            </ThreadDeleteDialogProvider>
          </QueryClientProvider>
        </I18nProvider>,
      );
      fireEvent.click(screen.getByRole("button", { name: "Open deletion" }));
      const cancel = await screen.findByRole("button", {
        name: "Cancel",
      });
      const del = screen.getByRole("button", { name: "Delete" });
      del.focus();
      fireEvent.click(del);
      await waitFor(() => expect(toast.error).toHaveBeenCalledWith(message));
      await waitFor(() => expect(document.activeElement).toBe(cancel));
      expect(log).toHaveBeenCalledWith("Failed to delete chat:", error);
      expect(screen.getByRole("dialog")).not.toBeNull();
      fireEvent.click(cancel);
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      client.clear();
    });
  }
});
