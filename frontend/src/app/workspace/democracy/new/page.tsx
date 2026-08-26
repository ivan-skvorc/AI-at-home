"use client";

import { DemocracySetup } from "@/components/workspace/democracy-setup";

/**
 * Panel setup lives at its own route rather than in a modal over the chat: it is
 * the start of a conversation, the same as `/workspace/chats/new`, and a roster
 * that can run to a dozen rows plus a cost warning does not belong in a dialog
 * that scrolls internally.
 */
export default function DemocracyNewPage() {
  return <DemocracySetup />;
}
