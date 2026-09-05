"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { AgentThread } from "@/core/threads/types";

const VIRTUALIZATION_THRESHOLD = 60;

/**
 * Offset of a virtual list's root from the top of its scroll container's
 * *content* — what `@tanstack/react-virtual` calls the scroll margin.
 *
 * It is deliberately scroll-position independent: `rootTop` and
 * `scrollParentTop` are viewport coordinates that both move with the scroll,
 * and adding `scrollTop` back cancels that out. Measuring while the container
 * is scrolled therefore yields the same number as measuring at rest, which is
 * what lets the observers below re-measure at any moment.
 */
export function calculateScrollMargin(
  rootTop: number,
  scrollParentTop: number,
  scrollTop: number,
) {
  return Math.max(0, rootTop - scrollParentTop + scrollTop);
}

/**
 * Call `onLayoutChange` whenever the list's offset inside a scroll container it
 * does not own could have moved.
 *
 * The virtualizer picks which rows to render by comparing the container's
 * `scrollTop` against row offsets that start at the scroll margin, so a margin
 * measured once and left alone silently shifts the rendered window by the drift
 * — rows the reader has scrolled to are simply never mounted. Nothing in React
 * tells this component that a *sibling* above it grew, so the DOM is asked
 * instead:
 *
 * - `MutationObserver` on the container subtree: another sidebar group finishing
 *   its fetch, or a folder above the list opening.
 * - `ResizeObserver` on the container and on the list root: the sidebar being
 *   resized, or the list's own height changing.
 * - `scroll`: the cheap self-heal. The margin is scroll-invariant (see above),
 *   so re-measuring during a scroll costs two rects and repairs any drift the
 *   two observers could not see — a web font swapping in above the list, say —
 *   during the very interaction that would expose it.
 *
 * Callbacks are coalesced into one animation frame, so a burst of mutations
 * measures once. Returns the teardown.
 */
export function watchListLayoutChanges(
  root: HTMLElement,
  scrollParent: HTMLElement,
  onLayoutChange: () => void,
): () => void {
  let frame: number | null = null;
  const schedule = () => {
    if (frame !== null) {
      return;
    }
    frame = requestAnimationFrame(() => {
      frame = null;
      onLayoutChange();
    });
  };

  const mutationObserver = new MutationObserver(schedule);
  mutationObserver.observe(scrollParent, { childList: true, subtree: true });

  // ResizeObserver is not implemented by every test DOM; a missing one costs
  // the resize trigger, not the whole watcher.
  const resizeObserver =
    typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
  resizeObserver?.observe(scrollParent);
  resizeObserver?.observe(root);

  scrollParent.addEventListener("scroll", schedule, { passive: true });

  return () => {
    if (frame !== null) {
      cancelAnimationFrame(frame);
      frame = null;
    }
    mutationObserver.disconnect();
    resizeObserver?.disconnect();
    scrollParent.removeEventListener("scroll", schedule);
  };
}

export function VirtualThreadList({
  estimateSize,
  gap = 0,
  items,
  renderItem,
  scrollParentSelector,
}: {
  estimateSize: number;
  gap?: number;
  items: readonly AgentThread[];
  renderItem: (thread: AgentThread, index: number) => ReactNode;
  scrollParentSelector: string;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const getScrollElement = useCallback(
    () => rootRef.current?.closest<HTMLElement>(scrollParentSelector) ?? null,
    [scrollParentSelector],
  );
  const [scrollMargin, setScrollMargin] = useState(0);
  const scrollMarginRef = useRef(0);
  const measureScrollMargin = useCallback(() => {
    const root = rootRef.current;
    const scrollParent = getScrollElement();
    if (!root || !scrollParent) return;
    const next = calculateScrollMargin(
      root.getBoundingClientRect().top,
      scrollParent.getBoundingClientRect().top,
      scrollParent.scrollTop,
    );
    if (next === scrollMarginRef.current) return;
    scrollMarginRef.current = next;
    setScrollMargin(next);
  }, [getScrollElement]);

  // Deliberately no dependency array: every commit is a chance the list moved,
  // and the measurement only re-renders when the number actually changed.
  useLayoutEffect(measureScrollMargin);

  useLayoutEffect(() => {
    const root = rootRef.current;
    const scrollParent = getScrollElement();
    if (!root || !scrollParent) return;
    return watchListLayoutChanges(root, scrollParent, measureScrollMargin);
  }, [getScrollElement, measureScrollMargin]);

  const virtualizer = useVirtualizer({
    count: items.length,
    estimateSize: () => estimateSize,
    getItemKey: (index) => items[index]?.thread_id ?? index,
    getScrollElement,
    overscan: 8,
    scrollMargin,
  });

  if (items.length < VIRTUALIZATION_THRESHOLD) {
    return (
      <div
        ref={rootRef}
        className="flex w-full flex-col"
        style={{ gap: `${gap}px` }}
      >
        {items.map(renderItem)}
      </div>
    );
  }

  return (
    <div
      ref={rootRef}
      className="relative w-full"
      style={{ height: `${virtualizer.getTotalSize()}px` }}
    >
      {virtualizer.getVirtualItems().map((virtualRow) => {
        const thread = items[virtualRow.index];
        if (!thread) return null;
        return (
          <div
            key={virtualRow.key}
            ref={virtualizer.measureElement}
            data-index={virtualRow.index}
            className="absolute top-0 left-0 w-full"
            style={{
              paddingBottom: `${gap}px`,
              transform: `translateY(${virtualRow.start - scrollMargin}px)`,
            }}
          >
            {renderItem(thread, virtualRow.index)}
          </div>
        );
      })}
    </div>
  );
}
