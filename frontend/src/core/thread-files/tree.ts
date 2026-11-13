import type { ThreadFileEntry, ThreadFileTreeState } from "./types";

function isInside(path: string, directory: string) {
  return path.startsWith(`${directory}/`);
}

/**
 * Expand or collapse a directory. Collapsing keeps the expansion of the
 * directories below it, so expanding it again restores the subtree, and
 * moves the tab stop to the collapsed directory when its row hid it.
 */
export function toggleThreadFileDirectory(
  state: ThreadFileTreeState,
  path: string,
): ThreadFileTreeState {
  if (!state.expanded.includes(path)) {
    return { ...state, expanded: [...state.expanded, path] };
  }
  const { activeKey } = state;
  return {
    ...state,
    expanded: state.expanded.filter((expanded) => expanded !== path),
    activeKey:
      activeKey !== null && isInside(activeKey, path) ? path : activeKey,
  };
}

/**
 * Keep the tab stop on a row that exists after `directory` was listed again.
 *
 * `entries` is the new listing, or null when it failed. When the active row
 * is no longer shown, the tab stop moves to its nearest listed ancestor, or
 * to `fallbackKey`: the directory's own row, or null (the first row) for the
 * root. Returns `state` itself when nothing changes, so React skips the
 * update.
 */
export function settleThreadFileActiveKey(
  state: ThreadFileTreeState,
  directory: string,
  entries: readonly ThreadFileEntry[] | null,
  fallbackKey: string | null,
): ThreadFileTreeState {
  const { activeKey } = state;
  if (activeKey === null || !isInside(activeKey, directory)) {
    return state;
  }
  const childName = activeKey.slice(directory.length + 1).split("/")[0];
  const childPath = `${directory}/${childName}`;
  const child = entries?.find((entry) => entry.path === childPath);
  if (!child) {
    return { ...state, activeKey: fallbackKey };
  }
  if (
    childPath === activeKey ||
    // The listing of the expanded child settles the rows below it.
    (child.kind === "directory" && state.expanded.includes(childPath))
  ) {
    return state;
  }
  return { ...state, activeKey: childPath };
}
