import { expect, test, type Page, type Request } from "@playwright/test";

import { handleRunStream, mockLangGraphAPI } from "./utils/mock-api";

/**
 * Automatic conversation renaming (fork feature, FORK.md §33).
 *
 * The unit tests pin the wire shape; this pins that the switch and its picker
 * are reachable at all, and that what the user clicks reaches both places the
 * preference lives: the account (`PUT /api/settings/auto-title`), which the
 * Gateway applies to runs from every device, channel and extension, and this
 * browser's copy, which the next run from here carries in its context.
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

/** The next save of the account preference, to assert what it sent. */
function nextAutoTitleSave(page: Page): Promise<Request> {
  return page.waitForRequest(
    (request) =>
      request.method() === "PUT" &&
      new URL(request.url()).pathname.endsWith("/api/settings/auto-title"),
  );
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
    let save = nextAutoTitleSave(page);
    await picker.click();
    await page.getByRole("option", { name: "Model One" }).click();
    await expect(picker).toContainText("Model One");
    expect(await readStoredAutoTitle(page)).toEqual({
      enabled: true,
      modelName: "m1",
    });
    expect((await save).postDataJSON()).toEqual({
      enabled: true,
      model_name: "m1",
    });

    // "No model call" is a distinct third state, stored as the empty string —
    // on the account too, where an omitted key would mean "server default".
    save = nextAutoTitleSave(page);
    await picker.click();
    await page.getByRole("option", { name: "No model call" }).click();
    expect(await readStoredAutoTitle(page)).toEqual({
      enabled: true,
      modelName: "",
    });
    expect((await save).postDataJSON()).toEqual({
      enabled: true,
      model_name: "",
    });
  });

  test("turning it off saves it to the account and the next run carries it", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockModels(page);
    let context: Record<string, unknown> | undefined;
    await page.route("**/runs/stream", (route) => {
      const body = route.request().postDataJSON() as {
        context?: Record<string, unknown>;
      };
      context = body.context;
      return handleRunStream(route);
    });

    const dialog = await openAutoTitleSettings(page);
    const toggle = dialog.getByRole("switch", {
      name: "Automatic conversation titles",
    });
    await expect(toggle).toBeVisible({ timeout: 15_000 });

    const save = nextAutoTitleSave(page);
    await toggle.click();
    await expect(toggle).not.toBeChecked();
    // Nothing is going to write a title, so there is no model to pick for it.
    await expect(dialog.locator('[data-slot="model-select"]')).toHaveCount(0);
    expect(await readStoredAutoTitle(page)).toMatchObject({ enabled: false });
    // The account copy is what IM channels, other devices and extension runs
    // get: an opt-out that stayed in this browser is the bug this fixes.
    expect((await save).postDataJSON()).toEqual({ enabled: false });

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 20_000 });
    await textarea.fill("hello");
    await textarea.press("Enter");
    await expect.poll(() => context?.auto_title_enabled).toBe(false);
    expect(context).not.toHaveProperty("auto_title_model_name");
  });

  test("a preference saved on another device is the one this browser uses", async ({
    page,
  }) => {
    // A fresh browser has the local default (on). The account says off, and
    // the account wins, or a new device, the PWA or another origin would
    // start renaming conversations again.
    mockLangGraphAPI(page, { autoTitlePreference: { enabled: false } });
    await mockModels(page);

    const dialog = await openAutoTitleSettings(page);
    const toggle = dialog.getByRole("switch", {
      name: "Automatic conversation titles",
    });
    await expect(toggle).toBeVisible({ timeout: 15_000 });
    await expect(toggle).not.toBeChecked();
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
