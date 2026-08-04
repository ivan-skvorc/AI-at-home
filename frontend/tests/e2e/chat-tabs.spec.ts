import { expect, test, type Locator, type Page } from "@playwright/test";

import {
  mockLangGraphAPI,
  MOCK_THREAD_ID,
  MOCK_THREAD_ID_2,
} from "./utils/mock-api";

// Fork feature: browser-style keep-alive chat tabs. These tests exercise the
// user-facing behavior: dragging a chat out of the sidebar onto the tab strip
// (the primary interaction), opening a chat as a tab via the row menu, switching
// between tabs without a remount, closing a tab, reordering by drag, and reload
// persistence. Native HTML5 drag-and-drop is driven directly (see
// `html5DragAndDrop`) by sharing one DataTransfer across the source's dragstart
// and the target's dragover/drop — Playwright's mouse-based `dragTo` does not
// trigger the HTML5 DnD events these handlers listen for.

// Simulate an HTML5 drag from `source` to `target`. The shared DataTransfer
// carries the payload set in the source's onDragStart to the target's onDrop,
// exactly like a real browser drag.
async function html5DragAndDrop(page: Page, source: Locator, target: Locator) {
  const sourceHandle = await source.elementHandle();
  const targetHandle = await target.elementHandle();
  if (!sourceHandle || !targetHandle) {
    throw new Error("drag source or target element not found");
  }
  await page.evaluate(
    ({ sourceEl, targetEl }) => {
      const dataTransfer = new DataTransfer();
      const fire = (element: Element, type: string) => {
        const event = new DragEvent(type, { bubbles: true, cancelable: true });
        Object.defineProperty(event, "dataTransfer", { value: dataTransfer });
        element.dispatchEvent(event);
      };
      fire(sourceEl, "dragstart");
      fire(targetEl, "dragenter");
      fire(targetEl, "dragover");
      fire(targetEl, "drop");
      fire(sourceEl, "dragend");
    },
    { sourceEl: sourceHandle, targetEl: targetHandle },
  );
}

const sidebarRow = (page: Page, threadId: string) =>
  page.locator(`[data-sidebar='sidebar'] a[href*='${threadId}']`);

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
  test("a brand-new chat shows the empty drop zone and accepts a dragged chat", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    // Land on a fresh chat — there are no tabs yet, but the strip must still be
    // present as a drop zone so the user has somewhere to drag a chat onto.
    await page.goto("/workspace/chats/new");
    await expect(
      page.locator("[data-sidebar='sidebar']").getByText("First conversation"),
    ).toBeVisible({ timeout: 15_000 });

    const strip = page.getByTestId("chat-tabs-bar");
    await expect(strip).toBeVisible();
    await expect(page.getByTestId("chat-tabs-empty-hint")).toBeVisible();
    await expect(page.getByTestId("chat-tab")).toHaveCount(0);

    // Drag "First conversation" out of the sidebar onto the strip — it becomes a
    // keep-alive tab and the empty hint goes away.
    await html5DragAndDrop(page, sidebarRow(page, MOCK_THREAD_ID), strip);

    await expect(page.getByTestId("chat-tab")).toHaveCount(1);
    await expect(
      page.getByTestId("chat-tab").filter({ hasText: "First conversation" }),
    ).toBeVisible();
    await expect(page.getByTestId("chat-tabs-empty-hint")).toHaveCount(0);
  });

  test("dragging a chip onto another reorders the tabs", async ({ page }) => {
    mockLangGraphAPI(page, { threads: THREADS });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByText(FIRST_MESSAGE)).toBeVisible({
      timeout: 15_000,
    });

    await openInTabFromSidebar(page, "First conversation");
    await openInTabFromSidebar(page, "Second conversation");
    await expect(page.getByTestId("chat-tab")).toHaveCount(2);

    // Initial order: First, Second.
    const titlesBefore = await page.getByTestId("chat-tab").allInnerTexts();
    expect(titlesBefore[0]).toContain("First conversation");
    expect(titlesBefore[1]).toContain("Second conversation");

    // Drag the second chip onto the first — they swap order.
    await html5DragAndDrop(
      page,
      page.getByTestId("chat-tab").filter({ hasText: "Second conversation" }),
      page.getByTestId("chat-tab").filter({ hasText: "First conversation" }),
    );

    await expect
      .poll(async () => {
        const titles = await page.getByTestId("chat-tab").allInnerTexts();
        return titles[0]?.includes("Second conversation") ?? false;
      })
      .toBe(true);
  });

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
