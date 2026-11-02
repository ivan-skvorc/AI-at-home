/**
 * Settings → Run limits (fork feature, FORK.md §46): the limits that can end a
 * run early — spend cap, tool-call loop limits, token budgets and the step
 * limit of background runs — edited server-wide from the UI instead of
 * config.yaml. Admin-only writes; any signed-in user can read what runs enforce.
 *
 * The server keeps one override per section. A section the page never saved
 * shows config.yaml's value; saving it stores the whole section, and
 * "Use config.yaml" clears it again. The draft below holds inputs as strings
 * so a half-typed number is not coerced until Save.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetch, getCsrfHeaders } from "@/core/api/fetcher";

const ENDPOINT = "/api/settings/run-limits";
export const RUN_LIMITS_QUERY_KEY = ["settings", "run-limits"] as const;

/** Same bounds the Gateway enforces (run_limit_overrides.py). */
export const RUN_LIMIT_BOUNDS = {
  maxAmount: 1_000_000,
  maxToolCalls: 100_000,
  minTokens: 1000,
  maxTokens: 1_000_000_000,
  maxSteps: 100_000,
} as const;

export interface SpendCapOverride {
  enabled: boolean;
  daily_limit?: number | null;
  weekly_limit?: number | null;
  monthly_limit?: number | null;
}

export interface ToolCallLimitsOverride {
  enabled: boolean;
  warn_threshold: number;
  hard_limit: number;
  tool_freq_warn: number;
  tool_freq_hard_limit: number;
}

export interface TokenBudgetOverride {
  enabled: boolean;
  max_tokens: number;
}

export interface RunLimitOverrides {
  spend_budget?: SpendCapOverride | null;
  loop_detection?: ToolCallLimitsOverride | null;
  token_budget?: TokenBudgetOverride | null;
  subagent_token_budget?: TokenBudgetOverride | null;
  recursion_limit?: number | null;
}

export interface EffectiveRunLimits {
  spend_budget: SpendCapOverride & { currency: string | null };
  loop_detection: ToolCallLimitsOverride & {
    tool_freq_overrides: Record<string, { warn: number; hard_limit: number }>;
  };
  token_budget: TokenBudgetOverride;
  subagent_token_budget: TokenBudgetOverride;
  recursion_limit: number;
  max_recursion_limit: number;
}

export interface RunLimitsResponse {
  overrides: RunLimitOverrides;
  effective: EffectiveRunLimits;
}

export const RUN_LIMIT_SECTIONS = [
  "spend_budget",
  "loop_detection",
  "token_budget",
  "subagent_token_budget",
  "recursion_limit",
] as const;
export type RunLimitSection = (typeof RUN_LIMIT_SECTIONS)[number];

export interface RunLimitsDraft {
  spend_budget: {
    enabled: boolean;
    daily_limit: string;
    weekly_limit: string;
    monthly_limit: string;
  };
  loop_detection: {
    enabled: boolean;
    warn_threshold: string;
    hard_limit: string;
    tool_freq_warn: string;
    tool_freq_hard_limit: string;
  };
  token_budget: { enabled: boolean; max_tokens: string };
  subagent_token_budget: { enabled: boolean; max_tokens: string };
  recursion_limit: string;
}

/** Why a section cannot be saved; the page maps each code to a message. */
export type RunLimitError =
  | "spendNeedsAmount"
  | "notPositiveNumber"
  | "notWholeNumber"
  | "stopBeforeWarn"
  | "tooFewTokens"
  | "tooLarge";

type SectionResult<T> = { value: T } | { error: RunLimitError };

const text = (value: number | null | undefined) =>
  value === null || value === undefined ? "" : String(value);

/** Pre-fill every input from what runs enforce now. */
export function draftFromLimits(limits: EffectiveRunLimits): RunLimitsDraft {
  const { spend_budget, loop_detection } = limits;
  return {
    spend_budget: {
      enabled: spend_budget.enabled,
      daily_limit: text(spend_budget.daily_limit),
      weekly_limit: text(spend_budget.weekly_limit),
      monthly_limit: text(spend_budget.monthly_limit),
    },
    loop_detection: {
      enabled: loop_detection.enabled,
      warn_threshold: text(loop_detection.warn_threshold),
      hard_limit: text(loop_detection.hard_limit),
      tool_freq_warn: text(loop_detection.tool_freq_warn),
      tool_freq_hard_limit: text(loop_detection.tool_freq_hard_limit),
    },
    token_budget: {
      enabled: limits.token_budget.enabled,
      max_tokens: text(limits.token_budget.max_tokens),
    },
    subagent_token_budget: {
      enabled: limits.subagent_token_budget.enabled,
      max_tokens: text(limits.subagent_token_budget.max_tokens),
    },
    recursion_limit: text(limits.recursion_limit),
  };
}

/**
 * Refresh the draft from new server values, keeping sections the user is still
 * editing: saving or clearing one section must not discard unsaved input in
 * another.
 */
export function mergeDraft(
  draft: RunLimitsDraft,
  fresh: RunLimitsDraft,
  editing: ReadonlySet<RunLimitSection>,
): RunLimitsDraft {
  const next = { ...fresh };
  for (const section of editing) {
    (next as Record<RunLimitSection, unknown>)[section] = draft[section];
  }
  return next;
}

