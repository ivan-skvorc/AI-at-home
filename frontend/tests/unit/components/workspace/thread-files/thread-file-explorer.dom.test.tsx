import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
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
import { useState } from "react";

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: null }),
}));

import { ThreadFileExplorer } from "@/components/workspace/thread-files/thread-file-explorer";
import { I18nProvider } from "@/core/i18n/context";
import { EMPTY_THREAD_FILE_TREE } from "@/core/thread-files/types";

const THREAD_ID = "thread-files-test";
const ROOT = "/mnt/user-data";
const OUTPUTS = `${ROOT}/outputs`;

type Handler = () => Response;

let handlers: Map<string, Handler>;
let requestedPaths: string[];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function listing(
  path: string,
  entries: [name: string, kind: string, size?: number][],
  extra: Record<string, unknown> = {},
) {
  return {
    path,
    exists: true,
    entries: entries.map(([name, kind, size]) => ({
      name,
      path: `${path}/${name}`,
      kind,
      size: size ?? null,
      modified_at: "2026-11-13T09:00:00Z",
    })),
    truncated: false,
    total: entries.length,
    ...extra,
  };
}

function serve(path: string, ...responses: Handler[]) {
  let call = 0;
  handlers.set(path, () => {
    const response = responses[Math.min(call, responses.length - 1)]!;
    call += 1;
    return response();
  });
}

function fetchCount(path: string) {
  return requestedPaths.filter((requested) => requested === path).length;
}

function Explorer({
  isRunning,
  onOpenFile,
}: {
  isRunning: boolean;
  onOpenFile: (path: string) => void;
}) {
  const [tree, setTree] = useState(EMPTY_THREAD_FILE_TREE);
  return (
    <ThreadFileExplorer
      threadId={THREAD_ID}
      isRunning={isRunning}
      tree={tree}
      onTreeChange={setTree}
      onOpenFile={onOpenFile}
    />
  );
}

function renderExplorer({ isRunning = false } = {}) {
  const onOpenFile = rs.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const ui = (running: boolean) => (
    <QueryClientProvider client={queryClient}>
      <I18nProvider initialLocale="en-US">
        <Explorer isRunning={running} onOpenFile={onOpenFile} />
      </I18nProvider>
    </QueryClientProvider>
  );
  const view = render(ui(isRunning));
  return {
    onOpenFile,
    setRunning: (running: boolean) => view.rerender(ui(running)),
  };
}

beforeEach(() => {
  handlers = new Map();
  requestedPaths = [];
  rs.stubGlobal(
    "fetch",
    rs.fn(async (input: RequestInfo | URL) => {
      const url = new URL(
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
        "http://localhost",
      );
      expect(url.pathname).toBe(`/backend/api/threads/${THREAD_ID}/files`);
      const path = url.searchParams.get("path") ?? "";
      requestedPaths.push(path);
      return handlers.get(path)?.() ?? json({ detail: "Not found" }, 404);
    }),
  );
  serve(ROOT, () =>
    json(
      listing(ROOT, [
        ["outputs", "directory"],
        ["workspace", "directory"],
        ["link", "symlink"],
        ["notes.md", "file", 2048],
      ]),
    ),
  );
  serve(OUTPUTS, () => json(listing(OUTPUTS, [["report.md", "file", 12]])));
});

afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
});

function treeItem(name: string) {
  return screen.findByRole("treeitem", { name });
}

