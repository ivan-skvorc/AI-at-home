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

  it("restores the reader's position only where the virtualizer owns layout", () => {
    // The static list keeps real DOM above the viewport, so the browser's own
    // scroll anchoring holds it. Scrolling to a virtualizer offset derived
    // from estimates would break exactly what it is meant to preserve.
    const restore = source.slice(
      source.indexOf("let restored = false;"),
      source.indexOf("previousFirstKeyRef.current = firstKey;"),
    );
    expect(restore).toContain("shouldVirtualize &&");
    expect(restore).toContain("virtualizer.scrollToOffset");
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
    expect(source.indexOf("let restored = false;")).toBeLessThan(
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
