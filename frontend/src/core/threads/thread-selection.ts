/**
 * Pure model for multi-selecting conversations in the sidebar.
 *
 * Nothing React and nothing DOM: the sidebar's chat lists virtualize past 60
 * rows, so most selected rows are not mounted and a range cannot be read off
 * the document. Every range is computed from the arrays the lists *render*,
 * which each list registers in display order (see `sidebar-selection.tsx`).
 *
 * Every operation answers the same reference when nothing changes, so a store
 * built on it can skip a notification and its subscribers skip a re-render.
 */

export type ThreadSelection = {
  readonly ids: ReadonlySet<string>;
  /**
   * The row a range starts from: the last row the user toggled on its own. A
   * shift-click moves it to the clicked row, so the next shift-click extends
   * from there, as in a mail client.
   */
  readonly anchorId: string | null;
};

export const EMPTY_THREAD_SELECTION: ThreadSelection = Object.freeze({
  ids: new Set<string>(),
  anchorId: null,
});

/** Flip one row and make it the anchor of the next range. */
export function toggleThread(
  selection: ThreadSelection,
  threadId: string,
): ThreadSelection {
  const ids = new Set(selection.ids);
  if (!ids.delete(threadId)) {
    ids.add(threadId);
  }
  return { ids, anchorId: threadId };
}

/**
 * Select or deselect every row from the anchor to `targetId`, inclusive, in
 * `order` (the rendered order of the whole sidebar).
 *
 * The range takes the state the clicked row is switching *to*: shift-clicking
 * an unselected row selects the run, shift-clicking a selected one clears it.
 * Without an anchor in `order` — nothing toggled yet, or the anchor sits in a
 * folder that has since collapsed — there is no range to draw, and the click
 * falls back to a plain toggle rather than doing nothing.
 */
export function selectRange(
  selection: ThreadSelection,
  order: readonly string[],
  targetId: string,
): ThreadSelection {
  const anchorIndex =
    selection.anchorId === null ? -1 : order.indexOf(selection.anchorId);
  const targetIndex = order.indexOf(targetId);
  if (anchorIndex === -1 || targetIndex === -1 || anchorIndex === targetIndex) {
    return toggleThread(selection, targetId);
  }
  const select = !selection.ids.has(targetId);
  const from = Math.min(anchorIndex, targetIndex);
  const to = Math.max(anchorIndex, targetIndex);
  const ids = new Set(selection.ids);
  for (let index = from; index <= to; index += 1) {
    const id = order[index]!;
    if (select) {
      ids.add(id);
    } else {
      ids.delete(id);
    }
  }
  return { ids, anchorId: targetId };
}

/**
 * Add every row in `order` to the selection. Rows already selected elsewhere —
 * inside a folder that has since collapsed — stay selected.
 */
export function selectAll(
  selection: ThreadSelection,
  order: readonly string[],
): ThreadSelection {
  if (order.every((id) => selection.ids.has(id))) {
    return selection;
  }
  return {
    ids: new Set([...selection.ids, ...order]),
    anchorId: selection.anchorId,
  };
}

/** Replace the selection outright (a failed bulk action keeps its failures). */
export function replaceSelection(
  selection: ThreadSelection,
  threadIds: Iterable<string>,
): ThreadSelection {
  const ids = new Set(threadIds);
  if (
    ids.size === selection.ids.size &&
    [...ids].every((id) => selection.ids.has(id))
  ) {
    return selection;
  }
  return {
    ids,
    anchorId:
      selection.anchorId !== null && ids.has(selection.anchorId)
        ? selection.anchorId
        : null,
  };
}

/**
 * Drop every selected id that is no longer present — a chat deleted, archived
 * or moved out of the loaded list elsewhere must not stay in a count the user
 * is about to act on.
 */
export function pruneSelection(
  selection: ThreadSelection,
  isPresent: (threadId: string) => boolean,
): ThreadSelection {
  let changed = false;
  const ids = new Set<string>();
  for (const id of selection.ids) {
    if (isPresent(id)) {
      ids.add(id);
    } else {
      changed = true;
    }
  }
  const anchorGone =
    selection.anchorId !== null && !isPresent(selection.anchorId);
  if (!changed && !anchorGone) {
    return selection;
  }
  return { ids, anchorId: anchorGone ? null : selection.anchorId };
}

/** The slice of a folder tree that ordering needs (a `ChatFolderNode`). */
export type SelectionFolderNode = {
  folder: { id: string };
  children: readonly SelectionFolderNode[];
};

/**
 * The rows of the folder-aware chat list, top to bottom, as it renders them.
 *
 * Mirrors `RecentChatList`'s `renderFolderNode`: the folder tree first, walked
 * depth-first in registry order, where an *expanded* folder shows its child
 * folders before its own conversations and a collapsed one shows nothing; then
 * the root list. `folderThreadIds` holds each folder's rows after branch
 * flattening — the exact arrays handed to the virtualizer.
 */
export function recentListSelectionOrder({
  tree,
  expandedFolderIds,
  folderThreadIds,
  rootThreadIds,
}: {
  tree: readonly SelectionFolderNode[];
  expandedFolderIds: ReadonlySet<string>;
  folderThreadIds: ReadonlyMap<string, readonly string[]>;
  rootThreadIds: readonly string[];
}): string[] {
  const order: string[] = [];
  const walk = (nodes: readonly SelectionFolderNode[]) => {
    for (const node of nodes) {
      if (!expandedFolderIds.has(node.folder.id)) {
        continue;
      }
      walk(node.children);
      order.push(...(folderThreadIds.get(node.folder.id) ?? []));
    }
  };
  walk(tree);
  order.push(...rootThreadIds);
  return order;
}

/** One list's rows, with where that list sits among the sidebar's sections. */
export type SelectionOrderSection = {
  /** Compared element by element: `[0, i]` (project group i) before `[1]`. */
  rank: readonly number[];
  ids: readonly string[];
};

function compareRanks(a: readonly number[], b: readonly number[]): number {
  const length = Math.min(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    const difference = a[index]! - b[index]!;
    if (difference !== 0) {
      return difference;
    }
  }
  return a.length - b.length;
}

/**
 * Concatenate the registered lists in the order the sidebar stacks them —
 * project groups above the folder tree and the root list — keeping the first
 * occurrence of an id, so a row two lists both show while project discovery
 * settles still counts once.
 */
export function combineSelectionOrder(
  sections: Iterable<SelectionOrderSection>,
): string[] {
  const sorted = [...sections].sort((a, b) => compareRanks(a.rank, b.rank));
  const seen = new Set<string>();
  const order: string[] = [];
  for (const section of sorted) {
    for (const id of section.ids) {
      if (!seen.has(id)) {
        seen.add(id);
        order.push(id);
      }
    }
  }
  return order;
}
