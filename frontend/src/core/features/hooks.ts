import {
  type AutoTitleCapability,
  DEFAULT_SCHEDULED_TASKS_FEATURE,
  DEFAULT_THREAD_ACTIVITY_FEATURE,
  type FeaturesResponse,
  selectAutoTitleCapability,
  selectBrowserControlEnabled,
  selectConversationReferencesCapability,
  selectKnowledgeBaseFeature,
  selectMcpTasksEnabled,
  selectScheduledTasksFeature,
  selectSubagentBatchesCapability,
  selectThreadActivityFeature,
} from "./api";
import { useFeaturesQuery } from "./query";

// Hooks that re-check on every mount, so flipping config.yaml reaches the UI
// on the next visit without a rebuild.
const ON_EVERY_MOUNT = { staleTime: 0, refetchOnMount: true } as const;

const selectRunInputs = (features: FeaturesResponse) =>
  features.run_inputs === true;

export function useRunInputsEnabled(enabled = true) {
  const { data } = useFeaturesQuery(selectRunInputs, {
    enabled,
    staleTime: 60_000,
  });
  return enabled && data === true;
}

export function useBrowserControlEnabled() {
  const { data, isPending } = useFeaturesQuery(
    selectBrowserControlEnabled,
    ON_EVERY_MOUNT,
  );

  return {
    enabled: data ?? false,
    isLoading: isPending,
  };
}

export function useMcpTasksEnabled() {
  const { data, isPending } = useFeaturesQuery(
    selectMcpTasksEnabled,
    ON_EVERY_MOUNT,
  );

  return {
    enabled: data ?? false,
    isLoading: isPending,
  };
}

export function useSubagentBatchesCapability() {
  const { data, isPending } = useFeaturesQuery(
    selectSubagentBatchesCapability,
    ON_EVERY_MOUNT,
  );
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
  const { data, isPending } = useFeaturesQuery(
    selectAutoTitleCapability,
    ON_EVERY_MOUNT,
  );
  return {
    enabled: data?.enabled ?? true,
    modelName: data?.modelName ?? null,
    isLoading: isPending,
  };
}

export function useConversationReferencesCapability() {
  const { data, isPending, isSuccess, error, refetch } = useFeaturesQuery(
    selectConversationReferencesCapability,
    ON_EVERY_MOUNT,
  );
  return {
    enabled: isSuccess && (data?.enabled ?? false),
    maxReferences: data?.maxReferences ?? 0,
    isLoading: isPending,
    isSuccess,
    error,
    refetch,
  };
}

export function useKnowledgeBaseEnabled() {
  const { data, isPending } = useFeaturesQuery(
    selectKnowledgeBaseFeature,
    ON_EVERY_MOUNT,
  );
  return {
    scopeSelectionEnabled: data?.scopeSelectionEnabled ?? false,
    isLoading: isPending,
  };
}

/**
 * Scheduled-task availability. While loading, or when the request fails, the
 * defaults apply (available and running, chat tool off), so the page never
 * flashes an "unavailable" state on a working server.
 */
export function useScheduledTasksFeature() {
  const { data, isPending } = useFeaturesQuery(
    selectScheduledTasksFeature,
    ON_EVERY_MOUNT,
  );
  const feature = data ?? DEFAULT_SCHEDULED_TASKS_FEATURE;
  return {
    available: feature.available,
    running: feature.running,
    toolEnabled: feature.toolEnabled,
    groupNotifications: feature.groupNotifications,
    minIntervalSeconds: feature.minIntervalSeconds,
    isLoading: isPending,
  };
}

/**
 * Thread activity (origin markers' live refresh, read markers, unread). Off
 * while loading, on error and on servers without the block, so nothing polls
 * or posts against a backend that lacks the endpoints.
 */
export function useThreadActivityFeature() {
  const { data, isPending } = useFeaturesQuery(
    selectThreadActivityFeature,
    ON_EVERY_MOUNT,
  );
  const feature = data ?? DEFAULT_THREAD_ACTIVITY_FEATURE;
  return {
    available: feature.available,
    isLoading: isPending,
  };
}
