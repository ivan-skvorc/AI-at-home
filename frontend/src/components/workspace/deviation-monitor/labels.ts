import type { Translations } from "@/core/i18n/locales/types";
import type { Model } from "@/core/models/types";
import type { DeviationMonitorCadence } from "@/core/threads/deviation-monitor";

/** "every 3 steps", "every turn", in the UI language. */
export function cadenceSummary(
  t: Translations,
  cadence: DeviationMonitorCadence,
): string {
  return cadence.mode === "steps"
    ? t.deviationMonitor.everySteps(cadence.every)
    : t.deviationMonitor.everyTurns(cadence.every);
}

/**
 * A model's display name for the monitor surfaces. No name means the chat's
 * own model (a chat seeded from that Settings default); a name no longer
 * configured is shown as the raw name rather than hidden.
 */
export function monitorModelLabel(
  t: Translations,
  models: readonly Model[],
  modelName: string | null | undefined,
): string {
  if (!modelName) return t.deviationMonitor.chatModel;
  return (
    models.find((model) => model.name === modelName)?.display_name ?? modelName
  );
}
