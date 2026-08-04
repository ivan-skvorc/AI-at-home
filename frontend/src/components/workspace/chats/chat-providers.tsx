"use client";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { BrowserViewProvider } from "@/components/workspace/browser-view";
import { SubtasksProvider } from "@/core/tasks/context";

/**
 * The per-chat provider stack (subtasks, artifacts, browser view, composer).
 * One stack is mounted per live chat instance. With keep-alive chat tabs
 * several instances are mounted at once under a single route, so each passes a
 * distinct `storageScope` (its thread id) to keep the artifacts panel's
 * persisted state isolated instead of sharing one pathname-keyed slot.
 */
export function ChatProviders({
  children,
  storageScope,
}: {
  children: React.ReactNode;
  storageScope?: string;
}) {
  return (
    <SubtasksProvider>
      <ArtifactsProvider storageScope={storageScope}>
        <BrowserViewProvider>
          <PromptInputProvider>{children}</PromptInputProvider>
        </BrowserViewProvider>
      </ArtifactsProvider>
    </SubtasksProvider>
  );
}
