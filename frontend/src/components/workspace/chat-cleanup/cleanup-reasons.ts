import type { Translations } from "@/core/i18n";
import type {
  OrganizeFailure,
  OrganizeStepResult,
  OrganizeStop,
} from "@/core/threads/chat-organize";

type CleanupCopy = Translations["chatCleanup"];

/**
 * Why one conversation could not be analyzed. Known cases get the UI's own
 * words; anything else keeps the Gateway's message, which is specific (a
 * checkpoint-mode mismatch, a model that could not be reached).
 */
export function analysisFailureReason(
  failure: OrganizeFailure,
  copy: CleanupCopy,
): string {
  switch (failure.status) {
    case 404:
      return copy.reasons.notFound;
    case 409:
      return failure.code === "empty"
        ? copy.reasons.empty
        : failure.message || copy.reasons.busy;
    case 504:
      return copy.reasons.timeout;
    case 502:
      return failure.code === "unusable_reply" ||
        failure.code === "malformed_response"
        ? copy.reasons.unusable
        : failure.message || copy.reasons.other;
    default:
      return failure.message || copy.reasons.other;
  }
}

/** Why the whole pass stopped: the Gateway's words (the spend cap's own text). */
export function stopReason(stop: OrganizeStop, copy: CleanupCopy): string {
  return stop.message || copy.reasons.other;
}

/** Why one write of the apply step failed. */
export function stepFailureReason(
  step: OrganizeStepResult,
  copy: CleanupCopy,
): string | null {
  if (step.state !== "failed") {
    return null;
  }
  switch (step.reason) {
    case "folder_missing":
      return copy.reasons.folderMissing;
    case "folder_not_created":
      return copy.reasons.folderNotCreated;
    case "folder_limit":
      return copy.reasons.folderLimit;
    case "request_failed":
      if (step.status === 409) return copy.reasons.busy;
      if (step.status === 404) return copy.reasons.notFound;
      if (step.status === 403) return copy.reasons.forbidden;
      return step.message ?? copy.reasons.other;
  }
}
