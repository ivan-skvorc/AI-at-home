import type { Model } from "./types";

export type InputMode = "flash" | "thinking" | "pro" | "ultra" | "democracy";

/**
 * Resolve the requested input mode against the selected model's capabilities.
 *
 * Only "thinking" mode strictly requires `supports_thinking` — it is a pure
 * extended-thinking toggle and meaningless without it. "pro", "ultra", and
 * "democracy" also enable plan mode / subagents, which work on any model; the
 * backend already degrades gracefully by disabling thinking on models that lack
 * it, so those modes must stay selectable.
 */
export function getResolvedMode(
  mode: InputMode | undefined,
  supportsThinking: boolean,
): InputMode {
  if (mode === "thinking" && !supportsThinking) {
    return "flash";
  }
  if (mode) {
    return mode;
  }
  return supportsThinking ? "pro" : "flash";
}

/**
 * Whether a model is explicitly flagged as unable to call tools
 * (`supports_tools: false` in config.yaml, e.g. set by the Ollama sync for
 * models without the "tools" capability). Undefined means unknown and is
 * treated as tool-capable, so hand-added cloud models are never locked out.
 */
export function lacksToolSupport(
  model: Pick<Model, "supports_tools">,
): boolean {
  return model.supports_tools === false;
}

/**
 * Sort models for tool-requiring pickers (Ultra mode): tool-capable models
 * first, alphabetical by display name within each group. Returns a new array.
 */
export function sortModelsByToolSupport(models: Model[]): Model[] {
  return [...models].sort((a, b) => {
    const aBad = lacksToolSupport(a) ? 1 : 0;
    const bBad = lacksToolSupport(b) ? 1 : 0;
    if (aBad !== bBad) return aBad - bBad;
    return (a.display_name ?? a.name).localeCompare(b.display_name ?? b.name);
  });
}
