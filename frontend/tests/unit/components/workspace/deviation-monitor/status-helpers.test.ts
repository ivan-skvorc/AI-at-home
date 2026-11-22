import { describe, expect, it } from "@rstest/core";

import { describeDeviationMonitorBar } from "@/components/workspace/deviation-monitor/status-helpers";

/**
 * What the deviation monitor's status bar shows (fork feature). Pure, so each
 * state the backend can report is pinned without a DOM.
 */

const ON = {
  enabled: true,
  model: "judge-model",
  cadence: { mode: "steps", every: 3 },
};

/** The stored choice of a chat seeded with "the chat's own model". */
function withoutModel<E, C>({
  enabled,
  cadence,
}: {
  enabled: E;
  cadence: C;
  model?: string;
}) {
  return { enabled, cadence };
}

function state(overrides: Record<string, unknown>) {
  return {
    status: "on_track",
    reason: null,
    drift_kind: null,
    restated_task: null,
    model: "judge-model",
    checks: 1,
    last_checked_step: 3,
    updated_at: "2026-11-22T10:00:05Z",
    ...overrides,
  };
}

describe("describeDeviationMonitorBar", () => {
  it("shows nothing while the chat's monitor is off", () => {
    expect(
      describeDeviationMonitorBar({
        setting: { ...ON, enabled: false },
        state: state({ status: "stopped" }),
        isRunning: false,
      }),
    ).toBeNull();
    expect(
      describeDeviationMonitorBar({
        setting: undefined,
        state: null,
        isRunning: false,
      }),
    ).toBeNull();
  });

  it("is watching before the first report", () => {
    expect(
      describeDeviationMonitorBar({
        setting: ON,
        state: null,
        isRunning: true,
      }),
    ).toMatchObject({ kind: "idle", busy: false, model: "judge-model" });
  });

  it("maps each reported status to its own state", () => {
    const tones = {
      off: "neutral",
      checking: "busy",
      on_track: "good",
      unsure: "neutral",
      drifting: "warn",
      retrying: "warn",
      stopped: "danger",
    } as const;
    for (const [status, tone] of Object.entries(tones)) {
      expect(
        describeDeviationMonitorBar({
          setting: ON,
          state: state({ status }),
          isRunning: true,
        }),
      ).toMatchObject({ kind: status, tone });
    }
  });

  it("carries the reason, the kind of drift and the request for the details", () => {
    const view = describeDeviationMonitorBar({
      setting: ON,
      state: state({
        status: "stopped",
        reason: "It began rewriting the whole README.",
        drift_kind: "scope_creep",
        restated_task: "Fix the typo in README.md",
        checks: 4,
        last_checked_step: 12,
      }),
      isRunning: false,
    });
    expect(view).toMatchObject({
      kind: "stopped",
      reason: "It began rewriting the whole README.",
      driftKind: "scope_creep",
      restatedTask: "Fix the typo in README.md",
      checks: 4,
      lastStep: 12,
      hasDetails: true,
    });
  });

  it("does not keep spinning on a check that no run is waiting for", () => {
    expect(
      describeDeviationMonitorBar({
        setting: ON,
        state: state({ status: "checking" }),
        isRunning: false,
      })?.kind,
    ).toBe("idle");
  });

  it("does not show the previous run's verdict as the current run's", () => {
    const runStartedAt = Date.parse("2026-11-22T10:01:00Z");
    expect(
      describeDeviationMonitorBar({
        setting: ON,
        state: state({ status: "stopped" }),
        isRunning: true,
        runStartedAt,
      })?.kind,
    ).toBe("idle");
    // A report written during this run is shown.
    expect(
      describeDeviationMonitorBar({
        setting: ON,
        state: state({
          status: "drifting",
          updated_at: "2026-11-22T10:01:30Z",
        }),
        isRunning: true,
        runStartedAt,
      })?.kind,
    ).toBe("drifting");
  });

  it("names the chat's model when the choice follows it", () => {
    const followsChat = withoutModel(ON);
    expect(
      describeDeviationMonitorBar({
        setting: followsChat,
        state: null,
        isRunning: false,
      })?.model,
    ).toBeNull();
  });
});
