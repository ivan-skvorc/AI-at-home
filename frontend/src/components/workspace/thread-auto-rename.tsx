"use client";

import { SparklesIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ModelSelect } from "@/components/workspace/model-select";
import { useAutoTitleCapability } from "@/core/features";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { useLocalSettings } from "@/core/settings";
import { useAutoRenameThread } from "@/core/threads/auto-rename";

/**
 * Picker sentinel for "whatever the operator configured".
 *
 * A picker row needs a non-empty value, and the stored preference for this one
 * is `undefined` — the same three-state contract Settings → Conversation titles
 * uses, minus its "no model call" row: a rename with no model call would just
 * truncate the first message, which is not worth a dialog and a button press.
 */
const SERVER_DEFAULT = "__server_default__";

/**
 * "Auto rename" in the chat header (fork feature, FORK.md §38).
 *
 * The automatic rename (§33) fires once, at the end of the first turn, on the
 * model `config.yaml -> title` names. This is the same thing on demand: after
 * a conversation has gone somewhere the opening exchange did not predict, or
 * when the first title described the wrong half of it.
 *
 * Two steps, deliberately: the Gateway *writes* the title and the client
 * *applies* it through the ordinary rename, so the refusal while a run is in
 * flight (409) stays in the one place that already enforces it.
 */
export function ThreadAutoRename({
  threadId,
  disabled,
}: {
  threadId: string;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const { models } = useModels();
  const [settings, setSettings] = useLocalSettings();
  const [open, setOpen] = useState(false);
  const { mutateAsync: autoRename, isPending } = useAutoRenameThread();
  // The operator's `config.yaml -> title.enabled`. When they have turned
  // renaming off, the Gateway answers this route with a 404, so showing the
  // button would only offer a press that cannot work. Same flag the Settings
  // page greys its toggle on.
  const { enabled: renamingEnabled } = useAutoTitleCapability();

  const storedModel = settings.autoTitle.modelName;
  // Derived, not an effect. The picker starts on the remembered model and only
  // holds a value once the user picks one, so it is correct while `models` is
  // still loading *and* immune to the array identity changing under a re-render
  // — an effect keyed on `models` resets the pick on every render, which reads
  // as a picker that will not stay on the model you chose.
  const [picked, setPicked] = useState<string | null>(null);
  // A model that has since left config.yaml must not leave the picker showing a
  // name the Gateway would refuse with a 400.
  const remembered =
    storedModel && models.some((model) => model.name === storedModel)
      ? storedModel
      : SERVER_DEFAULT;
  const modelName = picked ?? remembered;

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setPicked(null);
    }
  };

  const handleRun = async () => {
    // `undefined` for the sentinel, so the Gateway keeps the operator's model.
    const chosen = modelName === SERVER_DEFAULT ? undefined : modelName;
    try {
      const title = await autoRename({ threadId, modelName: chosen });
      // Remember the pick for the next press *and* for the automatic rename:
      // both read the one `autoTitle.modelName` preference, so choosing a model
      // here is the same choice as choosing it in Settings.
      if (chosen) {
        setSettings("autoTitle", { modelName: chosen });
      }
      setOpen(false);
      toast.success(t.autoRename.success(title));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t.autoRename.failed);
    }
  };

  if (!renamingEnabled) {
    return null;
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          aria-label={t.autoRename.label}
          data-testid="auto-rename-trigger"
        >
          <SparklesIcon />
          <span className="hidden lg:inline">{t.autoRename.label}</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t.autoRename.title}</DialogTitle>
          <DialogDescription>{t.autoRename.description}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <div className="text-sm font-medium">{t.autoRename.modelLabel}</div>
          <ModelSelect
            models={models}
            value={modelName}
            onChange={setPicked}
            disabled={isPending}
            data-testid="auto-rename-model-select"
            options={[
              {
                value: SERVER_DEFAULT,
                label: t.autoRename.serverDefault,
                description: t.autoRename.serverDefaultHint,
              },
            ]}
          />
        </div>
        <DialogFooter>
          <Button
            type="button"
            onClick={handleRun}
            disabled={isPending}
            data-testid="auto-rename-run"
          >
            {isPending ? t.autoRename.running : t.autoRename.run}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
