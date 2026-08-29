"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { ChevronDownIcon, CircleHelpIcon, CoinsIcon } from "lucide-react";
import { useMemo } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import {
  formatTokenCount,
  selectHeaderTokenUsage,
  type TokenUsage,
} from "@/core/messages/usage";
import {
  getTokenUsageViewPreset,
  tokenUsagePreferencesFromPreset,
  type TokenUsagePreferences,
  type TokenUsageViewPreset,
} from "@/core/messages/usage-model";
import {
  formatCost,
  type ContextUsage,
  type ThreadCostSummary,
} from "@/core/threads/token-usage";
import { cn } from "@/lib/utils";

import { formatContextUsagePercentage } from "./context-usage-format";
import { CostPerStepChart } from "./cost-per-step-chart";
import { Tooltip } from "./tooltip";

/**
 * Label for one auxiliary spend row.
 *
 * The backend's category is a free-form string
 * (`deerflow/runtime/aux_usage.py::CHAT_AUX_CATEGORIES`), and a chain of
 * ternaries here grew a branch every time a sink was added — which is how a new
 * sink ends up rendering its raw snake_case key in the header. A lookup keeps
 * that to one entry, and an unknown category still falls back to its own name
 * rather than disappearing: a row with no label is still money spent.
 */
function auxCategoryLabel(
  category: string,
  t: ReturnType<typeof useI18n>["t"],
): string {
  switch (category) {
    case "memory":
      return t.tokenUsage.memory;
    case "suggestions":
      return t.tokenUsage.suggestions;
    case "input_polish":
      return t.tokenUsage.inputPolish;
    case "goal":
      return t.tokenUsage.goal;
    default:
      return category;
  }
}

interface TokenUsageIndicatorProps {
  threadId?: string;
  messages: Message[];
  pendingMessages?: Message[];
  backendUsage?: TokenUsage | null;
  costSummary?: ThreadCostSummary | null;
  contextUsage?: ContextUsage | null;
  enabled?: boolean;
  preferences: TokenUsagePreferences;
  onPreferencesChange: (preferences: TokenUsagePreferences) => void;
  className?: string;
}

