import { expect, test } from "@playwright/test";

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
    supports_tools: false,
  },
];

test.describe("Subagent dropdown (Ultra mode)", () => {
  test("renders the Subagent model selector when Ultra mode is active", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    // Override the empty default models list.
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
    // Preseed Ultra mode so the composer should render the subagent selector.
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "deerflow.local-settings",
        JSON.stringify({ context: { mode: "ultra", model_name: "m1" } }),
      );
    });

    await page.goto("/workspace/chats/new");
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible({
      timeout: 20_000,
    });

    // The subagent selector shows a "Subagent" label + "Follow lead" default.
    await expect(page.getByText("Subagent", { exact: true })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Follow lead", { exact: true })).toBeVisible();
  });

  test("selecting Ultra from the mode menu reveals the Subagent selector", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
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
    // Start in Pro so the mode trigger is easy to target, then switch to Ultra.
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "deerflow.local-settings",
        JSON.stringify({ context: { mode: "pro", model_name: "m1" } }),
      );
    });

    await page.goto("/workspace/chats/new");
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible({
      timeout: 20_000,
    });

    // Not visible while in Pro mode.
    await expect(page.getByText("Subagent", { exact: true })).toHaveCount(0);

    // Open the mode menu (trigger shows the current mode "Pro") and pick Ultra.
    await page.getByRole("button").filter({ hasText: /^Pro$/ }).first().click();
    await page.getByRole("menuitem").filter({ hasText: "Ultra" }).click();

    // Now the subagent selector appears.
    await expect(page.getByText("Subagent", { exact: true })).toBeVisible({
      timeout: 15_000,
    });
  });
});

test.describe("Subagent dropdown (narrow composer)", () => {
  test.use({ viewport: { width: 420, height: 900 } });
  test("subagent selector stays visible on a narrow composer in Ultra mode", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
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
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "deerflow.local-settings",
        JSON.stringify({ context: { mode: "ultra", model_name: "m1" } }),
      );
    });
    await page.goto("/workspace/chats/new");
    await expect(page.getByPlaceholder(/how can i assist you/i)).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText("Subagent", { exact: true })).toBeVisible({
      timeout: 15_000,
    });
  });
});
