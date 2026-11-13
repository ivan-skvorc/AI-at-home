"use client";

import { Clock3Icon } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { Shimmer } from "@/components/ai-elements/shimmer";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import {
  formatRunDuration,
  formatRunStartTime,
  type RunStartSource,
} from "@/core/messages/run-duration";

/**
 * The live "Working… (12m 4s)" line. The elapsed time explains itself on hover
 * and to assistive tech: counted from the run's server-recorded start (so a
 * reload keeps counting), or, until the server reports that start, from when
 * this page began following the run, which can be later.
 */
export function RunActivity({
  startTime,
  startSource = "local",
}: {
  startTime: number | null;
  startSource?: RunStartSource;
}) {
  const { t, locale } = useI18n();
  const descriptionId = useId();
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (startTime === null) {
      setElapsed(0);
      return;
    }

    const updateElapsed = () => {
      setElapsed(Math.max(0, Math.floor((Date.now() - startTime) / 1000)));
    };
    updateElapsed();
    const interval = setInterval(updateElapsed, 1000);
    return () => clearInterval(interval);
  }, [startTime]);

  const formatted = formatRunDuration(elapsed, t.runDuration);
  const description =
    startTime !== null && startSource === "server"
      ? t.runDuration.serverStart(
          formatRunStartTime(startTime, { locale, now: Date.now() }),
        )
      : t.runDuration.localStart;

  return (
    <div
      className="text-muted-foreground flex items-center gap-2 text-sm"
      data-testid="run-activity"
    >
      <Clock3Icon className="size-4" />
      <Shimmer duration={1}>{t.runDuration.working}</Shimmer>
      {formatted && (
        <Tooltip content={description} contentClassName="max-w-72">
          <span
            role="timer"
            tabIndex={0}
            aria-label={t.runDuration.elapsed}
            aria-describedby={descriptionId}
            className="cursor-help rounded-sm underline decoration-dotted underline-offset-4 focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            ({formatted})
          </span>
        </Tooltip>
      )}
      <span id={descriptionId} className="sr-only">
        {description}
      </span>
    </div>
  );
}

export function RunDurationLabel({
  durationSeconds,
}: {
  durationSeconds: number;
}) {
  const { t } = useI18n();
  const formatted = formatRunDuration(durationSeconds, t.runDuration);
  if (!formatted) {
    return null;
  }

  return (
    <span data-testid="run-duration" title={t.runDuration.description}>
      {t.runDuration.completedIn(formatted)}
    </span>
  );
}

export function RunDuration({ durationSeconds }: { durationSeconds: number }) {
  return (
    <div className="text-muted-foreground border-border/60 mb-3 border-b pb-3 text-sm">
      <RunDurationLabel durationSeconds={durationSeconds} />
    </div>
  );
}
