"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FolderIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
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
import {
  deleteLedgerFolder,
  dismissLedgerFolder,
  fetchOrphanFolders,
  FolderLedgerRequestError,
} from "@/core/folder-ledger/api";
import { listenForDeletedThreads } from "@/core/folder-ledger/events";
import { FOLDER_LEDGER_QUERY_PREFIX } from "@/core/folder-ledger/hooks";
import type { OrphanFolder } from "@/core/folder-ledger/types";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

type Action = "delete" | "dismiss";

type ItemStatus =
  | { state: "working"; action: Action }
  | { state: "deleted" }
  | { state: "dismissed" }
  | { state: "failed"; message: string };

function isSettled(status: ItemStatus | undefined) {
  return status?.state === "deleted" || status?.state === "dismissed";
}

function describeFailure(
  error: unknown,
  t: Translations,
  kind: Action,
): string {
  let message: string;
  if (error instanceof FolderLedgerRequestError) {
    if (error.code === "in_use") {
      return t.folderLedger.inUse;
    }
    const reasons: Record<string, string> = t.folderLedger.reasons;
    message =
      error.code && Object.hasOwn(reasons, error.code)
        ? reasons[error.code]!
        : error.message;
  } else {
    message =
      error instanceof Error && error.message
        ? error.message
        : t.folderLedger.reasons.unknown;
  }
  return kind === "delete"
    ? t.folderLedger.deleteFailed(message)
    : t.folderLedger.dismissFailed(message);
}

/**
 * The workspace-level offer to delete shared folders that deleted
 * conversations leave without a user.
 *
 * Every delete path announces the deleted ids (`notifyThreadsDeleted`); this
 * host coalesces them, asks `POST /api/folder-ledger/orphans` once and, when
 * any folder is orphaned, opens a dialog. Nothing is deleted unless the user
 * ticks it: no box starts checked, folders that cannot be deleted from here
 * are listed with the reason and have no box, and every request runs once,
 * with its failure shown on its row and never retried automatically.
 *
 * Mounted once beside the command palette, above every route, so it covers
 * the sidebar, the chats page, projects and the bulk actions alike.
 */
