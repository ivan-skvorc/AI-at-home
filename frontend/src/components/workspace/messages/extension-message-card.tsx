"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { ChevronRight, PuzzleIcon } from "lucide-react";
import { useMemo, useState } from "react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { extensionDirectory } from "@/core/extensions/catalog";
import { useFrontendExtensions } from "@/core/extensions/hooks";
import { useI18n } from "@/core/i18n/hooks";
import type { ExtensionOrigin } from "@/core/messages/utils";
import { textOfMessage } from "@/core/threads/utils";
import { cn } from "@/lib/utils";

/**
 * A message an extension posted into the conversation, such as a Double Plus
 * Ultracode workflow's result (FORK.md §44). The Gateway stamps the origin, so
 * this never renders for text the user typed and the user's text can never
 * render as this. Shown as that extension's card with the first line as its
 * summary and the full message collapsed; plain text, never HTML.
 */
export function ExtensionMessageCard({
  message,
  origin,
  className,
}: {
  message: Message;
  origin: ExtensionOrigin;
  className?: string;
}) {
  const { t } = useI18n();
  const { data: extensions } = useFrontendExtensions();
  const [open, setOpen] = useState(false);
  const name = useMemo(
    () =>
      extensionDirectory(extensions ?? [], t.extensions.catalog).find(
        (entry) => entry.id === origin.namespace,
      )?.title ?? origin.namespace,
    [extensions, origin.namespace, t.extensions.catalog],
  );
  const text = textOfMessage(message) ?? "";
  const summary = text.split("\n", 1)[0]?.trim() ?? "";

  return (
    <div
      className={cn("flex w-full flex-col gap-2", className)}
      data-testid="extension-message"
      data-namespace={origin.namespace}
    >
      <div className="bg-card flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-4 py-2.5 text-sm">
        <PuzzleIcon className="size-4 shrink-0" aria-hidden />
        <span className="font-medium">{t.extensionMessage.postedBy(name)}</span>
        {summary && <span className="min-w-0 break-words">{summary}</span>}
        <span className="text-muted-foreground ml-auto text-xs">
          {t.extensionMessage.notTyped}
        </span>
      </div>
      {text && (
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger className="text-muted-foreground hover:text-foreground flex items-center gap-1 border-l-2 pl-3 text-left text-sm">
            <ChevronRight
              className={cn(
                "size-4 shrink-0 transition-transform",
                open && "rotate-90",
              )}
              aria-hidden
            />
            {t.extensionMessage.showMessage}
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2 border-l-2 pl-8">
            <pre
              className="text-muted-foreground max-h-96 overflow-auto text-xs break-words whitespace-pre-wrap"
              data-testid="extension-message-text"
            >
              {text}
            </pre>
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  );
}
