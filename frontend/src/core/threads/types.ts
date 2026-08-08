import type { Message, Thread } from "@langchain/langgraph-sdk";

import type { Todo } from "../todos";

export interface GoalState {
  objective: string;
  status: "active";
  created_at: string;
  updated_at: string;
  continuation_count: number;
  max_continuations: number;
  no_progress_count: number;
  max_no_progress_continuations: number;
  last_evaluation?: {
    satisfied: boolean;
    blocker:
      | "none"
      | "missing_evidence"
      | "needs_user_input"
      | "run_failed"
      | "external_wait"
      | "goal_not_met_yet";
    reason: string;
    evidence_summary?: string;
    run_id?: string;
    evaluated_at?: string;
    progress_key?: string;
    stand_down_reason?: string;
  };
}

export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: Message[];
  artifacts?: string[];
  todos?: Todo[];
  goal?: GoalState | null;
}

export interface AgentThreadContext extends Record<string, unknown> {
  thread_id: string;
  model_name: string | undefined;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  subagent_model_name?: string;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
  agent_name?: string;
  // Per-user long-term memory opt-in. When false the backend skips memory
  // injection/extraction/tools for this run; when omitted the backend falls back
  // to the operator config default. Gated on top by config.yaml memory.enabled.
  memory_enabled?: boolean;
}

export interface AgentThread extends Thread<AgentThreadState> {
  context?: AgentThreadContext;
}

export interface RunMessage {
  run_id: string;
  seq: number;
  content: Message;
  metadata: {
    caller: string;
    [key: string]: unknown;
  };
  created_at: string;
}

export interface ThreadTokenUsageModelBreakdown {
  tokens: number;
  runs: number;
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cost?: number | null;
}

export interface ThreadTokenUsageAuxBreakdown {
  tokens: number;
  input_tokens: number;
  output_tokens: number;
  calls: number;
  cost?: number | null;
}

export interface ThreadContextUsage {
  token_count: number;
  max_context_tokens: number | null;
  percentage: number | null;
}

export interface ThreadTokenUsageResponse {
  thread_id: string;
  total_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_runs: number;
  by_model: Record<string, ThreadTokenUsageModelBreakdown>;
  by_caller: {
    lead_agent: number;
    subagent: number;
    middleware: number;
  };
  // Real-cost overview (fork feature). Null when no models[*].pricing is
  // configured or priced models mix currencies. `aux` holds the separate
  // memory / suggestions counters keyed by category.
  total_cost?: number | null;
  // The same whole-thread total billed at any live promotional/introductory
  // rates — what the conversation costs right now, versus `total_cost`'s
  // standard rate. Null when nothing in the thread is currently discounted.
  promo_total_cost?: number | null;
  currency?: string | null;
  // Models that burned tokens here but carry no `pricing:` block, so they
  // contributed nothing to `total_cost`. Lets the UI say *which* model needs a
  // price instead of rendering an unexplained "—".
  unpriced_models?: string[];
  aux?: Record<string, ThreadTokenUsageAuxBreakdown>;
  // Real-time context window usage (upstream #3125/#3183).
  context_usage?: ThreadContextUsage | null;
}
