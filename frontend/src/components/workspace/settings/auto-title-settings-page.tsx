"use client";

import { Switch } from "@/components/ui/switch";
import { ModelSelect } from "@/components/workspace/model-select";
import { useAutoTitleCapability } from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { useLocalSettings } from "@/core/settings";

import { SettingsSection } from "./settings-section";

// Picker sentinels. The stored preference has three states and a picker row
// needs a non-empty value for each, so both "no opinion" and "no model call"
// get one. They are deliberately not interchangeable: FOLLOW_SERVER stores
// `undefined` (the backend keeps config.yaml's model), NO_MODEL stores `""`
// (the backend clears it, so the title is the truncated first message).
const FOLLOW_SERVER = "__follow_server__";
const NO_MODEL = "__no_model__";

export function AutoTitleSettingsPage() {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();
  const { models } = useModels();
  const { enabled: serverEnabled, modelName: serverModelName } =
    useAutoTitleCapability();

  const enabled = settings.autoTitle.enabled;
  const modelName = settings.autoTitle.modelName;

  let selectValue: string;
  if (modelName === undefined) {
    selectValue = FOLLOW_SERVER;
  } else if (modelName === "") {
    selectValue = NO_MODEL;
  } else {
    // A model that has since been removed from config.yaml must not leave the
    // picker showing a value the backend will silently drop.
    selectValue = models.some((m) => m.name === modelName)
      ? modelName
      : FOLLOW_SERVER;
  }

  const handleToggle = (next: boolean) => {
    setSettings("autoTitle", { enabled: next });
  };

  const handleModelChange = (value: string) => {
    setSettings("autoTitle", {
      modelName:
        value === FOLLOW_SERVER ? undefined : value === NO_MODEL ? "" : value,
    });
  };

  return (
    <SettingsSection
      title={t.settings.autoTitle.title}
      description={
        <div className="flex items-center gap-2">
          <div>{t.settings.autoTitle.description}</div>
          <div>
            <Switch
              aria-label={t.settings.autoTitle.title}
              disabled={!serverEnabled}
              checked={serverEnabled && enabled}
              onCheckedChange={handleToggle}
            />
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {!serverEnabled && (
          <p className="text-muted-foreground rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/50">
            {t.settings.autoTitle.serverDisabledHint}
          </p>
        )}

        {serverEnabled && enabled && (
          <div className="flex flex-col gap-2">
            <div className="text-sm font-medium">
              {t.settings.autoTitle.modelLabel}
            </div>
            <ModelSelect
              className="max-w-sm"
              models={models}
              value={selectValue}
              onChange={handleModelChange}
              options={[
                {
                  value: FOLLOW_SERVER,
                  label: t.settings.autoTitle.followServer,
                  description: serverModelName
                    ? t.settings.autoTitle.followServerModel(serverModelName)
                    : t.settings.autoTitle.followServerFallback,
                },
                {
                  value: NO_MODEL,
                  label: t.settings.autoTitle.noModel,
                  description: t.settings.autoTitle.noModelHint,
                },
              ]}
            />
            <p className="text-muted-foreground text-xs">
              {t.settings.autoTitle.modelHint}
            </p>
          </div>
        )}

        <p className="text-muted-foreground text-xs">
          {t.settings.autoTitle.timingHint}
        </p>
      </div>
    </SettingsSection>
  );
}
