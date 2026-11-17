import { FolderTreeIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";

import { useArtifacts } from "../artifacts/context";
import { useMaybeSidecar } from "../sidecar/context";

/**
 * The header width from which the label shows, per header. The controls row
 * cannot shrink and its last controls are cut off, so the word appears only
 * where the full row still fits with it: the auto-rename label, the token
 * pill, Side Chat, Browser, Export and Artifacts come to about 47rem on a chat
 * page, and an agent's page adds its badge and **New chat** (about 59rem).
 * Below that the button is icon-only and clips nothing it did not clip before.
 * Literal class names, so Tailwind finds them.
 */
const LABEL_CLASS = {
  chat: "hidden @[48rem]/chat-header:inline",
  agent: "hidden @[60rem]/chat-header:inline",
} as const;

/**
 * Header button that opens the side panel on the thread's file explorer.
 *
 * It carries a visible "Files" label so people can find it: an unlabelled
 * folder icon at the end of the header was both overlooked and the first
 * control the header clipped. The label follows the header's own width (the
 * `chat-header` container), not the viewport, because an open side panel
 * narrows the chat column without changing the viewport. The aria-label stays
 * "Show files", which is the accessible name tests and assistive tech use.
 */
export function ThreadFilesTrigger({
  header = "chat",
}: {
  /** Which chat header hosts the button; see {@link LABEL_CLASS}. */
  header?: keyof typeof LABEL_CLASS;
} = {}) {
  const { t } = useI18n();
  const { showFiles } = useArtifacts();
  const sidecar = useMaybeSidecar();
  return (
    <Tooltip content={t.threadFiles.showFiles}>
      <Button
        aria-label={t.threadFiles.showFiles}
        className="text-muted-foreground hover:text-foreground"
        variant="ghost"
        data-testid="thread-files-trigger"
        onClick={() => {
          sidecar?.close();
          showFiles();
        }}
      >
        <FolderTreeIcon />
        <span
          data-testid="thread-files-trigger-label"
          className={LABEL_CLASS[header]}
        >
          {t.threadFiles.title}
        </span>
      </Button>
    </Tooltip>
  );
}
