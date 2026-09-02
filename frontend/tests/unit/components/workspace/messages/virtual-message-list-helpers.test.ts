import { describe, expect, it } from "@rstest/core";

import {
  createRowHeightEstimator,
  ESTIMATED_ROW_HEIGHT,
  MAX_ESTIMATED_ROW_HEIGHT,
  MIN_ESTIMATED_ROW_HEIGHT,
  MIN_MEASURED_ROWS_FOR_ESTIMATE,
  resolveListGrowth,
} from "@/components/workspace/messages/virtual-message-list-helpers";

describe("resolveListGrowth", () => {
  it("treats a thread's opening load as an append", () => {
    // Nothing can have landed above the first content to arrive, and the list
    // still has to settle at the newest turn when a thread opens.
    expect(
      resolveListGrowth({
        previousCount: 0,
        previousFirstKey: undefined,
        count: 12,
        firstKey: "a",
      }),
    ).toBe("append");
  });

  it("reports no growth when the count is unchanged or smaller", () => {
    expect(
      resolveListGrowth({
        previousCount: 12,
        previousFirstKey: "a",
        count: 12,
        firstKey: "a",
      }),
    ).toBe("none");
    expect(
      resolveListGrowth({
        previousCount: 12,
        previousFirstKey: "a",
        count: 5,
        firstKey: "g",
      }),
    ).toBe("none");
  });

  it("calls growth with an unchanged first row an append", () => {
    expect(
      resolveListGrowth({
        previousCount: 12,
        previousFirstKey: "a",
        count: 13,
        firstKey: "a",
      }),
    ).toBe("append");
  });

  it("calls growth with a new first row a prepend", () => {
    // A loaded history page: 50 older turns arrive above everything on screen.
    expect(
      resolveListGrowth({
        previousCount: 60,
        previousFirstKey: "turn-51",
        count: 110,
        firstKey: "turn-1",
      }),
    ).toBe("prepend");
  });

  it("treats a page that also grew at the tail as a prepend", () => {
    // A history page landing in the same render as a streamed reply must not
    // be read as an append: content arrived above the viewport either way, and
    // pulling the reader to the bottom is the failure this guards.
    expect(
      resolveListGrowth({
        previousCount: 60,
        previousFirstKey: "turn-51",
        count: 111,
        firstKey: "turn-1",
      }),
    ).toBe("prepend");
  });
});

describe("createRowHeightEstimator", () => {
  const record = (
    estimator: ReturnType<typeof createRowHeightEstimator>,
    size: number,
    times: number,
  ) => {
    for (let i = 0; i < times; i += 1) {
      estimator.record(size);
    }
  };

  it("uses the static estimate until enough rows are measured", () => {
    const estimator = createRowHeightEstimator();
    expect(estimator.estimate()).toBe(ESTIMATED_ROW_HEIGHT);

    record(estimator, 320, MIN_MEASURED_ROWS_FOR_ESTIMATE - 1);
    expect(estimator.estimate()).toBe(ESTIMATED_ROW_HEIGHT);
  });

  it("returns the thread's own row height once enough rows are measured", () => {
    const estimator = createRowHeightEstimator();
    record(estimator, 320, MIN_MEASURED_ROWS_FOR_ESTIMATE);
    expect(estimator.estimate()).toBe(320);
  });

  it("ignores unlaid-out rows instead of counting them as samples", () => {
    const estimator = createRowHeightEstimator();
    record(estimator, 0, 50);
    record(estimator, -12, 50);
    expect(estimator.estimate()).toBe(ESTIMATED_ROW_HEIGHT);

    record(estimator, 320, MIN_MEASURED_ROWS_FOR_ESTIMATE);
    expect(estimator.estimate()).toBe(320);
  });

  it("clamps a degenerate average at both ends", () => {
    const tiny = createRowHeightEstimator();
    record(tiny, 4, MIN_MEASURED_ROWS_FOR_ESTIMATE);
    expect(tiny.estimate()).toBe(MIN_ESTIMATED_ROW_HEIGHT);

    const huge = createRowHeightEstimator();
    record(huge, 9_000, MIN_MEASURED_ROWS_FOR_ESTIMATE);
    expect(huge.estimate()).toBe(MAX_ESTIMATED_ROW_HEIGHT);
  });

  it("moves toward the current row size without chasing a single outlier", () => {
    const estimator = createRowHeightEstimator();
    record(estimator, 100, MIN_MEASURED_ROWS_FOR_ESTIMATE);
    expect(estimator.estimate()).toBe(100);

    // One very tall turn must not redefine the estimate for every other row.
    estimator.record(4_000);
    expect(estimator.estimate()).toBeLessThan(600);

    // A sustained change in turn shape should be followed, though — settling
    // near the new size from whichever side the outlier left it on.
    record(estimator, 400, 24);
    const settled = estimator.estimate();
    expect(Math.abs(settled - 400)).toBeLessThan(100);
  });

  it("keeps each thread's estimate independent", () => {
    const first = createRowHeightEstimator();
    const second = createRowHeightEstimator();
    record(first, 500, MIN_MEASURED_ROWS_FOR_ESTIMATE);

    expect(first.estimate()).toBe(500);
    expect(second.estimate()).toBe(ESTIMATED_ROW_HEIGHT);
  });
});
