"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";

import {
  composerControlsScope,
  type ComposerContext,
  mountComposerControlsShell,
  pluginRunContext,
  resolveComposerSelection,
  scopedComposerContext,
  type UltracodeState,
} from "@/core/extensions/composer-controls";
import type { SurfaceRunContext } from "@/core/extensions/contracts";
import { useFrontendExtensions } from "@/core/extensions/hooks";
import type { HostComposerControls } from "@/core/extensions/surfaces";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import {
  getResolvedMode,
  type InputMode,
  type ReasoningEffortValue,
  reasoningEffortForMode,
  resolveReasoningEffort,
} from "@/core/models/reasoning";
import { useThreadSettings } from "@/core/settings/hooks";
import {
  resolveThreadContext,
  updateThreadSettings,
} from "@/core/settings/store";
import {
  isUltracodeAvailable,
  isWorkflowScriptMode,
} from "@/core/threads/ultracode";

import {
  ComposerModeMenu,
  ComposerModelPicker,
  ComposerReasoningEffortMenu,
  ComposerSubagentModelPicker,
} from "./composer-run-controls";
import { DoubleUltracodeNotice } from "./mode-hover-guide";

type Mounted = {
  id: number;
  scope: string;
  container: HTMLElement;
  onChange?: (context: SurfaceRunContext) => void;
};

function useUltracodeState(): UltracodeState {
  const { data, isSuccess } = useFrontendExtensions();
  const available = isUltracodeAvailable(data);
  return useMemo(
    () => ({ loaded: isSuccess === true, available }),
    [isSuccess, available],
  );
}

/**
 * The host side of `SurfaceContext.composerControls` for one plugin page.
 * Each mount renders the controls through a portal from the page's own React
 * tree, so they keep the workspace's providers (models, settings, language,
 * toasts); dispose, and the page's unmount, unmount them.
 */
export function usePluginComposerControls({
  owner,
  namespace,
  surfaceId,
}: {
  owner: string;
  namespace: string;
  surfaceId: string;
}): { host: HostComposerControls; portals: ReactNode } {
  const [mounted, setMounted] = useState<Mounted[]>([]);
  const { models } = useModels();
  const ultracode = useUltracodeState();
  // runContext() is synchronous plugin code: it reads the latest list, not a render's.
  const sources = useRef({ models, ultracode });
  sources.current = { models, ultracode };
  const nextId = useRef(0);
  const host = useMemo<HostComposerControls>(
    () => ({
      mount(element, { storageKey, onChange }) {
        const scope = composerControlsScope(
          owner,
          namespace,
          surfaceId,
          storageKey ?? "default",
        );
        const shell = mountComposerControlsShell(element);
        nextId.current += 1;
        const entry: Mounted = {
          id: nextId.current,
          scope,
          container: shell.container,
          onChange,
        };
        setMounted((list) => [...list, entry]);
        return {
          runContext: () =>
            pluginRunContext(
              scopedComposerContext(scope),
              sources.current.models,
              sources.current.ultracode,
            ),
          dispose() {
            setMounted((list) => list.filter((item) => item !== entry));
            shell.remove();
          },
        };
      },
    }),
    [owner, namespace, surfaceId],
  );
  const portals = mounted.map((entry) =>
    createPortal(
      <PluginComposerControls scope={entry.scope} onChange={entry.onChange} />,
      entry.container,
      String(entry.id),
    ),
  );
  return { host, portals };
}

/**
 * The chat composer's run controls for one plugin selection: the same mode
 * menu, effort menu and model pickers `InputBox` renders, with the composer's
 * selection rules. Explicit choices go to the page's scope as a chat's go to
 * its thread; automatic repairs go where the chat's go (`resolveThreadContext`).
 */
