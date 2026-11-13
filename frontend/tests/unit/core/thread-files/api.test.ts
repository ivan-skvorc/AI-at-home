import { afterEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import {
  fetchThreadFiles,
  parseThreadFileListing,
  ThreadFilesRequestError,
} from "@/core/thread-files/api";

const ROOT = "/mnt/user-data";

afterEach(() => {
  rs.unstubAllGlobals();
});

describe("parseThreadFileListing", () => {
  it("keeps valid entries and drops malformed or duplicate ones", () => {
    const listing = parseThreadFileListing({
      path: ROOT,
      exists: true,
      entries: [
        {
          name: "outputs",
          path: `${ROOT}/outputs`,
          kind: "directory",
          size: null,
          modified_at: "2026-11-13T10:00:00Z",
        },
        {
          name: "a.txt",
          path: `${ROOT}/a.txt`,
          kind: "file",
          size: 12,
          modified_at: "2026-11-13T10:00:00Z",
        },
        // Duplicate path.
        { name: "a.txt", path: `${ROOT}/a.txt`, kind: "file" },
        // The path must be the listed directory plus the name.
        { name: "b.txt", path: "/mnt/user-data/../etc/b.txt", kind: "file" },
        { name: "c.txt", path: `${ROOT}/other/c.txt`, kind: "file" },
        { name: "..", path: `${ROOT}/..`, kind: "directory" },
        { name: "", path: `${ROOT}/`, kind: "file" },
        { name: "d.txt", path: `${ROOT}/d.txt`, kind: 3 },
        { name: 4, path: `${ROOT}/4`, kind: "file" },
        "e.txt",
        null,
      ],
      truncated: false,
      total: 2,
    });

    expect(listing?.entries.map((entry) => entry.path)).toEqual([
      `${ROOT}/outputs`,
      `${ROOT}/a.txt`,
    ]);
    expect(listing?.entries[1]).toEqual({
      name: "a.txt",
      path: `${ROOT}/a.txt`,
      kind: "file",
      size: 12,
      modified_at: "2026-11-13T10:00:00Z",
    });
  });

  it("narrows optional fields instead of trusting them", () => {
    const listing = parseThreadFileListing({
      path: `${ROOT}/workspace`,
      entries: [
        {
          name: "socket",
          path: `${ROOT}/workspace/socket`,
          kind: "fifo",
          size: -1,
          modified_at: "not a date",
        },
        {
          name: "big.bin",
          path: `${ROOT}/workspace/big.bin`,
          kind: "file",
          size: "12",
        },
      ],
      truncated: "yes",
      total: "many",
    });

    expect(listing).toEqual({
      path: `${ROOT}/workspace`,
      exists: true,
      entries: [
        {
          name: "socket",
          path: `${ROOT}/workspace/socket`,
          kind: "other",
          size: null,
          modified_at: null,
        },
        {
          name: "big.bin",
          path: `${ROOT}/workspace/big.bin`,
          kind: "file",
          size: null,
          modified_at: null,
        },
      ],
      truncated: false,
      total: 2,
    });
  });

  it("keeps the truncation total and never reports fewer than it shows", () => {
    const entry = { name: "a", path: `${ROOT}/a`, kind: "file", size: 1 };
    expect(
      parseThreadFileListing({
        path: ROOT,
        exists: true,
        entries: [entry],
        truncated: true,
        total: 700.5,
      }),
    ).toMatchObject({ truncated: true, total: 700 });
    expect(
      parseThreadFileListing({ path: ROOT, entries: [entry], total: 0 })?.total,
    ).toBe(1);
  });

  it("reports a missing root", () => {
    expect(
      parseThreadFileListing({
        path: ROOT,
        exists: false,
        entries: [],
        truncated: false,
        total: 0,
      }),
    ).toEqual({
      path: ROOT,
      exists: false,
      entries: [],
      truncated: false,
      total: 0,
    });
  });

  it.each([
    null,
    "listing",
    // it.each spreads an array case into arguments, so wrap the array body.
    [[]],
    { path: ROOT },
    { path: ROOT, entries: {} },
    { path: "/etc", entries: [] },
    { path: "/mnt/user-data-other", entries: [] },
    { path: `${ROOT}/../etc`, entries: [] },
  ])("rejects a body that is not a listing: %j", (body) => {
    expect(parseThreadFileListing(body)).toBeNull();
  });
});

describe("fetchThreadFiles", () => {
  it("encodes the thread id and path, and passes the abort signal", async () => {
    const fetchMock = rs.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(
          JSON.stringify({
            path: `${ROOT}/work space`,
            exists: true,
            entries: [],
            truncated: false,
            total: 0,
          }),
          { status: 200 },
        ),
    );
    rs.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    const listing = await fetchThreadFiles({
      threadId: "thread/1",
      path: `${ROOT}/work space`,
      signal: controller.signal,
    });

    expect(listing.path).toBe(`${ROOT}/work space`);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe(
      "/backend/api/threads/thread%2F1/files?path=%2Fmnt%2Fuser-data%2Fwork%20space",
    );
    expect(init).toMatchObject({
      signal: controller.signal,
      credentials: "include",
    });
  });

  it("throws the Gateway detail with the status", async () => {
    rs.stubGlobal(
      "fetch",
      rs.fn(
        async () =>
          new Response(JSON.stringify({ detail: "Directory not found" }), {
            status: 404,
          }),
      ),
    );

    const error: unknown = await fetchThreadFiles({ threadId: "t" }).catch(
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(ThreadFilesRequestError);
    expect(error).toMatchObject({
      status: 404,
      message: "Directory not found",
    });
  });

  it("keeps the status when the error body is not JSON", async () => {
    rs.stubGlobal(
      "fetch",
      rs.fn(async () => new Response("<html>", { status: 502 })),
    );

    await expect(fetchThreadFiles({ threadId: "t" })).rejects.toMatchObject({
      status: 502,
      message: "HTTP 502",
    });
  });

  it("rejects a successful response that is not a listing", async () => {
    rs.stubGlobal(
      "fetch",
      rs.fn(async () => new Response(JSON.stringify({ items: [] }))),
    );

    await expect(fetchThreadFiles({ threadId: "t" })).rejects.toThrow(
      "malformed file listing",
    );
  });
});
