"use client";

import { useCallback, useEffect, useRef } from "react";

import type { LocalSettings } from "@/core/settings/local";
import { patchThreadMetadata } from "@/core/threads/api";
import {
  buildThreadWorkflowPatch,
  readThreadWorkflow,
  workflowChanged,
  workflowOfContext,
  type ThreadWorkflow,
} from "@/core/threads/thread-workflow";

/**
 * Make a conversation remember what it was running with.
 *
 * Two halves, and the feature needs both:
 *
 * - **Seed.** When a chat opens with no local selection of its own, adopt the
 *   one recorded on the thread. Without this, every conversation this browser
 *   has not touched falls back to the app default — which is what made opening
 *   an old chat show whichever model was selected last rather than the model
 *   that chat had been talking to.
 * - **Record.** When the selection changes, write it back to the thread. The
 *   PATCH is the narrow workflow shape the Gateway exempts from bumping
 *   `updated_at`, so changing a model never reshuffles the recency-ordered
 *   sidebar under the user's cursor.
 *
 * Both halves are best-effort: the local store is still the source of truth for
 * the open chat, so a failed write costs durability, never the current session.
 */
export function useThreadWorkflowMemory({
  threadId,
  isNewThread,
  isMock,
  metadata,
  context,
  applyWorkflow,
}: {
  threadId: string;
  isNewThread: boolean;
  isMock: boolean;
  /** The open thread's metadata, once it has loaded. */
  metadata: Record<string, unknown> | null | undefined;
  context: LocalSettings["context"];
  /** Apply a recorded selection to this thread's own settings. */
  applyWorkflow: (workflow: ThreadWorkflow) => void;
}) {
  // What the server is believed to hold, so a re-render that reports the same
  // context does not PATCH again. Reset per thread: a slot can be reused for a
  // different conversation, and carrying this over would suppress its first
  // write.
  const storedRef = useRef<{
    threadId: string;
    workflow: ThreadWorkflow | null;
  }>({
    threadId,
    workflow: null,
  });
  const seededRef = useRef<string | null>(null);
  const applyRef = useRef(applyWorkflow);
  applyRef.current = applyWorkflow;

  if (storedRef.current.threadId !== threadId) {
    storedRef.current = { threadId, workflow: null };
  }

  // Seed once per thread, from the thread's own record.
  useEffect(() => {
    if (isMock || isNewThread || metadata === undefined) {
      return;
    }
    if (seededRef.current === threadId) {
      return;
    }
    const recorded = readThreadWorkflow(metadata);
    seededRef.current = threadId;
    storedRef.current = { threadId, workflow: recorded };
    if (recorded === null) {
      return;
    }
    // A selection made in this browser wins: it is what the user is looking at
    // right now, and the record is only ever a fallback for a chat this browser
    // has not seen. `applyWorkflow` decides that, because only the caller can
    // see whether this thread has a local override.
    applyRef.current(recorded);
  }, [isMock, isNewThread, metadata, threadId]);

  // Record changes back onto the thread.
  useEffect(() => {
    if (isMock || isNewThread || seededRef.current !== threadId) {
      return;
    }
    const next = workflowOfContext(context);
    if (!workflowChanged(storedRef.current.workflow, next)) {
      return;
    }
    storedRef.current = { threadId, workflow: next };
    void patchThreadMetadata(threadId, buildThreadWorkflowPatch(next)).catch(
      () => {
        // Durability is a nice-to-have; the open chat still has its local
        // selection. Allow the next change to retry by forgetting what we
        // believed the server held.
        if (storedRef.current.threadId === threadId) {
          storedRef.current = { threadId, workflow: null };
        }
      },
    );
  }, [context, isMock, isNewThread, threadId]);

  /**
   * Carry a brand-new chat's selection onto the real thread id.
   *
   * A new chat is addressed by a client-generated placeholder until the first
   * send, and the backend then assigns a *different* id. Every per-conversation
   * key is stored under the thread id, so without this the model the user
   * picked before sending is orphaned under the placeholder the moment the
   * conversation becomes real — the chat forgets, on its very first turn, what
   * it just answered with.
   */
  const recordOnPromotion = useCallback(
    (realThreadId: string, promotedContext: LocalSettings["context"]) => {
      if (isMock || !realThreadId) {
        return;
      }
      const workflow = workflowOfContext(promotedContext);
      if (Object.keys(workflow).length === 0) {
        return;
      }
      seededRef.current = realThreadId;
      storedRef.current = { threadId: realThreadId, workflow };
      void patchThreadMetadata(
        realThreadId,
        buildThreadWorkflowPatch(workflow),
      ).catch(() => {
        if (storedRef.current.threadId === realThreadId) {
          storedRef.current = { threadId: realThreadId, workflow: null };
        }
      });
    },
    [isMock],
  );

  return { recordOnPromotion };
}
