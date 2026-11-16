import { expect, test, type Page } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

// The folder ledger: which conversations created or edited the folders of
// shared writable mounts, and the offer to delete one once no conversation
// uses it any more. The Gateway is mocked; mock-api.ts answers every ledger
// route with "not tracked" unless a test routes it, as these do.

const CHAT = "00000000-0000-0000-0000-000000005252";
const OTHER = "00000000-0000-0000-0000-000000005253";
const FOLDER_ID = "a".repeat(32);
const LEGACY_ID = "b".repeat(32);
const ROOT = "/mnt/user-data";
const RECENT = "2026-11-15T09:00:00Z";

const FOLDER = {
  id: FOLDER_ID,
  path: "/mnt/projects/acme-site",
  name: "acme-site",
  mount_path: "/mnt/projects",
  kind: "dir",
  role: "created",
  created_here: true,
  created_attribution: "observed_create",
  first_at: RECENT,
  last_at: RECENT,
  writes: 4,
  edits: 9,
  shell_ops: 0,
  other_live_threads: 1,
  host_visible: true,
};

const THREADS = [
  {
    thread_id: CHAT,
    title: "Build the site",
    messages: [
      { type: "human", id: "human", content: "Build the landing page" },
      { type: "ai", id: "ai", content: "It is in /mnt/projects/acme-site." },
    ],
  },
  { thread_id: OTHER, title: "Something else" },
];

async function routeThreadFiles(page: Page) {
  await page.route(new RegExp(`/api/threads/${CHAT}/files\\?`), (route) =>
    route.fulfill({
      json: {
        path: ROOT,
        exists: true,
        entries: [
          {
            name: "outputs",
            path: `${ROOT}/outputs`,
            kind: "directory",
            size: null,
            modified_at: RECENT,
          },
        ],
        truncated: false,
        total: 1,
      },
    }),
  );
}

async function routeThreadFolders(page: Page) {
  await page.route(`**/api/folder-ledger/threads/${CHAT}/folders`, (route) =>
    route.fulfill({ json: { available: true, folders: [FOLDER] } }),
  );
}

test("the chat header labels the Files button", async ({ page }) => {
  mockLangGraphAPI(page, { threads: THREADS });
  await page.goto(`/workspace/chats/${CHAT}`);
  const files = page.getByRole("button", { name: "Show files" });
  await expect(files).toBeVisible();
  await expect(files).toHaveText("Files");
});

