import { expect, test } from "@playwright/test";

import {
  MOCK_THREAD_ID,
  MOCK_THREAD_ID_2,
  mockLangGraphAPI,
  THREAD_PINNED_METADATA_KEY,
} from "./utils/mock-api";

test.describe("Branch threads in the sidebar", () => {
  // This fork replaced the per-turn "Branch" button with Edit + a hidden-version
  // switcher (FORK.md, *Gaslight mode*), so upstream's "creates a new chat branch
  // from a completed assistant turn" test drives a control that no longer exists.
  // Branch *threads* themselves still exist (the API route and the sidebar tree are
  // untouched), so the rendering test below is kept.
  test("keeps a pinned branch top-level when its parent is unpinned", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Unpinned parent",
          updated_at: "2026-08-24T00:00:00Z",
        },
        {
          thread_id: MOCK_THREAD_ID_2,
          title: "Pinned branch (2)",
          updated_at: "2026-08-24T00:01:00Z",
          metadata: {
            deerflow_branch: true,
            branch_parent_thread_id: MOCK_THREAD_ID,
            [THREAD_PINNED_METADATA_KEY]: true,
          },
        },
      ],
    });

    await page.goto("/workspace/chats/new");

    const branchLink = page.locator(
      `a[href="/workspace/chats/${MOCK_THREAD_ID_2}"]`,
    );
    await expect(branchLink).toBeVisible();
    await expect(branchLink).not.toHaveAttribute("data-branch-depth");
    await expect(branchLink.getByTestId("thread-branch-stem")).toHaveCount(0);

    const recentChatHrefs = await page
      .locator(
        'a[data-sidebar="menu-button"][href^="/workspace/chats/"]:not([href="/workspace/chats/new"])',
      )
      .evaluateAll((links) => links.map((link) => link.getAttribute("href")));
    expect(recentChatHrefs).toEqual([
      `/workspace/chats/${MOCK_THREAD_ID_2}`,
      `/workspace/chats/${MOCK_THREAD_ID}`,
    ]);
  });
});
