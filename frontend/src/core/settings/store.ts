import {
  DEFAULT_LOCAL_SETTINGS,
  LOCAL_SETTINGS_KEY,
  THREAD_CONTEXT_KEY_PREFIX,
  getLocalSettings,
  getThreadContextOverride,
  pickThreadScopedContext,
  saveLocalSettings,
  saveThreadContextOverride,
  type LocalSettings,
  type ThreadContextOverride,
} from "./local";
import type { Preferences } from "./preferences-sync";

type Listener = () => void;

export type LocalSettingsSetter = <K extends keyof LocalSettings>(
  key: K,
  value: Partial<LocalSettings[K]>,
) => void;

// Stable empty override reused for SSR / never-touched threads so
// useSyncExternalStore does not see a fresh reference on every render.
export const EMPTY_THREAD_CONTEXT: ThreadContextOverride = Object.freeze({});

const listeners = new Set<Listener>();
// Cached per-thread workflow-selection overrides. The stored object reference is
// only replaced when that thread's override actually changes, so a change to one
// thread never re-renders another thread's `useThreadSettings` subscriber.
const threadContextOverrides = new Map<string, ThreadContextOverride>();

let baseSettings: LocalSettings = DEFAULT_LOCAL_SETTINGS;
let baseSettingsLoaded = false;
let storageListenerRegistered = false;
let preferenceEdit:
  | ((before: LocalSettings, after: LocalSettings) => void)
  | undefined;

/** Activate only after the workspace has identified the account. */
export function activatePreferences(
  initial: Preferences,
  edit: (before: LocalSettings, after: LocalSettings) => void,
) {
  ensureBaseSettingsLoaded();
  preferenceEdit = edit;
  const apply = (value: Preferences) => {
    if (preferenceEdit !== edit) return;
    baseSettings = {
      ...baseSettings,
      notification: { enabled: value.notification_enabled ?? true },
      context: {
        ...baseSettings.context,
        model_name: value.model_name ?? undefined,
        mode: value.mode ?? undefined,
        reasoning_effort: value.reasoning_effort ?? undefined,
      },
    };
    emitChange();
  };
  apply(initial);
  return {
    apply,
    stop: () => {
      if (preferenceEdit === edit) {
        apply({});
        preferenceEdit = undefined;
      }
    },
  };
}

function emitChange() {
  for (const listener of listeners) {
    listener();
  }
}

function persistLocalOnlySettings() {
  if (!preferenceEdit) {
    saveLocalSettings(baseSettings);
    return;
  }
  // Account preferences never leak back into the legacy shared-origin key.
  const legacy = getLocalSettings();
  saveLocalSettings({
    ...baseSettings,
    notification: legacy.notification,
    context: {
      ...baseSettings.context,
      model_name: legacy.context.model_name,
      mode: legacy.context.mode,
      reasoning_effort: legacy.context.reasoning_effort,
    },
  });
}

function ensureBaseSettingsLoaded() {
  if (baseSettingsLoaded || typeof window === "undefined") {
    return;
  }

  baseSettings = getLocalSettings();
  baseSettingsLoaded = true;
}

function ensureStorageListenerRegistered() {
  if (storageListenerRegistered || typeof window === "undefined") {
    return;
  }

  window.addEventListener("storage", handleStorage);
  storageListenerRegistered = true;
}

function mergeSettingsSection<K extends keyof LocalSettings>(
  settings: LocalSettings,
  key: K,
  value: Partial<LocalSettings[K]>,
): LocalSettings {
  const current = settings[key];
  if (
    current !== null &&
    typeof current === "object" &&
    value !== null &&
    typeof value === "object"
  ) {
    return {
      ...settings,
      [key]: {
        ...current,
        ...value,
      },
    } as LocalSettings;
  }
  return {
    ...settings,
    [key]: value,
  };
}

function readSharedSettings(): LocalSettings {
  const local = getLocalSettings();
  if (!preferenceEdit) return local;
  // Device-local fields still follow other tabs, including key removal and
  // storage.clear(). The legacy key must never replace account preferences.
  return {
    ...local,
    notification: baseSettings.notification,
    context: {
      ...local.context,
      model_name: baseSettings.context.model_name,
      mode: baseSettings.context.mode,
      reasoning_effort: baseSettings.context.reasoning_effort,
    },
  };
}

function handleStorage(event: StorageEvent) {
  if (event.storageArea && event.storageArea !== localStorage) {
    return;
  }

  ensureBaseSettingsLoaded();

  if (event.key === null) {
    baseSettings = readSharedSettings();
    threadContextOverrides.clear();
    emitChange();
    return;
  }

  if (event.key === LOCAL_SETTINGS_KEY) {
    baseSettings = readSharedSettings();
    emitChange();
    return;
  }

  if (!event.key.startsWith(THREAD_CONTEXT_KEY_PREFIX)) {
    return;
  }

  const threadId = event.key.slice(THREAD_CONTEXT_KEY_PREFIX.length);
  threadContextOverrides.set(threadId, getThreadContextOverride(threadId));
  emitChange();
}

