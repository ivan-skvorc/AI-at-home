"use client";

import { Switch } from "@/components/ui/switch";
import { ModelSelect } from "@/components/workspace/model-select";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { useLocalSettings } from "@/core/settings";
import { useSuggestionsConfig } from "@/core/suggestions/hooks";

import { SettingsSection } from "./settings-section";

// Sentinel picker value for "follow the workflow's selected model": the stored
// preference is `undefined`, and a picker row needs a non-empty value.
const FOLLOW_WORKFLOW = "__follow_workflow__";

export function SuggestionsSettingsPage() {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();
  const { models } = useModels();
  const { data: suggestionsConfig } = useSuggestionsConfig();

  // Operator master switch (config.yaml → suggestions.enabled). When off, the
  // server returns no suggestions regardless of the per-user toggle.
  const serverEnabled = suggestionsConfig?.enabled ?? true;
  const enabled = settings.suggestions.enabled;
  const modelName = settings.suggestions.modelName;
  const modelExists = modelName
    ? models.some((m) => m.name === modelName)
    : false;
  const selectValue = modelName && modelExists ? modelName : FOLLOW_WORKFLOW;

  const handleToggle = (next: boolean) => {
    setSettings("suggestions", { enabled: next });
  };

  const handleModelChange = (value: string) => {
    setSettings("suggestions", {
      modelName: value === FOLLOW_WORKFLOW ? undefined : value,
    });
  };

  return (
    <SettingsSection
      title={t.settings.suggestions.title}
      description={
        <div className="flex items-center gap-2">
          <div>{t.settings.suggestions.description}</div>
          <div>
            <Switch
              aria-label={t.settings.suggestions.title}
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
            {t.settings.suggestions.serverDisabledHint}
          </p>
        )}

        {serverEnabled && enabled && (
          <div className="flex flex-col gap-2">
            <div className="text-sm font-medium">
              {t.settings.suggestions.modelLabel}
            </div>
            <ModelSelect
              className="max-w-sm"
              models={models}
              value={selectValue}
              onChange={handleModelChange}
              options={[
                {
                  value: FOLLOW_WORKFLOW,
                  label: t.settings.suggestions.followWorkflow,
                },
              ]}
            />
            <p className="text-muted-foreground text-xs">
              {t.settings.suggestions.modelHint}
            </p>
          </div>
        )}
      </div>
    </SettingsSection>
  );
}
