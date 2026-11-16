"use client";

import { ArrowRightIcon, FolderPlusIcon } from "lucide-react";
import { memo, useId, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Translations } from "@/core/i18n";
import { useI18n } from "@/core/i18n/hooks";
import type { ChatFolder } from "@/core/threads/chat-folders";
import {
  itemHasChanges,
  mergeProposedFolder,
  renameProposedFolder,
  setAllIncluded,
  updatePlanItem,
  type OrganizeFailure,
  type OrganizeItemResult,
  type OrganizePlan,
  type OrganizePlanItem,
  type OrganizeTarget,
  type ProposedFolder,
} from "@/core/threads/chat-organize";
import { isIMEComposing } from "@/lib/ime";

import { analysisFailureReason, stepFailureReason } from "./cleanup-reasons";
import { folderPathLabel } from "./folder-labels";

export type PlanUpdate = (update: (plan: OrganizePlan) => OrganizePlan) => void;

const KEEP_VALUE = "keep";

/** Select values: one namespace per kind, so a key can never read as an id. */
function encodeTarget(target: OrganizeTarget): string {
  switch (target.kind) {
    case "keep":
      return KEEP_VALUE;
    case "existing":
      return `x:${target.folderId}`;
    case "new":
      return `n:${target.key}`;
  }
}

function decodeTarget(value: string): OrganizeTarget {
  if (value.startsWith("x:")) {
    return { kind: "existing", folderId: value.slice(2) };
  }
  if (value.startsWith("n:")) {
    return { kind: "new", key: value.slice(2) };
  }
  return { kind: "keep" };
}

function TargetOptions({
  folders,
  proposed,
  copy,
  keepLabel,
  excludeKey,
}: {
  folders: readonly ChatFolder[];
  proposed: readonly ProposedFolder[];
  copy: Translations["chatCleanup"];
  keepLabel: string;
  excludeKey?: string;
}) {
  const proposedOptions = proposed.filter(
    (folder) => folder.key !== excludeKey,
  );
  return (
    <>
      <SelectItem value={KEEP_VALUE}>{keepLabel}</SelectItem>
      {proposedOptions.length > 0 && (
        <SelectGroup>
          <SelectLabel>{copy.newFoldersGroup}</SelectLabel>
          {proposedOptions.map((folder) => (
            <SelectItem key={folder.key} value={`n:${folder.key}`}>
              {copy.newFolderOption(folder.name)}
            </SelectItem>
          ))}
        </SelectGroup>
      )}
      {folders.length > 0 && (
        <SelectGroup>
          <SelectLabel>{copy.existingFoldersGroup}</SelectLabel>
          {folders.map((folder) => (
            <SelectItem key={folder.id} value={`x:${folder.id}`}>
              {folderPathLabel(folders, folder.id)}
            </SelectItem>
          ))}
        </SelectGroup>
      )}
    </>
  );
}

/**
 * One conversation's row. Memoized on its own item: typing a title rebuilds
 * one item object, so only that row re-renders, which matters with two hundred
 * rows each carrying a folder picker.
 */
