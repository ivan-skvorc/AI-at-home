"use client";

/**
 * Multi-select for the sidebar's chat rows: the state, and the dialogs the
 * bulk actions open.
 *
 * The state lives in a store **per provider**, read with
 * `useSyncExternalStore`, rather than in a context value: a context change
 * re-renders every consumer, which is all 200+ rows on each toggle, and the
 * sidebar already re-renders while a chat streams. Each row subscribes to its
 * own status instead and re-renders only when that flips. Per provider rather
 * than module-global (cf. `settings-dialog-store.ts`) so tests stay isolated.
 *
 * The provider sits next to `ThreadDeleteDialogProvider` in
 * `workspace-sidebar.tsx`, above the lists, because the lists unmount when the
 * sidebar collapses and virtualize past 60 rows: a selection kept in a row, or
 * in the list, would vanish with it. For the same reason the bulk delete and
 * clean-up dialogs are hosted here, outside the virtual lists.
 *
 * Without a provider every hook answers "not selecting", so a row rendered on
 * its own (tests, any future list) behaves exactly as before.
 */

import dynamic from "next/dynamic";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import {
  combineSelectionOrder,
  EMPTY_THREAD_SELECTION,
  pruneSelection,
  replaceSelection,
  selectAll,
  selectRange,
  toggleThread,
  type SelectionOrderSection,
  type ThreadSelection,
} from "@/core/threads/thread-selection";
import type { AgentThread } from "@/core/threads/types";

import { ThreadBulkDeleteDialog } from "./thread-bulk-delete-dialog";

// The clean-up dialog carries a model picker and a whole review flow, and most
// sessions never open it: keep it out of the sidebar's bundle until asked for.
const ChatCleanupDialog = dynamic(
  () =>
    import("@/components/workspace/chat-cleanup/chat-cleanup-dialog").then(
      (module) => module.ChatCleanupDialog,
    ),
  { ssr: false },
);

type Listener = () => void;

export type SidebarSelectionState = {
  /** Selection mode is on: rows show checkboxes and the toolbar is up. */
  readonly active: boolean;
  readonly selection: ThreadSelection;
};

const INACTIVE_STATE: SidebarSelectionState = Object.freeze({
  active: false,
  selection: EMPTY_THREAD_SELECTION,
});

/** What a row renders: no checkbox, an empty one, or a ticked one. */
export type ThreadSelectionStatus = "off" | "unselected" | "selected";

export class SidebarSelectionStore {
  private state: SidebarSelectionState = INACTIVE_STATE;
  private readonly listeners = new Set<Listener>();
  private readonly sections = new Map<string, SelectionOrderSection>();

  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  readonly getSnapshot = (): SidebarSelectionState => this.state;

  private set(active: boolean, selection: ThreadSelection) {
    if (active === this.state.active && selection === this.state.selection) {
      return;
    }
    this.state = { active, selection };
    for (const listener of this.listeners) {
      listener();
    }
  }

  /** Every selectable row, top to bottom, as the sidebar renders it now. */
  order(): string[] {
    return combineSelectionOrder(this.sections.values());
  }

  /**
   * The ticked ids in sidebar order — what a bulk action and its dialogs
   * should list — followed by any ticked row that is out of sight (inside a
   * collapsed folder), in the order it was ticked.
   */
  selectedIdsInOrder(): string[] {
    const { ids } = this.state.selection;
    const visible = this.order().filter((id) => ids.has(id));
    const seen = new Set(visible);
    return [...visible, ...[...ids].filter((id) => !seen.has(id))];
  }

  /** Start selecting, optionally with one row already ticked. */
  enter(threadId?: string) {
    const { selection } = this.state;
    this.set(
      true,
      threadId === undefined || selection.ids.has(threadId)
        ? selection
        : toggleThread(selection, threadId),
    );
  }

  /** Leave selection mode and forget the selection. */
  exit() {
    this.set(false, EMPTY_THREAD_SELECTION);
  }

