"use client";

import { BellIcon, SmartphoneIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import { useNotification } from "@/core/notification/hooks";
import {
  detectPushSupport,
  fetchPushConfig,
  sendTestPush,
  subscribeToPush,
  unsubscribeFromPush,
  type PushConfig,
} from "@/core/notification/push";
import { useLocalSettings } from "@/core/settings";

import { SettingsSection } from "./settings-section";

export function NotificationSettingsPage() {
  const { t } = useI18n();
  const { permission, isSupported, requestPermission, showNotification } =
    useNotification();

  const [settings, setSettings] = useLocalSettings();

  const handleRequestPermission = async () => {
    await requestPermission();
  };

  const handleTestNotification = () => {
    showNotification(t.settings.notification.testTitle, {
      body: t.settings.notification.testBody,
    });
  };

  const handleEnableNotification = async (enabled: boolean) => {
    setSettings("notification", {
      enabled,
    });
  };

  if (!isSupported) {
    return (
      <SettingsSection
        title={t.settings.notification.title}
        description={t.settings.notification.description}
      >
        <p className="text-muted-foreground text-sm">
          {t.settings.notification.notSupported}
        </p>
      </SettingsSection>
    );
  }

  return (
    <SettingsSection
      title={t.settings.notification.title}
      description={
        <div className="flex items-center gap-2">
          <div>{t.settings.notification.description}</div>
          <div>
            <Switch
              aria-label={t.settings.notification.title}
              disabled={permission !== "granted"}
              checked={
                permission === "granted" && settings.notification.enabled
              }
              onCheckedChange={handleEnableNotification}
            />
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {permission === "default" && (
          <Button onClick={handleRequestPermission} variant="default">
            <BellIcon className="mr-2 size-4" />
            {t.settings.notification.requestPermission}
          </Button>
        )}

        {permission === "denied" && (
          <p className="text-muted-foreground rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/50">
            {t.settings.notification.deniedHint}
          </p>
        )}

        {permission === "granted" && settings.notification.enabled && (
          <div className="flex flex-col gap-4">
            <Button onClick={handleTestNotification} variant="outline">
              <BellIcon className="mr-2 size-4" />
              {t.settings.notification.testButton}
            </Button>
          </div>
        )}

        <BackgroundNotifications />
      </div>
    </SettingsSection>
  );
}

/**
 * Web Push: notifications that arrive with the browser closed (fork feature).
 *
 * Kept as its own component because its failure modes are entirely different
 * from the in-tab Notification API above — the common one being that the whole
 * browser API is *absent* on a plain-HTTP LAN origin, which is the fork's
 * documented deployment. Every such case renders a specific explanation with
 * the fix rather than a disabled switch, because a control that silently does
 * nothing is indistinguishable from a broken feature.
 */
function BackgroundNotifications() {
  const { t } = useI18n();
  const support = detectPushSupport();
  const [config, setConfig] = useState<PushConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const push = t.settings.notification.push;

  const refresh = useCallback(async () => {
    setConfig(await fetchPushConfig());
  }, []);

  useEffect(() => {
    if (support.supported) {
      void refresh();
    }
  }, [support.supported, refresh]);

  if (!support.supported) {
    const explanation =
      support.reason === "insecure-context"
        ? push.insecureContext
        : push.unsupported;
    return <Explanation title={push.title} body={explanation} tone="info" />;
  }

  if (config && !config.available) {
    return (
      <Explanation
        title={push.title}
        body={push.unavailable.replace("{reason}", config.reason)}
        tone="warn"
      />
    );
  }

  const subscribed = (config?.subscriptions ?? 0) > 0;
  const isApple =
    typeof navigator !== "undefined" &&
    /iPhone|iPad|iPod/i.test(navigator.userAgent);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setMessage(null);
    try {
      await action();
    } finally {
      setBusy(false);
      await refresh();
    }
  };

  return (
    <div className="border-border flex flex-col gap-3 rounded-md border p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium">{push.title}</div>
          <div className="text-muted-foreground text-sm">
            {push.description}
          </div>
        </div>
        <SmartphoneIcon className="text-muted-foreground size-4 shrink-0" />
      </div>

      {isApple && (
        <p className="text-muted-foreground text-xs">{push.iosHint}</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {!subscribed ? (
          <Button
            variant="default"
            disabled={busy || !config?.public_key}
            onClick={() =>
              run(async () => {
                if (config?.public_key) {
                  await subscribeToPush(config.public_key);
                }
              })
            }
          >
            {push.enable}
          </Button>
        ) : (
          <>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  const result = await sendTestPush();
                  setMessage(
                    result && result.delivered > 0
                      ? push.testSent.replace(
                          "{count}",
                          String(result.delivered),
                        )
                      : push.testFailed,
                  );
                })
              }
            >
              {push.test}
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await unsubscribeFromPush();
                })
              }
            >
              {push.disable}
            </Button>
          </>
        )}
      </div>

      {subscribed && (
        <p className="text-muted-foreground text-xs">
          {push.registered.replace(
            "{count}",
            String(config?.subscriptions ?? 0),
          )}
        </p>
      )}
      {message && <p className="text-muted-foreground text-xs">{message}</p>}
    </div>
  );
}

function Explanation({
  title,
  body,
  tone,
}: {
  title: string;
  body: string;
  tone: "info" | "warn";
}) {
  return (
    <div
      className={
        tone === "warn"
          ? "rounded-md border border-amber-200 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950/50"
          : "border-border rounded-md border p-3"
      }
    >
      <div className="text-sm font-medium">{title}</div>
      <p className="text-muted-foreground mt-1 text-sm">{body}</p>
    </div>
  );
}
