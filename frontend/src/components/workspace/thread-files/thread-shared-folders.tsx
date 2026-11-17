"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FileIcon, FolderIcon, RefreshCwIcon } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { FolderLedgerRequestError } from "@/core/folder-ledger/api";
import {
  threadFoldersQueryKey,
  useFolderDetail,
  useThreadFolders,
} from "@/core/folder-ledger/hooks";
import type {
  LedgerFolder,
  LedgerFolderRole,
  LedgerFolderThread,
} from "@/core/folder-ledger/types";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

function roleLabel(role: LedgerFolderRole | null, t: Translations) {
  switch (role) {
    case "created":
      return t.folderLedger.roleCreated;
    case "edited":
      return t.folderLedger.roleEdited;
    case "inherited":
      return t.folderLedger.roleInherited;
    default:
      return null;
  }
}

/**
 * The top of the Files tab: one line saying this chat's own folder is deleted
 * with it, then the folders in shared mounts the chat created, edited or
 * inherited, which outlive it. The shared list stays hidden when the
 * deployment does not track folders or the chat used none.
 */
export function ThreadSharedFolders({
  threadId,
  isRunning,
}: {
  threadId: string;
  /** A finished run may have touched new folders: refetch when it ends. */
  isRunning: boolean;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const query = useThreadFolders(threadId);
  // The id outlives `open`, so the dialog keeps its content while it closes.
  const [detail, setDetail] = useState<{ id: string; open: boolean } | null>(
    null,
  );
  const headingId = useId();

  const wasRunningRef = useRef(isRunning);
  useEffect(() => {
    if (wasRunningRef.current && !isRunning) {
      void queryClient.invalidateQueries({
        queryKey: threadFoldersQueryKey(threadId),
      });
    }
    wasRunningRef.current = isRunning;
  }, [isRunning, queryClient, threadId]);

  const folders = query.data?.available ? query.data.folders : [];
  // A Gateway without the ledger routes answers 404: nothing to show then.
  const failed =
    query.isError &&
    !query.data &&
    !(
      query.error instanceof FolderLedgerRequestError &&
      query.error.status === 404
    );

  return (
    <div className="flex shrink-0 flex-col gap-2">
      <p
        className="text-muted-foreground px-1 text-xs"
        data-testid="thread-own-folder-note"
      >
        {t.threadFiles.ownFolderNote}
      </p>
      {failed && (
        <div className="flex items-center justify-between gap-2 rounded-lg border px-3 py-2">
          <p role="alert" className="text-destructive text-xs">
            {t.folderLedger.sharedLoadFailed}
          </p>
          <Button
            variant="ghost"
            size="sm"
            className="h-7"
            onClick={() => {
              void query.refetch();
            }}
          >
            <RefreshCwIcon />
            {t.threadFiles.retry}
          </Button>
        </div>
      )}
      {folders.length > 0 && (
        <section
          aria-labelledby={headingId}
          className="flex min-h-0 flex-col rounded-lg border"
          data-testid="thread-shared-folders"
        >
          <header className="border-b px-3 py-2">
            <h3 id={headingId} className="text-sm font-medium">
              {t.folderLedger.sharedTitle}
            </h3>
            <p className="text-muted-foreground text-xs">
              {t.folderLedger.sharedDescription}
            </p>
          </header>
          <ul className="flex max-h-44 flex-col overflow-y-auto py-1">
            {folders.map((folder) => (
              <SharedFolderRow
                key={folder.id}
                folder={folder}
                onOpen={() => setDetail({ id: folder.id, open: true })}
              />
            ))}
          </ul>
        </section>
      )}
      <FolderDetailsDialog
        folderId={detail?.id ?? null}
        open={detail?.open ?? false}
        threadId={threadId}
        onClose={() =>
          setDetail((current) => current && { ...current, open: false })
        }
      />
    </div>
  );
}

function SharedFolderRow({
  folder,
  onOpen,
}: {
  folder: LedgerFolder;
  onOpen: () => void;
}) {
  const { t, locale } = useI18n();
  const metaId = useId();
  const role = roleLabel(folder.role, t);
  const meta = [
    folder.mount_path,
    folder.last_at
      ? t.folderLedger.lastEdit(formatTimeAgo(folder.last_at, locale))
      : null,
    folder.other_live_threads > 0
      ? t.folderLedger.otherChats(folder.other_live_threads)
      : t.folderLedger.onlyThisChat,
    folder.host_visible ? null : t.folderLedger.hostHidden,
  ].filter((part): part is string => Boolean(part));
  const Icon = folder.kind === "file" ? FileIcon : FolderIcon;
  return (
    <li>
      <button
        type="button"
        aria-label={t.folderLedger.showDetails(folder.name)}
        aria-describedby={metaId}
        className="hover:bg-accent focus-visible:ring-ring/50 flex w-full flex-col gap-0.5 px-3 py-1.5 text-left outline-none focus-visible:ring-[3px]"
        onClick={onOpen}
      >
        <span className="flex min-w-0 items-center gap-2">
          <Icon className="text-muted-foreground size-4 shrink-0" />
          <span
            className="min-w-0 truncate font-mono text-sm"
            title={folder.path}
          >
            {folder.name}
          </span>
          {role && <Badge variant="secondary">{role}</Badge>}
        </span>
        <span
          id={metaId}
          className="text-muted-foreground truncate pl-6 text-xs"
        >
          {meta.join(" · ")}
        </span>
      </button>
    </li>
  );
}

function threadLabel(
  thread: LedgerFolderThread | undefined,
  threadId: string,
  t: Translations,
) {
  if (thread?.thread_id === threadId) {
    return t.folderLedger.thisChat;
  }
  if (!thread?.own) {
    return t.folderLedger.otherUserChat;
  }
  return thread.title ?? t.folderLedger.untitledChat;
}

/** One folder's provenance: who created it, the conversations, the edit log. */
function FolderDetailsDialog({
  folderId,
  open,
  threadId,
  onClose,
}: {
  folderId: string | null;
  open: boolean;
  threadId: string;
  onClose: () => void;
}) {
  const { t, locale } = useI18n();
  // Closing disables the query, which cancels a request still in flight.
  const detail = useFolderDetail(folderId, { enabled: open });
  const data = detail.data?.folder.id === folderId ? detail.data : undefined;
  const threadsById = new Map(
    (data?.threads ?? []).map((thread) => [thread.thread_id, thread]),
  );
  const opLabels = t.folderLedger.ops;

  return (
    <Dialog
      open={open && folderId !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-mono break-all">
            {data?.folder.name ?? t.folderLedger.sharedTitle}
          </DialogTitle>
          <DialogDescription className="break-all">
            {data
              ? t.folderLedger.detailsDescription(data.folder.path)
              : t.folderLedger.sharedLoading}
          </DialogDescription>
        </DialogHeader>
        {data ? (
          <div className="flex min-w-0 flex-col gap-4 text-sm">
            <div className="flex flex-col gap-1">
              <p>
                {t.folderLedger.attribution[data.folder.created_attribution]}
              </p>
              <p className="text-muted-foreground text-xs">
                {[
                  t.folderLedger.activity(
                    data.folder.writes,
                    data.folder.edits,
                    data.folder.shell_ops,
                  ),
                  data.folder.last_at
                    ? t.folderLedger.lastEdit(
                        formatTimeAgo(data.folder.last_at, locale),
                      )
                    : null,
                  data.folder.host_visible ? null : t.folderLedger.hostHidden,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
            <section className="flex flex-col gap-1.5">
              <h3 className="font-medium">{t.folderLedger.conversations}</h3>
              <ul className="flex flex-col gap-1">
                {data.threads.map((thread) => (
                  <li
                    key={thread.thread_id}
                    className="flex min-w-0 items-center gap-2"
                  >
                    <span
                      className={cn(
                        "min-w-0 truncate",
                        thread.deleted && "text-muted-foreground",
                      )}
                    >
                      {threadLabel(thread, threadId, t)}
                    </span>
                    {roleLabel(thread.role, t) && (
                      <Badge variant="secondary">
                        {roleLabel(thread.role, t)}
                      </Badge>
                    )}
                    {thread.deleted && (
                      <Badge variant="outline">
                        {t.folderLedger.deletedChat}
                      </Badge>
                    )}
                    {thread.last_at && (
                      <span className="text-muted-foreground ml-auto shrink-0 text-xs">
                        {formatTimeAgo(thread.last_at, locale)}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
            <section className="flex flex-col gap-1.5">
              <h3 className="font-medium">{t.folderLedger.editLog}</h3>
              {data.events.length === 0 ? (
                <p className="text-muted-foreground text-xs">
                  {t.folderLedger.editLogEmpty}
                </p>
              ) : (
                <ol
                  aria-label={t.folderLedger.editLog}
                  className="flex max-h-56 flex-col gap-1 overflow-y-auto"
                >
                  {data.events.map((event, index) => (
                    <li
                      key={`${event.ts ?? ""}:${event.rel_path}:${index}`}
                      className="flex min-w-0 flex-col text-xs"
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="shrink-0 font-medium">
                          {opLabels[event.op]}
                        </span>
                        <span
                          className="min-w-0 truncate font-mono"
                          title={event.rel_path}
                        >
                          {event.rel_path}
                        </span>
                      </span>
                      <span className="text-muted-foreground truncate">
                        {[
                          threadLabel(
                            threadsById.get(event.thread_id),
                            threadId,
                            t,
                          ),
                          event.ts ? formatTimeAgo(event.ts, locale) : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>
        ) : detail.isError ? (
          <div className="flex items-center justify-between gap-2">
            <p role="alert" className="text-destructive text-sm">
              {t.folderLedger.detailsLoadFailed}
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void detail.refetch();
              }}
            >
              <RefreshCwIcon />
              {t.threadFiles.retry}
            </Button>
          </div>
        ) : (
          <div aria-busy="true" className="flex flex-col gap-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t.common.close}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
