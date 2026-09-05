"use client";

import { useVirtualizer } from "@tanstack/react-virtual";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

import type { AgentThread } from "@/core/threads/types";

const VIRTUALIZATION_THRESHOLD = 60;

export function calculateScrollMargin(
  rootTop: number,
  scrollParentTop: number,
  scrollTop: number,
) {
  return Math.max(0, rootTop - scrollParentTop + scrollTop);
}

/**
 * Keep the virtualizer's `scrollMargin` — this list's own offset inside the
 * sidebar's one shared scroll container — honest for as long as the list is
 * mounted.
 *
 * The margin is what maps a scroll position onto a row index, so a stale one
 * does not merely misplace a row: it hands the virtualizer the wrong window
 * entirely, and the tail of the list is drawn above the viewport, where no
 * amount of scrolling reaches it. Measuring once was wrong because everything
 * that moves this list sits *above* it and moves without the list's own item
 * count changing:
 *
 * - folders expand one render after mount, when the per-browser expanded set
 *   hydrates from `localStorage`;
 * - the channels list swaps skeletons for rows and the nav list grows an
 *   "Agents" row when their queries resolve;
 * - the window resizes, or a font lands and reflows a section above.
 *
 * All of them are worst on a cold load — what a user experiences as "it broke
 * after I restarted the machine" — because that is exactly when each one
 * settles *after* the single measurement.
 *
 * Exported for its own tests: what this hook gets wrong is invisible in a DOM
 * without a layout engine when observed through the virtualizer, and a
 * six-minute e2e should not be the only thing that notices.
 */
export function useThreadListScrollMargin(
  rootRef: RefObject<HTMLElement | null>,
  getScrollElement: () => HTMLElement | null,
): number {
  const [scrollMargin, setScrollMargin] = useState(0);

  const measure = useCallback(() => {
    const root = rootRef.current;
    const scrollParent = getScrollElement();
    if (!root || !scrollParent) {
      return;
    }
    const next = calculateScrollMargin(
      root.getBoundingClientRect().top,
      scrollParent.getBoundingClientRect().top,
      scrollParent.scrollTop,
    );
    // Guarded: the every-render measurement below would otherwise loop.
    setScrollMargin((current) => (current === next ? current : next));
  }, [getScrollElement, rootRef]);

  // Deliberately no dependency list. A re-render is the cheapest signal that
  // something in this subtree — a folder opening, a page of chats landing —
  // may have moved the list, and a layout effect lands the correction before
  // the browser paints the wrong window. The guard above makes a no-op
  // measurement free.
  useLayoutEffect(measure);

  useEffect(() => {
    const root = rootRef.current;
    const scrollParent = getScrollElement();
    if (!root || !scrollParent) {
      return;
    }
    // A sibling section growing above the list re-renders *it*, not this
    // component, so React alone never tells us. Observe the boxes whose height
    // can move this list — the scroll container, the list itself, and the
    // container's own sections — and keep that set current as sections mount
    // and unmount (the sidebar renders several of them conditionally).
    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => measure());
    const observeSections = () => {
      if (!resizeObserver) {
        return;
      }
      resizeObserver.disconnect();
      resizeObserver.observe(scrollParent);
      resizeObserver.observe(root);
      for (const section of Array.from(scrollParent.children)) {
        resizeObserver.observe(section);
      }
    };
    observeSections();
    const mutationObserver =
      typeof MutationObserver === "undefined"
        ? null
        : new MutationObserver(() => {
            observeSections();
            measure();
          });
    mutationObserver?.observe(scrollParent, { childList: true });
    // Last line of defence, and the one that matches the symptom directly:
    // whatever the observers miss, the reader's first scroll corrects before
    // they can reach a row a stale margin would have hidden.
    scrollParent.addEventListener("scroll", measure, { passive: true });
    return () => {
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
      scrollParent.removeEventListener("scroll", measure);
    };
  }, [getScrollElement, measure, rootRef]);

  return scrollMargin;
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
  const scrollMargin = useThreadListScrollMargin(rootRef, getScrollElement);
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
