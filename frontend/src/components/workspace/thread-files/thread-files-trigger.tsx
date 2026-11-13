import { FolderTreeIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";

import { useArtifacts } from "../artifacts/context";
import { useMaybeSidecar } from "../sidecar/context";

/**
 * Header button that opens the side panel on the thread's file explorer.
 * Icon-only: the chat header has no width to spare (the title shrinks first, and
 * an open side panel narrows the column below the viewport breakpoints), and the
 * aria-label and tooltip name it.
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
        size="icon"
        data-testid="thread-files-trigger"
        onClick={() => {
          sidecar?.close();
          showFiles();
        }}
      >
        <FolderTreeIcon />
      </Button>
    </Tooltip>
  );
}
