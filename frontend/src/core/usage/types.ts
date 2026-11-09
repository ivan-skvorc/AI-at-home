/** Token projection of /api/console responses; optional monetary fields are ignored. */
export interface UsageDay {
  date: string;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  /** Cache-hit part of input_tokens; absent from Gateways before roadmap 39. */
  cache_read_tokens?: number;
  runs: number;
}

export interface ModelUsage {
  tokens: number;
  runs: number;
  input_tokens: number;
  output_tokens?: number;
  cache_read_tokens: number;
}

export interface UsageSummary {
  days: UsageDay[];
  by_model: Record<string, ModelUsage>;
  total_tokens: number;
  total_runs: number;
  total_input_tokens?: number;
  total_output_tokens?: number;
  total_cache_read_tokens?: number;
}

export interface UsageRun {
  run_id: string;
  thread_id: string;
  thread_title: string | null;
  assistant_id: string | null;
  status: string;
  model_name: string | null;
  created_at: string | null;
  updated_at: string | null;
  duration_seconds: number | null;
  total_tokens: number;
  total_input_tokens?: number;
  total_output_tokens?: number;
  cache_read_tokens?: number;
  message_count: number;
  error: string | null;
}

export interface UsageRunsResponse {
  runs: UsageRun[];
  has_more: boolean;
}

export type UsagePeriod = 7 | 30;
export type UsageRunFilter = "all" | "error" | "timeout";