test("?panel=files opens the Files tab with the chat's shared folders", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: THREADS });
  await routeThreadFiles(page);
  await routeThreadFolders(page);
  await page.route(`**/api/folder-ledger/folders/${FOLDER_ID}`, (route) =>
    route.fulfill({
      json: {
        folder: { ...FOLDER, role: null },
        threads: [
          {
            thread_id: CHAT,
            own: true,
            title: "Build the site",
            role: "created",
            first_at: RECENT,
            last_at: RECENT,
            deleted: false,
          },
          {
            thread_id: "other-0123456789abcdef",
            own: false,
            title: null,
            role: "edited",
            first_at: RECENT,
            last_at: RECENT,
            deleted: false,
          },
        ],
        events: [
          {
            thread_id: CHAT,
            run_id: "run-1",
            op: "write",
            rel_path: "acme-site/index.html",
            ts: RECENT,
          },
        ],
      },
    }),
  );

  await page.goto(`/workspace/chats/${CHAT}?panel=files`);

  const panel = page.locator("#artifacts");
  await expect(panel.getByRole("tab", { name: "Files" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  // The parameter is consumed, so a reload does not reopen the panel.
  await expect(page).toHaveURL(new RegExp(`/workspace/chats/${CHAT}$`));
  await expect(
    panel.getByText(
      "This chat's own folder, /mnt/user-data, is deleted together with the chat.",
    ),
  ).toBeVisible();
  await expect(
    panel.getByRole("tree", { name: "Files in this chat" }),
  ).toBeVisible();

  const shared = panel.getByRole("region", { name: "Shared folders" });
  const row = shared.getByRole("button", {
    name: "Show details of acme-site",
  });
  await expect(row).toContainText("Created here");
  await expect(row).toContainText("Also used by 1 other chat");

  await row.click();
  const details = page.getByRole("dialog", { name: "acme-site" });
  await expect(details).toContainText("A conversation created it.");
  await expect(details).toContainText("This chat");
  await expect(details).toContainText("Another user's conversation");
  await expect(details.getByRole("list", { name: "Edit log" })).toContainText(
    "acme-site/index.html",
  );
});

test("deleting the last chat that used a folder offers to delete it, unticked", async ({
  page,
}) => {
  mockLangGraphAPI(page, { threads: THREADS });
  await routeThreadFolders(page);
  const orphanQueries: unknown[] = [];
  await page.route("**/api/folder-ledger/orphans", (route) => {
    orphanQueries.push(route.request().postDataJSON());
    return route.fulfill({
      json: {
        available: true,
        orphans: [
          {
            id: FOLDER_ID,
            path: FOLDER.path,
            name: FOLDER.name,
            mount_path: FOLDER.mount_path,
            created_by_thread_id: CHAT,
            created_attribution: "observed_create",
            last_at: RECENT,
            writes: 4,
            edits: 9,
            deletable: true,
            reason: null,
          },
          {
            id: LEGACY_ID,
            path: "/mnt/projects/legacy",
            name: "legacy",
            mount_path: "/mnt/projects",
            created_by_thread_id: null,
            created_attribution: "preexisting",
            last_at: RECENT,
            writes: 0,
            edits: 2,
            deletable: false,
            reason: "preexisting",
          },
        ],
      },
    });
  });
  const folderDeletes: string[] = [];
  await page.route("**/api/folder-ledger/folders/*", (route) => {
    if (route.request().method() !== "DELETE") return route.fallback();
    folderDeletes.push(route.request().url());
    return route.fulfill({ json: { deleted: true } });
  });

  // Delete the chat from the sidebar while another chat is open.
  await page.goto(`/workspace/chats/${OTHER}`);
  const link = page.locator(
    `a[data-sidebar="menu-button"][href="/workspace/chats/${CHAT}"]`,
  );
  await link.hover();
  await link.locator("xpath=..").getByRole("button", { name: "More" }).click();
  await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
  const confirm = page.getByRole("dialog", { name: "Delete chat" });
  await expect(confirm).toContainText(
    "its own folder (/mnt/user-data) with every file in it",
  );
  await expect(confirm).toContainText(
    "It used these shared folders, which are kept: acme-site.",
  );
  await confirm.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(confirm).toBeHidden();

  const offer = page.getByRole("dialog", {
    name: "2 shared folders are no longer used",
  });
  await expect(offer).toBeVisible();
  expect(orphanQueries).toEqual([{ thread_ids: [CHAT] }]);
  await expect(offer.getByRole("button", { name: "Keep" })).toBeFocused();
  const box = offer.getByRole("checkbox", { name: "Delete acme-site" });
  await expect(box).not.toBeChecked();
  // A folder that existed before any conversation is listed, never offered.
  await expect(offer.getByRole("checkbox")).toHaveCount(1);
  await expect(offer).toContainText(
    "Existed before a conversation used it, so it is never deleted from here.",
  );
  await expect(
    offer.getByRole("button", { name: "Delete 0 folders" }),
  ).toBeDisabled();
  expect(folderDeletes).toEqual([]);

  await box.check();
  await offer.getByRole("button", { name: "Delete 1 folder" }).click();
  await expect(offer).toBeHidden();
  await expect(page.getByText("Deleted 1 folder.")).toBeVisible();
  expect(folderDeletes).toHaveLength(1);
  expect(new URL(folderDeletes[0]!).pathname).toBe(
    `/api/folder-ledger/folders/${FOLDER_ID}`,
  );
  expect(new URL(folderDeletes[0]!).searchParams.get("confirm_name")).toBe(
    "acme-site",
  );
});
