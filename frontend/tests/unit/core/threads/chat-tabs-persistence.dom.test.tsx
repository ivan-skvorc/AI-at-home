/**
 * Boot-path persistence for the keep-alive chat tab strip (fork feature).
 *
 * `chat-tabs.test.ts` covers the pure model; this covers the thing that
 * actually lost people's tabs — the provider's hydrate/persist effect pair
 * running against a `localStorage` key that changes identity mid-session.
 *
 * The failing sequence is the ordinary "PC restart" boot: the browser reopens
 * DeerFlow before the gateway container is up, the SSR auth probe fails, and
 * `workspace/layout.tsx` renders `GatewayOfflineFallback`, which supplies
 * `<AuthProvider initialUser={null}>`. The provider therefore starts on the
 * `…anonymous` storage key and only later flips to `…default` when the offline
 * banner's probe calls `applyUser`.
 */
import { expect, rs, test, beforeEach, describe } from "@rstest/core";
import { act, render } from "@testing-library/react";
import { useEffect } from "react";

import {
  CHAT_TABS_STORAGE_PREFIX,
  type ChatTab,
} from "@/core/threads/chat-tabs";

const authState = rs.hoisted(() => ({
  user: null as { id: string } | null,
}));

// The durable per-user store the strip reconciles against. `remote === null`
// models an unreachable gateway — the normal state right after a machine
// restart, when the browser reopens the app before the backend is up.
const serverState = rs.hoisted(() => ({
  remote: null as { key: string; threadId: string; title?: string }[] | null,
  saved: [] as { key: string; threadId: string; title?: string }[][],
  reachable: true,
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: authState.user }),
}));

rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

rs.mock("@/core/threads/chat-tabs-api", () => ({
  fetchChatTabs: async () =>
    serverState.reachable ? (serverState.remote ?? []) : null,
  saveChatTabs: async (tabs: { key: string; threadId: string }[]) => {
    if (!serverState.reachable) {
      return null;
    }
    serverState.saved.push(tabs);
    serverState.remote = tabs;
    return tabs;
  },
}));

const { ChatTabsProvider, useChatTabs } =
  await import("@/core/threads/chat-tabs-context");

const KEY_ANON = `${CHAT_TABS_STORAGE_PREFIX}anonymous`;
const KEY_DEFAULT = `${CHAT_TABS_STORAGE_PREFIX}default`;

const STORED: ChatTab[] = [
  { key: "k1", threadId: "thread-a", title: "Alpha" },
  { key: "k2", threadId: "thread-b", title: "Beta" },
];

function readTabs(key: string): unknown {
  const raw = window.localStorage.getItem(key);
  return raw === null ? null : JSON.parse(raw);
}

/** Renders the provider and exposes its live value to the test. */
let latest: ReturnType<typeof useChatTabs> | null = null;

function Probe() {
  const value = useChatTabs();
  latest = value;
  return null;
}

function mountProvider() {
  return render(
    <ChatTabsProvider>
      <Probe />
    </ChatTabsProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  authState.user = null;
  latest = null;
  serverState.remote = null;
  serverState.saved = [];
  serverState.reachable = true;
});

