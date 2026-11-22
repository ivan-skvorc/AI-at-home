import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";

/**
 * The composer's deviation monitor button and its dialog (fork feature).
 *
 * What fails silently here: a button that renders on a server that will not
 * run the monitor, a dialog that saves an out-of-range cadence the backend
 * then drops, a model that is not the one the user picked, and a Cancel that
 * still changes the chat.
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
      { id: "other", name: "other", display_name: "Other Model" },
    ],
  }),
}));

import { DeviationMonitorControl } from "@/components/workspace/deviation-monitor/deviation-monitor-control";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { updateLocalSettings } from "@/core/settings/store";
import { DEFAULT_DEVIATION_MONITOR_DEFAULTS } from "@/core/threads/deviation-monitor";

const onChange = rs.fn();

beforeEach(() => {
  featureEnabled = true;
  window.localStorage.clear();
  updateLocalSettings("deviationMonitor", {
    ...DEFAULT_DEVIATION_MONITOR_DEFAULTS,
  });
});

afterEach(() => {
  cleanup();
  onChange.mockReset();
});

function mount(setting?: unknown) {
  return render(
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <DeviationMonitorControl
        setting={setting}
        chatModelName="chat-model"
        onChange={onChange}
      />
    </I18nContext.Provider>,
  );
}

function button() {
  return document.querySelector<HTMLButtonElement>(
    "[data-slot='deviation-monitor']",
  );
}

function dialog() {
  return within(screen.getByTestId("deviation-monitor-dialog"));
}

function openDialog() {
  fireEvent.click(button()!);
  return dialog();
}

function save() {
  fireEvent.click(screen.getByTestId("deviation-monitor-save"));
}

const ON = {
  enabled: true,
  model: "other",
  cadence: { mode: "steps", every: 5 },
};

describe("the composer button", () => {
  it("is hidden while the operator does not offer the monitor", () => {
    featureEnabled = false;
    mount();
    expect(button()).toBeNull();
  });

  it("publishes its own slot and state, off by default", () => {
    mount();
    expect(button()!.getAttribute("data-state")).toBe("off");
    expect(button()!.getAttribute("aria-label")).toBe(
      enUS.deviationMonitor.buttonOff,
    );
  });

  it("shows on for a chat whose monitor is on", () => {
    mount(ON);
    expect(button()!.getAttribute("data-state")).toBe("on");
    expect(button()!.getAttribute("aria-label")).toBe(
      enUS.deviationMonitor.buttonOn,
    );
  });
});

describe("turning it on", () => {
  it("preselects the chat's model and saves the contract shape", () => {
    mount();
    const view = openDialog();
    expect(
      view.getByTestId("deviation-monitor-model-select").textContent,
    ).toContain("Chat Model");
    save();
    expect(onChange).toHaveBeenCalledWith({
      enabled: true,
      model: "chat-model",
      cadence: { mode: "steps", every: 3 },
    });
  });

  it("preselects the Settings default model when one is set", () => {
    act(() =>
      updateLocalSettings("deviationMonitor", {
        modelName: "judge-model",
        cadence: { mode: "turns", every: 4 },
      }),
    );
    mount();
    openDialog();
    save();
    expect(onChange).toHaveBeenCalledWith({
      enabled: true,
      model: "judge-model",
      cadence: { mode: "turns", every: 4 },
    });
  });

  it("saves the model picked in the shared picker", () => {
    mount();
    const view = openDialog();
    fireEvent.click(view.getByTestId("deviation-monitor-model-select"));
    const option = screen
      .getAllByRole("option")
      .find((el) => el.getAttribute("data-value") === "judge-model");
    fireEvent.click(option!);
    save();
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ model: "judge-model" }),
    );
  });

  it("refuses a cadence outside the backend's bounds", () => {
    mount();
    const view = openDialog();
    const every = view.getByTestId("deviation-monitor-every");
    fireEvent.change(every, { target: { value: "51" } });
    expect(view.getByTestId("deviation-monitor-every-error").textContent).toBe(
      enUS.deviationMonitor.outOfRange(1, 50),
    );
    expect(screen.getByTestId("deviation-monitor-save")).toHaveProperty(
      "disabled",
      true,
    );

    fireEvent.click(view.getByTestId("deviation-monitor-cadence-turns"));
    fireEvent.change(view.getByTestId("deviation-monitor-every"), {
      target: { value: "21" },
    });
    expect(view.getByTestId("deviation-monitor-every-error").textContent).toBe(
      enUS.deviationMonitor.outOfRange(1, 20),
    );
    fireEvent.change(view.getByTestId("deviation-monitor-every"), {
      target: { value: "2.5" },
    });
    expect(view.getByTestId("deviation-monitor-every-error").textContent).toBe(
      enUS.deviationMonitor.notInteger,
    );
    save();
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.change(view.getByTestId("deviation-monitor-every"), {
      target: { value: "20" },
    });
    save();
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ cadence: { mode: "turns", every: 20 } }),
    );
  });

  it("stores every turn as one turn", () => {
    mount();
    const view = openDialog();
    fireEvent.click(view.getByTestId("deviation-monitor-cadence-everyTurn"));
    expect(view.queryByTestId("deviation-monitor-every")).toBeNull();
    save();
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ cadence: { mode: "turns", every: 1 } }),
    );
  });

  it("changes nothing on Cancel", () => {
    mount();
    const view = openDialog();
    fireEvent.click(view.getByTestId("deviation-monitor-cadence-everyTurn"));
    fireEvent.click(screen.getByTestId("deviation-monitor-cancel"));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByTestId("deviation-monitor-dialog")).toBeNull();
  });
});

describe("a chat whose monitor is on", () => {
  it("reopens the dialog on its own model and cadence", () => {
    mount(ON);
    const view = openDialog();
    expect(
      view.getByTestId("deviation-monitor-model-select").textContent,
    ).toContain("Other Model");
    expect(view.getByTestId("deviation-monitor-every")).toHaveProperty(
      "value",
      "5",
    );
    expect(screen.getByTestId("deviation-monitor-save").textContent).toBe(
      enUS.deviationMonitor.save,
    );
  });

  it("turns off from the dialog, keeping its model and cadence for next time", () => {
    mount(ON);
    openDialog();
    fireEvent.click(screen.getByTestId("deviation-monitor-turn-off"));
    expect(onChange).toHaveBeenCalledWith({ ...ON, enabled: false });
  });

  it("offers no Turn off while it is off", () => {
    mount({ ...ON, enabled: false });
    openDialog();
    expect(screen.queryByTestId("deviation-monitor-turn-off")).toBeNull();
    expect(screen.getByTestId("deviation-monitor-save").textContent).toBe(
      enUS.deviationMonitor.turnOn,
    );
  });
});
