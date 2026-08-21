"use client";

import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";

import { Tooltip } from "../tooltip";

/**
 * The `‹ 2/3 ›` control shown on a user message that has been edited.
 *
 * Each position is a whole hidden conversation thread, so moving between them
 * is a navigation, not a local state change — the parent owns that and receives
 * the target index.
 */
export function MessageVersionSwitcher({
  currentIndex,
  total,
  disabled = false,
  onSelectIndex,
}: {
  currentIndex: number;
  total: number;
  disabled?: boolean;
  onSelectIndex: (index: number) => void;
}) {
  const { t } = useI18n();

  if (total < 2) {
    return null;
  }

  return (
    <div
      className="text-muted-foreground flex items-center gap-0.5 text-xs tabular-nums"
      data-testid="message-version-switcher"
    >
      <Tooltip content={t.conversation.editVersionPrevious}>
        <Button
          aria-label={t.conversation.editVersionPrevious}
          className="size-5"
          disabled={disabled || currentIndex <= 0}
          onClick={() => onSelectIndex(currentIndex - 1)}
          size="icon-sm"
          type="button"
          variant="ghost"
        >
          <ChevronLeftIcon className="size-3" />
        </Button>
      </Tooltip>
      <span>{t.conversation.editVersionCounter(currentIndex + 1, total)}</span>
      <Tooltip content={t.conversation.editVersionNext}>
        <Button
          aria-label={t.conversation.editVersionNext}
          className="size-5"
          disabled={disabled || currentIndex >= total - 1}
          onClick={() => onSelectIndex(currentIndex + 1)}
          size="icon-sm"
          type="button"
          variant="ghost"
        >
          <ChevronRightIcon className="size-3" />
        </Button>
      </Tooltip>
    </div>
  );
}
