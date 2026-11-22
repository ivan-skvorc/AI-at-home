"use client";

import { CompassIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PromptInputButton } from "@/components/ai-elements/prompt-input";
import { Tooltip } from "@/components/workspace/tooltip";
import { useDeviationMonitorFeature } from "@/core/features/deviation-monitor";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { useLocalSettings } from "@/core/settings";
import {
  normalizeDeviationMonitorSetting,
  type DeviationMonitorChatSetting,
} from "@/core/threads/deviation-monitor";
import { cn } from "@/lib/utils";

import { DeviationMonitorDialog } from "./deviation-monitor-dialog";
import { cadenceSummary, monitorModelLabel } from "./labels";

/**
 * The composer's deviation monitor button (fork feature).
 *
 * Off: clicking opens the setup dialog, and Save turns the monitor on for this
 * chat. On: clicking reopens the dialog to change the model or cadence or to
 * turn it off; the status bar above the composer turns it off in one click.
 * Hidden entirely while `/api/features` does not report the operator switch
 * on, so a server that will not run the monitor never offers it.
 *
 * It publishes `data-slot="deviation-monitor"` and `data-state="on|off"`:
 * specs find it by that contract, never by the ARIA role of the button
 * primitive underneath (the model-picker lesson, FORK.md §8).
 */
export function DeviationMonitorControl({
  setting: storedSetting,
  chatModelName,
  disabled,
  onChange,
}: {
  /** The chat's stored choice, as read from its context (unvalidated). */
  setting: unknown;
  chatModelName: string | undefined;
  disabled?: boolean;
  onChange: (setting: DeviationMonitorChatSetting) => void;
}) {
  const { t } = useI18n();
  const copy = t.deviationMonitor;
  const { enabled: featureEnabled } = useDeviationMonitorFeature();
  const { models } = useModels();
  const [settings] = useLocalSettings();
  const [open, setOpen] = useState(false);

  if (!featureEnabled) {
    return null;
  }

  const setting = normalizeDeviationMonitorSetting(storedSetting);
  const isOn = setting?.enabled === true;
  const tooltip =
    isOn && setting
      ? copy.tooltipOn(
          monitorModelLabel(t, models, setting.model),
          cadenceSummary(t, setting.cadence),
        )
      : copy.tooltipOff;

  return (
    <>
      <Tooltip content={<span className="block max-w-72">{tooltip}</span>}>
        <PromptInputButton
          aria-label={isOn ? copy.buttonOn : copy.buttonOff}
          aria-haspopup="dialog"
          className={cn("px-2!", isOn && "text-primary bg-primary/10")}
          data-slot="deviation-monitor"
          data-state={isOn ? "on" : "off"}
          data-testid="deviation-monitor-button"
          disabled={disabled}
          onClick={() => setOpen(true)}
        >
          <CompassIcon className="size-3" />
        </PromptInputButton>
      </Tooltip>
      <DeviationMonitorDialog
        open={open}
        onOpenChange={setOpen}
        models={models}
        setting={setting}
        defaultModelName={settings.deviationMonitor.modelName}
        defaultCadence={settings.deviationMonitor.cadence}
        chatModelName={chatModelName}
        onSave={(next) => {
          onChange(next);
          setOpen(false);
        }}
        onTurnOff={() => {
          if (setting) onChange({ ...setting, enabled: false });
          setOpen(false);
          toast.message(copy.turnedOff);
        }}
      />
    </>
  );
}
