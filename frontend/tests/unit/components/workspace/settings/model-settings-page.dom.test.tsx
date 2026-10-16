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
import { useAuth } from "@/core/auth/AuthProvider";
import { enUS } from "@/core/i18n/locales/en-US";
import type * as Management from "@/core/models/management";
import {
  loadManagedModels,
  modelDraft,
  saveManagedModel,
  testManagedModel,
  type ManagedModel,
} from "@/core/models/management";
import {
  loadSubscriptions,
  beginGrokSignIn,
  pollGrokSignIn,
  connectKimiSubscription,
  importChatGPTConnection,
} from "@/core/models/subscriptions";

rs.mock("@/core/auth/AuthProvider", () => ({ useAuth: rs.fn() }));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/models/subscriptions", () => ({
  loadSubscriptions: rs.fn(),
  beginGrokSignIn: rs.fn(),
  pollGrokSignIn: rs.fn(),
  connectKimiSubscription: rs.fn(),
  importChatGPTConnection: rs.fn(),
  refreshSubscriptionModels: rs.fn(),
  disconnectSubscription: rs.fn(),
  chatGPTSignInHelperURL: () => "/api/subscriptions/chatgpt/helper",
}));
rs.mock("@/core/models/management", () => ({
  ...rs.requireActual<typeof Management>("@/core/models/management"),
  loadManagedModels: rs.fn(),
  saveManagedModel: rs.fn(),
  testManagedModel: rs.fn(),
}));

const existing: ManagedModel = {
  ...modelDraft(),
  name: "custom",
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
  rs.mocked(useAuth).mockReturnValue(auth("admin"));
  rs.mocked(loadManagedModels).mockResolvedValue({ models: [existing] });
  rs.mocked(loadSubscriptions).mockResolvedValue({ providers: [] });
  rs.mocked(saveManagedModel).mockResolvedValue({
    ...existing,
    revision: "v2",
  });
});
afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  client.setQueryData(["models"], { models: [] });
  render(
    <QueryClientProvider client={client}>
      <ModelSettingsPage />
    </QueryClientProvider>,
  );
  return client;
}

test("non-admin cannot load credentials configuration or add models", () => {
  rs.mocked(useAuth).mockReturnValue(auth("user"));
  mount();
  expect(screen.queryByRole("button", { name: "Add model" })).toBeNull();
  expect(loadManagedModels).not.toHaveBeenCalled();
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

test("remote ChatGPT setup offers the local helper and keeps provider errors private", async () => {
  mount();
  fireEvent.click(
    screen.getByRole("button", { name: "Continue with ChatGPT" }),
  );
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
  const dialog = screen.getByRole("dialog");
  expect((await within(dialog).findByRole("alert")).textContent).toBe(
    enUS.settings.subscriptions.failed,
  );
  expect(rs.mocked(importChatGPTConnection).mock.calls[0]?.[0]).toEqual({
    access_token: "private-access-token",
  });
  expect(
    within(dialog).queryByText("private-refresh-token in provider failure"),
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
