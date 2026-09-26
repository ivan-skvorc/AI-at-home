import type { Key } from "react";

/** Fallback row height before this thread has measured enough of its own. */
export const ESTIMATED_ROW_HEIGHT = 176;
/**
 * Rows a thread must have measured before its own average replaces the static
 * estimate, and the window that average is taken over. A handful of rows is a
 * worse predictor than the constant; a long window stops one outlier row from
 * moving the estimate for every not-yet-seen row above the viewport.
 */
export const MIN_MEASURED_ROWS_FOR_ESTIMATE = 8;
export const MEASURED_ROW_HEIGHT_WINDOW = 32;
/** Clamp the learned estimate so a pathological row cannot poison it. */
export const MIN_ESTIMATED_ROW_HEIGHT = 48;
export const MAX_ESTIMATED_ROW_HEIGHT = 1_200;

/**
 * How the group list changed since the previous render.
 *
 * `prepend` is the case this distinction exists for: a loaded history page
 * grows the list from the front, which is not new content arriving and must
 * never pull the viewport to the newest message.
 */
export type ListGrowth = "none" | "append" | "prepend";

export function resolveListGrowth({
  previousCount,
  previousFirstKey,
  count,
  firstKey,
}: {
  previousCount: number;
  previousFirstKey: Key | undefined;
  count: number;
  firstKey: Key | undefined;
}): ListGrowth {
  if (count <= previousCount) {
    return "none";
  }
  // The first content to arrive has no earlier first row to compare against,
  // and cannot be a history page landing above something — a thread's opening
  // load is an append, and must still settle at the newest turn.
  return previousFirstKey === undefined || firstKey === previousFirstKey
    ? "append"
    : "prepend";
}

/**
 * The row to hold still when older history lands above it.
 *
 * `rows` are the rendered rows that reach the viewport or sit below it, in list
 * order. The list's first row is passed over whenever a later one is on offer:
 * a history page is cut by row count, not at turn boundaries, and one agent
 * turn is many rows (every tool call and result), so the older page usually
 * carries the front of the turn the list starts with. Those messages merge into
 * the first group and change its key, so an anchor on it is never found again —
 * nothing is restored and the reader lands at the top of the page that just
 * loaded. Every later group keeps its key across a prepend.
 */
export function pickPrependAnchor<Row extends { index: number }>(
  rows: readonly Row[],
): Row | undefined {
  return rows.find((row) => row.index > 0) ?? rows[0];
}

export type RowHeightEstimator = {
  /** Feed a measured row height. Non-positive sizes are ignored. */
  record: (size: number) => void;
  /** The height to assume for a row the virtualizer has never rendered. */
  estimate: () => number;
};

/**
 * Learns a thread's typical row height from the rows it has measured.
 *
 * Rows the virtualizer has never rendered have no measurement, so a page of
 * older turns is prepended at `estimate()` each. Whatever that estimate gets
 * wrong lands above the viewport, where correcting it later moves the reader —
 * so a constant that matches no real thread is worse than this thread's own
 * average.
 */
export function createRowHeightEstimator(): RowHeightEstimator {
  let average = 0;
  let samples = 0;

  return {
    record(size) {
      // A zero here is an unlaid-out row, not a real height — averaging it in
      // would drag the estimate toward the clamp floor.
      if (!(size > 0)) {
        return;
      }
      samples += 1;
      // Exponential moving average: no per-row bookkeeping to keep in sync
      // with prepends, and it re-converges when turn shapes change.
      average +=
        (size - average) / Math.min(samples, MEASURED_ROW_HEIGHT_WINDOW);
    },
    estimate() {
      if (samples < MIN_MEASURED_ROWS_FOR_ESTIMATE) {
        return ESTIMATED_ROW_HEIGHT;
      }
      return Math.min(
        MAX_ESTIMATED_ROW_HEIGHT,
        Math.max(MIN_ESTIMATED_ROW_HEIGHT, Math.round(average)),
      );
    },
  };
}
