import { expect, test } from "@playwright/test";

import { mockLangGraphAPI, MOCK_THREAD_ID } from "./utils/mock-api";

/**
 * A conversation remembers its model and mode on a device that has never seen
 * it (FORK.md §36) — in the passwordless default, where no account preference
 * is ever active.
 *
 * The composer resolves a fallback model/mode the moment the model list loads.
 * On a second device that happens before the chat's own metadata arrives on
 * every chat after the first, because the model list is cached app-wide while
 * each chat's metadata is its own request. Written as the chat's own override,
 * that fallback made the recorded selection look like a local choice, so the
 * chat refused to adopt it — and the next edit then PATCHed the fallback over
 * the record, erasing it for every device.
 */
test("a chat opened on a new device shows the model and mode it recorded", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: MOCK_THREAD_ID,
        title: "Recorded workflow",
        metadata: {
          deerflow_workflow: {
            model_name: "recorded-model",
            mode: "thinking",
          },
        },
      },
    ],
  });
  let modelsServed = false;
  await page.route("**/api/models", async (route) => {
    await route.fulfill({
      json: {
        models: [
          {
            name: "first-model",
            display_name: "First Model",
            supports_thinking: true,
          },
          {
            name: "recorded-model",
            display_name: "Recorded Model",
            supports_thinking: true,
          },
        ],
      },
    });
    modelsServed = true;
  });
  // Hold this chat's metadata until the composer has resolved its fallback,
  // which is the order a second device sees.
  let releaseMetadata!: () => void;
  const metadataGate = new Promise<void>((resolve) => {
    releaseMetadata = resolve;
  });
  await page.route(
    `**/api/langgraph/threads/${MOCK_THREAD_ID}`,
    async (route) => {
      if (route.request().method() === "GET") {
        await metadataGate;
      }
      await route.fallback();
    },
  );
  const workflowPatches: unknown[] = [];
  await page.route(`**/api/threads/${MOCK_THREAD_ID}`, async (route) => {
    if (route.request().method() === "PATCH") {
      const body = route.request().postDataJSON() as {
        metadata?: Record<string, unknown>;
      };
      if (body.metadata && "deerflow_workflow" in body.metadata) {
        workflowPatches.push(body.metadata.deerflow_workflow);
      }
    }
    await route.fallback();
  });

  await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
  await expect.poll(() => modelsServed, { timeout: 15_000 }).toBe(true);
  // The fallback is showing: nothing better is known yet.
  await expect(page.getByRole("button", { name: /First Model/ })).toBeVisible({
    timeout: 15_000,
  });
  await expect(
    page.getByRole("button", { name: "Pro", exact: true }),
  ).toBeVisible();

  releaseMetadata();

  await expect(
    page.getByRole("button", { name: /Recorded Model/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reasoning", exact: true }),
  ).toBeVisible();
  // Adopting the record must not write it back, and the fallback must never
  // reach the server as this conversation's choice.
  await page.waitForTimeout(500);
  expect(workflowPatches).toEqual([]);
});
