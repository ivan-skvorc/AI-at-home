import { afterEach, beforeEach, describe, expect, it } from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";

import { useThreadListScrollMargin } from "@/components/workspace/thread-list-virtualizer";

// The sidebar's chat lists are virtualized inside **one** shared scroll
// container, so each list has to tell the virtualizer its own offset within
// that container (`scrollMargin`). Get that number wrong and the virtualizer
// maps scroll positions onto the wrong rows: the tail of the list is drawn
// above the viewport and the oldest conversations cannot be scrolled to at all.
//
// Measuring it once was the bug. Everything that moves a list sits *above* it
// and moves without the list's own item count changing — folders expanding when
// the per-browser expanded set hydrates, the channels list swapping skeletons
// for rows, the nav list growing an "Agents" row — and all of them settle after
// the first measurement on a cold load, which is why the symptom followed a
// restart. These tests pin each way the hook is told to look again.

type Rect = { top: number; height: number };

const layout = new Map<Element, Rect>();
const RECT_PROPERTY = "getBoundingClientRect";
let originalRectDescriptor: PropertyDescriptor | undefined;

function rectOf(element: Element): DOMRect {
  const rect = layout.get(element) ?? { top: 0, height: 0 };
  return {
    top: rect.top,
    bottom: rect.top + rect.height,
    height: rect.height,
    left: 0,
    right: 0,
    width: 0,
    x: 0,
    y: rect.top,
    toJSON: () => ({}),
  } as DOMRect;
}

/** A ResizeObserver we can fire by hand — happy-dom has no layout to observe. */
class FakeResizeObserver {
  static instances: FakeResizeObserver[] = [];
  observed = new Set<Element>();
  constructor(private readonly callback: () => void) {
    FakeResizeObserver.instances.push(this);
  }
  observe(element: Element) {
    this.observed.add(element);
  }
  unobserve(element: Element) {
    this.observed.delete(element);
  }
  disconnect() {
    this.observed.clear();
  }
  fire() {
    this.callback();
  }
}

let scrollParent: HTMLElement;
let sectionAbove: HTMLElement;
let root: HTMLElement;
let originalResizeObserver: typeof globalThis.ResizeObserver;

/** Move the list down by `delta`, the way a section above it growing would. */
function growSectionAbove(delta: number) {
  const above = layout.get(sectionAbove)!;
  layout.set(sectionAbove, { ...above, height: above.height + delta });
  const rootRect = layout.get(root)!;
  layout.set(root, { ...rootRect, top: rootRect.top + delta });
}

beforeEach(() => {
  // happy-dom has no layout engine, so every rect is ours to state. Elements
  // the test never placed keep the zero rect happy-dom would have given them.
  originalRectDescriptor = Object.getOwnPropertyDescriptor(
    Element.prototype,
    RECT_PROPERTY,
  );
  Object.defineProperty(Element.prototype, RECT_PROPERTY, {
    configurable: true,
    writable: true,
    value: function measure(this: Element) {
      return rectOf(this);
    },
  });

  originalResizeObserver = globalThis.ResizeObserver;
  FakeResizeObserver.instances = [];
  globalThis.ResizeObserver =
    FakeResizeObserver as unknown as typeof globalThis.ResizeObserver;

  scrollParent = document.createElement("div");
  scrollParent.setAttribute("data-sidebar", "content");
  sectionAbove = document.createElement("div");
  root = document.createElement("div");
  scrollParent.append(sectionAbove, root);
  document.body.append(scrollParent);

  layout.set(scrollParent, { top: 40, height: 600 });
  layout.set(sectionAbove, { top: 40, height: 100 });
  layout.set(root, { top: 140, height: 4000 });
});

afterEach(() => {
  cleanup();
  layout.clear();
  if (originalRectDescriptor) {
    Object.defineProperty(
      Element.prototype,
      RECT_PROPERTY,
      originalRectDescriptor,
    );
  }
  globalThis.ResizeObserver = originalResizeObserver;
  scrollParent.remove();
});

function renderMargin() {
  const rootRef = { current: root as HTMLElement | null };
  const getScrollElement = () => scrollParent;
  return renderHook(() => useThreadListScrollMargin(rootRef, getScrollElement));
}

describe("useThreadListScrollMargin", () => {
  it("measures the list's offset inside the shared scroll container", () => {
    const { result } = renderMargin();

    expect(result.current).toBe(100);
  });

  it("keeps the offset scroll-invariant", () => {
    // The margin is a position in the *content*, so scrolling must not change
    // it: the rect moves up by exactly what `scrollTop` gains.
    const { result } = renderMargin();

    act(() => {
      scrollParent.scrollTop = 250;
      layout.set(root, { top: -110, height: 4000 });
      scrollParent.dispatchEvent(new Event("scroll"));
    });

    expect(result.current).toBe(100);
  });

  it("re-measures when a section above the list grows", () => {
    // The channels list swapping its skeletons for rows: a sibling's height
    // changes, this component does not re-render, and nothing but a
    // ResizeObserver on that section can notice.
    const { result } = renderMargin();
    expect(result.current).toBe(100);

    act(() => {
      growSectionAbove(220);
      for (const observer of FakeResizeObserver.instances) {
        observer.fire();
      }
    });

    expect(result.current).toBe(320);
  });

  it("observes the container, the list, and each section above it", () => {
    renderMargin();

    const observer = FakeResizeObserver.instances.at(-1)!;
    expect(observer.observed.has(scrollParent)).toBe(true);
    expect(observer.observed.has(root)).toBe(true);
    expect(observer.observed.has(sectionAbove)).toBe(true);
  });

  it("re-measures and re-observes when a section mounts after the list", async () => {
    // Sidebar sections render conditionally, so the set of boxes to watch is
    // not fixed at mount. A section that appears later both moves the list and
    // has to join the observed set. MutationObserver delivers on a microtask,
    // so the assertion has to let one run.
    const { result } = renderMargin();

    const late = document.createElement("div");
    layout.set(late, { top: 40, height: 60 });
    await act(async () => {
      growSectionAbove(60);
      scrollParent.insertBefore(late, sectionAbove);
      await Promise.resolve();
    });

    expect(result.current).toBe(160);
    expect(FakeResizeObserver.instances.at(-1)!.observed.has(late)).toBe(true);
  });

  it("re-measures on a re-render, which is how an expanding folder reports", () => {
    // Folders expand one render after mount, when the expanded set hydrates
    // from localStorage. That is a re-render of this subtree with the list's
    // own item count unchanged — the case the old dependency list missed.
    const { result, rerender } = renderMargin();

    growSectionAbove(180);
    act(() => {
      rerender();
    });

    expect(result.current).toBe(280);
  });

  it("still corrects itself on scroll when nothing else reported", () => {
    // The backstop, and the one that matches the symptom: whatever the
    // observers miss, the reader's first scroll fixes before they can reach a
    // row the stale margin would have hidden.
    const { result } = renderMargin();

    growSectionAbove(300);
    act(() => {
      scrollParent.dispatchEvent(new Event("scroll"));
    });

    expect(result.current).toBe(400);
  });

  it("stops measuring once the list unmounts", () => {
    const { result, unmount } = renderMargin();

    unmount();
    growSectionAbove(500);
    act(() => {
      scrollParent.dispatchEvent(new Event("scroll"));
    });

    expect(result.current).toBe(100);
  });
});
