"use client";

import {
  defaultRangeExtractor,
  useVirtualizer,
  type Range,
} from "@tanstack/react-virtual";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  type Key,
  type ReactNode,
} from "react";
import { useStickToBottomContext } from "use-stick-to-bottom";

import {
  createRowHeightEstimator,
  resolveListGrowth,
  type ListGrowth,
} from "@/components/workspace/messages/virtual-message-list-helpers";
import type { MessageGroup } from "@/core/messages/utils";

const VIRTUALIZATION_THRESHOLD = 60;
const GROUP_START_OFFSET = 16;
const VIRTUAL_SCROLL_SETTLE_ATTEMPTS = 4;
const STATIC_SCROLL_SETTLE_ATTEMPTS = 2;
/**
 * How long a prepend keeps stick-to-bottom's lock forced open.
 *
 * `use-stick-to-bottom` re-engages its lock from any *downward* scroll
 * (`handleScroll` -> `setEscapedFromLock(false)`), and cannot tell our
 * anchor restore from the user scrolling down. It defers that decision by 1ms
 * to let its own ResizeObserver mark the event as resize-driven, so whether the
 * lock survives a prepend is a race we lose under load — and losing it scrolls
 * the reader to the bottom of the thread they were scrolling back through.
 * A window comfortably longer than that 1ms deferral makes the outcome
 * deterministic instead.
 */
const PREPEND_STICK_SUPPRESSION_MS = 250;

type GroupAlignment = "start" | "center";

type ScrollToGroupOptions = {
  behavior?: ScrollBehavior;
  align?: GroupAlignment;
};

type VirtualMessageListProps = {
  groups: readonly MessageGroup[];
  isLoading: boolean;
  renderGroup: (group: MessageGroup, index: number) => ReactNode;
  onActiveGroupChange?: (groupIndex: number) => void;
};

export type VirtualMessageListHandle = {
  scrollToGroup: (groupIndex: number, options?: ScrollToGroupOptions) => void;
};

function groupKey(group: MessageGroup | undefined, index: number): Key {
  return (
    group?.id ??
    group?.messages.find((message) => message.id)?.id ??
    `${group?.type ?? "message"}:${index}`
  );
}

export const VirtualMessageList = forwardRef<
  VirtualMessageListHandle,
  VirtualMessageListProps
