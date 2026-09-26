/**
 * A model's effective price from `GET /api/models` (fork feature).
 *
 * Server-resolved, so the UI never re-implements the `price:` / legacy
 * `pricing:` / display-name precedence. The discount fields are already
 * **expiry-filtered**: a lapsed discount is absent rather than stale, so a
 * client cannot advertise a promotion that has ended by forgetting to compare
 * dates. `discount_until` is for display only.
 */
export interface ModelPrice {
  currency: string;
  input: number;
  output: number;
  cache_hit?: number | null;
  discount_input?: number | null;
  discount_output?: number | null;
  discount_cache_hit?: number | null;
  discount_until?: string | null;
}

export type ModelThinkingMode = "unsupported" | "optional" | "required";

export interface ModelReasoningEffortCapabilities {
  /** Accepted effort values in the provider's own vocabulary, in display order. */
  values: string[];
  /** Effort the Gateway applies when the caller does not choose one. */
  default: string | null;
  /** DeerFlow generic value (minimal/low/medium/high) -> provider value. */
  aliases: Record<string, string>;
}

/**
 * Normalized reasoning capability contract projected by `/api/models`
 * (issue #5073). Legacy profiles report `source: "legacy"` with the generic
 * effort vocabulary, which is what the UI used to assume from the booleans.
 */
export interface ModelReasoningCapabilities {
  thinking: ModelThinkingMode;
  effort: ModelReasoningEffortCapabilities | null;
  history: "preserve" | "clear" | null;
  source: "legacy" | "contract";
}

export interface Model {
  id: string;
  name: string;
  model: string;
  display_name: string;
  description?: string | null;
  /** @deprecated derived from `reasoning`; kept for older Gateways. */
  supports_thinking?: boolean;
  /** @deprecated derived from `reasoning`; kept for older Gateways. */
  supports_reasoning_effort?: boolean;
  supports_tools?: boolean;
  /** Null when this model has no configured price. */
  price?: ModelPrice | null;
  /**
   * Total context window in tokens (fork feature), when the deployment
   * configured one. For an Ollama model this is the `num_ctx` the sync sized
   * for the local GPU, which is the window the model actually runs with — not
   * its native maximum. Null when unknown.
   */
  context_window?: number | null;
  /**
   * On-disk size of a local model's weights in bytes (fork feature), written by
   * `scripts/sync-ollama-models.py` from Ollama's `/api/tags`. Null for hosted
   * models, where the number is neither known nor meaningful.
   */
  size_bytes?: number | null;
  reasoning?: ModelReasoningCapabilities | null;
}

export interface TokenUsageSettings {
  enabled: boolean;
}

export interface ModelsResponse {
  models: Model[];
  token_usage: TokenUsageSettings;
}
