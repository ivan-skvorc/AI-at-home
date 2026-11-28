"use client";

import {
  CheckIcon,
  GraduationCapIcon,
  LightbulbIcon,
  RocketIcon,
  TriangleAlertIcon,
  UsersRoundIcon,
  WorkflowIcon,
  ZapIcon,
} from "lucide-react";
import { useCallback, useMemo } from "react";

import {
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuItem,
  PromptInputActionMenuTrigger,
  PromptInputButton,
} from "@/components/ai-elements/prompt-input";
import {
  DropdownMenuGroup,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import { lacksToolSupport } from "@/core/models/capabilities";
import {
  getReasoningEffortOptions,
  type InputMode,
  isThinkingRequired,
  type ReasoningEffortValue,
  reasoningEffortForMode,
  resolveReasoningEffort,
  supportsThinking as modelSupportsThinking,
} from "@/core/models/reasoning";
import type { Model } from "@/core/models/types";
import { useLocalSettings } from "@/core/settings";
import { isWorkflowScriptMode } from "@/core/threads/ultracode";
import { cn } from "@/lib/utils";

import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "../ai-elements/model-selector";

import {
  DoubleUltracodeWarningTooltip,
  ModeHoverGuide,
} from "./mode-hover-guide";
import {
  ModelDisplayName,
  ModelPickerControls,
  ModelPickerList,
  ModelPickerRow,
} from "./model-picker-controls";

/*
 * The run controls of the main chat composer: the mode menu, the reasoning
 * effort menu and the main-agent and subagent model pickers. `InputBox` renders
 * them, and so does the composer-controls hook plugin pages mount
 * (`plugin-composer-controls.tsx`), so a plugin page offers the same modes,
 * rows, search, sorting and hover guides as the chat. They only draw: each
 * caller owns its selection and its capability resolution.
 */

/** The mode menu: every mode the selected model and the installed extensions allow. */
export function ComposerModeMenu({
  mode,
  model,
  ultracodeAvailable,
  disabled,
  onSelect,
}: {
  mode: InputMode | undefined;
  model: Model | undefined;
  /** Plus and Double Plus Ultracode need the Script workflows extension. */
  ultracodeAvailable: boolean;
  disabled?: boolean;
  onSelect: (mode: InputMode) => void;
}) {
  const { t } = useI18n();
  const supportThinking = useMemo(() => modelSupportsThinking(model), [model]);
  const thinkingRequired = useMemo(() => isThinkingRequired(model), [model]);
  const workflowMode = isWorkflowScriptMode(mode);
  return (
    <PromptInputActionMenu>
      <ModeHoverGuide
        mode={
          mode === "flash" ||
          mode === "thinking" ||
          mode === "pro" ||
          mode === "ultra" ||
          mode === "democracy" ||
          mode === "ultracode" ||
          mode === "double_ultracode"
            ? mode
            : "flash"
        }
      >
        <PromptInputActionMenuTrigger
          className="max-w-28 gap-1! px-2! sm:max-w-none"
          disabled={disabled}
        >
          <div>
            {mode === "flash" && <ZapIcon className="size-3" />}
            {mode === "thinking" && <LightbulbIcon className="size-3" />}
            {mode === "pro" && <GraduationCapIcon className="size-3" />}
            {mode === "ultra" && (
              <RocketIcon className="size-3 text-[#dabb5e]" />
            )}
            {mode === "democracy" && (
              <UsersRoundIcon className="size-3 text-[#7c9ec4]" />
            )}
            {mode === "ultracode" && (
              <WorkflowIcon className="size-3 text-[#dabb5e]" />
            )}
            {mode === "double_ultracode" && (
              <TriangleAlertIcon className="size-3 text-[#dabb5e]" />
            )}
          </div>
          <div
            className={cn(
              "truncate text-xs font-normal",
              mode === "ultra" || workflowMode ? "golden-text" : "",
            )}
          >
            {(mode === "flash" && t.inputBox.flashMode) ||
              (mode === "thinking" && t.inputBox.reasoningMode) ||
              (mode === "pro" && t.inputBox.proMode) ||
              (mode === "ultra" && t.inputBox.ultraMode) ||
              (mode === "democracy" && t.inputBox.democracyMode) ||
              (mode === "ultracode" && t.inputBox.ultracodeMode) ||
              (mode === "double_ultracode" && t.inputBox.doubleUltracodeMode)}
          </div>
        </PromptInputActionMenuTrigger>
      </ModeHoverGuide>
      <PromptInputActionMenuContent className="w-80">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-muted-foreground text-xs">
            {t.inputBox.mode}
          </DropdownMenuLabel>
          <PromptInputActionMenu>
            {!thinkingRequired && (
              <PromptInputActionMenuItem
                className={cn(
                  mode === "flash"
                    ? "text-accent-foreground"
                    : "text-muted-foreground/65",
                )}
                onSelect={() => onSelect("flash")}
              >
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-1 font-bold">
                    <ZapIcon
                      className={cn(
                        "mr-2 size-4",
                        mode === "flash" && "text-accent-foreground",
                      )}
                    />
                    {t.inputBox.flashMode}
                  </div>
                  <div className="pl-7 text-xs">
                    {t.inputBox.flashModeDescription}
                  </div>
                </div>
                {mode === "flash" ? (
                  <CheckIcon className="ml-auto size-4" />
                ) : (
                  <div className="ml-auto size-4" />
                )}
              </PromptInputActionMenuItem>
            )}
            {supportThinking && (
              <PromptInputActionMenuItem
                className={cn(
                  mode === "thinking"
                    ? "text-accent-foreground"
                    : "text-muted-foreground/65",
                )}
                onSelect={() => onSelect("thinking")}
              >
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-1 font-bold">
                    <LightbulbIcon
                      className={cn(
                        "mr-2 size-4",
                        mode === "thinking" && "text-accent-foreground",
                      )}
                    />
                    {t.inputBox.reasoningMode}
                  </div>
                  <div className="pl-7 text-xs">
                    {t.inputBox.reasoningModeDescription}
                  </div>
                </div>
                {mode === "thinking" ? (
                  <CheckIcon className="ml-auto size-4" />
                ) : (
                  <div className="ml-auto size-4" />
                )}
              </PromptInputActionMenuItem>
            )}
            <PromptInputActionMenuItem
              className={cn(
                mode === "pro"
                  ? "text-accent-foreground"
                  : "text-muted-foreground/65",
              )}
              onSelect={() => onSelect("pro")}
            >
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1 font-bold">
                  <GraduationCapIcon
                    className={cn(
                      "mr-2 size-4",
                      mode === "pro" && "text-accent-foreground",
                    )}
                  />
                  {t.inputBox.proMode}
                </div>
                <div className="pl-7 text-xs">
                  {t.inputBox.proModeDescription}
                </div>
              </div>
              {mode === "pro" ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </PromptInputActionMenuItem>
            <PromptInputActionMenuItem
              className={cn(
                mode === "ultra"
                  ? "text-accent-foreground"
                  : "text-muted-foreground/65",
              )}
              onSelect={() => onSelect("ultra")}
            >
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1 font-bold">
                  <RocketIcon
                    className={cn(
                      "mr-2 size-4",
                      mode === "ultra" && "text-[#dabb5e]",
                    )}
                  />
                  <div className={cn(mode === "ultra" && "golden-text")}>
                    {t.inputBox.ultraMode}
                  </div>
                </div>
                <div className="pl-7 text-xs">
                  {t.inputBox.ultraModeDescription}
                </div>
              </div>
              {mode === "ultra" ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </PromptInputActionMenuItem>
            {ultracodeAvailable && (
              <PromptInputActionMenuItem
                className={cn(
                  mode === "ultracode"
                    ? "text-accent-foreground"
                    : "text-muted-foreground/65",
                )}
                onSelect={() => onSelect("ultracode")}
              >
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-1 font-bold">
                    <WorkflowIcon
                      className={cn(
                        "mr-2 size-4",
                        mode === "ultracode" && "text-[#dabb5e]",
                      )}
                    />
                    <div className={cn(mode === "ultracode" && "golden-text")}>
                      {t.inputBox.ultracodeMode}
                    </div>
                  </div>
                  <div className="pl-7 text-xs">
                    {t.inputBox.ultracodeModeDescription}
                  </div>
                </div>
                {mode === "ultracode" ? (
                  <CheckIcon className="ml-auto size-4" />
                ) : (
                  <div className="ml-auto size-4" />
                )}
              </PromptInputActionMenuItem>
            )}
            {ultracodeAvailable && (
              <DoubleUltracodeWarningTooltip>
                <PromptInputActionMenuItem
                  className={cn(
                    mode === "double_ultracode"
                      ? "text-accent-foreground"
                      : "text-muted-foreground/65",
                  )}
                  onSelect={() => onSelect("double_ultracode")}
                >
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-1 font-bold">
                      <TriangleAlertIcon
                        className={cn(
                          "mr-2 size-4",
                          mode === "double_ultracode" && "text-[#dabb5e]",
                        )}
                      />
                      <div
                        className={cn(
                          mode === "double_ultracode" && "golden-text",
                        )}
                      >
                        {t.inputBox.doubleUltracodeMode}
                      </div>
                    </div>
                    <div className="pl-7 text-xs">
                      {t.inputBox.doubleUltracodeModeDescription}
                    </div>
                  </div>
                  {mode === "double_ultracode" ? (
                    <CheckIcon className="ml-auto size-4" />
                  ) : (
                    <div className="ml-auto size-4" />
                  )}
                </PromptInputActionMenuItem>
              </DoubleUltracodeWarningTooltip>
            )}
          </PromptInputActionMenu>
        </DropdownMenuGroup>
      </PromptInputActionMenuContent>
    </PromptInputActionMenu>
  );
}

/**
 * The reasoning-effort menu. Its choices come from the model's reasoning
 * contract (issue #5073); it renders nothing in Flash or for a model without an
 * effort control.
 */
export function ComposerReasoningEffortMenu({
  mode,
  model,
  reasoningEffort,
  disabled,
  onSelect,
}: {
  mode: InputMode | undefined;
  model: Model | undefined;
  reasoningEffort: ReasoningEffortValue | undefined;
  disabled?: boolean;
  onSelect: (effort: ReasoningEffortValue) => void;
}) {
  const { t } = useI18n();
  const reasoningEffortOptions = useMemo(
    () => getReasoningEffortOptions(model),
    [model],
  );
  const effectiveReasoningEffort = useMemo(
    () =>
      resolveReasoningEffort(
        model,
        reasoningEffort ?? reasoningEffortForMode(mode ?? "pro", model),
      ),
    [mode, reasoningEffort, model],
  );
  const reasoningEffortLabel = useCallback(
    (effort: string | undefined) => {
      switch (effort) {
        case "minimal":
          return t.inputBox.reasoningEffortMinimal;
        case "low":
          return t.inputBox.reasoningEffortLow;
        case "medium":
          return t.inputBox.reasoningEffortMedium;
        case "high":
          return t.inputBox.reasoningEffortHigh;
        case "xhigh":
          return t.inputBox.reasoningEffortXhigh;
        case "max":
          return t.inputBox.reasoningEffortMax;
        default:
          return effort ?? "";
      }
    },
    [t],
  );
  const reasoningEffortDescription = useCallback(
    (effort: string) => {
      switch (effort) {
        case "minimal":
          return t.inputBox.reasoningEffortMinimalDescription;
        case "low":
          return t.inputBox.reasoningEffortLowDescription;
        case "medium":
          return t.inputBox.reasoningEffortMediumDescription;
        case "high":
          return t.inputBox.reasoningEffortHighDescription;
        case "xhigh":
          return t.inputBox.reasoningEffortXhighDescription;
        case "max":
          return t.inputBox.reasoningEffortMaxDescription;
        default:
          return null;
      }
    },
    [t],
  );
  if (reasoningEffortOptions.length === 0 || mode === "flash") {
    return null;
  }
  return (
    <PromptInputActionMenu>
      <PromptInputActionMenuTrigger
        className="hidden gap-1! px-2! sm:inline-flex"
        disabled={disabled}
        aria-label={`${t.inputBox.reasoningEffort}: ${reasoningEffortLabel(effectiveReasoningEffort)}`}
      >
        <div className="text-xs font-normal">
          <span className="hidden @[40rem]/composer-footer:inline">
            {t.inputBox.reasoningEffort}:{" "}
          </span>
          {reasoningEffortLabel(effectiveReasoningEffort)}
        </div>
      </PromptInputActionMenuTrigger>
      <PromptInputActionMenuContent className="w-70">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-muted-foreground text-xs">
            {t.inputBox.reasoningEffort}
          </DropdownMenuLabel>
          <PromptInputActionMenu>
            {reasoningEffortOptions.map((effort) => (
              <PromptInputActionMenuItem
                key={effort}
                className={cn(
                  effectiveReasoningEffort === effort
                    ? "text-accent-foreground"
                    : "text-muted-foreground/65",
                )}
                onSelect={() => onSelect(effort)}
              >
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-1 font-bold">
                    {reasoningEffortLabel(effort)}
                  </div>
                  {reasoningEffortDescription(effort) && (
                    <div className="pl-2 text-xs">
                      {reasoningEffortDescription(effort)}
                    </div>
                  )}
                </div>
                {effectiveReasoningEffort === effort ? (
                  <CheckIcon className="ml-auto size-4" />
                ) : (
                  <div className="ml-auto size-4" />
                )}
              </PromptInputActionMenuItem>
            ))}
          </PromptInputActionMenu>
        </DropdownMenuGroup>
      </PromptInputActionMenuContent>
    </PromptInputActionMenu>
  );
}

/**
 * The main agent's model picker. In Ultra and both Ultracode modes a model
 * without tool support is shown but disabled: those modes delegate through tools.
 */
export function ComposerModelPicker({
  models,
  selectedModel,
  selectedName,
  mode,
  open,
  onOpenChange,
  disabled,
  triggerClassName,
  onSelect,
}: {
  models: Model[];
  /** The model the trigger shows. */
  selectedModel: Model | undefined;
  /** The stored choice the check mark follows; a thread context value, so not narrowed. */
  selectedName: unknown;
  mode: InputMode | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  disabled?: boolean;
  triggerClassName?: string;
  onSelect: (modelName: string) => void;
}) {
  const { t } = useI18n();
  const [localSettings, setLocalSettings] = useLocalSettings();
  const workflowMode = isWorkflowScriptMode(mode);
  return (
    <ModelSelector open={open} onOpenChange={onOpenChange}>
      <ModelSelectorTrigger asChild>
        <PromptInputButton className={triggerClassName} disabled={disabled}>
          <div className="flex min-w-0 flex-col text-left">
            <span className="text-muted-foreground text-[10px] leading-none">
              Main agent
            </span>
            <ModelSelectorName className="w-full text-xs font-normal">
              <ModelDisplayName
                displayName={selectedModel?.display_name}
                price={selectedModel?.price}
                variant="compact"
              />
            </ModelSelectorName>
          </div>
        </PromptInputButton>
      </ModelSelectorTrigger>
      <ModelSelectorContent>
        <ModelSelectorInput placeholder={t.inputBox.searchModels} />
        <ModelPickerControls
          prefs={localSettings.modelPicker}
          onChange={(next) => setLocalSettings("modelPicker", next)}
        />
        <ModelPickerList
          models={models}
          prefs={localSettings.modelPicker}
          renderItem={(m) => {
            // Ultra mode delegates via the `task` tool (Double Plus
            // Ultracode via the workflow tools), so the lead model must
            // be able to call tools.
            const unusable =
              (mode === "ultra" || workflowMode) && lacksToolSupport(m);
            return (
              <ModelSelectorItem
                key={m.name}
                value={m.name}
                disabled={unusable}
                onSelect={() => onSelect(m.name)}
              >
                <ModelPickerRow
                  model={m}
                  showProvider={!localSettings.modelPicker.groupByProvider}
                  annotation={
                    unusable && (
                      <span className="text-muted-foreground shrink-0 text-[10px]">
                        {t.inputBox.noToolSupport}
                      </span>
                    )
                  }
                />
                {m.name === selectedName ? (
                  <CheckIcon className="ml-auto size-4" />
                ) : (
                  <div className="ml-auto size-4" />
                )}
              </ModelSelectorItem>
            );
          }}
        />
      </ModelSelectorContent>
    </ModelSelector>
  );
}

/**
 * The subagent model picker of Ultra and both Ultracode modes. Deliberately not
 * rendered for Democracy: a panel names its model per `task` call, and a
 * thread-wide subagent override would be outranked by every one of them (see
 * FORK.md §22 precedence).
 */
export function ComposerSubagentModelPicker({
  models,
  selectedName,
  open,
  onOpenChange,
  onSelect,
}: {
  models: Model[];
  /** The stored choice; `undefined` follows the lead agent's model. */
  selectedName: unknown;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (modelName: string | undefined) => void;
}) {
  const { t } = useI18n();
  const [localSettings, setLocalSettings] = useLocalSettings();
  const subagentSelected = useMemo(
    () => models.find((m) => m.name === selectedName),
    [selectedName, models],
  );
  return (
    <ModelSelector open={open} onOpenChange={onOpenChange}>
      <ModelSelectorTrigger asChild>
        <PromptInputButton>
          <div className="flex min-w-0 flex-col items-start text-left">
            <span className="text-muted-foreground text-[10px] leading-none">
              Subagent
            </span>
            <ModelSelectorName className="w-full text-xs font-normal">
              {subagentSelected ? (
                <ModelDisplayName
                  displayName={subagentSelected.display_name}
                  price={subagentSelected.price}
                  variant="compact"
                />
              ) : (
                "Follow lead"
              )}
            </ModelSelectorName>
          </div>
        </PromptInputButton>
      </ModelSelectorTrigger>
      <ModelSelectorContent>
        <ModelSelectorInput placeholder={t.inputBox.searchModels} />
        <ModelPickerControls
          prefs={localSettings.modelPicker}
          onChange={(next) => setLocalSettings("modelPicker", next)}
        />
        <ModelPickerList
          models={models}
          prefs={localSettings.modelPicker}
          // Keep tool-incapable models at the bottom (FORK.md §3).
          demoteLast={lacksToolSupport}
          leading={
            <ModelSelectorItem
              key="__follow_lead__"
              value="follow lead"
              onSelect={() => onSelect(undefined)}
            >
              <div className="flex min-w-0 flex-1 flex-col">
                <ModelSelectorName>Follow lead</ModelSelectorName>
                <span className="text-muted-foreground truncate text-[10px]">
                  Use the same model as the lead agent
                </span>
              </div>
              {selectedName === undefined ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </ModelSelectorItem>
          }
          renderItem={(m) => (
            <ModelSelectorItem
              key={m.name}
              value={m.name}
              disabled={lacksToolSupport(m)}
              onSelect={() => onSelect(m.name)}
            >
              <ModelPickerRow
                model={m}
                showProvider={!localSettings.modelPicker.groupByProvider}
                annotation={
                  lacksToolSupport(m) && (
                    <span className="text-muted-foreground shrink-0 text-[10px]">
                      {t.inputBox.noToolSupport}
                    </span>
                  )
                }
              />
              {m.name === selectedName ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </ModelSelectorItem>
          )}
        />
      </ModelSelectorContent>
    </ModelSelector>
  );
}
