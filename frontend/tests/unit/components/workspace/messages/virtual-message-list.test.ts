import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

const source = readFileSync(
  path.resolve(
    __dirname,
    "../../../../../src/components/workspace/messages/virtual-message-list.tsx",
  ),
  "utf8",
);

describe("message history virtualization", () => {
  it("uses measured stable-key rows and keeps the active tail mounted", () => {
    expect(source).toContain("useVirtualizer");
    expect(source).toContain("measureElement");
    expect(source).toContain("getItemKey");
    expect(source).toContain("activeIndex");
    expect(source).toContain("overscan: 8");
  });

  // The behaviours below decide whether scrolling back through a long thread
  // works, and none of them can be asserted in happy-dom: they only exist
  // against a real layout engine, where `thread-history.spec.ts` covers them.
  // These are the fast guards that fail in milliseconds instead of six minutes
  // when the wiring is undone.

  it("restores the reader's position in the static list too", () => {
    // The static list used to be left to the browser's own scroll anchoring,
    // which does nothing for a scroller at offset 0 — exactly where the
    // load-more sentinel fires — so every older page parked the reader at its
    // top. It restores from the row itself, which there is real DOM.
    const restore = source.slice(
      source.indexOf("let anchorStart"),
      source.indexOf("const anchorItem = pickPrependAnchor("),
    );
    expect(restore).not.toContain("shouldVirtualize &&");
    expect(restore).toContain("[data-message-group-index=");
    expect(restore).toContain("viewport.scrollTo({");
  });

  it("re-seats a virtualized restore on the measured row", () => {
    // The virtualized restore lands where the estimates for the new rows say;
    // only the rendered row says where the reader actually is.
    const restore = source.slice(
      source.indexOf("let anchorStart"),
      source.indexOf("const anchorItem = pickPrependAnchor("),
    );
    expect(restore).toContain("virtualizer.scrollToOffset");
    expect(restore).toContain("settleAnchorOnRow(anchor);");
  });

  it("anchors on a group a prepend cannot re-key", () => {
    // The older page usually completes the list's first turn, which re-keys
    // the first group. Both anchor captures must pass over it.
    expect(source.split("pickPrependAnchor(").length - 1).toBe(2);
  });

  it("holds stick-to-bottom's lock open across a prepend", () => {
    // `use-stick-to-bottom` re-locks on any downward scroll and cannot tell the
    // anchor restore from the reader choosing to go back to the newest turn.
    expect(source).toContain("stickSuppressedUntilRef.current =");
    expect(source).toContain("PREPEND_STICK_SUPPRESSION_MS");
    expect(source).toContain("stopScroll();");
  });

  it("only pulls the viewport to the bottom when the list grew at the tail", () => {
    expect(source).toContain("resolveListGrowth({");
    expect(source).toContain('listGrowthRef.current === "append"');
    expect(source).toContain("grewAtTail && isAtBottom && !stickSuppressed");
  });

  it("settles the restore before anything else may scroll", () => {
    // Effect order is the contract: the position restore has to run before the
    // stick-to-bottom effect can read the suppression window and the growth
    // classification it writes.
    expect(
      source.indexOf("listGrowthRef.current = resolveListGrowth"),
    ).toBeLessThan(source.indexOf('listGrowthRef.current === "append"'));
    expect(source.indexOf("let anchorStart")).toBeLessThan(
      source.indexOf("const stickSuppressed ="),
    );
  });

  it("keeps the re-anchor frame alive across list identity changes", () => {
    // The stick-to-bottom effect schedules a re-anchor on the next frame and
    // cancels it in cleanup. Depending on `groups` (or anything derived from
    // it, such as `getItemKey`) re-runs the effect on every list change, which
    // cancels that frame — and a long restored conversation then parks around
    // the estimated midpoint instead of at its newest turn. That is why the
    // growth classification is computed in the effect above and read from a
    // ref here rather than recomputed from `groups`.
    const deps = source.slice(
      source.indexOf("const stickSuppressed ="),
      source.indexOf("// `use-stick-to-bottom` re-locks"),
    );
    expect(deps).toContain("groups.length,");
    expect(deps).not.toContain("getItemKey,");
  });
});
