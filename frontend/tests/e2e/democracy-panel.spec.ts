import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const MODELS = [
  {
    name: "organizer",
    model: "organizer",
    display_name: "Organizer Model",
    supports_thinking: true,
    supports_reasoning_effort: true,
    supports_tools: true,
    price: { currency: "USD", input: 3, output: 15 },
  },
  {
    name: "panelist-a",
    model: "panelist-a",
    display_name: "Panelist A",
    supports_thinking: true,
    supports_reasoning_effort: false,
    supports_tools: true,
    price: { currency: "USD", input: 1, output: 5 },
  },
  {
    name: "panelist-b",
    model: "panelist-b",
    display_name: "Panelist B",
    supports_thinking: false,
    supports_reasoning_effort: false,
    supports_tools: true,
    price: { currency: "USD", input: 1, output: 5 },
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

test.describe("Democracy panel", () => {
  test("the sidebar opens the setup dialog and warns before a panel is started", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockModels(page);

    await page.goto("/workspace/chats/new");
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible({
      timeout: 20_000,
    });

    await page.getByRole("button", { name: "Democracy" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    // The cost warning is the reason this flow is a dialog rather than a mode
    // chip: the user must see what a panel costs *before* spending it.
    await expect(dialog.getByText(/burns tokens/i)).toBeVisible();
    await expect(dialog.getByText(/full model runs/i)).toBeVisible();

    // The default roster is empty, so the panel cannot be started yet.
    await expect(
      dialog.getByRole("button", { name: "Start panel" }),
    ).toBeDisabled();
  });

  test("a complete panel is dispatched with its roster, organizer, and task", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockModels(page);

    await page.goto("/workspace/chats/new");
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible({
      timeout: 20_000,
    });
    await page.getByRole("button", { name: "Democracy" }).click();

    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Panelists").fill("2");

    const selects = dialog.getByRole("combobox");
    // 0 = organizer, then one per panelist.
    await selects.nth(0).click();
    await page.getByRole("option", { name: "Organizer Model" }).click();
    await selects.nth(1).click();
    await page.getByRole("option", { name: "Panelist A" }).click();
    await selects.nth(2).click();
    await page.getByRole("option", { name: "Panelist B" }).click();

    await dialog
      .getByLabel("Task")
      .fill("Assess which sectors grow, hold, or shrink.");

    await dialog.getByRole("button", { name: "Start panel" }).click();

    // The composer is seeded rather than auto-sent, so the user gets a last look
    // at what a panel-priced run is about to be asked.
    await expect(page.getByPlaceholder(/how can i assist you/i)).toHaveValue(
      /Assess which sectors/,
      { timeout: 15_000 },
    );
    // The thread is now a Democracy run.
    await expect(page.getByText("Democracy").last()).toBeVisible();
  });

  test("a duplicate panelist is refused rather than dispatched twice", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockModels(page);

    await page.goto("/workspace/chats/new");
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible({
      timeout: 20_000,
    });
    await page.getByRole("button", { name: "Democracy" }).click();

    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Panelists").fill("2");

    const selects = dialog.getByRole("combobox");
    await selects.nth(1).click();
    await page.getByRole("option", { name: "Panelist A" }).click();
    await selects.nth(2).click();
    await page.getByRole("option", { name: "Panelist A" }).click();

    // One model asked twice is one opinion at twice the price.
    await expect(dialog.getByText(/must be a different model/i)).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "Start panel" }),
    ).toBeDisabled();
  });
});
