"use client";

import { DownloadCloudIcon, Loader2Icon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import {
  DependencyUpdateForbiddenError,
  fetchDependencyUpdateStatus,
  startDependencyUpdate,
  type DependencyUpdateOutcome,
  type DependencyUpdateStatus,
} from "@/core/settings/dependency-update";

import { SettingsSection } from "./settings-section";

// The work is a Docker pull and a browser download, so progress is measured in
// tens of seconds; polling faster than this only adds request noise.
const POLL_INTERVAL_MS = 3000;

const COMPONENTS = ["camoufox", "searxng"] as const;

/**
 * Force a refresh of the two components this fork installs for itself.
 *
 * Both already refresh on a daily throttle. This is the path for when that
 * throttle is in the way: a broken search backend or a browser that stopped
 * loading pages, where the answer is "pull the newer build now" and the
 * alternative is an SSH session on the host.
 */
export function MaintenanceSettingsPage() {
  const { t } = useI18n();
  const [status, setStatus] = useState<DependencyUpdateStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    const next = await fetchDependencyUpdateStatus();
    if (next) {
      setStatus(next);
    }
    return next;
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll only while a run is in flight — the state is otherwise static, and an
  // idle settings page has no reason to talk to the gateway on a timer.
  useEffect(() => {
    if (!status?.running) {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    if (pollRef.current !== null) {
      return;
    }
    pollRef.current = window.setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [refresh, status?.running]);

  const handleUpdate = useCallback(async () => {
    setStarting(true);
    try {
      const next = await startDependencyUpdate();
      if (next) {
        setStatus(next);
      }
      toast.info(t.settings.maintenance.started);
    } catch (error) {
      toast.error(
        error instanceof DependencyUpdateForbiddenError
          ? t.settings.maintenance.adminOnly
          : t.settings.maintenance.startFailed,
      );
    } finally {
      setStarting(false);
    }
  }, [
    t.settings.maintenance.adminOnly,
    t.settings.maintenance.started,
    t.settings.maintenance.startFailed,
  ]);

  const running = status?.running === true;
  const busy = running || starting;

  return (
    <SettingsSection
      title={t.settings.maintenance.title}
      description={t.settings.maintenance.description}
    >
      <div className="flex flex-col gap-4">
        <div>
          <Button
            data-testid="update-dependencies"
            disabled={busy}
            onClick={() => void handleUpdate()}
          >
            {busy ? (
              <Loader2Icon className="animate-spin" />
            ) : (
              <DownloadCloudIcon />
            )}
            {running
              ? t.settings.maintenance.updating
              : t.settings.maintenance.updateNow}
          </Button>
        </div>

        <p className="text-muted-foreground text-sm">
          {t.settings.maintenance.hint}
        </p>

        {status?.error ? (
          <p className="text-destructive text-sm">
            {t.settings.maintenance.failed}: {status.error}
          </p>
        ) : null}

        {Object.keys(status?.results ?? {}).length > 0 && (
          <dl className="flex flex-col gap-2 text-sm">
            {COMPONENTS.map((component) => {
              const outcome = status?.results?.[component];
              if (!outcome) {
                return null;
              }
              return (
                <div key={component} className="flex items-center gap-2">
                  <dt className="font-medium">
                    {t.settings.maintenance.components[component]}
                  </dt>
                  <dd className="text-muted-foreground">
                    {outcomeLabel(outcome, t)}
                  </dd>
                </div>
              );
            })}
          </dl>
        )}
      </div>
    </SettingsSection>
  );
}

function outcomeLabel(
  outcome: DependencyUpdateOutcome,
  t: ReturnType<typeof useI18n>["t"],
): string {
  const labels = t.settings.maintenance.outcomes;
  switch (outcome) {
    case "ok":
      return labels.ok;
    case "skipped":
      return labels.skipped;
    case "skipped-no-docker":
      return labels.noDocker;
    case "timeout":
      return labels.timeout;
    case "would-update":
      return labels.ok;
    default:
      return labels.failed;
  }
}
