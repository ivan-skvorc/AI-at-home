"use client";

import { Loader2Icon } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildOverrides,
  draftFromLimits,
  mergeDraft,
  sectionOverride,
  useRunLimits,
  useSaveRunLimits,
  type RunLimitError,
  type RunLimitSection,
  type RunLimitsDraft,
  type RunLimitsResponse,
} from "@/core/settings/run-limits";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import { SettingsSection } from "./settings-section";

/**
 * Settings → Run limits (fork feature, FORK.md §46): the spend cap, tool-call
 * limits, token budgets and background step limit, edited server-wide instead
 * of in config.yaml. Admin-only; the nav entry is hidden for everyone else and
 * the page guards again in case a deep link opens it.
 */
export function RunLimitsSettingsPage() {
  const { t } = useI18n();
  const { user } = useAuth();
  const canManage = user?.system_role === "admin" && !isStaticWebsiteOnly();
  const query = useRunLimits(canManage);

  return (
    <SettingsSection
      title={t.settings.runLimits.title}
      description={t.settings.runLimits.description}
    >
      {!canManage ? (
        <p className="text-muted-foreground text-sm">
          {t.settings.runLimits.adminOnly}
        </p>
      ) : query.isError ? (
        <div className="space-y-2">
          <p className="text-destructive text-sm">
            {t.settings.runLimits.loadError}
          </p>
          <Button variant="outline" size="sm" onClick={() => query.refetch()}>
            {t.settings.runLimits.retry}
          </Button>
        </div>
      ) : !query.data ? (
        <Loader2Icon
          className="text-muted-foreground size-4 animate-spin"
          aria-hidden
        />
      ) : (
        <RunLimitsForm data={query.data} />
      )}
    </SettingsSection>
  );
}

