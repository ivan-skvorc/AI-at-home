/**
 * Plus Ultracode and Double Plus Ultracode (fork feature, FORK.md §44),
 * inspired by Claude Code's ultracode: the lead plans substantive work as a
 * workflow script that the Script workflows extension runs in the background,
 * and the result comes back to the conversation on its own.
 *
 * Plus Ultracode (`ultracode`) keeps the usual limits. Double Plus Ultracode
 * (`double_ultracode`) is the same run with no automatic limits (no step limit,
 * tool-call limits, token budget or workflow time limit; the spend cap stays),
 * so an extremely large task runs until the model finishes. The host reads
 * `mode` for that; this module only tells the extension which one it is.
 *
 * Either mode is an Ultra run plus one per-run plugin option addressed to the
 * extension (`plugin_options["community.workflows"]`). The three limits are the
 * user's Settings → Subagents choice; the extension clamps each to the
 * operator's configuration, so they can only lower a run, never raise it.
 */

import type { FrontendContribution } from "../extensions/contracts";

export const ULTRACODE_MODE = "ultracode";
/** Same workflow as Plus Ultracode, with no automatic limits. */
export const DOUBLE_ULTRACODE_MODE = "double_ultracode";
export const ULTRACODE_NAMESPACE = "community.workflows";

export type WorkflowScriptMode =
  | typeof ULTRACODE_MODE
  | typeof DOUBLE_ULTRACODE_MODE;

export function isWorkflowScriptMode(
  mode: string | null | undefined,
): mode is WorkflowScriptMode {
  return mode === ULTRACODE_MODE || mode === DOUBLE_ULTRACODE_MODE;
}

export interface UltracodeLimits {
  /** Most agents one workflow may start. */
  maxAgents: number;
  /** Most of them running at once. */
  maxParallel: number;
  /** Wall time of the whole workflow, in minutes. */
  maxMinutes: number;
}

/** The extension's hard ceilings; the operator's own limits may be lower. */
export const ULTRACODE_LIMIT_CEILINGS: UltracodeLimits = {
  maxAgents: 256,
  maxParallel: 16,
  maxMinutes: 240,
};

/**
 * Defaults are the ceilings (FORK.md §46): the brief sizes each workflow to its
 * request, so a low default only cut long tasks short. Lower them in Settings.
 */
export const DEFAULT_ULTRACODE_LIMITS: UltracodeLimits = {
  ...ULTRACODE_LIMIT_CEILINGS,
};

/** The defaults before maxMinutes existed, saved whole into every browser. */
const PREVIOUS_DEFAULTS = { maxAgents: 64, maxParallel: 8 } as const;

function clampLimit(value: unknown, ceiling: number, fallback: number) {
  return typeof value === "number" &&
    Number.isInteger(value) &&
    value >= 1 &&
    value <= ceiling
    ? value
    : fallback;
}

/** Read a stored or typed value back into two whole numbers within bounds. */
export function normalizeUltracodeLimits(value: unknown): UltracodeLimits {
  const raw = (value && typeof value === "object" ? value : {}) as Record<
    string,
    unknown
  >;
  // A stored pair equal to the old defaults, saved before the minutes field
  // existed, was never chosen by the user: move it to the new defaults.
  if (
    !("maxMinutes" in raw) &&
    raw.maxAgents === PREVIOUS_DEFAULTS.maxAgents &&
    raw.maxParallel === PREVIOUS_DEFAULTS.maxParallel
  ) {
    return { ...DEFAULT_ULTRACODE_LIMITS };
  }
  return {
    maxAgents: clampLimit(
      raw.maxAgents,
      ULTRACODE_LIMIT_CEILINGS.maxAgents,
      DEFAULT_ULTRACODE_LIMITS.maxAgents,
    ),
    maxParallel: clampLimit(
      raw.maxParallel,
      ULTRACODE_LIMIT_CEILINGS.maxParallel,
      DEFAULT_ULTRACODE_LIMITS.maxParallel,
    ),
    maxMinutes: clampLimit(
      raw.maxMinutes,
      ULTRACODE_LIMIT_CEILINGS.maxMinutes,
      DEFAULT_ULTRACODE_LIMITS.maxMinutes,
    ),
  };
}

export interface UltracodePluginOptions {
  [ULTRACODE_NAMESPACE]: {
    mode: WorkflowScriptMode;
    max_agents: number;
    max_parallel: number;
    max_minutes: number;
  };
}

/** The run's `plugin_options`: the one key that makes an Ultra run this mode. */
export function ultracodePluginOptions(
  limits: unknown,
  mode: WorkflowScriptMode = ULTRACODE_MODE,
): UltracodePluginOptions {
  const { maxAgents, maxParallel, maxMinutes } =
    normalizeUltracodeLimits(limits);
  return {
    [ULTRACODE_NAMESPACE]: {
      mode,
      max_agents: maxAgents,
      max_parallel: Math.min(maxParallel, maxAgents),
      max_minutes: maxMinutes,
    },
  };
}

/**
 * Offer the mode only where it can run: the Script workflows extension is
 * installed and enabled for this viewer. Without it the composer never shows
 * the entry, and a remembered selection falls back to Ultra visibly.
 */
export function isUltracodeAvailable(
  extensions:
    | readonly Pick<FrontendContribution, "namespace" | "settings">[]
    | undefined,
): boolean {
  return (extensions ?? []).some(
    (entry) =>
      entry.namespace === ULTRACODE_NAMESPACE &&
      entry.settings.enabled === true,
  );
}
