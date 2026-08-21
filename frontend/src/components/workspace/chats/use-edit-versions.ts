"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { toast } from "sonner";

import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { useI18n } from "@/core/i18n/hooks";
import {
  readEditVersionGroups,
  resolveEditVersionLineage,
  resolveEditVersionRootThreadId,
  resolveEditVersionSwitchers,
  type EditVersionSwitcher,
} from "@/core/threads/edit-versions";
import {
  useCreateEditVersion,
  useSetActiveEditVersion,
  useThreadMetadata,
} from "@/core/threads/hooks";
import {
  getSessionPendingEditSendStorage,
  takePendingEditSend,
} from "@/core/threads/pending-edit-send";
import { pathOfThread } from "@/core/threads/utils";

export type EditMessageInput = {
  messageId: string;
  turnIndex: number;
  baseMessageId: string | null;
  baseMessageIds: string[];
  replacementText: string;
};

/**
 * Everything a chat surface needs to offer "edit this message".
 *
 * The version groups live on the family's root thread, so a chat that is itself
 * a version reads them one hop away; the open thread's ancestry then decides
 * which entry of each group is the one currently on screen.
 */
export function useEditVersions({
  threadId,
  threadMetadata,
  isThreadMetadataLoading = false,
  enabled,
  agentName,
  title,
}: {
  threadId: string;
  threadMetadata?: Record<string, unknown> | null;
  /**
   * Whether `threadMetadata` is still being fetched. Editing before it lands
   * would read a version thread as its own root and register the new version on
   * the wrong thread, so the button stays disabled until it resolves.
   */
  isThreadMetadataLoading?: boolean;
  enabled: boolean;
  agentName?: string | null;
  title?: string | null;
}) {
  const router = useRouter();
  const { t } = useI18n();
  const createEditVersion = useCreateEditVersion();
  const setActiveEditVersion = useSetActiveEditVersion();

  const metadata = threadMetadata ?? null;
  const rootThreadId = resolveEditVersionRootThreadId(threadId, metadata);
  const isVersionThread = rootThreadId !== threadId;
  const rootMetadataQuery = useThreadMetadata(
    isVersionThread ? rootThreadId : undefined,
    { enabled: enabled && isVersionThread },
  );
  const rootMetadata = isVersionThread
    ? (rootMetadataQuery.data?.metadata ?? null)
    : metadata;
  const isReady =
    enabled &&
    !isThreadMetadataLoading &&
    (!isVersionThread || !rootMetadataQuery.isLoading);

  const editVersionSwitchers: ReadonlyMap<string, EditVersionSwitcher> =
    useMemo(
      () =>
        resolveEditVersionSwitchers(
          readEditVersionGroups(rootMetadata),
          resolveEditVersionLineage(threadId, metadata),
        ),
      [metadata, rootMetadata, threadId],
    );

  const routeTo = useCallback(
    (targetThreadId: string) => {
      router.push(
        pathOfThread(
          targetThreadId,
          agentName ? { agent_name: agentName } : null,
        ),
      );
    },
    [agentName, router],
  );

  const handleEditMessage = useCallback(
    async ({
      turnIndex,
      baseMessageId,
      baseMessageIds,
      replacementText,
    }: EditMessageInput) => {
      if (!isReady) {
        return false;
      }
      try {
        const created = await createEditVersion.mutateAsync({
          threadId,
          threadMetadata: metadata,
          rootMetadata,
          turnIndex,
          baseMessageId,
          baseMessageIds,
          title,
          agentName,
          text: replacementText,
        });
        routeTo(created.threadId);
        return true;
      } catch (error) {
        toast.error(
          error instanceof Error
            ? error.message
            : t.conversation.editVersionFailed,
        );
        return false;
      }
    },
    [
      agentName,
      createEditVersion,
      isReady,
      metadata,
      rootMetadata,
      routeTo,
      t.conversation.editVersionFailed,
      threadId,
      title,
    ],
  );

  const handleSelectEditVersion = useCallback(
    (versionThreadId: string) => {
      if (versionThreadId === threadId) {
        return;
      }
      // Recording the choice before navigating is what makes the single sidebar
      // entry follow the reader; a failure here only costs that, so it must not
      // block the switch itself.
      setActiveEditVersion.mutate({ rootThreadId, versionThreadId });
      routeTo(versionThreadId);
    },
    [rootThreadId, routeTo, setActiveEditVersion, threadId],
  );

  return {
    editVersionSwitchers,
    handleEditMessage,
    handleSelectEditVersion,
    isReady,
    isCreatingEditVersion: createEditVersion.isPending,
  };
}

/**
 * Replay the edited message once the version thread it belongs to is mounted.
 *
 * The send has to happen here rather than at the click site: creating the
 * version navigates, which remounts the chat, so the text is parked in session
 * storage and consumed exactly once by whichever instance renders the target.
 */
export function usePendingEditSend({
  threadId,
  enabled,
  sendMessage,
}: {
  threadId: string;
  enabled: boolean;
  sendMessage: (threadId: string, message: PromptInputMessage) => unknown;
}) {
  const sentForThreadIdRef = useRef<string | null>(null);
  const sendMessageRef = useRef(sendMessage);
  sendMessageRef.current = sendMessage;

  useEffect(() => {
    if (!enabled || sentForThreadIdRef.current === threadId) {
      return;
    }
    const pending = takePendingEditSend(
      getSessionPendingEditSendStorage(),
      threadId,
    );
    if (!pending) {
      return;
    }
    sentForThreadIdRef.current = threadId;
    sendMessageRef.current(threadId, { text: pending.text, files: [] });
  }, [enabled, threadId]);
}
