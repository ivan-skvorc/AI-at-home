/**
 * The deviation monitor's client half (fork feature).
 *
 * A second model checks, on a cadence the user picks, whether the agent's
 * recent work still serves the request it was given; on a confirmed drift the
 * backend stops the run (or, in a mode with subagents, retries once). This
 * module owns the two halves of the fixed contract with the backend and the
 * per-browser defaults:
 *
 * - **Run context.** The chat's choice is stored per conversation (a
 *   `THREAD_SCOPED_CONTEXT_KEYS` entry) and sent as
 *   `context.deviation_monitor = { enabled: true, model, cadence: { mode,
 *   every } }`. Anything else — off, a stale model, an out-of-range cadence —
 *   is sent as nothing at all, so a hand-edited blob can never put a malformed
 *   object on the wire.
 * - **Thread state.** The monitor reports through a `deviation_monitor`
 *   channel that the status bar renders; the reader here narrows it, since it
 *   arrives from history, `updates` frames and status reads alike.
 *
 * Framework-free on purpose: the composer, the status bar, Settings, the run
 * builder and the stream reducer all read it, and none of them may disagree
 * about what a valid cadence is.
 */

export type DeviationMonitorCadenceMode = "steps" | "turns";

export interface DeviationMonitorCadence {
  mode: DeviationMonitorCadenceMode;
  every: number;
}

/** The backend's bounds; a value outside them turns the monitor off for the run. */
export const DEVIATION_MONITOR_CADENCE_BOUNDS = {
  steps: { min: 1, max: 50 },
  turns: { min: 1, max: 20 },
} as const satisfies Record<
  DeviationMonitorCadenceMode,
  { min: number; max: number }
>;

export const DEFAULT_DEVIATION_MONITOR_CADENCE: DeviationMonitorCadence =
  Object.freeze({ mode: "steps", every: 3 });

/** The Gateway refuses longer model names on the run's model keys too. */
const MAX_MODEL_NAME_LENGTH = 200;

/**
 * The per-chat choice, as stored in the conversation's context override.
 *
 * `enabled: false` keeps the last model and cadence so reopening the dialog
 * starts from them. `model` is absent only for a chat seeded from a Settings
 * default of "the chat's own model": the run then uses the model it is sent
 * with. The dialog itself always stores a concrete model.
 */
export interface DeviationMonitorChatSetting {
  enabled: boolean;
  model?: string;
  cadence: DeviationMonitorCadence;
}

/** `context.deviation_monitor` exactly as the backend contract states it. */
export interface DeviationMonitorRunContext {
  enabled: true;
  model: string;
  cadence: DeviationMonitorCadence;
}

/** Settings → Deviation monitor: what a new chat starts with (per browser). */
export interface DeviationMonitorDefaults {
  enabledForNewChats: boolean;
  /** `undefined` = the chat's own model. */
  modelName?: string | undefined;
  cadence: DeviationMonitorCadence;
}

export const DEFAULT_DEVIATION_MONITOR_DEFAULTS: DeviationMonitorDefaults =
  Object.freeze({
    enabledForNewChats: false,
    modelName: undefined,
    cadence: DEFAULT_DEVIATION_MONITOR_CADENCE,
  });

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validModelName(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 && trimmed.length <= MAX_MODEL_NAME_LENGTH
    ? trimmed
    : undefined;
}

export function isValidDeviationMonitorCadence(
  value: unknown,
): value is DeviationMonitorCadence {
  if (!isRecord(value)) return false;
  const { mode, every } = value;
  if (mode !== "steps" && mode !== "turns") return false;
  const bounds = DEVIATION_MONITOR_CADENCE_BOUNDS[mode];
  return (
    typeof every === "number" &&
    Number.isInteger(every) &&
    every >= bounds.min &&
    every <= bounds.max
  );
}

/**
 * The dialog's three cadence choices. "Every turn" is not a third mode on the
 * wire — it is `{ mode: "turns", every: 1 }` — so it is told apart only here.
 */
export type DeviationMonitorCadenceChoice = "steps" | "turns" | "everyTurn";

export function cadenceChoiceOf(
  cadence: DeviationMonitorCadence,
): DeviationMonitorCadenceChoice {
  if (cadence.mode === "turns" && cadence.every === 1) return "everyTurn";
  return cadence.mode;
}

