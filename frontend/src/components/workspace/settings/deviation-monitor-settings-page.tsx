"use client";

import { useState } from "react";

import { Switch } from "@/components/ui/switch";
import {
  DeviationMonitorCadenceField,
  cadenceDraftOf,
  validateCadenceDraft,
  type CadenceDraft,
} from "@/components/workspace/deviation-monitor/cadence-field";
import { ModelSelect } from "@/components/workspace/model-select";
import { useDeviationMonitorFeature } from "@/core/features/deviation-monitor";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { useLocalSettings } from "@/core/settings";

import { SettingsSection } from "./settings-section";

// Picker sentinel for "the chat's own model": the stored default is
// `undefined`, and a picker row needs a non-empty value.
const CHAT_MODEL = "__chat_model__";

/**
 * Settings → Deviation monitor (fork feature): what a new chat starts with.
 *
 * Per browser, in `LocalSettings.deviationMonitor`, like the other per-user
 * defaults on these pages. It never reaches a run directly: a new chat copies
 * it into its own per-conversation choice when it starts
 * (`useDeviationMonitorNewChatDefault`), so changing it here leaves every
 * existing chat as it is.
 */
export function DeviationMonitorSettingsPage() {
  const { t } = useI18n();
  const copy = t.settings.deviationMonitor;
  const [settings, setSettings] = useLocalSettings();
  const { models } = useModels();
  const { enabled: serverEnabled } = useDeviationMonitorFeature();
  const defaults = settings.deviationMonitor;
  // The typed number is kept locally so a half-typed value is not thrown
  // away; only a valid cadence is saved.
  const [cadence, setCadence] = useState<CadenceDraft>(() =>
    cadenceDraftOf(defaults.cadence),
  );

  const modelName = defaults.modelName;
  // A default model that has since left config.yaml falls back to "the chat's
  // model" on screen, which is also what a new chat then uses.
  const selectValue =
    modelName && models.some((model) => model.name === modelName)
      ? modelName
      : CHAT_MODEL;

  const handleCadence = (next: CadenceDraft) => {
    setCadence(next);
    const result = validateCadenceDraft(next);
    if ("cadence" in result) {
      setSettings("deviationMonitor", { cadence: result.cadence });
    }
  };

  return (
    <SettingsSection title={copy.title} description={copy.description}>
      <div
        className="flex flex-col gap-6"
        data-testid="deviation-monitor-settings"
      >
        {!serverEnabled && (
          <p className="text-muted-foreground rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/50">
            {copy.serverDisabledHint}
          </p>
        )}
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <div className="text-sm font-medium">{copy.enableLabel}</div>
            <p className="text-muted-foreground text-xs">{copy.enableHint}</p>
          </div>
          <Switch
            aria-label={copy.enableLabel}
            checked={defaults.enabledForNewChats}
            disabled={!serverEnabled}
            onCheckedChange={(enabledForNewChats) =>
              setSettings("deviationMonitor", { enabledForNewChats })
            }
            data-testid="deviation-monitor-default-enabled"
          />
        </div>
        <div className="flex flex-col gap-2">
          <div className="text-sm font-medium">{copy.modelLabel}</div>
          <ModelSelect
            className="max-w-sm"
            models={models}
            value={selectValue}
            disabled={!serverEnabled}
            aria-label={copy.modelLabel}
            onChange={(value) =>
              setSettings("deviationMonitor", {
                modelName: value === CHAT_MODEL ? undefined : value,
              })
            }
            options={[
              {
                value: CHAT_MODEL,
                label: t.deviationMonitor.chatModel,
                description: copy.chatModelHint,
              },
            ]}
            data-testid="deviation-monitor-default-model"
          />
          <p className="text-muted-foreground text-xs">
            {t.deviationMonitor.modelHint}
          </p>
        </div>
        <div className="max-w-md">
          <DeviationMonitorCadenceField
            legend={copy.cadenceLabel}
            value={cadence}
            onChange={handleCadence}
            disabled={!serverEnabled}
          />
        </div>
      </div>
    </SettingsSection>
  );
}
