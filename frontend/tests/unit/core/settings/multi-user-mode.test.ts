import { beforeEach, describe, expect, rs, test } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
  getCsrfHeaders: () => ({ "X-CSRF-Token": "test-token" }),
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import { getMultiUserMode, setMultiUserMode } from "@/core/settings/multi-user-mode";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("getMultiUserMode", () => {
  test("returns true when the server reports isolation on", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, { multi_user_mode: true }));
    expect(await getMultiUserMode()).toBe(true);
  });

  test("returns false when the server reports the shared workspace", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, { multi_user_mode: false }));
    expect(await getMultiUserMode()).toBe(false);
  });

  test("defaults to isolated (true) on an unexpected payload", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, { unexpected: 1 }));
    expect(await getMultiUserMode()).toBe(true);
  });

  test("throws on a non-ok response", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(500, { detail: "boom" }));
    await expect(getMultiUserMode()).rejects.toThrow(/multi-user mode/i);
  });
});

describe("setMultiUserMode", () => {
  test("PUTs the enabled flag with CSRF headers and returns the persisted value", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, { multi_user_mode: false }));
    const result = await setMultiUserMode(false);
    expect(result).toBe(false);

    expect(mockedFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockedFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/settings/multi-user-mode");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ enabled: false });
    expect(init.headers).toMatchObject({ "X-CSRF-Token": "test-token" });
  });

  test("throws on a non-ok response", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(403, { detail: "nope" }));
    await expect(setMultiUserMode(false)).rejects.toThrow(/multi-user mode/i);
  });
});
