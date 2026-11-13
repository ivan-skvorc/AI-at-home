import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import type { ReactNode } from "react";

const mocks = rs.hoisted(() => ({ messages: [] as Message[] }));

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/chats/a",
}));
rs.mock("@/components/ui/sidebar", () => ({
  useSidebar: () => ({ setOpen: rs.fn() }),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "account-a" } }),
}));
rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));
rs.mock("@/core/artifacts/hooks", () => ({
  useArtifactContent: () => ({
    content: undefined,
    url: undefined,
    sha256: undefined,
    truncated: false,
    previewBytes: undefined,
    totalBytes: undefined,
    fullContentRequested: false,
    loadFullContent: () => undefined,
    isLoading: false,
    error: undefined,
  }),
}));
rs.mock("@/components/workspace/messages/context", () => ({
  useThread: () => ({
    thread: { isLoading: true, messages: mocks.messages },
    isMock: false,
  }),
}));
rs.mock("@/components/workspace/code-editor", () => ({
  CodeEditor: ({ value }: { value: string }) => <pre>{value}</pre>,
}));
rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));
// The step's enter/exit animation; AnimatePresence would hold the next tool
// call back until an exit animation that happy-dom never finishes.
rs.mock("@/components/workspace/flip-display", () => ({
  FlipDisplay: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

import { ArtifactFileDetail } from "@/components/workspace/artifacts/artifact-file-detail";
import {
  ArtifactsProvider,
  useArtifacts,
} from "@/components/workspace/artifacts/context";
import { MessageGroup } from "@/components/workspace/messages/message-group";
import { ThreadFilesTrigger } from "@/components/workspace/thread-files/thread-files-trigger";
import { ArtifactDraftsProvider } from "@/core/artifacts/draft-context";
import { I18nProvider } from "@/core/i18n/context";

const THREAD_ID = "7cfa5f8f-a2f8-47ad-acbd-da7137baf990";

function writeFile(id: string): Message {
  return {
    id: `ai-${id}`,
    type: "ai",
    content: "",
    tool_calls: [
      {
        id,
        name: "write_file",
        args: { path: `/mnt/user-data/outputs/${id}.py`, content: "x = 1\n" },
      },
    ],
  } as Message;
}

function written(id: string): Message {
  return {
    id: `tool-${id}`,
    type: "tool",
    name: "write_file",
    tool_call_id: id,
    content: "OK",
  } as Message;
}

/** chat-box's artifacts panel: an open file, else the Files view's explorer. */
function Panel() {
  const { open, selectedArtifact, view } = useArtifacts();
  if (!open) {
    return null;
  }
  if (selectedArtifact) {
    return (
      <ArtifactFileDetail filepath={selectedArtifact} threadId={THREAD_ID} />
    );
  }
  return view === "files" ? <div data-testid="explorer" /> : null;
}

function Chat({
  messages,
  queryClient,
}: {
  messages: Message[];
  queryClient: QueryClient;
}) {
  mocks.messages = messages;
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider initialLocale="en-US">
        <ArtifactDraftsProvider>
          <ArtifactsProvider>
            <ThreadFilesTrigger />
            <MessageGroup messages={messages} isLoading threadId={THREAD_ID} />
            <Panel />
          </ArtifactsProvider>
        </ArtifactDraftsProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  rs.useFakeTimers();
});

afterEach(() => {
  cleanup();
  rs.useRealTimers();
  window.sessionStorage.clear();
});

describe("write_file previews in the Files view", () => {
  it("stop opening over the explorer once one is closed", () => {
    const queryClient = new QueryClient();
    const { rerender } = render(
      <Chat messages={[]} queryClient={queryClient} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show files" }));
    expect(screen.getByTestId("explorer")).toBeTruthy();

    rerender(
      <Chat messages={[writeFile("write-1")]} queryClient={queryClient} />,
    );
    act(() => {
      rs.advanceTimersByTime(1_000);
    });
    // The running write opened its preview over the explorer.
    expect(screen.queryByTestId("explorer")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.getByTestId("explorer")).toBeTruthy();

    rerender(
      <Chat
        messages={[
          writeFile("write-1"),
          written("write-1"),
          writeFile("write-2"),
        ]}
        queryClient={queryClient}
      />,
    );
    act(() => {
      rs.advanceTimersByTime(1_000);
    });

    expect(screen.getByTestId("explorer")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
  });
});
