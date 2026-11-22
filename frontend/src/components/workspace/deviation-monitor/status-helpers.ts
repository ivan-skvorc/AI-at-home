import {
  normalizeDeviationMonitorSetting,
  readDeviationMonitorState,
  type DeviationMonitorDriftKind,
  type DeviationMonitorStatus,
} from "@/core/threads/deviation-monitor";

/** "idle": on for this chat, with no report for the current run yet. */
export type DeviationMonitorBarKind = "idle" | DeviationMonitorStatus;

export type DeviationMonitorBarTone =
  | "neutral"
  | "busy"
  | "good"
  | "warn"
  | "danger";

export interface DeviationMonitorBarView {
  kind: DeviationMonitorBarKind;
  tone: DeviationMonitorBarTone;
  /** A check is in flight right now. */
  busy: boolean;
  reason: string | null;
  driftKind: DeviationMonitorDriftKind | null;
  restatedTask: string | null;
  /** The model the report names, else the chat's stored pick (`null` = the chat's model). */
  model: string | null;
  checks: number;
  lastStep: number | null;
  hasDetails: boolean;
  /**
   * The chat's choice changed while a run is going, and applies from the next
   * message: "off" while this run keeps the monitor it was sent with, "on"
   * while this run was sent without one. `null` when nothing is pending.
   */
  nextMessage: "on" | "off" | null;
}

const TONES: Record<DeviationMonitorBarKind, DeviationMonitorBarTone> = {
  idle: "neutral",
  off: "neutral",
  checking: "busy",
  on_track: "good",
  unsure: "neutral",
  drifting: "warn",
  retrying: "warn",
  stopped: "danger",
};

function parseTime(value: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * What the status bar shows, or `null` for no bar.
 *
 * The bar exists while the chat's monitor is on, whatever the thread state
 * says: it is also where the monitor is turned off in one click. A run reads
 * its choice once, when it is sent, so while a run is going the bar follows
 * what that run was sent (`runSetting`, or the run's own report, which proves
 * it is monitored) and says when a change applies from the next message.
 * Three stale reports are not shown as current:
 *
 * - "checking" once no run is going — a cancelled run never writes its
 *   verdict, and a spinner that never stops reads as a hung check;
 * - any report older than the run now going — the previous run's "stopped"
 *   would otherwise sit on the bar until this run's first check;
 * - once no run is going, any report older than the newest run
 *   (`latestRunStartedAt`) — runs sent while the monitor was off write
 *   nothing, so an earlier run's verdict would otherwise come back as current
 *   when the monitor is turned on again.
 *
 * One report is not a verdict at all: the backend's run-start write is
 * `on_track` with `last_checked_step: null` (`run_start_state` in
 * contracts/deviation_monitor_contract.json), which means no check has run in
 * this turn yet, so it reads as watching rather than "On track".
 */
export function describeDeviationMonitorBar({
  setting: storedSetting,
  state: storedState,
  isRunning,
  runStartedAt,
  runSetting,
  latestRunStartedAt,
}: {
  setting: unknown;
  state: unknown;
  isRunning: boolean;
  runStartedAt?: number | null;
  /** The chat's choice when the running run was sent; `undefined` when unknown. */
  runSetting?: unknown;
  /** The newest run's start, finished or not. */
  latestRunStartedAt?: number | null;
}): DeviationMonitorBarView | null {
  const setting = normalizeDeviationMonitorSetting(storedSetting);
  const chatOn = setting?.enabled === true;
  let state = readDeviationMonitorState(storedState);

  const since = isRunning ? runStartedAt : latestRunStartedAt;
  if (state && since != null) {
    const updatedAt = parseTime(state.updated_at);
    if (updatedAt !== null && updatedAt < since) state = null;
  }
  if (state?.status === "checking" && !isRunning) state = null;

  let nextMessage: DeviationMonitorBarView["nextMessage"] = null;
  if (isRunning) {
    // A report from this run proves the run asked for the monitor.
    const runReported = runStartedAt != null && state !== null;
    const runOn =
      runReported ||
      (runSetting !== undefined
        ? normalizeDeviationMonitorSetting(runSetting)?.enabled === true
        : chatOn);
    if (!chatOn && !runOn) return null;
    if (chatOn !== runOn) nextMessage = chatOn ? "on" : "off";
  } else if (!chatOn) {
    return null;
  }
  const noCheckYet =
    state?.status === "on_track" && state.last_checked_step === null;

  const kind: DeviationMonitorBarKind = noCheckYet
    ? "idle"
    : (state?.status ?? "idle");
  const reason = state?.reason ?? null;
  const driftKind = state?.drift_kind ?? null;
  const restatedTask = state?.restated_task ?? null;
  return {
    kind,
    tone: TONES[kind],
    busy: kind === "checking" || kind === "retrying",
    reason,
    driftKind,
    restatedTask,
    model: state?.model ?? setting?.model ?? null,
    checks: state?.checks ?? 0,
    lastStep: state?.last_checked_step ?? null,
    hasDetails: reason !== null || driftKind !== null || restatedTask !== null,
    nextMessage,
  };
}
