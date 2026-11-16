import { expect, test, type Page, type Request } from "@playwright/test";

import { mockLangGraphAPI, THREAD_FOLDER_METADATA_KEY } from "./utils/mock-api";

// Sidebar multi-select: tick several chats, then move, file into a new folder
// or delete them in one go. These drive the real UI against the mocked
// Gateway and assert the requests themselves, because the properties that
// matter are on the wire: a bulk move sends placement-only PATCHes (so the
// recency-ordered sidebar does not reshuffle), "New folder from selection"
// writes the folder registry once and then files every chat into the id it
// created, and a bulk delete that includes the open chat leaves that page.

const REPORT = "00000000-0000-0000-0000-000000000a01";
const HOLIDAY = "00000000-0000-0000-0000-000000000a02";
const BUDGET = "00000000-0000-0000-0000-000000000a03";

const THREADS = [
  {
    thread_id: REPORT,
    title: "Quarterly report",
    updated_at: "2026-07-04T10:00:00Z",
  },
  {
    thread_id: HOLIDAY,
    title: "Holiday planning",
    updated_at: "2026-07-03T10:00:00Z",
  },
  {
    thread_id: BUDGET,
    title: "Budget review",
    updated_at: "2026-07-02T10:00:00Z",
  },
];

const sidebar = (page: Page) => page.locator("[data-sidebar='sidebar']");
const chatRow = (page: Page, threadId: string) =>
  sidebar(page).locator(`a[data-sidebar='menu-button'][href$='${threadId}']`);
const rootList = (page: Page) => page.getByTestId("chat-root-list");
const folderRow = (page: Page, name: string) =>
  page.getByTestId("chat-folder-row").filter({ hasText: name });
const checkbox = (page: Page, title: string) =>
  page.getByRole("checkbox", { name: `Select “${title}”` });

/** Every metadata PATCH on the Gateway's thread route, by thread id. */
function recordThreadPatches(page: Page) {
  const patches: Array<{ threadId: string; body: unknown }> = [];
  page.on("request", (request: Request) => {
    if (request.method() !== "PATCH") return;
    const match = /\/api\/threads\/([^/]+)$/.exec(
      new URL(request.url()).pathname,
    );
    if (!match) return;
    patches.push({
      threadId: decodeURIComponent(match[1]!),
      body: request.postDataJSON(),
    });
  });
  return patches;
}

async function startSelecting(page: Page) {
  await page.getByTestId("chat-selection-toggle").click();
  await expect(page.getByTestId("chat-selection-toolbar")).toBeVisible();
}

