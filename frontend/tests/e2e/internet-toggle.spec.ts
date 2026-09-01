import { expect, test } from "@playwright/test";

import {
  MOCK_THREAD_ID,
  handleRunStream,
  mockLangGraphAPI,
} from "./utils/mock-api";

/**
 * The conversation's internet switch (fork feature, FORK.md §27).
 *
 * What is worth an e2e run here is the whole chain the unit tests can only see
 * one end of: click the composer control, and the run request the backend
 * receives carries `internet_enabled: false`. Everything downstream of that key
 * is pinned in `backend/tests/test_internet_toggle.py`.
 *
 * The control is located by its own `data-slot`, never by the ARIA role of the
 * button primitive underneath it — see the model-picker lesson in FORK.md.
 */

const TOGGLE = "[data-slot='internet-toggle']";

test.describe("Composer internet switch", () => {
  test("is on by default and sends internet_enabled: true", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    let context: Record<string, unknown> | undefined;
    await page.route("**/runs/stream", (route) => {
      const body = route.request().postDataJSON() as {
        context?: Record<string, unknown>;
      };
      context = body.context;
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 20_000 });

    // Nothing was clicked: the switch is an opt-out, so a fresh chat browses.
    const toggle = page.locator(TOGGLE);
    await expect(toggle).toHaveAttribute("data-state", "on");
    await expect(toggle).toHaveAccessibleName("Internet on");

    await textarea.fill("hello");
    await textarea.press("Enter");
    await expect.poll(() => context?.internet_enabled).toBe(true);
  });

  test("turning it off sends internet_enabled: false with the next run", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    let context: Record<string, unknown> | undefined;
    await page.route("**/runs/stream", (route) => {
      const body = route.request().postDataJSON() as {
        context?: Record<string, unknown>;
      };
      context = body.context;
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 20_000 });

    const toggle = page.locator(TOGGLE);
    await toggle.click();
    await expect(toggle).toHaveAttribute("data-state", "off");
    await expect(toggle).toHaveAccessibleName("Internet off");

    await textarea.fill("what do you know about this repo?");
    await textarea.press("Enter");

    // The whole feature in one assertion: the backend is told to assemble this
    // run without any internet-reaching tool.
    await expect.poll(() => context?.internet_enabled).toBe(false);
  });

  test("an offline conversation stays offline across a reload", async ({
    page,
  }) => {
    // An existing thread, because a brand-new chat is issued a fresh id on
    // every mount — the switch is stored per conversation, so there has to be
    // a conversation for it to be stored against.
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "An offline conversation",
          updated_at: "2025-06-01T12:00:00Z",
        },
      ],
    });
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible({
      timeout: 20_000,
    });

    await page.locator(TOGGLE).click();
    await expect(page.locator(TOGGLE)).toHaveAttribute("data-state", "off");

    // Reopening the chat must not quietly put it back online.
    await page.reload();
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.locator(TOGGLE)).toHaveAttribute("data-state", "off");
  });
});
