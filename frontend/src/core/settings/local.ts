import type { TokenUsageInlineMode } from "../messages/usage-model";
import {
  DEFAULT_MODEL_PICKER_PREFS,
  type ModelPickerPrefs,
} from "../models/sorting";
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
  // Automatic conversation renaming after the first exchange. ON by default, so
  // a fresh install behaves as it did before the switch existed; `modelName`
  // undefined means "whatever config.yaml -> title.model_name says" (null there
  // = the free local fallback title, which is the shipped default).
  autoTitle: {
    enabled: true,
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
  // Per-browser model-picker preference (sort key/direction + group-by-provider
  // toggle). Defaults to config order, ungrouped, so the picker looks unchanged
  // until the user opts into sorting/grouping.
  modelPicker: DEFAULT_MODEL_PICKER_PREFS,
  context: {
    model_name: undefined,
    mode: undefined,
    reasoning_effort: undefined,
    // The internet is ON by default — this is an opt-out, not an opt-in, so a
    // fresh install behaves exactly as it did before the switch existed. It is
    // stored per conversation (see THREAD_SCOPED_CONTEXT_KEYS): taking one chat
    // offline must not silently unplug every other open chat.
    internet_enabled: true,
  },
};

export const LOCAL_SETTINGS_KEY = "deerflow.local-settings";
// Per-conversation workflow selection (model, subagent model, mode, reasoning
// effort) is persisted per thread under this prefix so concurrent conversations
// stay independent: selecting a model in one open chat must never change the
// model selected in another. This is deliberately NOT stored in the shared
// `deerflow.local-settings` blob, which every thread reads — writing the model
// there is exactly what used to leak a selection across chats (and across tabs
// via the `storage` event).
export const THREAD_CONTEXT_KEY_PREFIX = "deerflow.thread-context.";
// Legacy key that stored only the model name per thread. Read once for
// migration so a user's currently-pinned model survives the upgrade; never
// written to anymore.
const LEGACY_THREAD_MODEL_KEY_PREFIX = "deerflow.thread-model.";

// The context fields that are scoped per conversation. Everything else in
// `context` (e.g. `agent_name`, which is fixed by the route) stays out of the
// per-thread override.
export const THREAD_SCOPED_CONTEXT_KEYS = [
  "model_name",
  "subagent_model_name",
  // The Democracy panel is per conversation, like the model it runs on: two open
  // panels must not overwrite each other's rosters.
  "democracy_participants",
  "democracy_grading",
  "mode",
  "reasoning_effort",
  // The internet switch is per conversation for the same reason the model is:
  // an offline chat and a browsing chat are two different workflows the user is
  // running side by side.
  "internet_enabled",
] as const;

export type ThreadContextOverride = Partial<
  Pick<LocalSettings["context"], (typeof THREAD_SCOPED_CONTEXT_KEYS)[number]>
>;

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

/**
 * Best-effort localStorage facade.
 *
 * Safari private mode, Firefox strict containers, some embedded WebViews, and
 * quotas already filled by sibling tabs throw ``SecurityError`` or
 * ``QuotaExceededError`` from ``getItem``/``setItem``. Without a guard those
 * exceptions bubble into React render handlers and break the composer /
 * settings panel. This wrapper traps every storage exception so callers can
 * always fall back to a sane default.
 */