  /**
   * Flip one row, or — with `range` — every row from the anchor to it in the
   * rendered order. Toggling a row also starts selection mode.
   */
  toggle(threadId: string, { range = false }: { range?: boolean } = {}) {
    const { selection } = this.state;
    this.set(
      true,
      range
        ? selectRange(selection, this.order(), threadId)
        : toggleThread(selection, threadId),
    );
  }

  /** Tick every row the sidebar shows (loaded and in an open section). */
  selectAll() {
    this.set(true, selectAll(this.state.selection, this.order()));
  }

  /** Untick everything but stay in selection mode. */
  clear() {
    this.set(this.state.active, replaceSelection(this.state.selection, []));
  }

  /** Keep exactly these rows ticked — what a partly failed action leaves. */
  replace(threadIds: Iterable<string>) {
    this.set(
      this.state.active,
      replaceSelection(this.state.selection, threadIds),
    );
  }

  /** Drop ticked rows that are no longer loaded (deleted, archived elsewhere). */
  prune(isPresent: (threadId: string) => boolean) {
    this.set(
      this.state.active,
      pruneSelection(this.state.selection, isPresent),
    );
  }

  /**
   * Publish one list's rows for ranges and **Select all**. Not part of the
   * snapshot: a list re-rendering its order must not re-render every row.
   */
  registerOrder(key: string, section: SelectionOrderSection): () => void {
    this.sections.set(key, section);
    return () => {
      if (this.sections.get(key) === section) {
        this.sections.delete(key);
      }
    };
  }
}

export type BulkDeleteRequest = {
  threads: readonly AgentThread[];
  /** The global most-recent thread, as a single delete gets it. */
  recentThreadId?: string | undefined;
};

export type SidebarSelectionApi = {
  store: SidebarSelectionStore;
  /** Open the bulk delete confirmation for these chats. */
  requestDelete: (request: BulkDeleteRequest) => void;
  /** Open clean-up mode for these chats, or for every chat (`null`). */
  openCleanup: (threadIds: readonly string[] | null) => void;
};

const SidebarSelectionContext = createContext<SidebarSelectionApi | null>(null);

/** The selection controls, or `null` outside a {@link SidebarSelectionProvider}. */
export function useSidebarSelection(): SidebarSelectionApi | null {
  return useContext(SidebarSelectionContext);
}

const noopSubscribe = () => () => undefined;
const inactiveSnapshot = () => INACTIVE_STATE;

/** The whole selection state; re-renders on every change. For the toolbar. */
export function useSidebarSelectionState(): SidebarSelectionState {
  const api = useSidebarSelection();
  return useSyncExternalStore(
    api?.store.subscribe ?? noopSubscribe,
    api?.store.getSnapshot ?? inactiveSnapshot,
    inactiveSnapshot,
  );
}

/**
 * Whether selection mode is on, and nothing else: a list that only needs to
 * know whether to show the toolbar must not re-render — and re-render every
 * row it renders — on each tick.
 */
export function useSidebarSelectionActive(): boolean {
  const api = useSidebarSelection();
  const store = api?.store;
  const getActive = useCallback(
    () => store?.getSnapshot().active ?? false,
    [store],
  );
  return useSyncExternalStore(
    store?.subscribe ?? noopSubscribe,
    getActive,
    () => false,
  );
}

/**
 * One row's status. The snapshot is a string, so a toggle elsewhere in the
 * list leaves this row's value — and the row — untouched.
 */
export function useThreadSelectionStatus(
  threadId: string,
): ThreadSelectionStatus {
  const api = useSidebarSelection();
  const store = api?.store;
  const getStatus = useCallback((): ThreadSelectionStatus => {
    const state = store?.getSnapshot() ?? INACTIVE_STATE;
    if (!state.active) {
      return "off";
    }
    return state.selection.ids.has(threadId) ? "selected" : "unselected";
  }, [store, threadId]);
  return useSyncExternalStore(
    store?.subscribe ?? noopSubscribe,
    getStatus,
    () => "off",
  );
}

const EMPTY_IDS: readonly string[] = [];

