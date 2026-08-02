import { useCallback, useMemo, useSyncExternalStore } from "react";

import {
  DEFAULT_LOCAL_SETTINGS,
  applyThreadContextOverride,
  type LocalSettings,
} from "./local";
import {
  EMPTY_THREAD_CONTEXT,
  getBaseSettingsSnapshot,
  getThreadContextSnapshot,
  subscribe,
  updateLocalSettings,
  updateThreadSettings,
  type LocalSettingsSetter,
} from "./store";

export function useLocalSettings(): [LocalSettings, LocalSettingsSetter] {
  const settings = useSyncExternalStore(
    subscribe,
    getBaseSettingsSnapshot,
    () => DEFAULT_LOCAL_SETTINGS,
  );

  const setSettings = useCallback<LocalSettingsSetter>((key, value) => {
    updateLocalSettings(key, value);
  }, []);

  return [settings, setSettings];
}

export function useThreadSettings(
  threadId: string,
): [LocalSettings, LocalSettingsSetter] {
  const baseSettings = useSyncExternalStore(
    subscribe,
    getBaseSettingsSnapshot,
    () => DEFAULT_LOCAL_SETTINGS,
  );

  const threadContext = useSyncExternalStore(
    subscribe,
    () => getThreadContextSnapshot(threadId),
    () => EMPTY_THREAD_CONTEXT,
  );

  // The thread's own workflow selection (model / subagent model / mode /
  // reasoning effort) overrides the shared base settings, so two conversations
  // open at once each keep their own model.
  const settings = useMemo(
    () => applyThreadContextOverride(baseSettings, threadContext),
    [baseSettings, threadContext],
  );

  const setSettings = useCallback<LocalSettingsSetter>(
    (key, value) => {
      updateThreadSettings(threadId, key, value);
    },
    [threadId],
  );

  return [settings, setSettings];
}
