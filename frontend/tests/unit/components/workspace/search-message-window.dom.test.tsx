import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useEffect, type ComponentProps } from "react";

import { SearchableMessageList } from "@/components/workspace/search-message-window";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";

const mocks = rs.hoisted(() => ({
  fetch: rs.fn(),
  pathname: "/workspace/chats/A",
  search: "",
  mounted: [] as string[],
  unmounted: [] as string[],
}));
rs.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useSearchParams: () => new URLSearchParams(mocks.search),
  useRouter: () => ({ push: rs.fn(), replace: rs.fn() }),
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "user-1" } }),
}));
// The real list needs a live thread stream; the stub records its own mount
// and unmount, which is the property under test.
rs.mock("@/components/workspace/messages/message-list", () => ({
  MessageList: StubMessageList,
}));

function StubMessageList({
  threadId,
  testId,
}: {
  threadId: string;
  testId?: string;
}) {
  useEffect(() => {
    mocks.mounted.push(threadId);
    return () => {
      mocks.unmounted.push(threadId);
    };
  }, [threadId]);
  return <div data-testid={testId} />;
}

const clients: QueryClient[] = [];

beforeEach(() => {
  mocks.fetch.mockResolvedValue({
    ok: true,
    json: async () => ({
      messages: [],
      target_seq: 3,
      has_before: false,
      has_after: false,
    }),
  });
  mocks.mounted.length = 0;
  mocks.unmounted.length = 0;
});

afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  mocks.fetch.mockReset();
  rs.restoreAllMocks();
});

function listProps(threadId: string) {
  return {
    threadId,
    testId: "main-message-list",
  } as unknown as ComponentProps<typeof SearchableMessageList>;
}

/** Two live chat slots, as KeepAliveChatViewport co-mounts them. */
function renderSlots() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const tree = () => (
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <QueryClientProvider client={client}>
        <div data-testid="slot-A">
          <SearchableMessageList {...listProps("A")} />
        </div>
        <div data-testid="slot-B">
          <SearchableMessageList {...listProps("B")} />
        </div>
      </QueryClientProvider>
    </I18nProvider>
  );
  const view = render(tree());
  return { rerender: () => view.rerender(tree()) };
}

function aroundRequests() {
  return mocks.fetch.mock.calls
    .map(([url]) => String(url))
    .filter((url) => url.includes("/messages/around"));
}

/**
 * Every keep-alive chat slot reads the same page-wide URL, so a search hit's
 * `?message=` must open the context window only in the slot whose thread is
 * routed. A hidden background slot that reacted to it would fetch another
 * thread's message (a 404) and remount its message list, losing scroll and
 * stick-to-bottom state (FORK.md, live chat slots).
 */
describe("SearchableMessageList in co-mounted chat slots", () => {
  it("opens the search window only for the routed thread", async () => {
    mocks.pathname = "/workspace/chats/A";
    mocks.search = "message=X&message_seq=3";

    renderSlots();

    const slotA = screen.getByTestId("slot-A");
    const slotB = screen.getByTestId("slot-B");
    expect(within(slotA).getByTestId("search-message-window")).toBeTruthy();
    expect(within(slotB).queryByTestId("search-message-window")).toBeNull();
    expect(within(slotB).getByTestId("main-message-list")).toBeTruthy();
    await waitFor(() => expect(aroundRequests()).toHaveLength(1));
    expect(aroundRequests()[0]).toContain("/api/threads/A/messages/around");
  });

  it("keeps a background slot's message list mounted when a hit routes to another agent chat", () => {
    mocks.pathname = "/workspace/agents/helper/chats/A";
    mocks.search = "";
    const { rerender } = renderSlots();
    expect(mocks.mounted).toEqual(["A", "B"]);

    mocks.search = "message=X&message_seq=3";
    rerender();

    expect(
      within(screen.getByTestId("slot-A")).getByTestId("search-message-window"),
    ).toBeTruthy();
    expect(mocks.unmounted).toEqual(["A"]);
    expect(mocks.mounted).toEqual(["A", "B"]);
  });
});
