import { afterEach, describe, expect, it } from "@rstest/core";
import { act, cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import {
  DoubleUltracodeWarningTooltip,
  ModeHoverGuide,
} from "@/components/workspace/mode-hover-guide";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";

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
    expect(tip).toContain("automatic limits are off");
    expect(tip).toContain("spend cap still applies");
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

  it("says what is lifted and what still applies, without promising an unstoppable run", () => {
    const en = enUS.inputBox.doubleUltracodeModeDescription;
    const zh = zhCN.inputBox.doubleUltracodeModeDescription;

    // The workflow's own limits and a provider stop can still end a run.
    expect(en).not.toContain("only the model finishing");
    expect(zh).not.toContain("只有模型完成任务才会结束运行");
    for (const lifted of [
      "step limit",
      "tool-call limits",
      "subtasks per run",
      "token budgets",
      "time limit",
    ]) {
      expect(en).toContain(lifted);
    }
    for (const lifted of [
      "步数上限",
      "工具调用上限",
      "子任务",
      "Token 预算",
      "时间上限",
    ]) {
      expect(zh).toContain(lifted);
    }
    expect(en).toContain("agent-count and size limits still apply");
    expect(zh).toContain("智能体数量和大小上限仍然生效");
    // The cap is off by default, so it must not read as a safety net.
    expect(en).toContain("only if one is set");
    expect(en).toContain("off by default");
    expect(zh).toContain("默认未设置");

    // Plus Ultracode keeps its limits and says so.
    expect(enUS.inputBox.ultracodeModeDescription).toContain(
      "limits still apply",
    );
    expect(zhCN.inputBox.ultracodeModeDescription).toContain("仍然生效");
  });

  it("tells the Run limits page that Double Plus Ultracode ignores it, bar the spend cap", () => {
    expect(enUS.settings.runLimits.description).toContain(
      "Double Plus Ultracode ignores all of them except the spend cap",
    );
    expect(zhCN.settings.runLimits.description).toMatch(
      /Double Plus Ultracode.*花费上限/,
    );
  });
});