/** Let the provider's async server reconciliation settle. */
async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("chat tab persistence across the offline boot", () => {
  test("a populated tab set survives the anonymous→user storage-key flip", async () => {
    window.localStorage.setItem(KEY_DEFAULT, JSON.stringify(STORED));

    // 1. Gateway offline at boot: SSR gave us no user.
    const view = mountProvider();
    expect(latest?.tabs).toEqual([]);

    // 2. The offline banner's probe succeeds and applies the real user.
    await act(async () => {
      authState.user = { id: "default" };
      view.rerender(
        <ChatTabsProvider>
          <Probe />
        </ChatTabsProvider>,
      );
    });

    // The persisted tabs must come back, and must still be on disk.
    expect(latest?.tabs).toEqual(STORED);
    expect(readTabs(KEY_DEFAULT)).toEqual(STORED);
  });

  test("a boot that never learns the user does not blank the stored set", async () => {
    window.localStorage.setItem(KEY_DEFAULT, JSON.stringify(STORED));

    mountProvider();
    await settle();

    // The gateway never came up; the user's tabs are still on disk untouched,
    // so the next (successful) boot restores them.
    expect(readTabs(KEY_DEFAULT)).toEqual(STORED);
  });

  test("a normal boot round-trips the stored set without blanking it", async () => {
    authState.user = { id: "default" };
    window.localStorage.setItem(KEY_DEFAULT, JSON.stringify(STORED));

    mountProvider();
    await settle();

    expect(latest?.tabs).toEqual(STORED);
    expect(readTabs(KEY_DEFAULT)).toEqual(STORED);
  });

  test("closing the last tab is an explicit clear and is persisted", async () => {
    authState.user = { id: "default" };
    window.localStorage.setItem(
      KEY_DEFAULT,
      JSON.stringify([STORED[0]] as ChatTab[]),
    );

    mountProvider();
    await settle();
    expect(latest?.tabs).toHaveLength(1);

    await act(async () => {
      latest?.closeTab("k1");
    });

    // An empty set the *user* produced must stick — the anti-wipe guard only
    // protects sets we have not been told to change.
    expect(latest?.tabs).toEqual([]);
    expect(readTabs(KEY_DEFAULT)).toEqual([]);
  });

  test("pinning while anonymous never overwrites the real user's set", async () => {
    window.localStorage.setItem(KEY_DEFAULT, JSON.stringify(STORED));

    mountProvider();
    await act(async () => {
      latest?.pinThread("thread-z", "Zeta");
    });

    expect(readTabs(KEY_DEFAULT)).toEqual(STORED);
    expect(readTabs(KEY_ANON)).toEqual([
      { key: expect.any(String), threadId: "thread-z", title: "Zeta" },
    ]);
  });
});

/** A component that unmounts the provider as soon as it has mounted. */
function ShortLived({ onDone }: { onDone: () => void }) {
  useEffect(() => {
    onDone();
  }, [onDone]);
  return null;
}

test("a provider torn down immediately after mount leaves the store intact", async () => {
  authState.user = { id: "default" };
  window.localStorage.setItem(KEY_DEFAULT, JSON.stringify(STORED));

  const view = render(
    <ChatTabsProvider>
      <ShortLived onDone={() => undefined} />
    </ChatTabsProvider>,
  );
  view.unmount();

  expect(readTabs(KEY_DEFAULT)).toEqual(STORED);
});

describe("durable server-side tab persistence", () => {
  test("an empty browser adopts the tabs stored for the user", async () => {
    // The PC-restart case that localStorage alone cannot cover: a cleared /
    // evicted / different-origin browser store, with the server holding truth.
    authState.user = { id: "default" };
    serverState.remote = STORED;

    mountProvider();
    await settle();

    expect(latest?.tabs).toEqual(STORED);
    // ...and the local cache is repopulated for the next first paint.
    expect(readTabs(KEY_DEFAULT)).toEqual(STORED);
  });

  test("an unreachable gateway keeps the local cache instead of blanking", async () => {
    authState.user = { id: "default" };
    window.localStorage.setItem(KEY_DEFAULT, JSON.stringify(STORED));
    serverState.reachable = false;

    mountProvider();
    await settle();

    expect(latest?.tabs).toEqual(STORED);
    expect(readTabs(KEY_DEFAULT)).toEqual(STORED);
  });

  test("a server with no stored set adopts and seeds from the local cache", async () => {
    // Upgrade path: tabs pinned before server persistence existed must not be
    // wiped by an empty server response.
    authState.user = { id: "default" };
    window.localStorage.setItem(KEY_DEFAULT, JSON.stringify(STORED));
    serverState.remote = [];

    mountProvider();
    await settle();

    expect(latest?.tabs).toEqual(STORED);
    expect(serverState.saved).toEqual([STORED]);
  });

  test("a user mutation is pushed to the durable store", async () => {
    authState.user = { id: "default" };
    serverState.remote = [];

    const view = mountProvider();
    await settle();

    await act(async () => {
      latest?.pinThread("thread-z", "Zeta");
    });
    // The push is debounced; tearing the provider down flushes it, so a browser
    // tab closed right after a pin still records the change.
    view.unmount();
    await settle();

    expect(serverState.remote).toEqual([
      { key: expect.any(String), threadId: "thread-z", title: "Zeta" },
    ]);
  });

  test("closing the last tab is pushed as an explicit empty set", async () => {
    authState.user = { id: "default" };
    serverState.remote = [STORED[0]!];

    const view = mountProvider();
    await settle();
    expect(latest?.tabs).toHaveLength(1);

    await act(async () => {
      latest?.closeTab("k1");
    });
    view.unmount();
    await settle();

    expect(serverState.remote).toEqual([]);
  });
});
