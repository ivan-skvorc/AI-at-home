import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { MessageListItem } from "@/components/workspace/messages/message-list-item";
import { buildConversationReferenceMetadata } from "@/core/conversation-references";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    setLocale: () => undefined,
    t: enUS,
  }),
}));

// The transcript body is not under test; stubbing the markdown pipeline also
// avoids its first-render suspension.
rs.mock("@/components/workspace/messages/markdown-content", () => ({
  MarkdownContent: () => null,
}));

afterEach(cleanup);

describe("conversation reference transcript chips", () => {
  it("links the transcript chip to a custom-agent source conversation", () => {
    // The send path stores display-only metadata for the reference the @
    // mention picker selected; the chip routes back to the agent's chat.
    const message = {
      id: "human-1",
      type: "human",
      content: "Summarize the referenced brief",
      additional_kwargs: buildConversationReferenceMetadata([
        { threadId: "source-1", title: "Writer brief", agentName: "writer" },
      ]),
    } as unknown as Message;

    render(
      <MessageListItem
        message={message}
        threadId="t-current"
        showCopyButton={false}
        isLoading={false}
      />,
    );
    const chip = screen.getByTestId("conversation-reference-chip");
    expect(chip.getAttribute("href")).toBe(
      "/workspace/agents/writer/chats/source-1",
    );
  });

  it("links a default-agent source to the plain chats path", () => {
    const message = {
      id: "human-2",
      type: "human",
      content: "Summarize the referenced chat",
      additional_kwargs: buildConversationReferenceMetadata([
        { threadId: "source-2", title: "Plain chat" },
      ]),
    } as unknown as Message;

    render(
      <MessageListItem
        message={message}
        threadId="t-current"
        showCopyButton={false}
        isLoading={false}
      />,
    );
    const chip = screen.getByTestId("conversation-reference-chip");
    expect(chip.getAttribute("href")).toBe("/workspace/chats/source-2");
  });
});
