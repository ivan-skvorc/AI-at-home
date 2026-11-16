import { FolderTreeIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";

import { useArtifacts } from "../artifacts/context";
import { useMaybeSidecar } from "../sidecar/context";

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
export function ThreadFilesTrigger() {
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
          className="hidden @[32rem]/chat-header:inline"
        >
          {t.threadFiles.title}
        </span>
      </Button>
    </Tooltip>
  );
}
