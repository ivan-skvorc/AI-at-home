"use client";

import { CheckIcon, ChevronDownIcon } from "lucide-react";
import { type ReactNode, useState } from "react";

import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorEmpty,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "@/components/ai-elements/model-selector";
import { useI18n } from "@/core/i18n/hooks";
import type { Model } from "@/core/models/types";
import { useLocalSettings } from "@/core/settings";
import { cn } from "@/lib/utils";

import {
  ModelDisplayName,
  ModelPickerControls,
  ModelPickerList,
} from "./model-picker-controls";

/**
 * A pinned pseudo-option that is not a model: "Follow lead", "Use the default
 * model", "Inherit from the workflow". Every picker in the app has one, and it
 * must stay above the models regardless of sort or grouping — it is the
 * *absence* of a choice, so sorting it in among the models by name or price
 * would be meaningless.
 */
export interface ModelSelectOption {
  /** The value reported to `onChange` when this row is picked. */
  value: string;
  label: string;
  /** Optional second line, e.g. what "follow the lead model" resolves to. */
  description?: string;
}

/**
 * The one model picker (fork feature, FORK.md §8).
 *
 * The chat composer's picker grew sort-by-name/price, group-by-provider, a
 * search box and colour-coded prices; every *other* place a model is chosen —
 * democracy panelists, the suggestions model, the subagent default, the agent
 * generator, a custom agent's own model — kept a bare `<Select>` listing
 * `config.yaml` order with the price as undifferentiated grey text. With a
 * couple of dozen bundled models that is the difference between picking a model
 * and hunting for one, and the inconsistency is itself the bug: the same roster
 * behaved differently depending on which screen you opened it from.
 *
 * This component is that picker, extracted. It renders the identical
 * `ModelPickerControls` + `ModelPickerList` the composer uses, reads and writes
 * the same per-browser `modelPicker` preference (so a sort chosen in the chat is
 * already applied in settings), and paints prices through the same
 * `ModelDisplayName`. Anything that selects a model should use it rather than
 * mapping `models` into `SelectItem`s — a new flat list is how the two
 * behaviours drift apart again.
 *
 * It is built on `ModelSelector` (a Dialog + cmdk `Command`), the same
 * primitive as the composer's picker, which is what makes the two visually
 * identical. That also means it nests safely inside the settings dialog and the
 * agent dialog, both of which already stack Radix dialogs.
 */
export function ModelSelect({
  models,
  value,
  onChange,
  options = [],
  placeholder,
  disabled,
  className,
  demoteLast,
  annotate,
  id,
  "data-testid": dataTestId,
}: {
  models: readonly Model[];
  /** Selected model `name`, or one of `options`' values. */
  value: string | null | undefined;
  onChange: (value: string) => void;
  /** Pseudo-options pinned above the models (see `ModelSelectOption`). */
  options?: readonly ModelSelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  /** Keep matching models at the bottom (e.g. models with no tool support). */
  demoteLast?: (model: Model) => boolean;
  /** Optional annotation rendered after a model's name in the list. */
  annotate?: (model: Model) => ReactNode;
  id?: string;
  "data-testid"?: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [localSettings, setLocalSettings] = useLocalSettings();

  const selectedOption = options.find((option) => option.value === value);
  const selectedModel = models.find((model) => model.name === value);

  const select = (next: string) => {
    onChange(next);
    setOpen(false);
  };

  return (
    <ModelSelector open={open} onOpenChange={setOpen}>
      <ModelSelectorTrigger asChild>
        <button
          type="button"
          id={id}
          disabled={disabled}
          data-testid={dataTestId}
          // The stable hook every test targets a model picker through.
          //
          // It exists because the alternative already broke: e2e specs used to
          // find these pickers by `getByRole("combobox")`, which is the ARIA
          // role of whatever primitive happens to be underneath — Radix
          // `Select` at the time. Swapping the primitive for this dialog + cmdk
          // picker deleted that role, and every spec driving a picker failed
          // with a 30s timeout on a locator that no longer matched anything.
          // `data-slot` is this component's *own* contract: it survives any
          // future re-implementation, so a spec written against it does not
          // have to know what the picker is built from.
          data-slot="model-select"
          // Matches `SelectTrigger` so a picker swapped in beside other form
          // controls does not read as a different kind of control.
          className={cn(
            "border-input dark:bg-input/30 dark:hover:bg-input/50 focus-visible:border-ring focus-visible:ring-ring/50 flex h-9 w-full cursor-pointer items-center justify-between gap-2 rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs transition-[color,box-shadow] outline-none focus-visible:ring-[3px] disabled:cursor-not-allowed disabled:opacity-50",
            className,
          )}
        >
          <ModelSelectorName className="w-full text-sm font-normal">
            {selectedOption ? (
              selectedOption.label
            ) : selectedModel ? (
              <ModelDisplayName
                displayName={selectedModel.display_name}
                price={selectedModel.price}
                variant="compact"
              />
            ) : (
              <span className="text-muted-foreground">
                {placeholder ?? t.inputBox.searchModels}
              </span>
            )}
          </ModelSelectorName>
          <ChevronDownIcon className="text-muted-foreground size-4 shrink-0" />
        </button>
      </ModelSelectorTrigger>
      <ModelSelectorContent>
        <ModelSelectorInput placeholder={t.inputBox.searchModels} />
        <ModelPickerControls
          prefs={localSettings.modelPicker}
          onChange={(next) => setLocalSettings("modelPicker", next)}
        />
        <ModelSelectorEmpty>{t.inputBox.noModelsFound}</ModelSelectorEmpty>
        <ModelPickerList
          models={models}
          prefs={localSettings.modelPicker}
          demoteLast={demoteLast}
          leading={options.map((option) => (
            <ModelSelectorItem
              key={option.value}
              value={option.label}
              onSelect={() => select(option.value)}
            >
              <div className="flex min-w-0 flex-1 flex-col">
                <ModelSelectorName>{option.label}</ModelSelectorName>
                {option.description && (
                  <span className="text-muted-foreground truncate text-[10px]">
                    {option.description}
                  </span>
                )}
              </div>
              {value === option.value ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </ModelSelectorItem>
          ))}
          renderItem={(model) => (
            <ModelSelectorItem
              key={model.name}
              value={model.name}
              onSelect={() => select(model.name)}
            >
              <div className="flex min-w-0 flex-1 flex-col">
                <ModelSelectorName>
                  <ModelDisplayName
                    displayName={model.display_name}
                    price={model.price}
                  />
                  {annotate?.(model)}
                </ModelSelectorName>
                <span className="text-muted-foreground truncate text-[10px]">
                  {model.model}
                </span>
              </div>
              {model.name === value ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </ModelSelectorItem>
          )}
        />
      </ModelSelectorContent>
    </ModelSelector>
  );
}
