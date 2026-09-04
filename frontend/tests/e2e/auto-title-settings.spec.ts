import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

/**
 * Automatic conversation renaming (fork feature, FORK.md §33).
 *
 * The unit tests pin the wire shape; this pins that the switch and its picker
 * are reachable at all, and that what the user clicks is what lands in
 * localStorage — the only place the preference lives before a run reads it.
 */

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

async function openAutoTitleSettings(page: Page) {
  await page.goto("/workspace/chats/new");
  const sidebar = page.locator("[data-sidebar='sidebar']");
  await sidebar.getByRole("button", { name: /Settings and more/ }).click();
  await page.getByRole("menuitem", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Conversation titles" }).click();
  return dialog;
}

function readStoredAutoTitle(page: Page) {
  return page.evaluate(() => {
    const raw = window.localStorage.getItem("deerflow.local-settings");
    return raw
      ? (JSON.parse(raw) as { autoTitle?: Record<string, unknown> }).autoTitle
      : null;
  });
}

test.describe("Conversation titles settings", () => {
  test("defaults on, and the model pick persists", async ({ page }) => {
    mockLangGraphAPI(page);
    await mockModels(page);

    const dialog = await openAutoTitleSettings(page);

    // ON by default: a fresh install keeps naming conversations, as it did
    // before the switch existed.
    const toggle = dialog.getByRole("switch", {
      name: "Automatic conversation titles",
    });
    await expect(toggle).toBeVisible({ timeout: 15_000 });
    await expect(toggle).toBeChecked();

    // The picker starts on "Server default" — the state that sends no model key
    // at all, so config.yaml keeps deciding.
    const picker = dialog.locator('[data-slot="model-select"]');
    await expect(picker).toContainText("Server default");

    // Targeted by the shared picker's own `data-slot`, never by the ARIA role of
    // whichever primitive is underneath it (FORK.md's shared-control rule).
    await picker.click();
    await page.getByRole("option", { name: "Model One" }).click();
    await expect(picker).toContainText("Model One");
    expect(await readStoredAutoTitle(page)).toEqual({
      enabled: true,
      modelName: "m1",
    });

    // "No model call" is a distinct third state, stored as the empty string.
    await picker.click();
    await page.getByRole("option", { name: "No model call" }).click();
    expect(await readStoredAutoTitle(page)).toEqual({
      enabled: true,
      modelName: "",
    });
  });

  test("turning it off hides the model picker", async ({ page }) => {
    mockLangGraphAPI(page);
    await mockModels(page);

    const dialog = await openAutoTitleSettings(page);
    const toggle = dialog.getByRole("switch", {
      name: "Automatic conversation titles",
    });
    await expect(toggle).toBeVisible({ timeout: 15_000 });

    await toggle.click();
    await expect(toggle).not.toBeChecked();
    // Nothing is going to write a title, so there is no model to pick for it.
    await expect(dialog.locator('[data-slot="model-select"]')).toHaveCount(0);
    expect(await readStoredAutoTitle(page)).toMatchObject({ enabled: false });
  });

  test("toggle is disabled when the server master switch is off", async ({
    page,
  }) => {
    mockLangGraphAPI(page, { features: { autoTitleEnabled: false } });
    await mockModels(page);

    const dialog = await openAutoTitleSettings(page);
    const toggle = dialog.getByRole("switch", {
      name: "Automatic conversation titles",
    });
    await expect(toggle).toBeVisible({ timeout: 15_000 });
    await expect(toggle).toBeDisabled();
    // Explained, not silently ignored.
    await expect(
      dialog.getByText(/title\.enabled in config\.yaml/),
    ).toBeVisible();
  });
});
