import { expect, test, type Page, type Request } from "@playwright/test";

import {
  mockLangGraphAPI,
  THREAD_FOLDER_METADATA_KEY,
  type MockAPIController,
} from "./utils/mock-api";

// Chat clean-up mode (fork feature): a model reads the chosen conversations,
// suggests titles and folders, and the user reviews and applies the result.
// The unit tests pin the rules; this drives the real sidebar → dialog → apply
// flow against the mocked Gateway and asserts the wire, because the
// properties that matter are requests: nothing is written before Apply, new
// folders land in one registry write, moves are placement-only PATCHes and
// renames ask the Gateway to keep the sidebar's recency order.

const REPORT = "00000000-0000-0000-0000-000000000c01";
const HOLIDAY = "00000000-0000-0000-0000-000000000c02";
const BUDGET = "00000000-0000-0000-0000-000000000c03";

const THREADS = [
  {
    thread_id: REPORT,
    title: "q3 numbers",
    updated_at: "2026-07-04T10:00:00Z",
  },
  { thread_id: HOLIDAY, title: "trip", updated_at: "2026-07-03T10:00:00Z" },
  { thread_id: BUDGET, title: "money", updated_at: "2026-07-02T10:00:00Z" },
];

const SUGGESTIONS: Record<string, { title: string; category: string }> = {
  [REPORT]: { title: "Quarterly report", category: "Finance" },
  [HOLIDAY]: { title: "Holiday in Lisbon", category: "Travel" },
  [BUDGET]: { title: "Household budget", category: "finance" },
};

const sidebar = (page: Page) => page.locator("[data-sidebar='sidebar']");
const chatRow = (page: Page, threadId: string) =>
  sidebar(page).locator(`a[data-sidebar='menu-button'][href$='${threadId}']`);
const dialog = (page: Page) => page.getByTestId("chat-cleanup-dialog");

type Recorded = { method: string; path: string; body: unknown };

/** Every request the dialog's flow makes to the Gateway, in order. */
function recordRequests(page: Page) {
  const requests: Recorded[] = [];
  page.on("request", (request: Request) => {
    const path = new URL(request.url()).pathname;
    if (
      !/\/api\/(threads\/[^/]+(\/state|\/organize\/suggest)?|chat-organize\/consolidate|settings\/chat-folders)$/.test(
        path,
      )
    ) {
      return;
    }
    let body: unknown = null;
    try {
      body = request.postDataJSON();
    } catch {
      body = null;
    }
    requests.push({ method: request.method(), path, body });
  });
  return requests;
}

function threadIdOf(path: string): string {
  return decodeURIComponent(path.split("/")[3] ?? "");
}

/** The organize routes and the Gateway-native rename. */
async function mockOrganize(
  page: Page,
  controller: MockAPIController,
  { suggestStatus = 200 }: { suggestStatus?: number } = {},
) {
  await page.route("**/api/threads/*/organize/suggest", (route) => {
    const threadId = threadIdOf(new URL(route.request().url()).pathname);
    if (suggestStatus !== 200) {
      return route.fulfill({
        status: suggestStatus,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Spend cap reached for today." }),
      });
    }
    const current = THREADS.find((thread) => thread.thread_id === threadId);
    const suggestion = SUGGESTIONS[threadId]!;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        thread_id: threadId,
        current_title: current?.title ?? null,
        title: suggestion.title,
        title_changed: true,
        rename_disabled: false,
        target_id: null,
        category: suggestion.category,
        summary: null,
        model_name: "mock-model",
      }),
    });
  });
  await page.route("**/api/chat-organize/consolidate", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        folders: [
          {
            name: "Finance",
            existing_folder_id: null,
            thread_ids: [REPORT, BUDGET],
          },
          {
            name: "Travel",
            existing_folder_id: "folder-travel",
            thread_ids: [HOLIDAY],
          },
        ],
        unfiled: [],
        model_name: "mock-model",
      }),
    }),
  );
  await page.route(/\/api\/threads\/[^/]+\/state$/, (route) => {
    if (route.request().method() !== "POST") {
      return route.fallback();
    }
    const threadId = threadIdOf(new URL(route.request().url()).pathname);
    const body = route.request().postDataJSON() as {
      values?: { title?: string };
    };
    const thread = controller.getThread(threadId);
    if (thread && body.values?.title) {
      controller.upsertThread({ ...thread, title: body.values.title });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ values: body.values ?? {}, next: [] }),
    });
  });
}

async function startSelecting(page: Page) {
  await page.getByTestId("chat-selection-toggle").click();
  await expect(page.getByTestId("chat-selection-toolbar")).toBeVisible();
}

