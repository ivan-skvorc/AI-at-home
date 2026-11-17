import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { toast } from "sonner";

import { AutoTitleSettingsPage } from "@/components/workspace/settings/auto-title-settings-page";
import { enUS } from "@/core/i18n/locales/en-US";
import {
  AUTO_TITLE_SYNCED_STORAGE_KEY,
  hydrateAutoTitlePreference,
} from "@/core/settings/auto-title-sync";
import {
  getBaseSettingsSnapshot,
  updateLocalSettings,
} from "@/core/settings/store";

/**
 * Settings → Conversation titles writes to the account (fork feature, FORK.md
 * §33): the switch is the user's opt-out for runs from every device, IM
 * channel and extension, not only for this browser's own sends.
 */

const mocks = rs.hoisted(() => ({ fetch: rs.fn(), staticMode: false }));
rs.mock("@/core/api/fetcher", () => ({ fetch: mocks.fetch }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: () => mocks.staticMode,
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/features", () => ({
  useAutoTitleCapability: () => ({ enabled: true, modelName: null }),
}));
rs.mock("@/core/models/hooks", () => ({ useModels: () => ({ models: [] }) }));
rs.mock("sonner", () => ({ toast: { success: rs.fn(), error: rs.fn() } }));

const SWITCH = { name: enUS.settings.autoTitle.title };

beforeEach(() => {
  mocks.fetch.mockReset();
  mocks.staticMode = false;
  rs.mocked(toast.error).mockReset();
  updateLocalSettings("autoTitle", { enabled: true, modelName: undefined });
  localStorage.clear();
  localStorage.setItem(AUTO_TITLE_SYNCED_STORAGE_KEY, "1");
});
afterEach(() => {
  cleanup();
});

test("turning the switch off saves the opt-out to the account", async () => {
  mocks.fetch.mockImplementation(async (_url: string, init?: RequestInit) =>
    Response.json(JSON.parse(init!.body as string)),
  );
  render(<AutoTitleSettingsPage />);

  fireEvent.click(screen.getByRole("switch", SWITCH));

  expect(screen.getByRole("switch", SWITCH).getAttribute("aria-checked")).toBe(
    "false",
  );
  await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(1));
  const [url, init] = mocks.fetch.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/api/settings/auto-title");
  expect(init.method).toBe("PUT");
  expect(JSON.parse(init.body as string)).toEqual({ enabled: false });
  expect(screen.getByText(enUS.settings.autoTitle.accountHint)).toBeTruthy();
});

test("a save the account refused is reported and the switch goes back", async () => {
  mocks.fetch.mockImplementation(async (_url: string, init?: RequestInit) =>
    init?.method === "PUT"
      ? Response.json({ detail: "boom" }, { status: 500 })
      : Response.json({ enabled: true }),
  );
  await hydrateAutoTitlePreference();
  render(<AutoTitleSettingsPage />);

  await act(async () => {
    fireEvent.click(screen.getByRole("switch", SWITCH));
  });

  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith(
      enUS.settings.autoTitle.saveFailed,
    ),
  );
  expect(screen.getByRole("switch", SWITCH).getAttribute("aria-checked")).toBe(
    "true",
  );
  expect(getBaseSettingsSnapshot().autoTitle.enabled).toBe(true);
});

test("the static demo keeps the setting in this browser and says nothing of an account", () => {
  mocks.staticMode = true;
  render(<AutoTitleSettingsPage />);

  fireEvent.click(screen.getByRole("switch", SWITCH));

  expect(getBaseSettingsSnapshot().autoTitle.enabled).toBe(false);
  expect(mocks.fetch).not.toHaveBeenCalled();
  expect(screen.queryByText(enUS.settings.autoTitle.accountHint)).toBeNull();
});