describe("ThreadFileExplorer", () => {
  it("lists a directory only when it is expanded", async () => {
    renderExplorer();
    const outputs = await treeItem("outputs");
    expect(requestedPaths).toEqual([ROOT]);
    expect(outputs.getAttribute("aria-expanded")).toBe("false");
    expect(outputs.getAttribute("aria-level")).toBe("1");

    fireEvent.click(within(outputs).getByText("outputs"));

    const report = await treeItem("report.md");
    expect(outputs.getAttribute("aria-expanded")).toBe("true");
    expect(report.getAttribute("aria-level")).toBe("2");
    expect(requestedPaths).toEqual([ROOT, OUTPUTS]);
    // Links are never followed: no chevron state and no request.
    const link = await treeItem("link");
    expect(link.hasAttribute("aria-expanded")).toBe(false);
    fireEvent.click(within(link).getByText("link"));
    expect(requestedPaths).toEqual([ROOT, OUTPUTS]);
  });

  it("opens a file on click and offers its download", async () => {
    const { onOpenFile } = renderExplorer();
    const notes = await treeItem("notes.md");

    expect(within(notes).getByText("2.0 KiB")).toBeTruthy();
    const download = within(notes).getByRole("button", {
      name: "Download notes.md",
    });
    // The tree keeps one tab stop; the preview has the same download.
    expect(download.tabIndex).toBe(-1);

    fireEvent.click(within(notes).getByText("notes.md"));
    expect(onOpenFile).toHaveBeenCalledWith(`${ROOT}/notes.md`);
  });

  it("ends a truncated listing with the number of rows not shown", async () => {
    serve(ROOT, () =>
      json(
        listing(ROOT, [["a.txt", "file", 1]], {
          truncated: true,
          total: 501,
        }),
      ),
    );
    renderExplorer();

    expect(await screen.findByText("500 more not shown")).toBeTruthy();
  });

  it("shows the empty state for a root the sandbox has not created", async () => {
    serve(ROOT, () =>
      json({
        path: ROOT,
        exists: false,
        entries: [],
        truncated: false,
        total: 0,
      }),
    );
    renderExplorer();

    expect(await screen.findByText("No files yet")).toBeTruthy();
    expect(screen.queryByRole("tree")).toBeNull();
  });

  it("shows a failed listing with a retry, for the root and a folder", async () => {
    serve(
      ROOT,
      () => json({ detail: "boom" }, 500),
      () => json(listing(ROOT, [["outputs", "directory"]])),
    );
    serve(
      OUTPUTS,
      () => json({ detail: "Directory not found" }, 404),
      () => json(listing(OUTPUTS, [["report.md", "file", 12]])),
    );
    renderExplorer();

    expect(
      await screen.findByText("Could not load the files of this chat."),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    const outputs = await treeItem("outputs");
    fireEvent.click(within(outputs).getByText("outputs"));
    expect(
      await screen.findByText("This folder no longer exists."),
    ).toBeTruthy();
    fireEvent.click(within(outputs).getByRole("button", { name: "Retry" }));

    expect(await treeItem("report.md")).toBeTruthy();
    expect(fetchCount(OUTPUTS)).toBe(2);
  });

  it("moves one tab stop with the arrow, Home and End keys", async () => {
    const { onOpenFile } = renderExplorer();
    const outputs = await treeItem("outputs");
    const items = () => screen.getAllByRole("treeitem");
    expect(items().map((item) => item.tabIndex)).toEqual([0, -1, -1, -1]);

    act(() => outputs.focus());
    fireEvent.keyDown(outputs, { key: "ArrowDown" });
    expect(document.activeElement).toBe(await treeItem("workspace"));
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    const notes = await treeItem("notes.md");
    expect(document.activeElement).toBe(notes);
    await waitFor(() => expect(notes.tabIndex).toBe(0));
    expect(outputs.tabIndex).toBe(-1);
    fireEvent.keyDown(notes, { key: "Home" });
    expect(document.activeElement).toBe(outputs);

    // Right expands, then enters the folder; Left leaves, then collapses.
    fireEvent.keyDown(outputs, { key: "ArrowRight" });
    const report = await treeItem("report.md");
    expect(outputs.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(outputs, { key: "ArrowRight" });
    expect(document.activeElement).toBe(report);
    fireEvent.keyDown(report, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(outputs);
    fireEvent.keyDown(outputs, { key: "ArrowLeft" });
    await waitFor(() =>
      expect(outputs.getAttribute("aria-expanded")).toBe("false"),
    );
    expect(screen.queryByRole("treeitem", { name: "report.md" })).toBeNull();

    fireEvent.keyDown(outputs, { key: "End" });
    fireEvent.keyDown(document.activeElement!, { key: "Enter" });
    expect(onOpenFile).toHaveBeenCalledWith(`${ROOT}/notes.md`);
  });

  it("refetches the open listings on refresh and when a run ends", async () => {
    const { setRunning } = renderExplorer({ isRunning: true });
    const outputs = await treeItem("outputs");
    fireEvent.click(within(outputs).getByText("outputs"));
    await treeItem("report.md");

    fireEvent.click(screen.getByRole("button", { name: "Refresh files" }));
    await waitFor(() => expect(fetchCount(OUTPUTS)).toBe(2));
    expect(fetchCount(ROOT)).toBe(2);
    // A collapsed folder stays unlisted.
    expect(fetchCount(`${ROOT}/workspace`)).toBe(0);

    setRunning(false);
    await waitFor(() => expect(fetchCount(OUTPUTS)).toBe(3));
    expect(fetchCount(ROOT)).toBe(3);
  });
});
