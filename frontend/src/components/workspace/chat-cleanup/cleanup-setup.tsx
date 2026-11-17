"use client";

import { FolderIcon, PlusIcon, XIcon } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ModelSelect } from "@/components/workspace/model-select";
import { useI18n } from "@/core/i18n/hooks";
import type { Model } from "@/core/models/types";
import type { ChatFolder } from "@/core/threads/chat-folders";
import {
  MAX_NEW_FOLDERS_LIMIT,
  MAX_ORGANIZE_TARGETS,
  clampMaxNewFolders,
  type OrganizeMode,
} from "@/core/threads/chat-organize";
import { isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

import { folderPathLabel } from "./folder-labels";

/**
 * Picker sentinel for "the operator's title model". The Gateway reads an absent
 * `model_name` as `title.model_name`, then the default model; this row is how
 * the user asks for that, and it is mapped to `undefined` before any request.
 */
export const SERVER_DEFAULT_MODEL = "__server_default__";

export type CleanupSetupState = {
  /** A model name, or {@link SERVER_DEFAULT_MODEL}. */
  model: string;
  rename: boolean;
  folderMode: OrganizeMode;
  selectedFolderIds: string[];
  newFolderNames: string[];
  maxNewFolders: number;
};

export type CleanupScopeStatus =
  | { status: "loading" }
  | { status: "error"; retry: () => void }
  | {
      status: "ready";
      all: boolean;
      count: number;
      capped: boolean;
      missing: number;
    };

const FOLDER_MODES: readonly OrganizeMode[] = ["auto", "targets", "none"];

export function CleanupSetup({
  scope,
  state,
  onChange,
  models,
  folders,
  renameAvailable,
  localPace,
}: {
  scope: CleanupScopeStatus;
  state: CleanupSetupState;
  onChange: (patch: Partial<CleanupSetupState>) => void;
  models: readonly Model[];
  folders: readonly ChatFolder[];
  /** False when the operator turned renaming off (`title.enabled: false`). */
  renameAvailable: boolean;
  /** The resolved model runs locally, so the pass goes one chat at a time. */
  localPace: boolean;
}) {
  const { t } = useI18n();
  const copy = t.chatCleanup;
  const baseId = useId();
  const [draftName, setDraftName] = useState("");
  const targetCount =
    state.selectedFolderIds.length + state.newFolderNames.length;
  const targetsFull = targetCount >= MAX_ORGANIZE_TARGETS;

  const addDraft = () => {
    const name = draftName.trim();
    if (!name || targetsFull) {
      return;
    }
    const key = name.toLocaleLowerCase();
    if (
      !state.newFolderNames.some(
        (existing) => existing.trim().toLocaleLowerCase() === key,
      )
    ) {
      onChange({ newFolderNames: [...state.newFolderNames, name] });
    }
    setDraftName("");
  };

  const modeLabel = (mode: OrganizeMode) =>
    mode === "none"
      ? copy.folderModeNone
      : mode === "targets"
        ? copy.folderModeTargets
        : copy.folderModeAuto;
  const modeHint = (mode: OrganizeMode) =>
    mode === "none"
      ? copy.folderModeNoneHint
      : mode === "targets"
        ? copy.folderModeTargetsHint
        : copy.folderModeAutoHint;

  return (
    <div className="flex flex-col gap-5" data-testid="chat-cleanup-setup">
      <section
        className="bg-muted/40 flex flex-col gap-1 rounded-lg border px-3 py-2 text-sm"
        aria-live="polite"
        data-testid="chat-cleanup-scope"
      >
        {scope.status === "loading" && (
          <div className="flex flex-col gap-2 py-1">
            <span className="sr-only">{copy.scopeLoading}</span>
            <Skeleton className="h-4 w-48" />
          </div>
        )}
        {scope.status === "error" && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-destructive">{copy.scopeFailed}</span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={scope.retry}
            >
              {copy.scopeRetry}
            </Button>
          </div>
        )}
        {scope.status === "ready" && (
          <>
            <span className="font-medium">
              {scope.count === 0
                ? copy.scopeEmpty
                : scope.all
                  ? copy.scopeAll(scope.count)
                  : copy.scopeSelected(scope.count)}
            </span>
            {scope.capped && (
              <span className="text-muted-foreground">
                {scope.all
                  ? copy.scopeCapped(scope.count)
                  : copy.scopeSelectionCapped(scope.count)}
              </span>
            )}
            {scope.missing > 0 && (
              <span className="text-muted-foreground">
                {copy.scopeMissing(scope.missing)}
              </span>
            )}
            {scope.count > 0 && (
              <span className="text-muted-foreground">{copy.costHint}</span>
            )}
          </>
        )}
      </section>

      <div className="flex flex-col gap-2">
        <label className="text-sm font-medium" htmlFor={`${baseId}-model`}>
          {copy.modelLabel}
        </label>
        <ModelSelect
          id={`${baseId}-model`}
          models={models}
          value={state.model}
          onChange={(model) => onChange({ model })}
          data-testid="chat-cleanup-model-select"
          options={[
            {
              value: SERVER_DEFAULT_MODEL,
              label: copy.serverDefault,
              description: copy.serverDefaultHint,
            },
          ]}
        />
        {localPace && (
          <p className="text-muted-foreground text-xs">{copy.localPaceHint}</p>
        )}
      </div>

      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <label className="text-sm font-medium" htmlFor={`${baseId}-rename`}>
            {copy.renameLabel}
          </label>
          <p className="text-muted-foreground text-xs">
            {renameAvailable ? copy.renameHint : copy.renameDisabled}
          </p>
        </div>
        <Switch
          id={`${baseId}-rename`}
          checked={renameAvailable && state.rename}
          disabled={!renameAvailable}
          onCheckedChange={(rename) => onChange({ rename })}
          data-testid="chat-cleanup-rename"
        />
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-2 text-sm font-medium">
          {copy.foldersLabel}
        </legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {FOLDER_MODES.map((mode) => (
            <label
              key={mode}
              className={cn(
                "hover:bg-accent/60 flex cursor-pointer flex-col gap-1 rounded-lg border p-3 text-sm transition-colors",
                state.folderMode === mode && "border-ring bg-accent/40",
              )}
            >
              <span className="flex items-center gap-2 font-medium">
                <input
                  type="radio"
                  name={`${baseId}-folder-mode`}
                  value={mode}
                  checked={state.folderMode === mode}
                  onChange={() => onChange({ folderMode: mode })}
                  className="accent-primary size-4"
                  data-testid={`chat-cleanup-mode-${mode}`}
                />
                {modeLabel(mode)}
              </span>
              <span className="text-muted-foreground text-xs">
                {modeHint(mode)}
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {state.folderMode === "targets" && (
        <div className="flex flex-col gap-3" data-testid="chat-cleanup-targets">
          <div className="flex flex-col gap-1">
            <span className="text-sm font-medium">{copy.targetsExisting}</span>
            {folders.length === 0 ? (
              <p className="text-muted-foreground text-xs">
                {copy.targetsNoExisting}
              </p>
            ) : (
              <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto rounded-md border p-2">
                {folders.map((folder) => {
                  const checked = state.selectedFolderIds.includes(folder.id);
                  return (
                    <li key={folder.id}>
                      <label className="hover:bg-accent/60 flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm">
                        <input
                          type="checkbox"
                          className="accent-primary size-4"
                          checked={checked}
                          disabled={!checked && targetsFull}
                          onChange={() =>
                            onChange({
                              selectedFolderIds: checked
                                ? state.selectedFolderIds.filter(
                                    (id) => id !== folder.id,
                                  )
                                : [...state.selectedFolderIds, folder.id],
                            })
                          }
                        />
                        <FolderIcon className="text-muted-foreground size-4 shrink-0" />
                        <span className="min-w-0 truncate">
                          {folderPathLabel(folders, folder.id)}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <label
              className="text-sm font-medium"
              htmlFor={`${baseId}-new-folder`}
            >
              {copy.targetsNewLabel}
            </label>
            <div className="flex gap-2">
              <Input
                id={`${baseId}-new-folder`}
                value={draftName}
                maxLength={80}
                placeholder={copy.targetsNewPlaceholder}
                disabled={targetsFull}
                onChange={(event) => setDraftName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !isIMEComposing(event)) {
                    event.preventDefault();
                    addDraft();
                  }
                }}
                data-testid="chat-cleanup-new-folder-input"
              />
              <Button
                type="button"
                variant="outline"
                onClick={addDraft}
                disabled={!draftName.trim() || targetsFull}
                data-testid="chat-cleanup-new-folder-add"
              >
                <PlusIcon />
                {copy.targetsAdd}
              </Button>
            </div>
            {state.newFolderNames.length > 0 && (
              <ul className="flex flex-wrap gap-2">
                {state.newFolderNames.map((name, index) => (
                  <li
                    key={`${name}-${index}`}
                    className="bg-secondary flex items-center gap-1 rounded-md py-1 pr-1 pl-2 text-sm"
                  >
                    <span className="max-w-48 truncate">{name}</span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-6"
                      aria-label={copy.targetsRemove(name)}
                      onClick={() =>
                        onChange({
                          newFolderNames: state.newFolderNames.filter(
                            (_, position) => position !== index,
                          ),
                        })
                      }
                    >
                      <XIcon />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-muted-foreground text-xs">
              {targetCount === 0
                ? copy.targetsNone
                : copy.targetsLimit(MAX_ORGANIZE_TARGETS)}
            </p>
          </div>
        </div>
      )}

      {state.folderMode === "auto" && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between gap-4">
            <label
              className="text-sm font-medium"
              htmlFor={`${baseId}-max-new`}
            >
              {copy.maxNewFoldersLabel}
            </label>
            <Input
              id={`${baseId}-max-new`}
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_NEW_FOLDERS_LIMIT}
              className="w-20"
              value={state.maxNewFolders}
              onChange={(event) =>
                onChange({
                  maxNewFolders: clampMaxNewFolders(event.target.valueAsNumber),
                })
              }
              data-testid="chat-cleanup-max-new-folders"
            />
          </div>
          <p className="text-muted-foreground text-xs">
            {copy.maxNewFoldersHint}
          </p>
        </div>
      )}
    </div>
  );
}