export function TokenUsageIndicator({
  threadId,
  messages,
  pendingMessages,
  backendUsage,
  costSummary,
  contextUsage,
  enabled = false,
  preferences,
  onPreferencesChange,
  className,
}: TokenUsageIndicatorProps) {
  const { t } = useI18n();

  const usage = useMemo(
    () =>
      selectHeaderTokenUsage({
        backendUsage: threadId ? backendUsage : null,
        messages,
        pendingMessages,
      }),
    [backendUsage, messages, pendingMessages, threadId],
  );
  const preset = getTokenUsageViewPreset(preferences);
  // Cost only reflects persisted runs (the backend does not price in-flight
  // stream deltas), and is shown only when a thread exists and pricing is set.
  const cost = threadId ? costSummary : null;
  const auxEntries = cost ? Object.entries(cost.aux) : [];
  const contextPercentage = formatContextUsagePercentage(
    contextUsage?.percentage,
  );

  if (!enabled) {
    return null;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          className={cn(
            "text-muted-foreground bg-background/70 hover:bg-background/90 flex h-auto items-center gap-1.5 rounded-full border px-2 py-1 text-xs font-normal",
            className,
          )}
        >
          <CoinsIcon size={14} />
          <span>{t.tokenUsage.label}</span>
          <span className="font-mono">
            {preferences.headerTotal
              ? usage
                ? formatTokenCount(usage.totalTokens)
                : "-"
              : t.tokenUsage.presets[presetKeyToTranslationKey(preset)]}
          </span>
          {preferences.headerTotal &&
            cost?.totalCost != null &&
            cost.currency && (
              <>
                <span className="opacity-40">·</span>
                {/* The pill shows one number — what you actually pay, i.e. the
                    promo rate when one is live. The standard rate it reverts to
                    is in the dropdown, where there is room to label the pair. */}
                <span className="font-mono text-emerald-500">
                  {formatCost(
                    cost.promoTotalCost ?? cost.totalCost,
                    cost.currency,
                  )}
                </span>
              </>
            )}
          {contextPercentage != null && (
            <span
              className="text-muted-foreground/80 border-l pl-1.5 font-mono"
              aria-label={t.contextUsage.badgeAriaLabel(contextPercentage)}
            >
              {contextPercentage}%
            </span>
          )}
          <ChevronDownIcon className="size-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="bottom" align="end" className="w-80">
        <DropdownMenuLabel>{t.tokenUsage.title}</DropdownMenuLabel>
        <div className="px-2 py-1 text-xs">
          {usage ? (
            <div className="space-y-1">
              <div className="flex justify-between gap-4">
                <span>{t.tokenUsage.input}</span>
                <span className="font-mono">
                  {formatTokenCount(usage.inputTokens)}
                </span>
              </div>
              <div className="flex justify-between gap-4">
                <span>{t.tokenUsage.output}</span>
                <span className="font-mono">
                  {formatTokenCount(usage.outputTokens)}
                </span>
              </div>
              <div className="border-t pt-1">
                <div className="flex justify-between gap-4">
                  <span>{t.tokenUsage.total}</span>
                  <span className="font-mono font-medium">
                    {formatTokenCount(usage.totalTokens)}
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <div className="text-muted-foreground">
              {t.tokenUsage.unavailable}
            </div>
          )}
        </div>
        {cost && (
          <>
            <DropdownMenuSeparator />
            <div className="px-2 py-1 text-xs">
              <div className="flex items-center justify-between gap-4">
                <span className="flex items-center gap-1">
                  {t.tokenUsage.cost}
                  <Tooltip
                    content={
                      <span className="block max-w-72 text-xs leading-relaxed">
                        {t.tokenUsage.costHint}
                      </span>
                    }
                  >
                    <CircleHelpIcon
                      className="text-muted-foreground size-3 cursor-help"
                      aria-label={t.tokenUsage.costHint}
                    />
                  </Tooltip>
                </span>
                {/* Green is what you pay; a red standard rate appears beside it
                    only while a promo is live, so the pair reads as "now" vs
                    "once the discount ends" rather than as two rival numbers. */}
                <span className="flex items-baseline gap-1.5 font-mono font-medium">
                  {cost.totalCost != null && cost.currency ? (
                    <>
                      <span className="text-emerald-500">
                        {formatCost(
                          cost.promoTotalCost ?? cost.totalCost,
                          cost.currency,
                        )}
                      </span>
                      {cost.promoTotalCost != null && (
                        <span className="text-red-500">
                          {formatCost(cost.totalCost, cost.currency)}
                        </span>
                      )}
                    </>
                  ) : (
                    "—"
                  )}
                </span>
              </div>
              {cost.promoTotalCost != null && cost.currency && (
                <div
                  data-testid="token-usage-promo-note"
                  className="text-muted-foreground mt-1 flex items-baseline gap-1.5 text-[11px] leading-snug"
                >
                  <span className="text-emerald-500">
                    {t.tokenUsage.promoRate}
                  </span>
                  <span className="text-red-500">
                    {t.tokenUsage.standardRate}
                  </span>
                </div>
              )}
              {cost.unpricedModels.length > 0 && (
                // A bare "—" (or a total that silently omits a model) is
                // indistinguishable from a broken feature. Name the models that
                // have no `pricing:` block so the fix is obvious.
                <div
                  data-testid="token-usage-unpriced"
                  className="text-muted-foreground mt-1 text-[11px] leading-snug"
                >
                  {cost.totalCost == null
                    ? t.tokenUsage.unpricedOnly(cost.unpricedModels.join(", "))
                    : t.tokenUsage.unpricedPartial(
                        cost.unpricedModels.join(", "),
                      )}
                </div>
              )}
              {cost.steps.length > 0 && cost.currency && (
                // The totals above say what the conversation cost; this says
                // which turn cost it. Only rendered once there is a step to
                // plot, so a fresh thread shows no empty axes.
                <CostPerStepChart steps={cost.steps} currency={cost.currency} />
              )}
              {cost.spendBudget?.tightest && (
                // The cap is money too, so it belongs beside the cost rather
                // than in a settings page nobody opens mid-conversation. Only
                // the tightest window is shown: three rows of headroom is noise,
                // and the one about to bite is the one that matters.
                <div
                  data-testid="token-usage-spend-budget"
                  className="mt-1 flex items-center justify-between gap-4 border-t pt-1"
                >
                  <span className="text-muted-foreground flex items-center gap-1">
                    {t.tokenUsage.budgetLeft}
                    <span className="opacity-70">
                      (
                      {t.tokenUsage.budgetPeriod(
                        cost.spendBudget.tightest.period,
                      )}
                      )
                    </span>
                    <Tooltip
                      content={
                        <span className="block max-w-72 text-xs leading-relaxed">
                          {t.tokenUsage.budgetHint}
                        </span>
                      }
                    >
                      <CircleHelpIcon
                        className="text-muted-foreground size-3 cursor-help"
                        aria-label={t.tokenUsage.budgetHint}
                      />
                    </Tooltip>
                  </span>
                  <span
                    className={cn(
                      "font-mono font-medium",
                      cost.spendBudget.exceeded
                        ? "text-red-500"
                        : cost.spendBudget.tightest.fraction >=
                            cost.spendBudget.warnThreshold
                          ? "text-amber-500"
                          : "text-emerald-500",
                    )}
                  >
                    {cost.spendBudget.currency
                      ? formatCost(
                          cost.spendBudget.tightest.remaining,
                          cost.spendBudget.currency,
                        )
                      : cost.spendBudget.tightest.remaining.toFixed(2)}
                  </span>
                </div>
              )}
              {cost.spendBudget?.exceeded && (
                <div
                  data-testid="token-usage-spend-budget-exceeded"
                  className="mt-1 text-[11px] leading-snug text-red-500"
                >
                  {t.tokenUsage.budgetExceeded}
                </div>
              )}
              {auxEntries.length > 0 && (
                <div className="mt-1 space-y-1 border-t pt-1">
                  {auxEntries.map(([category, entry]) => (
                    <div
                      key={category}
                      className="flex items-center justify-between gap-4"
                    >
                      <span className="text-muted-foreground">
                        {auxCategoryLabel(category, t)}
                      </span>
                      {/* One figure, on the same basis as the headline: what
                          this sink costs now. Memory and suggestions can each run
                          on their own model, so a discount applies per sink. */}
                      <span className="font-mono">
                        {entry.cost != null && cost.currency ? (
                          <span className="text-emerald-500">
                            {formatCost(
                              entry.promoCost ?? entry.cost,
                              cost.currency,
                            )}
                          </span>
                        ) : (
                          formatTokenCount(entry.tokens)
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuLabel>{t.tokenUsage.view}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={preset}
          onValueChange={(value) =>
            onPreferencesChange(
              tokenUsagePreferencesFromPreset(value as TokenUsageViewPreset),
            )
          }
        >
          {(
            ["off", "summary", "per_turn", "debug"] as TokenUsageViewPreset[]
          ).map((value) => {
            const translationKey = presetKeyToTranslationKey(value);
            return (
              <DropdownMenuRadioItem key={value} value={value}>
                <div className="grid gap-0.5">
                  <span>{t.tokenUsage.presets[translationKey]}</span>
                  <span className="text-muted-foreground text-xs">
                    {t.tokenUsage.presetDescriptions[translationKey]}
                  </span>
                </div>
              </DropdownMenuRadioItem>
            );
          })}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <div className="text-muted-foreground px-2 py-2 text-xs leading-relaxed">
          {t.tokenUsage.note}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function presetKeyToTranslationKey(preset: TokenUsageViewPreset) {
  switch (preset) {
    case "per_turn":
      return "perTurn" as const;
    default:
      return preset;
  }
}
