import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { MessageList } from "@/components/workspace/messages/message-list";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { formatRunStartTime } from "@/core/messages/run-duration";
import type { MessageGroup } from "@/core/messages/utils";

rs.mock("@/components/workspace/messages/message-group", () => ({
  MessageGroup: () => null,
  getMessageGroupReasoningMessage: () => undefined,
}));
rs.mock("@/components/ai-elements/conversation", () => ({
  Conversation: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  ConversationContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));
rs.mock("@/components/workspace/messages/virtual-message-list", () => ({
  VirtualMessageList: ({
    groups,
    renderGroup,
    renderAfterGroup,
  }: {
    groups: MessageGroup[];
    renderGroup: (group: MessageGroup, index: number) => ReactNode;
    renderAfterGroup?: (index: number) => ReactNode;
  }) => (
    <div>
      {groups.map((group, index) => (
        <div key={`${group.type}:${group.id}`}>
          {renderGroup(group, index)}
          {renderAfterGroup?.(index)}
        </div>
      ))}
    </div>
  ),
}));
rs.mock("@/components/workspace/messages/message-list-item", () => ({
  MessageListItem: ({
    message,
    canEdit,
    editLockedByGoal,
  }: {
    message: Message;
    canEdit?: boolean;
    editLockedByGoal?: boolean;
  }) => (
    <div
      data-testid={`item-${message.type}`}
      data-can-edit={canEdit ? "true" : "false"}
      data-edit-locked={editLockedByGoal ? "true" : "false"}
    />
  ),
}));
rs.mock("@/components/workspace/messages/subtask-card", () => ({
  SubtaskCard: () => null,
}));
rs.mock("@/components/workspace/messages/scheduled-task-card", () => ({
  ScheduledTaskCard: ({ result }: { result: { task: { id: string } } }) => (
    <div data-testid="card" data-task-id={result.task.id} />
  ),
  taskPagePath: (id: string) => `/workspace/scheduled-tasks?task_id=${id}`,
}));
rs.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const NOW = Date.UTC(2026, 10, 4, 9, 0, 0);

beforeEach(() => {
  rs.useFakeTimers();
  rs.setSystemTime(NOW);
});

afterEach(() => {
  cleanup();
  rs.useRealTimers();
});

const MESSAGES = [
  { id: "human-1", type: "human", content: "Research this" },
  { id: "ai-1", type: "ai", content: "Working on it" },
] as Message[];

function view({
  isLoading,
  activeRunStartedAt,
}: {
  isLoading: boolean;
  activeRunStartedAt?: number | null;
}) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <MessageList
        threadId="thread-1"
        activeRunStartedAt={activeRunStartedAt}
        thread={
          {
            messages: MESSAGES,
            isLoading,
            isThreadLoading: false,
            values: {},
            getMessagesMetadata: () => undefined,
          } as unknown as React.ComponentProps<typeof MessageList>["thread"]
        }
      />
    </I18nContext.Provider>
  );
}

function activity() {
  return screen.getByTestId("run-activity").textContent;
}

/** The focusable elapsed time, found by the explanation it is described by. */
function elapsedTime(description: string) {
  return screen.getByRole("timer", {
    name: enUS.runDuration.elapsed,
    description,
  }).textContent;
}

function serverStart(startTime: number) {
  return enUS.runDuration.serverStart(
    formatRunStartTime(startTime, { locale: "en-US", now: Date.now() }),
  );
}

describe("MessageList live run timer", () => {
  it("counts from the run's server start when mounted mid-run", () => {
    render(view({ isLoading: true, activeRunStartedAt: NOW - 42_000 }));

    expect(activity()).toContain("(42s)");
    expect(elapsedTime(serverStart(NOW - 42_000))).toBe("(42s)");
  });

  it("says a start this page observed may be later than the run's", () => {
    const { rerender } = render(view({ isLoading: false }));
    rerender(view({ isLoading: true }));
    act(() => {
      rs.advanceTimersByTime(3_000);
    });

    expect(elapsedTime(enUS.runDuration.localStart)).toBe("(3s)");

    rerender(view({ isLoading: true, activeRunStartedAt: NOW - 60_000 }));

    expect(elapsedTime(serverStart(NOW - 60_000))).toBe("(1m 3s)");
  });

  it("keeps counting the same run when it becomes active in this view again", () => {
    const { rerender } = render(view({ isLoading: false }));

    rerender(view({ isLoading: true, activeRunStartedAt: NOW - 95_000 }));

    expect(activity()).toContain("(1m 35s)");
  });

  it("does not move a run started in this view forward to its server start", () => {
    const { rerender } = render(view({ isLoading: false }));
    rerender(view({ isLoading: true }));
    act(() => {
      rs.advanceTimersByTime(5_000);
    });

    // The server records the run slightly after the browser submitted it.
    rerender(view({ isLoading: true, activeRunStartedAt: NOW + 400 }));

    expect(activity()).toContain("(5s)");
    // The server knows the run now, so a reload keeps counting.
    expect(elapsedTime(serverStart(NOW))).toBe("(5s)");
  });

  it("records the completed duration from the corrected start", () => {
    const { rerender } = render(
      view({ isLoading: true, activeRunStartedAt: NOW - 42_000 }),
    );

    rerender(view({ isLoading: false, activeRunStartedAt: null }));

    expect(screen.getByTestId("run-duration").textContent).toContain("42s");
  });
});