const PlanRow = memo(function PlanRow({
  item,
  folders,
  proposed,
  result,
  disabled,
  untitled,
  onUpdate,
}: {
  item: OrganizePlanItem;
  folders: readonly ChatFolder[];
  proposed: readonly ProposedFolder[];
  result: OrganizeItemResult | undefined;
  disabled: boolean;
  untitled: string;
  onUpdate: PlanUpdate;
}) {
  const { t } = useI18n();
  const copy = t.chatCleanup;
  const label = item.currentTitle ?? untitled;
  const hasChanges = itemHasChanges(item);
  const currentFolder = item.currentFolderId
    ? folders.some((folder) => folder.id === item.currentFolderId)
      ? folderPathLabel(folders, item.currentFolderId)
      : null
    : null;
  const moveFailure = result ? stepFailureReason(result.move, copy) : null;
  const renameFailure = result ? stepFailureReason(result.rename, copy) : null;

  return (
    <li
      className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-2 py-3 sm:grid-cols-[auto_minmax(0,1fr)_13rem]"
      data-testid="chat-cleanup-row"
      data-thread-id={item.threadId}
    >
      <input
        type="checkbox"
        className="accent-primary mt-2 size-4"
        aria-label={copy.includeLabel(label)}
        checked={item.include && hasChanges}
        disabled={disabled || !hasChanges}
        onChange={(event) => {
          const include = event.target.checked;
          onUpdate((plan) => updatePlanItem(plan, item.threadId, { include }));
        }}
      />
      <div className="flex min-w-0 flex-col gap-1">
        <span
          className="text-muted-foreground flex min-w-0 items-center gap-1 text-xs"
          title={label}
        >
          <span className="truncate">{label}</span>
          {item.suggestedTitle && (
            <ArrowRightIcon className="size-3 shrink-0" aria-hidden />
          )}
        </span>
        <Input
          value={item.title}
          maxLength={200}
          disabled={disabled}
          aria-label={copy.newTitleLabel(label)}
          className="h-8"
          onChange={(event) => {
            const title = event.target.value;
            onUpdate((plan) => updatePlanItem(plan, item.threadId, { title }));
          }}
          data-testid="chat-cleanup-row-title"
        />
        <span className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
          {currentFolder && <span>{copy.currentFolder(currentFolder)}</span>}
          {!hasChanges && (
            <Badge variant="secondary" className="font-normal">
              {copy.unchanged}
            </Badge>
          )}
        </span>
        {moveFailure && (
          <span className="text-destructive text-xs" role="status">
            {copy.moveFailed(moveFailure)}
          </span>
        )}
        {renameFailure && (
          <span className="text-destructive text-xs" role="status">
            {copy.renameFailed(renameFailure)}
          </span>
        )}
      </div>
      <div className="col-start-2 sm:col-start-3">
        <Select
          value={encodeTarget(item.target)}
          disabled={disabled}
          onValueChange={(value) => {
            const target = decodeTarget(value);
            onUpdate((plan) => updatePlanItem(plan, item.threadId, { target }));
          }}
        >
          <SelectTrigger
            size="sm"
            className="w-full"
            aria-label={copy.folderLabel(label)}
            data-testid="chat-cleanup-row-folder"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <TargetOptions
              folders={folders}
              proposed={proposed}
              copy={copy}
              keepLabel={copy.keepFolder}
            />
          </SelectContent>
        </Select>
      </div>
    </li>
  );
});

function ProposedFolderRow({
  folder,
  count,
  folders,
  proposed,
  disabled,
  onUpdate,
}: {
  folder: ProposedFolder;
  count: number;
  folders: readonly ChatFolder[];
  proposed: readonly ProposedFolder[];
  disabled: boolean;
  onUpdate: PlanUpdate;
}) {
  const { t } = useI18n();
  const copy = t.chatCleanup;
  const [draft, setDraft] = useState(folder.name);
  // A rename that the model normalized away (blank) snaps back on blur.
  const [syncedName, setSyncedName] = useState(folder.name);
  if (syncedName !== folder.name) {
    setSyncedName(folder.name);
    setDraft(folder.name);
  }
  const commit = () => {
    if (draft.trim() && draft !== folder.name) {
      onUpdate((plan) => renameProposedFolder(plan, folder.key, draft));
    } else {
      setDraft(folder.name);
    }
  };
  return (
    <li
      className="flex flex-col gap-2 py-2 sm:flex-row sm:items-center"
      data-testid="chat-cleanup-proposed-folder"
    >
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <FolderPlusIcon className="text-muted-foreground size-4 shrink-0" />
        <Input
          value={draft}
          maxLength={80}
          disabled={disabled}
          aria-label={copy.proposedNameLabel(folder.name)}
          className="h-8"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !isIMEComposing(event)) {
              event.preventDefault();
              commit();
            }
          }}
        />
        <span className="text-muted-foreground shrink-0 text-xs">
          {copy.proposedCount(count)}
        </span>
      </div>
      <Select
        value=""
        disabled={disabled}
        onValueChange={(value) => {
          const into = decodeTarget(value);
          onUpdate((plan) => mergeProposedFolder(plan, folder.key, into));
        }}
      >
        <SelectTrigger
          size="sm"
          className="w-full sm:w-52"
          aria-label={copy.mergeIntoLabel(folder.name)}
        >
          <SelectValue placeholder={copy.mergeInto} />
        </SelectTrigger>
        <SelectContent>
          <TargetOptions
            folders={folders}
            proposed={proposed}
            copy={copy}
            keepLabel={copy.mergeUnfile}
            excludeKey={folder.key}
          />
        </SelectContent>
      </Select>
    </li>
  );
}

