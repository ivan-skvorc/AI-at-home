import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import { ThreadSharedFolders } from "@/components/workspace/thread-files/thread-shared-folders";
import { I18nProvider } from "@/core/i18n/context";

const THREAD = "t1";
const RECENT = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();

function folder(name: string, extra: Record<string, unknown> = {}) {
  return {
    id: `id-${name}`,
    path: `/mnt/projects/${name}`,
    name,
    mount_path: "/mnt/projects",
    kind: "dir",
    role: "created",
    created_here: true,
    created_attribution: "observed_create",
    first_at: RECENT,
    last_at: RECENT,
    writes: 2,
    edits: 3,
    shell_ops: 0,
    other_live_threads: 0,
    host_visible: true,
    ...extra,
  };
}

function stubLedger(routes: Record<string, unknown>) {
  const fetchMock = rs.fn(async (url: string) => {
    const path = url.replace(/^.*\/api\/folder-ledger/, "");
    return path in routes
      ? Response.json(routes[path])
      : new Response(null, { status: 404 });
  });
  rs.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <I18nProvider initialLocale="en-US">
      <QueryClientProvider client={client}>
        <ThreadSharedFolders threadId={THREAD} isRunning={false} />
      </QueryClientProvider>
    </I18nProvider>,
  );
}

afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
});

describe("Shared folders in the Files tab", () => {
  it("says the chat's own folder goes with it and lists the shared ones it used", async () => {
    stubLedger({
      [`/threads/${THREAD}/folders`]: {
        available: true,
        folders: [
          folder("acme", { other_live_threads: 2 }),
          folder("reports", {
            role: "edited",
            created_here: false,
            created_attribution: "preexisting",
            host_visible: false,
          }),
        ],
      },
    });
    renderSection();

    expect(
      screen.getByText(
        "This chat's own folder, /mnt/user-data, is deleted together with the chat.",
      ),
    ).not.toBeNull();
    const section = await screen.findByRole("region", {
      name: "Shared folders",
    });
    const acme = within(section).getByRole("button", {
      name: "Show details of acme",
    });
    expect(within(acme).getByText("Created here")).not.toBeNull();
    expect(acme.textContent).toContain("Also used by 2 other chats");
    expect(acme.textContent).toContain("Last edit about 2 hours ago");
    const reports = within(section).getByRole("button", {
      name: "Show details of reports",
    });
    expect(within(reports).getByText("Edited here")).not.toBeNull();
    expect(reports.textContent).toContain("Only this chat uses it");
    expect(reports.textContent).toContain("Managed outside this server");
  });

  it("opens the edit log and the conversations involved", async () => {
    stubLedger({
      [`/threads/${THREAD}/folders`]: {
        available: true,
        folders: [folder("acme")],
      },
      "/folders/id-acme": {
        folder: { ...folder("acme"), role: null, other_live_threads: 1 },
        threads: [
          {
            thread_id: THREAD,
            own: true,
            title: "Launch plan",
            role: "created",
            first_at: RECENT,
            last_at: RECENT,
            deleted: false,
          },
          {
            thread_id: "other-0123456789abcdef",
            own: false,
            title: null,
            role: "edited",
            first_at: RECENT,
            last_at: RECENT,
            deleted: false,
          },
          {
            thread_id: "t-old",
            own: true,
            title: "Old draft",
            role: "inherited",
            first_at: RECENT,
            last_at: RECENT,
            deleted: true,
          },
        ],
        events: [
          {
            thread_id: "other-0123456789abcdef",
            run_id: null,
            op: "edit",
            rel_path: "acme/notes.md",
            ts: RECENT,
          },
          {
            thread_id: THREAD,
            run_id: "r1",
            op: "write",
            rel_path: "acme/index.html",
            ts: RECENT,
          },
        ],
      },
    });
    renderSection();
    fireEvent.click(
      await screen.findByRole("button", { name: "Show details of acme" }),
    );

    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("A conversation created it.");
    expect(within(dialog).getByText("This chat")).not.toBeNull();
    expect(
      within(dialog).getByText("Another user's conversation"),
    ).not.toBeNull();
    expect(within(dialog).getByText("Old draft")).not.toBeNull();
    expect(within(dialog).getByText("Deleted")).not.toBeNull();
    const log = within(dialog).getByRole("list", { name: "Edit log" });
    const entries = within(log).getAllByRole("listitem");
    expect(entries.map((entry) => entry.textContent)).toEqual([
      expect.stringContaining("Editedacme/notes.md"),
      expect.stringContaining("Wroteacme/index.html"),
    ]);
    expect(entries[0]?.textContent).toContain("Another user's conversation");
  });

  for (const [name, body] of [
    [
      "the deployment does not track folders",
      { available: false, folders: [] },
    ],
    ["the chat used no shared folder", { available: true, folders: [] }],
  ] as const) {
    it(`stays hidden when ${name}`, async () => {
      const fetchMock = stubLedger({ [`/threads/${THREAD}/folders`]: body });
      renderSection();
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect(
        screen.queryByRole("region", { name: "Shared folders" }),
      ).toBeNull();
      expect(screen.queryByRole("alert")).toBeNull();
      // The own-folder line is shown either way.
      expect(screen.getByTestId("thread-own-folder-note")).not.toBeNull();
    });
  }
});
