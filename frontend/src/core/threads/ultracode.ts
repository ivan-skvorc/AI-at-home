/**
 * Double Plus Ultracode (fork feature, FORK.md §44), inspired by Claude Code's
 * ultracode: the lead plans substantive work as a workflow script that the
 * Script workflows extension runs in the background, and the result comes back
 * to the conversation on its own.
 *
 * The mode is an Ultra run plus one per-run plugin option addressed to the
 * extension (`plugin_options["community.workflows"]`). The two limits are the
 * user's Settings → Subagents choice; the extension clamps both to the
 * operator's configuration, so they can only lower a run, never raise it.
 */

import type { FrontendContribution } from "../extensions/contracts";

export const ULTRACODE_MODE = "ultracode";
export const ULTRACODE_NAMESPACE = "community.workflows";

export interface UltracodeLimits {
  /** Most agents one workflow may start. */
  maxAgents: number;
  /** Most of them running at once. */
  maxParallel: number;
}

/** The extension's hard ceilings; the operator's own limits may be lower. */
export const ULTRACODE_LIMIT_CEILINGS: UltracodeLimits = {
  maxAgents: 256,
  maxParallel: 16,
};

export const DEFAULT_ULTRACODE_LIMITS: UltracodeLimits = {
  maxAgents: 64,
  maxParallel: 8,
};

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
  };
}

export interface UltracodePluginOptions {
  [ULTRACODE_NAMESPACE]: {
    mode: typeof ULTRACODE_MODE;
    max_agents: number;
    max_parallel: number;
  };
}

/** The run's `plugin_options`: the one key that makes an Ultra run this mode. */
export function ultracodePluginOptions(
  limits: unknown,
): UltracodePluginOptions {
  const { maxAgents, maxParallel } = normalizeUltracodeLimits(limits);
  return {
    [ULTRACODE_NAMESPACE]: {
      mode: ULTRACODE_MODE,
      max_agents: maxAgents,
      max_parallel: Math.min(maxParallel, maxAgents),
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
