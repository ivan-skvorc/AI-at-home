/** Source kinds the analysis can read. Mirrors the backend `SourceKind`. */
export type GenerationSourceKind = "thread" | "scheduled_task";

export interface GenerationSource {
  kind: GenerationSourceKind;
  id: string;
}

export interface AgentProposal {
  name: string;
  description: string;
  soul: string;
  skills: string[] | null;
}

/**
 * `no_gap` is a successful outcome, not an error: the analysis is allowed to
 * conclude that the user's existing agents already cover the selected work.
 */
export type GenerationVerdict = "propose" | "no_gap";

export interface AnalyzeResult {
  verdict: GenerationVerdict;
  rationale: string;
  covered_by: string | null;
  proposal: AgentProposal | null;
  analyzed_sources: number;
  model_name: string | null;
  /** True when this draft came from overriding a no_gap verdict, or from a revision. */
  forced: boolean;
}

/** The draft being revised, carried back so a refine edits rather than regenerates. */
export interface DraftInput {
  name: string;
  description: string;
  soul: string;
}

export interface AnalyzeRequest {
  sources: GenerationSource[];
  model_name?: string | null;
  /** What the user wants the agent for, or — when revising — what to change. */
  goal?: string | null;
  /** Draft an agent even though an existing one may overlap. */
  force_proposal?: boolean;
  /** Revise this draft instead of analyzing afresh. Implies force_proposal. */
  revise_from?: DraftInput | null;
}

export interface AgentGenerationConfig {
  /** True only when the analysis *and* the create route it feeds are both available. */
  enabled: boolean;
  max_sources: number;
  default_model_name: string | null;
  max_goal_chars: number;
}