export function subscribe(listener: Listener): () => void {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();
  listeners.add(listener);

  return () => {
    listeners.delete(listener);
  };
}

export function getBaseSettingsSnapshot(): LocalSettings {
  ensureBaseSettingsLoaded();
  return baseSettings;
}

export function getThreadContextSnapshot(
  threadId: string,
): ThreadContextOverride {
  ensureBaseSettingsLoaded();

  if (!threadContextOverrides.has(threadId)) {
    threadContextOverrides.set(threadId, getThreadContextOverride(threadId));
  }

  return threadContextOverrides.get(threadId) ?? EMPTY_THREAD_CONTEXT;
}

/** The model this conversation has explicitly pinned, if any. */
export function getThreadModelSnapshot(threadId: string): string | undefined {
  return getThreadContextSnapshot(threadId).model_name;
}

export const updateLocalSettings: LocalSettingsSetter = (key, value) => {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();

  const previous = baseSettings;
  baseSettings = mergeSettingsSection(baseSettings, key, value);
  persistLocalOnlySettings();
  preferenceEdit?.(previous, baseSettings);
  emitChange();
};

export function updateThreadSettings<K extends keyof LocalSettings>(
  threadId: string,
  key: K,
  value: Partial<LocalSettings[K]>,
) {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();

  if (key === "context") {
    // Workflow selection is per conversation: merge the change into THIS
    // thread's own override and never touch the shared global base settings, so
    // changing the model/mode in one open chat cannot flip another open chat's
    // selection (same tab or, via the `storage` event, another tab). That is
    // also why it never calls `preferenceEdit`: every key in
    // THREAD_SCOPED_CONTEXT_KEYS is a per-conversation choice, so uploading it
    // as an account preference would make one chat's model the default for all
    // of them — on every device.
    const previous = threadContextOverrides.has(threadId)
      ? (threadContextOverrides.get(threadId) ?? EMPTY_THREAD_CONTEXT)
      : getThreadContextOverride(threadId);
    const nextOverride: ThreadContextOverride = {
      ...previous,
      ...pickThreadScopedContext(value as Partial<LocalSettings["context"]>),
    };
    threadContextOverrides.set(threadId, nextOverride);
    saveThreadContextOverride(threadId, nextOverride);
    emitChange();
    return;
  }

  // Anything outside `context` is a global setting that happens to have been
  // edited from a thread page, so it follows the same account-preference path
  // as `updateLocalSettings`.
  const previous = baseSettings;
  baseSettings = mergeSettingsSection(baseSettings, key, value);
  persistLocalOnlySettings();
  preferenceEdit?.(previous, baseSettings);
  emitChange();
}

/**
 * Model availability/default resolution is not an explicit choice — not an
 * account edit, and not this conversation's own selection either.
 *
 * A key the conversation already chose is repaired in its override (its model
 * may have been removed). Every other key lands in the in-memory base, which is
 * uploaded nowhere and persisted by nothing here, so anything better known
 * later still wins: the account preference when a slow GET arrives, or the
 * workflow the conversation recorded on another device (`deerflow_workflow`),
 * which `applyWorkflow` only adopts while the chat has no override of its own.
 * Pinning the fallback as an override — what passwordless mode, with no
 * account sync, used to do — made that record look like a local choice, so it
 * was refused, and the next edit PATCHed the fallback over it.
 */
export function resolveThreadContext(
  threadId: string,
  context: Partial<LocalSettings["context"]>,
) {
  ensureBaseSettingsLoaded();
  const existing = getThreadContextSnapshot(threadId);
  const resolved = pickThreadScopedContext(context);
  const updates: Record<string, unknown> = {};
  const baseUpdates: Record<string, unknown> = { ...context };
  for (const key of Object.keys(resolved)) {
    if (Object.prototype.hasOwnProperty.call(existing, key)) {
      updates[key] = (resolved as Record<string, unknown>)[key];
      // The caller reports the chat's whole effective context, its overrides
      // included; merging those into the base would hand one chat's choices
      // (an offline switch, a Democracy roster) to every other chat.
      delete baseUpdates[key];
    }
  }
  baseSettings = mergeSettingsSection(
    baseSettings,
    "context",
    baseUpdates as Partial<LocalSettings["context"]>,
  );
  if (Object.keys(updates).length > 0) {
    const nextOverride: ThreadContextOverride = { ...existing, ...updates };
    threadContextOverrides.set(threadId, nextOverride);
    saveThreadContextOverride(threadId, nextOverride);
  }
  emitChange();
}