function RunLimitsForm({ data }: { data: RunLimitsResponse }) {
  const { t } = useI18n();
  const copy = t.settings.runLimits;
  const save = useSaveRunLimits();
  // One state so a refresh can read which sections are still being edited.
  const [form, setForm] = useState<{
    draft: RunLimitsDraft;
    edited: ReadonlySet<RunLimitSection>;
  }>(() => ({ draft: draftFromLimits(data.effective), edited: new Set() }));
  const { draft, edited } = form;
  // New server values (a save, or a refetch) refresh every section the user is
  // not editing.
  useEffect(() => {
    setForm((current) => ({
      ...current,
      draft: mergeDraft(
        current.draft,
        draftFromLimits(data.effective),
        current.edited,
      ),
    }));
  }, [data]);

  const update = <S extends RunLimitSection>(
    section: S,
    value: RunLimitsDraft[S],
  ) => {
    setForm((current) => ({
      draft: { ...current.draft, [section]: value },
      edited: new Set(current.edited).add(section),
    }));
  };

  const errorOf = (section: RunLimitSection): RunLimitError | null => {
    if (!edited.has(section)) {
      return null;
    }
    const result = sectionOverride(draft, section);
    return "error" in result ? result.error : null;
  };
  const hasErrors = [...edited].some((section) => errorOf(section) !== null);

  /** Save the given edited sections, or clear one section back to config.yaml. */
  const submit = (
    sections: ReadonlySet<RunLimitSection>,
    cleared?: RunLimitSection,
  ) => {
    const base = cleared
      ? { ...data.overrides, [cleared]: null }
      : data.overrides;
    const built = buildOverrides(base, draft, sections);
    if ("error" in built) {
      return;
    }
    const settled = new Set<RunLimitSection>(sections);
    if (cleared) {
      settled.add(cleared);
    }
    save.mutate(built.value, {
      onSuccess: (response) => {
        setForm((current) => {
          const editing = new Set(current.edited);
          settled.forEach((section) => editing.delete(section));
          return {
            draft: mergeDraft(
              current.draft,
              draftFromLimits(response.effective),
              editing,
            ),
            edited: editing,
          };
        });
        toast.success(copy.saved);
      },
      onError: (error) =>
        toast.error(
          copy.saveError(
            error instanceof Error ? error.message : String(error),
          ),
        ),
    });
  };

  const header = (section: RunLimitSection, title: string) => {
    const overridden = data.overrides[section] != null;
    return (
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-medium">{title}</h3>
        <Badge variant={overridden ? "secondary" : "outline"}>
          {overridden ? copy.sourceSettings : copy.sourceYaml}
        </Badge>
        {overridden && (
          <Button
            variant="link"
            size="sm"
            className="h-auto p-0"
            disabled={save.isPending}
            onClick={() => submit(new Set(), section)}
          >
            {copy.useYaml}
          </Button>
        )}
      </div>
    );
  };

  const spend = draft.spend_budget;
  const loop = draft.loop_detection;
  const yamlToolLimits = Object.entries(
    data.effective.loop_detection.tool_freq_overrides,
  );

  return (
    <div className="space-y-4">
      <LimitCard
        header={header("spend_budget", copy.spendTitle)}
        description={copy.spendDescription}
        toggleLabel={copy.spendTitle}
        enabled={spend.enabled}
        onToggle={(enabled) => update("spend_budget", { ...spend, enabled })}
        error={errorOf("spend_budget")}
      >
        <div className="grid gap-4 sm:grid-cols-3">
          {(
            [
              ["daily_limit", copy.spendDaily],
              ["weekly_limit", copy.spendWeekly],
              ["monthly_limit", copy.spendMonthly],
            ] as const
          ).map(([field, label]) => (
            <NumberField
              key={field}
              label={label}
              value={spend[field]}
              decimal
              onChange={(value) =>
                update("spend_budget", { ...spend, [field]: value })
              }
            />
          ))}
        </div>
        <p className="text-muted-foreground text-xs">
          {copy.spendBlankHint}{" "}
          {data.effective.spend_budget.currency
            ? copy.spendCurrency(data.effective.spend_budget.currency)
            : copy.spendNoPricing}
        </p>
      </LimitCard>

      <LimitCard
        header={header("loop_detection", copy.toolTitle)}
        description={copy.toolDescription}
        toggleLabel={copy.toolTitle}
        enabled={loop.enabled}
        onToggle={(enabled) => update("loop_detection", { ...loop, enabled })}
        error={errorOf("loop_detection")}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          {(
            [
              ["tool_freq_warn", copy.toolPerToolWarn],
              ["tool_freq_hard_limit", copy.toolPerToolStop],
              ["warn_threshold", copy.toolRepeatWarn],
              ["hard_limit", copy.toolRepeatStop],
            ] as const
          ).map(([field, label]) => (
            <NumberField
              key={field}
              label={label}
              value={loop[field]}
              onChange={(value) =>
                update("loop_detection", { ...loop, [field]: value })
              }
            />
          ))}
        </div>
        <p className="text-muted-foreground text-xs">
          {copy.toolAppliesToAll}
          {yamlToolLimits.length > 0 &&
            ` ${copy.toolYamlOverrides(
              yamlToolLimits
                .map(
                  ([name, item]) => `${name} (${item.warn}/${item.hard_limit})`,
                )
                .join(", "),
            )}`}
        </p>
      </LimitCard>

      {(
        [
          ["token_budget", copy.leadTokensTitle, copy.leadTokensDescription],
          [
            "subagent_token_budget",
            copy.subagentTokensTitle,
            copy.subagentTokensDescription,
          ],
        ] as const
      ).map(([section, title, description]) => (
        <LimitCard
          key={section}
          header={header(section, title)}
          description={description}
          toggleLabel={title}
          enabled={draft[section].enabled}
          onToggle={(enabled) =>
            update(section, { ...draft[section], enabled })
          }
          error={errorOf(section)}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <NumberField
              label={copy.maxTokens}
              value={draft[section].max_tokens}
              onChange={(max_tokens) =>
                update(section, { ...draft[section], max_tokens })
              }
            />
          </div>
        </LimitCard>
      ))}

      <LimitCard
        header={header("recursion_limit", copy.stepsTitle)}
        description={copy.stepsDescription}
        error={errorOf("recursion_limit")}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <NumberField
            label={copy.steps}
            value={draft.recursion_limit}
            hint={copy.stepsHint(data.effective.max_recursion_limit)}
            onChange={(value) => update("recursion_limit", value)}
          />
        </div>
      </LimitCard>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          disabled={edited.size === 0 || hasErrors || save.isPending}
          onClick={() => submit(edited)}
        >
          {save.isPending && <Loader2Icon className="size-4 animate-spin" />}
          {save.isPending ? copy.saving : copy.save}
        </Button>
        <p className="text-muted-foreground text-xs">{copy.appliesNext}</p>
      </div>
    </div>
  );
}

function LimitCard({
  header,
  description,
  toggleLabel,
  enabled,
  onToggle,
  error,
  children,
}: {
  header: React.ReactNode;
  description: string;
  toggleLabel?: string;
  enabled?: boolean;
  onToggle?: (enabled: boolean) => void;
  error: RunLimitError | null;
  children: React.ReactNode;
}) {
  const { t } = useI18n();
  return (
    <section className="space-y-3 rounded-md border p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          {header}
          <p className="text-muted-foreground text-sm">{description}</p>
        </div>
        {onToggle && (
          <Switch
            aria-label={toggleLabel}
            checked={enabled}
            onCheckedChange={onToggle}
          />
        )}
      </div>
      {children}
      {error && (
        <p className="text-destructive text-sm" role="alert">
          {t.settings.runLimits.errors[error]}
        </p>
      )}
    </section>
  );
}

function NumberField({
  label,
  value,
  hint,
  decimal = false,
  onChange,
}: {
  label: string;
  value: string;
  hint?: string;
  decimal?: boolean;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <Input
        id={id}
        inputMode={decimal ? "decimal" : "numeric"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
    </div>
  );
}
