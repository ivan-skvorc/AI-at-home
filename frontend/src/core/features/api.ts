import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export interface FeaturesResponse {
  run_inputs?: boolean;
  tool_approval?: {
    enabled: boolean;
    default_mode: "ask" | "auto" | "full";
    allowed_modes: ("ask" | "auto" | "full")[];
  };
  agents_api: { enabled: boolean };
  // Fork: the operator master switch for automatic conversation renaming
  // (config.yaml -> title). Optional so an older Gateway degrades to "on".
  auto_title?: { enabled: boolean; model_name?: string | null };
  browser_control?: { enabled: boolean };
  mcp_tasks?: { enabled: boolean };
  subagent_batches?: {
    enabled?: boolean;
    repository_available?: boolean;
    worker_running?: boolean;
    max_running?: number;
  };
  conversation_references?: {
    enabled?: boolean;
    max_references?: number;
  };
  knowledge_base?: {
    scope_selection_enabled?: boolean;
  };
  scheduled_tasks?: {
    available?: boolean;
    running?: boolean;
    tool_enabled?: boolean;
    group_notifications?: boolean;
    min_interval_seconds?: number;
  };
  thread_activity?: {
    available?: boolean;
  };
}

export interface ScheduledTasksFeature {
  /** The scheduled-task APIs exist on this server. */
  available: boolean;
  /** This Gateway's scheduler is running: tasks run on schedule and new tasks can be created. */
  running: boolean;
  /** Chats can create and manage tasks, and runs can pause their own schedule. */
  toolEnabled: boolean;
  /** Explicit support is required before submitting an additional Feishu group. */
  groupNotifications: boolean;
  /** Shortest interval and earliest one-time delay, in seconds. */
  minIntervalSeconds: number;
}

/**
 * Assumed when the backend sends no `scheduled_tasks` block (an older backend
 * or a test mock): the page keeps working as before, and chat-only copy (stop
 * conditions, "ask in any chat") stays hidden.
 */
export const DEFAULT_SCHEDULED_TASKS_FEATURE: ScheduledTasksFeature = {
  available: true,
  running: true,
  toolEnabled: false,
  groupNotifications: false,
  minIntervalSeconds: 60,
};

export interface ThreadActivityFeature {
  /**
   * The activity feed, read markers and unread state exist (SQL persistence).
   * When false the sidebar does not poll and chats are never marked read.
   */
  available: boolean;
}

/** Assumed while loading, on error, and when an older backend sends no block. */
export const DEFAULT_THREAD_ACTIVITY_FEATURE: ThreadActivityFeature = {
  available: false,
};

export interface ConversationReferencesCapability {
  enabled: boolean;
  maxReferences: number;
}

export interface SubagentBatchesCapability {
  repositoryAvailable: boolean;
  workerRunning: boolean;
  maxRunning: number;
}

/**
 * The feature hooks in `core/features` (and `useToolApprovalFeature`) read
 * this one response through `useFeaturesQuery` (`./query.ts`) and pick their
 * block with a `select*` function below, so they share one `/api/features`
 * request. `useAgentsApiEnabled` (`core/agents/hooks.ts`) still queries on its
 * own key; see docs/quality-exceptions.md.
 */
export async function fetchFeatures(): Promise<FeaturesResponse> {
  const res = await fetch(`${getBackendBaseURL()}/api/features`);
  if (!res.ok) {
    throw new Error(`Failed to load features: ${res.statusText}`);
  }
  return (await res.json()) as FeaturesResponse;
}

export async function fetchAgentsApiEnabled(): Promise<boolean> {
  return (await fetchFeatures()).agents_api.enabled;
}

export interface AutoTitleCapability {
  /** config.yaml -> title.enabled. */
  enabled: boolean;
  /** config.yaml -> title.model_name; null means the local fallback title. */
  modelName: string | null;
}

export function selectAutoTitleCapability(
  features: FeaturesResponse,
): AutoTitleCapability {
  const feature = features.auto_title;
  return {
    // Fail open: a Gateway that predates the field still renames conversations,
    // so reporting "disabled" would grey out a toggle that in fact works.
    enabled: feature?.enabled ?? true,
    modelName: feature?.model_name ?? null,
  };
}

export function selectBrowserControlEnabled(
  features: FeaturesResponse,
): boolean {
  return features.browser_control?.enabled ?? false;
}

export function selectMcpTasksEnabled(features: FeaturesResponse): boolean {
  return features.mcp_tasks?.enabled ?? false;
}

export function selectSubagentBatchesCapability(
  features: FeaturesResponse,
): SubagentBatchesCapability {
  const feature = features.subagent_batches;
  const legacyEnabled = feature?.enabled ?? false;
  return {
    repositoryAvailable: feature?.repository_available ?? legacyEnabled,
    workerRunning: feature?.worker_running ?? legacyEnabled,
    maxRunning: feature?.max_running ?? 0,
  };
}

export function selectConversationReferencesCapability(
  features: FeaturesResponse,
): ConversationReferencesCapability {
  const capability = features.conversation_references;
  const maxReferences = capability?.max_references;
  return {
    enabled: capability?.enabled === true,
    maxReferences:
      typeof maxReferences === "number" &&
      Number.isInteger(maxReferences) &&
      maxReferences > 0
        ? maxReferences
        : 0,
  };
}

export function selectKnowledgeBaseFeature(features: FeaturesResponse): {
  scopeSelectionEnabled: boolean;
} {
  const feature = features.knowledge_base;
  return {
    scopeSelectionEnabled: feature?.scope_selection_enabled ?? false,
  };
}

export function selectScheduledTasksFeature(
  features: FeaturesResponse,
): ScheduledTasksFeature {
  const feature = features.scheduled_tasks;
  const defaults = DEFAULT_SCHEDULED_TASKS_FEATURE;
  const minInterval = feature?.min_interval_seconds;
  return {
    available:
      typeof feature?.available === "boolean"
        ? feature.available
        : defaults.available,
    running:
      typeof feature?.running === "boolean"
        ? feature.running
        : defaults.running,
    toolEnabled:
      typeof feature?.tool_enabled === "boolean"
        ? feature.tool_enabled
        : defaults.toolEnabled,
    groupNotifications: feature?.group_notifications === true,
    minIntervalSeconds:
      typeof minInterval === "number" &&
      Number.isInteger(minInterval) &&
      minInterval > 0
        ? minInterval
        : defaults.minIntervalSeconds,
  };
}

export function selectThreadActivityFeature(
  features: FeaturesResponse,
): ThreadActivityFeature {
  const feature = features.thread_activity;
  return {
    available: feature?.available === true,
  };
}