export function FolderOrphanOfferHost() {
  const { t, locale } = useI18n();
  const queryClient = useQueryClient();
  const [orphans, setOrphans] = useState<OrphanFolder[]>([]);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [statuses, setStatuses] = useState<Record<string, ItemStatus>>({});
  const [busyAction, setBusyAction] = useState<Action | null>(null);
  const busy = busyAction !== null;
  const busyRef = useRef(false);
  const actionRef = useRef<AbortController | null>(null);
  const keepRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (isStaticWebsiteOnly()) {
      return;
    }
    const lookups = new Set<AbortController>();
    const stop = listenForDeletedThreads((threadIds) => {
      const controller = new AbortController();
      lookups.add(controller);
      fetchOrphanFolders(threadIds, { signal: controller.signal })
        .then((result) => {
          if (controller.signal.aborted || result.orphans.length === 0) {
            return;
          }
          setOrphans((current) => {
            const known = new Set(current.map((orphan) => orphan.id));
            return [
              ...current,
              ...result.orphans.filter((orphan) => !known.has(orphan.id)),
            ];
          });
          setOpen(true);
        })
        .catch((error: unknown) => {
          // Only an offer: the conversations are deleted either way.
          if (!controller.signal.aborted) {
            console.warn("Folder ledger: the orphan check failed.", error);
          }
        })
        .finally(() => {
          lookups.delete(controller);
        });
    });
    return () => {
      stop();
      for (const controller of lookups) {
        controller.abort();
      }
      actionRef.current?.abort();
    };
  }, []);

  const close = useCallback(() => {
    if (busyRef.current) {
      return;
    }
    setOpen(false);
    setOrphans([]);
    setSelected(new Set());
    setStatuses({});
  }, []);

  const pending = orphans.filter((orphan) => !isSettled(statuses[orphan.id]));
  const deletable = orphans.filter((orphan) => orphan.deletable);
  const kept = orphans.filter((orphan) => !orphan.deletable);
  const toDelete = deletable.filter(
    (orphan) => selected.has(orphan.id) && !isSettled(statuses[orphan.id]),
  );

  const run = useCallback(
    async (targets: OrphanFolder[], kind: Action): Promise<boolean> => {
      busyRef.current = true;
      setBusyAction(kind);
      const controller = new AbortController();
      actionRef.current = controller;
      let done = 0;
      let failed = 0;
      // One at a time and once each: a refused or failed folder is reported
      // on its row, and only the user can ask again.
      for (const orphan of targets) {
        if (controller.signal.aborted) {
          break;
        }
        setStatuses((current) => ({
          ...current,
          [orphan.id]: { state: "working", action: kind },
        }));
        try {
          if (kind === "delete") {
            await deleteLedgerFolder(orphan.id, orphan.name, {
              signal: controller.signal,
            });
          } else {
            await dismissLedgerFolder(orphan.id, {
              signal: controller.signal,
            });
          }
          done += 1;
          setStatuses((current) => ({
            ...current,
            [orphan.id]: {
              state: kind === "delete" ? "deleted" : "dismissed",
            },
          }));
          setSelected((current) => {
            const next = new Set(current);
            next.delete(orphan.id);
            return next;
          });
        } catch (error) {
          if (controller.signal.aborted) {
            break;
          }
          failed += 1;
          setStatuses((current) => ({
            ...current,
            [orphan.id]: {
              state: "failed",
              message: describeFailure(error, t, kind),
            },
          }));
        }
      }
      if (actionRef.current === controller) {
        actionRef.current = null;
      }
      busyRef.current = false;
      setBusyAction(null);
      if (done > 0) {
        void queryClient.invalidateQueries({
          queryKey: FOLDER_LEDGER_QUERY_PREFIX,
        });
        if (kind === "delete") {
          toast.success(t.folderLedger.deletedToast(done));
        }
      }
      return failed === 0 && !controller.signal.aborted;
    },
    [queryClient, t],
  );

  const deleteSelected = useCallback(async () => {
    if (busyRef.current || toDelete.length === 0) {
      return;
    }
    // The folders left unticked are kept, as the dialog says.
    if (await run(toDelete, "delete")) {
      close();
    }
  }, [close, run, toDelete]);

  const dismissAll = useCallback(async () => {
    if (busyRef.current || pending.length === 0) {
      return;
    }
    if (await run(pending, "dismiss")) {
      close();
    }
  }, [close, pending, run]);

  const renderRow = (orphan: OrphanFolder) => {
    const status = statuses[orphan.id];
    const settled = isSettled(status);
    const meta = [
      orphan.path,
      t.folderLedger.orphanStats(
        orphan.edits + orphan.writes,
        orphan.last_at ? formatTimeAgo(orphan.last_at, locale) : null,
      ),
    ].join(" · ");
    const name = (
      <span className="flex min-w-0 flex-col">
        <span className="flex min-w-0 items-center gap-2">
          <FolderIcon className="text-muted-foreground size-4 shrink-0" />
          <span
            className={cn(
              "min-w-0 truncate font-mono text-sm",
              settled && "text-muted-foreground",
            )}
          >
            {orphan.name}
          </span>
          {status?.state === "deleted" && (
            <span className="text-muted-foreground shrink-0 text-xs">
              {t.folderLedger.deletedStatus}
            </span>
          )}
          {status?.state === "dismissed" && (
            <span className="text-muted-foreground shrink-0 text-xs">
              {t.folderLedger.dismissedStatus}
            </span>
          )}
          {status?.state === "working" && (
            <span className="text-muted-foreground shrink-0 text-xs">
              {status.action === "delete"
                ? t.folderLedger.deleting
                : t.folderLedger.dismissing}
            </span>
          )}
        </span>
        <span className="text-muted-foreground truncate text-xs">{meta}</span>
        {!orphan.deletable && orphan.reason && (
          <span className="text-muted-foreground text-xs">
            {t.folderLedger.reasons[orphan.reason]}
          </span>
        )}
        {status?.state === "failed" && (
          <span className="text-destructive text-xs">{status.message}</span>
        )}
      </span>
    );
    return (
      <li
        key={orphan.id}
        data-testid="folder-orphan-row"
        data-folder-id={orphan.id}
        className="rounded-md border px-3 py-2"
      >
        {orphan.deletable ? (
          <label className="flex min-w-0 cursor-pointer items-start gap-3">
            <input
              type="checkbox"
              className="mt-1 size-4 shrink-0"
              aria-label={t.folderLedger.orphanSelect(orphan.name)}
              checked={selected.has(orphan.id)}
              disabled={busy || settled}
              onChange={(event) => {
                const { checked } = event.target;
                setSelected((current) => {
                  const next = new Set(current);
                  if (checked) {
                    next.add(orphan.id);
                  } else {
                    next.delete(orphan.id);
                  }
                  return next;
                });
              }}
            />
            {name}
          </label>
        ) : (
          name
        )}
      </li>
    );
  };

  return (
    <Dialog
      open={open && orphans.length > 0}
      onOpenChange={(next) => {
        if (!next) close();
      }}
    >
      <DialogContent
        className="max-h-[85vh] overflow-y-auto sm:max-w-lg"
        showCloseButton={!busy}
        data-testid="folder-orphan-offer"
        onOpenAutoFocus={(event) => {
          // The safe choice takes focus: Enter must not delete anything.
          event.preventDefault();
          keepRef.current?.focus();
        }}
        onEscapeKeyDown={(event) => {
          if (busyRef.current) event.preventDefault();
        }}
        onInteractOutside={(event) => {
          if (busyRef.current) event.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>
            {t.folderLedger.orphanTitle(orphans.length)}
          </DialogTitle>
          <DialogDescription>
            {t.folderLedger.orphanDescription}
          </DialogDescription>
        </DialogHeader>
        <div aria-live="polite" className="flex min-w-0 flex-col gap-3">
          {deletable.length > 0 && (
            <>
              <ul className="flex flex-col gap-2">
                {deletable.map(renderRow)}
              </ul>
              <p className="text-muted-foreground text-xs">
                {t.folderLedger.orphanWarning}
              </p>
            </>
          )}
          {kept.length > 0 && (
            <section className="flex flex-col gap-2">
              <h3 className="text-sm font-medium">
                {t.folderLedger.orphanKept}
              </h3>
              <ul className="flex flex-col gap-2">{kept.map(renderRow)}</ul>
            </section>
          )}
        </div>
        <DialogFooter className="flex-wrap gap-2">
          <Button
            variant="ghost"
            disabled={busy || pending.length === 0}
            onClick={() => void dismissAll()}
          >
            {t.folderLedger.dismiss}
          </Button>
          <Button
            ref={keepRef}
            variant="outline"
            disabled={busy}
            onClick={close}
          >
            {t.folderLedger.keep}
          </Button>
          {deletable.length > 0 && (
            <Button
              variant="destructive"
              disabled={busy || toDelete.length === 0}
              onClick={() => void deleteSelected()}
            >
              {busyAction === "delete"
                ? t.folderLedger.deleting
                : t.folderLedger.deleteSelected(toDelete.length)}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