function wholeNumber(
  raw: string,
  min: number,
  max: number,
): SectionResult<number> {
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) {
    return { error: "notWholeNumber" };
  }
  const value = Number(trimmed);
  if (value < min) {
    return { error: min > 1 ? "tooFewTokens" : "notWholeNumber" };
  }
  return value > max ? { error: "tooLarge" } : { value };
}

/** A blank amount clears that window; anything else must be a positive number. */
function amount(raw: string): SectionResult<number | null> {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return { value: null };
  }
  const value = Number(trimmed);
  if (!Number.isFinite(value) || value <= 0) {
    return { error: "notPositiveNumber" };
  }
  return value > RUN_LIMIT_BOUNDS.maxAmount ? { error: "tooLarge" } : { value };
}

function tokenBudget(
  draft: RunLimitsDraft["token_budget"],
): SectionResult<TokenBudgetOverride> {
  const tokens = wholeNumber(
    draft.max_tokens,
    RUN_LIMIT_BOUNDS.minTokens,
    RUN_LIMIT_BOUNDS.maxTokens,
  );
  return "error" in tokens
    ? tokens
    : { value: { enabled: draft.enabled, max_tokens: tokens.value } };
}

/** Turn one section of the draft into the override the Gateway stores. */
export function sectionOverride(
  draft: RunLimitsDraft,
  section: RunLimitSection,
): SectionResult<NonNullable<RunLimitOverrides[RunLimitSection]>> {
  switch (section) {
    case "spend_budget": {
      const { enabled } = draft.spend_budget;
      const daily = amount(draft.spend_budget.daily_limit);
      const weekly = amount(draft.spend_budget.weekly_limit);
      const monthly = amount(draft.spend_budget.monthly_limit);
      for (const result of [daily, weekly, monthly]) {
        if ("error" in result) {
          return result;
        }
      }
      const value = {
        enabled,
        daily_limit: "value" in daily ? daily.value : null,
        weekly_limit: "value" in weekly ? weekly.value : null,
        monthly_limit: "value" in monthly ? monthly.value : null,
      };
      if (
        enabled &&
        value.daily_limit === null &&
        value.weekly_limit === null &&
        value.monthly_limit === null
      ) {
        return { error: "spendNeedsAmount" };
      }
      return { value };
    }
    case "loop_detection": {
      const loop = draft.loop_detection;
      const parsed = {
        warn_threshold: wholeNumber(
          loop.warn_threshold,
          1,
          RUN_LIMIT_BOUNDS.maxToolCalls,
        ),
        hard_limit: wholeNumber(
          loop.hard_limit,
          1,
          RUN_LIMIT_BOUNDS.maxToolCalls,
        ),
        tool_freq_warn: wholeNumber(
          loop.tool_freq_warn,
          1,
          RUN_LIMIT_BOUNDS.maxToolCalls,
        ),
        tool_freq_hard_limit: wholeNumber(
          loop.tool_freq_hard_limit,
          1,
          RUN_LIMIT_BOUNDS.maxToolCalls,
        ),
      };
      const values: Record<keyof typeof parsed, number> = {
        warn_threshold: 0,
        hard_limit: 0,
        tool_freq_warn: 0,
        tool_freq_hard_limit: 0,
      };
      for (const key of Object.keys(parsed) as (keyof typeof parsed)[]) {
        const result = parsed[key];
        if ("error" in result) {
          return result;
        }
        values[key] = result.value;
      }
      if (
        values.hard_limit < values.warn_threshold ||
        values.tool_freq_hard_limit < values.tool_freq_warn
      ) {
        return { error: "stopBeforeWarn" };
      }
      return { value: { enabled: loop.enabled, ...values } };
    }
    case "token_budget":
      return tokenBudget(draft.token_budget);
    case "subagent_token_budget":
      return tokenBudget(draft.subagent_token_budget);
    case "recursion_limit":
      return wholeNumber(draft.recursion_limit, 1, RUN_LIMIT_BOUNDS.maxSteps);
  }
}

/**
 * The full override set to PUT: the sections the user edited, built from the
 * draft, and every other section exactly as the server already stores it.
 */
export function buildOverrides(
  current: RunLimitOverrides,
  draft: RunLimitsDraft,
  edited: ReadonlySet<RunLimitSection>,
): SectionResult<RunLimitOverrides> {
  const next: RunLimitOverrides = { ...current };
  for (const section of edited) {
    const result = sectionOverride(draft, section);
    if ("error" in result) {
      return result;
    }
    (next as Record<RunLimitSection, unknown>)[section] = result.value;
  }
  return { value: next };
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((item: { msg?: unknown }) =>
          typeof item?.msg === "string" ? item.msg : "",
        )
        .filter(Boolean)
        .join("; ");
    }
  } catch {
    // Not JSON: fall through to the status line.
  }
  return `HTTP ${response.status}`;
}

export async function fetchRunLimits(): Promise<RunLimitsResponse> {
  const response = await fetch(ENDPOINT, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as RunLimitsResponse;
}

export async function saveRunLimits(
  overrides: RunLimitOverrides,
): Promise<RunLimitsResponse> {
  const response = await fetch(ENDPOINT, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...getCsrfHeaders() },
    body: JSON.stringify(overrides),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as RunLimitsResponse;
}

export function useRunLimits(enabled = true) {
  return useQuery({
    queryKey: RUN_LIMITS_QUERY_KEY,
    queryFn: fetchRunLimits,
    enabled,
  });
}

export function useSaveRunLimits() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: saveRunLimits,
    onSuccess: (response) =>
      client.setQueryData(RUN_LIMITS_QUERY_KEY, response),
  });
}
