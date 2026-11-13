import { expect, test, type Page, type Route } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

// Reported: a task started half an hour before the page was opened showed
// "Working… (1s)" and counted up from there, as if it had just begun.
const NOW = new Date("2026-11-13T10:00:00Z");
const RUN_ID = "00000000-0000-0000-0000-0000000000a1";
const STARTED_AT = new Date(NOW.getTime() - 30 * 60_000).toISOString();

test.use({ timezoneId: "UTC" });

async function openRunningChat(page: Page) {
  const joins: Route[] = [];
  await page.clock.install({ time: NOW });
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Long research",
        messages: [
          { type: "human", id: "human-long", content: "Research this" },
          {
            type: "ai",
            id: "ai-search",
            content: "",
            tool_calls: [
              {
                id: "call-search",
                name: "web_search",
                args: { query: "DeerFlow" },
              },
            ],
          },
          {
            type: "tool",
            id: "tool-search",
            name: "web_search",
            tool_call_id: "call-search",
            content: "[]",
          },
        ],
      },
    ],
  });
  const run = {
    run_id: RUN_ID,
    thread_id: MOCK_THREAD_ID,
    assistant_id: "lead_agent",
    status: "running",
    metadata: {},
    kwargs: {},
    created_at: STARTED_AT,
    updated_at: STARTED_AT,
  };
  await page.route(
    new RegExp(`/api/langgraph/threads/${MOCK_THREAD_ID}/runs(?:\\?|$)`),
    (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: [run] })
        : route.fallback(),
  );
  await page.route(
    new RegExp(
      `/api/langgraph/threads/${MOCK_THREAD_ID}/runs/${RUN_ID}(?:\\?|$)`,
    ),
    (route) => route.fulfill({ json: run }),
  );
  // Hold every join open: the run is still working on the server.
  await page.route(
    `**/api/langgraph/threads/${MOCK_THREAD_ID}/runs/${RUN_ID}/stream*`,
    (route) => {
      joins.push(route);
    },
  );
  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  return joins;
}

async function release(joins: Route[]) {
  await Promise.all(joins.map((route) => route.abort().catch(() => undefined)));
}

test("counts a run started before the page opened from its server start, across a reload", async ({
  page,
}) => {
  const joins = await openRunningChat(page);
  try {
    const activity = page.getByTestId("run-activity");
    await expect(activity).toContainText(/\(30m(?: \d+s)?\)/);

    // A reload rejoins through the SDK's same-tab pointer instead of the
    // runs-list recovery; the count must still start at the server's start.
    await page.reload();
    await expect(activity).toContainText(/\(30m(?: \d+s)?\)/);
    await page.clock.fastForward("02:00");
    await expect(activity).toContainText(/\(32m(?: \d+s)?\)/);
    expect(joins.length).toBeGreaterThanOrEqual(2);
  } finally {
    await release(joins);
  }
});

test("says where the live timer counts from on hover and keyboard focus", async ({
  page,
}) => {
  const joins = await openRunningChat(page);
  try {
    const elapsed = page.getByRole("timer", {
      name: "Time this task has been running",
    });
    await expect(elapsed).toContainText(/\(30m(?: \d+s)?\)/);
    const explanation =
      /^Running since 9:30\sAM\. Counted from when the task started on the server, so it keeps counting after you reload or reopen the page\.$/;
    await expect(elapsed).toHaveAccessibleDescription(explanation);

    await elapsed.hover();
    await expect(page.getByRole("tooltip")).toHaveText(explanation);

    // Radix closes once the pointer has left the trigger's grace area, which
    // takes pointer movement outside it, not a single jump.
    await page.mouse.move(0, 0, { steps: 10 });
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    await elapsed.focus();
    await expect(page.getByRole("tooltip")).toHaveText(explanation);
  } finally {
    await release(joins);
  }
});
