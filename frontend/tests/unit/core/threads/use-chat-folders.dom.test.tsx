import {
  afterEach,
  beforeEach,
  describe,
  expect,
  rs,
  test,
} from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const api = rs.hoisted(() => ({
  fetchChatFolders: rs.fn(),
  saveChatFolders: rs.fn(),
}));
rs.mock("@/core/threads/chat-folders-api", () => api);

import {
  CHAT_FOLDERS_EXPANDED_STORAGE_KEY,
  type ChatFolder,
} from "@/core/threads/chat-folders";
import {
  CHAT_FOLDERS_QUERY_KEY,
  useChatFolders,
} from "@/core/threads/use-chat-folders";

const EXISTING: ChatFolder[] = [{ id: "existing", name: "Existing" }];

function setup() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
  client.setQueryData(CHAT_FOLDERS_QUERY_KEY, EXISTING);
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, ...renderHook(() => useChatFolders(), { wrapper }) };
}

const names = (folders: readonly ChatFolder[] | undefined) =>
  folders?.map((folder) => folder.name);

beforeEach(() => {
  window.localStorage.clear();
  api.fetchChatFolders.mockReset().mockResolvedValue(EXISTING);
  api.saveChatFolders
    .mockReset()
    .mockImplementation(async (folders: readonly ChatFolder[]) => [...folders]);
});
afterEach(cleanup);

describe("useChatFolders in one handler", () => {
  test("two creates keep both folders, and the second write carries both", async () => {
    const { client, result } = setup();
    let first: string | null = null;
    let second: string | null = null;
    act(() => {
      first = result.current.createFolder("Reports");
      second = result.current.createFolder("Drafts", first);
    });
    expect(first).not.toBeNull();
    expect(second).not.toBeNull();
    const cached = client.getQueryData<ChatFolder[]>(CHAT_FOLDERS_QUERY_KEY);
    expect(names(cached)).toEqual(["Existing", "Reports", "Drafts"]);
    expect(cached?.find((folder) => folder.id === second)?.parentId).toBe(
      first,
    );
    await waitFor(() => expect(api.saveChatFolders).toHaveBeenCalledTimes(2));
    expect(names(api.saveChatFolders.mock.calls[1]![0])).toEqual([
      "Existing",
      "Reports",
      "Drafts",
    ]);
    // Both new folders and the parent stay open: the second write to the
    // expanded set started from the first, not from the render's copy.
    expect(result.current.expandedFolderIds).toEqual(new Set([first, second]));
    expect(
      JSON.parse(
        window.localStorage.getItem(CHAT_FOLDERS_EXPANDED_STORAGE_KEY) ?? "[]",
      ),
    ).toEqual([first, second]);
    client.clear();
  });

  test("createFolders makes several in one write and answers null for a refused name", async () => {
    const { client, result } = setup();
    let ids: Array<string | null> = [];
    act(() => {
      ids = result.current.createFolders(["Alpha", "  ", "Beta"], "existing");
    });
    expect(ids).toHaveLength(3);
    expect(ids[1]).toBeNull();
    expect(ids[0]).not.toBeNull();
    expect(ids[2]).not.toBeNull();
    await waitFor(() => expect(api.saveChatFolders).toHaveBeenCalledTimes(1));
    expect(api.saveChatFolders.mock.calls[0]![0]).toEqual([
      ...EXISTING,
      { id: ids[0], name: "Alpha", parentId: "existing" },
      { id: ids[2], name: "Beta", parentId: "existing" },
    ]);
    expect(result.current.expandedFolderIds).toEqual(
      new Set([ids[0], ids[2], "existing"]),
    );
    client.clear();
  });

  test("whole-list writes run one at a time, so an older response cannot land last", async () => {
    const releases: Array<() => void> = [];
    api.saveChatFolders.mockImplementation(
      (folders: readonly ChatFolder[]) =>
        new Promise<ChatFolder[]>((resolve) => {
          releases.push(() => resolve([...folders]));
        }),
    );
    const { client, result } = setup();
    act(() => {
      result.current.createFolder("One");
    });
    act(() => {
      result.current.createFolder("Two");
    });
    await waitFor(() => expect(api.saveChatFolders).toHaveBeenCalledTimes(1));
    // The second PUT waits for the first instead of racing it.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(api.saveChatFolders).toHaveBeenCalledTimes(1);
    await act(async () => {
      releases[0]!();
    });
    await waitFor(() => expect(api.saveChatFolders).toHaveBeenCalledTimes(2));
    // The first response describes the older list; it must not make the
    // newer folder blink out while its own write is still in flight.
    expect(
      names(client.getQueryData<ChatFolder[]>(CHAT_FOLDERS_QUERY_KEY)),
    ).toEqual(["Existing", "One", "Two"]);
    await act(async () => {
      releases[1]!();
    });
    await waitFor(() =>
      expect(
        names(client.getQueryData<ChatFolder[]>(CHAT_FOLDERS_QUERY_KEY)),
      ).toEqual(["Existing", "One", "Two"]),
    );
    client.clear();
  });
});
