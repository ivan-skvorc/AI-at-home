"use client";

import { useId } from "react";

import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";
import {
  DEVIATION_MONITOR_CADENCE_BOUNDS,
  cadenceChoiceOf,
  cadenceFromChoice,
  type CadenceInputResult,
  type DeviationMonitorCadence,
  type DeviationMonitorCadenceChoice,
} from "@/core/threads/deviation-monitor";
import { cn } from "@/lib/utils";

/** The field's own state: the choice, and the number as typed. */
export interface CadenceDraft {
  choice: DeviationMonitorCadenceChoice;
  /** Raw text of the number input, so a half-typed value is not lost. */
  every: string;
}

const CHOICES: readonly DeviationMonitorCadenceChoice[] = [
  "steps",
  "turns",
  "everyTurn",
];

export function validateCadenceDraft(draft: CadenceDraft): CadenceInputResult {
  return cadenceFromChoice(draft.choice, draft.every);
}

export function cadenceDraftOf(cadence: DeviationMonitorCadence): CadenceDraft {
  return { choice: cadenceChoiceOf(cadence), every: String(cadence.every) };
}

/**
 * The cadence choice, shared by the composer dialog and Settings so the two
 * cannot disagree about the bounds: every X steps (1-50), every N turns
 * (1-20), or every turn. The number is validated as typed and the error is
 * tied to the input; the caller decides what an invalid draft blocks.
 */
export function DeviationMonitorCadenceField({
  value,
  onChange,
  disabled,
  legend,
}: {
  value: CadenceDraft;
  onChange: (next: CadenceDraft) => void;
  disabled?: boolean;
  legend: string;
}) {
  const { t } = useI18n();
  const copy = t.deviationMonitor;
  const baseId = useId();
  const result = validateCadenceDraft(value);
  const errorId = `${baseId}-error`;
  const error =
    "error" in result
      ? result.error === "notInteger"
        ? copy.notInteger
        : copy.outOfRange(result.min, result.max)
      : null;

  const label = (choice: DeviationMonitorCadenceChoice) =>
    choice === "steps"
      ? copy.cadenceSteps
      : choice === "turns"
        ? copy.cadenceTurns
        : copy.cadenceEveryTurn;
  const hint = (choice: DeviationMonitorCadenceChoice) =>
    choice === "steps"
      ? copy.cadenceStepsHint
      : choice === "turns"
        ? copy.cadenceTurnsHint
        : copy.cadenceEveryTurnHint;

  return (
    <fieldset
      className="flex flex-col gap-2"
      disabled={disabled}
      data-testid="deviation-monitor-cadence"
    >
      <legend className="mb-2 text-sm font-medium">{legend}</legend>
      {CHOICES.map((choice) => {
        const selected = value.choice === choice;
        const withNumber = choice !== "everyTurn";
        const bounds = withNumber
          ? DEVIATION_MONITOR_CADENCE_BOUNDS[choice]
          : null;
        return (
          <div
            key={choice}
            className={cn(
              "flex flex-col gap-2 rounded-lg border p-3 text-sm transition-colors",
              selected && "border-ring bg-accent/40",
            )}
          >
            <label className="flex cursor-pointer items-start gap-2">
              <input
                type="radio"
                name={`${baseId}-cadence`}
                value={choice}
                checked={selected}
                onChange={() => onChange({ ...value, choice })}
                className="accent-primary mt-0.5 size-4 shrink-0"
                data-testid={`deviation-monitor-cadence-${choice}`}
              />
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="font-medium">{label(choice)}</span>
                <span className="text-muted-foreground text-xs">
                  {hint(choice)}
                </span>
              </span>
            </label>
            {selected && bounds && (
              <div className="flex flex-col gap-1 pl-6">
                <label className="sr-only" htmlFor={`${baseId}-every`}>
                  {choice === "steps"
                    ? copy.stepsInputLabel
                    : copy.turnsInputLabel}
                </label>
                <Input
                  id={`${baseId}-every`}
                  type="number"
                  inputMode="numeric"
                  min={bounds.min}
                  max={bounds.max}
                  step={1}
                  className="h-8 w-24"
                  value={value.every}
                  aria-invalid={error !== null}
                  aria-describedby={error ? errorId : undefined}
                  onChange={(event) =>
                    onChange({ ...value, every: event.target.value })
                  }
                  data-testid="deviation-monitor-every"
                />
                {error && (
                  <p
                    id={errorId}
                    role="alert"
                    className="text-destructive text-xs"
                    data-testid="deviation-monitor-every-error"
                  >
                    {error}
                  </p>
                )}
              </div>
            )}
          </div>
        );
      })}
    </fieldset>
  );
}
