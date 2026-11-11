"use client";

import { TriangleAlertIcon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";

import { Tooltip } from "./tooltip";

export type AgentMode =
  | "flash"
  | "thinking"
  | "pro"
  | "ultra"
  | "democracy"
  | "ultracode"
  | "double_ultracode";

function getModeLabelKey(
  mode: AgentMode,
): keyof Pick<
  Translations["inputBox"],
  | "flashMode"
  | "reasoningMode"
  | "proMode"
  | "ultraMode"
  | "democracyMode"
  | "ultracodeMode"
  | "doubleUltracodeMode"
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
    case "ultracode":
      return "ultracodeMode";
    case "double_ultracode":
      return "doubleUltracodeMode";
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
  | "ultracodeModeDescription"
  | "doubleUltracodeModeDescription"
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
    case "ultracode":
      return "ultracodeModeDescription";
    case "double_ultracode":
      return "doubleUltracodeModeDescription";
  }
}

/**
 * The floating warning for Double Plus Ultracode (FORK.md §44): an alert icon,
 * a one-line risk title and the mode's description. Shown on hover and focus of
 * the menu option, before anyone selects it, and of the composer's mode button
 * while it is selected.
 */
export function ModeWarning({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex max-w-72 gap-2 text-left" role="note">
      <TriangleAlertIcon
        aria-hidden
        className="text-destructive mt-0.5 size-4 shrink-0"
      />
      <div className="space-y-1">
        <p className="font-semibold">{title}</p>
        <p>{description}</p>
      </div>
    </div>
  );
}

/**
 * The one-line Double Plus Ultracode warning that stays in the composer for as
 * long as that mode is selected. The tooltips in this file need hover or focus:
 * a touch screen gives neither, and nobody hovers the mode button when a chat
 * opens already in the mode, at submit time or while the run streams. The full
 * text stays in the tooltip. Renders nothing for any other mode, Plus
 * Ultracode included.
 */
export function DoubleUltracodeNotice({ mode }: { mode: string | undefined }) {
  const { t } = useI18n();
  if (mode !== "double_ultracode") {
    return null;
  }
  return (
    <div
      className="text-muted-foreground flex w-full items-center gap-1.5 text-xs"
      role="note"
    >
      <TriangleAlertIcon
        aria-hidden
        className="text-destructive size-3 shrink-0"
      />
      <span className="min-w-0 truncate">
        {t.inputBox.doubleUltracodeWarningTitle}
      </span>
    </div>
  );
}

/** Hover/focus wrapper for the Double Plus Ultracode menu option. */
export function DoubleUltracodeWarningTooltip({
  children,
}: {
  children: React.ReactNode;
}) {
  const { t } = useI18n();
  return (
    <Tooltip
      side="right"
      delayDuration={100}
      content={
        <ModeWarning
          title={t.inputBox.doubleUltracodeWarningTitle}
          description={t.inputBox.doubleUltracodeModeDescription}
        />
      }
    >
      {children}
    </Tooltip>
  );
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
  if (mode === "double_ultracode") {
    // A risk, not a feature tour: warn as soon as the pointer arrives.
    return (
      <Tooltip
        delayDuration={100}
        content={
          <ModeWarning
            title={t.inputBox.doubleUltracodeWarningTitle}
            description={description}
          />
        }
      >
        {children}
      </Tooltip>
    );
  }
  const content = showTitle ? `${label}: ${description}` : description;

  return <Tooltip content={content}>{children}</Tooltip>;
}
