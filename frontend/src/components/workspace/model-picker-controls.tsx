"use client";

import { ArrowDownIcon, ArrowUpIcon } from "lucide-react";
import { type ReactNode, useMemo } from "react";

import {
  ModelSelectorGroup,
  ModelSelectorList,
} from "@/components/ai-elements/model-selector";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useI18n } from "@/core/i18n/hooks";
import {
  groupModelsByProvider,
  type ModelPickerPrefs,
  type ModelProvider,
  type ModelSortKey,
  sortModels,
  splitModelNamePriceSegments,
} from "@/core/models/sorting";
import type { Model } from "@/core/models/types";
import { cn } from "@/lib/utils";

/**
 * Sort/group controls rendered inside the model dropdown (fork feature). Shared
 * by the lead, subagent, and sidecar pickers so the ordering behaves the same
 * everywhere. See `core/models/sorting.ts` for the parsing/sorting logic and
 * `core/settings/local.ts` for where the preference is persisted.
 */
export function ModelPickerControls({
  prefs,
  onChange,
  className,
}: {
  prefs: ModelPickerPrefs;
  onChange: (next: ModelPickerPrefs) => void;
  className?: string;
}) {
  const { t } = useI18n();
  const directionAsc = prefs.sortDir === "asc";
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 border-b px-3 py-2 text-xs",
        className,
      )}
    >
      <span className="text-muted-foreground">{t.inputBox.sortModelsBy}</span>
      <ToggleGroup
        type="single"
        size="sm"
        value={prefs.sortKey}
        // Radix clears the value when the active item is re-pressed; keep the
        // current key rather than falling into an empty selection.
        onValueChange={(value) =>
          onChange({
            ...prefs,
            sortKey: (value || prefs.sortKey) as ModelSortKey,
          })
        }
      >
        <ToggleGroupItem value="default" className="h-6 px-2 text-xs">
          {t.inputBox.sortByDefault}
        </ToggleGroupItem>
        <ToggleGroupItem value="name" className="h-6 px-2 text-xs">
          {t.inputBox.sortByName}
        </ToggleGroupItem>
        <ToggleGroupItem value="price" className="h-6 px-2 text-xs">
          {t.inputBox.sortByPrice}
        </ToggleGroupItem>
      </ToggleGroup>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="size-6"
        // Direction is meaningless for config order.
        disabled={prefs.sortKey === "default"}
        aria-label={
          directionAsc ? t.inputBox.sortDescending : t.inputBox.sortAscending
        }
        title={
          directionAsc ? t.inputBox.sortDescending : t.inputBox.sortAscending
        }
        onClick={() =>
          onChange({ ...prefs, sortDir: directionAsc ? "desc" : "asc" })
        }
      >
        {directionAsc ? (
          <ArrowUpIcon className="size-3.5" />
        ) : (
          <ArrowDownIcon className="size-3.5" />
        )}
      </Button>
      <label className="ml-auto flex items-center gap-1.5">
        <span className="text-muted-foreground">
          {t.inputBox.groupByProvider}
        </span>
        <Switch
          checked={prefs.groupByProvider}
          onCheckedChange={(checked) =>
            onChange({ ...prefs, groupByProvider: checked })
          }
        />
      </label>
    </div>
  );
}

/**
 * Render a model's `display_name` with its price picked out in colour.
 *
 * Green is what you pay: the only price on an ordinary model, or the starred
 * promo on a discounted one. Red is the standard list price *beside* a live
 * promo — it is what the model reverts to, so it reads as the more expensive of
 * the pair rather than as an error. A name with no parseable price renders
 * verbatim (see `splitModelNamePriceSegments`), so nothing is ever hidden by a
 * format the parser does not recognize.
 */
export function ModelDisplayName({
  displayName,
  className,
}: {
  displayName: string | null | undefined;
  className?: string;
}) {
  const segments = useMemo(
    () => splitModelNamePriceSegments(displayName),
    [displayName],
  );
  return (
    <span className={className}>
      {segments.map((segment, index) => (
        <span
          key={index}
          className={
            segment.kind === "price" || segment.kind === "promoPrice"
              ? "text-emerald-500"
              : segment.kind === "listPrice"
                ? "text-red-500"
                : undefined
          }
        >
          {segment.text}
        </span>
      ))}
    </span>
  );
}

function providerHeading(provider: ModelProvider, otherLabel: string): string {
  return provider === "Other" ? otherLabel : provider;
}

/**
 * Render `models` inside a `ModelSelectorList`, ordered/grouped by `prefs`.
 * `renderItem` supplies each row (it owns its own `key`), so the lead, subagent,
 * and sidecar pickers keep their own item markup while sharing the ordering.
 * `leading` is rendered before every model (e.g. the subagent "Follow lead"
 * pseudo-item) and stays pinned regardless of sort/group.
 */
export function ModelPickerList<T extends Model>({
  models,
  prefs,
  renderItem,
  leading,
  demoteLast,
}: {
  models: readonly T[];
  prefs: ModelPickerPrefs;
  renderItem: (model: T) => ReactNode;
  leading?: ReactNode;
  /** Keep matching models at the bottom regardless of sort (e.g. no-tool
   * models in the subagent picker — see `core/models/sorting.ts`). */
  demoteLast?: (model: T) => boolean;
}) {
  const { t } = useI18n();
  const view = useMemo(() => {
    const options = demoteLast ? { demoteLast } : undefined;
    if (prefs.groupByProvider) {
      return {
        grouped: true as const,
        groups: groupModelsByProvider(models, prefs, options),
      };
    }
    return {
      grouped: false as const,
      models: sortModels(models, prefs, options),
    };
  }, [models, prefs, demoteLast]);

  return (
    <ModelSelectorList>
      {leading}
      {view.grouped
        ? view.groups.map((group) => (
            <ModelSelectorGroup
              key={group.provider}
              heading={providerHeading(
                group.provider,
                t.inputBox.modelProviderOther,
              )}
            >
              {group.models.map(renderItem)}
            </ModelSelectorGroup>
          ))
        : view.models.map(renderItem)}
    </ModelSelectorList>
  );
}
