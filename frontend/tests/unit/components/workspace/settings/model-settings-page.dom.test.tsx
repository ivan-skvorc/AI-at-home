import { afterEach, beforeEach, expect, test, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import { ModelSettingsPage } from "@/components/workspace/settings/model-settings-page";
import { GatewayApiError } from "@/core/api/errors";
import { useAuth } from "@/core/auth/AuthProvider";
import { enUS } from "@/core/i18n/locales/en-US";
import { loadModels } from "@/core/models/api";
import { useModels } from "@/core/models/hooks";
import type * as Management from "@/core/models/management";
import {
  loadManagedModels,
  loadManagedModelProviders,
  modelDraft,
  saveManagedModel,
  testManagedModel,
  type ManagedModel,
} from "@/core/models/management";
import {
  beginChatGPTSignIn,
  completeChatGPTSignIn,
  loadSubscriptions,
  beginGrokSignIn,
  pollGrokSignIn,
  connectKimiSubscription,
  importChatGPTConnection,
  updateGrokFeatures,
} from "@/core/models/subscriptions";
import { isStaticWebsiteOnly } from "@/core/static-mode";

rs.mock("@/core/models/api", () => ({ loadModels: rs.fn() }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: rs.fn() }));
rs.mock("@/core/auth/AuthProvider", () => ({ useAuth: rs.fn() }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/models/subscriptions", () => ({
  beginChatGPTSignIn: rs.fn(),
  completeChatGPTSignIn: rs.fn(),
  loadSubscriptions: rs.fn(),
  beginGrokSignIn: rs.fn(),
  pollGrokSignIn: rs.fn(),
  connectKimiSubscription: rs.fn(),
  importChatGPTConnection: rs.fn(),
  refreshSubscriptionModels: rs.fn(),
  disconnectSubscription: rs.fn(),
  updateGrokFeatures: rs.fn(),
  chatGPTSignInHelperURL: () => "/api/subscriptions/chatgpt/helper",
}));
rs.mock("@/core/models/management", () => ({
  ...rs.requireActual<typeof Management>("@/core/models/management"),
  loadManagedModels: rs.fn(),
  loadManagedModelProviders: rs.fn(),
  saveManagedModel: rs.fn(),
  testManagedModel: rs.fn(),
}));

const existing: ManagedModel = {
  ...modelDraft(),
  name: "custom",
  provider: "openai-compatible",
  model: "test",
  base_url: "https://example.com/v1",
  display_name: "Custom",
  source: "managed",
  has_api_key: true,
  revision: "v1",
};
const auth = (role: "admin" | "user") =>
  ({ user: { id: "admin-id", system_role: role } }) as ReturnType<
    typeof useAuth
  >;

beforeEach(() => {
  rs.mocked(isStaticWebsiteOnly).mockReturnValue(false);
  rs.mocked(loadModels).mockResolvedValue({
    models: [],
    token_usage: { enabled: false },
  });
  rs.mocked(useAuth).mockReturnValue(auth("admin"));
  rs.mocked(loadManagedModelProviders).mockResolvedValue({
    providers: [
      {
        id: "openai",
        display_name: "OpenAI",
        requires_api_key: true,
        custom_endpoint: false,
      },
      {
        id: "anthropic",
        display_name: "Anthropic",
        requires_api_key: true,
        custom_endpoint: false,
      },
      {
        id: "openai-compatible",
        display_name: "Custom OpenAI-compatible",
        requires_api_key: false,
        custom_endpoint: true,
      },
    ],
  });
  rs.mocked(loadManagedModels).mockResolvedValue({ models: [existing] });
  rs.mocked(loadSubscriptions).mockResolvedValue({ providers: [] });
  rs.mocked(beginChatGPTSignIn).mockResolvedValue({
    status: "pending",
    flow_id: "chatgpt-flow",
    authorization_url:
      "https://auth.openai.com/api/accounts/authorize?state=state&code_challenge=challenge&nonce=nonce",
    redirect_uri: "http://127.0.0.1:1455/auth/callback",
    expires_in: 600,
  });
  rs.mocked(saveManagedModel).mockResolvedValue({
    ...existing,
    revision: "v2",
  });
});
afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

