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

/**
 * Pick a model in one of the setup page's pickers.
 *
 * The model pickers are the shared `ModelSelect` (a dialog + cmdk list, the same
 * control as the chat composer's), not a Radix `<Select>` — so they are targeted
 * by test id rather than by the `combobox` role, which now belongs only to the
 * grading scale and to the picker's own search box while it is open.
 */
async function pickModel(page: Page, testId: string, name: string) {
  await page.getByTestId(testId).click();
  await page.getByRole("option", { name, exact: false }).first().click();
}

/** Fill a complete two-model panel on the setup page. */
async function fillPanel(page: Page) {
  await page.getByLabel("Panelists").fill("2");
  await pickModel(page, "democracy-organizer-model", "Organizer Model");
  await pickModel(page, "democracy-panelist-0", "Panelist A");
  await pickModel(page, "democracy-panelist-1", "Panelist B");
}

test.describe("Democracy panel", () => {
  test("the sidebar navigates to a setup page, not a modal", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockModels(page);

    await page.goto("/workspace/chats/new");
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible({
      timeout: 20_000,
    });

    await page.getByRole("link", { name: "Democracy" }).click();

    // A route of its own, so the panel setup is back/forward-navigable and the
    // roster is not trapped in a dialog that scrolls internally.
    await expect(page).toHaveURL(/\/workspace\/democracy\/new/);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: /Start a Democracy panel/i }),
    ).toBeVisible();

    // The cost warning is on the page, above the button that spends the money.
    await expect(page.getByText(/burns tokens/i)).toBeVisible();
    await expect(page.getByText(/full model runs/i)).toBeVisible();
    // ...and says the charge repeats, because the panel is standing.
    await expect(
      page.getByText(/every follow-up runs it again/i),
    ).toBeVisible();

    await expect(
      page.getByRole("button", { name: "Start panel" }),
    ).toBeDisabled();
  });

  test("a complete panel is dispatched with its roster, grading, and task", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockModels(page);

    await page.goto("/workspace/democracy/new");
    await expect(
      page.getByRole("heading", { name: /Start a Democracy panel/i }),
    ).toBeVisible({ timeout: 20_000 });

    await fillPanel(page);

    // Grading is now the only `<Select>` left on the page — the model rows are
    // the shared dialog picker.
    await page.getByRole("combobox").last().click();
    await page.getByRole("option", { name: /Score out of 5/i }).click();

    await page
      .getByLabel("Task")
      .fill("Assess which sectors grow, hold, or shrink.");

    await page.getByRole("button", { name: "Start panel" }).click();

    // The composer is seeded rather than auto-sent, so the user gets a last look
    // at what a panel-priced run is about to be asked.
    await expect(page.getByPlaceholder(/how can i assist you/i)).toHaveValue(
      /Assess which sectors/,
      { timeout: 15_000 },
    );
    await expect(page.getByText("Democracy").last()).toBeVisible();
  });

  test("a file attached at setup arrives on the chat composer", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockModels(page);

    await page.goto("/workspace/democracy/new");
    await expect(
      page.getByRole("heading", { name: /Start a Democracy panel/i }),
    ).toBeVisible({ timeout: 20_000 });

    await fillPanel(page);
    await page.getByLabel("Task").fill("Read the attached figures.");

    // Setup has no thread yet, so the file cannot be uploaded here; it rides the
    // composer's own upload path on send instead.
    await page.setInputFiles('input[type="file"]', {
      name: "rates.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("date,rate\n2026-01-01,4.5\n"),
    });
    await expect(page.getByText("rates.csv")).toBeVisible();

    await page.getByRole("button", { name: "Start panel" }).click();

    await expect(page.getByPlaceholder(/how can i assist you/i)).toHaveValue(
      /attached figures/,
      { timeout: 15_000 },
    );
    // The attachment survived the hop and is staged on the composer.
    await expect(page.getByText("rates.csv")).toBeVisible({ timeout: 10_000 });
  });

  test("a duplicate panelist is refused rather than dispatched twice", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockModels(page);

    await page.goto("/workspace/democracy/new");
    await expect(
      page.getByRole("heading", { name: /Start a Democracy panel/i }),
    ).toBeVisible({ timeout: 20_000 });

    await page.getByLabel("Panelists").fill("2");
    await pickModel(page, "democracy-panelist-0", "Panelist A");
    await pickModel(page, "democracy-panelist-1", "Panelist A");

    // One model asked twice is one opinion at twice the price.
    await expect(page.getByText(/must be a different model/i)).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Start panel" }),
    ).toBeDisabled();
  });
});
