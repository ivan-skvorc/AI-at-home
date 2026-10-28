import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type SubscriptionProvider = "chatgpt" | "grok" | "kimi";
export type GrokFeatureName = "image" | "video" | "x_search" | "voice";
/** Only `not_on_plan` (a 401/403 from xAI) locks a switch; `unknown` stays switchable. */
export type GrokFeatureAvailability = "available" | "not_on_plan" | "unknown";
export type GrokFeature = {
  name: GrokFeatureName;
  enabled: boolean;
  availability: GrokFeatureAvailability;
};
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
  /** Grok only, and only while connected; absent from older Gateways. */
  features?: GrokFeature[];
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
export type ChatGPTSignIn = {
  status: "pending";
  flow_id: string;
  authorization_url: string;
  redirect_uri: string;
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
export async function beginChatGPTSignIn(
  newAccount = false,
): Promise<ChatGPTSignIn> {
  const flow = await request<ChatGPTSignIn>(
    "/chatgpt/start",
    "POST",
    newAccount ? { new_account: true } : {},
  );
  const authorization = new URL(flow.authorization_url);
  if (
    authorization.origin !== "https://auth.openai.com" ||
    authorization.pathname !== "/api/accounts/authorize" ||
    authorization.username ||
    authorization.password ||
    authorization.hash ||
    authorization.searchParams.has("id_token_hint")
  )
    throw new Error("Invalid ChatGPT sign-in response");
  return flow;
}
export const completeChatGPTSignIn = (flowId: string, callbackURL: string) =>
  request<Connected>("/chatgpt/complete", "POST", {
    flow_id: flowId,
    callback_url: callbackURL,
  });
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
export const updateGrokFeatures = (
  features: Partial<Record<GrokFeatureName, boolean>>,
) =>
  request<{ provider: "grok"; features: GrokFeature[] }>(
    "/grok/features",
    "PATCH",
    { features },
  );
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
