"use client";

import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ModelSelect } from "@/components/workspace/model-select";
import { useI18n } from "@/core/i18n/hooks";
import type { Model } from "@/core/models/types";
import {
  pickDeviationMonitorModel,
  type DeviationMonitorCadence,
  type DeviationMonitorChatSetting,
} from "@/core/threads/deviation-monitor";

import {
  DeviationMonitorCadenceField,
  cadenceDraftOf,
  validateCadenceDraft,
  type CadenceDraft,
} from "./cadence-field";

/**
 * The deviation monitor's setup dialog (fork feature).
 *
 * Turning the monitor on, or clicking it while on, opens this: the monitor's
 * model through the one shared `ModelSelect` (FORK.md §8 — sort, groups,
 * search and prices like every other picker), the cadence, and Save / Cancel.
 * While the chat's monitor is on it also offers Turn off.
 *
 * The model is required and preselected, never a "same as the chat" sentinel:
 * the owner wants the monitor's model to be a deliberate pick. The selection
 * is derived until the user picks, so a roster that arrives after the dialog
 * opened still preselects instead of leaving it empty.
 */
export function DeviationMonitorDialog({
  open,
  onOpenChange,
  models,
  setting,
  defaultModelName,
  defaultCadence,
  chatModelName,
  onSave,
  onTurnOff,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  models: readonly Model[];
  /** The chat's stored choice; on or off, or none yet. */
  setting: DeviationMonitorChatSetting | undefined;
  /** Settings → Deviation monitor's default model, if one is set. */
  defaultModelName: string | undefined;
  defaultCadence: DeviationMonitorCadence;
  chatModelName: string | undefined;
  onSave: (setting: DeviationMonitorChatSetting) => void;
  onTurnOff: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-md"
        data-testid="deviation-monitor-dialog"
      >
        {/* Mounted per opening, so Cancel discards the draft by construction. */}
        {open && (
          <DialogBody
            models={models}
            setting={setting}
            defaultModelName={defaultModelName}
            defaultCadence={defaultCadence}
            chatModelName={chatModelName}
            onCancel={() => onOpenChange(false)}
            onSave={onSave}
            onTurnOff={onTurnOff}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function DialogBody({
  models,
  setting,
  defaultModelName,
  defaultCadence,
  chatModelName,
  onCancel,
  onSave,
  onTurnOff,
}: {
  models: readonly Model[];
  setting: DeviationMonitorChatSetting | undefined;
  defaultModelName: string | undefined;
  defaultCadence: DeviationMonitorCadence;
  chatModelName: string | undefined;
  onCancel: () => void;
  onSave: (setting: DeviationMonitorChatSetting) => void;
  onTurnOff: () => void;
}) {
  const { t } = useI18n();
  const copy = t.deviationMonitor;
  const modelHintId = useId();
  const [pickedModel, setPickedModel] = useState<string | null>(null);
  const [cadence, setCadence] = useState<CadenceDraft>(() =>
    cadenceDraftOf(setting?.cadence ?? defaultCadence),
  );
  const isOn = setting?.enabled === true;

  const configured = models.map((model) => model.name);
  const model =
    pickedModel ??
    pickDeviationMonitorModel(configured, [
      setting?.model,
      defaultModelName,
      chatModelName,
    ]);
  const modelValid = model !== "" && configured.includes(model);
  const cadenceResult = validateCadenceDraft(cadence);
  const canSave = modelValid && "cadence" in cadenceResult;

  const save = () => {
    if (!modelValid || !("cadence" in cadenceResult)) return;
    onSave({ enabled: true, model, cadence: cadenceResult.cadence });
  };

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <DialogHeader>
        <DialogTitle>{copy.title}</DialogTitle>
        <DialogDescription>{copy.description}</DialogDescription>
      </DialogHeader>
      <div className="flex flex-col gap-2">
        <div className="text-sm font-medium">{copy.modelLabel}</div>
        <ModelSelect
          models={models}
          value={model}
          onChange={setPickedModel}
          aria-label={copy.modelLabel}
          aria-describedby={modelHintId}
          data-testid="deviation-monitor-model-select"
        />
        <p id={modelHintId} className="text-muted-foreground text-xs">
          {modelValid ? copy.modelHint : copy.modelRequired}
        </p>
      </div>
      <DeviationMonitorCadenceField
        legend={copy.cadenceLabel}
        value={cadence}
        onChange={setCadence}
      />
      <DialogFooter className="gap-2 sm:justify-between">
        {isOn ? (
          <Button
            type="button"
            variant="outline"
            onClick={onTurnOff}
            data-testid="deviation-monitor-turn-off"
          >
            {copy.turnOff}
          </Button>
        ) : (
          <span className="hidden sm:block" />
        )}
        <div className="flex flex-col-reverse gap-2 sm:flex-row">
          <Button
            type="button"
            variant="ghost"
            onClick={onCancel}
            data-testid="deviation-monitor-cancel"
          >
            {copy.cancel}
          </Button>
          <Button
            type="submit"
            disabled={!canSave}
            data-testid="deviation-monitor-save"
          >
            {isOn ? copy.save : copy.turnOn}
          </Button>
        </div>
      </DialogFooter>
    </form>
  );
}
