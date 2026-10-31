import { expect, test, type Page } from "@playwright/test";

import { handleRunStream, mockLangGraphAPI } from "./utils/mock-api";

/**
 * Double Plus Ultracode (fork feature, FORK.md §44).
 *
 * The unit tests pin each piece (the run context, the limits, the grouping);
 * this pins the chain a user sees: the composer offers the mode only where the
 * Script workflows extension runs, picking it puts the extension's run option
 * on the wire with the Settings limits, a remembered selection falls back to
 * Ultra visibly, and a workflow's posted result reads as the extension's card.
 */

const WORKFLOWS = {
  namespace: "community.workflows",
  module: null,
  entry: null,
  title: "Script workflows / 脚本工作流",
  description: "",
  settings: { enabled: true },
};

function plugins(page: Page, list: unknown[]) {
  // Registered after mockLangGraphAPI, so it wins over the default empty list.
  void page.route("**/api/plugins", (route) => route.fulfill({ json: list }));
}

async function composer(page: Page) {
  const textarea = page.getByPlaceholder(/how can i assist you/i);
  await expect(textarea).toBeVisible({ timeout: 20_000 });
  return textarea;
}

test.describe("Double Plus Ultracode", () => {
  test("is offered with Script workflows and sends its run option", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    plugins(page, [WORKFLOWS]);
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "deerflow.local-settings",
        JSON.stringify({
          context: { mode: "pro", model_name: "m1" },
          ultracode: { maxAgents: 12, maxParallel: 3 },
        }),
      );
    });
    let context: Record<string, unknown> | undefined;
    await page.route("**/runs/stream", (route) => {
      context = (
        route.request().postDataJSON() as { context?: Record<string, unknown> }
      ).context;
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");
    const textarea = await composer(page);
    await page.getByRole("button").filter({ hasText: /^Pro$/ }).first().click();
    await page
      .getByRole("menuitem")
      .filter({ hasText: "Double Plus Ultracode" })
      .click();
    // The menu can stay open after a pick; while it is open the rest of the
    // page is hidden from the accessibility tree.
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("button").filter({ hasText: /^Double Plus Ultracode$/ }),
    ).toBeVisible();

    await textarea.fill("audit every route for missing permission checks");
    await textarea.press("Enter");
    await expect
      .poll(() => context?.plugin_options)
      .toEqual({
        "community.workflows": {
          mode: "ultracode",
          max_agents: 12,
          max_parallel: 3,
        },
      });
    expect(context?.subagent_enabled).toBe(true);
    expect(context?.is_plan_mode).toBe(true);
  });

  test("is not offered without the extension, and a remembered pick falls back to Ultra", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    plugins(page, []);
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "deerflow.local-settings",
        JSON.stringify({ context: { mode: "ultracode", model_name: "m1" } }),
      );
    });
    let context: Record<string, unknown> | undefined;
    await page.route("**/runs/stream", (route) => {
      context = (
        route.request().postDataJSON() as { context?: Record<string, unknown> }
      ).context;
      return handleRunStream(route);
    });

    await page.goto("/workspace/chats/new");
    const textarea = await composer(page);
    await expect(
      page.getByText(/Double Plus Ultracode needs the Script workflows/),
    ).toBeVisible();
    const trigger = page.getByRole("button").filter({ hasText: /^Ultra$/ });
    await expect(trigger.first()).toBeVisible();
    await trigger.first().click();
    await expect(
      page.getByRole("menuitem").filter({ hasText: "Double Plus Ultracode" }),
    ).toHaveCount(0);
    await page.keyboard.press("Escape");

    await textarea.fill("hello");
    await textarea.press("Enter");
    await expect.poll(() => context !== undefined).toBe(true);
    expect(context?.plugin_options).toBeUndefined();
  });

  test("Settings → Subagents stores both limits for the next run", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    plugins(page, [WORKFLOWS]);
    await page.goto("/workspace/chats/new?settings=subagents");
    const section = page.getByTestId("ultracode-limits");
    await expect(section).toBeVisible({ timeout: 20_000 });

    const agents = section.getByLabel("Agents per workflow");
    await agents.fill("20");
    await agents.press("Enter");
    const parallel = section.getByLabel("Agents at once");
    // Out of range snaps back instead of saving a silently different value.
    await parallel.fill("99");
    await parallel.press("Enter");
    await expect(parallel).toHaveValue("8");
    await parallel.fill("4");
    await parallel.press("Enter");

    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (
              JSON.parse(
                window.localStorage.getItem("deerflow.local-settings") ?? "{}",
              ) as { ultracode?: unknown }
            ).ultracode,
        ),
      )
      .toEqual({ maxAgents: 20, maxParallel: 4 });
  });

  test("a posted workflow result reads as the extension's card", async ({
    page,
  }) => {
    const threadId = "ultracode-thread";
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: threadId,
          title: "Route audit",
          messages: [
            {
              id: "h1",
              type: "human",
              content: "audit every route",
            },
            {
              id: "a1",
              type: "ai",
              content: "A workflow is running; the result will appear here.",
            },
            {
              id: "workflow-result-1",
              type: "human",
              content:
                '[Workflow result] route-audit (abc123) ended: completed.\nPosted automatically by the Script workflows extension.\n```json\n{"findings": 2}\n```',
              additional_kwargs: {
                deerflow_extension_origin: { namespace: "community.workflows" },
              },
            },
            {
              id: "a2",
              type: "ai",
              content: "Two routes lacked permission checks.",
            },
          ],
        },
      ],
    });
    plugins(page, [WORKFLOWS]);
    // The cost header only renders when the Gateway reports token usage on.
    void page.route("**/api/models", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({
            json: { models: [], token_usage: { enabled: true } },
          })
        : route.fallback(),
    );
    void page.route("**/api/threads/*/token-usage", (route) =>
      route.fulfill({
        json: {
          thread_id: threadId,
          total_tokens: 1000,
          total_input_tokens: 800,
          total_output_tokens: 200,
          total_runs: 2,
          by_model: {},
          by_caller: { lead_agent: 1000, subagent: 0, middleware: 0 },
          total_cost: 0.5,
          currency: "USD",
          steps: [],
          delegated: {
            threads: 3,
            runs: 3,
            tokens: 9000,
            cost: 1.25,
            promo_cost: null,
          },
          context_usage: null,
        },
      }),
    );

    await page.goto(`/workspace/chats/${threadId}`);
    const card = page.getByTestId("extension-message");
    await expect(card).toHaveCount(1, { timeout: 20_000 });
    await expect(card).toContainText("Posted by Script workflows");
    await expect(card).toContainText(
      "[Workflow result] route-audit (abc123) ended: completed.",
    );
    await expect(card.getByTestId("extension-message-text")).toBeHidden();
    await card.getByText("Show the full message").click();
    await expect(card.getByTestId("extension-message-text")).toContainText(
      '"findings": 2',
    );

    await page
      .getByRole("button")
      .filter({ hasText: /Tokens/ })
      .first()
      .click();
    const row = page.getByTestId("token-usage-workflow-agents");
    await expect(row).toContainText("Workflow agents");
    await expect(row).toContainText("1.25");
  });
});
