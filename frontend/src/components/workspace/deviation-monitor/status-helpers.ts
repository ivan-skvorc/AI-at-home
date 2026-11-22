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
 * says: it is also where the monitor is turned off in one click. Two stale
 * reports are not shown as current:
 *
 * - "checking" once no run is going — a cancelled run never writes its
 *   verdict, and a spinner that never stops reads as a hung check;
 * - any report older than the run now going — the previous run's "stopped"
 *   would otherwise sit on the bar until this run's first check.
 */
export function describeDeviationMonitorBar({
  setting: storedSetting,
  state: storedState,
  isRunning,
  runStartedAt,
}: {
  setting: unknown;
  state: unknown;
  isRunning: boolean;
  runStartedAt?: number | null;
}): DeviationMonitorBarView | null {
  const setting = normalizeDeviationMonitorSetting(storedSetting);
  if (setting?.enabled !== true) return null;
  let state = readDeviationMonitorState(storedState);

  if (state && isRunning && runStartedAt != null) {
    const updatedAt = parseTime(state.updated_at);
    if (updatedAt !== null && updatedAt < runStartedAt) state = null;
  }
  if (state?.status === "checking" && !isRunning) state = null;

  const kind: DeviationMonitorBarKind = state?.status ?? "idle";
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
    model: state?.model ?? setting.model ?? null,
    checks: state?.checks ?? 0,
    lastStep: state?.last_checked_step ?? null,
    hasDetails: reason !== null || driftKind !== null || restatedTask !== null,
  };
}
