"use client";

import { AlertTriangleIcon, RotateCcwIcon, SaveIcon } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import { SystemPromptError } from "@/core/system-prompt/api";
import {
  useResetSystemPrompt,
  useSaveSystemPrompt,
  useSystemPrompt,
  useSystemPromptPreview,
} from "@/core/system-prompt/hooks";

import { SettingsSection } from "./settings-section";

/**
 * Section of the built-in prompt that tells the agent not to disclose its own
 * instructions. Dropping it is a legitimate edit — some operators want an agent
 * that can explain itself — but it is worth surfacing, because the consequence
 * is invisible until someone asks the agent to repeat its prompt.
 */
const CONFIDENTIALITY_MARKER = "System-Context Confidentiality";

function isAdminRequired(error: unknown): boolean {
  return error instanceof SystemPromptError && error.status === 403;
}

export function SystemPromptSettingsPage() {
  const { t } = useI18n();
  const copy = t.settings.systemPrompt;
  const editorId = useId();
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const { data: prompt, isLoading, error } = useSystemPrompt();
  const saveMutation = useSaveSystemPrompt();
  const resetMutation = useResetSystemPrompt();

  const [draft, setDraft] = useState<string | null>(null);
  const [tab, setTab] = useState("edit");
  const [previewSubagents, setPreviewSubagents] = useState(true);
  const [resetOpen, setResetOpen] = useState(false);

  // The preview renders the saved template, so only fetch it on that tab.
  const preview = useSystemPromptPreview(
    previewSubagents,
    tab === "preview" && prompt !== undefined,
  );

  // Adopt the server's template as the draft on first load, and again whenever
  // a save or reset returns new content — but never while the user is midway
  // through an edit, which is why this keys off the server value alone.
  const serverContent = prompt?.content;
  useEffect(() => {
    if (serverContent !== undefined) {
      setDraft(serverContent);
    }
  }, [serverContent]);

  const content = draft ?? serverContent ?? "";
  const dirty = serverContent !== undefined && content !== serverContent;
  const overLimit = prompt ? content.length > prompt.max_length : false;
  const confidentialityDropped = useMemo(
    () =>
      prompt !== undefined &&
      prompt.default_content.includes(CONFIDENTIALITY_MARKER) &&
      !content.includes(CONFIDENTIALITY_MARKER),
    [content, prompt],
  );

  const insertPlaceholder = useCallback(
    (name: string) => {
      const textarea = textareaRef.current;
      const token = `{${name}}`;
      if (!textarea) {
        setDraft(content + token);
        return;
      }
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      setDraft(content.slice(0, start) + token + content.slice(end));
      // Restore focus with the caret after the inserted token.
      requestAnimationFrame(() => {
        textarea.focus();
        textarea.setSelectionRange(start + token.length, start + token.length);
      });
    },
    [content],
  );

  const handleSave = useCallback(() => {
    saveMutation.mutate(content, {
      onSuccess: () => toast.success(copy.saved),
      onError: (err) =>
        toast.error(
          err instanceof SystemPromptError ? err.message : copy.saveFailed,
        ),
    });
  }, [content, copy.saveFailed, copy.saved, saveMutation]);

  const handleReset = useCallback(() => {
    resetMutation.mutate(undefined, {
      onSuccess: (next) => {
        setDraft(next.content);
        setResetOpen(false);
      },
      onError: (err) =>
        toast.error(
          err instanceof SystemPromptError ? err.message : copy.saveFailed,
        ),
    });
  }, [copy.saveFailed, resetMutation]);

  if (isAdminRequired(error)) {
    return (
      <SettingsSection title={copy.title} description={copy.description}>
        <p className="text-muted-foreground rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/50">
          {copy.adminRequired}
        </p>
      </SettingsSection>
    );
  }

  if (error) {
    return (
      <SettingsSection title={copy.title} description={copy.description}>
        <p className="text-destructive text-sm">{copy.loadFailed}</p>
      </SettingsSection>
    );
  }

  if (isLoading || !prompt) {
    return (
      <SettingsSection title={copy.title} description={copy.description}>
        <p role="status" className="text-muted-foreground text-sm">
          {t.common.loading}
        </p>
      </SettingsSection>
    );
  }

  return (
    <SettingsSection
      title={
        <div className="flex items-center gap-2">
          <span>{copy.title}</span>
          <Badge variant={prompt.is_custom ? "default" : "secondary"}>
            {prompt.is_custom ? copy.customBadge : copy.defaultBadge}
          </Badge>
        </div>
      }
      description={copy.description}
    >
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="edit">{copy.tabEdit}</TabsTrigger>
          <TabsTrigger value="preview">{copy.tabPreview}</TabsTrigger>
        </TabsList>

        <TabsContent value="edit" className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <label htmlFor={editorId} className="text-sm font-medium">
              {copy.editorLabel}
            </label>
            <p className="text-muted-foreground text-xs">{copy.editorHint}</p>
            <Textarea
              id={editorId}
              ref={textareaRef}
              spellCheck={false}
              value={content}
              onChange={(event) => setDraft(event.target.value)}
              className="min-h-[22rem] font-mono text-xs leading-relaxed"
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span
                className={
                  overLimit
                    ? "text-destructive text-xs"
                    : "text-muted-foreground text-xs"
                }
              >
                {copy.charCount(content.length, prompt.max_length)}
              </span>
              {dirty && (
                <span className="text-muted-foreground text-xs">
                  {copy.unsavedChanges}
                </span>
              )}
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">
              {copy.placeholdersLabel}
            </span>
            <p className="text-muted-foreground text-xs">
              {copy.placeholdersHint}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {prompt.placeholders.map((name) => (
                <Button
                  key={name}
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 font-mono text-xs"
                  onClick={() => insertPlaceholder(name)}
                >
                  {`{${name}}`}
                </Button>
              ))}
            </div>
            {prompt.missing_placeholders.length > 0 && (
              <p className="text-muted-foreground text-xs">
                {copy.missingPlaceholders(
                  prompt.missing_placeholders.join(", "),
                )}
              </p>
            )}
          </div>

          {confidentialityDropped && (
            <p className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/50">
              <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" />
              <span>{copy.confidentialityWarning}</span>
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              onClick={handleSave}
              disabled={!dirty || overLimit || saveMutation.isPending}
            >
              <SaveIcon className="size-4" />
              {saveMutation.isPending ? copy.saving : copy.save}
            </Button>
            {dirty && (
              <Button
                type="button"
                variant="ghost"
                onClick={() => setDraft(prompt.content)}
              >
                {copy.revertEdits}
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              className="ml-auto"
              onClick={() => setResetOpen(true)}
              disabled={!prompt.is_custom || resetMutation.isPending}
            >
              <RotateCcwIcon className="size-4" />
              {resetMutation.isPending ? copy.resetting : copy.reset}
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="preview" className="flex flex-col gap-3">
          <p className="text-muted-foreground text-xs">
            {copy.previewDescription}
          </p>
          <label className="flex items-center gap-2 text-sm">
            <Switch
              checked={previewSubagents}
              onCheckedChange={setPreviewSubagents}
            />
            <span>{copy.previewSubagentToggle}</span>
          </label>
          <pre className="bg-muted max-h-[26rem] overflow-auto rounded-md p-3 font-mono text-xs whitespace-pre-wrap">
            {preview.data?.rendered ?? copy.previewEmpty}
          </pre>
        </TabsContent>
      </Tabs>

      <Dialog open={resetOpen} onOpenChange={setResetOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{copy.resetConfirmTitle}</DialogTitle>
            <DialogDescription>
              {copy.resetConfirmDescription}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setResetOpen(false)}>
              {copy.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={handleReset}
              disabled={resetMutation.isPending}
            >
              {resetMutation.isPending
                ? copy.resetting
                : copy.resetConfirmAction}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SettingsSection>
  );
}
