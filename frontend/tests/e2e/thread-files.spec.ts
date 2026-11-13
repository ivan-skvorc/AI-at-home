import { expect, test, type Route } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const THREAD_ID = "00000000-0000-0000-0000-000000005151";
const ROOT = "/mnt/user-data";
const WORKSPACE = `${ROOT}/workspace`;
const SCRIPT = `${WORKSPACE}/analysis.py`;
const SCRIPT_SOURCE = "print('hello from the sandbox')";

function listing(
  path: string,
  entries: [name: string, kind: "directory" | "file", size?: number][],
) {
  return {
    path,
    exists: true,
    entries: entries.map(([name, kind, size]) => ({
      name,
      path: `${path}/${name}`,
      kind,
      size: size ?? null,
      modified_at: "2026-11-13T09:00:00Z",
    })),
    truncated: false,
    total: entries.length,
  };
}

test("browses the thread's files and previews one from the header", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: THREAD_ID,
        title: "Sandbox files",
        messages: [
          { type: "human", id: "human", content: "Write a script" },
          { type: "ai", id: "ai", content: "The script is in the workspace." },
        ],
      },
    ],
  });
  const listed: string[] = [];
  await page.route(
    new RegExp(`/api/threads/${THREAD_ID}/files\\?`),
    (route: Route) => {
      const path = new URL(route.request().url()).searchParams.get("path");
      listed.push(path ?? "");
      if (path === ROOT) {
        return route.fulfill({
          json: listing(ROOT, [
            ["outputs", "directory"],
            ["uploads", "directory"],
            ["workspace", "directory"],
          ]),
        });
      }
      if (path === WORKSPACE) {
        return route.fulfill({
          json: listing(WORKSPACE, [
            ["analysis.py", "file", SCRIPT_SOURCE.length],
          ]),
        });
      }
      return route.fulfill({
        status: 404,
        json: { detail: "Directory not found" },
      });
    },
  );
  await page.route(`**/api/threads/${THREAD_ID}/artifacts${SCRIPT}`, (route) =>
    route.fulfill({ contentType: "text/plain", body: SCRIPT_SOURCE }),
  );

  await page.goto(`/workspace/chats/${THREAD_ID}`);
  await page.getByRole("button", { name: "Show files" }).click();

  const panel = page.locator("#artifacts");
  await expect(panel.getByRole("tab", { name: "Files" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  const tree = panel.getByRole("tree", { name: "Files in this chat" });
  const workspace = tree.getByRole("treeitem", { name: "workspace" });
  await expect(workspace).toHaveAttribute("aria-expanded", "false");
  expect(listed).toEqual([ROOT]);

  await workspace.getByText("workspace", { exact: true }).click();
  await expect(workspace).toHaveAttribute("aria-expanded", "true");
  const script = tree.getByRole("treeitem", { name: "analysis.py" });
  await expect(script).toHaveAttribute("aria-level", "2");
  expect(listed).toContain(WORKSPACE);

  await script.getByText("analysis.py", { exact: true }).click();
  await expect(panel.locator(".cm-content")).toHaveText(SCRIPT_SOURCE);
  // Workspace files are read-only: the Gateway edits outputs only.
  await expect(
    panel.getByRole("button", { name: "Edit", exact: true }),
  ).toHaveCount(0);

  // Closing the preview returns to the explorer with the folder still open.
  await panel.getByRole("button", { name: "Close", exact: true }).click();
  await expect(
    tree.getByRole("treeitem", { name: "analysis.py" }),
  ).toBeVisible();
  await expect(panel).toBeVisible();

  await panel.getByRole("tab", { name: "Artifacts" }).click();
  await expect(panel.getByText("No artifact selected")).toBeVisible();
});
