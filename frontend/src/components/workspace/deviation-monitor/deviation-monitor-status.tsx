"use client";

import {
  ChevronDownIcon,
  CircleCheckIcon,
  CircleHelpIcon,
  CircleStopIcon,
  CompassIcon,
  LoaderCircleIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { useDeviationMonitorFeature } from "@/core/features/deviation-monitor";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import {
  normalizeDeviationMonitorSetting,
  type DeviationMonitorChatSetting,
} from "@/core/threads/deviation-monitor";
import { cn } from "@/lib/utils";

import { cadenceSummary, monitorModelLabel } from "./labels";
import {
  describeDeviationMonitorBar,
  type DeviationMonitorBarKind,
  type DeviationMonitorBarTone,
} from "./status-helpers";

const ICONS: Record<DeviationMonitorBarKind, LucideIcon> = {
  idle: CompassIcon,
  off: CircleHelpIcon,
  checking: LoaderCircleIcon,
  on_track: CircleCheckIcon,
  unsure: CircleHelpIcon,
  drifting: TriangleAlertIcon,
  retrying: LoaderCircleIcon,
  stopped: CircleStopIcon,
};

const TONE_CLASSES: Record<DeviationMonitorBarTone, string> = {
  neutral: "text-muted-foreground",
  busy: "text-primary",
  good: "text-emerald-600 dark:text-emerald-400",
  warn: "text-amber-600 dark:text-amber-400",
  danger: "text-destructive",
};

/**
 * The deviation monitor's status bar above the composer (fork feature),
 * modelled on `GoalStatus`: one compact row with the latest verdict, the
 * reason and the request it judged against in a disclosure, and a one-click
 * Turn off. Fed by the `deviation_monitor` thread-state channel, which
 * survives a reload, unlike a custom stream event.
 *
 * Renders nothing unless the operator offers the monitor and this chat has it
 * on. The run's stop note itself is an ordinary assistant message from the
 * backend, rendered in the transcript like any other cap's note.
 */
export function DeviationMonitorStatus({
  className,
  setting: storedSetting,
  state,
  isRunning = false,
  runStartedAt,
  onChange,
}: {
  className?: string;
  /** The chat's stored choice, as read from its context (unvalidated). */
  setting: unknown;
  /** `thread.values.deviation_monitor` (unvalidated). */
  state: unknown;
  isRunning?: boolean;
  runStartedAt?: number | null;
  onChange: (setting: DeviationMonitorChatSetting) => void;
}) {
  const { t } = useI18n();
  const copy = t.deviationMonitor;
  const { enabled: featureEnabled } = useDeviationMonitorFeature();
  const { models } = useModels();
  const view = describeDeviationMonitorBar({
    setting: storedSetting,
    state,
    isRunning,
    runStartedAt,
  });
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [openedFor, setOpenedFor] = useState(view?.kind);
  if (openedFor !== view?.kind) {
    // A new verdict starts collapsed, like the goal bar.
    setOpenedFor(view?.kind);
    setDetailsOpen(false);
  }
  const detailsId = useId();

  const setting = normalizeDeviationMonitorSetting(storedSetting);
  if (!featureEnabled || !view || !setting) {
    return null;
  }
  const Icon = ICONS[view.kind];
  const statusLabel = copy.status[view.kind];
  const modelLabel = monitorModelLabel(t, models, view.model);
  const meta = [
    view.checks > 0 ? copy.checks(view.checks) : null,
    view.lastStep !== null ? copy.lastStep(view.lastStep) : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <section
      aria-label={copy.status.regionLabel}
      className={cn(
        "bg-background/90 border-border flex w-full flex-col gap-1 rounded-xl border px-3 py-1.5 text-sm shadow-sm backdrop-blur-sm",
        className,
      )}
      data-testid="deviation-monitor-status"
      data-status={view.kind}
    >
      <div className="flex min-w-0 items-center gap-2">
        <Icon
          aria-hidden
          className={cn(
            "size-4 shrink-0",
            TONE_CLASSES[view.tone],
            view.busy && "motion-safe:animate-spin",
          )}
        />
        <div className="min-w-0 flex-1 truncate">
          <span className="text-muted-foreground mr-1.5">{copy.name}</span>
          <span
            className={cn("font-medium", TONE_CLASSES[view.tone])}
            data-testid="deviation-monitor-status-label"
          >
            {statusLabel}
          </span>
          <span className="text-muted-foreground hidden text-xs sm:inline">
            {" · "}
            {cadenceSummary(t, setting.cadence)}
            {" · "}
            {modelLabel}
          </span>
        </div>
        {meta && (
          <span className="text-muted-foreground hidden shrink-0 text-xs tabular-nums sm:inline">
            {meta}
          </span>
        )}
        {view.hasDetails && (
          <button
            type="button"
            aria-expanded={detailsOpen}
            aria-controls={detailsId}
            className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 flex shrink-0 items-center gap-0.5 rounded text-xs outline-none focus-visible:ring-[3px]"
            onClick={() => setDetailsOpen((open) => !open)}
            data-testid="deviation-monitor-status-details-toggle"
          >
            {detailsOpen ? copy.hideDetails : copy.details}
            <ChevronDownIcon
              aria-hidden
              className={cn(
                "size-3 motion-safe:transition-transform",
                detailsOpen && "rotate-180",
              )}
            />
          </button>
        )}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 shrink-0 px-2 text-xs"
          onClick={() => onChange({ ...setting, enabled: false })}
          data-testid="deviation-monitor-status-turn-off"
        >
          {copy.turnOff}
        </Button>
      </div>
      {view.hasDetails && (
        <div
          id={detailsId}
          hidden={!detailsOpen}
          data-testid="deviation-monitor-status-details"
        >
          {detailsOpen && (
            <div className="bg-muted/50 flex flex-col gap-1 rounded-md p-2 text-xs break-words whitespace-pre-wrap">
              {view.reason && (
                <p>
                  <span className="text-muted-foreground mr-1">
                    {copy.reasonLabel}
                  </span>
                  <span dir="auto" data-testid="deviation-monitor-reason">
                    {view.reason}
                  </span>
                </p>
              )}
              {view.driftKind && (
                <p>
                  <span className="text-muted-foreground mr-1">
                    {copy.driftKindLabel}
                  </span>
                  {copy.driftKinds[view.driftKind]}
                </p>
              )}
              {view.restatedTask && (
                <p>
                  <span className="text-muted-foreground mr-1">
                    {copy.restatedTaskLabel}
                  </span>
                  <span dir="auto">{view.restatedTask}</span>
                </p>
              )}
              <p>
                <span className="text-muted-foreground mr-1">
                  {copy.modelLabelShort}
                </span>
                {modelLabel}
              </p>
            </div>
          )}
        </div>
      )}
      <p role="status" className="sr-only">
        {`${copy.name}: ${statusLabel}`}
      </p>
    </section>
  );
}