export type CadenceInputResult =
  | { cadence: DeviationMonitorCadence }
  | { error: "notInteger" | "outOfRange"; min: number; max: number };

/** Validate the dialog's number field for a cadence choice. */
export function cadenceFromChoice(
  choice: DeviationMonitorCadenceChoice,
  rawEvery: string,
): CadenceInputResult {
  if (choice === "everyTurn") {
    return { cadence: { mode: "turns", every: 1 } };
  }
  const bounds = DEVIATION_MONITOR_CADENCE_BOUNDS[choice];
  const trimmed = rawEvery.trim();
  // Digits only: `Number()` would accept "3e1", "0x3" and "" as numbers.
  if (!/^-?\d+$/.test(trimmed)) {
    return { error: "notInteger", min: bounds.min, max: bounds.max };
  }
  const every = Number(trimmed);
  if (every < bounds.min || every > bounds.max) {
    return { error: "outOfRange", min: bounds.min, max: bounds.max };
  }
  return { cadence: { mode: choice, every } };
}

/**
 * Read a stored per-chat choice. The switch and the model must be readable or
 * there is no choice at all; a broken cadence alone falls back to the default
 * cadence rather than discarding the user's switch.
 */
export function normalizeDeviationMonitorSetting(
  value: unknown,
): DeviationMonitorChatSetting | undefined {
  if (!isRecord(value) || typeof value.enabled !== "boolean") {
    return undefined;
  }
  const model = validModelName(value.model);
  const cadence = isValidDeviationMonitorCadence(value.cadence)
    ? { mode: value.cadence.mode, every: value.cadence.every }
    : { ...DEFAULT_DEVIATION_MONITOR_CADENCE };
  return {
    enabled: value.enabled,
    ...(model ? { model } : {}),
    cadence,
  };
}

/**
 * `context.deviation_monitor` for a run, or `undefined` to send nothing.
 *
 * Strict on purpose, unlike the stored-value reader: only an explicit
 * `enabled: true` with an in-range cadence is sent, because the backend turns
 * the monitor off (with a logged reason) for anything else, and a run that the
 * user believes is monitored must not quietly be the one that is not.
 */
export function deviationMonitorRunContext(
  setting: unknown,
  runModelName: unknown,
): DeviationMonitorRunContext | undefined {
  if (!isRecord(setting) || setting.enabled !== true) return undefined;
  if (!isValidDeviationMonitorCadence(setting.cadence)) return undefined;
  const model =
    setting.model === undefined
      ? validModelName(runModelName)
      : validModelName(setting.model);
  if (!model) return undefined;
  return {
    enabled: true,
    model,
    cadence: { mode: setting.cadence.mode, every: setting.cadence.every },
  };
}

/** Repair a stored Settings default (stale, hand-edited, or from an older build). */
export function normalizeDeviationMonitorDefaults(
  value: unknown,
): DeviationMonitorDefaults {
  if (!isRecord(value)) return { ...DEFAULT_DEVIATION_MONITOR_DEFAULTS };
  return {
    enabledForNewChats:
      typeof value.enabledForNewChats === "boolean"
        ? value.enabledForNewChats
        : DEFAULT_DEVIATION_MONITOR_DEFAULTS.enabledForNewChats,
    modelName: validModelName(value.modelName),
    cadence: isValidDeviationMonitorCadence(value.cadence)
      ? { mode: value.cadence.mode, every: value.cadence.every }
      : { ...DEFAULT_DEVIATION_MONITOR_CADENCE },
  };
}

export function chatSettingFromDefaults(
  defaults: DeviationMonitorDefaults,
): DeviationMonitorChatSetting {
  return {
    enabled: defaults.enabledForNewChats,
    ...(defaults.modelName ? { model: defaults.modelName } : {}),
    cadence: { ...defaults.cadence },
  };
}

/**
 * The choice a new chat starts with, or `null` to leave it alone.
 *
 * Only a chat that is still new, has no choice of its own yet (an explicit
 * "off" in this chat wins), and whose user switched the default on. An
 * existing chat never picks the default up: "off by default per chat" means a
 * conversation that predates the setting stays unmonitored.
 */
export function newChatDeviationMonitorSeed({
  isNewThread,
  override,
  defaults,
}: {
  isNewThread: boolean;
  override: Record<string, unknown>;
  defaults: DeviationMonitorDefaults;
}): DeviationMonitorChatSetting | null {
  if (!isNewThread || !defaults.enabledForNewChats) return null;
  if (Object.prototype.hasOwnProperty.call(override, "deviation_monitor")) {
    return null;
  }
  return chatSettingFromDefaults(defaults);
}

