import { normalizeTokenUsage } from "../messages/usage";

import type { Subtask } from "./types";

type TaskStartedEvent = {
  type: "task_started";
  task_id: string;
  model_name?: unknown;
  routing?: unknown;
};

type TaskRunningEvent = {
  type: "task_running";
  task_id: string;
  model_name?: unknown;
  usage?: unknown;
};

/** Convert an additive task lifecycle event into a task-state update. */
export function taskEventToSubtaskUpdate(
  event: unknown,
): (Partial<Subtask> & { id: string }) | null {
  if (!isRecord(event)) {
    return null;
  }

  const taskId = event.task_id;
  if (typeof taskId !== "string" || !taskId.trim()) {
    return null;
  }

  if (event.type === "task_started") {
    const started = event as TaskStartedEvent;
    const modelName =
      typeof started.model_name === "string" && started.model_name.trim()
        ? started.model_name.trim()
        : undefined;
    const routing = normalizeRouting(started.routing);
    return {
      id: taskId,
      ...(modelName ? { modelName } : {}),
      ...(routing ? { routing } : {}),
    };
  }

  if (event.type === "task_running") {
    const running = event as TaskRunningEvent;
    const usage = normalizeTokenUsage(running.usage);
    const modelName = normalizeModelName(running.model_name);
    return usage || modelName
      ? {
          id: taskId,
          ...(modelName ? { modelName } : {}),
          ...(usage ? { usage } : {}),
        }
      : null;
  }

  return null;
}

/**
 * Read the routing decision the backend attached to `task_started`.
 *
 * Defensive because this is additive metadata on a stream event: an older
 * backend omits it entirely, and a malformed value must leave the card
 * showing the model name rather than break the whole update.
 */
function normalizeRouting(
  value: unknown,
): { rule?: string; reason: string } | undefined {
  if (!isRecord(value)) {
    return undefined;
  }
  const reason = typeof value.reason === "string" ? value.reason.trim() : "";
  if (!reason) {
    return undefined;
  }
  const rule = typeof value.rule === "string" ? value.rule.trim() : "";
  return { reason, ...(rule ? { rule } : {}) };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function normalizeModelName(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}