export const safeLocalStorage = {
  getItem(key: string): string | null {
    if (!isBrowser()) return null;
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem(key: string, value: string): boolean {
    if (!isBrowser()) return false;
    try {
      window.localStorage.setItem(key, value);
      return true;
    } catch {
      return false;
    }
  },
  removeItem(key: string): boolean {
    if (!isBrowser()) return false;
    try {
      window.localStorage.removeItem(key);
      return true;
    } catch {
      return false;
    }
  },
};

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
  autoTitle: {
    // Whether a conversation is renamed automatically after its first exchange.
    // Sent to the backend as the per-run `auto_title_enabled` flag; `false`
    // stops the run from writing a title. Combined (logical AND) with the
    // operator master switch `title.enabled` in config.yaml.
    enabled: boolean;
    // Which model writes the title. `undefined` = follow the operator's
    // `title.model_name`; `""` = rename without a model call (truncate the
    // first message); a name = that model. The three states are distinct on
    // purpose — see FORK.md §33.
    modelName?: string | undefined;
  };
  memory: {
    // Whether long-term memory is used for this user. Sent to the backend as the
    // per-run `memory_enabled` flag; when false the backend skips memory
    // injection/extraction/tools for the run. Combined (logical AND) with the
    // operator master switch `memory.enabled` in config.yaml.
    enabled: boolean;
  };
  // How the model dropdown orders/groups its entries (fork feature). Per browser,
  // shared across threads. See `core/models/sorting.ts`.
  modelPicker: ModelPickerPrefs;
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
    mode: "flash" | "thinking" | "pro" | "ultra" | "democracy" | undefined;
    reasoning_effort?: "minimal" | "low" | "medium" | "high";
    // Per-conversation internet switch (fork feature, FORK.md §27). Sent to the
    // backend in the run context; `false` strips every internet-reaching tool
    // from the run.
    internet_enabled?: boolean;
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
    autoTitle: {
      ...DEFAULT_LOCAL_SETTINGS.autoTitle,
      ...settings?.autoTitle,
    },
    memory: {
      ...DEFAULT_LOCAL_SETTINGS.memory,
      ...settings?.memory,
    },
    modelPicker: {
      ...DEFAULT_LOCAL_SETTINGS.modelPicker,
      ...settings?.modelPicker,
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

function getThreadContextStorageKey(threadId: string): string {
  return `${THREAD_CONTEXT_KEY_PREFIX}${threadId}`;
}

/**
 * Narrow an arbitrary context patch to only the per-conversation workflow keys.
 * A key present with an `undefined` value is kept (it means "clear this
 * override", e.g. the subagent model going back to "follow lead").
 */
export function pickThreadScopedContext(
  value: Partial<LocalSettings["context"]>,
): ThreadContextOverride {
  const out: ThreadContextOverride = {};
  for (const key of THREAD_SCOPED_CONTEXT_KEYS) {
    if (Object.prototype.hasOwnProperty.call(value, key)) {
      // Copy across the picked union; the source and target key sets match.
      (out as Record<string, unknown>)[key] = value[key];
    }
  }
  return out;
}

export function getThreadContextOverride(
  threadId: string,
): ThreadContextOverride {
  if (!isBrowser()) {
    return {};
  }
  const raw = safeLocalStorage.getItem(getThreadContextStorageKey(threadId));
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (parsed && typeof parsed === "object") {
        return pickThreadScopedContext(
          parsed as Partial<LocalSettings["context"]>,
        );
      }
    } catch {}
    return {};
  }
  // Migration: fall back to the legacy model-only per-thread key so a chat that
  // already had a pinned model keeps it after the upgrade.
  const legacyModel = safeLocalStorage.getItem(
    `${LEGACY_THREAD_MODEL_KEY_PREFIX}${threadId}`,
  );
  return legacyModel ? { model_name: legacyModel } : {};
}

export function saveThreadContextOverride(
  threadId: string,
  override: ThreadContextOverride,
) {
  if (!isBrowser()) {
    return;
  }
  const key = getThreadContextStorageKey(threadId);
  // Persist only defined values; an override with nothing left to store is
  // removed so a reset chat falls back cleanly to the app default.
  const persisted = Object.fromEntries(
    Object.entries(override).filter(([, v]) => v !== undefined),
  );
  if (Object.keys(persisted).length === 0) {
    safeLocalStorage.removeItem(key);
    return;
  }
  safeLocalStorage.setItem(key, JSON.stringify(persisted));
}

/**
 * Carry a conversation's per-thread workflow selection onto a thread forked
 * from it.
 *
 * Editing a message branches the conversation into a *new thread id*, and every
 * per-conversation key — the model above all — is stored under that id. Without
 * this the fork reads no override and falls back to the app defaults, so
 * editing a message silently moves the conversation onto a different model
 * (and mode, reasoning effort, internet switch, and Democracy panel) than the
 * turn it is replacing.
 *
 * Copying rather than sharing keeps the two threads independent afterwards:
 * changing the model in the version must not reach back into its parent.
 */
export function copyThreadContextOverride(
  sourceThreadId: string,
  targetThreadId: string,
) {
  if (!isBrowser() || !sourceThreadId || !targetThreadId) {
    return;
  }
  if (sourceThreadId === targetThreadId) {
    return;
  }
  saveThreadContextOverride(
    targetThreadId,
    getThreadContextOverride(sourceThreadId),
  );
}

export function applyThreadContextOverride(
  settings: LocalSettings,
  override: ThreadContextOverride,
): LocalSettings {
  return {
    ...settings,
    context: {
      ...settings.context,
      ...override,
    },
  };
}

export function getLocalSettings(): LocalSettings {
  if (!isBrowser()) {
    return DEFAULT_LOCAL_SETTINGS;
  }
  const json = safeLocalStorage.getItem(LOCAL_SETTINGS_KEY);
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
  safeLocalStorage.setItem(LOCAL_SETTINGS_KEY, JSON.stringify(settings));
}
