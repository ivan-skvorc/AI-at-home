"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronRightIcon,
  FileIcon,
  FolderIcon,
  FolderOpenIcon,
  FolderTreeIcon,
  LinkIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
} from "lucide-react";
import {
  createContext,
  type Dispatch,
  type KeyboardEvent,
  type ReactNode,
  type SetStateAction,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { ArtifactDownloadButton } from "@/components/workspace/artifacts/artifact-download-button";
import { FileTypeIcon } from "@/components/workspace/file-type-icon";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import {
  formatFileSize,
  settleThreadFileActiveKey,
  THREAD_FILES_ROOT,
  threadFilesQueryPrefix,
  ThreadFilesRequestError,
  toggleThreadFileDirectory,
  useThreadFiles,
  type ThreadFileEntry,
  type ThreadFileListing,
  type ThreadFileTreeState,
} from "@/core/thread-files";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

/** Poll interval for the expanded directories while the thread runs. */
export const THREAD_FILES_RUNNING_REFETCH_MS = 5_000;

const ROW_START_PX = 4;
const INDENT_STEP_PX = 16;
/** Chevron plus gap, so status rows line up with the names above them. */
const STATUS_OFFSET_PX = 22;

function rowIndent(level: number) {
  return ROW_START_PX + (level - 1) * INDENT_STEP_PX;
}

interface TreeContextValue {
  threadId: string;
  refetchInterval: number | false;
  expanded: ReadonlySet<string>;
  /** The row holding the tab stop, already resolved to the first row. */
  activeKey: string | null;
  restoreFocus: boolean;
  setActive: (path: string) => void;
  activate: (path: string, kind: string | undefined) => void;
  settle: (
    directory: string,
    entries: readonly ThreadFileEntry[] | null,
    fallbackKey: string | null,
  ) => void;
  focusRestored: () => void;
}

const TreeContext = createContext<TreeContextValue | null>(null);

function useTreeContext() {
  const context = useContext(TreeContext);
  if (!context) {
    throw new Error("Thread file rows must be inside ThreadFileExplorer");
  }
  return context;
}

function describeFolderError(error: unknown, t: Translations) {
  if (error instanceof ThreadFilesRequestError) {
    if (error.status === 404) {
      return t.threadFiles.folderMissing;
    }
    if (error.status === 403) {
      return t.threadFiles.accessDenied;
    }
  }
  return t.threadFiles.folderLoadFailed;
}

/**
 * A lazy tree of the thread's `/mnt/user-data`: each expanded directory is
 * one listing request. Keyboard use follows the WAI-ARIA tree pattern, with
 * one tab stop that moves with the arrow keys.
 */
export function ThreadFileExplorer({
  threadId,
  isRunning,
  tree,
  onTreeChange,
  onOpenFile,
  className,
}: {
  threadId: string;
  /** While the thread runs, expanded directories poll for new files. */
  isRunning: boolean;
  tree: ThreadFileTreeState;
  onTreeChange: Dispatch<SetStateAction<ThreadFileTreeState>>;
  onOpenFile: (path: string) => void;
  className?: string;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const refetchInterval = isRunning ? THREAD_FILES_RUNNING_REFETCH_MS : false;
  const root = useThreadFiles(threadId, THREAD_FILES_ROOT, {
    refetchInterval,
  });
  const [refreshing, setRefreshing] = useState(false);

  const wasRunningRef = useRef(isRunning);
  useEffect(() => {
    // The last poll can predate the run's final writes.
    if (wasRunningRef.current && !isRunning) {
      void queryClient.invalidateQueries({
        queryKey: threadFilesQueryPrefix(threadId),
      });
    }
    wasRunningRef.current = isRunning;
  }, [isRunning, queryClient, threadId]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      // Refetches every mounted listing: the root and the open directories.
      await queryClient.invalidateQueries({
        queryKey: threadFilesQueryPrefix(threadId),
      });
    } finally {
      setRefreshing(false);
    }
  }, [queryClient, threadId]);

  const setActive = useCallback(
    (path: string) => {
      onTreeChange((state) =>
        state.activeKey === path ? state : { ...state, activeKey: path },
      );
    },
    [onTreeChange],
  );

  const activate = useCallback(
    (path: string, kind: string | undefined) => {
      if (kind === "directory") {
        onTreeChange((state) => toggleThreadFileDirectory(state, path));
      } else if (kind === "file") {
        onTreeChange((state) => ({
          ...state,
          activeKey: path,
          restoreFocus: true,
        }));
        onOpenFile(path);
      }
    },
    [onOpenFile, onTreeChange],
  );

  const settle = useCallback(
    (
      directory: string,
      entries: readonly ThreadFileEntry[] | null,
      fallbackKey: string | null,
    ) => {
      onTreeChange((state) =>
        settleThreadFileActiveKey(state, directory, entries, fallbackKey),
      );
    },
    [onTreeChange],
  );

  const focusRestored = useCallback(() => {
    onTreeChange((state) =>
      state.restoreFocus ? { ...state, restoreFocus: false } : state,
    );
  }, [onTreeChange]);

  const firstRootPath = root.data?.entries[0]?.path ?? null;
  const expanded = useMemo(() => new Set(tree.expanded), [tree.expanded]);
  const contextValue = useMemo<TreeContextValue>(
    () => ({
      threadId,
      refetchInterval,
      expanded,
      activeKey: tree.activeKey ?? firstRootPath,
      restoreFocus: tree.restoreFocus,
      setActive,
      activate,
      settle,
      focusRestored,
    }),
    [
      activate,
      expanded,
      firstRootPath,
      focusRestored,
      refetchInterval,
      setActive,
      settle,
      threadId,
      tree.activeKey,
      tree.restoreFocus,
    ],
  );

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLUListElement>) => {
      const item = event.target;
      if (
        !(item instanceof HTMLElement) ||
        item.getAttribute("role") !== "treeitem" ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey
      ) {
        return;
      }
      const path = item.dataset.path;
      const kind = item.dataset.kind;
      if (!path) {
        return;
      }
      // Collapsed directories render no children, so document order is the
      // visible order.
      const items = Array.from(
        event.currentTarget.querySelectorAll<HTMLElement>('[role="treeitem"]'),
      );
      const index = items.indexOf(item);
      const isExpanded = item.getAttribute("aria-expanded") === "true";
      let target: Element | null | undefined = null;
      switch (event.key) {
        case "ArrowDown":
          target = items[index + 1];
          break;
        case "ArrowUp":
          target = items[index - 1];
          break;
        case "Home":
          target = items[0];
          break;
        case "End":
          target = items[items.length - 1];
          break;
        case "ArrowRight":
          if (kind === "directory") {
            if (isExpanded) {
              target = item.querySelector('[role="treeitem"]');
            } else {
              activate(path, kind);
            }
          }
          break;
        case "ArrowLeft":
          if (kind === "directory" && isExpanded) {
            activate(path, kind);
          } else {
            target = item.parentElement?.closest('[role="treeitem"]');
          }
          break;
        case "Enter":
          activate(path, kind);
          break;
        default:
          return;
      }
      event.preventDefault();
      if (target instanceof HTMLElement) {
        target.focus();
      }
    },
    [activate],
  );

  let body: ReactNode;
  if (root.data && root.data.exists && root.data.entries.length > 0) {
    body = (
      <TreeContext.Provider value={contextValue}>
        <ul
          role="tree"
          aria-label={t.threadFiles.treeLabel}
          className="flex flex-col gap-px py-1"
          onKeyDown={handleKeyDown}
        >
          <ThreadFileRows listing={root.data} level={1} fallbackKey={null} />
        </ul>
      </TreeContext.Provider>
    );
  } else if (root.data) {
    body = (
      <Empty className="border-none">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FolderTreeIcon />
          </EmptyMedia>
          <EmptyTitle>{t.threadFiles.emptyTitle}</EmptyTitle>
          <EmptyDescription>{t.threadFiles.emptyDescription}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  } else if (root.isError) {
    body = (
      <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
        <p role="alert" className="text-destructive text-sm">
          {t.threadFiles.loadFailed}
        </p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void root.refetch();
          }}
        >
          <RefreshCwIcon />
          {t.threadFiles.retry}
        </Button>
      </div>
    );
  } else {
    body = (
      <div aria-busy="true" className="flex flex-col gap-2 p-2">
        <span className="sr-only">{t.threadFiles.loading}</span>
        {[72, 56, 64].map((width) => (
          <Skeleton
            key={width}
            className="h-6"
            style={{ width: `${width}%` }}
          />
        ))}
      </div>
    );
  }

  // The panel's Files tab names this region, so it carries no label itself.
  return (
    <div
      className={cn("@container flex size-full min-h-0 flex-col", className)}
    >
      <div className="flex shrink-0 items-center justify-between gap-2 border-b pb-1">
        <span
          className="text-muted-foreground min-w-0 truncate px-1 font-mono text-xs"
          title={THREAD_FILES_ROOT}
        >
          {THREAD_FILES_ROOT}
        </span>
        <Tooltip content={t.threadFiles.refresh}>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={t.threadFiles.refresh}
            className="text-muted-foreground hover:text-foreground"
            onClick={() => {
              void refresh();
            }}
          >
            <RefreshCwIcon
              className={cn(refreshing && "motion-safe:animate-spin")}
            />
          </Button>
        </Tooltip>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">{body}</div>
    </div>
  );
}

