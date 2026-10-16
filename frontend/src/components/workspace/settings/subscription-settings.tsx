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
import { useI18n } from "@/core/i18n/hooks";
import { MODELS_QUERY_KEY } from "@/core/models/hooks";
import {
  beginGrokSignIn,
  chatGPTSignInHelperURL,
  connectKimiSubscription,
  disconnectSubscription,
  importChatGPTConnection,
  loadSubscriptions,
  pollGrokSignIn,
  refreshSubscriptionModels,
  type DeviceSignIn,
  type SubscriptionProvider,
} from "@/core/models/subscriptions";

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
  const [flow, setFlow] = useState<DeviceSignIn | null>(null);

  async function refresh() {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["subscriptions", userId] }),
      client.invalidateQueries({ queryKey: MODELS_QUERY_KEY }),
    ]);
  }

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      await refresh();
    } catch {
      // Provider errors and imported JSON may contain credentials. Keep UI errors generic.
      setError(text.failed);
    } finally {
      setBusy(false);
    }
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
      setChatgpt(false);
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
              <Button
                disabled={busy}
                onClick={() => {
                  setError("");
                  setChatgpt(true);
                }}
              >
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
      <Dialog open={chatgpt} onOpenChange={setChatgpt}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{text.helperTitle}</DialogTitle>
            <DialogDescription>{text.helperDescription}</DialogDescription>
          </DialogHeader>
          <a href={chatGPTSignInHelperURL()} download className="underline">
            {text.helperDownload}
          </a>
          <p>{text.helperRun}</p>
          <code className="text-sm break-all">
            uv run deerflow-chatgpt-login.py
          </code>
          <p>{text.helperImport}</p>
          {error && <p role="alert">{error}</p>}
          <label className="space-y-1">
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
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => setChatgpt(false)}
          >
            {busy ? text.working : text.close}
          </Button>
        </DialogContent>
      </Dialog>
    </section>
  );
}
