import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * The chat header's "Auto rename" (fork feature, FORK.md §38).
 *
 * The unit tests pin the wire shape and the dialog's own state. This clicks the
 * real flow — header button → dialog → model pick → Run — and asserts the two
 * things that only exist end to end: the picked model reaches the Gateway, and
 * the returned title lands in the header *and* the sidebar rather than only in
 * whichever cache the mutation happened to touch.
 */

const THREAD_ID = "00000000-0000-0000-0000-000000000654";
const ORIGINAL_TITLE = "New Conversation";
const GENERATED_TITLE = "Choosing Go over Rust";

const MODELS = [
  {
    name: "cheap-model",
    model: "cheap-model",
    display_name: "Cheap Model",
    supports_thinking: false,
    supports_reasoning_effort: false,
    supports_tools: true,
  },
  {
    name: "big-model",
    model: "big-model",
    display_name: "Big Model",
    supports_thinking: false,
    supports_reasoning_effort: false,
    supports_tools: true,
  },
];

async function mockModels(page: Page) {
  await page.route("**/api/models", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            models: MODELS,
            token_usage: { enabled: false },
          }),
        })
      : route.fallback(),
  );
}

/** Capture what the suggest route was asked for, and answer it. */
function mockSuggest(
  page: Page,
  respond: { status: number; body: unknown } = {
    status: 200,
    body: { title: GENERATED_TITLE, exchange_count: 2 },
  },
) {
  const requests: Array<Record<string, unknown>> = [];
  void page.route("**/api/threads/*/title/suggest", (route) => {
    requests.push(
      JSON.parse(route.request().postData() ?? "{}") as Record<string, unknown>,
    );
    return route.fulfill({
      status: respond.status,
      contentType: "application/json",
      body: JSON.stringify(respond.body),
    });
  });
  return requests;
}

async function openChat(page: Page) {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: THREAD_ID,
        title: ORIGINAL_TITLE,
        updated_at: "2026-07-05T10:00:00Z",
      },
    ],
  });
  await mockModels(page);
  await page.goto(`/workspace/chats/${THREAD_ID}`);
  await expect(page.getByText(ORIGINAL_TITLE).first()).toBeVisible({
    timeout: 15_000,
  });
}

test("the picked model writes the title, and it lands in the header and the sidebar", async ({
  page,
}) => {
  await openChat(page);
  const requests = mockSuggest(page);

  await page.getByTestId("auto-rename-trigger").click();
  const dialog = page.getByRole("dialog", { name: "Rename this conversation" });
  await expect(dialog).toBeVisible();

  // The shared picker, not a flat list: it has a search box (FORK.md §8).
  await dialog.getByTestId("auto-rename-model-select").click();
  await expect(page.getByPlaceholder("Search models...")).toBeVisible();
  await page.getByText("Big Model").click();

  await dialog.getByTestId("auto-rename-run").click();

  await expect(dialog).toBeHidden();
  expect(requests).toEqual([{ model_name: "big-model" }]);

  await expect(page.locator("header").getByText(GENERATED_TITLE)).toBeVisible();
  await expect(
    page
      .locator(
        `a[data-sidebar="menu-button"][href="/workspace/chats/${THREAD_ID}"]`,
      )
      .locator("xpath=.."),
  ).toContainText(GENERATED_TITLE);
});

test("running without picking a model leaves the operator's choice to the Gateway", async ({
  page,
}) => {
  // An empty body, not `model_name: null`. The Gateway reads an absent key as
  // "use config.yaml -> title.model_name"; sending null is a different value.
  await openChat(page);
  const requests = mockSuggest(page);

  await page.getByTestId("auto-rename-trigger").click();
  await page.getByTestId("auto-rename-run").click();

  await expect(
    page.getByRole("dialog", { name: "Rename this conversation" }),
  ).toBeHidden();
  expect(requests).toEqual([{}]);
});

test("a refused model is reported in the Gateway's own words, with the dialog still open", async ({
  page,
}) => {
  await openChat(page);
  mockSuggest(page, {
    status: 400,
    body: { detail: "Model big-model is not configured" },
  });

  await page.getByTestId("auto-rename-trigger").click();
  const dialog = page.getByRole("dialog", { name: "Rename this conversation" });
  await dialog.getByTestId("auto-rename-run").click();

  await expect(
    page.getByText("Model big-model is not configured"),
  ).toBeVisible();
  // Still open, so the user can pick another model instead of reopening it.
  await expect(dialog).toBeVisible();
  await expect(page.locator("header").getByText(ORIGINAL_TITLE)).toBeVisible();
});
