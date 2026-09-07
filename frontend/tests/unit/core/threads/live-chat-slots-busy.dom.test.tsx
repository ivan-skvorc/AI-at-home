/**
 * Concurrent chats: leaving a chat that is still answering must not end it.
 *
 * The current slot is normally dropped the moment the route moves to another
 * chat, which unmounts its instance and ends its live view. That is the classic
 * one-live-chat behavior and is fine for an idle chat — but it is exactly what
 * makes a second prompt in a second chat feel like it cancelled the first one.
 * While a slot reports a run in flight, leaving it keeps it mounted in the
 * background (reusing the slot key so the mounted instance survives), so the
 * answer keeps arriving; once the run lands, the slot is released again.
 *
 * `live-chat-slots.test.ts` covers the pure model; this covers the provider's
 * route/busy coordination.
 */
import { expect, rs, test, beforeEach, describe } from "@rstest/core";
import { act, render } from "@testing-library/react";

import { MAX_BACKGROUND_CHAT_SLOTS } from "@/core/threads/live-chat-slots";

rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

const { LiveChatSlotsProvider, useLiveChatSlots } =
  await import("@/core/threads/live-chat-slots-context");

let latest: ReturnType<typeof useLiveChatSlots> | null = null;

function Probe() {
  latest = useLiveChatSlots();
  return null;
}

function mountProvider() {
  return render(
    <LiveChatSlotsProvider>
      <Probe />
    </LiveChatSlotsProvider>,
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
  latest = null;
});

describe("leaving a chat that is still answering", () => {
  test("keeps the running chat mounted instead of dropping its live instance", async () => {
    mountProvider();

    await visit("thread-a");
    const runningKey = latest?.current?.key;
    expect(runningKey).toBe("route:thread-a");
    await setBusy(runningKey!, true);
    expect(latest?.busyKeys.has(runningKey!)).toBe(true);

    // The user goes off to write a prompt in another chat.
    await visit("thread-b");

    // thread-a is now a background slot — same slot key, so its mounted
    // instance (and its stream) was never torn down — and thread-b is the
    // chat on screen.
    expect(latest?.background).toEqual([
      { key: runningKey, threadId: "thread-a", isNew: false },
    ]);
    expect(latest?.current).toEqual({
      key: "route:thread-b",
      threadId: "thread-b",
      isNew: false,
    });
    expect(latest?.activeKey).toBe("route:thread-b");
    expect(latest?.busyKeys.has(runningKey!)).toBe(true);
  });

  test("leaves an idle chat alone", async () => {
    mountProvider();

    await visit("thread-a");
    await visit("thread-b");

    expect(latest?.background).toEqual([]);
    expect(latest?.current?.threadId).toBe("thread-b");
  });

  test("a finished chat is idle again and is not retained on the way out", async () => {
    mountProvider();

    await visit("thread-a");
    const key = latest!.current!.key;
    await setBusy(key, true);
    await setBusy(key, false);

    await visit("thread-b");

    expect(latest?.background).toEqual([]);
  });

  test("a chat that has not been created yet is not retained", async () => {
    mountProvider();

    // A brand-new chat's id is a client-side placeholder until the backend
    // creates the thread; a background slot is addressed by a real thread id.
    await visit("draft-thread", true);
    await setBusy(latest!.current!.key, true);

    await visit("thread-b");

    expect(latest?.background).toEqual([]);
  });

  test("a full background set declines the retention rather than evicting", async () => {
    mountProvider();

    for (let index = 0; index < MAX_BACKGROUND_CHAT_SLOTS; index += 1) {
      const threadId = `busy-${index}`;
      await visit(threadId);
      await setBusy(latest!.current!.key, true);
    }
    // The last one is still the current slot, so leaving it fills the set.
    await visit("spillover");
    expect(latest?.background).toHaveLength(MAX_BACKGROUND_CHAT_SLOTS);

    await setBusy(latest!.current!.key, true);
    await visit("thread-b");

    expect(latest?.background).toHaveLength(MAX_BACKGROUND_CHAT_SLOTS);
    expect(
      latest?.background.some((slot) => slot.threadId === "spillover"),
    ).toBe(false);
  });

  test("returning to a chat still answering in the background re-adopts its instance", async () => {
    mountProvider();

    await visit("thread-a");
    const runningKey = latest!.current!.key;
    await setBusy(runningKey, true);
    await visit("thread-b");

    await visit("thread-a");

    // Adopted, not re-mounted: a second instance for the same thread would show
    // an empty transcript beside a run already in flight.
    expect(latest?.activeKey).toBe(runningKey);
    expect(latest?.current?.key).toBe(runningKey);
    expect(latest?.background).toEqual([]);
  });

  test("a background chat is released once its run lands", async () => {
    mountProvider();

    await visit("thread-a");
    const runningKey = latest!.current!.key;
    await setBusy(runningKey, true);
    await visit("thread-b");
    expect(latest?.background).toHaveLength(1);

    // The answer arrives. The instance has nothing left to receive, so it is
    // unmounted rather than held forever — the transcript is on the server.
    await setBusy(runningKey, false);

    expect(latest?.background).toEqual([]);
    expect(latest?.current?.threadId).toBe("thread-b");
  });
});