function ThreadFileRows({
  listing,
  level,
  fallbackKey,
}: {
  listing: ThreadFileListing;
  level: number;
  /** Takes the tab stop when the active row leaves this listing. */
  fallbackKey: string | null;
}) {
  const { t } = useI18n();
  const { settle } = useTreeContext();
  useEffect(() => {
    settle(listing.path, listing.entries, fallbackKey);
  }, [fallbackKey, listing, settle]);
  const hidden = listing.total - listing.entries.length;
  return (
    <>
      {listing.entries.length === 0 ? (
        <StatusRow level={level} announce>
          {t.threadFiles.emptyFolder}
        </StatusRow>
      ) : (
        listing.entries.map((entry) => (
          <ThreadFileItem key={entry.path} entry={entry} level={level} />
        ))
      )}
      {hidden > 0 && (
        <StatusRow level={level} announce>
          {t.threadFiles.moreNotShown(hidden)}
        </StatusRow>
      )}
    </>
  );
}

function ThreadFileGroup({ path, level }: { path: string; level: number }) {
  const { t } = useI18n();
  const { threadId, refetchInterval, settle } = useTreeContext();
  const query = useThreadFiles(threadId, path, { refetchInterval });
  // A failed refetch keeps the last listing; only a first failure replaces it.
  const failed = query.isError && !query.data;
  useEffect(() => {
    if (failed) {
      settle(path, null, path);
    }
  }, [failed, path, settle]);
  return (
    <ul
      role="group"
      aria-busy={query.isPending ? true : undefined}
      className="flex flex-col gap-px"
    >
      {query.data ? (
        <ThreadFileRows listing={query.data} level={level} fallbackKey={path} />
      ) : failed ? (
        <StatusRow level={level} tone="error">
          <span role="alert">{describeFolderError(query.error, t)}</span>
          <Button
            variant="ghost"
            size="sm"
            className="h-7"
            onClick={() => {
              void query.refetch();
            }}
          >
            {t.threadFiles.retry}
          </Button>
        </StatusRow>
      ) : (
        <StatusRow level={level}>
          <LoaderCircleIcon
            aria-hidden="true"
            className="size-3.5 motion-safe:animate-spin"
          />
          {t.threadFiles.loadingFolder}
        </StatusRow>
      )}
    </ul>
  );
}

