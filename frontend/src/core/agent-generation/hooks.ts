import { useMutation, useQuery } from "@tanstack/react-query";

import { analyzeSources, fetchAgentGenerationConfig } from "./api";
import type { AnalyzeRequest } from "./types";

export const AGENT_GENERATION_CONFIG_QUERY_KEY = [
  "agent-generation",
  "config",
] as const;

export function useAgentGenerationConfig() {
  const { data, isPending } = useQuery({
    queryKey: AGENT_GENERATION_CONFIG_QUERY_KEY,
    queryFn: () => fetchAgentGenerationConfig(),
    // Mirrors useAgentsApiEnabled: flipping config.yaml and revisiting the
    // Agents page should surface the entry point without a rebuild.
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return {
    config: data ?? null,
    // Fail closed while unknown: showing an entry point that 404s is worse
    // than showing it a moment late.
    enabled: data?.enabled ?? false,
    isLoading: isPending,
  };
}

export function useAnalyzeSources() {
  return useMutation({
    mutationFn: (request: AnalyzeRequest) => analyzeSources(request),
  });
}
