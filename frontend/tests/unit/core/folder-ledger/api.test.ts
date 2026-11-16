import { afterEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import {
  deleteLedgerFolder,
  fetchOrphanFolders,
  FolderLedgerRequestError,
  MAX_ORPHAN_THREAD_IDS,
  parseFolderDetail,
  parseOrphanFolders,
  parseThreadFolders,
} from "@/core/folder-ledger/api";

afterEach(() => {
  rs.unstubAllGlobals();
});

const FOLDER = {
  id: "a".repeat(32),
  path: "/mnt/projects/acme",
  name: "acme",
  mount_path: "/mnt/projects",
  kind: "dir",
  role: "created",
  created_here: true,
  created_attribution: "observed_create",
  first_at: "2026-11-10T09:00:00Z",
  last_at: "2026-11-12T09:00:00Z",
  writes: 3,
  edits: 4,
  shell_ops: 0,
  other_live_threads: 2,
  host_visible: true,
};

function orphan(id: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    path: `/mnt/projects/${id}`,
    name: id,
    mount_path: "/mnt/projects",
    created_by_thread_id: null,
    created_attribution: "observed_create",
    last_at: null,
    writes: 1,
    edits: 0,
    deletable: true,
    reason: null,
    ...extra,
  };
}

describe("folder-ledger parsers", () => {
  it("keeps valid folders, drops malformed and duplicate ones", () => {
    const parsed = parseThreadFolders({
      available: true,
      folders: [
        FOLDER,
        { ...FOLDER, name: "dupe" },
        { ...FOLDER, id: "b".repeat(32), name: 3 },
        null,
      ],
    });
    expect(parsed?.folders).toHaveLength(1);
    expect(parsed?.folders[0]).toMatchObject({
      name: "acme",
      role: "created",
      other_live_threads: 2,
    });
  });

  it("reads an unknown attribution as pre-existing, never as created", () => {
    const parsed = parseThreadFolders({
      available: true,
      folders: [{ ...FOLDER, created_attribution: "guess" }],
    });
    expect(parsed?.folders[0]?.created_attribution).toBe("preexisting");
  });

  it("reports an untracked deployment and rejects a non-listing body", () => {
    expect(parseThreadFolders({ available: false, folders: [FOLDER] })).toEqual(
      { available: false, folders: [] },
    );
    expect(parseThreadFolders({ folders: [] })).toBeNull();
    expect(parseOrphanFolders("nope")).toBeNull();
  });

  it("never lets a body make a folder deletable without the flag", () => {
    const parsed = parseOrphanFolders({
      available: true,
      orphans: [
        orphan("kept", { deletable: "yes", reason: "something-new" }),
        orphan("gone"),
      ],
    });
    expect(parsed?.orphans.map((item) => [item.id, item.deletable])).toEqual([
      ["kept", false],
      ["gone", true],
    ]);
    expect(parsed?.orphans[0]?.reason).toBe("unknown");
  });

  it("parses a folder detail with its conversations and edit log", () => {
    const detail = parseFolderDetail({
      folder: { ...FOLDER, role: null },
      threads: [
        {
          thread_id: "t1",
          own: true,
          title: "Plan",
          role: "created",
          first_at: null,
          last_at: null,
          deleted: false,
        },
        { thread_id: "t2", role: "bogus" },
      ],
      events: [
        {
          thread_id: "t1",
          run_id: "r1",
          op: "edit",
          rel_path: "acme/a.md",
          ts: "2026-11-12T09:00:00Z",
        },
        { thread_id: "t1", op: "delete", rel_path: "acme/b.md" },
      ],
    });
    expect(detail?.folder.role).toBeNull();
    expect(detail?.threads.map((thread) => thread.thread_id)).toEqual(["t1"]);
    expect(detail?.events).toEqual([
      {
        thread_id: "t1",
        run_id: "r1",
        op: "edit",
        rel_path: "acme/a.md",
        ts: "2026-11-12T09:00:00Z",
      },
    ]);
  });
});

describe("fetchOrphanFolders", () => {
  it("splits long id lists into accepted chunks and merges the answers", async () => {
    const bodies: string[][] = [];
    const fetchMock = rs.fn(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(
        typeof init?.body === "string" ? init.body : "{}",
      ) as { thread_ids: string[] };
      bodies.push(body.thread_ids);
      return Response.json({
        available: true,
        // The same folder reached from both chunks is offered once.
        orphans: [orphan("shared"), orphan(`only-${bodies.length}`)],
      });
    });
    rs.stubGlobal("fetch", fetchMock);
    const ids = Array.from(
      { length: MAX_ORPHAN_THREAD_IDS + 3 },
      (_, index) => `t${index}`,
    );

    const result = await fetchOrphanFolders([...ids, "t0", ""]);

    expect(bodies.map((chunk) => chunk.length)).toEqual([
      MAX_ORPHAN_THREAD_IDS,
      3,
    ]);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/backend/api/folder-ledger/orphans",
    );
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("POST");
    expect(result.orphans.map((item) => item.id)).toEqual([
      "shared",
      "only-1",
      "only-2",
    ]);
  });

  it("asks nothing for an empty list", async () => {
    const fetchMock = rs.fn();
    rs.stubGlobal("fetch", fetchMock);
    await expect(fetchOrphanFolders([])).resolves.toEqual({
      available: true,
      orphans: [],
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("deleteLedgerFolder", () => {
  it("sends the folder name as confirm_name and surfaces a structured refusal", async () => {
    const fetchMock = rs.fn(async () =>
      Response.json(
        { detail: { code: "in_use", message: "A conversation uses it." } },
        { status: 409 },
      ),
    );
    rs.stubGlobal("fetch", fetchMock);

    const error = await deleteLedgerFolder("f".repeat(32), "acme site").catch(
      (caught: unknown) => caught,
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe(
      `/backend/api/folder-ledger/folders/${"f".repeat(32)}?confirm_name=acme%20site`,
    );
    expect(init.method).toBe("DELETE");
    expect(error).toBeInstanceOf(FolderLedgerRequestError);
    expect(error).toMatchObject({
      status: 409,
      code: "in_use",
      message: "A conversation uses it.",
    });
  });
});
