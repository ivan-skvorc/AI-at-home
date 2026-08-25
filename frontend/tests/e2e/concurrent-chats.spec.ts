import { expect, test, type Route } from "@playwright/test";

import {
  handleRunStream,
  mockLangGraphAPI,
  MOCK_THREAD_ID,
  MOCK_THREAD_ID_2,
} from "./utils/mock-api";

/**
 * Concurrent chats: a prompt in a second chat while the first is still
 * answering.
 *
 * The two halves of the promise are asserted together here because they only
 * work as a pair:
 *
 * 1. The run request carries `on_disconnect: "continue"`, so the Gateway does
 *    not cancel the first chat's run when leaving the chat tears its SSE
 *    stream down (the Gateway's own default is `"cancel"`).
 * 2. Leaving a chat that is still answering pins it as a keep-alive tab rather
 *    than dropping its slot, so the answer keeps streaming into a live,
 *    visibly-running background tab instead of a torn-down one.
 */

type Answer = { type: "ai"; id: string; content: string };

const ANSWERS: Record<string, Answer> = {
  [MOCK_THREAD_ID]: {
    type: "ai",
    id: "ai-first",
    content: "Answer from the first chat",
  },
  [MOCK_THREAD_ID_2]: {
    type: "ai",
    id: "ai-second",
    content: "Answer from the second chat",
  },
};

/**
 * Both chats start empty. A custom run-stream handler has to keep the mock
 * thread's transcript in step with what it streams (the default handler does
 * that itself), and starting from nothing keeps that bookkeeping to one turn.
 */
function makeThreads() {
  return [
    {
      thread_id: MOCK_THREAD_ID,
      title: "First conversation",
      updated_at: "2025-06-01T12:00:00Z",
      messages: [] as unknown[],
    },
    {
      thread_id: MOCK_THREAD_ID_2,
      title: "Second conversation",
      updated_at: "2025-06-02T12:00:00Z",
      messages: [] as unknown[],
    },
  ];
}

function threadIdOf(route: Route): string {
  return (
    /\/threads\/([^/]+)\/runs\/stream/.exec(
      new URL(route.request().url()).pathname,
    )?.[1] ?? ""
  );
}

function requestBody(route: Route): {
  on_disconnect?: unknown;
  input?: { messages?: unknown[] };
} {
  try {
    return route.request().postDataJSON() as {
      on_disconnect?: unknown;
      input?: { messages?: unknown[] };
    };
  } catch {
    return {};
  }
}

test("a second chat answers while the first one is still working", async ({
  page,
}) => {
  const threads = makeThreads();
  const streamedThreads: string[] = [];
  const disconnectModes: unknown[] = [];
  let releaseFirstAnswer!: () => void;
  const firstAnswerHeld = new Promise<void>((resolve) => {
    releaseFirstAnswer = resolve;
  });

  const runStreamHandler = async (route: Route) => {
    const threadId = threadIdOf(route);
    const body = requestBody(route);
    streamedThreads.push(threadId);
    disconnectModes.push(body.on_disconnect);

    const answer = ANSWERS[threadId]!;
    const thread = threads.find((entry) => entry.thread_id === threadId)!;
    thread.messages = [...(body.input?.messages ?? []), answer];

    if (threadId === MOCK_THREAD_ID) {
      // The first chat is still thinking for most of the test: its SSE response
      // is withheld until the end.
      await firstAnswerHeld;
    }
    return handleRunStream(route, {}, undefined, { responseMessage: answer });
  };

  mockLangGraphAPI(page, { threads, runStreamHandler });

  try {
    // 1. Ask the first chat something slow.
    await page.goto(`/workspace/chats/${MOCK_THREAD_ID}`);
    const firstComposer = page.getByPlaceholder(/how can i assist you/i);
    await expect(firstComposer).toBeVisible({ timeout: 15_000 });
    await firstComposer.fill("Take your time with this one");
    await firstComposer.press("Enter");
    await expect.poll(() => streamedThreads).toEqual([MOCK_THREAD_ID]);

    // 2. Walk over to the other chat while that answer is still coming.
    await page
      .locator("[data-sidebar='sidebar']")
      .locator(`a[href*='${MOCK_THREAD_ID_2}']`)
      .click();
    await expect(page).toHaveURL(new RegExp(MOCK_THREAD_ID_2));

    // The first chat was not torn down: it is a keep-alive tab now, both
    // instances are mounted, and the tab shows that it is still answering.
    const runningTab = page
      .getByTestId("chat-tab")
      .filter({ hasText: "First conversation" });
    await expect(runningTab).toHaveCount(1);
    await expect(runningTab.getByTestId("chat-tab-busy")).toBeVisible();
    await expect(page.locator("[data-slot-key]")).toHaveCount(2);

    // 3. The whole point: a prompt in the second chat is accepted and answered
    //    while the first chat is still unanswered.
    const secondComposer = page
      .getByPlaceholder(/how can i assist you/i)
      .locator("visible=true");
    await secondComposer.fill("Something else entirely");
    await secondComposer.press("Enter");

    await expect
      .poll(() => streamedThreads)
      .toEqual([MOCK_THREAD_ID, MOCK_THREAD_ID_2]);
    await expect(page.getByText("Answer from the second chat")).toBeVisible({
      timeout: 15_000,
    });

    // Neither run asked the Gateway to cancel on disconnect, which is what
    // makes leaving a chat safe in the first place.
    expect(disconnectModes).toEqual(["continue", "continue"]);
  } finally {
    releaseFirstAnswer();
  }

  // 4. The first chat's answer still lands, in its background tab.
  const finishedTab = page
    .getByTestId("chat-tab")
    .filter({ hasText: "First conversation" });
  await expect(finishedTab.getByTestId("chat-tab-busy")).toHaveCount(0, {
    timeout: 15_000,
  });
  await finishedTab.click();
  await expect(page.getByText("Answer from the first chat")).toBeVisible({
    timeout: 15_000,
  });
});