test.describe("Chat clean-up", () => {
  test("cleaning up all chats previews first, then writes folders once and files and renames each chat", async ({
    page,
  }) => {
    const controller = mockLangGraphAPI(page, {
      threads: THREADS,
      chatFolders: [{ id: "folder-travel", name: "Travel" }],
    });
    await mockOrganize(page, controller);
    const requests = recordRequests(page);
    await page.goto("/workspace/chats/new");
    await expect(chatRow(page, REPORT)).toBeVisible({ timeout: 15_000 });

    // Nothing ticked: the toolbar offers to clean up every conversation.
    await startSelecting(page);
    await page.getByTestId("chat-selection-cleanup").click();
    await expect(dialog(page)).toBeVisible();
    await expect(dialog(page)).toContainText("All 3 conversations");
    // The shared model picker, on its server-default row.
    await expect(
      dialog(page).locator('[data-slot="model-select"]'),
    ).toContainText("Server default");

    await dialog(page).getByTestId("chat-cleanup-mode-auto").check();
    await dialog(page).getByTestId("chat-cleanup-start").click();
    await expect(
      dialog(page).getByTestId("chat-cleanup-preview"),
    ).toBeVisible();
    await expect(dialog(page).getByTestId("chat-cleanup-row")).toHaveCount(3);
    await expect(
      dialog(page).getByTestId("chat-cleanup-proposed-folder"),
    ).toHaveCount(1);

    // The preview is read-only: three suggestions and one consolidation.
    const writes = () =>
      requests.filter(
        (request) =>
          request.method === "PUT" ||
          request.method === "PATCH" ||
          request.path.endsWith("/state"),
      );
    expect(
      requests.filter((request) => request.path.endsWith("/organize/suggest")),
    ).toHaveLength(3);
    expect(writes()).toEqual([]);

    await dialog(page).getByTestId("chat-cleanup-apply").click();
    await expect(dialog(page).getByTestId("chat-cleanup-result")).toContainText(
      "1 folder created",
    );

    const puts = requests.filter(
      (request) =>
        request.method === "PUT" &&
        request.path.endsWith("/settings/chat-folders"),
    );
    expect(puts).toHaveLength(1);
    const saved = (
      puts[0]!.body as { chat_folders: Array<{ id: string; name: string }> }
    ).chat_folders;
    expect(saved.map((folder) => folder.name)).toEqual(["Travel", "Finance"]);
    const financeId = saved[1]!.id;

    const patches = requests
      .filter((request) => request.method === "PATCH")
      .map((request) => [threadIdOf(request.path), request.body])
      .sort(([a], [b]) => String(a).localeCompare(String(b)));
    expect(patches).toEqual([
      [REPORT, { metadata: { [THREAD_FOLDER_METADATA_KEY]: financeId } }],
      [
        HOLIDAY,
        { metadata: { [THREAD_FOLDER_METADATA_KEY]: "folder-travel" } },
      ],
      [BUDGET, { metadata: { [THREAD_FOLDER_METADATA_KEY]: financeId } }],
    ]);
    const renames = requests
      .filter((request) => request.path.endsWith("/state"))
      .map((request) => [threadIdOf(request.path), request.body])
      .sort(([a], [b]) => String(a).localeCompare(String(b)));
    expect(renames).toEqual([
      [
        REPORT,
        { values: { title: "Quarterly report" }, preserve_recency: true },
      ],
      [
        HOLIDAY,
        { values: { title: "Holiday in Lisbon" }, preserve_recency: true },
      ],
      [
        BUDGET,
        { values: { title: "Household budget" }, preserve_recency: true },
      ],
    ]);

    await dialog(page).getByTestId("chat-cleanup-done").click();
    await expect(dialog(page)).toBeHidden();
    const finance = page.locator(
      `[data-testid='chat-folder-children'][data-folder-id='${financeId}']`,
    );
    // A folder the pass created starts collapsed, with its count showing.
    await page
      .getByTestId("chat-folder-row")
      .filter({ hasText: "Finance" })
      .getByRole("button")
      .first()
      .click();
    await expect(finance.locator(`a[href$='${REPORT}']`)).toContainText(
      "Quarterly report",
    );
  });

  test("a spend-cap refusal stops the pass after one call and writes nothing", async ({
    page,
  }) => {
    const controller = mockLangGraphAPI(page, { threads: THREADS });
    await mockOrganize(page, controller, { suggestStatus: 402 });
    const requests = recordRequests(page);
    await page.goto("/workspace/chats/new");
    await expect(chatRow(page, REPORT)).toBeVisible({ timeout: 15_000 });

    await startSelecting(page);
    await page.getByRole("checkbox", { name: "Select “q3 numbers”" }).check();
    await page.getByRole("checkbox", { name: "Select “money”" }).check();
    await page.getByTestId("chat-selection-cleanup").click();
    await expect(dialog(page)).toContainText("2 selected conversations");

    await dialog(page).getByTestId("chat-cleanup-start").click();
    await expect(dialog(page).getByTestId("chat-cleanup-notice")).toContainText(
      "Spend cap reached for today.",
    );
    await expect(dialog(page).getByTestId("chat-cleanup-setup")).toBeVisible();
    expect(
      requests.filter((request) => request.path.endsWith("/organize/suggest")),
    ).toHaveLength(1);
    expect(
      requests.filter(
        (request) =>
          request.method === "PUT" ||
          request.method === "PATCH" ||
          request.path.endsWith("/state") ||
          request.path.endsWith("/consolidate"),
      ),
    ).toEqual([]);
  });
});
