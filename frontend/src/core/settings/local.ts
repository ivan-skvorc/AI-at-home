import type { TokenUsageInlineMode } from "../messages/usage-model";
import type { AgentThreadContext } from "../threads";

export const DEFAULT_LOCAL_SETTINGS: LocalSettings = {
  notification: {
    enabled: true,
  },
  // Decorative animations (landing background, subagent "flashing lights",
  // aurora/wave shimmer) are reduced by default to keep the UI calm and cheap on
  // GPU/CPU; users who prefer the full motion can turn the toggle off from
  // Settings → Appearance. The system `prefers-reduced-motion` preference is
  // honored independently of this flag (it can only add reduction, never
  // override an explicit opt-in to motion).
  appearance: {
    reduceAnimations: true,
  },
  tokenUsage: {
    headerTotal: true,
    inlineMode: "per_turn",
  },
  // Follow-up suggestions default OFF to avoid the extra per-turn LLM call
  // (and its cost). Users opt in from Settings → Suggestions and can pick which
  // model generates them (undefined = follow the workflow's selected model).
  suggestions: {
    enabled: false,
    modelName: undefined,
  },
  // Long-term memory defaults OFF on a fresh install so the agent does not learn
  // from / inject conversation context until the user explicitly opts in from
  // Settings → Memory. When off, the per-run `memory_enabled` flag is sent to the
  // backend which skips memory injection, extraction, and memory tools for that
  // run (the operator master switch `memory.enabled` in config.yaml still gates
  // availability on top of this per-user preference).
  memory: {
    enabled: false,
  },
  context: {
    model_name: undefined,
    mode: undefined,
    reasoning_effort: undefined,
  },
};

export const LOCAL_SETTINGS_KEY = "deerflow.local-settings";
export const THREAD_MODEL_KEY_PREFIX = "deerflow.thread-model.";

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export interface LocalSettings {
  notification: {
    enabled: boolean;
  };
  appearance: {
    // When true, decorative/continuous animations are suppressed to reduce
    // GPU/CPU overhead and visual noise. This is combined (logical OR) with the
    // system `prefers-reduced-motion` media query at read time.
    reduceAnimations: boolean;
  };
  tokenUsage: {
    headerTotal: boolean;
    inlineMode: TokenUsageInlineMode;
  };
  suggestions: {
    // Whether the follow-up suggestion chips are generated after each answer.
    enabled: boolean;
    // Model that generates the suggestions; undefined = follow the workflow's
    // selected model (the thread's current lead model).
    modelName?: string | undefined;
  };
  memory: {
    // Whether long-term memory is used for this user. Sent to the backend as the
    // per-run `memory_enabled` flag; when false the backend skips memory
    // injection/extraction/tools for the run. Combined (logical AND) with the
    // operator master switch `memory.enabled` in config.yaml.
    enabled: boolean;
  };
  context: Omit<
    AgentThreadContext,
    | "thread_id"
    | "is_plan_mode"
    | "thinking_enabled"
    | "subagent_enabled"
    | "subagent_model_name"
    | "model_name"
    | "reasoning_effort"
    | "memory_enabled"
  > & {
    model_name?: string | undefined;
    subagent_model_name?: string | undefined;
    mode: "flash" | "thinking" | "pro" | "ultra" | undefined;
    reasoning_effort?: "minimal" | "low" | "medium" | "high";
  };
}

export function mergeLocalSettings(
  settings?: Partial<LocalSettings>,
): LocalSettings {
  return {
    ...DEFAULT_LOCAL_SETTINGS,
    context: {
      ...DEFAULT_LOCAL_SETTINGS.context,
      ...settings?.context,
    },
    tokenUsage: {
      ...DEFAULT_LOCAL_SETTINGS.tokenUsage,
      ...settings?.tokenUsage,
    },
    suggestions: {
      ...DEFAULT_LOCAL_SETTINGS.suggestions,
      ...settings?.suggestions,
    },
    memory: {
      ...DEFAULT_LOCAL_SETTINGS.memory,
      ...settings?.memory,
    },
    notification: {
      ...DEFAULT_LOCAL_SETTINGS.notification,
      ...settings?.notification,
    },
    appearance: {
      ...DEFAULT_LOCAL_SETTINGS.appearance,
      ...settings?.appearance,
    },
  };
}

function getThreadModelStorageKey(threadId: string): string {
  return `${THREAD_MODEL_KEY_PREFIX}${threadId}`;
}

export function getThreadModelName(threadId: string): string | undefined {
  if (!isBrowser()) {
    return undefined;
  }
  return localStorage.getItem(getThreadModelStorageKey(threadId)) ?? undefined;
}

export function saveThreadModelName(
  threadId: string,
  modelName: string | undefined,
) {
  if (!isBrowser()) {
    return;
  }
  const key = getThreadModelStorageKey(threadId);
  if (!modelName) {
    localStorage.removeItem(key);
    return;
  }
  localStorage.setItem(key, modelName);
}

export function applyThreadModelOverride(
  settings: LocalSettings,
  threadModelName: string | undefined,
): LocalSettings {
  if (!threadModelName) {
    return settings;
  }
  return {
    ...settings,
    context: {
      ...settings.context,
      model_name: threadModelName,
    },
  };
}

export function getLocalSettings(): LocalSettings {
  if (!isBrowser()) {
    return DEFAULT_LOCAL_SETTINGS;
  }
  const json = localStorage.getItem(LOCAL_SETTINGS_KEY);
  try {
    if (json) {
      const settings = JSON.parse(json) as Partial<LocalSettings>;
      return mergeLocalSettings(settings);
    }
  } catch {}
  return DEFAULT_LOCAL_SETTINGS;
}

export function saveLocalSettings(settings: LocalSettings) {
  if (!isBrowser()) {
    return;
  }
  localStorage.setItem(LOCAL_SETTINGS_KEY, JSON.stringify(settings));
}
