"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircleIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { useAutoTitleCapability } from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { PROJECTS_QUERY_KEY } from "@/core/projects/api";
import { useLocalSettings } from "@/core/settings";
import { THREAD_FOLDER_METADATA_KEY } from "@/core/threads/chat-folders";
import {
  fetchChatFolders,
  saveChatFolders,
} from "@/core/threads/chat-folders-api";
import {
  applicableItems,
  applyOrganizePlan,
  applyResultsToPlan,
  buildConsolidationItems,
  buildOrganizePlan,
  buildTargetChoices,
  collectOrganizeSuggestions,
  consolidateChatCategories,
  consolidationMinGroupSize,
  existingFolderChoices,
  fileThreadInFolder,
  organizeConcurrency,
  readCleanupPreferences,
  renameThreadKeepingRecency,
  resolveOrganizeModel,
  summarizeApply,
  type ConsolidationResult,
  type OrganizeApplyOutcome,
  type OrganizeFailure,
  type OrganizeItemResult,
  type OrganizePlan,
} from "@/core/threads/chat-organize";
import {
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  setThreadMetadataInCaches,
  setThreadTitleInCaches,
} from "@/core/threads/hooks";
import {
  CHAT_FOLDERS_MUTATION_SCOPE,
  CHAT_FOLDERS_QUERY_KEY,
  newFolderId,
  useChatFolders,
} from "@/core/threads/use-chat-folders";

import { CleanupPreview, type PlanUpdate } from "./cleanup-preview";
import { stepFailureReason, stopReason } from "./cleanup-reasons";
import {
  loadAllConversations,
  loadSelectedConversations,
  type CleanupScope,
} from "./cleanup-scope";
import {
  CleanupSetup,
  SERVER_DEFAULT_MODEL,
  type CleanupScopeStatus,
  type CleanupSetupState,
} from "./cleanup-setup";

type Phase =
  | { name: "setup" }
  | { name: "running"; done: number; total: number; consolidating: boolean }
  | { name: "preview" }
  | { name: "applying"; done: number; total: number }
  | {
      name: "result";
      outcome: Extract<OrganizeApplyOutcome, { status: "applied" }>;
    };

// Stable defaults, so the memoized target list is not rebuilt every render.
const NO_SELECTED_FOLDERS: string[] = [];
const NO_NEW_FOLDERS: string[] = [];

/**
 * Clean-up mode (fork feature): a model the user picks reads the chosen
 * conversations (or all of them), suggests titles and folders, and the user
 * reviews and applies the result.
 *
 * Four steps, and only the last one writes:
 *
 * 1. **Setup** — scope, model (the shared picker, with a server-default row),
 *    rename on/off, and how to file: not at all, into folders the user picks or
 *    names, or into folders the model proposes. Remembered per browser.
 * 2. **Run** — one read-only suggest call per conversation, one at a time on a
 *    local model and three at a time otherwise; then, in auto mode, one call
 *    that merges the categories into folders. Cancel or closing the dialog
 *    aborts the calls in flight. A spend cap (402), a refused model (400/403)
 *    stops the whole pass with the Gateway's own message.
 * 3. **Preview** — every title and folder is editable, every row can be
 *    left out, and proposed folders can be renamed or merged.
 * 4. **Apply** — new folders in one write, then per conversation a move and a
 *    rename that do not gate each other; the lists refresh once at the end and
 *    every failure is listed, never retried on its own.
 *
 * Hosted by the sidebar selection provider, outside the virtualized lists.
 * The dialog cannot be dismissed while writes are in flight.
 */
