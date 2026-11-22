import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "@rstest/core";

import { selectDeviationMonitorFeature } from "@/core/features/api";
import {
  DEFAULT_LOCAL_SETTINGS,
  THREAD_SCOPED_CONTEXT_KEYS,
  mergeLocalSettings,
  pickThreadScopedContext,
  type LocalSettings,
} from "@/core/settings/local";
import {
  DEFAULT_DEVIATION_MONITOR_CADENCE,
  DEFAULT_DEVIATION_MONITOR_DEFAULTS,
  DEVIATION_MONITOR_CADENCE_BOUNDS,
  DEVIATION_MONITOR_DRIFT_KINDS,
  DEVIATION_MONITOR_STATUSES,
  cadenceChoiceOf,
  cadenceFromChoice,
  chatSettingFromDefaults,
  deviationMonitorRunContext,
  holdsWorkflowSelection,
  newChatDeviationMonitorSeed,
  normalizeDeviationMonitorDefaults,
  normalizeDeviationMonitorSetting,
  pickDeviationMonitorModel,
  readDeviationMonitorState,
  sidecarRunContext,
  type DeviationMonitorRunContext,
} from "@/core/threads/deviation-monitor";
import { buildRunContext } from "@/core/threads/hooks";
import {
  hasRenderedThreadStateUpdate,
  reduceThreadStateUpdates,
} from "@/core/threads/stream-state";
import type { AgentThreadState } from "@/core/threads/types";

/**
 * The deviation monitor's client half (fork feature).
 *
 * The contract with the backend is fixed: the run context carries
 * `deviation_monitor: { enabled: true, model, cadence: { mode, every } }`, and
 * the thread state carries a `deviation_monitor` status channel. Every failure
 * guarded here is silent: the composer button still lights up, the run still
 * answers — it just is not monitored, or the status bar never moves.
 */

const FRONTEND_ROOT = path.resolve(__dirname, "../../../..");
const read = (relativePath: string) =>
  readFileSync(path.join(FRONTEND_ROOT, relativePath), "utf8");

const ON = {
  enabled: true,
  model: "judge-model",
  cadence: { mode: "steps", every: 3 },
} as const;

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

const baseContext = {
  mode: "pro",
  model_name: "chat-model",
  reasoning_effort: undefined,
} as unknown as LocalSettings["context"];

describe("the cadence choice", () => {
  it("bounds every X steps to 1-50 and every N turns to 1-20", () => {
    expect(cadenceFromChoice("steps", "1")).toEqual({
      cadence: { mode: "steps", every: 1 },
    });
    expect(cadenceFromChoice("steps", "50")).toEqual({
      cadence: { mode: "steps", every: 50 },
    });
    expect(cadenceFromChoice("steps", "51")).toEqual({
      error: "outOfRange",
      min: 1,
      max: 50,
    });
    expect(cadenceFromChoice("turns", "20")).toEqual({
      cadence: { mode: "turns", every: 20 },
    });
    expect(cadenceFromChoice("turns", "21")).toEqual({
      error: "outOfRange",
      min: 1,
      max: 20,
    });
    expect(cadenceFromChoice("turns", "0")).toMatchObject({
      error: "outOfRange",
    });
  });

  it("refuses anything that is not a whole number", () => {
    for (const raw of ["", " ", "2.5", "3e1", "abc", "-1", "0x3"]) {
      expect(cadenceFromChoice("steps", raw)).toMatchObject({
        error: raw.trim() === "-1" ? "outOfRange" : "notInteger",
      });
    }
    // Surrounding whitespace from a paste is not an error.
    expect(cadenceFromChoice("steps", " 7 ")).toEqual({
      cadence: { mode: "steps", every: 7 },
    });
  });

  it("stores every turn as one turn, and reads one turn back as every turn", () => {
    // The contract has no third mode: "every turn" is `{mode: "turns", every: 1}`.
    expect(cadenceFromChoice("everyTurn", "")).toEqual({
      cadence: { mode: "turns", every: 1 },
    });
    expect(cadenceChoiceOf({ mode: "turns", every: 1 })).toBe("everyTurn");
    expect(cadenceChoiceOf({ mode: "turns", every: 4 })).toBe("turns");
    expect(cadenceChoiceOf({ mode: "steps", every: 1 })).toBe("steps");
  });
});