>(function VirtualMessageList(
  { groups, isLoading, renderGroup, onActiveGroupChange },
  ref,
) {
  const { isAtBottom, scrollRef, scrollToBottom, stopScroll } =
    useStickToBottomContext();
  const listRef = useRef<HTMLDivElement | null>(null);
  const activeIndex = isLoading ? groups.length - 1 : -1;
  const getItemKey = useCallback(
    (index: number) => groupKey(groups[index], index),
    [groups],
  );
  const rangeExtractor = useCallback(
    (range: Range) => {
      const indices = defaultRangeExtractor(range);
      if (activeIndex >= 0 && !indices.includes(activeIndex)) {
        indices.push(activeIndex);
        indices.sort((a, b) => a - b);
      }
      return indices;
    },
    [activeIndex],
  );
  const rowHeightEstimatorRef = useRef(createRowHeightEstimator());
  const estimateRowHeight = useCallback(
    () => rowHeightEstimatorRef.current.estimate(),
    [],
  );
  const measureRowHeight = useCallback(
    (element: Element, entry: ResizeObserverEntry | undefined) => {
      // Mirrors virtual-core's default measurement, with the learned estimate
      // fed from the same numbers the virtualizer actually lays rows out with.
      const borderBox = entry?.borderBoxSize?.[0];
      const size = borderBox
        ? Math.round(borderBox.blockSize)
        : (element as HTMLElement).offsetHeight;
      rowHeightEstimatorRef.current.record(size);
      return size;
    },
    [],
  );
  const virtualizer = useVirtualizer({
    count: groups.length,
    estimateSize: estimateRowHeight,
    getItemKey,
    getScrollElement: () => scrollRef.current,
    measureElement: measureRowHeight,
    overscan: 8,
    rangeExtractor,
  });
  const virtualItems = virtualizer.getVirtualItems();
  const shouldVirtualize = groups.length >= VIRTUALIZATION_THRESHOLD;
  const firstVirtualIndex = virtualItems[0]?.index ?? -1;
  const lastVirtualIndex = virtualItems.at(-1)?.index ?? -1;
  const positionedInitialVirtualWindowRef = useRef(false);
  const previousCountRef = useRef(groups.length);
  const previousFirstKeyRef = useRef<Key | undefined>(undefined);
  const previousActiveGroupRef = useRef(-1);
  /** How the list last changed, classified by the anchor effect below. */
  const listGrowthRef = useRef<ListGrowth>("none");
  /** Epoch ms until which stick-to-bottom's lock is not allowed to re-engage. */
  const stickSuppressedUntilRef = useRef(0);
  const anchorRef = useRef<{ key: Key; viewportOffset: number } | undefined>(
    undefined,
  );

  const alignGroupToViewport = useCallback(
    (
      groupIndex: number,
      align: GroupAlignment,
      behavior: ScrollBehavior,
    ): boolean => {
      const viewport = scrollRef.current;
      const row = listRef.current?.querySelector<HTMLElement>(
        `[data-message-group-index="${groupIndex}"]`,
      );
      if (!viewport || !row) {
        return false;
      }

      const viewportRect = viewport.getBoundingClientRect();
      const rowRect = row.getBoundingClientRect();
      const top =
        viewport.scrollTop +
        rowRect.top -
        viewportRect.top -
        (align === "center"
          ? Math.max(0, (viewport.clientHeight - rowRect.height) / 2)
          : GROUP_START_OFFSET);
      viewport.scrollTo({ top: Math.max(0, top), behavior });
      return true;
    },
    [scrollRef],
  );

  useImperativeHandle(
    ref,
    () => ({
      scrollToGroup(groupIndex, options) {
        if (groupIndex < 0 || groupIndex >= groups.length) {
          return;
        }
        stopScroll();
        const behavior = options?.behavior ?? "auto";
        const align = options?.align ?? "start";
        if (shouldVirtualize) {
          virtualizer.scrollToIndex(groupIndex, { align, behavior });
        }

        const maxAttempts = shouldVirtualize
          ? VIRTUAL_SCROLL_SETTLE_ATTEMPTS
          : STATIC_SCROLL_SETTLE_ATTEMPTS;
        let attempt = 0;
        const settleOnExactGroup = () => {
          const exactBehavior = attempt === 0 ? behavior : "auto";
          const aligned = alignGroupToViewport(
            groupIndex,
            align,
            exactBehavior,
          );
          attempt += 1;
          const needsAnotherAttempt = shouldVirtualize || !aligned;
          if (attempt < maxAttempts && needsAnotherAttempt) {
            requestAnimationFrame(settleOnExactGroup);
          }
        };
        requestAnimationFrame(settleOnExactGroup);
      },
    }),
    [
      alignGroupToViewport,
      groups.length,
      shouldVirtualize,
      stopScroll,
      virtualizer,
    ],
  );

  useEffect(() => {
    const viewport = scrollRef.current;
    const list = listRef.current;
    if (!viewport || !list || !onActiveGroupChange) {
      return;
    }

    let animationFrame: number | undefined;
    const updateActiveGroup = () => {
      animationFrame = undefined;
      const rows = list.querySelectorAll<HTMLElement>(
        "[data-message-group-index]",
      );
      if (rows.length === 0) {
        return;
      }

      const readingLine = viewport.getBoundingClientRect().top + 96;
      let activeRow = rows[0];
      for (const row of rows) {
        if (row.getBoundingClientRect().top > readingLine) {
          break;
        }
        activeRow = row;
      }
      const groupIndex = Number(activeRow?.dataset.messageGroupIndex);
      if (
        Number.isSafeInteger(groupIndex) &&
        groupIndex !== previousActiveGroupRef.current
      ) {
        previousActiveGroupRef.current = groupIndex;
        onActiveGroupChange(groupIndex);
      }
    };
    const scheduleUpdate = () => {
      animationFrame ??= requestAnimationFrame(updateActiveGroup);
    };

    scheduleUpdate();
    viewport.addEventListener("scroll", scheduleUpdate, { passive: true });
    return () => {
      viewport.removeEventListener("scroll", scheduleUpdate);
      if (animationFrame !== undefined) {
        cancelAnimationFrame(animationFrame);
      }
    };
  }, [
    firstVirtualIndex,
    groups,
    lastVirtualIndex,
    onActiveGroupChange,
    scrollRef,
  ]);

  // Runs before the stick-to-bottom effect below on purpose: restoring the
  // reader's position after a prepend has to settle before anything else is
  // allowed to decide the list should scroll.
  useLayoutEffect(() => {
    const firstKey = getItemKey(0);
    const previousFirstKey = previousFirstKeyRef.current;
    const anchor = anchorRef.current;
    // Classified here, where this effect already has both sides of the
    // comparison, and read by the stick-to-bottom effect below. That effect
    // deliberately does NOT depend on `groups`: it schedules a re-anchor on the
    // next frame, and re-running it on every list identity change would cancel
    // that frame in cleanup and leave a long thread parked mid-history.
    listGrowthRef.current = resolveListGrowth({
      previousCount: previousCountRef.current,
      previousFirstKey,
      count: groups.length,
      firstKey: groups.length > 0 ? firstKey : undefined,
    });
    let restored = false;
    if (
      // Only the virtualized list needs restoring. In the static list the rows
      // above the viewport are real DOM with real heights, so the browser's own
      // scroll anchoring already holds the position — and scrolling to an
      // offset the virtualizer derived from estimates would break it.
      shouldVirtualize &&
      previousFirstKey !== undefined &&
      firstKey !== previousFirstKey &&
      anchor
    ) {
      const anchorIndex = groups.findIndex(
        (group, index) => groupKey(group, index) === anchor.key,
      );
      if (anchorIndex >= 0) {
        const anchorStart = virtualizer.getOffsetForIndex(
          anchorIndex,
          "start",
        )?.[0];
        if (anchorStart !== undefined) {
          // Older turns arrived above the viewport. Hold stick-to-bottom's
          // lock open across the restore, or it reads the resulting downward
          // scroll as the reader choosing to go back to the newest message.
          if (!isAtBottom) {
            stickSuppressedUntilRef.current =
              Date.now() + PREPEND_STICK_SUPPRESSION_MS;
            stopScroll();
          }
          virtualizer.scrollToOffset(anchorStart - anchor.viewportOffset, {
            behavior: "auto",
          });
          restored = true;
        }
      }
    }
    previousFirstKeyRef.current = firstKey;

    if (restored) {
      // `virtualItems` was built from the pre-restore scroll offset, so the
      // anchor derived from it here would describe a viewport that no longer
      // exists — and the next prepend would restore to it. Leave the existing
      // anchor alone; the next render captures a consistent one.
      return;
    }

    if (shouldVirtualize) {
      const scrollOffset = virtualizer.scrollOffset ?? 0;
      const firstVisible = virtualItems.find(
        (item) => item.end >= scrollOffset,
      );
      if (firstVisible) {
        anchorRef.current = {
          key: firstVisible.key,
          viewportOffset: firstVisible.start - scrollOffset,
        };
      }
      return;
    }

    // Static list: the virtualizer's offsets are estimates nothing rendered
    // from, so read the anchor off the DOM instead. Keeping it current here is
    // what lets a thread cross VIRTUALIZATION_THRESHOLD — which a loaded
    // history page routinely does — without losing the reader's place.
    const viewport = scrollRef.current;
    const list = listRef.current;
    if (!viewport || !list) {
      return;
    }
    const viewportTop = viewport.getBoundingClientRect().top;
    for (const row of list.querySelectorAll<HTMLElement>(
      "[data-message-group-index]",
    )) {
      const rect = row.getBoundingClientRect();
      if (rect.bottom < viewportTop) {
        continue;
      }
      const index = Number(row.dataset.messageGroupIndex);
      if (Number.isSafeInteger(index) && index >= 0 && index < groups.length) {
        anchorRef.current = {
          key: getItemKey(index),
          viewportOffset: rect.top - viewportTop,
        };
      }
      break;
    }
  }, [
    getItemKey,
    groups,
    isAtBottom,
    scrollRef,
    shouldVirtualize,
    stopScroll,
    virtualItems,
    virtualizer,
  ]);

  useLayoutEffect(() => {
    // Growth alone does not mean a new message arrived: a loaded history page
    // grows the list from the front. Only a list whose first row is unchanged
    // grew at the tail, and only that may pull the viewport to the bottom.
    // Classified by the effect above, which runs first in the same commit.
    const grewAtTail = listGrowthRef.current === "append";
    const stickSuppressed = Date.now() < stickSuppressedUntilRef.current;
    let settleFrame: number | undefined;
    if (
      shouldVirtualize &&
      isAtBottom &&
      !stickSuppressed &&
      !positionedInitialVirtualWindowRef.current
    ) {
      positionedInitialVirtualWindowRef.current = true;
      const scrollToLatest = () => {
        virtualizer.scrollToIndex(groups.length - 1, { align: "end" });
      };
      scrollToLatest();
      // Dynamic row measurement changes the total after the first layout.
      // Re-anchor once with measured sizes so a long restored conversation
      // cannot land around the estimated midpoint.
      settleFrame = requestAnimationFrame(scrollToLatest);
    } else if (!shouldVirtualize) {
      positionedInitialVirtualWindowRef.current = false;
    }
    if (grewAtTail && isAtBottom && !stickSuppressed) {
      void scrollToBottom({
        animation: "instant",
        preserveScrollPosition: true,
      });
    }
    previousCountRef.current = groups.length;
    return () => {
      if (settleFrame !== undefined) cancelAnimationFrame(settleFrame);
    };
  }, [
    groups.length,
    isAtBottom,
    scrollToBottom,
    shouldVirtualize,
    virtualizer,
  ]);

  // `use-stick-to-bottom` re-locks on any downward scroll and defers that call
  // by 1ms, so a prepend's anchor restore can re-engage the lock behind our
  // back. Whenever it does so inside the suppression window opened above,
  // revoke it: the reader is scrolling back, not returning to the newest turn.
  useEffect(() => {
    if (!isAtBottom || Date.now() >= stickSuppressedUntilRef.current) {
      return;
    }
    stopScroll();
  }, [isAtBottom, stopScroll]);

  if (!shouldVirtualize) {
    return (
      <div ref={listRef} className="flex flex-col gap-8">
        {groups.map((group, index) => (
          <div key={getItemKey(index)} data-message-group-index={index}>
            {renderGroup(group, index)}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div
      ref={listRef}
      className="relative w-full"
      style={{ height: `${virtualizer.getTotalSize()}px` }}
    >
      {virtualItems.map((virtualRow) => {
        const group = groups[virtualRow.index];
        if (!group) return null;
        return (
          <div
            key={virtualRow.key}
            ref={virtualizer.measureElement}
            data-index={virtualRow.index}
            data-message-group-index={virtualRow.index}
            className="absolute top-0 left-0 w-full pb-8"
            style={{ transform: `translateY(${virtualRow.start}px)` }}
          >
            {renderGroup(group, virtualRow.index)}
          </div>
        );
      })}
    </div>
  );
});
