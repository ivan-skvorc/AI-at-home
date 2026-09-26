import type { Model } from "./types";

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
