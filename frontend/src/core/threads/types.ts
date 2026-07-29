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

export interface ThreadTokenUsageResponse {
  thread_id: string;
  total_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_runs: number;
  by_model: Record<string, { tokens: number; runs: number }>;
  by_caller: {
    lead_agent: number;
    subagent: number;
    middleware: number;
  };
}
