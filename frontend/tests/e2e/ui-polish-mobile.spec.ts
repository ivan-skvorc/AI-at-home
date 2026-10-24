import { expect, test } from "@playwright/test";

import { MOCK_THREAD_ID, mockLangGraphAPI } from "./utils/mock-api";

test.describe("UI polish mobile regressions", () => {
  test("workspace exposes mobile sidebar navigation from the chat header", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    mockLangGraphAPI(page);

    await page.goto("/workspace/chats/new");

    await page.getByRole("button", { name: /toggle sidebar/i }).click();

    await expect(page.getByRole("link", { name: /new chat/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /agents/i })).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(375);
  });

  test("mobile artifacts open in a drawer without horizontal overflow", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Thread with artifact",
          artifacts: ["reports/mobile-summary.md"],
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    await page.getByTestId("artifact-trigger").click();

    await expect(
      page.getByRole("dialog", { name: /artifacts/i }),
    ).toBeVisible();
    await expect(page.getByText("mobile-summary.md")).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
      .toBeLessThanOrEqual(375);
  });

  test("global focus ring tokens are visible in light and dark themes", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await page.goto("/workspace/chats/new");

    // Toggle the theme class and read the token in one synchronous task.
    // next-themes applies the resolved theme from a mount effect that can run
    // after page.goto() resolves; with the toggle and the read in separate
    // evaluate() calls, that effect could strip "dark" in between.
    const readRing = (theme: "light" | "dark") =>
      page.evaluate((mode) => {
        const root = document.documentElement;
        const hadDark = root.classList.contains("dark");
        root.classList.toggle("dark", mode === "dark");
        const ring = getComputedStyle(root).getPropertyValue("--ring").trim();
        root.classList.toggle("dark", hadDark);
        return ring;
      }, theme);

    const lightRing = await readRing("light");
    expect(lightRing).not.toBe("transparent");
    expect(lightRing).not.toBe("");

    const darkRing = await readRing("dark");
    expect(darkRing).not.toBe("transparent");
    expect(darkRing).not.toBe("");

    // The two themes must resolve to different ring tokens, otherwise the test
    // would pass trivially if <html> were stuck in one mode.
    expect(darkRing).not.toBe(lightRing);
  });
});
