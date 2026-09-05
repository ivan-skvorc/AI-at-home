import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI, THREAD_FOLDER_METADATA_KEY } from "./utils/mock-api";

// The sidebar's chat lists virtualize past 60 rows and share **one** scroll
// container with everything above them, so each list has to tell the
// virtualizer its own offset inside that container. Measure that offset once
// and anything that moves the list afterwards — a folder opening above it, a
// section of the sidebar settling on a cold load — leaves the virtualizer
// mapping scroll positions onto the wrong rows: the rows are drawn where the
// list *used* to be, and the band you are actually looking at is blank. The
// conversations in it cannot be scrolled to at all.
//
// That only exists against a real layout engine, which is why it is here and
// not in the unit suite (`thread-list-scroll-margin.dom.test.tsx` pins the
// re-measurement itself). Expanding the folder is the deterministic way to
// move the list *after* the last thing the old code re-measured on.

const FOLDER_ID = "folder-seed";
const FILED_COUNT = 30;
const ROOT_COUNT = 80;

function threadId(index: number) {
  return `00000000-0000-0000-0000-${String(index).padStart(12, "0")}`;
}

/** Newest first, so index 0 is the top of the sidebar and the last is oldest. */
function seedThreads() {
  const filed = Array.from({ length: FILED_COUNT }, (_, index) => ({
    thread_id: threadId(index + 1),
    title: `Filed conversation ${index + 1}`,
    updated_at: new Date(Date.UTC(2026, 6, 1, 0, 0, 900 - index)).toISOString(),
    metadata: { [THREAD_FOLDER_METADATA_KEY]: FOLDER_ID },
  }));
  const root = Array.from({ length: ROOT_COUNT }, (_, index) => ({
    thread_id: threadId(index + 501),
    title: `Conversation ${index + 1}`,
    updated_at: new Date(Date.UTC(2026, 6, 1, 0, 0, 800 - index)).toISOString(),
  }));
  return [...filed, ...root];
}

const sidebarContent = (page: Page) =>
  page.locator('[data-sidebar="content"]').first();

/** Load every page, so no later fetch can re-measure the list for us. */
async function loadEveryPage(page: Page) {
  const loadMore = page.getByTestId("recent-chat-list-load-more");
  for (let attempt = 0; attempt < 10; attempt += 1) {
    if ((await loadMore.count()) === 0) {
      return;
    }
    await loadMore.click();
    await page.waitForTimeout(250);
  }
  throw new Error("the sidebar never finished loading its pages");
}

/**
 * Park the sidebar `offset` pixels into the root list and report how many
 * conversation rows are actually inside the visible band. Zero is the bug: the
 * rows exist, they are just drawn somewhere the reader cannot get to.
 */
async function chatRowsVisibleAt(page: Page, offset: number) {
  return page.evaluate((intoList) => {
    const content = document.querySelector<HTMLElement>(
      '[data-sidebar="content"]',
    );
    const rootList = document.querySelector<HTMLElement>(
      '[data-testid="chat-root-list"]',
    );
    if (!content || !rootList) {
      return -1;
    }
    const contentBox = content.getBoundingClientRect();
    const listTop =
      rootList.getBoundingClientRect().top - contentBox.top + content.scrollTop;
    content.scrollTop = listTop + intoList;
    const band = content.getBoundingClientRect();
    return [
      ...rootList.querySelectorAll<HTMLElement>('a[href*="/workspace/chats/"]'),
    ].filter((row) => {
      const box = row.getBoundingClientRect();
      return box.bottom > band.top + 1 && box.top < band.bottom - 1;
    }).length;
  }, offset);
}

test.describe("Sidebar chat list, past the virtualization threshold", () => {
  test("a folder opening above the list does not put its rows out of reach", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: seedThreads(),
      chatFolders: [{ id: FOLDER_ID, name: "Work" }],
    });
    await page.goto("/workspace/chats/new");
    await expect(
      page.locator(`[data-sidebar='sidebar'] a[href$='${threadId(501)}']`),
    ).toBeVisible({ timeout: 15_000 });

    await loadEveryPage(page);
    await expect(sidebarContent(page)).toBeVisible();

    // Before the folder opens, the list is where it was measured.
    await expect.poll(() => chatRowsVisibleAt(page, 600)).toBeGreaterThan(0);

    // Open the folder: 30 rows appear *above* the root list and push it down,
    // with the root list's own item count unchanged.
    const folder = page
      .getByTestId("chat-folder-row")
      .filter({ hasText: "Work" });
    await folder.getByRole("button").first().click();
    await expect(page.getByTestId("chat-folder-children")).toBeVisible();

    // The rows the reader is looking at have to be the rows that are there.
    await expect
      .poll(() => chatRowsVisibleAt(page, 600), { timeout: 10_000 })
      .toBeGreaterThan(0);
    await expect
      .poll(() => chatRowsVisibleAt(page, 1400), { timeout: 10_000 })
      .toBeGreaterThan(0);
  });
});