describe("what reaches the run context", () => {
  it("is exactly the contract object when the chat's monitor is on", () => {
    expect(deviationMonitorRunContext(ON, "chat-model")).toEqual({
      enabled: true,
      model: "judge-model",
      cadence: { mode: "steps", every: 3 },
    });
  });

  it("is omitted when the monitor is off, so no run is monitored by accident", () => {
    expect(
      deviationMonitorRunContext({ ...ON, enabled: false }, "chat-model"),
    ).toBeUndefined();
    expect(deviationMonitorRunContext(undefined, "chat-model")).toBeUndefined();
  });

  it("follows the chat's model when the stored choice names none", () => {
    // A chat seeded from a Settings default of "Same as the chat's model".
    const followsChat = withoutModel(ON);
    expect(deviationMonitorRunContext(followsChat, "chat-model")).toEqual({
      ...ON,
      model: "chat-model",
    });
    expect(deviationMonitorRunContext(followsChat, undefined)).toBeUndefined();
  });

  it("never sends a value the backend would have to reject", () => {
    // A hand-edited or stale localStorage blob must degrade to "off", never
    // to a malformed object on the wire.
    for (const bad of [
      { ...ON, cadence: { mode: "steps", every: 51 } },
      { ...ON, cadence: { mode: "turns", every: 21 } },
      { ...ON, cadence: { mode: "steps", every: 2.5 } },
      { ...ON, cadence: { mode: "tokens", every: 3 } },
      { ...ON, cadence: { mode: "steps", every: "3" } },
      { ...ON, enabled: "true" },
      { ...ON, model: "   " },
      { ...ON, model: "x".repeat(201) },
      "on",
      null,
      [],
    ]) {
      expect(deviationMonitorRunContext(bad, "chat-model")).toBeUndefined();
    }
  });

  it("is sent by the shared run-context builder, explicitly", () => {
    const context = buildRunContext({
      settings: { ...baseContext, deviation_monitor: ON },
      threadId: "t-1",
    });
    expect(context.deviation_monitor).toEqual(ON);
    // Not left to the settings spread: a key that reaches the wire only as a
    // side effect of a spread is one refactor away from not being sent.
    const hooks = read("src/core/threads/hooks.ts");
    expect(
      hooks.match(/deviation_monitor: deviationMonitorRunContext\(/g),
    ).toHaveLength(1);
  });

  it("survives every mode's derived context, Ultracode and Democracy included", () => {
    for (const mode of [
      "flash",
      "thinking",
      "pro",
      "ultra",
      "democracy",
      "ultracode",
      "double_ultracode",
    ] as const) {
      const context = buildRunContext({
        settings: {
          ...baseContext,
          mode,
          democracy_participants: ["a", "b", "c"],
          deviation_monitor: ON,
        },
        threadId: "t-1",
      });
      expect(context.deviation_monitor).toEqual(ON);
    }
  });

  it("drops a switched-off choice rather than spreading it onto the wire", () => {
    const context = buildRunContext({
      settings: {
        ...baseContext,
        deviation_monitor: { ...ON, enabled: false },
      },
      threadId: "t-1",
    });
    expect(JSON.parse(JSON.stringify(context))).not.toHaveProperty(
      "deviation_monitor",
    );
  });

  it("resolves a follow-the-chat model to the model this run is sent with", () => {
    const followsChat = withoutModel(ON);
    const context = buildRunContext({
      settings: { ...baseContext, deviation_monitor: followsChat },
      threadId: "t-1",
      extraContext: { model_name: "one-turn-model" },
    });
    expect(context.deviation_monitor).toEqual({
      ...ON,
      model: "one-turn-model",
    });
  });

  it("is not inherited by a side chat", () => {
    // A side chat starts from its parent's context but has no monitor button
    // and no status bar, so a monitor riding along would be invisible.
    const sidecar = sidecarRunContext({
      ...baseContext,
      deviation_monitor: ON,
    });
    expect(sidecar).not.toHaveProperty("deviation_monitor");
    expect(sidecar.model_name).toBe("chat-model");
  });
});

describe("where the per-chat choice is stored", () => {
  it("is scoped to the conversation, like the model", () => {
    expect(THREAD_SCOPED_CONTEXT_KEYS).toContain("deviation_monitor");
    expect(pickThreadScopedContext({ deviation_monitor: ON })).toEqual({
      deviation_monitor: ON,
    });
  });

  it("is off in every chat until it is turned on there", () => {
    expect(DEFAULT_LOCAL_SETTINGS.context).not.toHaveProperty(
      "deviation_monitor",
    );
  });

  it("reads a stored choice tolerantly", () => {
    expect(normalizeDeviationMonitorSetting(ON)).toEqual(ON);
    expect(normalizeDeviationMonitorSetting({ ...ON, enabled: false })).toEqual(
      { ...ON, enabled: false },
    );
    // A broken cadence keeps the switch but falls back to the default cadence.
    expect(
      normalizeDeviationMonitorSetting({
        ...ON,
        cadence: { mode: "steps", every: 99 },
      }),
    ).toEqual({ ...ON, cadence: DEFAULT_DEVIATION_MONITOR_CADENCE });
    expect(normalizeDeviationMonitorSetting("on")).toBeUndefined();
    expect(normalizeDeviationMonitorSetting({ model: "x" })).toBeUndefined();
  });

  it("does not count as a workflow selection when a chat seeds its workflow", () => {
    // A chat this browser touched only through the monitor still adopts the
    // model it recorded on the thread (FORK.md §36).
    expect(holdsWorkflowSelection({ deviation_monitor: ON })).toBe(false);
    expect(holdsWorkflowSelection({})).toBe(false);
    expect(
      holdsWorkflowSelection({ deviation_monitor: ON, model_name: "m" }),
    ).toBe(true);
    expect(holdsWorkflowSelection({ internet_enabled: false })).toBe(true);
  });
});

describe("the Settings defaults", () => {
  it("default to off, the chat's own model and every three steps", () => {
    expect(DEFAULT_LOCAL_SETTINGS.deviationMonitor).toEqual({
      enabledForNewChats: false,
      modelName: undefined,
      cadence: { mode: "steps", every: 3 },
    });
    expect(mergeLocalSettings({}).deviationMonitor).toEqual(
      DEFAULT_DEVIATION_MONITOR_DEFAULTS,
    );
  });

  it("repair a stale or hand-edited stored value", () => {
    expect(
      normalizeDeviationMonitorDefaults({
        enabledForNewChats: "yes",
        modelName: 42,
        cadence: { mode: "turns", every: 900 },
      }),
    ).toEqual(DEFAULT_DEVIATION_MONITOR_DEFAULTS);
    expect(
      mergeLocalSettings({
        deviationMonitor: {
          enabledForNewChats: true,
          modelName: "judge-model",
          cadence: { mode: "turns", every: 2 },
        },
      }).deviationMonitor,
    ).toEqual({
      enabledForNewChats: true,
      modelName: "judge-model",
      cadence: { mode: "turns", every: 2 },
    });
  });

  it("seed a new chat only, and only when it has no choice of its own", () => {
    const defaults = {
      enabledForNewChats: true,
      modelName: "judge-model",
      cadence: { mode: "turns" as const, every: 2 },
    };
    expect(
      newChatDeviationMonitorSeed({
        isNewThread: true,
        override: {},
        defaults,
      }),
    ).toEqual({
      enabled: true,
      model: "judge-model",
      cadence: { mode: "turns", every: 2 },
    });
    // An existing chat that predates the default stays off.
    expect(
      newChatDeviationMonitorSeed({
        isNewThread: false,
        override: {},
        defaults,
      }),
    ).toBeNull();
    // The user already turned it off in this new chat: their choice wins.
    expect(
      newChatDeviationMonitorSeed({
        isNewThread: true,
        override: { deviation_monitor: { ...ON, enabled: false } },
        defaults,
      }),
    ).toBeNull();
    expect(
      newChatDeviationMonitorSeed({
        isNewThread: true,
        override: {},
        defaults: { ...defaults, enabledForNewChats: false },
      }),
    ).toBeNull();
  });

  it("leave the model out when the default is the chat's own model", () => {
    expect(
      chatSettingFromDefaults({
        enabledForNewChats: true,
        modelName: undefined,
        cadence: DEFAULT_DEVIATION_MONITOR_CADENCE,
      }),
    ).toEqual({ enabled: true, cadence: DEFAULT_DEVIATION_MONITOR_CADENCE });
  });
});

describe("the dialog's preselected model", () => {
  const configured = ["chat-model", "judge-model", "other"];

  it("prefers the chat's remembered pick, then the Settings default, then the chat's model", () => {
    expect(
      pickDeviationMonitorModel(configured, [
        "other",
        "judge-model",
        "chat-model",
      ]),
    ).toBe("other");
    expect(
      pickDeviationMonitorModel(configured, [
        undefined,
        "judge-model",
        "chat-model",
      ]),
    ).toBe("judge-model");
    expect(
      pickDeviationMonitorModel(configured, [
        undefined,
        undefined,
        "chat-model",
      ]),
    ).toBe("chat-model");
  });

  it("skips a model that is no longer configured", () => {
    expect(
      pickDeviationMonitorModel(configured, ["removed", null, "chat-model"]),
    ).toBe("chat-model");
    // Nothing to preselect (roster still loading): the dialog cannot save.
    expect(pickDeviationMonitorModel([], ["judge-model"])).toBe("");
  });
});

describe("the thread-state channel", () => {
  const checking = {
    status: "checking",
    reason: null,
    drift_kind: null,
    restated_task: null,
    model: "judge-model",
    checks: 2,
    last_checked_step: 6,
    updated_at: "2026-11-22T10:00:00Z",
  };

  it("is folded from an updates frame and counts as rendered state", () => {
    const frame = {
      DeviationMonitorMiddleware: { deviation_monitor: checking },
    };
    expect(hasRenderedThreadStateUpdate(frame)).toBe(true);
    expect(
      reduceThreadStateUpdates(
        { title: "t", messages: [] } as AgentThreadState,
        frame,
      ),
    ).toEqual({ deviation_monitor: checking });
  });

  it("replaces the previous status with the latest one", () => {
    const stopped = {
      ...checking,
      status: "stopped",
      reason: "It started rewriting the whole README.",
      drift_kind: "scope_creep",
      restated_task: "Fix the typo in README.md",
    };
    const patch = reduceThreadStateUpdates(
      {
        title: "t",
        messages: [],
        deviation_monitor: checking,
      } as AgentThreadState,
      { node: { deviation_monitor: stopped } },
    );
    expect(patch).toEqual({ deviation_monitor: stopped });
  });

  it("ignores a null or malformed write instead of blanking the bar", () => {
    for (const bad of [null, "stopped", { status: "exploded" }, []]) {
      expect(
        reduceThreadStateUpdates(
          { title: "t", messages: [] } as AgentThreadState,
          { node: { deviation_monitor: bad } },
        ),
      ).toBeUndefined();
    }
  });

  it("reads each status and drops fields of the wrong type", () => {
    for (const status of [
      "off",
      "checking",
      "on_track",
      "unsure",
      "drifting",
      "retrying",
      "stopped",
    ]) {
      expect(readDeviationMonitorState({ status })?.status).toBe(status);
    }
    expect(
      readDeviationMonitorState({
        status: "drifting",
        reason: 7,
        drift_kind: "made_up",
        checks: -1,
        last_checked_step: 1.5,
        model: ["x"],
      }),
    ).toEqual({
      status: "drifting",
      reason: null,
      drift_kind: null,
      restated_task: null,
      model: null,
      checks: 0,
      last_checked_step: null,
      updated_at: null,
    });
  });
});

describe("the operator flag", () => {
  it("offers the button only when /api/features says the feature is on", () => {
    expect(
      selectDeviationMonitorFeature({
        agents_api: { enabled: true },
        deviation_monitor: { enabled: true },
      }),
    ).toEqual({ enabled: true });
    expect(
      selectDeviationMonitorFeature({
        agents_api: { enabled: true },
        deviation_monitor: { enabled: false },
      }),
    ).toEqual({ enabled: false });
    // A Gateway that predates the feature cannot honour the context key.
    expect(
      selectDeviationMonitorFeature({ agents_api: { enabled: true } }),
    ).toEqual({ enabled: false });
  });
});

/**
 * The fixture the backend's tests regenerate (`TestSharedContract` in
 * backend/tests/test_deviation_monitor.py), so a rename or a new status on
 * either side fails here instead of leaving a button that does nothing.
 */
const CONTRACT = JSON.parse(
  read("../contracts/deviation_monitor_contract.json"),
) as {
  context_key: string;
  cadence_bounds: Record<string, { min: number; max: number }>;
  run_context_examples: DeviationMonitorRunContext[];
  state_channel: string;
  statuses: string[];
  drift_kinds: string[];
  run_start_state: Record<string, unknown>;
  stopped_state: Record<string, unknown>;
  feature_key: string;
};

describe("the backend contract (contracts/deviation_monitor_contract.json)", () => {
  it("names the same key, bounds, statuses and drift kinds", () => {
    expect(THREAD_SCOPED_CONTEXT_KEYS).toContain(CONTRACT.context_key);
    expect(CONTRACT.state_channel).toBe(CONTRACT.context_key);
    expect(DEVIATION_MONITOR_CADENCE_BOUNDS).toEqual(CONTRACT.cadence_bounds);
    expect([...DEVIATION_MONITOR_STATUSES].sort()).toEqual(
      [...CONTRACT.statuses].sort(),
    );
    expect([...DEVIATION_MONITOR_DRIFT_KINDS].sort()).toEqual(
      [...CONTRACT.drift_kinds].sort(),
    );
  });

  it("sends each example exactly as the backend accepts it, and nothing when off", () => {
    for (const example of CONTRACT.run_context_examples) {
      expect(deviationMonitorRunContext(example, "chat-model")).toEqual(
        example,
      );
      expect(
        buildRunContext({
          settings: { ...baseContext, deviation_monitor: example },
          threadId: "t-1",
        }).deviation_monitor,
      ).toEqual(example);
      expect(
        deviationMonitorRunContext({ ...example, enabled: false }, "x"),
      ).toBeUndefined();
    }
  });

  it("reads what the middleware writes, extra fields included", () => {
    // `turn` is the backend's own counter, outside the channel's contract.
    const stopped = Object.fromEntries(
      Object.entries(CONTRACT.stopped_state).filter(([key]) => key !== "turn"),
    );
    expect(readDeviationMonitorState(CONTRACT.stopped_state)).toEqual(stopped);
    // The run-start write's empty strings are "no text", not a reason.
    expect(readDeviationMonitorState(CONTRACT.run_start_state)).toEqual({
      status: "on_track",
      reason: null,
      drift_kind: null,
      restated_task: null,
      model: CONTRACT.run_start_state.model,
      checks: 0,
      last_checked_step: null,
      updated_at: CONTRACT.run_start_state.updated_at,
    });
  });

  it("reads the operator flag under the key the Gateway sends", () => {
    expect(
      selectDeviationMonitorFeature({
        agents_api: { enabled: true },
        [CONTRACT.feature_key]: { enabled: true },
      }),
    ).toEqual({ enabled: true });
  });
});
