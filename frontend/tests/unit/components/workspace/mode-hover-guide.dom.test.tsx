import { afterEach, describe, expect, it } from "@rstest/core";
import { act, cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import {
  DoubleUltracodeWarningTooltip,
  ModeHoverGuide,
} from "@/components/workspace/mode-hover-guide";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

afterEach(cleanup);

function renderEn(node: ReactNode) {
  return render(
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      {node}
    </I18nContext.Provider>,
  );
}

async function focusAndReadTip(name: string): Promise<string> {
  const trigger = screen.getByRole("button", { name });
  act(() => trigger.focus());
  const tips = await screen.findAllByRole("tooltip");
  return tips.map((tip) => tip.textContent ?? "").join(" ");
}

describe("Double Plus Ultracode warning (FORK.md §44)", () => {
  it("floats over the menu option before anyone selects it", async () => {
    renderEn(
      <DoubleUltracodeWarningTooltip>
        <button type="button">Double Plus Ultracode</button>
      </DoubleUltracodeWarningTooltip>,
    );

    const tip = await focusAndReadTip("Double Plus Ultracode");

    expect(tip).toContain(enUS.inputBox.doubleUltracodeWarningTitle);
    expect(tip).toContain("Token-risky");
    expect(tip).toContain("tool-call limits are off");
  });

  it("shows on the mode button while the mode is selected, and only for that mode", async () => {
    renderEn(
      <ModeHoverGuide mode="double_ultracode">
        <button type="button">mode</button>
      </ModeHoverGuide>,
    );
    expect(await focusAndReadTip("mode")).toContain(
      enUS.inputBox.doubleUltracodeWarningTitle,
    );
    cleanup();

    renderEn(
      <ModeHoverGuide mode="ultracode">
        <button type="button">mode</button>
      </ModeHoverGuide>,
    );
    const plus = await focusAndReadTip("mode");
    expect(plus).toContain(enUS.inputBox.ultracodeModeDescription);
    expect(plus).not.toContain(enUS.inputBox.doubleUltracodeWarningTitle);
  });
});
