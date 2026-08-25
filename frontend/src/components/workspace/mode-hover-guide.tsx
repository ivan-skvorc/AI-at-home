"use client";

import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";

import { Tooltip } from "./tooltip";

export type AgentMode = "flash" | "thinking" | "pro" | "ultra" | "democracy";

function getModeLabelKey(
  mode: AgentMode,
): keyof Pick<
  Translations["inputBox"],
  "flashMode" | "reasoningMode" | "proMode" | "ultraMode" | "democracyMode"
> {
  switch (mode) {
    case "flash":
      return "flashMode";
    case "thinking":
      return "reasoningMode";
    case "pro":
      return "proMode";
    case "ultra":
      return "ultraMode";
    case "democracy":
      return "democracyMode";
  }
}

function getModeDescriptionKey(
  mode: AgentMode,
): keyof Pick<
  Translations["inputBox"],
  | "flashModeDescription"
  | "reasoningModeDescription"
  | "proModeDescription"
  | "ultraModeDescription"
  | "democracyModeDescription"
> {
  switch (mode) {
    case "flash":
      return "flashModeDescription";
    case "thinking":
      return "reasoningModeDescription";
    case "pro":
      return "proModeDescription";
    case "ultra":
      return "ultraModeDescription";
    case "democracy":
      return "democracyModeDescription";
  }
}

export function ModeHoverGuide({
  mode,
  children,
  showTitle = true,
}: {
  mode: AgentMode;
  children: React.ReactNode;
  /** When true, tooltip shows "ModeName: Description". When false, only description. */
  showTitle?: boolean;
}) {
  const { t } = useI18n();
  const label = t.inputBox[getModeLabelKey(mode)];
  const description = t.inputBox[getModeDescriptionKey(mode)];
  const content = showTitle ? `${label}: ${description}` : description;

  return <Tooltip content={content}>{children}</Tooltip>;
}
