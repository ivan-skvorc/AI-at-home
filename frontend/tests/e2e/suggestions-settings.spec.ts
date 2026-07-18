import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const MODELS = [
  {
    name: "m1",
    model: "m1",
    display_name: "Model One",
    supports_thinking: false,
    supports_reasoning_effort: false,
    supports_tools: true,
  },
  {
    name: "m2",
    model: "m2",
    display_name: "Model Two",
    supports_thinking: false,
    supports_reasoning_effort: false,
    supports_tools: true,
  },
];

// Server master switch ON so the per-user toggle is usable (not greyed out).
async function mockSuggestionsEnabledServer(page: Page) {
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
  await page.route("**/api/suggestions/config", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ enabled: true }),
        })
      : route.fallback(),
  );
}

async function openSuggestionsSettings(page: Page) {
  await page.goto("/workspace/chats/new");
  const sidebar = page.locator("[data-sidebar='sidebar']");
  await sidebar.getByRole("button", { name: /Settings and more/ }).click();
  await page.getByRole("menuitem", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Suggestions" }).click();
  return dialog;
}

test.describe("Suggestions settings (model picker)", () => {
  test("defaults off, and enabling it reveals the model picker whose pick persists", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockSuggestionsEnabledServer(page);

    const dialog = await openSuggestionsSettings(page);

    // Toggle is present and OFF by default (cost-saving default).
    const toggle = dialog.getByRole("switch", {
      name: "Follow-up suggestions",
    });
    await expect(toggle).toBeVisible({ timeout: 15_000 });
    await expect(toggle).not.toBeChecked();

    // No model picker while suggestions are off.
    await expect(
      dialog.getByText("Follow workflow selection", { exact: true }),
    ).toHaveCount(0);

    // Turn it on → the model dropdown appears, defaulting to "Follow workflow selection".
    await toggle.click();
    await expect(toggle).toBeChecked();
    await expect(
      dialog.getByText("Follow workflow selection", { exact: true }),
    ).toBeVisible({ timeout: 10_000 });

    // Pick a concrete model from the dropdown.
    await dialog.getByRole("combobox").click();
    await page.getByRole("option", { name: "Model One" }).click();
    await expect(dialog.getByRole("combobox")).toContainText("Model One");

    // The pick is persisted to localStorage so the suggestions request uses it.
    const stored = await page.evaluate(() => {
      const raw = window.localStorage.getItem("deerflow.local-settings");
      return raw ? JSON.parse(raw) : null;
    });
    expect(stored?.suggestions).toEqual({ enabled: true, modelName: "m1" });
  });

  test("toggle is disabled when the server master switch is off", async ({
    page,
  }) => {
    mockLangGraphAPI(page); // default mock: /api/suggestions/config -> { enabled: false }

    const dialog = await openSuggestionsSettings(page);

    const toggle = dialog.getByRole("switch", {
      name: "Follow-up suggestions",
    });
    await expect(toggle).toBeVisible({ timeout: 15_000 });
    await expect(toggle).toBeDisabled();
  });
});
