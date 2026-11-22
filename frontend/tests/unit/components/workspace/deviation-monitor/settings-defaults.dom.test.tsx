import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
} from "@testing-library/react";

/**
 * Settings → Deviation monitor and how a new chat picks it up (fork feature).
 *
 * The defaults are per browser and apply only to a chat as it starts: an
 * existing conversation never starts being monitored because a default
 * changed, and a choice the user made in the new chat is never overwritten.
 */

let featureEnabled = true;
rs.mock("@/core/features/deviation-monitor", () => ({
  useDeviationMonitorFeature: () => ({
    enabled: featureEnabled,
    isLoading: false,
  }),
}));
rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({
    models: [
      { id: "chat-model", name: "chat-model", display_name: "Chat Model" },
      { id: "judge-model", name: "judge-model", display_name: "Judge Model" },
    ],
  }),
}));

import { useDeviationMonitorNewChatDefault } from "@/components/workspace/deviation-monitor/use-new-chat-default";
import { DeviationMonitorSettingsPage } from "@/components/workspace/settings/deviation-monitor-settings-page";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { getThreadContextOverride } from "@/core/settings/local";
import {
  getBaseSettingsSnapshot,
  updateLocalSettings,
  updateThreadSettings,
} from "@/core/settings/store";
import { DEFAULT_DEVIATION_MONITOR_DEFAULTS } from "@/core/threads/deviation-monitor";

beforeEach(() => {
  featureEnabled = true;
  window.localStorage.clear();
  updateLocalSettings("deviationMonitor", {
    ...DEFAULT_DEVIATION_MONITOR_DEFAULTS,
  });
});
afterEach(cleanup);

function defaults() {
  return getBaseSettingsSnapshot().deviationMonitor;
}

function mountPage() {
  return render(
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <DeviationMonitorSettingsPage />
    </I18nContext.Provider>,
  );
}

describe("the Settings page", () => {
  it("switches the default on for new chats", () => {
    mountPage();
    fireEvent.click(screen.getByTestId("deviation-monitor-default-enabled"));
    expect(defaults().enabledForNewChats).toBe(true);
  });

  it("offers the chat's own model as the default, and saves a picked one", () => {
    mountPage();
    const picker = screen.getByTestId("deviation-monitor-default-model");
    expect(picker.textContent).toContain(enUS.deviationMonitor.chatModel);
    fireEvent.click(picker);
    const option = screen
      .getAllByRole("option")
      .find((el) => el.getAttribute("data-value") === "judge-model");
    fireEvent.click(option!);
    expect(defaults().modelName).toBe("judge-model");
  });

  it("saves only a cadence inside the backend's bounds", () => {
    mountPage();
    const every = screen.getByTestId("deviation-monitor-every");
    fireEvent.change(every, { target: { value: "60" } });
    expect(screen.getByTestId("deviation-monitor-every-error")).toBeTruthy();
    expect(defaults().cadence).toEqual({ mode: "steps", every: 3 });
    fireEvent.change(every, { target: { value: "12" } });
    expect(defaults().cadence).toEqual({ mode: "steps", every: 12 });
    fireEvent.click(screen.getByTestId("deviation-monitor-cadence-everyTurn"));
    expect(defaults().cadence).toEqual({ mode: "turns", every: 1 });
  });

  it("says so, and locks the controls, when the operator turned it off", () => {
    featureEnabled = false;
    mountPage();
    expect(
      screen.getByText(enUS.settings.deviationMonitor.serverDisabledHint),
    ).toBeTruthy();
    expect(
      screen.getByTestId("deviation-monitor-default-enabled"),
    ).toHaveProperty("disabled", true);
  });
});

describe("a new chat taking the defaults", () => {
  function seed(threadId: string, isNewThread: boolean) {
    return renderHook(() =>
      useDeviationMonitorNewChatDefault({
        threadId,
        isNewThread,
        enabled: true,
      }),
    );
  }

  beforeEach(() => {
    act(() =>
      updateLocalSettings("deviationMonitor", {
        enabledForNewChats: true,
        modelName: "judge-model",
        cadence: { mode: "turns", every: 2 },
      }),
    );
  });

  it("starts with the monitor on, as this chat's own choice", () => {
    seed("new-chat", true);
    expect(getThreadContextOverride("new-chat")).toEqual({
      deviation_monitor: {
        enabled: true,
        model: "judge-model",
        cadence: { mode: "turns", every: 2 },
      },
    });
  });

  it("leaves an existing chat unmonitored", () => {
    seed("old-chat", false);
    expect(getThreadContextOverride("old-chat")).toEqual({});
  });

  it("never overrides what the user chose in that chat", () => {
    const off = {
      enabled: false,
      model: "chat-model",
      cadence: { mode: "steps" as const, every: 3 },
    };
    updateThreadSettings("new-chat", "context", { deviation_monitor: off });
    seed("new-chat", true);
    expect(getThreadContextOverride("new-chat")).toEqual({
      deviation_monitor: off,
    });
  });

  it("does nothing while the default is off or the operator does not offer it", () => {
    act(() =>
      updateLocalSettings("deviationMonitor", { enabledForNewChats: false }),
    );
    seed("chat-a", true);
    expect(getThreadContextOverride("chat-a")).toEqual({});

    act(() =>
      updateLocalSettings("deviationMonitor", { enabledForNewChats: true }),
    );
    featureEnabled = false;
    seed("chat-b", true);
    expect(getThreadContextOverride("chat-b")).toEqual({});
  });
});