test.describe("Sidebar multi-select", () => {
  test("two ticked chats move into a folder with placement-only writes", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: THREADS,
      chatFolders: [{ id: "folder-work", name: "Work" }],
    });
    const patches = recordThreadPatches(page);
    await page.goto("/workspace/chats/new");
    await expect(chatRow(page, REPORT)).toBeVisible({ timeout: 15_000 });

    await startSelecting(page);
    await checkbox(page, "Quarterly report").check();
    await checkbox(page, "Budget review").check();
    await expect(page.getByTestId("chat-selection-count")).toHaveText(
      "2 selected",
    );

    await page.getByTestId("chat-selection-move").click();
    await page.getByRole("menuitem", { name: "Work", exact: true }).click();

    const children = page.locator(
      "[data-testid='chat-folder-children'][data-folder-id='folder-work']",
    );
    await expect(children.locator(`a[href$='${REPORT}']`)).toBeVisible();
    await expect(children.locator(`a[href$='${BUDGET}']`)).toBeVisible();
    await expect(rootList(page).locator(`a[href$='${REPORT}']`)).toHaveCount(0);
    await expect(rootList(page).locator(`a[href$='${HOLIDAY}']`)).toBeVisible();

    await expect.poll(() => patches.length).toBe(2);
    expect(
      patches
        .map(({ threadId, body }) => [threadId, body])
        .sort(([a], [b]) => String(a).localeCompare(String(b))),
    ).toEqual([
      [REPORT, { metadata: { [THREAD_FOLDER_METADATA_KEY]: "folder-work" } }],
      [BUDGET, { metadata: { [THREAD_FOLDER_METADATA_KEY]: "folder-work" } }],
    ]);
    // The batch is done: nothing stays ticked, selection mode stays on.
    await expect(page.getByTestId("chat-selection-count")).toHaveText(
      "0 selected",
    );
  });

  test("New folder from selection writes the folder once and files every ticked chat into it", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: THREADS });
    const patches = recordThreadPatches(page);
    await page.goto("/workspace/chats/new");
    await expect(chatRow(page, REPORT)).toBeVisible({ timeout: 15_000 });

    await startSelecting(page);
    await checkbox(page, "Holiday planning").check();
    // Shift-click draws the range in rendered order: Holiday → Budget.
    await checkbox(page, "Budget review").click({ modifiers: ["Shift"] });
    await expect(page.getByTestId("chat-selection-count")).toHaveText(
      "2 selected",
    );

    await page.getByTestId("chat-selection-move").click();
    await page
      .getByRole("menuitem", { name: "New folder from selection…" })
      .click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText(
      "The 2 selected chats move into the new folder.",
    );
    await page.getByTestId("chat-folder-name-input").fill("Planning");
    const put = page.waitForRequest(
      (request) =>
        request.method() === "PUT" &&
        request.url().includes("/api/settings/chat-folders"),
    );
    await dialog.getByRole("button", { name: "Save" }).click();

    const body = (await put).postDataJSON() as {
      chat_folders: Array<{ id: string; name: string; parentId?: string }>;
    };
    expect(body.chat_folders).toHaveLength(1);
    const [created] = body.chat_folders;
    expect(created).toMatchObject({ name: "Planning" });
    expect(created!.parentId).toBeUndefined();

    await expect.poll(() => patches.length).toBe(2);
    expect(
      patches
        .map(({ threadId, body }) => [threadId, body])
        .sort(([a], [b]) => String(a).localeCompare(String(b))),
    ).toEqual([
      [HOLIDAY, { metadata: { [THREAD_FOLDER_METADATA_KEY]: created!.id } }],
      [BUDGET, { metadata: { [THREAD_FOLDER_METADATA_KEY]: created!.id } }],
    ]);

    await expect(folderRow(page, "Planning")).toBeVisible();
    const children = page.locator(
      `[data-testid='chat-folder-children'][data-folder-id='${created!.id}']`,
    );
    await expect(children.locator(`a[href$='${HOLIDAY}']`)).toBeVisible();
    await expect(children.locator(`a[href$='${BUDGET}']`)).toBeVisible();
    await expect(rootList(page).locator(`a[href$='${REPORT}']`)).toBeVisible();
  });

  test("bulk delete confirms, removes every ticked chat and leaves the open one", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: THREADS });
    const deletes: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "DELETE") deletes.push(request.url());
    });
    await page.goto(`/workspace/chats/${REPORT}`);
    await expect(chatRow(page, HOLIDAY)).toBeVisible({ timeout: 15_000 });

    await startSelecting(page);
    // A click on a row toggles it while selecting; it does not navigate.
    await chatRow(page, HOLIDAY).click();
    await expect(page).toHaveURL(new RegExp(REPORT));
    await checkbox(page, "Quarterly report").check();
    await expect(page.getByTestId("chat-selection-count")).toHaveText(
      "2 selected",
    );

    await page.getByTestId("chat-selection-delete").click();
    const dialog = page.getByTestId("thread-bulk-delete-dialog");
    await expect(dialog).toContainText("Delete 2 chats?");
    await expect(dialog).toContainText("Quarterly report");
    await expect(dialog).toContainText("Holiday planning");
    await expect(dialog).toContainText("cannot be undone");
    await expect(
      dialog.getByRole("button", { name: "Cancel", exact: true }),
    ).toBeFocused();
    expect(deletes).toEqual([]);

    await dialog.getByRole("button", { name: "Delete 2 chats" }).click();
    await expect(dialog).toBeHidden();
    await expect(page).toHaveURL(/\/workspace\/chats\/new$/);
    await expect(chatRow(page, REPORT)).toHaveCount(0);
    await expect(chatRow(page, HOLIDAY)).toHaveCount(0);
    await expect(chatRow(page, BUDGET)).toBeVisible();
    expect(deletes.some((url) => url.includes(REPORT))).toBe(true);
    expect(deletes.some((url) => url.includes(HOLIDAY))).toBe(true);
    expect(deletes.some((url) => url.includes(BUDGET))).toBe(false);
  });

  test("the row menu offers Select and a link to the chat's files", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: THREADS });
    await page.goto("/workspace/chats/new");
    const row = chatRow(page, BUDGET);
    await expect(row).toBeVisible({ timeout: 15_000 });

    await row.hover();
    await row.locator("xpath=..").getByRole("button", { name: "More" }).click();
    await expect(
      page.getByRole("menuitem", { name: "Show files" }),
    ).toHaveAttribute("href", `/workspace/chats/${BUDGET}?panel=files`);
    await page.getByRole("menuitem", { name: "Select" }).click();
    await expect(page.getByTestId("chat-selection-toolbar")).toBeVisible();
    await expect(checkbox(page, "Budget review")).toBeChecked();

    // Escape leaves selection mode.
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("chat-selection-toolbar")).toBeHidden();
    await expect(page.getByRole("checkbox")).toHaveCount(0);
  });
});
