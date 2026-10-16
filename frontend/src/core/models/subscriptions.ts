import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type SubscriptionProvider = "chatgpt" | "grok" | "kimi";
export type SubscriptionConnection = {
  provider: SubscriptionProvider;
  connected: boolean;
  needs_reauth: boolean;
  model_count: number;
  models: { name: string; display_name: string; model: string }[];
  auth_type: "oauth" | "api_key";
  interactive_only: boolean;
  updated_at: number | null;
  account_label?: string | null;
};
export type DeviceSignIn = {
  status: "pending";
  flow_id: string;
  user_code: string;
  verification_uri: string;
  verification_uri_complete: string | null;
  interval: number;
  expires_in: number;
};
type Connected = {
  status: "connected";
  provider: SubscriptionProvider;
  model_count: number;
};

async function request<T>(
  path: string,
  method = "GET",
  body?: object,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/subscriptions${path}`,
    {
      method,
      signal,
      ...(body
        ? {
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }
        : {}),
    },
  );
  if (!response.ok)
    await throwGatewayApiError(response, "Subscription request failed");
  return response.json() as Promise<T>;
}

export const loadSubscriptions = (signal?: AbortSignal) =>
  request<{ providers: SubscriptionConnection[] }>(
    "",
    "GET",
    undefined,
    signal,
  );
export const beginGrokSignIn = () =>
  request<DeviceSignIn>("/grok/connect", "POST", {});
export const pollGrokSignIn = (flowId: string, signal?: AbortSignal) =>
  request<Connected | { status: "pending"; interval: number }>(
    "/grok/poll",
    "POST",
    { flow_id: flowId },
    signal,
  );
export const connectKimiSubscription = (apiKey: string) =>
  request<Connected>("/kimi/connect", "POST", { api_key: apiKey });
export const importChatGPTConnection = (connection: object) =>
  request<Connected>("/chatgpt/connect", "POST", { connection });
export const refreshSubscriptionModels = (provider: SubscriptionProvider) =>
  request<Connected>(`/${provider}/refresh`, "POST", {});
export const disconnectSubscription = (provider: SubscriptionProvider) =>
  request<{
    status: "disconnected";
    provider: SubscriptionProvider;
    revocation_confirmed: boolean;
  }>(`/${provider}`, "DELETE");
export const chatGPTSignInHelperURL = () =>
  `${getBackendBaseURL()}/api/subscriptions/chatgpt/helper`;
