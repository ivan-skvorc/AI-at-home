"use client";

import {
  ArrowLeftIcon,
  BotIcon,
  CalendarClockIcon,
  CheckIcon,
  LightbulbIcon,
  MessageSquareIcon,
  SparklesIcon,
  WandSparklesIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
  AgentGenerationError,
  canAnalyze,
  canRefine,
  goalLength,
  isGoalWithinCap,
  isSelected,
  normalizeGoal,
  toggleSource,
  useAgentGenerationConfig,
  useAnalyzeSources,
} from "@/core/agent-generation";
import type {
  AnalyzeRequest,
  AnalyzeResult,
  GenerationSource,
} from "@/core/agent-generation/types";
import { useCreateAgent } from "@/core/agents/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { useScheduledTasks } from "@/core/scheduled-tasks/hooks";
import { useThreads } from "@/core/threads/hooks";
import { cn } from "@/lib/utils";

const DEFAULT_MODEL_VALUE = "__default__";

type Step = "select" | "result";

/**
 * One selectable conversation / scheduled task row.
 *
 * Rendered as a button rather than a checkbox so the whole row is the hit
 * target; `aria-pressed` carries the state that a checkbox would have carried.
 */
function SourceRow({
  icon,
  title,
  subtitle,
  selected,
  disabled,
  onToggle,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  selected: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled && !selected}
      onClick={onToggle}
      className={cn(
        "flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors",
        selected ? "border-primary bg-primary/5" : "hover:bg-muted/50",
        disabled && !selected && "cursor-not-allowed opacity-50",
      )}
    >
      <span className="text-muted-foreground shrink-0">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{title}</span>
        <span className="text-muted-foreground block truncate text-xs">
          {subtitle}
        </span>
      </span>
      <span
        className={cn(
          "flex h-5 w-5 shrink-0 items-center justify-center rounded border",
          selected ? "border-primary bg-primary text-primary-foreground" : "",
        )}
      >
        {selected ? <CheckIcon className="h-3.5 w-3.5" /> : null}
      </span>
    </button>
  );
}