function StatusRow({
  level,
  tone,
  announce = false,
  children,
}: {
  level: number;
  tone?: "error";
  /**
   * Arrow keys move between treeitems only, so a screen reader never lands on
   * this row: announce it politely when it appears instead, or an empty or cut
   * listing would sound like a complete one.
   */
  announce?: boolean;
  children: ReactNode;
}) {
  return (
    <li
      role="none"
      className={cn(
        "flex min-h-8 items-center gap-2",
        tone === "error"
          ? "text-destructive text-sm"
          : "text-muted-foreground text-xs",
      )}
      style={{ paddingInlineStart: rowIndent(level) + STATUS_OFFSET_PX }}
    >
      {announce ? <span role="status">{children}</span> : children}
    </li>
  );
}

function EntryIcon({
  entry,
  expanded,
}: {
  entry: ThreadFileEntry;
  expanded: boolean;
}) {
  if (entry.kind === "file") {
    return <FileTypeIcon filename={entry.name} compact />;
  }
  const Icon =
    entry.kind === "directory"
      ? expanded
        ? FolderOpenIcon
        : FolderIcon
      : entry.kind === "symlink"
        ? LinkIcon
        : FileIcon;
  return (
    <span
      aria-hidden="true"
      className="file-type-icon inline-flex size-6 shrink-0 items-center justify-center rounded-md"
    >
      <Icon className="size-4" />
    </span>
  );
}

