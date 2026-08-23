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
}

export interface AnalyzeRequest {
  sources: GenerationSource[];
  model_name?: string | null;
}

export interface AgentGenerationConfig {
  /** True only when the analysis *and* the create route it feeds are both available. */
  enabled: boolean;
  max_sources: number;
  default_model_name: string | null;
}
