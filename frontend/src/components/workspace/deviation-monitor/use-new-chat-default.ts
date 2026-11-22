"use client";

import { useEffect } from "react";

import { useDeviationMonitorFeature } from "@/core/features/deviation-monitor";
import { useModels } from "@/core/models/hooks";
import { useLocalSettings } from "@/core/settings";
import {
  getThreadContextSnapshot,
  seedThreadContext,
} from "@/core/settings/store";
import { newChatDeviationMonitorSeed } from "@/core/threads/deviation-monitor";

/**
 * Apply Settings → Deviation monitor to a chat when it starts.
 *
 * Seeded into the new chat's own override, the same record the composer
 * button writes, so everything downstream treats it as this chat's choice: the
 * button shows it, the first run sends it, `promoteThreadContext` saves it
 * under the real thread id, and the user can turn it off for this chat alone.
 * Deriving it at read time instead would lose it at that promotion and would
 * put it into the composer's automatic context reports. It is held in memory
 * (`seedThreadContext`) until then, so a new chat left without a message
 * leaves nothing in browser storage.
 *
 * Only a still-new chat with no monitor choice of its own is seeded, and only
 * while the operator offers the feature; an existing conversation never picks
 * the default up. A default model that left `config.yaml` is dropped once the
 * model list has loaded, so the chat follows its own model, as Settings shows.
 */
export function useDeviationMonitorNewChatDefault({
  threadId,
  isNewThread,
  enabled,
}: {
  threadId: string;
  isNewThread: boolean;
  /** False for background slots, mock threads and the static demo. */
  enabled: boolean;
}) {
  const [settings] = useLocalSettings();
  const { enabled: featureEnabled } = useDeviationMonitorFeature();
  const { models, isLoading: modelsLoading, error: modelsError } = useModels();
  const defaults = settings.deviationMonitor;
  // Wait for the roster before seeding a named model: a chat is seeded once,
  // and an empty list while it loads would wrongly drop the model. If the list
  // cannot be read, the stored default is used and the backend decides.
  const waitForModels = defaults.modelName !== undefined && modelsLoading;
  const defaultModelGone =
    defaults.modelName !== undefined &&
    !modelsLoading &&
    !modelsError &&
    !models.some((model) => model.name === defaults.modelName);

  useEffect(() => {
    if (!enabled || !featureEnabled || waitForModels) return;
    const seed = newChatDeviationMonitorSeed({
      isNewThread,
      override: getThreadContextSnapshot(threadId),
      defaults,
      configuredModels: defaultModelGone ? [] : undefined,
    });
    if (seed) {
      seedThreadContext(threadId, { deviation_monitor: seed });
    }
  }, [
    defaultModelGone,
    defaults,
    enabled,
    featureEnabled,
    isNewThread,
    threadId,
    waitForModels,
  ]);
}
