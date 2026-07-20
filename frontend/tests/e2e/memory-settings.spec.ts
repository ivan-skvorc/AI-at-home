import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const EMPTY_SECTION = { summary: "", updatedAt: "" };

const EMPTY_MEMORY = {
  version: "1.0",
  lastUpdated: "",
  user: {
    workContext: EMPTY_SECTION,
    personalContext: EMPTY_SECTION,
    topOfMind: EMPTY_SECTION,
  },
  history: {
    recentMonths: EMPTY_SECTION,
    earlierContext: EMPTY_SECTION,
    longTermBackground: EMPTY_SECTION,
  },
  facts: [],
};

async function mockMemoryData(page: Page) {
  await page.route("**/api/memory", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(EMPTY_MEMORY),
        })
      : route.fallback(),
  );
}

// Server master switch ON so the per-user toggle is usable (not greyed out).
async function mockMemoryEnabledServer(page: Page) {
  await page.route("**/api/memory/config", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ enabled: true }),
        })
      : route.fallback(),
  );
}

async function openMemorySettings(page: Page) {
  await page.goto("/workspace/chats/new");
  const sidebar = page.locator("[data-sidebar='sidebar']");
  await sidebar.getByRole("button", { name: /Settings and more/ }).click();
  await page.getByRole("menuitem", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Memory" }).click();
  return dialog;
}

test.describe("Memory settings (enable toggle)", () => {
  test("defaults off, and enabling it persists to localStorage", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockMemoryData(page);
    await mockMemoryEnabledServer(page);

    const dialog = await openMemorySettings(page);

    // Toggle is present and OFF by default (privacy-preserving default).
    const toggle = dialog.getByRole("switch", { name: "Enable memory" });
    await expect(toggle).toBeVisible({ timeout: 15_000 });
    await expect(toggle).not.toBeChecked();

    // Turn it on → persisted so the run context sends memory_enabled=true.
    await toggle.click();
    await expect(toggle).toBeChecked();

    const stored = await page.evaluate(() => {
      const raw = window.localStorage.getItem("deerflow.local-settings");
      return raw ? JSON.parse(raw) : null;
    });
    expect(stored?.memory).toEqual({ enabled: true });
  });

  test("toggle is disabled when the server master switch is off", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockMemoryData(page);
    // Server master switch OFF.
    await page.route("**/api/memory/config", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ enabled: false }),
          })
        : route.fallback(),
    );

    const dialog = await openMemorySettings(page);

    const toggle = dialog.getByRole("switch", { name: "Enable memory" });
    await expect(toggle).toBeVisible({ timeout: 15_000 });
    await expect(toggle).toBeDisabled();
  });
});
