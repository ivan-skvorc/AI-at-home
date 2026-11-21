import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import { fetchAgentsApiEnabled } from "@/core/agents/api";
import { fetch as fetcher } from "@/core/api/fetcher";
import {
  type FeaturesResponse,
  selectBrowserControlEnabled,
  selectKnowledgeBaseFeature,
  selectMcpTasksEnabled,
} from "@/core/features/api";

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

describe("fetchAgentsApiEnabled", () => {
  test("returns true when backend reports agents_api enabled", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { agents_api: { enabled: true } }),
    );
    await expect(fetchAgentsApiEnabled()).resolves.toBe(true);
    expect(mockedFetch).toHaveBeenCalledWith("/api/features");
  });

  test("returns false when backend reports agents_api disabled", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { agents_api: { enabled: false } }),
    );
    await expect(fetchAgentsApiEnabled()).resolves.toBe(false);
  });

  test("throws when the features request fails", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(500, {}));
    await expect(fetchAgentsApiEnabled()).rejects.toThrow();
  });
});

// The feature hooks share one `/api/features` query (core/features/query.ts)
// and read their block with these selectors; the request itself, including
// its failure, is covered by the fetchAgentsApiEnabled tests above.
const features = (body: unknown) => body as FeaturesResponse;

describe("selectBrowserControlEnabled", () => {
  test("returns true when backend reports browser_control enabled", () => {
    expect(
      selectBrowserControlEnabled(
        features({
          agents_api: { enabled: true },
          browser_control: { enabled: true },
        }),
      ),
    ).toBe(true);
  });

  test("returns false when browser_control is disabled or omitted", () => {
    expect(
      selectBrowserControlEnabled(
        features({
          agents_api: { enabled: true },
          browser_control: { enabled: false },
        }),
      ),
    ).toBe(false);
    expect(
      selectBrowserControlEnabled(features({ agents_api: { enabled: true } })),
    ).toBe(false);
  });
});

describe("selectMcpTasksEnabled", () => {
  test("returns true when backend reports mcp_tasks enabled", () => {
    expect(
      selectMcpTasksEnabled(
        features({
          agents_api: { enabled: true },
          mcp_tasks: { enabled: true },
        }),
      ),
    ).toBe(true);
  });

  test("returns false when mcp_tasks is disabled or omitted", () => {
    expect(
      selectMcpTasksEnabled(
        features({
          agents_api: { enabled: true },
          mcp_tasks: { enabled: false },
        }),
      ),
    ).toBe(false);
    expect(
      selectMcpTasksEnabled(features({ agents_api: { enabled: true } })),
    ).toBe(false);
  });
});

describe("selectKnowledgeBaseFeature", () => {
  test("reads the knowledge-base retrieval-scope flags", () => {
    expect(
      selectKnowledgeBaseFeature(
        features({
          agents_api: { enabled: true },
          knowledge_base: {
            scope_selection_enabled: true,
          },
        }),
      ),
    ).toEqual({
      scopeSelectionEnabled: true,
    });
  });

  test("defaults to disabled when omitted", () => {
    expect(
      selectKnowledgeBaseFeature(features({ agents_api: { enabled: true } })),
    ).toEqual({
      scopeSelectionEnabled: false,
    });
  });
});