function CurrentModelPicker() {
  const { models } = useModels();
  return (
    <select aria-label="Chat model picker">
      {models.map((model) => (
        <option key={model.name}>{model.display_name ?? model.name}</option>
      ))}
    </select>
  );
}

function mount(withPicker = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  client.setQueryData(["models"], {
    models: [],
    token_usage: { enabled: false },
  });
  render(
    <QueryClientProvider client={client}>
      <ModelSettingsPage />
      {withPicker && <CurrentModelPicker />}
    </QueryClientProvider>,
  );
  return client;
}

test("non-admin cannot load credentials configuration or add models", () => {
  rs.mocked(useAuth).mockReturnValue(auth("user"));
  mount();
  expect(screen.queryByRole("button", { name: "Add model" })).toBeNull();
  expect(loadManagedModels).not.toHaveBeenCalled();
  expect(loadManagedModelProviders).not.toHaveBeenCalled();
  expect(loadSubscriptions).not.toHaveBeenCalled();
  expect(screen.queryByRole("heading", { name: "Subscriptions" })).toBeNull();
});

test("subscription device sign-in refreshes the picker and keys are cleared after saving", async () => {
  const client = mount();
  expect(
    await screen.findByRole("heading", { name: "Subscriptions" }),
  ).toBeTruthy();
  rs.mocked(beginGrokSignIn).mockResolvedValue({
    status: "pending",
    flow_id: "flow",
    user_code: "CODE",
    verification_uri: "https://accounts.x.ai/device",
    verification_uri_complete: null,
    interval: 1,
    expires_in: 600,
  });
  rs.mocked(pollGrokSignIn).mockResolvedValue({
    status: "connected",
    provider: "grok",
    model_count: 2,
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in to Grok" }));
  expect(await screen.findByText("CODE")).toBeTruthy();
  expect(
    screen
      .getByRole("link", { name: "Open Grok sign-in" })
      .getAttribute("href"),
  ).toBe("https://accounts.x.ai/device");
  await waitFor(() => expect(pollGrokSignIn).toHaveBeenCalledTimes(1), {
    timeout: 3000,
  });
  await waitFor(() =>
    expect(client.getQueryState(["models"])?.isInvalidated).toBe(true),
  );
  rs.mocked(connectKimiSubscription).mockResolvedValue({
    status: "connected",
    provider: "kimi",
    model_count: 1,
  });
  const keyInput = screen.getByLabelText<HTMLInputElement>(
    "Kimi Code subscription key",
  );
  fireEvent.change(keyInput, { target: { value: "private-key" } });
  fireEvent.click(screen.getByRole("button", { name: "Connect Kimi Code" }));
  await waitFor(() => expect(keyInput.value).toBe(""));
  expect(connectKimiSubscription).toHaveBeenCalledWith("private-key");
});

test("Grok features start off, keep plan refusals locked, and refresh read-aloud", async () => {
  const text = enUS.settings.subscriptions;
  rs.mocked(loadSubscriptions).mockResolvedValue({
    providers: [
      {
        provider: "grok",
        connected: true,
        needs_reauth: false,
        model_count: 0,
        models: [],
        auth_type: "oauth",
        interactive_only: false,
        updated_at: 1,
        features: [
          { name: "image", enabled: false, availability: "available" },
          { name: "video", enabled: false, availability: "unknown" },
          { name: "x_search", enabled: false, availability: "available" },
          { name: "voice", enabled: false, availability: "not_on_plan" },
        ],
      },
    ],
  });
  rs.mocked(updateGrokFeatures).mockResolvedValue({
    provider: "grok",
    features: [],
  });
  const client = mount();
  client.setQueryData(["voice-config"], { read_aloud: false });
  const image = await screen.findByRole("switch", {
    name: text.grokFeatureImage,
  });
  expect(image.getAttribute("aria-checked")).toBe("false");
  const voice = screen.getByRole("switch", { name: text.grokFeatureVoice });
  expect(voice.hasAttribute("disabled")).toBe(true);
  expect(
    screen.getByTestId("grok-feature-voice-availability").textContent,
  ).toContain(text.grokNotOnPlan);
  // "Couldn't check" must stay switchable: an outage never locks a feature.
  expect(
    screen
      .getByRole("switch", { name: text.grokFeatureVideo })
      .hasAttribute("disabled"),
  ).toBe(false);
  fireEvent.click(image);
  await waitFor(() =>
    expect(updateGrokFeatures).toHaveBeenCalledWith({ image: true }),
  );
  await waitFor(() =>
    expect(client.getQueryState(["voice-config"])?.isInvalidated).toBe(true),
  );
});

test("remote ChatGPT browser sign-in keeps callbacks private and preserves the helper fallback", async () => {
  const client = mount();
  fireEvent.click(
    screen.getByRole("button", { name: "Continue with ChatGPT" }),
  );
  const signIn = await screen.findByRole("link", {
    name: "Open ChatGPT sign-in",
  });
  expect(signIn.getAttribute("href")).toBe(
    "https://auth.openai.com/api/accounts/authorize?state=state&code_challenge=challenge&nonce=nonce",
  );
  expect(signIn.getAttribute("rel")).toBe("noopener noreferrer");
  expect(signIn.getAttribute("referrerpolicy")).toBe("no-referrer");
  const callback = screen.getByLabelText<HTMLInputElement>(
    "ChatGPT return address",
  );
  expect(callback.type).toBe("password");
  expect(callback.autocomplete).toBe("off");
  expect(client.getQueryState(["models"])?.isInvalidated).toBe(false);
  const callbackURL =
    "http://127.0.0.1:1455/auth/callback?state=state&code=private-one-time-code&client_id=oaiapp_test";
  rs.mocked(completeChatGPTSignIn).mockRejectedValueOnce(
    new Error("private-one-time-code in provider failure"),
  );
  fireEvent.change(callback, { target: { value: callbackURL } });
  fireEvent.click(screen.getByRole("button", { name: "Complete sign-in" }));
  const dialog = screen.getByRole("dialog");
  expect((await within(dialog).findByRole("alert")).textContent).toBe(
    enUS.settings.subscriptions.failed,
  );
  expect(
    within(dialog).queryByText("private-one-time-code in provider failure"),
  ).toBeNull();
  await waitFor(() =>
    expect(client.getQueryState(["models"])?.isInvalidated).toBe(true),
  );
  client.setQueryData(["models"], { models: [] });
  fireEvent.click(screen.getByRole("button", { name: "Start a new sign-in" }));
  await waitFor(() => expect(beginChatGPTSignIn).toHaveBeenCalledTimes(2));
  expect(callback.value).toBe("");
  await screen.findByRole("link", { name: "Open ChatGPT sign-in" });
  rs.mocked(completeChatGPTSignIn).mockResolvedValueOnce({
    status: "connected",
    provider: "chatgpt",
    model_count: 1,
  });
  fireEvent.change(callback, { target: { value: callbackURL } });
  fireEvent.click(screen.getByRole("button", { name: "Complete sign-in" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(completeChatGPTSignIn).toHaveBeenLastCalledWith(
    "chatgpt-flow",
    callbackURL,
  );
  expect(client.getQueryState(["models"])?.isInvalidated).toBe(true);
  fireEvent.click(
    screen.getByRole("button", { name: "Continue with ChatGPT" }),
  );
  expect(
    screen.getByLabelText<HTMLInputElement>("ChatGPT return address").value,
  ).toBe("");
  const otherAccount = screen.getByRole<HTMLButtonElement>("button", {
    name: "Use another ChatGPT account",
  });
  await waitFor(() => expect(otherAccount.disabled).toBe(false));
  fireEvent.click(otherAccount);
  await waitFor(() =>
    expect(beginChatGPTSignIn).toHaveBeenLastCalledWith(true),
  );
  const advanced = screen.getByRole<HTMLButtonElement>("button", {
    name: "Advanced: local sign-in helper",
  });
  await waitFor(() => expect(advanced.disabled).toBe(false));
  fireEvent.click(advanced);
  expect(
    screen
      .getByRole("link", { name: "Download sign-in helper" })
      .getAttribute("href"),
  ).toBe("/api/subscriptions/chatgpt/helper");
  expect(screen.getByLabelText("ChatGPT connection file")).toBeTruthy();
  rs.mocked(importChatGPTConnection).mockRejectedValueOnce(
    new Error("private-refresh-token in provider failure"),
  );
  fireEvent.change(screen.getByLabelText("ChatGPT connection file"), {
    target: {
      files: [
        new File(
          [JSON.stringify({ access_token: "private-access-token" })],
          "connection.json",
          {
            type: "application/json",
          },
        ),
      ],
    },
  });
  expect(
    (await within(screen.getByRole("dialog")).findByRole("alert")).textContent,
  ).toBe(enUS.settings.subscriptions.failed);
  expect(rs.mocked(importChatGPTConnection).mock.calls[0]?.[0]).toEqual({
    access_token: "private-access-token",
  });
  expect(
    within(screen.getByRole("dialog")).queryByText(
      "private-refresh-token in provider failure",
    ),
  ).toBeNull();
  fireEvent.click(screen.getByText("Close", { selector: "button" }));
  rs.mocked(connectKimiSubscription).mockRejectedValueOnce(
    new Error("private-key in provider failure"),
  );
  fireEvent.change(screen.getByLabelText("Kimi Code subscription key"), {
    target: { value: "private-key" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Connect Kimi Code" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByText("private-key in provider failure")).toBeNull();
  expect(importChatGPTConnection).toHaveBeenCalledTimes(1);
});

test("editing preserves saved key and refreshes chat catalog after saving", async () => {
  const client = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  const input = screen.getByLabelText<HTMLInputElement>("API Key");
  expect(input.value).toBe("");
  fireEvent.change(screen.getByLabelText("Display name"), {
    target: { value: "Updated" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveManagedModel).toHaveBeenCalledTimes(1));
  expect(rs.mocked(saveManagedModel).mock.calls[0]?.[0]).toMatchObject({
    config: { display_name: "Updated" },
    expected_revision: "v1",
  });
  expect(
    rs.mocked(saveManagedModel).mock.calls[0]?.[0].config,
  ).not.toHaveProperty("api_key");
  await waitFor(() =>
    expect(client.getQueryState(["models"])?.isInvalidated).toBe(true),
  );
});

test("failed save keeps draft open and displays conflict", async () => {
  rs.mocked(saveManagedModel).mockRejectedValueOnce(
    new Error("Model changed; reload before saving"),
  );
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  fireEvent.change(screen.getByLabelText<HTMLInputElement>("API Key"), {
    target: { value: "replacement" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(
    await screen.findByText("Model changed; reload before saving"),
  ).toBeTruthy();
  expect(screen.getByLabelText<HTMLInputElement>("API Key").value).toBe(
    "replacement",
  );
});

test("connection test never saves and supports explicit key removal", async () => {
  rs.mocked(testManagedModel).mockResolvedValueOnce({
    ok: true,
    message: "success",
  });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  fireEvent.click(screen.getByLabelText("Remove the saved API key"));
  fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
  expect(await screen.findByText(enUS.settings.models.success)).toBeTruthy();
  expect(rs.mocked(testManagedModel).mock.calls[0]?.[0].config.api_key).toBe(
    "",
  );
  expect(saveManagedModel).not.toHaveBeenCalled();
});

test("new preset needs only provider, API key and arbitrary model ID", async () => {
  const client = mount();
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Add model" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Add model" }));
  expect(screen.getByRole("combobox", { name: "Provider" }).textContent).toBe(
    "OpenAI",
  );
  expect(screen.queryByLabelText("Base URL")).toBeNull();
  expect(screen.queryByLabelText("Unique name")).toBeNull();
  fireEvent.change(screen.getByLabelText("API Key"), {
    target: { value: "test-key" },
  });
  fireEvent.change(screen.getByLabelText("Model ID"), {
    target: { value: "org/任意 model" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveManagedModel).toHaveBeenCalledTimes(1));
  const body = rs.mocked(saveManagedModel).mock.calls[0]![0];
  expect(body.config).toMatchObject({
    provider: "openai",
    api_key: "test-key",
    model: "org/任意 model",
    enabled: true,
  });
  expect(body.config).not.toHaveProperty("base_url");
  await waitFor(() =>
    expect(client.getQueryState(["models"])?.isInvalidated).toBe(true),
  );
});

async function selectProvider(name: string) {
  fireEvent.pointerDown(screen.getByRole("combobox", { name: "Provider" }), {
    button: 0,
    ctrlKey: false,
    pointerType: "mouse",
  });
  fireEvent.click(await screen.findByRole("option", { name }));
}

test("switching providers clears test status and cannot reuse a saved key", async () => {
  rs.mocked(testManagedModel).mockResolvedValue({
    ok: true,
    message: "success",
  });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
  await screen.findByText(enUS.settings.models.success);
  await selectProvider("Anthropic");
  expect(screen.queryByText(enUS.settings.models.success)).toBeNull();
  expect(screen.queryByLabelText("Base URL")).toBeNull();
  expect(screen.getByLabelText<HTMLInputElement>("API Key").value).toBe("");
  expect(
    screen.queryByPlaceholderText(enUS.settings.models.keepKey),
  ).toBeNull();
  fireEvent.change(screen.getByLabelText("API Key"), {
    target: { value: "new-provider-key" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveManagedModel).toHaveBeenCalledTimes(1));
  expect(rs.mocked(saveManagedModel).mock.calls[0]![0]).toMatchObject({
    config: {
      name: "custom",
      provider: "anthropic",
      api_key: "new-provider-key",
    },
    expected_revision: "v1",
  });
  expect(
    rs.mocked(saveManagedModel).mock.calls[0]![0].config,
  ).not.toHaveProperty("base_url");
});

test("reverting a provider switch preserves the saved key", async () => {
  rs.mocked(loadManagedModels).mockResolvedValue({
    models: [{ ...existing, provider: "openai", base_url: null }],
  });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  await selectProvider("Anthropic");
  await selectProvider("OpenAI");

  expect(screen.queryByText(enUS.settings.models.providerChanged)).toBeNull();
  expect(
    screen.getByPlaceholderText(enUS.settings.models.keepKey),
  ).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveManagedModel).toHaveBeenCalledTimes(1));
  expect(
    rs.mocked(saveManagedModel).mock.calls[0]![0].config,
  ).not.toHaveProperty("api_key");
});

test("custom endpoint is separate and allows no authentication", async () => {
  mount();
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "Add model" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "Add model" }));
  await selectProvider("Custom OpenAI-compatible");
  fireEvent.change(screen.getByLabelText("Base URL"), {
    target: { value: "http://localhost:9000/v1" },
  });
  fireEvent.change(screen.getByLabelText("Model ID"), {
    target: { value: "local-model" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveManagedModel).toHaveBeenCalledTimes(1));
  expect(rs.mocked(saveManagedModel).mock.calls[0]![0].config).toMatchObject({
    provider: "openai-compatible",
    base_url: "http://localhost:9000/v1",
  });
});

test("reverting a custom endpoint edit preserves the saved key", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  const endpoint = screen.getByLabelText("Base URL");
  fireEvent.change(endpoint, {
    target: { value: "https://other.example.com/v1" },
  });
  fireEvent.change(endpoint, {
    target: { value: existing.base_url },
  });

  expect(screen.queryByText(enUS.settings.models.providerChanged)).toBeNull();
  expect(
    screen.getByPlaceholderText(enUS.settings.models.keepKey),
  ).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveManagedModel).toHaveBeenCalledTimes(1));
  expect(
    rs.mocked(saveManagedModel).mock.calls[0]![0].config,
  ).not.toHaveProperty("api_key");
});

test("preset edits retain stable ID, leave key blank and preserve advanced overrides", async () => {
  rs.mocked(loadManagedModels).mockResolvedValue({
    models: [
      {
        ...existing,
        provider: "openai",
        base_url: null,
        context_window: 12345,
        supports_vision: true,
      },
    ],
  });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  expect(screen.getByLabelText<HTMLInputElement>("Unique name").disabled).toBe(
    true,
  );
  expect(screen.queryByLabelText("Base URL")).toBeNull();
  fireEvent.change(screen.getByLabelText("Model ID"), {
    target: { value: "new/arbitrary-model" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveManagedModel).toHaveBeenCalledTimes(1));
  expect(rs.mocked(saveManagedModel).mock.calls[0]![0].config).toMatchObject({
    name: "custom",
    model: "new/arbitrary-model",
    supports_vision: true,
    context_window: 12345,
  });
  expect(
    rs.mocked(saveManagedModel).mock.calls[0]![0].config,
  ).not.toHaveProperty("api_key");
});

test("preset key clearing requires disabling and does not save a password mask", async () => {
  rs.mocked(loadManagedModels).mockResolvedValue({
    models: [{ ...existing, provider: "openai", base_url: null }],
  });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  fireEvent.click(screen.getByLabelText("Remove the saved API key"));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(
    await screen.findByText(enUS.settings.models.missing_api_key),
  ).toBeTruthy();
  expect(saveManagedModel).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText("Enabled"));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(saveManagedModel).toHaveBeenCalledTimes(1));
  expect(rs.mocked(saveManagedModel).mock.calls[0]![0].config).toMatchObject({
    api_key: "",
    enabled: false,
  });
});

test("enable/disable uses the existing revision and invalidates both catalogs", async () => {
  const client = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Disable" }));
  await waitFor(() => expect(saveManagedModel).toHaveBeenCalledTimes(1));
  expect(rs.mocked(saveManagedModel).mock.calls[0]![0]).toMatchObject({
    config: { name: "custom", enabled: false },
    expected_revision: "v1",
  });
  expect(
    rs.mocked(saveManagedModel).mock.calls[0]![0].config,
  ).not.toHaveProperty("api_key");
  await waitFor(() =>
    expect(client.getQueryState(["models"])?.isInvalidated).toBe(true),
  );
  expect(loadManagedModels).toHaveBeenCalledTimes(2);
});

test("provider loading failures are visible and retryable", async () => {
  rs.mocked(loadManagedModelProviders).mockRejectedValueOnce(
    new Error("offline"),
  );
  mount();
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(
    screen.getByRole<HTMLButtonElement>("button", { name: "Add model" })
      .disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Reload" }));
  await waitFor(() =>
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Add model" })
        .disabled,
    ).toBe(false),
  );
});

test("test failures display localized protocol feedback without saving", async () => {
  rs.mocked(testManagedModel).mockResolvedValueOnce({
    ok: false,
    message: "authentication_failed",
  });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
  expect(
    await screen.findByText(enUS.settings.models.authentication_failed),
  ).toBeTruthy();
  expect(saveManagedModel).not.toHaveBeenCalled();
});

test("saving refreshes an active existing model selector", async () => {
  mount(true);
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  rs.mocked(loadModels).mockResolvedValue({
    models: [
      {
        name: "custom",
        model: "test",
        display_name: "Updated picker model",
        id: "custom",
        supports_thinking: false,
        supports_reasoning_effort: false,
      },
    ],
    token_usage: { enabled: false },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(
    await screen.findByRole("option", { name: "Updated picker model" }),
  ).toBeTruthy();
  expect(loadModels).toHaveBeenCalled();
  expect(loadManagedModels).toHaveBeenCalledTimes(2);
});

test("static mode does not request management or provider metadata", () => {
  rs.mocked(isStaticWebsiteOnly).mockReturnValue(true);
  mount();
  expect(loadManagedModels).not.toHaveBeenCalled();
  expect(loadManagedModelProviders).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "Add model" })).toBeNull();
});

test("revision/name conflicts are localized and the unsaved draft survives", async () => {
  rs.mocked(saveManagedModel).mockRejectedValueOnce(
    new GatewayApiError({
      message: "private server detail",
      rawMessage: "private server detail",
      status: 409,
      code: null,
      params: {},
    }),
  );
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit model" }));
  fireEvent.change(screen.getByLabelText("Model ID"), {
    target: { value: "draft-model" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(
    await screen.findByText(enUS.settings.models.revisionConflict),
  ).toBeTruthy();
  expect(screen.getByLabelText<HTMLInputElement>("Model ID").value).toBe(
    "draft-model",
  );
  expect(screen.queryByText("private server detail")).toBeNull();
});
