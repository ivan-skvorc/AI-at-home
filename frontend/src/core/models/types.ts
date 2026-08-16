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

export interface Model {
  id: string;
  name: string;
  model: string;
  display_name: string;
  description?: string | null;
  supports_thinking?: boolean;
  supports_reasoning_effort?: boolean;
  supports_tools?: boolean;
  /** Null when this model has no configured price. */
  price?: ModelPrice | null;
}

export interface TokenUsageSettings {
  enabled: boolean;
}

export interface ModelsResponse {
  models: Model[];
  token_usage: TokenUsageSettings;
}
