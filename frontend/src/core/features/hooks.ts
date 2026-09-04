import { useQuery } from "@tanstack/react-query";

import {
  type AutoTitleCapability,
  fetchAutoTitleCapability,
  fetchBrowserControlEnabled,
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
    staleTime: 0,
    refetchOnMount: true,
    retry: false,
  });
  return {
    enabled: data?.enabled ?? true,
    modelName: data?.modelName ?? null,
    isLoading: isPending,
  };
}
