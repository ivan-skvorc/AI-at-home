import { describe, expect, test } from "@rstest/core";

import type { Model } from "@/core/models/types";
import {
  clampParticipantCount,
  democracyDelegationBudget,
  democracyRunContext,
  estimateDemocracyCost,
  isValidDemocracyPanel,
  MAX_DEMOCRACY_PARTICIPANTS,
  MIN_DEMOCRACY_PARTICIPANTS,
  parseDemocracyLaunch,
} from "@/core/threads/democracy";
import { deriveModeContext } from "@/core/threads/run-context";

function model(name: string, input?: number, output?: number): Model {
  return {
    id: name,
    name,
    model: name,
    display_name: name,
    price:
      input === undefined || output === undefined
        ? null
        : { currency: "USD", input, output },
  };
}

const MODELS = [
  model("organizer", 3, 15),
  model("panelist-a", 3, 15),
  model("panelist-b", 1, 5),
  model("local", undefined, undefined),
];

describe("democracy delegation budget", () => {
  test("covers both phases plus retry headroom", () => {
    // The run-wide default is 6. A three-model panel needs 6 for the happy path
    // alone, so a budget that merely equals the phases turns one failed panelist
    // into a silently smaller panel — excess `task` calls are discarded.
    expect(democracyDelegationBudget(3)).toBeGreaterThan(3 * 2);
  });

  test("never exceeds the range the backend clamps to", () => {
    expect(
      democracyDelegationBudget(MAX_DEMOCRACY_PARTICIPANTS),
    ).toBeLessThanOrEqual(50);
    expect(democracyDelegationBudget(1)).toBeGreaterThanOrEqual(1);
  });
});

describe("panel validity", () => {
  test("two different models is the smallest real panel", () => {
    expect(isValidDemocracyPanel(["a", "b"])).toBe(true);
    expect(isValidDemocracyPanel(["a"])).toBe(false);
    expect(MIN_DEMOCRACY_PARTICIPANTS).toBe(2);
  });

  test("the same model twice is one opinion at twice the price", () => {
    expect(isValidDemocracyPanel(["a", "a"])).toBe(false);
  });

  test("an unfilled slot is not a panelist", () => {
    expect(isValidDemocracyPanel(["a", ""])).toBe(false);
  });

  test("the roster is capped", () => {
    const tooMany = Array.from(
      { length: MAX_DEMOCRACY_PARTICIPANTS + 1 },
      (_, index) => `m${index}`,
    );
    expect(isValidDemocracyPanel(tooMany)).toBe(false);
  });
});

describe("participant count clamping", () => {
  test("an emptied number input collapses to the minimum, not NaN slots", () => {
    expect(clampParticipantCount(Number.NaN)).toBe(MIN_DEMOCRACY_PARTICIPANTS);
  });

  test("clamps both ends and floors fractions", () => {
    expect(clampParticipantCount(0)).toBe(MIN_DEMOCRACY_PARTICIPANTS);
    expect(clampParticipantCount(999)).toBe(MAX_DEMOCRACY_PARTICIPANTS);
    expect(clampParticipantCount(3.7)).toBe(3);
  });
});

describe("cost estimate", () => {
  test("counts one run per panelist per phase", () => {
    const estimate = estimateDemocracyCost(
      { organizer: "organizer", participants: ["panelist-a", "panelist-b"] },
      MODELS,
    );
    expect(estimate.runs).toBe(4);
  });

  test("the multiple compares the panel's rates against one organizer answer", () => {
    // organizer = 18/M blended; panel = 18 + 6 = 24/M -> 1.3x
    const estimate = estimateDemocracyCost(
      { organizer: "organizer", participants: ["panelist-a", "panelist-b"] },
      MODELS,
    );
    expect(estimate.rateMultiple).toBeCloseTo(1.3, 5);
  });

  test("an unpriced panelist counts as zero and is named", () => {
    // Local models are free everywhere else in this fork, so a panel containing
    // one genuinely is cheaper — but a multiple that quietly excludes a model
    // reads as a bug, so the estimate says which one it left out.
    const estimate = estimateDemocracyCost(
      { organizer: "organizer", participants: ["panelist-a", "local"] },
      MODELS,
    );
    expect(estimate.unpricedParticipants).toEqual(["local"]);
    expect(estimate.rateMultiple).toBeCloseTo(1, 5);
  });

  test("an unpriced organizer has nothing to compare against", () => {
    const estimate = estimateDemocracyCost(
      { organizer: "local", participants: ["panelist-a", "panelist-b"] },
      MODELS,
    );
    expect(estimate.rateMultiple).toBeNull();
  });
});