function ThreadFileItem({
  entry,
  level,
}: {
  entry: ThreadFileEntry;
  level: number;
}) {
  const { t, locale } = useI18n();
  const {
    threadId,
    expanded: expandedPaths,
    activeKey,
    restoreFocus,
    setActive,
    activate,
    focusRestored,
  } = useTreeContext();
  const ref = useRef<HTMLLIElement>(null);
  const nameId = useId();
  const detailsId = useId();
  const isDirectory = entry.kind === "directory";
  const expanded = isDirectory && expandedPaths.has(entry.path);
  const isActive = activeKey === entry.path;
  // Links are never followed and other kinds cannot be previewed.
  const actionable = isDirectory || entry.kind === "file";

  useEffect(() => {
    if (isActive && restoreFocus) {
      ref.current?.focus();
      focusRestored();
    }
  }, [focusRestored, isActive, restoreFocus]);

  const kindLabel =
    entry.kind === "symlink"
      ? t.threadFiles.symlink
      : entry.kind === "other"
        ? t.threadFiles.specialFile
        : null;
  const size =
    entry.kind === "file" && entry.size !== null
      ? formatFileSize(entry.size)
      : null;
  const modifiedAt = entry.modified_at;
  const hasDetails = Boolean(kindLabel ?? size ?? modifiedAt);

  return (
    <li
      ref={ref}
      role="treeitem"
      aria-level={level}
      aria-expanded={isDirectory ? expanded : undefined}
      // Single selection that follows the tab stop.
      aria-selected={isActive ? true : undefined}
      aria-labelledby={nameId}
      aria-describedby={hasDetails ? detailsId : undefined}
      tabIndex={isActive ? 0 : -1}
      data-path={entry.path}
      data-kind={entry.kind}
      onFocus={(event) => {
        if (event.target === event.currentTarget) {
          setActive(entry.path);
        }
      }}
      className="[&:focus-visible>div]:ring-ring/50 outline-none [&:focus-visible>div]:ring-2 [&:focus-visible>div]:ring-inset"
    >
      <div
        className={cn(
          "hover:bg-accent flex min-h-8 items-center gap-1.5 rounded-md pr-1 transition-colors",
          actionable ? "cursor-pointer" : "cursor-default",
        )}
        style={{ paddingInlineStart: rowIndent(level) }}
        onClick={() => activate(entry.path, entry.kind)}
      >
        <ChevronRightIcon
          aria-hidden="true"
          className={cn(
            "text-muted-foreground size-4 shrink-0 transition-transform motion-reduce:transition-none",
            !isDirectory && "invisible",
            expanded && "rotate-90",
          )}
        />
        <EntryIcon entry={entry} expanded={expanded} />
        <span
          id={nameId}
          className={cn(
            "min-w-0 flex-1 truncate text-sm",
            !actionable && "text-muted-foreground",
          )}
          title={entry.name}
        >
          {entry.name}
        </span>
        {hasDetails && (
          <span
            id={detailsId}
            className="text-muted-foreground flex shrink-0 items-center gap-2 text-xs tabular-nums"
          >
            {kindLabel && <span>{kindLabel}</span>}
            {size && <span>{size}</span>}
            {modifiedAt && (
              <time
                dateTime={modifiedAt}
                title={new Date(modifiedAt).toLocaleString(locale)}
                className="hidden @xs:inline"
              >
                {formatTimeAgo(modifiedAt, locale)}
              </time>
            )}
          </span>
        )}
        {entry.kind === "file" && (
          <ArtifactDownloadButton
            filepath={entry.path}
            threadId={threadId}
            compact
            size="icon-sm"
            // The tree is one tab stop; the preview offers the same download.
            tabIndex={-1}
          />
        )}
      </div>
      {expanded && <ThreadFileGroup path={entry.path} level={level + 1} />}
    </li>
  );
}
