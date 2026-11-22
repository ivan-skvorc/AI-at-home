"use client";

import { useEffect } from "react";

import { useDeviationMonitorFeature } from "@/core/features/deviation-monitor";
import { useLocalSettings } from "@/core/settings";
import {
  getThreadContextSnapshot,
  updateThreadSettings,
} from "@/core/settings/store";
import { newChatDeviationMonitorSeed } from "@/core/threads/deviation-monitor";

/**
 * Apply Settings → Deviation monitor to a chat when it starts.
 *
 * Written into the new chat's own override, the same record the composer
 * button writes, so everything downstream treats it as this chat's choice: the
 * button shows it, the first run sends it, `copyThreadContextOverride` carries
 * it onto the real thread id, and the user can turn it off for this chat
 * alone. Deriving it at read time instead would lose it at that promotion and
 * would put it into the composer's automatic context reports.
 *
 * Only a still-new chat with no monitor choice of its own is seeded, and only
 * while the operator offers the feature; an existing conversation never picks
 * the default up.
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
  const defaults = settings.deviationMonitor;

  useEffect(() => {
    if (!enabled || !featureEnabled) return;
    const seed = newChatDeviationMonitorSeed({
      isNewThread,
      override: getThreadContextSnapshot(threadId),
      defaults,
    });
    if (seed) {
      updateThreadSettings(threadId, "context", { deviation_monitor: seed });
    }
  }, [defaults, enabled, featureEnabled, isNewThread, threadId]);
}
