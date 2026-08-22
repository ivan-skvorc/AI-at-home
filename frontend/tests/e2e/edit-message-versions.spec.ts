import { expect, test } from "@playwright/test";

import {
  MOCK_THREAD_ID,
  MOCK_THREAD_ID_2,
  MOCK_THREAD_ID_3,
  mockLangGraphAPI,
} from "./utils/mock-api";

const CONVERSATION = [
  {
    type: "human",
    id: "human-1",
    content: [{ type: "text", text: "First question" }],
  },
  {
    type: "ai",
    id: "ai-1",
    content: "First answer",
  },
  {
    type: "human",
    id: "human-2",
    content: [{ type: "text", text: "Second question" }],
  },
  {
    type: "ai",
    id: "ai-2",
    content: "Second answer",
  },
];

test.describe("Edit a message into a hidden version", () => {
  test("replays the conversation from the edited turn and keeps the original one switch away", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      // The point of the edit is that the version inherits the turns before it,
      // so the run must not wipe the branched history the way a fresh chat does.
      appendRunMessagesToHistory: true,
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Original chat",
          messages: CONVERSATION,
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);

    const editedTurn = page.locator('[data-message-id="human-2"]');
    await expect(editedTurn).toBeVisible();
    await editedTurn.hover();
    await editedTurn.getByRole("button", { name: /edit message/i }).click();

    const editor = editedTurn.getByRole("textbox");
    await expect(editor).toHaveValue("Second question");
    await editor.fill("Second question, rephrased");
    await editedTurn.getByRole("button", { name: /save and send/i }).click();

    // The edit lands in a *new* thread carrying the history up to the previous
    // turn — the answer it replaces must be gone.
    await expect(page).toHaveURL(
      new RegExp(`/workspace/chats/${MOCK_THREAD_ID_2}$`),
    );
    await expect(page.getByText("First answer")).toBeVisible();
    await expect(page.getByText("Second question, rephrased")).toBeVisible();
    await expect(page.getByText("Second answer")).toHaveCount(0);

    // One conversation, one sidebar entry — and it now opens the edited version.
    await expect(
      page.locator(`a[href="/workspace/chats/${MOCK_THREAD_ID_2}"]`),
    ).toHaveCount(1);
    await expect(
      page.locator(`a[href="/workspace/chats/${MOCK_THREAD_ID}"]`),
    ).toHaveCount(0);

    const switcher = page.getByTestId("message-version-switcher");
    await expect(switcher).toContainText("2/2");

    await switcher.getByRole("button", { name: /previous version/i }).click();

    await expect(page).toHaveURL(
      new RegExp(`/workspace/chats/${MOCK_THREAD_ID}$`),
    );
    await expect(page.getByText("Second answer")).toBeVisible();
    await expect(page.getByTestId("message-version-switcher")).toContainText(
      "1/2",
    );
  });

  test("edits an answer into a version that keeps its prompt and runs nothing", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      appendRunMessagesToHistory: true,
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Original chat",
          messages: CONVERSATION,
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);

    const answer = page.locator('[data-message-id="ai-2"]');
    await expect(answer).toBeVisible();
    await answer.hover();
    await answer.getByRole("button", { name: /edit answer/i }).click();

    const editor = answer.getByRole("textbox");
    await expect(editor).toHaveValue("Second answer");
    await editor.fill("Second answer, in my words");
    // Saving an answer sends nothing, so the button must not say it will.
    await answer.getByRole("button", { name: /save version/i }).click();

    await expect(page).toHaveURL(
      new RegExp(`/workspace/chats/${MOCK_THREAD_ID_2}$`),
    );

    // The version carries the question *and* the rewritten answer: an answer
    // edit branches at its own turn, unlike a prompt edit which stops short of
    // the turn it replaces.
    await expect(page.getByText("Second question")).toBeVisible();
    await expect(page.getByText("Second answer, in my words")).toBeVisible();
    await expect(page.getByText("Second answer", { exact: true })).toHaveCount(
      0,
    );

    // Still one conversation in the sidebar, and the original is one switch away.
    await expect(
      page.locator(`a[href="/workspace/chats/${MOCK_THREAD_ID_2}"]`),
    ).toHaveCount(1);

    const switcher = page.getByTestId("message-version-switcher");
    await expect(switcher).toContainText("2/2");

    await switcher.getByRole("button", { name: /previous version/i }).click();
    await expect(page).toHaveURL(
      new RegExp(`/workspace/chats/${MOCK_THREAD_ID}$`),
    );
    await expect(
      page.getByText("Second answer", { exact: true }),
    ).toBeVisible();
  });

  test("edits the first message by starting the version from an empty conversation", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      appendRunMessagesToHistory: true,
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Original chat",
          messages: CONVERSATION.slice(0, 2),
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);

    const firstTurn = page.locator('[data-message-id="human-1"]');
    await expect(firstTurn).toBeVisible();
    await firstTurn.hover();
    await firstTurn.getByRole("button", { name: /edit message/i }).click();

    const editor = firstTurn.getByRole("textbox");
    await editor.fill("First question, rephrased");
    await firstTurn.getByRole("button", { name: /save and send/i }).click();

    // There is no assistant turn to branch from, so the version is a brand new
    // thread rather than a branch — the switcher must still find it.
    await expect(page).toHaveURL(
      new RegExp(`/workspace/chats/${MOCK_THREAD_ID_3}$`),
    );
    await expect(page.getByText("First question, rephrased")).toBeVisible();
    await expect(page.getByText("First answer")).toHaveCount(0);
    await expect(page.getByTestId("message-version-switcher")).toContainText(
      "2/2",
    );
  });

  test("does not offer an edit while the conversation has no settled turn before it", async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: MOCK_THREAD_ID,
          title: "Tool chat",
          messages: [
            {
              type: "human",
              id: "human-1",
              content: [{ type: "text", text: "Use a tool" }],
            },
            {
              type: "ai",
              id: "ai-tool",
              content: "",
              tool_calls: [
                { id: "tool-call-1", name: "write_todos", args: { todos: [] } },
              ],
            },
            {
              type: "tool",
              id: "tool-1",
              name: "write_todos",
              tool_call_id: "tool-call-1",
              content: "Todos updated",
            },
            {
              type: "human",
              id: "human-2",
              content: [{ type: "text", text: "Follow up" }],
            },
          ],
        },
      ],
    });

    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);

    // The first turn always branches from the start of the conversation, so it
    // stays editable; the second has no settled assistant turn to fork from.
    const firstTurn = page.locator('[data-message-id="human-1"]');
    await expect(firstTurn).toBeVisible();
    await firstTurn.hover();
    await expect(
      firstTurn.getByRole("button", { name: /edit message/i }),
    ).toBeVisible();

    const secondTurn = page.locator('[data-message-id="human-2"]');
    await secondTurn.hover();
    await expect(
      secondTurn.getByRole("button", { name: /edit message/i }),
    ).toHaveCount(0);
  });
});