/**
 * The model the dialog starts on: the first candidate still configured.
 *
 * Callers pass, in order, the chat's remembered monitor model, the Settings
 * default and the chat's own model ("preselect the Settings default if one is
 * set, otherwise the chat's current model"). A name that left `config.yaml`
 * is skipped rather than preselected, because the backend would refuse it and
 * turn the monitor off for the run. `""` while the roster is still loading:
 * the dialog cannot save a model it cannot show.
 */
export function pickDeviationMonitorModel(
  configured: readonly string[],
  candidates: readonly (string | null | undefined)[],
): string {
  for (const candidate of candidates) {
    if (candidate && configured.includes(candidate)) return candidate;
  }
  return "";
}

/**
 * Whether a conversation's local override holds a workflow choice of its own.
 *
 * The thread-workflow seed (FORK.md §36) adopts the model a conversation
 * recorded on the thread only while this browser holds no selection for it.
 * A monitor choice — which a new chat gets from the Settings default without
 * the user touching anything — is not a model selection, and counting it
 * would make every such chat ignore the model it was actually run with.
 */
export function holdsWorkflowSelection(
  override: Record<string, unknown>,
): boolean {
  return Object.keys(override).some((key) => key !== "deviation_monitor");
}

/**
 * A side chat's starting context. It copies its parent's selection, but it has
 * no monitor button and no status bar, so a monitor carried along would check
 * and stop side-chat runs with nothing on screen to explain it.
 */
export function sidecarRunContext<
  T extends { deviation_monitor?: unknown } & Record<string, unknown>,
>(context: T): T {
  // The key is optional on every context type, so dropping it keeps a `T`;
  // `Omit` would also drop the named keys of a type with an index signature.
  const rest: T = { ...context };
  delete rest.deviation_monitor;
  return rest;
}

// ---------------------------------------------------------------------------
// The thread-state channel
// ---------------------------------------------------------------------------

export const DEVIATION_MONITOR_STATUSES = [
  "off",
  "checking",
  "on_track",
  "unsure",
  "drifting",
  "retrying",
  "stopped",
] as const;

export type DeviationMonitorStatus =
  (typeof DEVIATION_MONITOR_STATUSES)[number];

/** The drift eval's kinds (FORK.md §25a), which the backend judge reuses. */
export const DEVIATION_MONITOR_DRIFT_KINDS = [
  "goal_substitution",
  "scope_creep",
  "abandonment",
  "false_completion",
] as const;

export type DeviationMonitorDriftKind =
  (typeof DEVIATION_MONITOR_DRIFT_KINDS)[number];

/** The `deviation_monitor` thread-state channel, narrowed. */
export interface DeviationMonitorState {
  status: DeviationMonitorStatus;
  reason: string | null;
  drift_kind: DeviationMonitorDriftKind | null;
  restated_task: string | null;
  model: string | null;
  checks: number;
  last_checked_step: number | null;
  updated_at: string | null;
}

function textOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function wholeOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : null;
}

/**
 * Narrow the channel. An unknown status is no state at all (it renders
 * nothing rather than a bar that claims something the backend did not say);
 * other fields of the wrong type are dropped one by one.
 */
export function readDeviationMonitorState(
  value: unknown,
): DeviationMonitorState | null {
  if (!isRecord(value)) return null;
  const status = value.status;
  if (
    typeof status !== "string" ||
    !(DEVIATION_MONITOR_STATUSES as readonly string[]).includes(status)
  ) {
    return null;
  }
  const driftKind = value.drift_kind;
  return {
    status: status as DeviationMonitorStatus,
    reason: textOrNull(value.reason),
    drift_kind:
      typeof driftKind === "string" &&
      (DEVIATION_MONITOR_DRIFT_KINDS as readonly string[]).includes(driftKind)
        ? (driftKind as DeviationMonitorDriftKind)
        : null,
    restated_task: textOrNull(value.restated_task),
    model: textOrNull(value.model),
    checks: wholeOrNull(value.checks) ?? 0,
    last_checked_step: wholeOrNull(value.last_checked_step),
    updated_at: textOrNull(value.updated_at),
  };
}
