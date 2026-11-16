import { useCallback, useEffect, useRef } from "react";
import { toast } from "sonner";

import { useI18n } from "@/core/i18n/hooks";
import { useArchiveThread, useArchiveThreads } from "@/core/threads/archive";
import type { BulkThreadResult } from "@/core/threads/bulk";

export function useThreadArchiveAction() {
  const { t } = useI18n();
  const mutation = useArchiveThread({
    onSuccess(_data, { threadId, archived }) {
      if (archived) {
        toast.success(t.chats.archiveSuccess, {
          description: t.chats.archiveDescription,
          action: {
            label: t.chats.undoArchive,
            onClick: () => setArchived(threadId, false),
          },
        });
      } else {
        toast.success(t.chats.restoreSuccess);
      }
    },
    onError() {
      toast.error(t.chats.archiveFailed);
    },
  });

  function setArchived(threadId: string, archived: boolean) {
    mutation.mutate({ threadId, archived });
  }

  return { setArchived, isPending: mutation.isPending };
}

/**
 * Archive several chats with one toast and one **Undo** that restores the
 * whole batch — N single archives would stack N toasts, each undoing one chat.
 * `onSettled` reports the batch's outcome so the caller can keep the failures
 * selected.
 */
export function useThreadsArchiveAction({
  onSettled,
}: {
  onSettled?: (result: BulkThreadResult, archived: boolean) => void;
} = {}) {
  const { t } = useI18n();
  const onSettledRef = useRef(onSettled);
  useEffect(() => {
    onSettledRef.current = onSettled;
  }, [onSettled]);
  const { mutate, isPending } = useArchiveThreads({
    onSettled(result, { archived }) {
      const { succeeded, failed } = result;
      if (succeeded.length > 0) {
        if (archived) {
          toast.success(t.chats.selection.archived(succeeded.length), {
            description: t.chats.archiveDescription,
            action: {
              label: t.chats.undoArchive,
              onClick: () => mutate({ threadIds: succeeded, archived: false }),
            },
          });
        } else {
          toast.success(t.chats.selection.restored(succeeded.length));
        }
      }
      if (failed.length > 0) {
        toast.error(t.chats.selection.archiveFailed(failed.length));
      }
      onSettledRef.current?.(result, archived);
    },
  });

  const setArchived = useCallback(
    (threadIds: readonly string[], archived: boolean) => {
      if (threadIds.length > 0) {
        mutate({ threadIds, archived });
      }
    },
    [mutate],
  );

  return { setArchived, isPending };
}
