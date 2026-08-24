/**
 * Concurrent chats: leaving a chat that is still answering must not end it.
 *
 * The unpinned "current" slot is normally dropped the moment the route moves to
 * another chat, which unmounts its instance and ends its live view. That is the
 * classic one-live-chat behavior and is fine for an idle chat — but it is
 * exactly what makes a second prompt in a second chat feel like it cancelled
 * the first one. While a slot reports a run in flight, leaving it pins it as a
 * keep-alive tab (reusing the slot key so the mounted instance survives), so
 * the answer keeps arriving in the background.
 *
 * `chat-tabs.test.ts` covers the pure model and
 * `chat-tabs-persistence.dom.test.tsx` the hydrate/persist pair; this covers the
 * provider's route/busy coordination.
 */
import { expect, rs, test, beforeEach, describe } from "@rstest/core";
import { act, render } from "@testing-library/react";

import { MAX_CHAT_TABS } from "@/core/threads/chat-tabs";

const authState = rs.hoisted(() => ({
  user: { id: "default" } as { id: string } | null,
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: authState.user }),
}));

rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

rs.mock("@/core/threads/chat-tabs-api", () => ({
  fetchChatTabs: async () => [],
  saveChatTabs: async () => null,
}));

const { ChatTabsProvider, useChatTabs } =
  await import("@/core/threads/chat-tabs-context");

let latest: ReturnType<typeof useChatTabs> | null = null;

function Probe() {
  latest = useChatTabs();
  return null;
}

function mountProvider() {
  return render(
    <ChatTabsProvider>
      <Probe />
    </ChatTabsProvider>,
  );
}

/** Report a chat route the way the route registrar does. */
async function visit(threadId: string, isNew = false) {
  await act(async () => {
    latest?.syncRoute({ threadId, isNew });
  });
}

async function setBusy(slotKey: string, busy: boolean) {
  await act(async () => {
    latest?.reportBusy(slotKey, busy);
  });
}

beforeEach(() => {
  window.localStorage.clear();
  authState.user = { id: "default" };
  latest = null;
});

describe("leaving a chat that is still answering", () => {
  test("pins the running chat instead of dropping its live instance", async () => {
    mountProvider();

    await visit("thread-a");
    const runningKey = latest?.current?.key;
    expect(runningKey).toBe("route:thread-a");
    await setBusy(runningKey!, true);
    expect(latest?.busyKeys.has(runningKey!)).toBe(true);

    // The user goes off to write a prompt in another chat.
    await visit("thread-b");

    // thread-a is now a keep-alive tab — same slot key, so its mounted
    // instance (and its stream) was never torn down — and thread-b is the
    // chat on screen.
    expect(latest?.tabs).toEqual([{ key: runningKey, threadId: "thread-a" }]);
    expect(latest?.current).toEqual({
      key: "route:thread-b",
      threadId: "thread-b",
      isNew: false,
    });
    expect(latest?.activeKey).toBe("route:thread-b");
    // Still marked as running, so the strip can show it.
    expect(latest?.busyKeys.has(runningKey!)).toBe(true);
  });

  test("leaves an idle chat alone", async () => {
    mountProvider();

    await visit("thread-a");
    await visit("thread-b");

    expect(latest?.tabs).toEqual([]);
    expect(latest?.current?.threadId).toBe("thread-b");
  });

  test("a finished chat is idle again and is not pinned on the way out", async () => {
    mountProvider();

    await visit("thread-a");
    const key = latest!.current!.key;
    await setBusy(key, true);
    await setBusy(key, false);

    await visit("thread-b");

    expect(latest?.tabs).toEqual([]);
  });

  test("a chat that has not been created yet is not pinned", async () => {
    mountProvider();

    // A brand-new chat's id is a client-side placeholder until the backend
    // creates the thread; a tab is addressed by a real thread id.
    await visit("draft-thread", true);
    await setBusy(latest!.current!.key, true);

    await visit("thread-b");

    expect(latest?.tabs).toEqual([]);
  });

  test("a full strip declines the pin rather than evicting a tab", async () => {
    mountProvider();

    for (let index = 0; index < MAX_CHAT_TABS; index += 1) {
      const threadId = `pinned-${index}`;
      await visit(threadId);
      await act(async () => {
        latest?.pinThread(threadId);
      });
    }
    expect(latest?.tabs).toHaveLength(MAX_CHAT_TABS);

    await visit("thread-a");
    await setBusy(latest!.current!.key, true);
    await visit("thread-b");

    expect(latest?.tabs).toHaveLength(MAX_CHAT_TABS);
    expect(latest?.tabs.some((tab) => tab.threadId === "thread-a")).toBe(false);
  });

  test("returning to an already pinned running chat re-selects its tab", async () => {
    mountProvider();

    await visit("thread-a");
    const runningKey = latest!.current!.key;
    await setBusy(runningKey, true);
    await visit("thread-b");

    await visit("thread-a");

    expect(latest?.activeKey).toBe(runningKey);
    expect(latest?.tabs).toHaveLength(1);
  });
});
