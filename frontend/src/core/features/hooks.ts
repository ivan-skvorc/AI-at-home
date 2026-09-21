import { useQuery } from "@tanstack/react-query";

import {
  type AutoTitleCapability,
  fetchAutoTitleCapability,
  fetchBrowserControlEnabled,
  fetchConversationReferencesCapability,
  fetchKnowledgeBaseFeature,
  fetchMcpTasksEnabled,
  fetchSubagentBatchesCapability,
} from "./api";

export function useBrowserControlEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "browser_control"],
    queryFn: () => fetchBrowserControlEnabled(),
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });

  return {
    enabled: data ?? false,
    isLoading: isPending,
  };
}

export function useMcpTasksEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "mcp_tasks"],
    queryFn: () => fetchMcpTasksEnabled(),
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });

  return {
    enabled: data ?? false,
    isLoading: isPending,
  };
}

export function useSubagentBatchesCapability() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "subagent_batches"],
    queryFn: () => fetchSubagentBatchesCapability(),
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return {
    repositoryAvailable: data?.repositoryAvailable ?? false,
    workerRunning: data?.workerRunning ?? false,
    maxRunning: data?.maxRunning ?? 0,
    isLoading: isPending,
  };
}

<<<<<<< HEAD
/**
 * Operator master switch for automatic conversation renaming (fork feature).
 * Read through the shared `/api/features` endpoint so Settings can explain a
 * greyed-out toggle instead of silently ignoring it.
 */
export function useAutoTitleCapability(): AutoTitleCapability & {
  isLoading: boolean;
} {
  const { data, isPending } = useQuery({
    queryKey: ["features", "auto_title"],
    queryFn: () => fetchAutoTitleCapability(),
=======
export function useConversationReferencesCapability() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "conversation_references"],
    queryFn: () => fetchConversationReferencesCapability(),
>>>>>>> upstream/main
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return {
<<<<<<< HEAD
    enabled: data?.enabled ?? true,
    modelName: data?.modelName ?? null,
=======
    enabled: data?.enabled ?? false,
    maxReferences: data?.maxReferences ?? 0,
    isLoading: isPending,
  };
}

export function useKnowledgeBaseEnabled() {
  const { data, isPending } = useQuery({
    queryKey: ["features", "knowledge_base"],
    queryFn: fetchKnowledgeBaseFeature,
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return {
    scopeSelectionEnabled: data?.scopeSelectionEnabled ?? false,
>>>>>>> upstream/main
    isLoading: isPending,
  };
}
