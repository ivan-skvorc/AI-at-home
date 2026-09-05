import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI, THREAD_FOLDER_METADATA_KEY } from "./utils/mock-api";

// Fork regression: past `VIRTUALIZATION_THRESHOLD` rows the sidebar's chat list
// is virtualized inside a scroll container it does not own, and the offset it
// renders against — the scroll margin — used to be measured once per change in
// row *count*. Anything else that moved the list left that number stale, and the
// virtualizer then mounted rows for a part of the list the reader was not
// looking at: scroll into the middle of a long history and the sidebar is blank
// where conversations should be.
//
// Opening a folder is the cheapest deterministic way to move the list without
// touching its row count — the same shift a cold load produces on its own, when
// the per-browser expanded set hydrates from `localStorage` after the first
// paint and the channels group above fills in from its own fetch.
//
// The other two cases are the same complaint from the other end: a sidebar that
// stops paging is a history you cannot reach either. Both need a real layout
// engine (happy-dom has none, so every rect it reports is zero) and a real
// paging loop, which is why they are E2E; the unit tests beside them pin the
// watcher's wiring and the budget's arithmetic.

const ROOT_THREAD_COUNT = 80;
const FILED_THREAD_COUNT = 40;
const FOLDER = { id: "archive-folder", name: "Archive" };

const THREADS = [
  ...Array.from({ length: ROOT_THREAD_COUNT }, (_, index) => ({
    thread_id: `00000000-0000-0000-0000-1000000${String(index).padStart(5, "0")}`,
    title: `Root conversation ${String(index + 1).padStart(3, "0")}`,
    updated_at: new Date(
      Date.UTC(2026, 5, 30, 12, 0, 0) - index * 60_000,
    ).toISOString(),
  })),
  ...Array.from({ length: FILED_THREAD_COUNT }, (_, index) => ({
    thread_id: `00000000-0000-0000-0000-2000000${String(index).padStart(5, "0")}`,
    title: `Filed conversation ${String(index + 1).padStart(3, "0")}`,
    updated_at: new Date(
      Date.UTC(2026, 4, 30, 12, 0, 0) - index * 60_000,
    ).toISOString(),
    metadata: { [THREAD_FOLDER_METADATA_KEY]: FOLDER.id },
  })),
];

/** How many root-list rows carrying this title are mounted right now. */
async function rootRowsTitled(page: Page, title: string) {
  return page
    .locator('[data-testid="chat-root-list"] a[href]')
    .filter({ hasText: title })
    .count();
}

/** Root-list rows whose box actually overlaps the sidebar's scroll viewport. */
async function rootRowsOnScreen(page: Page) {
  return page.evaluate(() => {
    const viewport = document.querySelector('[data-sidebar="content"]');
    const list = document.querySelector('[data-testid="chat-root-list"]');
    if (!viewport || !list) {
      return -1;
    }
    const bounds = viewport.getBoundingClientRect();
    return Array.from(list.querySelectorAll("a[href]")).filter((row) => {
      const box = row.getBoundingClientRect();
      return box.bottom > bounds.top && box.top < bounds.bottom;
    }).length;
  });
}

async function scrollSidebarTo(page: Page, fraction: number) {
  await page.evaluate((ratio) => {
    const viewport = document.querySelector('[data-sidebar="content"]');
    if (!viewport) {
      return;
    }
    viewport.scrollTop = Math.round(
      (viewport.scrollHeight - viewport.clientHeight) * ratio,
    );
  }, fraction);
}

/**
 * Page the sidebar in by doing what a reader does — scroll to the bottom, which
 * is what puts the load sentinel in view — until `title` is mounted.
 */
async function pageDownUntilMounted(page: Page, title: string) {
  await expect
    .poll(
      async () => {
        await scrollSidebarTo(page, 1);
        return rootRowsTitled(page, title);
      },
      { intervals: [400], timeout: 60_000 },
    )
    .toBeGreaterThan(0);
}

/** The list has rendered at all — separates "app is up" from "app is paging". */
async function waitForSidebarList(page: Page) {
  await expect(page.getByTestId("chat-root-list")).toBeVisible({
    timeout: 60_000,
  });
}

