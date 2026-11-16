"use client";

import { useParams, usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { resetThreadChatAfterDelete } from "@/components/workspace/chats/use-thread-chat";
import type { Translations } from "@/core/i18n";
import { useI18n } from "@/core/i18n/hooks";
import type { BulkThreadFailure } from "@/core/threads/bulk";
import { useDeleteThreads } from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";
import { pathOfThread, titleOfThread } from "@/core/threads/utils";

import type {
  BulkDeleteRequest,
  SidebarSelectionStore,
} from "./sidebar-selection";

/** How many titles the confirmation names before "and N more". */
const LISTED_TITLES = 5;

type Phase = "confirm" | "deleting" | "failed";

function failureReason(failure: BulkThreadFailure, t: Translations): string {
  if (failure.status === 409) {
    return t.chats.selection.failedBusy;
  }
  if (failure.status === 403) {
    return t.chats.selection.failedForbidden;
  }
  return t.chats.selection.failedOther;
}

/**
 * Confirm and run a bulk delete.
 *
 * Deletion is a hard delete — there is no trash for conversations — so this
 * names the count and the first few titles and says it cannot be undone.
 * Hosted by `SidebarSelectionProvider`, outside the virtualized lists, and it
 * keeps its own snapshot of the chats: rows leave the list as they are
 * deleted, and a partial failure must still be able to name what is left.
 *
 * The open chat is detected the way the single delete dialog detects it, and
 * only that one gets the forced reset and the navigation to a new chat; every
 * other deleted chat gets a non-forced reset, which frees a live chat slot it
 * may hold without touching the page. A chat that failed (a 409 while its run
 * is in flight, a 403) stays selected and stays in this dialog, which offers
 * to try those again — nothing is retried on its own.
 */
export function ThreadBulkDeleteDialog({
  request,
  store,
  onClose,
}: {
  request: BulkDeleteRequest | null;
  store: SidebarSelectionStore;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const pathname = usePathname();
  const { thread_id: threadIdFromPath, agent_name: agentNameFromPath } =
    useParams<{ thread_id: string; agent_name?: string }>();
  const { mutateAsync: deleteThreads } = useDeleteThreads();

  const [threads, setThreads] = useState<readonly AgentThread[]>(
    request?.threads ?? [],
  );
  const [phase, setPhase] = useState<Phase>("confirm");
  const [failures, setFailures] = useState<ReadonlyMap<
    string,
    BulkThreadFailure
  > | null>(null);
  const [progress, setProgress] = useState(0);
  const inFlight = useRef(false);
  const cancelRef = useRef<HTMLButtonElement>(null);

  // Take the snapshot when a request arrives — during render, so the dialog
  // never paints the previous request's chats for a frame — and keep it:
  // later list changes (a row deleted elsewhere, a refetch) must not change
  // what the user confirmed. A closed dialog keeps its content for the exit
  // animation.
  const [snapshotOf, setSnapshotOf] = useState(request);
  if (request !== snapshotOf) {
    setSnapshotOf(request);
    if (request) {
      setThreads(request.threads);
      setPhase("confirm");
      setFailures(null);
      setProgress(0);
    }
  }

  useEffect(() => {
    // Back from a failed run: put focus where the next decision is made.
    if (phase === "failed") {
      cancelRef.current?.focus();
    }
  }, [phase]);

  const close = () => {
    if (!inFlight.current) {
      onClose();
    }
  };

  const handleDelete = async () => {
    if (!request || inFlight.current || threads.length === 0) {
      return;
    }
    inFlight.current = true;
    setPhase("deleting");
    setProgress(0);
    const currentPathname =
      typeof window === "undefined" ? pathname : window.location.pathname;
    const nextPath = pathOfThread("new", { agent_name: agentNameFromPath });
    const isNewThreadPath = currentPathname === nextPath;
    const isCurrentThread = (thread: AgentThread) =>
      thread.thread_id === threadIdFromPath ||
      pathOfThread(thread) === currentPathname ||
      (isNewThreadPath && request.recentThreadId === thread.thread_id);
    const currentThreadIds = new Set(
      threads.filter(isCurrentThread).map((thread) => thread.thread_id),
    );

    try {
      const result = await deleteThreads({
        threadIds: threads.map((thread) => thread.thread_id),
        onProgress: (done) => setProgress(done),
        onDeleted: (threadId) => {
          const isCurrent = currentThreadIds.has(threadId);
          resetThreadChatAfterDelete({
            deletedThreadId: threadId,
            nextPath,
            force: isCurrent,
          });
          if (isCurrent) {
            void router.replace(nextPath);
          }
        },
      });
      if (result.deleted.length > 0) {
        toast.success(t.chats.selection.deleted(result.deleted.length));
      }
      const failedIds = result.failed.map((failure) => failure.threadId);
      store.replace(failedIds);
      if (result.failed.length === 0) {
        inFlight.current = false;
        onClose();
        return;
      }
      setFailures(
        new Map(result.failed.map((failure) => [failure.threadId, failure])),
      );
      const failedSet = new Set(failedIds);
      setThreads((current) =>
        current.filter((thread) => failedSet.has(thread.thread_id)),
      );
      setPhase("failed");
    } catch (error) {
      // The hook reports per chat and does not reject; this is a bug guard.
      console.error("Failed to delete chats:", error);
      toast.error(t.chats.deleteFailed);
      setPhase("confirm");
    } finally {
      inFlight.current = false;
    }
  };

  const count = threads.length;
  const deleting = phase === "deleting";
  const listed = threads.slice(0, LISTED_TITLES);
  const includesOpenChat =
    phase === "confirm" &&
    threads.some(
      (thread) =>
        thread.thread_id === threadIdFromPath ||
        pathOfThread(thread) === pathname,
    );

  return (
    <Dialog
      open={request !== null}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent
        data-testid="thread-bulk-delete-dialog"
        showCloseButton={!deleting}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          cancelRef.current?.focus();
        }}
        onEscapeKeyDown={(event) => {
          if (inFlight.current) event.preventDefault();
        }}
        onInteractOutside={(event) => {
          if (inFlight.current) event.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>
            {phase === "failed"
              ? t.chats.selection.deleteFailedTitle(count)
              : t.chats.selection.deleteTitle(count)}
          </DialogTitle>
          <DialogDescription className="break-words">
            {phase === "failed"
              ? t.chats.selection.deleteFailedDescription
              : t.chats.selection.deleteDescription}
          </DialogDescription>
        </DialogHeader>
        <ul
          className="text-muted-foreground flex flex-col gap-1 text-sm"
          data-testid="thread-bulk-delete-titles"
        >
          {listed.map((thread) => {
            const failure = failures?.get(thread.thread_id);
            return (
              <li key={thread.thread_id} className="min-w-0">
                <span className="text-foreground block truncate">
                  {titleOfThread(thread, t.pages.untitled)}
                </span>
                {failure && (
                  <span className="text-destructive block text-xs">
                    {failureReason(failure, t)}
                  </span>
                )}
              </li>
            );
          })}
          {count > listed.length && (
            <li>{t.chats.selection.deleteMore(count - listed.length)}</li>
          )}
        </ul>
        {includesOpenChat && (
          <p className="text-muted-foreground text-sm">
            {t.chats.selection.deleteIncludesOpenChat}
          </p>
        )}
        <DialogFooter>
          <Button
            ref={cancelRef}
            variant="outline"
            onClick={close}
            disabled={deleting}
          >
            {t.common.cancel}
          </Button>
          <Button
            variant="destructive"
            onClick={() => void handleDelete()}
            disabled={deleting || count === 0}
          >
            {deleting
              ? t.chats.selection.deleting(progress, count)
              : phase === "failed"
                ? t.chats.selection.retry
                : t.chats.selection.deleteConfirm(count)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