export function ChatCleanupDialog({
  open,
  onOpenChange,
  threadIds,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The conversations to clean up; `null` = all conversations. */
  threadIds: string[] | null;
}) {
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  // Every opening is a fresh pass: the flow below is keyed on it, so a
  // reopened dialog never shows the previous pass's plan or results. The flow
  // stays mounted while closed, which keeps the exit animation's content.
  const [session, setSession] = useState(0);
  const [lastOpen, setLastOpen] = useState(open);
  if (open !== lastOpen) {
    setLastOpen(open);
    if (open) {
      setSession((value) => value + 1);
    }
  }

  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (!next && busyRef.current) {
        return;
      }
      onOpenChange(next);
    },
    [onOpenChange],
  );
  const handleBusyChange = useCallback((next: boolean) => {
    busyRef.current = next;
    setBusy(next);
  }, []);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        data-testid="chat-cleanup-dialog"
        className="flex max-h-[min(90dvh,56rem)] flex-col gap-4 sm:max-w-3xl"
        showCloseButton={!busy}
        onEscapeKeyDown={(event) => {
          if (busyRef.current) event.preventDefault();
        }}
        onInteractOutside={(event) => {
          if (busyRef.current) event.preventDefault();
        }}
      >
        <ChatCleanupFlow
          key={session}
          open={open}
          threadIds={threadIds}
          onClose={() => handleOpenChange(false)}
          onBusyChange={handleBusyChange}
        />
      </DialogContent>
    </Dialog>
  );
}

