import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  AgentGenerationConfig,
  AnalyzeRequest,
  AnalyzeResult,
} from "./types";

const DISABLED_STATUSES = new Set([403, 404]);

/**
 * Raised when the backend rejects an analysis. `retryable` marks the failures
 * a different model or a second attempt can fix (the model was unreachable, or
 * answered with something unparseable) as opposed to a configuration problem.
 */
export class AgentGenerationError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly retryable: boolean,
  ) {
    super(message);
    this.name = "AgentGenerationError";
  }
}

export async function fetchAgentGenerationConfig(): Promise<AgentGenerationConfig> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/agent-generation/config`,
    // A 404 here means the route is not mounted at all (an older backend).
    // Treat that like "disabled" rather than surfacing an error in the gallery.
  );
  if (DISABLED_STATUSES.has(res.status)) {
    return {
      enabled: false,
      max_sources: 0,
      default_model_name: null,
      max_goal_chars: 0,
    };
  }
  if (!res.ok) {
    throw new Error(
      `Failed to load agent generation config: ${res.statusText}`,
    );
  }
  return (await res.json()) as AgentGenerationConfig;
}

export async function analyzeSources(
  request: AnalyzeRequest,
): Promise<AnalyzeResult> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/agent-generation/analyze`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new AgentGenerationError(
      body.detail ?? `Analysis failed: ${res.statusText}`,
      res.status,
      res.status === 502,
    );
  }
  return (await res.json()) as AnalyzeResult;
}
