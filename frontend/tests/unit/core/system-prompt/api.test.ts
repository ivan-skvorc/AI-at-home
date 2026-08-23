/**
 * Tests for the system-prompt API client.
 *
 * The editor has to tell three failures apart: 403 (the caller is not an
 * admin, so the page shows an explainer instead of an editor), 422 (the
 * template is invalid, and the backend's detail names the offending
 * placeholder — that string must reach the toast verbatim), and everything
 * else. These pin that classification plus the request shapes.
 */
import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  SystemPromptError,
  loadSystemPrompt,
  loadSystemPromptPreview,
  resetSystemPrompt,
  saveSystemPrompt,
} from "@/core/system-prompt/api";

const mockedFetch = rs.mocked(fetcher);

const PROMPT = {
  content: "You are {agent_name}.",
  default_content: "<role>You are {agent_name}</role>",
  is_custom: true,
  placeholders: ["agent_name", "skills_section"],
  missing_placeholders: ["skills_section"],
  max_length: 200000,
};

/** First argument of a recorded fetch call; the client always passes a string URL. */
function requestedUrl(callIndex: number): string {
  const input = mockedFetch.mock.calls[callIndex]![0];
  expect(typeof input).toBe("string");
  return input as string;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("loadSystemPrompt", () => {
  test("returns the payload on 200", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, PROMPT));
    await expect(loadSystemPrompt()).resolves.toEqual(PROMPT);
  });

  test("carries the 403 status so the page can explain the admin gate", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(403, {
        detail: "Admin privileges required to manage the system prompt.",
      }),
    );
    await expect(loadSystemPrompt()).rejects.toMatchObject({
      name: "SystemPromptError",
      status: 403,
    });
  });
});

describe("saveSystemPrompt", () => {
  test("PUTs the content as JSON", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, PROMPT));
    await saveSystemPrompt("You are {agent_name}.");

    const [, init] = mockedFetch.mock.calls[0]!;
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(init?.body as string)).toEqual({
      content: "You are {agent_name}.",
    });
  });

  test("surfaces the backend detail for an invalid template", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(422, {
        detail: "Unknown placeholder `{nope}`. Available placeholders: soul.",
      }),
    );
    await expect(saveSystemPrompt("{nope}")).rejects.toMatchObject({
      status: 422,
      detail: "Unknown placeholder `{nope}`. Available placeholders: soul.",
    });
  });

  test("falls back to a generated message when there is no detail", async () => {
    mockedFetch.mockResolvedValueOnce(new Response("", { status: 500 }));
    const error = await saveSystemPrompt("x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(SystemPromptError);
    expect((error as SystemPromptError).detail).toBeNull();
    expect((error as SystemPromptError).message).toContain(
      "Failed to save the system prompt",
    );
  });
});

describe("resetSystemPrompt", () => {
  test("DELETEs and returns the reverted state", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { ...PROMPT, is_custom: false }),
    );
    await expect(resetSystemPrompt()).resolves.toMatchObject({
      is_custom: false,
    });
    expect(mockedFetch.mock.calls[0]![1]?.method).toBe("DELETE");
  });
});

describe("loadSystemPromptPreview", () => {
  test("passes the subagent flag as a query parameter", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { rendered: "hello", is_custom: false }),
    );
    await loadSystemPromptPreview({ subagentEnabled: false });
    expect(requestedUrl(0)).toContain("subagent_enabled=false");
  });

  test("defaults the subagent flag to true", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { rendered: "hello", is_custom: false }),
    );
    await loadSystemPromptPreview();
    expect(requestedUrl(0)).toContain("subagent_enabled=true");
  });
});
