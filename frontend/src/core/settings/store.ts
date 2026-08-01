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

function emitChange() {
  for (const listener of listeners) {
    listener();
  }
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
  return {
    ...settings,
    [key]: {
      ...settings[key],
      ...value,
    },
  } as LocalSettings;
}

function handleStorage(event: StorageEvent) {
  if (event.storageArea && event.storageArea !== localStorage) {
    return;
  }

  ensureBaseSettingsLoaded();

  if (event.key === null) {
    baseSettings = getLocalSettings();
    threadContextOverrides.clear();
    emitChange();
    return;
  }

  if (event.key === LOCAL_SETTINGS_KEY) {
    baseSettings = getLocalSettings();
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

export const updateLocalSettings: LocalSettingsSetter = (key, value) => {
  ensureBaseSettingsLoaded();
  ensureStorageListenerRegistered();

  baseSettings = mergeSettingsSection(baseSettings, key, value);
  saveLocalSettings(baseSettings);
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
    // selection (same tab or, via the `storage` event, another tab).
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

  baseSettings = mergeSettingsSection(baseSettings, key, value);
  saveLocalSettings(baseSettings);
  emitChange();
}