export function CleanupPreview({
  plan,
  folders,
  threadTitles,
  failures,
  results,
  disabled,
  onUpdate,
}: {
  plan: OrganizePlan;
  folders: readonly ChatFolder[];
  /** Titles by thread id, for naming the conversations that failed. */
  threadTitles: ReadonlyMap<string, string | null>;
  failures: readonly OrganizeFailure[];
  results: ReadonlyMap<string, OrganizeItemResult> | null;
  disabled: boolean;
  onUpdate: PlanUpdate;
}) {
  const { t } = useI18n();
  const copy = t.chatCleanup;
  const headingId = useId();
  const counts = new Map<string, number>();
  for (const item of plan.items) {
    if (item.target.kind === "new") {
      counts.set(item.target.key, (counts.get(item.target.key) ?? 0) + 1);
    }
  }
  const anyChanges = plan.items.some(itemHasChanges);

  return (
    <div className="flex flex-col gap-4" data-testid="chat-cleanup-preview">
      {!anyChanges ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>{copy.noChanges}</EmptyTitle>
            <EmptyDescription>{copy.noChangesHint}</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <>
          <div className="flex items-center justify-end gap-1">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={disabled}
              onClick={() =>
                onUpdate((current) => setAllIncluded(current, true))
              }
            >
              {copy.selectAll}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={disabled}
              onClick={() =>
                onUpdate((current) => setAllIncluded(current, false))
              }
            >
              {copy.selectNone}
            </Button>
          </div>
          <ul className="divide-y" data-testid="chat-cleanup-rows">
            {plan.items.map((item) => (
              <PlanRow
                key={item.threadId}
                item={item}
                folders={folders}
                proposed={plan.proposedFolders}
                result={results?.get(item.threadId)}
                disabled={disabled}
                untitled={t.pages.untitled}
                onUpdate={onUpdate}
              />
            ))}
          </ul>
        </>
      )}

      {plan.proposedFolders.length > 0 && (
        <section
          aria-labelledby={headingId}
          className="flex flex-col gap-1 rounded-lg border p-3"
        >
          <h3 id={headingId} className="text-sm font-medium">
            {copy.proposedTitle}
          </h3>
          <p className="text-muted-foreground text-xs">{copy.proposedHint}</p>
          <ul className="divide-y">
            {plan.proposedFolders.map((folder) => (
              <ProposedFolderRow
                key={folder.key}
                folder={folder}
                count={counts.get(folder.key) ?? 0}
                folders={folders}
                proposed={plan.proposedFolders}
                disabled={disabled}
                onUpdate={onUpdate}
              />
            ))}
          </ul>
        </section>
      )}

      {failures.length > 0 && (
        <section
          className="flex flex-col gap-2 rounded-lg border p-3"
          data-testid="chat-cleanup-failures"
        >
          <h3 className="text-sm font-medium">
            {copy.failuresTitle(failures.length)}
          </h3>
          <ul className="flex flex-col gap-1 text-sm">
            {failures.map((failure) => (
              <li key={failure.threadId} className="min-w-0">
                <span className="block truncate">
                  {threadTitles.get(failure.threadId) ?? t.pages.untitled}
                </span>
                <span className="text-muted-foreground block text-xs">
                  {analysisFailureReason(failure, copy)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
