/**
 * Spend history and attribution (fork feature).
 *
 * Mirrors `ConsoleSpendResponse` in `backend/app/gateway/routers/console.py`.
 * Every cost is priced by the backend through the one shared pricing module, so
 * nothing here recomputes money — the page only formats and orders it.
 */

export interface SpendModelRow {
  model: string;
  /** null when this model has no configured price (local Ollama, hand-added). */
  cost: number | null;
  tokens: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  runs: number;
  aux_calls: number;
}

export interface SpendThreadRow {
  thread_id: string;
  title: string | null;
  cost: number | null;
  tokens: number;
  runs: number;
}

export interface SpendCategoryRow {
  /** "conversation" | "memory" | "suggestions". */
  category: string;
  cost: number | null;
  tokens: number;
}

export interface SpendReport {
  start: string;
  end: string;
  days: number;
  currency: string | null;
  /** null when no models[*].pricing is configured at all. */
  total_cost: number | null;
  total_tokens: number;
  total_runs: number;
  by_model: SpendModelRow[];
  by_thread: SpendThreadRow[];
  by_category: SpendCategoryRow[];
  /** Models that spent tokens with no price — named, never silently dropped. */
  unpriced_models: string[];
}