describe("run context", () => {
  test("carries the roster and a budget big enough for it", () => {
    const context = democracyRunContext({
      organizer: "organizer",
      participants: ["panelist-a", "panelist-b"],
      task: "q",
      grading: "off",
    });
    expect(context.democracy_participants).toEqual([
      "panelist-a",
      "panelist-b",
    ]);
    expect(context.max_total_subagents).toBe(democracyDelegationBudget(2));
    expect(context.model_name).toBe("organizer");
  });

  test("the roster is copied, not aliased", () => {
    const participants = ["panelist-a", "panelist-b"];
    const context = democracyRunContext({
      organizer: "organizer",
      participants,
      task: "q",
      grading: "off",
    });
    participants.push("panelist-c");
    expect(context.democracy_participants).toHaveLength(2);
  });
});

describe("mode-derived run context", () => {
  test("democracy is an ultra run with a panel attached", () => {
    const derived = deriveModeContext({
      mode: "democracy",
      model_name: "organizer",
      democracy_participants: ["panelist-a", "panelist-b"],
    });
    expect(derived.subagent_enabled).toBe(true);
    expect(derived.is_plan_mode).toBe(true);
    expect(derived.thinking_enabled).toBe(true);
    expect(derived.reasoning_effort).toBe("high");
    expect(derived.democracy_participants).toEqual([
      "panelist-a",
      "panelist-b",
    ]);
  });

  test("the delegation budget travels with the panel", () => {
    // Without this the run-wide ledger (default 6) truncates the panel partway
    // through phase two and the organizer synthesizes from whoever fit.
    const derived = deriveModeContext({
      mode: "democracy",
      model_name: "organizer",
      democracy_participants: ["a", "b", "c", "d"],
    });
    expect(derived.max_total_subagents).toBe(democracyDelegationBudget(4));
  });

  test("a sub-quorum roster does not raise the budget", () => {
    const derived = deriveModeContext({
      mode: "democracy",
      model_name: "organizer",
      democracy_participants: ["only-one"],
    });
    expect(derived.max_total_subagents).toBeUndefined();
    expect(derived.democracy_participants).toBeUndefined();
  });

  test("it never rewrites the thread's selected model", () => {
    const derived = deriveModeContext({
      mode: "democracy",
      model_name: "organizer",
      democracy_participants: ["a", "b"],
    });
    expect("model_name" in derived).toBe(false);
  });

  test("the other modes are unchanged", () => {
    expect(deriveModeContext({ mode: "ultra" })).toMatchObject({
      thinking_enabled: true,
      is_plan_mode: true,
      subagent_enabled: true,
      reasoning_effort: "high",
    });
    expect(deriveModeContext({ mode: "pro" })).toMatchObject({
      is_plan_mode: true,
      subagent_enabled: false,
      reasoning_effort: "medium",
    });
    expect(deriveModeContext({ mode: "thinking" })).toMatchObject({
      is_plan_mode: false,
      subagent_enabled: false,
      reasoning_effort: "low",
    });
    expect(deriveModeContext({ mode: "flash" })).toMatchObject({
      thinking_enabled: false,
      is_plan_mode: false,
      subagent_enabled: false,
      reasoning_effort: undefined,
    });
  });

  test("an explicit reasoning effort still wins", () => {
    const derived = deriveModeContext({
      mode: "democracy",
      reasoning_effort: "low",
      model_name: "organizer",
      democracy_participants: ["a", "b"],
    });
    expect(derived.reasoning_effort).toBe("low");
  });

  test("switching a panel thread to another mode drops the roster", () => {
    // The roster is thread-scoped and outlives a mode change, and the caller
    // spreads the whole thread context before this. Ultra is the dangerous one:
    // it has `subagent_enabled`, so a leaked roster would render the organizer
    // section on a run the user did not ask to be a panel.
    const derived = deriveModeContext({
      mode: "ultra",
      model_name: "organizer",
      democracy_participants: ["a", "b"],
    });
    expect(derived.subagent_enabled).toBe(true);
    expect("democracy_participants" in derived).toBe(true);
    expect(derived.democracy_participants).toBeUndefined();
  });

  test("no panel means no subagents outside ultra", () => {
    const derived = deriveModeContext({
      mode: "pro",
      democracy_participants: ["a", "b"],
    });
    expect(derived.subagent_enabled).toBe(false);
    expect(derived.democracy_participants).toBeUndefined();
  });
});

