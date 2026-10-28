"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import { MODELS_QUERY_KEY } from "@/core/models/hooks";
import {
  beginChatGPTSignIn,
  beginGrokSignIn,
  chatGPTSignInHelperURL,
  completeChatGPTSignIn,
  connectKimiSubscription,
  disconnectSubscription,
  importChatGPTConnection,
  loadSubscriptions,
  pollGrokSignIn,
  refreshSubscriptionModels,
  updateGrokFeatures,
  type ChatGPTSignIn,
  type DeviceSignIn,
  type GrokFeature,
  type GrokFeatureName,
  type SubscriptionProvider,
} from "@/core/models/subscriptions";
import { VOICE_CONFIG_QUERY_KEY } from "@/core/voice-input/read-aloud";

const names = { chatgpt: "ChatGPT", grok: "Grok", kimi: "Kimi Code" };

export function SubscriptionSettings({ userId }: { userId: string }) {
  const { t } = useI18n();
  const text = t.settings.subscriptions;
  const client = useQueryClient();
  const catalog = useQuery({
    queryKey: ["subscriptions", userId],
    queryFn: ({ signal }) => loadSubscriptions(signal),
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [key, setKey] = useState("");
  const [chatgpt, setChatgpt] = useState(false);
  const [chatgptFlow, setChatgptFlow] = useState<ChatGPTSignIn | null>(null);
  const [callbackURL, setCallbackURL] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [flow, setFlow] = useState<DeviceSignIn | null>(null);

  async function refresh() {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["subscriptions", userId] }),
      client.invalidateQueries({ queryKey: MODELS_QUERY_KEY }),
      // Grok voice decides whether answers offer read-aloud.
      client.invalidateQueries({ queryKey: VOICE_CONFIG_QUERY_KEY }),
    ]);
  }

  async function run(action: () => Promise<unknown>, refreshCatalog = true) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch {
      // Provider errors and imported JSON may contain credentials. Keep UI errors generic.
      setError(text.failed);
    } finally {
      if (refreshCatalog) {
        try {
          // A provider can save a new grant before discovery temporarily fails.
          await refresh();
        } catch {
          setError(text.failed);
        }
      }
      setBusy(false);
    }
  }

  function closeChatGPT() {
    setCallbackURL("");
    setChatgptFlow(null);
    setAdvanced(false);
    setChatgpt(false);
  }

  async function startChatGPT(newAccount = false) {
    setCallbackURL("");
    setChatgptFlow(null);
    setAdvanced(false);
    setChatgpt(true);
    await run(
      async () => setChatgptFlow(await beginChatGPTSignIn(newAccount)),
      false,
    );
  }

  useEffect(() => {
    if (!flow) return;
    const controller = new AbortController();
    const timeout = setTimeout(
      () => {
        void pollGrokSignIn(flow.flow_id, controller.signal)
          .then(async (result) => {
            if (controller.signal.aborted) return;
            if (result.status === "connected") {
              setFlow(null);
              await Promise.all([
                client.invalidateQueries({
                  queryKey: ["subscriptions", userId],
                }),
                client.invalidateQueries({ queryKey: MODELS_QUERY_KEY }),
              ]);
            } else {
              setFlow({ ...flow, interval: result.interval });
            }
          })
          .catch(() => {
            if (!controller.signal.aborted) {
              setFlow(null);
              setError(text.failed);
            }
          });
      },
      Math.max(1, flow.interval) * 1000,
    );
    return () => {
      clearTimeout(timeout);
      controller.abort();
    };
  }, [flow, client, userId, text.failed]);

  async function importFile(file: File | undefined) {
    if (!file) return;
    if (file.size > 65536) {
      setError(text.invalidFile);
      return;
    }
    let connection: object;
    try {
      const parsed: unknown = JSON.parse(await file.text());
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error("invalid");
      connection = parsed;
    } catch {
      setError(text.invalidFile);
      return;
    }
    await run(async () => {
      await importChatGPTConnection(connection);
      closeChatGPT();
    });
  }

  return (
    <section
      aria-label={text.title}
      className="space-y-3 rounded-lg border p-4"
    >
      <h3 className="font-semibold">{text.title}</h3>
      <p className="text-muted-foreground text-sm">{text.description}</p>
      {!chatgpt && (error || catalog.error) && (
        <p role="alert">{error || text.failed}</p>
      )}
      {(Object.keys(names) as SubscriptionProvider[]).map((provider) => {
        const connection = catalog.data?.providers.find(
          (item) => item.provider === provider,
        );
        return (
          <div key={provider} className="space-y-2 border-t pt-3">
            <h4 className="font-medium">{names[provider]}</h4>
            {connection?.account_label && (
              <p className="text-sm">{connection.account_label}</p>
            )}
            <p className="text-muted-foreground text-sm">
              {connection?.needs_reauth
                ? text.reauth
                : connection?.connected
                  ? text.connected
                  : text.disconnected}
            </p>
            {provider === "chatgpt" && (
              <Button disabled={busy} onClick={() => void startChatGPT()}>
                {text.chatgptConnect}
              </Button>
            )}
            {provider === "grok" && (
              <Button
                disabled={busy || !!flow}
                onClick={() =>
                  void run(async () => setFlow(await beginGrokSignIn()))
                }
              >
                {text.grokConnect}
              </Button>
            )}
            {provider === "grok" && flow && (
              <div role="status" className="space-y-2">
                <p>{text.deviceInstructions}</p>
                <p className="font-mono text-lg">{flow.user_code}</p>
                <a
                  className="underline"
                  href={flow.verification_uri_complete ?? flow.verification_uri}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {text.deviceLink}
                </a>
                <p>{text.waiting}</p>
                <Button variant="outline" onClick={() => setFlow(null)}>
                  {text.close}
                </Button>
              </div>
            )}
            {provider === "kimi" && (
              <form
                className="space-y-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void run(async () => {
                    await connectKimiSubscription(key);
                    setKey("");
                  });
                }}
              >
                <p className="text-muted-foreground text-sm">{text.kimiNote}</p>
                <label className="block space-y-1">
                  <span>{text.kimiKey}</span>
                  <Input
                    type="password"
                    autoComplete="new-password"
                    value={key}
                    onChange={(event) => setKey(event.target.value)}
                    disabled={busy}
                  />
                </label>
                <Button type="submit" disabled={busy || !key.trim()}>
                  {text.kimiConnect}
                </Button>
              </form>
            )}
            {(connection?.connected === true ||
              connection?.needs_reauth === true) && (
              <>
                <p className="text-sm">
                  {text.models}: {connection.model_count}
                </p>
                {connection.models.length ? (
                  <ul className="text-muted-foreground text-sm">
                    {connection.models.map((model) => (
                      <li key={model.name}>{model.display_name}</li>
                    ))}
                  </ul>
                ) : (
                  <p>{text.none}</p>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    disabled={busy || connection.needs_reauth}
                    onClick={() =>
                      void run(() => refreshSubscriptionModels(provider))
                    }
                  >
                    {text.refresh}
                  </Button>
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        const result = await disconnectSubscription(provider);
                        if (!result.revocation_confirmed)
                          setNotice(text.revocationPending);
                      })
                    }
                  >
                    {text.disconnect}
                  </Button>
                </div>
              </>
            )}
            {provider === "grok" &&
              connection?.connected === true &&
              !!connection.features?.length && (
                <GrokFeatures
                  features={connection.features}
                  busy={busy}
                  onChange={(name, enabled) =>
                    void run(() => updateGrokFeatures({ [name]: enabled }))
                  }
                />
              )}
            {provider === "chatgpt" && connection?.connected && (
              <a
                href="https://chatgpt.com/settings/usage"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm underline"
              >
                {text.usage}
              </a>
            )}
          </div>
        );
      })}
      {notice && <p role="status">{notice}</p>}
      <Dialog
        open={chatgpt}
        onOpenChange={(open) => {
          if (!open && !busy) closeChatGPT();
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{text.browserTitle}</DialogTitle>
            <DialogDescription>{text.browserDescription}</DialogDescription>
          </DialogHeader>
          <p>{text.browserInstructions}</p>
          {chatgptFlow && (
            <a
              href={chatgptFlow.authorization_url}
              target="_blank"
              rel="noopener noreferrer"
              referrerPolicy="no-referrer"
              className="underline"
            >
              {text.browserOpen}
            </a>
          )}
          <p className="text-muted-foreground text-sm">{text.browserExpiry}</p>
          {error && <p role="alert">{error}</p>}
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (!chatgptFlow || !callbackURL.trim()) return;
              void run(async () => {
                await completeChatGPTSignIn(
                  chatgptFlow.flow_id,
                  callbackURL.trim(),
                );
                closeChatGPT();
              });
            }}
          >
            <label className="block space-y-1">
              <span>{text.callbackLabel}</span>
              <Input
                type="password"
                autoComplete="off"
                autoCorrect="off"
                spellCheck={false}
                inputMode="url"
                maxLength={8192}
                value={callbackURL}
                disabled={busy || !chatgptFlow}
                onChange={(event) => setCallbackURL(event.target.value)}
              />
            </label>
            <div className="flex flex-wrap gap-2">
              <Button
                type="submit"
                disabled={busy || !chatgptFlow || !callbackURL.trim()}
              >
                {text.callbackComplete}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => void startChatGPT()}
              >
                {text.browserRestart}
              </Button>
              {!catalog.data?.providers.some(
                (connection) =>
                  connection.provider === "chatgpt" &&
                  (connection.connected || connection.needs_reauth),
              ) && (
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void startChatGPT(true)}
                >
                  {text.browserOtherAccount}
                </Button>
              )}
            </div>
          </form>
          <Button
            variant="ghost"
            disabled={busy}
            aria-expanded={advanced}
            onClick={() => setAdvanced(!advanced)}
          >
            {text.advancedHelper}
          </Button>
          {advanced && (
            <div className="space-y-3 border-t pt-3">
              <h4 className="font-medium">{text.helperTitle}</h4>
              <p>{text.helperDescription}</p>
              <a href={chatGPTSignInHelperURL()} download className="underline">
                {text.helperDownload}
              </a>
              <p>{text.helperRun}</p>
              <code className="text-sm break-all">
                uv run deerflow-chatgpt-login.py
              </code>
              <p>{text.helperImport}</p>
              <label className="block space-y-1">
                <span>{text.connectionFile}</span>
                <Input
                  type="file"
                  accept="application/json,.json"
                  disabled={busy}
                  onChange={(event) => {
                    void importFile(event.target.files?.[0]);
                    event.target.value = "";
                  }}
                />
              </label>
            </div>
          )}
          <Button variant="outline" disabled={busy} onClick={closeChatGPT}>
            {busy ? text.working : text.close}
          </Button>
        </DialogContent>
      </Dialog>
    </section>
  );
}