export function PluginComposerControls({
  scope,
  onChange,
}: {
  scope: string;
  onChange?: (context: SurfaceRunContext) => void;
}) {
  const { t } = useI18n();
  const [settings] = useThreadSettings(scope);
  const context = settings.context;
  const { models } = useModels();
  const ultracode = useUltracodeState();
  const selection = useMemo(
    () => resolveComposerSelection(context, models, ultracode),
    [context, models, ultracode],
  );
  const [modelOpen, setModelOpen] = useState(false);
  const [subagentOpen, setSubagentOpen] = useState(false);

  // InputBox's automatic resolution: a model that is gone, a mode or an effort
  // the model cannot take, repaired the way the chat repairs them.
  useEffect(() => {
    if (models.length === 0) return;
    const fallback =
      models.find((model) => model.name === context.model_name) ?? models[0]!;
    const mode = getResolvedMode(context.mode, fallback);
    const effort = resolveReasoningEffort(fallback, context.reasoning_effort);
    if (
      context.model_name === fallback.name &&
      context.mode === mode &&
      context.reasoning_effort === effort
    ) {
      return;
    }
    resolveThreadContext(scope, {
      ...context,
      model_name: fallback.name,
      mode,
      reasoning_effort: effort,
    });
  }, [context, models, scope]);

  // Both Ultracodes need Script workflows; without it they move to Ultra, visibly.
  const workflowMode = isWorkflowScriptMode(context.mode);
  const fallbackModel = selection.model;
  useEffect(() => {
    if (!workflowMode || !ultracode.loaded || ultracode.available) return;
    toast.message(t.inputBox.ultracodeUnavailable);
    resolveThreadContext(scope, {
      mode: "ultra",
      reasoning_effort: reasoningEffortForMode("ultra", fallbackModel),
    });
  }, [
    workflowMode,
    ultracode,
    scope,
    fallbackModel,
    t.inputBox.ultracodeUnavailable,
  ]);

  const choose = useCallback(
    (patch: Partial<ComposerContext>) =>
      updateThreadSettings(scope, "context", patch),
    [scope],
  );
  const handleModelSelect = useCallback(
    (modelName: string) => {
      const model = models.find((candidate) => candidate.name === modelName);
      if (!model) return;
      const mode = getResolvedMode(context.mode, model);
      const effort = resolveReasoningEffort(model, context.reasoning_effort);
      choose({
        model_name: modelName,
        ...(mode !== context.mode ? { mode } : {}),
        ...(effort !== context.reasoning_effort
          ? { reasoning_effort: effort }
          : {}),
      });
      setModelOpen(false);
    },
    [choose, context.mode, context.reasoning_effort, models],
  );
  const handleModeSelect = useCallback(
    (mode: InputMode) => {
      const next = getResolvedMode(mode, selection.model);
      choose({
        mode: next,
        reasoning_effort: reasoningEffortForMode(next, selection.model),
      });
    },
    [choose, selection.model],
  );
  const handleEffortSelect = useCallback(
    (effort: ReasoningEffortValue) => choose({ reasoning_effort: effort }),
    [choose],
  );
  const handleSubagentSelect = useCallback(
    (modelName: string | undefined) => {
      choose({ ...context, subagent_model_name: modelName });
      setSubagentOpen(false);
    },
    [choose, context],
  );

  // Tell the page when the context it would send changes (not for the first one).
  const runContext = useMemo(
    () => JSON.stringify(pluginRunContext(context, models, ultracode)),
    [context, models, ultracode],
  );
  const reported = useRef(runContext);
  useEffect(() => {
    if (reported.current === runContext) return;
    reported.current = runContext;
    onChange?.(JSON.parse(runContext) as SurfaceRunContext);
  }, [runContext, onChange]);

  return (
    <div
      className="text-foreground flex min-w-0 flex-wrap items-center gap-1"
      data-slot="plugin-composer-controls"
    >
      <DoubleUltracodeNotice mode={selection.mode} />
      <ComposerModeMenu
        mode={selection.mode}
        model={selection.model}
        ultracodeAvailable={ultracode.available}
        onSelect={handleModeSelect}
      />
      <ComposerReasoningEffortMenu
        mode={selection.mode}
        model={selection.model}
        reasoningEffort={selection.reasoning_effort}
        onSelect={handleEffortSelect}
      />
      <ComposerModelPicker
        models={models}
        selectedModel={selection.model}
        selectedName={context.model_name}
        mode={selection.mode}
        open={modelOpen}
        onOpenChange={setModelOpen}
        triggerClassName="max-w-56 min-w-0"
        onSelect={handleModelSelect}
      />
      {(selection.mode === "ultra" || isWorkflowScriptMode(selection.mode)) && (
        <ComposerSubagentModelPicker
          models={models}
          selectedName={context.subagent_model_name}
          open={subagentOpen}
          onOpenChange={setSubagentOpen}
          onSelect={handleSubagentSelect}
        />
      )}
    </div>
  );
}
