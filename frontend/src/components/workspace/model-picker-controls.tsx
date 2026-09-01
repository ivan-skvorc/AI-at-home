"use client";

import { ArrowDownIcon, ArrowUpIcon } from "lucide-react";
import { type ReactNode, useMemo } from "react";

import {
  ModelSelectorGroup,
  ModelSelectorList,
  ModelSelectorName,
} from "@/components/ai-elements/model-selector";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useI18n } from "@/core/i18n/hooks";
import {
  groupModelsByProvider,
  type ModelNameSegmentKind,
  type ModelPickerPrefs,
  type ModelProvider,
  type ModelSortKey,
  compactModelDisplayName,
  modelRowParts,
  sortModels,
  modelNameSegments,
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
 * The colour a price run is painted in.
 *
 * Green is what you pay: the only price on an ordinary model, or the starred
 * promo on a discounted one. Red is the standard list price *beside* a live
 * promo — it is what the model reverts to, so it reads as the more expensive of
 * the pair rather than as an error. Kept in one place so the trigger label and
 * the row cannot drift into two colour conventions for the same number.
 */
function priceClassName(kind: ModelNameSegmentKind): string | undefined {
  if (kind === "price" || kind === "promoPrice") {
    return "text-emerald-500";
  }
  return kind === "listPrice" ? "text-red-500" : undefined;
}

/**
 * Render a model's `display_name` with its price picked out in colour.
 *
 * This is the **collapsed trigger's** label, where the name and price are one
 * flowing string. The open list's rows use `ModelPickerRow` below, which lays
 * the same pieces out as columns. A name with no parseable price renders
 * verbatim (see `splitModelNamePriceSegments`), so nothing is ever hidden by a
 * format the parser does not recognize.
 */
export function ModelDisplayName({
  displayName,
  price,
  className,
  variant = "inline",
}: {
  displayName: string | null | undefined;
  /**
   * The model's structured price. Supplied, it is the source of the coloured
   * price suffix; omitted, the price is parsed out of `displayName` as it was
   * before prices moved into their own field (which is still how a config
   * written before that change carries them).
   */
  price?: Model["price"];
  className?: string;
  /**
   * `"compact"` is for the width-capped trigger button: the name is shortened
   * (provider suffix dropped, `(p)` kept) and only the **leading text** is
   * allowed to ellipsize, so the price pair survives at any button width.
   *
   * The host `ModelSelectorName` must carry `w-full`. It lives in a
   * `flex-col items-start` container, where its own `flex-1` sizes the *cross*
   * axis — height, not width — so it defaults to `fit-content`, renders past the
   * capped button, and its `truncate` never fires. Measured in Chromium: a
   * bundled promo name is 315px inside a 160px button. Without `w-full` there is
   * no width budget for the pinning below to work inside.
   */
  variant?: "inline" | "compact";
}) {
  const compact = variant === "compact";
  const segments = useMemo(
    () =>
      modelNameSegments(
        { display_name: displayName ?? "", price },
        compact ? compactModelDisplayName(displayName) : displayName,
      ),
    [displayName, price, compact],
  );
  return (
    <span
      className={cn(compact && "flex min-w-0 items-baseline", className)}
      // The full, uncompacted name stays reachable on hover, since the compact
      // form deliberately drops the provider.
      title={compact ? (displayName ?? undefined) : undefined}
    >
      {segments.map((segment, index) => (
        <span
          key={index}
          className={cn(
            priceClassName(segment.kind),
            // Everything after the leading text is pinned; the model name is
            // the only part that may be sacrificed to a narrow button.
            compact &&
              (index === 0 && segment.kind === "text"
                ? "min-w-0 truncate"
                : "shrink-0 whitespace-nowrap"),
          )}
        >
          {segment.text}
        </span>
      ))}
    </span>
  );
}

/**
 * One model's row in the open picker: **provider, then name, then the price
 * pinned to the right edge**, with the model id, its weights, and its context
 * window on a second line.
 *
 * The row used to be a single flowing string — `Claude Sonnet 5 (Anthropic)
 * ($3/15)` — so the one number worth comparing across a couple of dozen models
 * landed wherever each name happened to end, and no two rows lined up. Pinning
 * it with `ml-auto` needs the price as its own node, which is why
 * `modelRowParts` splits what `modelNameSegments` joins; the width-capped
 * trigger button still uses the joined form, where one string is correct.
 *
 * Two details are load-bearing. The provider is the **literal** suffix
 * (`xAI`, `DeepSeek`), not the four-way sort bucket, so a first-party lab is
 * named rather than collapsed into "Other"; and only the name may ellipsize —
 * the provider and the price are `shrink-0`, the same rule the compact trigger
 * follows, because a truncated price is worse than a truncated name.
 *
 * Used by every picker (composer lead, composer subagent, sidecar, and the
 * shared `ModelSelect`). A site that hand-rolls this markup instead is how the
 * rows drift apart again — see `model-picker-sites.test.ts`.
 */
export function ModelPickerRow({
  model,
  showProvider = true,
  annotation,
}: {
  model: Model;
  /**
   * Grouped mode already names the provider in the section heading, so the
   * per-row copy is redundant there and is dropped.
   */
  showProvider?: boolean;
  /** Rendered after the name, e.g. `(no tool support)`. */
  annotation?: ReactNode;
}) {
  const { t } = useI18n();
  const parts = useMemo(() => modelRowParts(model), [model]);
  const meta = [
    model.model,
    parts.size,
    parts.contextWindow &&
      `${parts.contextWindow} ${t.inputBox.modelContextSuffix}`,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <ModelSelectorName className="flex w-full min-w-0 items-baseline gap-1.5">
        {showProvider && parts.provider && (
          <span className="text-muted-foreground shrink-0 text-[10px] tracking-wide uppercase">
            {parts.provider}
          </span>
        )}
        <span className="min-w-0 truncate">{parts.name}</span>
        {annotation}
        {parts.price.length > 0 && (
          <span className="ml-auto shrink-0 pl-2 tabular-nums">
            {parts.price.map((segment, index) => (
              <span key={index} className={priceClassName(segment.kind)}>
                {segment.text}
              </span>
            ))}
          </span>
        )}
      </ModelSelectorName>
      <span
        className="text-muted-foreground truncate text-[10px]"
        title={t.inputBox.modelMetaTitle}
      >
        {meta}
      </span>
    </div>
  );
}

function providerHeading(provider: ModelProvider, otherLabel: string): string {
  return provider === "Other" ? otherLabel : provider;
}

/**
 * Render `models` inside a `ModelSelectorList`, ordered/grouped by `prefs`.
 * `renderItem` supplies each row (it owns its own `key` and its own selection
 * behaviour — which model is checked, whether it is disabled), while the row's
 * *contents* come from `ModelPickerRow` so every picker looks the same.
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
