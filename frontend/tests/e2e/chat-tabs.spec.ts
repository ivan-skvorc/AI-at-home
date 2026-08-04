import { expect, test, type Page } from "@playwright/test";

import {
  mockLangGraphAPI,
  MOCK_THREAD_ID,
  MOCK_THREAD_ID_2,
} from "./utils/mock-api";

// Fork feature: browser-style keep-alive chat tabs. These tests exercise the
// user-facing behavior (open a chat as a tab, switch between tabs without a
// remount, close a tab). Drag-and-drop reordering is covered by the pure-model
// unit tests (reorderTabsByKey) since native HTML5 DnD is not reliably
// simulatable in headless browsers.

const THREADS = [
  {
    thread_id: MOCK_THREAD_ID,
    title: "First conversation",
    updated_at: "2025-06-01T12:00:00Z",
  },
  {
    thread_id: MOCK_THREAD_ID_2,
    title: "Second conversation",
    updated_at: "2025-06-02T12:00:00Z",
  },
];

const FIRST_MESSAGE = "Response in thread First conversation";
const SECOND_MESSAGE = "Response in thread Second conversation";

async function openInTabFromSidebar(page: Page, title: string) {
  const sidebar = page.locator("[data-sidebar='sidebar']");
  const item = sidebar
    .locator("[data-sidebar='menu-item']")
    .filter({ hasText: title })
    .first();
  await expect(item).toBeVisible({ timeout: 15_000 });
  await item.hover();
  await item.getByRole("button", { name: "More" }).click();
  await page.getByRole("menuitem", { name: "Open in tab" }).click();
}

test.describe("Chat tabs", () => {
  test("opening chats as tabs keeps both mounted and switches between them", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText(FIRST_MESSAGE)).toBeVisible({
      timeout: 15_000,
    });

    // Pin both conversations as tabs from the sidebar row menu.
    await openInTabFromSidebar(page, "First conversation");
    await openInTabFromSidebar(page, "Second conversation");

    const tabs = page.getByTestId("chat-tab");
    await expect(tabs).toHaveCount(2);

    // Opening the second one makes it the active/visible chat.
    await expect(page.getByText(SECOND_MESSAGE)).toBeVisible();
    await expect(page).toHaveURL(new RegExp(MOCK_THREAD_ID_2));

    // Keep-alive: both chat instances stay mounted (two slots in the DOM),
    // even though only one is displayed.
    await expect(page.locator("[data-slot-key]")).toHaveCount(2);

    // Switch back to the first tab — no remount, the first chat's history is
    // shown again and the second remains mounted but hidden.
    await tabs.filter({ hasText: "First conversation" }).click();
    await expect(page.getByText(FIRST_MESSAGE)).toBeVisible();
    await expect(page.getByText(SECOND_MESSAGE)).toBeHidden();
    await expect(page.locator("[data-slot-key]")).toHaveCount(2);
    await expect(page).toHaveURL(new RegExp(MOCK_THREAD_ID));
  });

  test("closing a tab removes it and reveals a neighbor", async ({ page }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText(FIRST_MESSAGE)).toBeVisible({
      timeout: 15_000,
    });

    await openInTabFromSidebar(page, "First conversation");
    await openInTabFromSidebar(page, "Second conversation");
    await expect(page.getByTestId("chat-tab")).toHaveCount(2);

    // Close the active (second) tab; the first tab becomes active again.
    const secondTab = page
      .getByTestId("chat-tab")
      .filter({ hasText: "Second conversation" });
    await secondTab.hover();
    await secondTab.getByTestId("chat-tab-close").click();

    await expect(page.getByTestId("chat-tab")).toHaveCount(1);
    await expect(page.getByText(FIRST_MESSAGE)).toBeVisible();
    await expect(page).toHaveURL(new RegExp(MOCK_THREAD_ID));
  });

  test("pinned tabs persist across a reload", async ({ page }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText(FIRST_MESSAGE)).toBeVisible({
      timeout: 15_000,
    });
    await openInTabFromSidebar(page, "First conversation");
    await expect(page.getByTestId("chat-tab")).toHaveCount(1);

    await page.reload();

    await expect(page.getByText(FIRST_MESSAGE)).toBeVisible({
      timeout: 15_000,
    });
    // The pinned tab is restored from localStorage after the reload.
    await expect(
      page.getByTestId("chat-tab").filter({ hasText: "First conversation" }),
    ).toBeVisible();
  });
});