describe("launch parsing", () => {
  test("a malformed stash is not a panel", () => {
    expect(parseDemocracyLaunch("not json")).toBeNull();
    expect(parseDemocracyLaunch("null")).toBeNull();
    expect(parseDemocracyLaunch(JSON.stringify({ organizer: "o" }))).toBeNull();
  });

  test("a stash that lost its quorum is rejected rather than run short", () => {
    const raw = JSON.stringify({
      organizer: "organizer",
      participants: ["only-one"],
      task: "q",
    });
    expect(parseDemocracyLaunch(raw)).toBeNull();
  });

  test("non-string roster entries are dropped before the quorum check", () => {
    const raw = JSON.stringify({
      organizer: "organizer",
      participants: ["a", 7, null, "b"],
      task: "q",
    });
    expect(parseDemocracyLaunch(raw)).toEqual({
      organizer: "organizer",
      participants: ["a", "b"],
      task: "q",
      grading: "off",
    });
  });
});

describe("grading", () => {
  test("a chosen scale reaches the run context", () => {
    const context = democracyRunContext({
      organizer: "organizer",
      participants: ["panelist-a", "panelist-b"],
      task: "q",
      grading: "five_point",
    });
    expect(context.democracy_grading).toBe("five_point");
  });

  test("'off' is sent as absent, not as a magic string", () => {
    // The backend's own rule is that an unrecognized scale means no grading, so
    // sending nothing makes the two agree by default rather than by a shared
    // literal that could drift on one side.
    const context = democracyRunContext({
      organizer: "organizer",
      participants: ["panelist-a", "panelist-b"],
      task: "q",
      grading: "off",
    });
    expect(context.democracy_grading).toBeUndefined();
  });

  test("the scale rides the mode-derived context", () => {
    const derived = deriveModeContext({
      mode: "democracy",
      model_name: "organizer",
      democracy_participants: ["a", "b"],
      democracy_grading: "boolean",
    });
    expect(derived.democracy_grading).toBe("boolean");
  });

  test("switching a panel thread to another mode drops the scale too", () => {
    // A leftover scale would put a scoreboard on an ordinary Ultra answer.
    const derived = deriveModeContext({
      mode: "ultra",
      model_name: "organizer",
      democracy_participants: ["a", "b"],
      democracy_grading: "five_point",
    });
    expect("democracy_grading" in derived).toBe(true);
    expect(derived.democracy_grading).toBeUndefined();
  });

  test("a stash from a build that predates grading still starts a panel", () => {
    const raw = JSON.stringify({
      organizer: "organizer",
      participants: ["a", "b"],
      task: "q",
    });
    // Degrades to no grading rather than failing the whole launch.
    expect(parseDemocracyLaunch(raw)?.grading).toBe("off");
  });

  test("an unrecognized scale degrades to no grading", () => {
    const raw = JSON.stringify({
      organizer: "organizer",
      participants: ["a", "b"],
      task: "q",
      grading: "ten_point",
    });
    expect(parseDemocracyLaunch(raw)?.grading).toBe("off");
  });

  test("a valid scale round-trips through the stash", () => {
    const raw = JSON.stringify({
      organizer: "organizer",
      participants: ["a", "b"],
      task: "q",
      grading: "boolean",
    });
    expect(parseDemocracyLaunch(raw)?.grading).toBe("boolean");
  });
});
