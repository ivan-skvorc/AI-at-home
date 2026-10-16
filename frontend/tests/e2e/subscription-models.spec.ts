import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

test("remote model settings complete device sign-in, refresh discovery, and disconnect", async ({
  page,
}, testInfo) => {
  mockLangGraphAPI(page, { threads: [{ thread_id: MOCK_THREAD_ID }] });
  let connected = false;
  let polls = 0;
  let refreshes = 0;
  let modelReads = 0;
  const model = {
    name: "subscription-grok-test",
    model: "grok-test",
    display_name: "Grok subscription test",
  };
  await page.route("**/api/managed-models", (route) =>
    route.fulfill({ json: { models: [] } }),
  );
  await page.route("**/api/models", (route) => {
    modelReads++;
    return route.fulfill({
      json: {
        models: connected ? [model] : [],
        token_usage: { enabled: false },
      },
    });
  });
  await page.route("**/api/subscriptions", (route) =>
    route.fulfill({
      json: {
        providers: [
          {
            provider: "grok",
            connected,
            needs_reauth: false,
            models: connected ? [model] : [],
            model_count: connected ? 1 : 0,
          },
        ],
      },
    }),
  );
  await page.route("**/api/subscriptions/grok/connect", (route) =>
    route.fulfill({
      json: {
        status: "pending",
        flow_id: "flow",
        user_code: "ABCD-1234",
        verification_uri: "https://accounts.x.ai/device",
        verification_uri_complete: null,
        interval: 1,
        expires_in: 600,
      },
    }),
  );
  await page.route("**/api/subscriptions/grok/poll", (route) => {
    polls++;
    connected = true;
    return route.fulfill({
      json: { status: "connected", provider: "grok", model_count: 1 },
    });
  });
  await page.route("**/api/subscriptions/grok/refresh", (route) => {
    refreshes++;
    return route.fulfill({
      json: { status: "connected", provider: "grok", model_count: 1 },
    });
  });
  await page.route("**/api/subscriptions/grok", (route) => {
    connected = false;
    return route.fulfill({
      json: {
        status: "disconnected",
        provider: "grok",
        revocation_confirmed: true,
      },
    });
  });
  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}?settings=models`);
  const subscriptions = page.getByRole("region", { name: "Subscriptions" });
  await page.getByRole("button", { name: "Sign in to Grok" }).click();
  await expect(page.getByText("ABCD-1234")).toBeVisible();
  const before = modelReads;
  await expect(
    subscriptions.getByText("Grok subscription test", { exact: true }),
  ).toBeVisible();
  expect(polls).toBe(1);
  await expect.poll(() => modelReads).toBeGreaterThan(before);
  await page
    .getByRole("button", { name: "Refresh models", exact: true })
    .click();
  await expect.poll(() => refreshes).toBe(1);
  await subscriptions
    .getByRole("heading", { name: "Subscriptions", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: testInfo.outputPath("subscription-model-settings.png"),
  });
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  await expect(
    subscriptions.getByText("Grok subscription test", { exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Continue with ChatGPT" }).click();
  await expect(
    page.getByRole("link", { name: "Download sign-in helper" }),
  ).toHaveAttribute("href", /\/api\/subscriptions\/chatgpt\/helper$/);
  await expect(page.getByLabel("ChatGPT connection file")).toBeVisible();
});