/**
 * Register a list's rendered rows under `key`. `rank` places the list among
 * the sidebar's sections (`[0, i]` for project group i, `[1]` for the folder
 * tree and root list) so a shift-click range can cross from one into the
 * next. Pass the memoized array the list renders: the registration follows it.
 */
export function useRegisterSelectionOrder(
  key: string,
  rank: readonly number[],
  ids: readonly string[] | null,
) {
  const api = useSidebarSelection();
  const store = api?.store;
  const rankKey = rank.join(",");
  useEffect(() => {
    if (!store) {
      return;
    }
    return store.registerOrder(key, {
      rank: rankKey.split(",").map(Number),
      ids: ids ?? EMPTY_IDS,
    });
  }, [store, key, rankKey, ids]);
}

/** An Escape typed into a field belongs to the field, not to the sidebar. */
function isTextEntryTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  if (target.isContentEditable) {
    return true;
  }
  if (target instanceof HTMLTextAreaElement) {
    return true;
  }
  if (target instanceof HTMLSelectElement) {
    return true;
  }
  return (
    target instanceof HTMLInputElement &&
    target.type !== "checkbox" &&
    target.type !== "radio" &&
    target.type !== "button"
  );
}

/**
 * Escape exits selection only from the sidebar itself (or with nothing
 * focused): an Escape meant for the chat page — closing a preview, leaving a
 * panel — must not throw away a selection the user built up.
 */
function isSidebarOrPageTarget(target: EventTarget | null): boolean {
  if (
    target === null ||
    target === document.body ||
    target === document.documentElement
  ) {
    return true;
  }
  return (
    target instanceof Element &&
    target.closest('[data-sidebar="sidebar"]') !== null
  );
}

export function SidebarSelectionProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [store] = useState(() => new SidebarSelectionStore());
  const [deleteRequest, setDeleteRequest] = useState<BulkDeleteRequest | null>(
    null,
  );
  // Mounted on first use and kept, so closing it plays its exit animation and
  // the dialog itself decides what closing means for work it has in flight.
  const [cleanup, setCleanup] = useState<{
    open: boolean;
    threadIds: string[] | null;
  } | null>(null);

  const requestDelete = useCallback((request: BulkDeleteRequest) => {
    if (request.threads.length > 0) {
      setDeleteRequest(request);
    }
  }, []);
  const openCleanup = useCallback((threadIds: readonly string[] | null) => {
    setCleanup({ open: true, threadIds: threadIds ? [...threadIds] : null });
  }, []);
  const handleCleanupOpenChange = useCallback((open: boolean) => {
    setCleanup((current) => (current ? { ...current, open } : current));
  }, []);

  const api = useMemo<SidebarSelectionApi>(
    () => ({ store, requestDelete, openCleanup }),
    [store, requestDelete, openCleanup],
  );

  const active = useSyncExternalStore(
    store.subscribe,
    () => store.getSnapshot().active,
    () => false,
  );
  useEffect(() => {
    if (!active) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        event.key !== "Escape" ||
        event.defaultPrevented ||
        isTextEntryTarget(event.target) ||
        !isSidebarOrPageTarget(event.target)
      ) {
        return;
      }
      // A menu, dialog or the mobile drawer closes on this same Escape (Radix
      // listens on the document too, and its layer is still in the DOM while
      // it closes): that keypress is theirs, so selection stays.
      if (
        document.querySelector(
          '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"], [role="menu"][data-state="open"]',
        )
      ) {
        return;
      }
      store.exit();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [active, store]);

  return (
    <SidebarSelectionContext.Provider value={api}>
      {children}
      <ThreadBulkDeleteDialog
        request={deleteRequest}
        store={store}
        onClose={() => setDeleteRequest(null)}
      />
      {cleanup && (
        <ChatCleanupDialog
          open={cleanup.open}
          onOpenChange={handleCleanupOpenChange}
          threadIds={cleanup.threadIds}
        />
      )}
    </SidebarSelectionContext.Provider>
  );
}