test.describe("Sidebar long chat list", () => {
  // Each case loads a hundred conversations or more; running them against one
  // dev server in parallel starves the very render loop they measure.
  test.describe.configure({ mode: "default" });

  test("keeps rendering conversations after a folder above the list opens", async ({
    page,
  }) => {
    test.slow();
    mockLangGraphAPI(page, { threads: THREADS, chatFolders: [FOLDER] });
    await page.goto("/workspace/chats/new");
    await waitForSidebarList(page);

    // Page the whole history in first, so the scroll range is stable before
    // anything moves the list.
    await pageDownUntilMounted(
      page,
      `Root conversation ${String(ROOT_THREAD_COUNT).padStart(3, "0")}`,
    );

    // The list moves down by the folder's height; its row count does not change.
    await page.getByTestId("chat-folder-row").click();
    await expect(
      page.getByTestId("chat-folder-children").getByText("Filed conversation"),
    ).not.toHaveCount(0);

    await scrollSidebarTo(page, 0.6);
    await expect.poll(() => rootRowsOnScreen(page)).toBeGreaterThan(0);

    await scrollSidebarTo(page, 1);
    await expect.poll(() => rootRowsOnScreen(page)).toBeGreaterThan(0);
  });

  test("filing a history away does not starve the list that is still shown", async ({
    page,
  }) => {
    test.slow();
    // The sidebar pages until it has enough *root* rows. Counting filed
    // conversations against that budget stopped pagination four pages in with
    // an empty root list — the five conversations still outside a folder were
    // older than the window and could never be reached.
    const filed = Array.from({ length: 200 }, (_, index) => ({
      thread_id: `00000000-0000-0000-0000-3000000${String(index).padStart(5, "0")}`,
      title: `Filed conversation ${String(index + 1).padStart(3, "0")}`,
      updated_at: new Date(
        Date.UTC(2026, 5, 30, 12, 0, 0) - index * 60_000,
      ).toISOString(),
      metadata: { [THREAD_FOLDER_METADATA_KEY]: FOLDER.id },
    }));
    const stillOutside = Array.from({ length: 5 }, (_, index) => ({
      thread_id: `00000000-0000-0000-0000-4000000${String(index).padStart(5, "0")}`,
      title: `Root conversation ${String(index + 1).padStart(3, "0")}`,
      updated_at: new Date(
        Date.UTC(2026, 0, 30, 12, 0, 0) - index * 60_000,
      ).toISOString(),
    }));

    mockLangGraphAPI(page, {
      threads: [...filed, ...stillOutside],
      chatFolders: [FOLDER],
    });
    await page.goto("/workspace/chats/new");
    await waitForSidebarList(page);

    await pageDownUntilMounted(page, "Root conversation 005");
  });

  test("older conversations stay one click away past the auto-load budget", async ({
    page,
  }) => {
    test.slow();
    // 250 root conversations: the sidebar loads 200 on its own and then stops
    // chasing pages, but stopping must not mean the rest are unreachable.
    const threads = Array.from({ length: 250 }, (_, index) => ({
      thread_id: `00000000-0000-0000-0000-5000000${String(index).padStart(5, "0")}`,
      title: `Root conversation ${String(index + 1).padStart(3, "0")}`,
      updated_at: new Date(
        Date.UTC(2026, 5, 30, 12, 0, 0) - index * 60_000,
      ).toISOString(),
    }));

    mockLangGraphAPI(page, { threads });
    await page.goto("/workspace/chats/new");
    await waitForSidebarList(page);

    await pageDownUntilMounted(page, "Root conversation 200");

    // The sidebar now stops chasing pages by itself...
    await expect
      .poll(() => page.getByTestId("recent-chat-list-sentinel").count())
      .toBe(0);
    expect(await rootRowsTitled(page, "Root conversation 201")).toBe(0);

    // ...but the rest of the history is still one click away, not unreachable.
    const loadMore = page.getByTestId("recent-chat-list-load-more");
    await expect(loadMore).toBeVisible();
    await loadMore.click();

    await pageDownUntilMounted(page, "Root conversation 250");
  });
});