/**
 * Per-feature switches for what the Grok grant reaches beyond chat.
 *
 * Every switch starts off. A feature xAI refused for this plan (401/403 at
 * connect or Refresh) cannot be switched on, but one already on can still be
 * switched off; "couldn't check" stays switchable so an outage never locks a
 * feature the plan does include.
 */
function GrokFeatures({
  features,
  busy,
  onChange,
}: {
  features: GrokFeature[];
  busy: boolean;
  onChange: (name: GrokFeatureName, enabled: boolean) => void;
}) {
  const { t } = useI18n();
  const text = t.settings.subscriptions;
  const labels: Record<GrokFeatureName, [string, string]> = {
    image: [text.grokFeatureImage, text.grokFeatureImageNote],
    video: [text.grokFeatureVideo, text.grokFeatureVideoNote],
    x_search: [text.grokFeatureXSearch, text.grokFeatureXSearchNote],
    voice: [text.grokFeatureVoice, text.grokFeatureVoiceNote],
  };
  const availability = {
    available: text.grokAvailable,
    not_on_plan: text.grokNotOnPlan,
    unknown: text.grokUnknown,
  };
  return (
    <fieldset className="space-y-2 rounded-md border p-3">
      <legend className="px-1 font-medium">{text.grokFeaturesTitle}</legend>
      <p className="text-muted-foreground text-sm">
        {text.grokFeaturesDescription}
      </p>
      <ul className="space-y-3">
        {features.map((feature) => {
          if (!(feature.name in labels)) return null;
          const [label, note] = labels[feature.name];
          const id = `grok-feature-${feature.name}`;
          const locked = feature.availability === "not_on_plan";
          return (
            <li
              key={feature.name}
              className="flex items-start justify-between gap-3"
            >
              <div className="min-w-0 space-y-0.5">
                <label htmlFor={id} className="text-sm font-medium">
                  {label}
                </label>
                <p className="text-muted-foreground text-xs">{note}</p>
                <p className="text-xs" data-testid={`${id}-availability`}>
                  {availability[feature.availability] ?? text.grokUnknown}
                  {locked && ` — ${text.grokNotOnPlanHint}`}
                </p>
              </div>
              <Switch
                id={id}
                checked={feature.enabled}
                disabled={busy || (locked && !feature.enabled)}
                onCheckedChange={(checked) => onChange(feature.name, checked)}
              />
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}
