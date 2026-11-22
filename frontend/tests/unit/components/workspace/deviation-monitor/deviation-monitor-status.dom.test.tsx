import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";

/**
 * The deviation monitor's status bar above the composer (fork feature).
 *
 * It must render every status the backend reports, in both languages, never
 * when the chat's monitor is off or the operator does not offer it, and it is
 * where the monitor is turned off in one click.
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
      { id: "judge-model", name: "judge-model", display_name: "Judge Model" },
    ],
  }),
}));

import { DeviationMonitorStatus } from "@/components/workspace/deviation-monitor/deviation-monitor-status";
import { I18nContext } from "@/core/i18n/context";
import type { Locale } from "@/core/i18n/locale";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { DEVIATION_MONITOR_STATUSES } from "@/core/threads/deviation-monitor";

const onChange = rs.fn();
const TRANSLATIONS = { "en-US": enUS, "zh-CN": zhCN } as const;

const ON = {
  enabled: true,
  model: "judge-model",
  cadence: { mode: "steps" as const, every: 3 },
};

beforeEach(() => {
  featureEnabled = true;
});
afterEach(() => {
  cleanup();
  onChange.mockReset();
});

type Props = Omit<ComponentProps<typeof DeviationMonitorStatus>, "onChange">;

function mount(props: Props, locale: Locale = "en-US") {
  return render(
    <I18nContext.Provider
      value={{ locale, setLocale: () => undefined, t: TRANSLATIONS[locale] }}
    >
      <DeviationMonitorStatus {...props} onChange={onChange} />
    </I18nContext.Provider>,
  );
}

function bar() {
  return screen.queryByTestId("deviation-monitor-status");
}

describe("the status bar", () => {
  it("renders each reported status, in English and Chinese", () => {
    for (const locale of ["en-US", "zh-CN"] as const) {
      for (const status of DEVIATION_MONITOR_STATUSES) {
        mount(
          {
            setting: ON,
            state: { status, checks: 2, last_checked_step: 6 },
            isRunning: true,
          },
          locale,
        );
        expect(bar()!.getAttribute("data-status")).toBe(status);
        expect(
          screen.getByTestId("deviation-monitor-status-label").textContent,
        ).toBe(TRANSLATIONS[locale].deviationMonitor.status[status]);
        cleanup();
      }
    }
  });

  it("is watching before the first check of a run", () => {
    mount({ setting: ON, state: undefined, isRunning: true });
    expect(bar()!.getAttribute("data-status")).toBe("idle");
    expect(bar()!.textContent).toContain(enUS.deviationMonitor.status.idle);
    expect(bar()!.textContent).toContain("every 3 steps");
    expect(bar()!.textContent).toContain("Judge Model");
  });

  it("is absent while the chat's monitor is off", () => {
    mount({
      setting: { ...ON, enabled: false },
      state: { status: "stopped" },
    });
    expect(bar()).toBeNull();
  });

  it("is absent while the operator does not offer the monitor", () => {
    featureEnabled = false;
    mount({ setting: ON, state: { status: "on_track" } });
    expect(bar()).toBeNull();
  });

  it("explains a stop: why, what kind of drift, and the request it lost", () => {
    mount({
      setting: ON,
      state: {
        status: "stopped",
        reason: "It began rewriting the whole README.",
        drift_kind: "scope_creep",
        restated_task: "Fix the typo in README.md",
      },
    });
    const details = screen.getByTestId("deviation-monitor-status-details");
    expect(details.hidden).toBe(true);
    fireEvent.click(
      screen.getByTestId("deviation-monitor-status-details-toggle"),
    );
    expect(details.hidden).toBe(false);
    expect(details.textContent).toContain(
      "It began rewriting the whole README.",
    );
    expect(details.textContent).toContain(
      enUS.deviationMonitor.driftKinds.scope_creep,
    );
    expect(details.textContent).toContain("Fix the typo in README.md");
    // No raw drift code reaches the user.
    expect(details.textContent).not.toContain("scope_creep");
  });

  it("turns the monitor off in one click, keeping its model and cadence", () => {
    mount({ setting: ON, state: { status: "on_track" } });
    fireEvent.click(screen.getByTestId("deviation-monitor-status-turn-off"));
    expect(onChange).toHaveBeenCalledWith({ ...ON, enabled: false });
  });

  it("keeps a monitored run's bar when the monitor is turned off during it", () => {
    // The run read the chat's choice when it was sent; it is still monitored.
    const runStartedAt = Date.parse("2026-11-22T10:00:00Z");
    const during = {
      state: { status: "drifting", updated_at: "2026-11-22T10:00:30Z" },
      runStartedAt,
    };
    const view = mount({ setting: ON, isRunning: true, ...during });
    const rerender = (props: Props) =>
      view.rerender(
        <I18nContext.Provider
          value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
        >
          <DeviationMonitorStatus {...props} onChange={onChange} />
        </I18nContext.Provider>,
      );
    rerender({
      setting: { ...ON, enabled: false },
      isRunning: true,
      ...during,
    });
    expect(bar()!.getAttribute("data-status")).toBe("drifting");
    expect(
      screen.getByTestId("deviation-monitor-next-message").textContent,
    ).toBe(enUS.deviationMonitor.offFromNextMessage);
    expect(
      screen.queryByTestId("deviation-monitor-status-turn-off"),
    ).toBeNull();
    // The run is over: the chat's choice decides.
    rerender({
      setting: { ...ON, enabled: false },
      isRunning: false,
      ...during,
    });
    expect(bar()).toBeNull();
  });

  it("says a monitor turned on during a run starts with the next message", () => {
    const off = { ...ON, enabled: false };
    const view = mount({ setting: off, state: undefined, isRunning: true });
    expect(bar()).toBeNull();
    view.rerender(
      <I18nContext.Provider
        value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
      >
        <DeviationMonitorStatus
          setting={ON}
          state={undefined}
          isRunning
          onChange={onChange}
        />
      </I18nContext.Provider>,
    );
    expect(
      screen.getByTestId("deviation-monitor-status-label").textContent,
    ).toBe(enUS.deviationMonitor.onFromNextMessage);
    expect(bar()!.textContent).not.toContain(enUS.deviationMonitor.status.idle);
  });

  it("announces the status to screen readers", () => {
    mount({ setting: ON, state: { status: "drifting" }, isRunning: true });
    expect(bar()!.querySelector('[role="status"]')!.textContent).toBe(
      `${enUS.deviationMonitor.name}: ${enUS.deviationMonitor.status.drifting}`,
    );
  });
});