export function AgentGenerator() {
  const { t } = useI18n();
  const router = useRouter();

  const {
    config,
    enabled,
    isLoading: isConfigLoading,
  } = useAgentGenerationConfig();
  const { models } = useModels();
  const { data: threads = [], isLoading: isThreadsLoading } = useThreads();
  const { data: tasks = [], isLoading: isTasksLoading } = useScheduledTasks();
  const analyze = useAnalyzeSources();
  const createAgent = useCreateAgent();

  const [step, setStep] = useState<Step>("select");
  const [goal, setGoal] = useState("");
  const [refinement, setRefinement] = useState("");
  const [modelValue, setModelValue] = useState(DEFAULT_MODEL_VALUE);
  const [selection, setSelection] = useState<GenerationSource[]>([]);
  const [result, setResult] = useState<AnalyzeResult | null>(null);
  const [draftName, setDraftName] = useState("");
  const [draftDescription, setDraftDescription] = useState("");
  const [draftSoul, setDraftSoul] = useState("");

  const maxSources = config?.max_sources ?? 0;
  const maxGoalChars = config?.max_goal_chars ?? 0;
  const atCap = maxSources > 0 && selection.length >= maxSources;
  const goalWithinCap = isGoalWithinCap(goal, maxGoalChars);

  const handleToggle = useCallback(
    (source: GenerationSource) => {
      setSelection((current) => {
        const next = toggleSource(current, source, maxSources);
        if (next === current) {
          toast.warning(t.agentGeneration.capReached(maxSources));
        }
        return next;
      });
    },
    [maxSources, t],
  );

  // One call path for all three buttons — Analyze, Generate anyway, Refine —
  // so the draft-state bookkeeping after a successful run cannot drift between
  // them. Only the request differs.
  const run = useCallback(
    async (extra: Partial<AnalyzeRequest>) => {
      try {
        const analysis = await analyze.mutateAsync({
          sources: selection,
          model_name: modelValue === DEFAULT_MODEL_VALUE ? null : modelValue,
          ...extra,
        });
        setResult(analysis);
        if (analysis.proposal) {
          setDraftName(analysis.proposal.name);
          setDraftDescription(analysis.proposal.description);
          setDraftSoul(analysis.proposal.soul);
          setRefinement("");
        }
        setStep("result");
      } catch (error) {
        const message =
          error instanceof AgentGenerationError
            ? error.message
            : t.agentGeneration.analyzeFailed;
        toast.error(message);
      }
    },
    [analyze, modelValue, selection, t],
  );

  const handleAnalyze = useCallback(
    () => run({ goal: normalizeGoal(goal) }),
    [goal, run],
  );

  const handleGenerateAnyway = useCallback(
    () => run({ goal: normalizeGoal(goal), force_proposal: true }),
    [goal, run],
  );

  // Refining sends the draft as it currently stands in the form, hand edits and
  // all, so the model revises what the user is looking at rather than the last
  // thing it generated.
  const handleRefine = useCallback(
    () =>
      run({
        goal: normalizeGoal(refinement),
        revise_from: {
          name: draftName,
          description: draftDescription,
          soul: draftSoul,
        },
      }),
    [draftDescription, draftName, draftSoul, refinement, run],
  );

  const handleCreate = useCallback(async () => {
    if (!result?.proposal) {
      return;
    }
    try {
      const created = await createAgent.mutateAsync({
        name: draftName.trim(),
        description: draftDescription.trim(),
        soul: draftSoul,
        skills: result.proposal.skills,
      });
      toast.success(t.agentGeneration.created);
      router.push(`/workspace/agents/${created.name}/chats`);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.agentGeneration.createFailed,
      );
    }
  }, [createAgent, draftDescription, draftName, draftSoul, result, router, t]);

  const isSourcesLoading = isThreadsLoading || isTasksLoading;
  const hasSources = threads.length > 0 || tasks.length > 0;

  const selectionSummary = useMemo(
    () =>
      maxSources > 0
        ? t.agentGeneration.selectedCount(selection.length, maxSources)
        : String(selection.length),
    [maxSources, selection.length, t],
  );

  if (isConfigLoading) {
    return (
      <div className="text-muted-foreground flex h-40 items-center justify-center text-sm">
        {t.common.loading}
      </div>
    );
  }

  if (!enabled) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="font-medium">{t.agentGeneration.disabledTitle}</p>
        <p className="text-muted-foreground max-w-md text-sm">
          {t.agentGeneration.disabledDescription}
        </p>
        <Button
          variant="outline"
          onClick={() => router.push("/workspace/agents")}
        >
          <ArrowLeftIcon className="mr-1.5 h-4 w-4" />
          {t.agents.backToGallery}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex size-full flex-col">
      <div className="flex items-center gap-3 border-b px-6 py-4">
        <Button
          variant="ghost"
          size="icon"
          onClick={() =>
            step === "result"
              ? setStep("select")
              : router.push("/workspace/agents")
          }
          aria-label={t.agents.backToGallery}
        >
          <ArrowLeftIcon className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-xl font-semibold">{t.agentGeneration.title}</h1>
          <p className="text-muted-foreground mt-0.5 text-sm">
            {t.agentGeneration.description}
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {step === "select" ? (
          <div className="mx-auto flex max-w-3xl flex-col gap-6">
            <div className="space-y-1.5">
              <div className="flex items-baseline justify-between">
                <span className="text-sm font-medium">
                  {t.agentGeneration.goalLabel}
                </span>
                <span className="text-muted-foreground text-xs">
                  {t.agentGeneration.optional}
                </span>
              </div>
              <Textarea
                value={goal}
                onChange={(event) => setGoal(event.target.value)}
                placeholder={t.agentGeneration.goalPlaceholder}
                className="min-h-20"
              />
              <div className="flex items-baseline justify-between gap-4">
                <p className="text-muted-foreground text-xs">
                  {t.agentGeneration.goalHint}
                </p>
                {maxGoalChars > 0 && goalLength(goal) > 0 ? (
                  <span
                    className={cn(
                      "shrink-0 text-xs tabular-nums",
                      goalWithinCap
                        ? "text-muted-foreground"
                        : "text-destructive",
                    )}
                  >
                    {goalLength(goal)}/{maxGoalChars}
                  </span>
                ) : null}
              </div>
            </div>

            <div className="space-y-1.5">
              <span className="text-sm font-medium">
                {t.agentGeneration.modelLabel}
              </span>
              <Select value={modelValue} onValueChange={setModelValue}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DEFAULT_MODEL_VALUE}>
                    {t.agentGeneration.modelDefault}
                  </SelectItem>
                  {models.map((model) => (
                    <SelectItem key={model.name} value={model.name}>
                      {model.display_name || model.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">
                {t.agentGeneration.modelHint}
              </p>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">
                  {t.agentGeneration.sourcesLabel}
                </span>
                <Badge variant="secondary">{selectionSummary}</Badge>
              </div>
              <p className="text-muted-foreground text-xs">
                {t.agentGeneration.sourcesHint}
              </p>

              {isSourcesLoading ? (
                <div className="text-muted-foreground py-6 text-center text-sm">
                  {t.common.loading}
                </div>
              ) : !hasSources ? (
                <Alert>
                  <AlertDescription>
                    {t.agentGeneration.noSources}
                  </AlertDescription>
                </Alert>
              ) : (
                <div className="flex flex-col gap-4">
                  {threads.length > 0 ? (
                    <div className="space-y-2">
                      <span className="text-muted-foreground text-xs font-medium uppercase">
                        {t.agentGeneration.conversations}
                      </span>
                      <div className="flex flex-col gap-1.5">
                        {threads.map((thread) => {
                          const source: GenerationSource = {
                            kind: "thread",
                            id: thread.thread_id,
                          };
                          return (
                            <SourceRow
                              key={thread.thread_id}
                              icon={<MessageSquareIcon className="h-4 w-4" />}
                              title={
                                thread.values?.title ||
                                t.agentGeneration.untitledConversation
                              }
                              subtitle={thread.updated_at ?? ""}
                              selected={isSelected(selection, source)}
                              disabled={atCap}
                              onToggle={() => handleToggle(source)}
                            />
                          );
                        })}
                      </div>
                    </div>
                  ) : null}

                  {tasks.length > 0 ? (
                    <div className="space-y-2">
                      <span className="text-muted-foreground text-xs font-medium uppercase">
                        {t.agentGeneration.scheduledTasks}
                      </span>
                      <div className="flex flex-col gap-1.5">
                        {tasks.map((task) => {
                          const source: GenerationSource = {
                            kind: "scheduled_task",
                            id: task.id,
                          };
                          return (
                            <SourceRow
                              key={task.id}
                              icon={<CalendarClockIcon className="h-4 w-4" />}
                              title={task.title}
                              subtitle={task.prompt}
                              selected={isSelected(selection, source)}
                              disabled={atCap}
                              onToggle={() => handleToggle(source)}
                            />
                          );
                        })}
                      </div>
                    </div>
                  ) : null}
                </div>
              )}
            </div>

            <div className="flex justify-end">
              <Button
                onClick={() => void handleAnalyze()}
                disabled={
                  !canAnalyze(selection, maxSources) ||
                  !goalWithinCap ||
                  analyze.isPending
                }
              >
                <SparklesIcon className="mr-1.5 h-4 w-4" />
                {analyze.isPending
                  ? t.agentGeneration.analyzing
                  : t.agentGeneration.analyze}
              </Button>
            </div>
          </div>
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-6">
            {result?.verdict === "no_gap" ? (
              <div className="flex flex-col items-center gap-3 py-10 text-center">
                <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
                  <LightbulbIcon className="text-muted-foreground h-7 w-7" />
                </div>
                <p className="font-medium">{t.agentGeneration.noGapTitle}</p>
                <p className="text-muted-foreground max-w-lg text-sm">
                  {result.rationale}
                </p>
                {result.covered_by ? (
                  <p className="text-muted-foreground text-sm">
                    {t.agentGeneration.coveredBy(result.covered_by)}
                  </p>
                ) : null}
                <div className="mt-2 flex flex-wrap justify-center gap-2">
                  <Button variant="outline" onClick={() => setStep("select")}>
                    {t.agentGeneration.changeSelection}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => void handleGenerateAnyway()}
                    disabled={analyze.isPending}
                  >
                    <SparklesIcon className="mr-1.5 h-4 w-4" />
                    {analyze.isPending
                      ? t.agentGeneration.analyzing
                      : t.agentGeneration.generateAnyway}
                  </Button>
                  <Button onClick={() => router.push("/workspace/agents")}>
                    {t.agents.backToGallery}
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <Alert>
                  <BotIcon className="h-4 w-4" />
                  <AlertDescription>
                    {result?.rationale}
                    {result?.forced && result?.covered_by ? (
                      <span className="text-muted-foreground mt-1 block">
                        {t.agentGeneration.overlapNote(result.covered_by)}
                      </span>
                    ) : null}
                  </AlertDescription>
                </Alert>

                <div className="space-y-1.5">
                  <span className="text-sm font-medium">
                    {t.agentGeneration.proposalName}
                  </span>
                  <Input
                    value={draftName}
                    onChange={(event) => setDraftName(event.target.value)}
                  />
                </div>

                <div className="space-y-1.5">
                  <span className="text-sm font-medium">
                    {t.agentGeneration.proposalDescription}
                  </span>
                  <Input
                    value={draftDescription}
                    onChange={(event) =>
                      setDraftDescription(event.target.value)
                    }
                  />
                </div>

                <div className="space-y-1.5">
                  <span className="text-sm font-medium">
                    {t.agentGeneration.proposalSoul}
                  </span>
                  <Textarea
                    value={draftSoul}
                    onChange={(event) => setDraftSoul(event.target.value)}
                    className="min-h-72 font-mono text-xs"
                  />
                  <p className="text-muted-foreground text-xs">
                    {t.agentGeneration.proposalSoulHint}
                  </p>
                </div>

                <div className="space-y-1.5 rounded-md border p-3">
                  <span className="text-sm font-medium">
                    {t.agentGeneration.refineLabel}
                  </span>
                  <div className="flex items-start gap-2">
                    <Textarea
                      value={refinement}
                      onChange={(event) => setRefinement(event.target.value)}
                      placeholder={t.agentGeneration.refinePlaceholder}
                      className="min-h-16 flex-1"
                    />
                    <Button
                      variant="outline"
                      onClick={() => void handleRefine()}
                      disabled={
                        !canRefine(refinement, maxGoalChars) ||
                        analyze.isPending
                      }
                    >
                      <WandSparklesIcon className="mr-1.5 h-4 w-4" />
                      {analyze.isPending
                        ? t.agentGeneration.refining
                        : t.agentGeneration.refine}
                    </Button>
                  </div>
                  <p className="text-muted-foreground text-xs">
                    {t.agentGeneration.refineHint}
                  </p>
                </div>

                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setStep("select")}>
                    {t.agentGeneration.changeSelection}
                  </Button>
                  <Button
                    onClick={() => void handleCreate()}
                    disabled={
                      !draftName.trim() ||
                      !draftSoul.trim() ||
                      createAgent.isPending
                    }
                  >
                    <CheckIcon className="mr-1.5 h-4 w-4" />
                    {createAgent.isPending
                      ? t.agentGeneration.creating
                      : t.agentGeneration.create}
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
