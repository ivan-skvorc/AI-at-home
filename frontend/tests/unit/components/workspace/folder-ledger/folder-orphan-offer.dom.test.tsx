import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { toast } from "sonner";

import { FolderOrphanOfferHost } from "@/components/workspace/folder-ledger/folder-orphan-offer";
import { notifyThreadsDeleted } from "@/core/folder-ledger/events";
import { I18nProvider } from "@/core/i18n/context";

rs.mock("sonner", () => ({ toast: { success: rs.fn(), error: rs.fn() } }));

type Call = { method: string; url: string; body: unknown };

function orphan(name: string, extra: Record<string, unknown> = {}) {
  return {
    id: `id-${name}`,
    path: `/mnt/projects/${name}`,
    name,
    mount_path: "/mnt/projects",
    created_by_thread_id: "t1",
    created_attribution: "observed_create",
    last_at: "2026-11-12T09:00:00Z",
    writes: 2,
    edits: 3,
    deletable: true,
    reason: null,
    ...extra,
  };
}

const ORPHANS = [
  orphan("acme"),
  orphan("data"),
  orphan("legacy", {
    created_attribution: "preexisting",
    deletable: false,
    reason: "preexisting",
  }),
];

let calls: Call[];
let respond: (call: Call) => Response;

beforeEach(() => {
  calls = [];
  respond = (call) => {
    if (call.url.endsWith("/api/folder-ledger/orphans")) {
      return Response.json({ available: true, orphans: ORPHANS });
    }
    if (call.method === "DELETE") {
      return Response.json({ deleted: true });
    }
    if (call.url.endsWith("/dismiss")) {
      return Response.json({ dismissed: true });
    }
    return new Response(null, { status: 404 });
  };
  rs.stubGlobal(
    "fetch",
    rs.fn(async (url: string, init?: RequestInit) => {
      const call = {
        method: init?.method ?? "GET",
        url,
        body:
          typeof init?.body === "string"
            ? (JSON.parse(init.body) as unknown)
            : null,
      };
      calls.push(call);
      return respond(call);
    }),
  );
});

afterEach(() => {
  cleanup();
  rs.unstubAllGlobals();
  rs.clearAllMocks();
});

function renderHost() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <I18nProvider initialLocale="en-US">
      <QueryClientProvider client={client}>
        <FolderOrphanOfferHost />
      </QueryClientProvider>
    </I18nProvider>,
  );
}

async function openOffer() {
  renderHost();
  notifyThreadsDeleted(["t1", "sidecar-1"]);
  notifyThreadsDeleted(["t2", "t1"]);
  return screen.findByRole("dialog");
}

function writes(method: string) {
  return calls.filter((call) => call.method === method);
}

describe("folder orphan offer", () => {
  it("asks once for a burst of deletions and pre-selects nothing", async () => {
    const dialog = await openOffer();

    const lookups = calls.filter((call) => call.url.endsWith("/orphans"));
    expect(lookups).toHaveLength(1);
    expect(lookups[0]?.body).toEqual({
      thread_ids: ["t1", "sidecar-1", "t2"],
    });
    expect(
      within(dialog).getByText("3 shared folders are no longer used"),
    ).not.toBeNull();

    const boxes = within(dialog).getAllByRole("checkbox");
    expect(boxes.map((box) => box.getAttribute("aria-label"))).toEqual([
      "Delete acme",
      "Delete data",
    ]);
    for (const box of boxes) {
      expect((box as HTMLInputElement).checked).toBe(false);
    }
    // Not deletable from here: listed with the reason, with nothing to tick.
    expect(
      within(dialog).queryByRole("checkbox", { name: "Delete legacy" }),
    ).toBeNull();
    expect(within(dialog).getByText("legacy")).not.toBeNull();
    expect(
      within(dialog).getByText(
        "Existed before a conversation used it, so it is never deleted from here.",
      ),
    ).not.toBeNull();
    const deleteButton = within(dialog).getByRole("button", {
      name: "Delete 0 folders",
    });
    expect((deleteButton as HTMLButtonElement).disabled).toBe(true);
    // The safe choice holds focus, so Enter deletes nothing.
    expect(document.activeElement).toBe(
      within(dialog).getByRole("button", { name: "Keep" }),
    );
  });

  it("deletes only the ticked folders, once each, and reports a failure on its row", async () => {
    respond = (call) => {
      if (call.url.endsWith("/orphans")) {
        return Response.json({ available: true, orphans: ORPHANS });
      }
      if (call.method === "DELETE" && call.url.includes("id-data")) {
        return Response.json(
          { detail: { code: "in_use", message: "in use" } },
          { status: 409 },
        );
      }
      return Response.json({ deleted: true });
    };
    const dialog = await openOffer();
    fireEvent.click(
      within(dialog).getByRole("checkbox", { name: "Delete acme" }),
    );
    fireEvent.click(
      within(dialog).getByRole("checkbox", { name: "Delete data" }),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Delete 2 folders" }),
    );

    await within(dialog).findByText(
      "A conversation uses it again, so it was not deleted.",
    );
    expect(writes("DELETE").map((call) => call.url)).toEqual([
      "/api/folder-ledger/folders/id-acme?confirm_name=acme",
      "/api/folder-ledger/folders/id-data?confirm_name=data",
    ]);
    expect(toast.success).toHaveBeenCalledWith("Deleted 1 folder.");
    // The failure stays on screen, nothing is retried, and the user decides.
    expect(screen.getByRole("dialog")).toBe(dialog);
    const acme = within(dialog)
      .getAllByTestId("folder-orphan-row")
      .find((row) => row.getAttribute("data-folder-id") === "id-acme")!;
    expect(within(acme).getByText("Deleted")).not.toBeNull();
    expect(
      within(dialog).getByRole("checkbox", { name: "Delete acme" }),
    ).toHaveProperty("disabled", true);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(writes("DELETE")).toHaveLength(2);
  });

  it("stops asking about every listed folder on dismiss", async () => {
    const dialog = await openOffer();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Don't ask again for these" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes("POST").map((call) => call.url)).toEqual([
      "/api/folder-ledger/orphans",
      "/api/folder-ledger/folders/id-acme/dismiss",
      "/api/folder-ledger/folders/id-data/dismiss",
      "/api/folder-ledger/folders/id-legacy/dismiss",
    ]);
    expect(writes("DELETE")).toHaveLength(0);
  });

  it("keeps everything when the user chooses Keep", async () => {
    const dialog = await openOffer();
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls).toHaveLength(1);
  });

  it("offers nothing when the deployment does not track folders", async () => {
    respond = () => Response.json({ available: false, orphans: [] });
    renderHost();
    notifyThreadsDeleted(["t1"]);
    await waitFor(() => expect(calls).toHaveLength(1));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
