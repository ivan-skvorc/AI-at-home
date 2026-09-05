/**
 * The sidebar's virtual list does not own the element it scrolls in — the whole
 * sidebar does. `@tanstack/react-virtual` picks which rows to mount by comparing
 * that container's `scrollTop` against row offsets measured from the list's
 * scroll margin, so a margin measured once at mount and never again shifts the
 * rendered window by however much the content *above* the list has moved since:
 * the reader scrolls to a conversation that is in the model and nothing mounts
 * there.
 *
 * That is not a hypothetical drift. On a cold load — the ordinary "PC restart"
 * boot — the folders' expanded set hydrates from `localStorage` in an effect
 * *after* the first paint, so every folder the user left open pushes the root
 * list down one commit later; the channels group above it fills in from its own
 * fetch a moment after that. Neither changes the root list's item count, which
 * was the only thing that used to trigger a re-measure.
 *
 * Layout is not simulated here (happy-dom has no layout engine, so every rect is
 * zero); what is pinned is the wiring — that the watcher actually subscribes to
 * the three ways the list can move, coalesces a burst into one measurement, and
 * detaches on teardown.
 */
import { afterEach, describe, expect, it } from "@rstest/core";

import { watchListLayoutChanges } from "@/components/workspace/thread-list-virtualizer";

/** Long enough for a queued mutation record and the frame it schedules. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 48));

const teardowns: (() => void)[] = [];

afterEach(() => {
  while (teardowns.length) {
    teardowns.pop()?.();
  }
  document.body.innerHTML = "";
});

function mountList() {
  const scrollParent = document.createElement("div");
  const above = document.createElement("div");
  const root = document.createElement("div");
  scrollParent.append(above, root);
  document.body.append(scrollParent);

  let measurements = 0;
  const stop = watchListLayoutChanges(root, scrollParent, () => {
    measurements += 1;
  });
  teardowns.push(stop);

  return {
    above,
    measurements: () => measurements,
    root,
    scrollParent,
    stop,
  };
}

describe("watchListLayoutChanges", () => {
  it("re-measures when a sibling above the list grows", async () => {
    const list = mountList();

    // A folder above the list opening, or another sidebar group finishing its
    // fetch: the list moved, its own item count did not change.
    list.above.append(document.createElement("div"));
    await settle();

    expect(list.measurements()).toBe(1);
  });

  it("coalesces a burst of mutations into one measurement", async () => {
    const list = mountList();

    for (let index = 0; index < 25; index += 1) {
      list.above.append(document.createElement("div"));
    }
    await settle();

    expect(list.measurements()).toBe(1);
  });

  it("re-measures while the container scrolls", async () => {
    const list = mountList();

    // The self-heal: the margin is scroll-invariant, so a scroll is a free
    // chance to repair drift no observer could see — during the very
    // interaction that would otherwise expose it as a gap in the list.
    list.scrollParent.dispatchEvent(new Event("scroll"));
    await settle();

    expect(list.measurements()).toBe(1);
  });

  it("stops measuring once torn down", async () => {
    const list = mountList();
    list.above.append(document.createElement("div"));
    await settle();
    expect(list.measurements()).toBe(1);

    list.stop();
    list.above.append(document.createElement("div"));
    list.scrollParent.dispatchEvent(new Event("scroll"));
    await settle();

    expect(list.measurements()).toBe(1);
  });
});
