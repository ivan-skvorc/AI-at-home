"use client";

import {
  AlertTriangleIcon,
  PaperclipIcon,
  UsersRoundIcon,
  XIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { lacksToolSupport } from "@/core/models/capabilities";
import { useModels } from "@/core/models/hooks";
import type { Model } from "@/core/models/types";
import {
  clampParticipantCount,
  DEMOCRACY_GRADING_OPTIONS,
  type DemocracyGrading,
  estimateDemocracyCost,
  isValidDemocracyPanel,
  MAX_DEMOCRACY_PARTICIPANTS,
  MIN_DEMOCRACY_PARTICIPANTS,
  stashDemocracyFiles,
  stashDemocracyLaunch,
} from "@/core/threads/democracy";

import { ModelSelect } from "./model-select";

const DEFAULT_PARTICIPANT_COUNT = 3;

/**
 * Setup for a Democracy panel: how many panelists, which organizer, which
 * models, how they get graded, and the task (text plus any files).
 *
 * A **full page**, not a modal. Starting a panel is the same kind of act as
 * starting a chat — it is the beginning of a conversation, not a preference
 * being adjusted — and it needs enough room for a roster that can reach a dozen
 * rows plus a cost warning the user is meant to actually read. A modal that
 * scrolls internally buries exactly the part that matters.
 */
export function DemocracySetup() {
  const { t } = useI18n();
  const router = useRouter();
  const { models } = useModels();

  const [count, setCount] = useState(DEFAULT_PARTICIPANT_COUNT);
  const [organizer, setOrganizer] = useState<string>("");
  const [participants, setParticipants] = useState<string[]>([]);
  const [grading, setGrading] = useState<DemocracyGrading>("off");
  const [task, setTask] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // The organizer delegates the whole panel through `task`, so a model that
  // cannot call tools cannot organize; panelists only have to answer, so they
  // are merely demoted rather than excluded.
  const organizerModels = useMemo(
    () => models.filter((model) => !lacksToolSupport(model)),
    [models],
  );
  // Panelists keep tool-incapable models available but last. That ordering is
  // now the picker's `demoteLast` rather than a pre-sorted array: the shared
  // picker re-sorts whatever it is handed (by name, by price, grouped by
  // provider), so a pre-sort here would simply be discarded — and silently, with
  // no-tool models scattered back through the list.
  const panelistModels = models;

  // An empty selection means "not chosen yet", so the first tool-capable model
  // stands in until the user picks — `||` rather than `??` because "" is the
  // unset state here, not a value.
  const resolvedOrganizer =
    organizer.length > 0 ? organizer : (organizerModels[0]?.name ?? "");
  const roster = useMemo(() => {
    const next = participants.slice(0, count);
    while (next.length < count) next.push("");
    return next;
  }, [participants, count]);

  const chosen = roster.filter((name) => name.length > 0);
  const hasEveryPanelist = chosen.length === count;
  const hasDuplicates = new Set(chosen).size !== chosen.length;
  const panelIsValid = hasEveryPanelist && isValidDemocracyPanel(roster);
  const taskIsValid = task.trim().length > 0;

  const estimate = useMemo(
    () =>
      estimateDemocracyCost(
        { organizer: resolvedOrganizer, participants: chosen },
        models,
      ),
    // `chosen` is derived per render; keying on its contents keeps the estimate
    // from recomputing on every keystroke in the task field.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [resolvedOrganizer, chosen.join(" "), models],
  );

  const setParticipantAt = useCallback((index: number, name: string) => {
    setParticipants((previous) => {
      const next = [...previous];
      while (next.length <= index) next.push("");
      next[index] = name;
      return next;
    });
  }, []);

  const handleStart = useCallback(() => {
    if (!panelIsValid || !taskIsValid || !resolvedOrganizer) return;
    // Files first: the launch stash fires the claim event, and the chat that
    // claims it reads the files in the same tick.
    stashDemocracyFiles(files);
    stashDemocracyLaunch({
      organizer: resolvedOrganizer,
      participants: chosen,
      task: task.trim(),
      grading,
    });
    router.push("/workspace/chats/new");
  }, [
    chosen,
    files,
    grading,
    panelIsValid,
    resolvedOrganizer,
    router,
    task,
    taskIsValid,
  ]);

  const unpricedNames = estimate.unpricedParticipants
    .map((name) => modelLabel(models, name))
    .join(", ");

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="overflow-y-auto">
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-4 sm:p-6">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold">
              <UsersRoundIcon className="size-5" />
              {t.democracy.title}
            </h1>
            <p className="text-muted-foreground mt-1 text-sm">
              {t.democracy.description}
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              className="text-sm font-medium"
              htmlFor="democracy-panelist-count"
            >
              {t.democracy.panelists}
            </label>
            <Input
              id="democracy-panelist-count"
              className="max-w-32"
              type="number"
              min={MIN_DEMOCRACY_PARTICIPANTS}
              max={MAX_DEMOCRACY_PARTICIPANTS}
              value={count}
              onChange={(event) =>
                setCount(clampParticipantCount(event.target.valueAsNumber))
              }
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium">
              {t.democracy.organizer}
            </label>
            <ModelSelect
              value={resolvedOrganizer}
              models={organizerModels}
              placeholder={t.democracy.pickModel}
              onChange={setOrganizer}
              data-testid="democracy-organizer-model"
            />
            <p className="text-muted-foreground text-xs">
              {t.democracy.organizerHint}
            </p>
          </div>

          <div className="flex flex-col gap-3">
            {roster.map((name, index) => (
              <div key={index} className="flex flex-col gap-1.5">
                <label className="text-sm font-medium">
                  {t.democracy.panelist(index + 1)}
                </label>
                <ModelSelect
                  value={name}
                  models={panelistModels}
                  placeholder={t.democracy.pickModel}
                  onChange={(next) => setParticipantAt(index, next)}
                  demoteLast={lacksToolSupport}
                  data-testid={`democracy-panelist-${index}`}
                />
              </div>
            ))}
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium">{t.democracy.grading}</label>
            <Select
              value={grading}
              onValueChange={(next) => setGrading(next as DemocracyGrading)}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DEMOCRACY_GRADING_OPTIONS.map((option) => (
                  <SelectItem key={option} value={option}>
                    {t.democracy.gradingOption(option)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">
              {t.democracy.gradingHint}
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium" htmlFor="democracy-task">
              {t.democracy.task}
            </label>
            <Textarea
              id="democracy-task"
              rows={5}
              value={task}
              placeholder={t.democracy.taskPlaceholder}
              onChange={(event) => setTask(event.target.value)}
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => fileInputRef.current?.click()}
              >
                <PaperclipIcon className="size-3.5" />
                {t.democracy.attachFiles}
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                aria-label={t.democracy.attachFiles}
                onChange={(event) => {
                  const picked = Array.from(event.target.files ?? []);
                  if (picked.length > 0) {
                    setFiles((previous) => [...previous, ...picked]);
                  }
                  // Reset so re-picking the same file fires `change` again.
                  event.target.value = "";
                }}
              />
              {files.length === 0 && (
                <span className="text-muted-foreground text-xs">
                  {t.democracy.attachHint}
                </span>
              )}
            </div>
            {files.length > 0 && (
              <ul className="flex flex-col gap-1">
                {files.map((file, index) => (
                  <li
                    key={`${file.name}-${index}`}
                    className="bg-muted/50 flex items-center gap-2 rounded px-2 py-1 text-xs"
                  >
                    <PaperclipIcon className="size-3 shrink-0" />
                    <span className="truncate">{file.name}</span>
                    <button
                      type="button"
                      className="text-muted-foreground hover:text-foreground ml-auto"
                      aria-label={t.democracy.removeFile(file.name)}
                      onClick={() =>
                        setFiles((previous) =>
                          previous.filter((_, i) => i !== index),
                        )
                      }
                    >
                      <XIcon className="size-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div
            className="flex flex-col gap-1 rounded-md border border-amber-500/40 bg-amber-500/5 p-3"
            role="note"
          >
            <div className="flex items-center gap-2 text-sm font-medium text-amber-600 dark:text-amber-500">
              <AlertTriangleIcon className="size-4 shrink-0" />
              {t.democracy.costTitle}
            </div>
            <p className="text-muted-foreground text-xs">
              {t.democracy.costRuns(Math.max(count, chosen.length) * 2)}
            </p>
            {estimate.rateMultiple !== null && (
              <p className="text-muted-foreground text-xs">
                {t.democracy.costMultiple(estimate.rateMultiple)}
              </p>
            )}
            {unpricedNames.length > 0 && (
              <p className="text-muted-foreground text-xs">
                {t.democracy.costUnpriced(unpricedNames)}
              </p>
            )}
            <p className="text-muted-foreground text-xs">
              {t.democracy.costPerTurn}
            </p>
            <p className="text-muted-foreground text-xs">
              {t.democracy.costHint}
            </p>
          </div>

          {hasDuplicates && (
            <p className="text-destructive text-xs">
              {t.democracy.duplicateWarning}
            </p>
          )}
          {!hasDuplicates && !hasEveryPanelist && (
            <p className="text-muted-foreground text-xs">
              {t.democracy.incompleteWarning}
            </p>
          )}
          {hasEveryPanelist && !hasDuplicates && !taskIsValid && (
            <p className="text-muted-foreground text-xs">
              {t.democracy.taskWarning}
            </p>
          )}

          <div className="flex items-center gap-2 pb-6">
            <Button
              onClick={handleStart}
              disabled={!panelIsValid || !taskIsValid || !resolvedOrganizer}
            >
              {t.democracy.start}
            </Button>
            <Button variant="ghost" onClick={() => router.back()}>
              {t.democracy.cancel}
            </Button>
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function modelLabel(models: readonly Model[], name: string): string {
  const model = models.find((entry) => entry.name === name);
  return model?.display_name ?? name;
}
