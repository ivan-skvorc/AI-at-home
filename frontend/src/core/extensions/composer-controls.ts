import {
  getResolvedMode,
  type InputMode,
  type ReasoningEffortValue,
  reasoningEffortForMode,
  resolveReasoningEffort,
} from "../models/reasoning";
import type { Model } from "../models/types";
import {
  applyThreadContextOverride,
  getLocalSettings,
  type LocalSettings,
} from "../settings/local";
import {
  getBaseSettingsSnapshot,
  getThreadContextSnapshot,
} from "../settings/store";
import { deriveModeContext } from "../threads/run-context";
import { isWorkflowScriptMode } from "../threads/ultracode";

import type { SurfaceComposerMode, SurfaceRunContext } from "./contracts";

/*
 * The host half of `SurfaceContext.composerControls`: the selection a plugin
 * page's controls stand for, and the run context the main chat would send for
 * it. The React controls are in `components/workspace/plugin-composer-controls.tsx`.
 */

export type ComposerContext = LocalSettings["context"];

/** Whether the Script workflows extension, which Plus and Double Plus Ultracode need, is active. */
export type UltracodeState = { loaded: boolean; available: boolean };

export type ComposerSelection = {
  /** The model the controls show; undefined while the list is empty. */
  model: Model | undefined;
  model_name: string | undefined;
  mode: SurfaceComposerMode;
  reasoning_effort: ReasoningEffortValue | undefined;
  subagent_model_name: string | undefined;
};

const STORAGE_KEY = /^[A-Za-z0-9._-]{1,64}$/;

/**
 * The per-thread settings scope a page's selection is stored under. It sits
 * beside the conversations' own overrides (`deerflow.thread-context.<scope>`),
 * so it is browser-local, never an account preference, and never collides with
 * a thread id. The account id keeps two accounts on one browser apart.
 */
export function composerControlsScope(
  owner: string,
  namespace: string,
  surfaceId: string,
  storageKey: unknown = "default",
): string {
  if (typeof storageKey !== "string" || !STORAGE_KEY.test(storageKey)) {
    throw new TypeError(
      "storageKey must be 1 to 64 letters, digits, '.', '_' or '-'",
    );
  }
  return `plugin:${owner}:${namespace}/${surfaceId}/${storageKey}`;
}

/** The scope's context as `useThreadSettings(scope)` reads it: account defaults under the page's own choices. */
export function scopedComposerContext(scope: string): ComposerContext {
  return applyThreadContextOverride(
    getBaseSettingsSnapshot(),
    getThreadContextSnapshot(scope),
  ).context;
}

/**
 * Resolve a stored selection the way the composer does before it sends:
 * a model that is gone falls back to the first one, the mode is clamped to the
 * model (only `thinking` falls back to `flash` without thinking), and the
 * effort is mapped onto the model's contract. Two rules are the controls' own:
 * the composer's dropdown never offers Democracy (a panel needs the roster the
 * New-chat dialog picks), so a remembered Democracy reads as Ultra, the run it
 * is without a roster; and both Ultracodes read as Ultra once the extensions
 * have loaded without Script workflows, as the composer moves them.
 */
export function resolveComposerSelection(
  context: ComposerContext,
  models: readonly Model[],
  ultracode: UltracodeState,
): ComposerSelection {
  const model =
    models.find((candidate) => candidate.name === context.model_name) ??
    models[0];
  let mode: InputMode = getResolvedMode(context.mode, model);
  let reasoning_effort = resolveReasoningEffort(
    model,
    context.reasoning_effort,
  );
  if (
    mode === "democracy" ||
    (isWorkflowScriptMode(mode) && ultracode.loaded && !ultracode.available)
  ) {
    mode = "ultra";
    reasoning_effort = reasoningEffortForMode("ultra", model);
  }
  return {
    model,
    model_name:
      model?.name ??
      (typeof context.model_name === "string" ? context.model_name : undefined),
    mode,
    reasoning_effort,
    subagent_model_name:
      typeof context.subagent_model_name === "string"
        ? context.subagent_model_name
        : undefined,
  };
}

/**
 * The run context the main chat sends for this selection (`buildRunContext`):
 * the model, the mode string and `deriveModeContext`'s keys, with the Settings
 * → Subagents limits read now, as a send reads them. The subagent model rides
 * only on a run that can delegate. Always a fresh plain object.
 */
export function pluginRunContext(
  context: ComposerContext,
  models: readonly Model[],
  ultracode: UltracodeState,
  ultracodeLimits: unknown = getLocalSettings().ultracode,
): SurfaceRunContext {
  const selection = resolveComposerSelection(context, models, ultracode);
  const derived = deriveModeContext({
    mode: selection.mode,
    reasoning_effort: selection.reasoning_effort,
    model_name: selection.model_name,
    ultracode_limits: ultracodeLimits,
    internet_enabled: context.internet_enabled,
  });
  const run: SurfaceRunContext = {
    mode: selection.mode,
    thinking_enabled: derived.thinking_enabled,
    is_plan_mode: derived.is_plan_mode,
    subagent_enabled: derived.subagent_enabled,
  };
  if (selection.model_name) run.model_name = selection.model_name;
  if (derived.reasoning_effort !== undefined)
    run.reasoning_effort = derived.reasoning_effort;
  if (derived.subagent_enabled && selection.subagent_model_name)
    run.subagent_model_name = selection.subagent_model_name;
  if (derived.max_total_subagents !== undefined)
    run.max_total_subagents = derived.max_total_subagents;
  if (derived.max_concurrent_subagents !== undefined)
    run.max_concurrent_subagents = derived.max_concurrent_subagents;
  if (derived.plugin_options)
    run.plugin_options = JSON.parse(
      JSON.stringify(derived.plugin_options),
    ) as SurfaceRunContext["plugin_options"];
  return run;
}

/**
 * The element the host renders a page's controls into: a child of the
 * plugin's element with a shadow root of its own, holding copies of the
 * document's stylesheets. The page's styles stay out of the controls and the
 * host's out of the page; the menus and dialogs portal to the document body as
 * they do in the chat. Tailwind's `dark:` variant needs `.dark` inside the same
 * tree, so the document's theme class is mirrored onto the container.
 */
export function mountComposerControlsShell(element: HTMLElement): {
  container: HTMLElement;
  remove: () => void;
} {
  const host = document.createElement("span");
  host.dataset.slot = "composer-controls-host";
  host.style.display = "contents";
  const shadow = host.attachShadow({ mode: "open" });
  for (const sheet of document.querySelectorAll(
    'link[rel="stylesheet"], style',
  )) {
    shadow.append(sheet.cloneNode(true));
  }
  const container = document.createElement("div");
  container.dataset.slot = "composer-controls";
  shadow.append(container);
  const theme = () =>
    container.classList.toggle(
      "dark",
      document.documentElement.classList.contains("dark"),
    );
  theme();
  const observer = new MutationObserver(theme);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  });
  element.append(host);
  let removed = false;
  return {
    container,
    remove() {
      if (removed) return;
      removed = true;
      observer.disconnect();
      host.remove();
    },
  };
}