function ChatCleanupFlow({
  open,
  threadIds,
  onClose,
  onBusyChange,
}: {
  open: boolean;
  threadIds: string[] | null;
  onClose: () => void;
  onBusyChange: (busy: boolean) => void;
}) {
  const { t } = useI18n();
  const copy = t.chatCleanup;
  const queryClient = useQueryClient();
  const { models } = useModels();
  const { enabled: renameAvailable, modelName: operatorTitleModel } =
    useAutoTitleCapability();
  const [settings, setSettings] = useLocalSettings();
  const { folders } = useChatFolders();

  // The ids this pass was opened with; a later change of selection belongs to
  // the next opening.
  const [scopeIds] = useState(() => (threadIds ? [...threadIds] : null));
  const scopeQuery = useQuery<CleanupScope>({
    queryKey: ["chat-cleanup", "scope", scopeIds],
    queryFn: ({ signal }) =>
      scopeIds
        ? loadSelectedConversations({
            threadIds: scopeIds,
            queryClient,
            signal,
          })
        : loadAllConversations({ signal }),
    enabled: open,
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const scope = scopeQuery.data ?? null;

  const preferences = readCleanupPreferences(settings.chatCleanup, models);
  // Derived, not copied into state on mount: the remembered model can only be
  // checked against the catalog once `models` has loaded.
  const [setupEdits, setSetupEdits] = useState<Partial<CleanupSetupState>>({});
  const setup: CleanupSetupState = {
    model: preferences.modelName ?? SERVER_DEFAULT_MODEL,
    rename: preferences.rename,
    folderMode: preferences.folderMode,
    selectedFolderIds: NO_SELECTED_FOLDERS,
    newFolderNames: NO_NEW_FOLDERS,
    maxNewFolders: preferences.maxNewFolders,
    ...setupEdits,
  };
  const pickedModel =
    setup.model === SERVER_DEFAULT_MODEL ? undefined : setup.model;
  const resolvedModel = resolveOrganizeModel(
    models,
    pickedModel,
    operatorTitleModel,
  );
  const concurrency = organizeConcurrency(resolvedModel);
  const rename = renameAvailable && setup.rename;
  const targetChoices = useMemo(
    () =>
      buildTargetChoices(
        folders,
        setup.selectedFolderIds,
        setup.newFolderNames,
      ),
    [folders, setup.selectedFolderIds, setup.newFolderNames],
  );

  const [phase, setPhase] = useState<Phase>({ name: "setup" });
  const [plan, setPlan] = useState<OrganizePlan | null>(null);
  const [failures, setFailures] = useState<readonly OrganizeFailure[]>([]);
  const [notices, setNotices] = useState<readonly string[]>([]);
  const [results, setResults] = useState<ReadonlyMap<
    string,
    OrganizeItemResult
  > | null>(null);

  const runRef = useRef<AbortController | null>(null);
  const applyingRef = useRef(false);

  // A dialog aborts its requests when it closes (workspace AGENTS.md); the
  // read-only calls are cancelled, and a late answer finds `runRef` changed.
  useEffect(() => {
    if (!open) {
      runRef.current?.abort();
      runRef.current = null;
    }
  }, [open]);
  useEffect(
    () => () => {
      runRef.current?.abort();
      runRef.current = null;
    },
    [],
  );

  const folderWrite = useMutation({
    mutationFn: (write: () => Promise<unknown>) => write(),
    // Queued behind the sidebar's own whole-list folder writes, so the fresh
    // read inside starts from the list they left.
    scope: { id: CHAT_FOLDERS_MUTATION_SCOPE },
  });

  const threadTitles = useMemo(
    () =>
      new Map(
        (scope?.threads ?? []).map((thread) => [thread.threadId, thread.title]),
      ),
    [scope],
  );

  const scopeStatus: CleanupScopeStatus = scope
    ? {
        status: "ready",
        all: scopeIds === null,
        count: scope.threads.length,
        capped: scope.capped,
        missing: scope.missing.length,
      }
    : scopeQuery.isError
      ? { status: "error", retry: () => void scopeQuery.refetch() }
      : { status: "loading" };

  const nothingToDo = !rename && setup.folderMode === "none";
  const needsTargets =
    setup.folderMode === "targets" && targetChoices.targets.length === 0;
  const canStart =
    phase.name === "setup" &&
    scope !== null &&
    scope.threads.length > 0 &&
    !nothingToDo &&
    !needsTargets;

  const updateSetup = useCallback((patch: Partial<CleanupSetupState>) => {
    setSetupEdits((current) => ({ ...current, ...patch }));
  }, []);

  const updatePlan = useCallback<PlanUpdate>((update) => {
    setPlan((current) => (current ? update(current) : current));
  }, []);

  const start = async () => {
    if (!canStart || !scope) {
      return;
    }
    setSettings("chatCleanup", {
      // Before the catalog loads the picker shows the server default only
      // because the remembered model cannot be checked yet; that is not a
      // choice, so it must not overwrite the remembered one.
      ...(setupEdits.model !== undefined || models.length > 0
        ? { modelName: pickedModel }
        : {}),
      rename: setup.rename,
      folderMode: setup.folderMode,
      maxNewFolders: setup.maxNewFolders,
    });
    runRef.current?.abort();
    const controller = new AbortController();
    runRef.current = controller;
    const isCurrent = () =>
      runRef.current === controller && !controller.signal.aborted;

    const mode = setup.folderMode;
    const threads = scope.threads;
    const folderSnapshot = folders;
    const existing = existingFolderChoices(folderSnapshot);
    const total = threads.length;
    setNotices([]);
    setFailures([]);
    setResults(null);
    setPlan(null);
    setPhase({ name: "running", done: 0, total, consolidating: false });

    const nextNotices: string[] = [];
    try {
      const collection = await collectOrganizeSuggestions({
        threadIds: threads.map((thread) => thread.threadId),
        options: {
          modelName: pickedModel,
          rename,
          mode,
          targets: targetChoices.targets,
          existing,
        },
        concurrency,
        signal: controller.signal,
        onProgress: (done) => {
          if (isCurrent()) {
            setPhase({ name: "running", done, total, consolidating: false });
          }
        },
      });
      if (!isCurrent()) {
        return;
      }
      if (collection.stop) {
        nextNotices.push(copy.stopped(stopReason(collection.stop, copy)));
        if (mode === "auto" && collection.suggestions.length > 0) {
          nextNotices.push(copy.foldersSkipped);
        }
      }
      if (
        rename &&
        collection.suggestions.some((suggestion) => suggestion.renameDisabled)
      ) {
        nextNotices.push(copy.renameDisabled);
      }

      let consolidation: ConsolidationResult | null = null;
      const items =
        mode === "auto" && !collection.stop
          ? buildConsolidationItems(collection.suggestions)
          : [];
      if (items.length > 0) {
        setPhase({ name: "running", done: total, total, consolidating: true });
        try {
          consolidation = await consolidateChatCategories({
            modelName: pickedModel,
            items,
            existing,
            maxNewFolders: setup.maxNewFolders,
            minGroupSize: consolidationMinGroupSize(items.length),
            signal: controller.signal,
          });
        } catch (error) {
          if (!isCurrent()) {
            return;
          }
          nextNotices.push(
            copy.consolidateFailed(
              error instanceof Error && error.message
                ? error.message
                : copy.reasons.other,
            ),
          );
        }
        if (!isCurrent()) {
          return;
        }
      }

      runRef.current = null;
      if (collection.suggestions.length === 0 && collection.stop) {
        // Nothing to review, and the same request would stop again: back to
        // the setup, where the model can be changed.
        setNotices(nextNotices);
        setPhase({ name: "setup" });
        return;
      }
      if (
        collection.suggestions.length === 0 &&
        collection.failures.length > 0
      ) {
        nextNotices.push(copy.nothingAnalyzed);
      }
      setPlan(
        buildOrganizePlan({
          threads,
          suggestions: collection.suggestions,
          mode,
          folders: folderSnapshot,
          proposed: targetChoices.proposed,
          consolidation,
        }),
      );
      setFailures(collection.failures);
      setNotices(nextNotices);
      setPhase({ name: "preview" });
    } catch (error) {
      // Every request failure is reported per conversation; this is a guard.
      if (!isCurrent()) {
        return;
      }
      console.error("Chat clean-up failed:", error);
      runRef.current = null;
      setNotices([copy.reasons.other]);
      setPhase({ name: "setup" });
    }
  };

  const cancelRun = () => {
    runRef.current?.abort();
    runRef.current = null;
    setPhase({ name: "setup" });
  };

  const apply = async () => {
    if (!plan || applyingRef.current) {
      return;
    }
    const total = applicableItems(plan).length;
    if (total === 0) {
      return;
    }
    applyingRef.current = true;
    onBusyChange(true);
    setNotices([]);
    setPhase({ name: "applying", done: 0, total });
    let done = 0;
    try {
      // A list read that started before the first write must not land after
      // the cache updates below and put the old titles or placement back.
      await Promise.all([
        queryClient.cancelQueries({
          queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
        }),
        queryClient.cancelQueries({ queryKey: ["threads", "search"] }),
      ]);
      const outcome = await applyOrganizePlan(plan, {
        fetchFolders: fetchChatFolders,
        saveFolders: async (next) => {
          const stored = await saveChatFolders(next);
          if (stored) {
            // Inside the queued write: the sidebar's next folder edit starts
            // from a list that already holds these folders.
            queryClient.setQueryData(CHAT_FOLDERS_QUERY_KEY, stored);
          }
          return stored;
        },
        moveThread: async (threadId, folderId) => {
          const metadata = await fileThreadInFolder(threadId, folderId);
          setThreadMetadataInCaches(queryClient, threadId, {
            ...metadata,
            [THREAD_FOLDER_METADATA_KEY]: folderId,
          });
        },
        renameThread: async (threadId, title) => {
          await renameThreadKeepingRecency(threadId, title);
          setThreadTitleInCaches(queryClient, threadId, title);
        },
        newFolderId,
        serializeFolderWrite: <T,>(write: () => Promise<T>) =>
          folderWrite.mutateAsync(write) as Promise<T>,
        onItem: () => {
          done += 1;
          setPhase({ name: "applying", done, total });
        },
      });
      if (outcome.status === "folders_unavailable") {
        setNotices([copy.foldersUnavailable]);
        setPhase({ name: "preview" });
        return;
      }
      setPlan(applyResultsToPlan(plan, outcome));
      setResults(
        new Map(outcome.results.map((result) => [result.threadId, result])),
      );
      setNotices(outcome.folderSaveFailed ? [copy.foldersSaveFailed] : []);
      setPhase({ name: "result", outcome });
    } catch (error) {
      // The apply step reports per conversation; this is a guard.
      console.error("Chat clean-up apply failed:", error);
      setNotices([copy.reasons.other]);
      setPhase({ name: "preview" });
    } finally {
      applyingRef.current = false;
      onBusyChange(false);
      // One refresh for the whole pass, not one per conversation: N
      // invalidations would restart the sidebar's paged refetch N times.
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      void queryClient.invalidateQueries({
        queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
      });
      void queryClient.invalidateQueries({ queryKey: CHAT_FOLDERS_QUERY_KEY });
      void queryClient.invalidateQueries({
        queryKey: [...PROJECTS_QUERY_KEY, "threads"],
      });
      void queryClient.invalidateQueries({ queryKey: ["workspace-search"] });
    }
  };

  const applyCount = plan ? applicableItems(plan).length : 0;
  const title =
    phase.name === "preview" || phase.name === "applying"
      ? copy.previewTitle
      : phase.name === "result"
        ? copy.resultTitle
        : copy.title;
  const description =
    phase.name === "preview" || phase.name === "applying"
      ? copy.previewDescription
      : phase.name === "result"
        ? null
        : copy.description;

  return (
    <>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        {description ? (
          <DialogDescription>{description}</DialogDescription>
        ) : (
          <DialogDescription className="sr-only">
            {copy.title}
          </DialogDescription>
        )}
      </DialogHeader>

      <div className="-mx-6 min-h-0 flex-1 overflow-y-auto px-6">
        {notices.length > 0 && (
          <div className="mb-4 flex flex-col gap-2">
            {notices.map((notice) => (
              <Alert
                key={notice}
                variant="destructive"
                data-testid="chat-cleanup-notice"
              >
                <AlertDescription>{notice}</AlertDescription>
              </Alert>
            ))}
          </div>
        )}

        {phase.name === "setup" && (
          <CleanupSetup
            scope={scopeStatus}
            state={setup}
            onChange={updateSetup}
            models={models}
            folders={folders}
            renameAvailable={renameAvailable}
            localPace={Boolean(resolvedModel?.size_bytes)}
          />
        )}

        {phase.name === "running" && (
          <div
            className="flex flex-col gap-3 py-2"
            data-testid="chat-cleanup-running"
            aria-live="polite"
          >
            <div className="flex items-center gap-2 text-sm">
              <LoaderCircleIcon className="size-4 animate-spin motion-reduce:animate-none" />
              <span>
                {phase.consolidating
                  ? copy.consolidating
                  : copy.analyzing(phase.done, phase.total)}
              </span>
            </div>
            <Progress
              value={phase.total ? (phase.done / phase.total) * 100 : 0}
              aria-label={copy.analyzing(phase.done, phase.total)}
            />
            <p className="text-muted-foreground text-xs">{copy.runningHint}</p>
          </div>
        )}

        {(phase.name === "preview" || phase.name === "applying") && plan && (
          <>
            {phase.name === "applying" && (
              <div
                className="mb-4 flex flex-col gap-2"
                aria-live="polite"
                data-testid="chat-cleanup-applying"
              >
                <div className="flex items-center gap-2 text-sm">
                  <LoaderCircleIcon className="size-4 animate-spin motion-reduce:animate-none" />
                  <span>{copy.applying(phase.done, phase.total)}</span>
                </div>
                <Progress
                  value={phase.total ? (phase.done / phase.total) * 100 : 0}
                  aria-label={copy.applying(phase.done, phase.total)}
                />
                <p className="text-muted-foreground text-xs">
                  {copy.applyingHint}
                </p>
              </div>
            )}
            <CleanupPreview
              plan={plan}
              folders={folders}
              threadTitles={threadTitles}
              failures={failures}
              results={results}
              disabled={phase.name === "applying"}
              onUpdate={updatePlan}
            />
          </>
        )}

        {phase.name === "result" && (
          <CleanupResult
            outcome={phase.outcome}
            threadTitles={threadTitles}
            plan={plan}
          />
        )}
      </div>

      <DialogFooter>
        {phase.name === "setup" && (
          <>
            <Button type="button" variant="outline" onClick={onClose}>
              {t.common.cancel}
            </Button>
            <Button
              type="button"
              onClick={() => void start()}
              disabled={!canStart}
              data-testid="chat-cleanup-start"
            >
              {copy.start}
            </Button>
          </>
        )}
        {phase.name === "running" && (
          <Button
            type="button"
            variant="outline"
            onClick={cancelRun}
            data-testid="chat-cleanup-cancel-run"
          >
            {t.common.cancel}
          </Button>
        )}
        {(phase.name === "preview" || phase.name === "applying") && (
          <>
            <Button
              type="button"
              variant="outline"
              disabled={phase.name === "applying"}
              onClick={() => {
                setPlan(null);
                setResults(null);
                setFailures([]);
                setNotices([]);
                setPhase({ name: "setup" });
              }}
            >
              {copy.back}
            </Button>
            <Button
              type="button"
              onClick={() => void apply()}
              disabled={phase.name === "applying" || applyCount === 0}
              data-testid="chat-cleanup-apply"
            >
              {phase.name === "applying"
                ? copy.applying(phase.done, phase.total)
                : copy.apply(applyCount)}
            </Button>
          </>
        )}
        {phase.name === "result" && (
          <>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPhase({ name: "preview" })}
              data-testid="chat-cleanup-review-again"
            >
              {copy.reviewAgain}
            </Button>
            <Button
              type="button"
              onClick={onClose}
              data-testid="chat-cleanup-done"
            >
              {copy.done}
            </Button>
          </>
        )}
      </DialogFooter>
    </>
  );
}

function CleanupResult({
  outcome,
  threadTitles,
  plan,
}: {
  outcome: Extract<OrganizeApplyOutcome, { status: "applied" }>;
  threadTitles: ReadonlyMap<string, string | null>;
  plan: OrganizePlan | null;
}) {
  const { t } = useI18n();
  const copy = t.chatCleanup;
  const summary = summarizeApply(outcome.results);
  const failed = outcome.results.filter(
    (result) =>
      result.move.state === "failed" || result.rename.state === "failed",
  );
  const titleOf = (threadId: string) =>
    plan?.items.find((item) => item.threadId === threadId)?.currentTitle ??
    threadTitles.get(threadId) ??
    t.pages.untitled;

  return (
    <div className="flex flex-col gap-3" data-testid="chat-cleanup-result">
      <ul className="flex flex-col gap-1 text-sm">
        <li>{copy.resultRenamed(summary.renamed)}</li>
        <li>{copy.resultMoved(summary.moved)}</li>
        <li>{copy.resultFoldersCreated(outcome.createdFolderIds.length)}</li>
        {summary.failed > 0 && (
          <li className="text-destructive">
            {copy.resultFailed(summary.failed)}
          </li>
        )}
      </ul>
      {failed.length > 0 && (
        <>
          <p className="text-muted-foreground text-sm">
            {copy.resultFailedHint}
          </p>
          <ul
            className="flex flex-col gap-2 text-sm"
            data-testid="chat-cleanup-result-failures"
          >
            {failed.map((result) => {
              const moveReason = stepFailureReason(result.move, copy);
              const renameReason = stepFailureReason(result.rename, copy);
              return (
                <li key={result.threadId} className="min-w-0">
                  <span className="block truncate">
                    {titleOf(result.threadId)}
                  </span>
                  {moveReason && (
                    <span className="text-destructive block text-xs">
                      {copy.moveFailed(moveReason)}
                    </span>
                  )}
                  {renameReason && (
                    <span className="text-destructive block text-xs">
                      {copy.renameFailed(renameReason)}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
