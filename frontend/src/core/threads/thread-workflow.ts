/**
 * What a conversation was last run with, recorded on the conversation itself.
 *
 * The per-thread model / subagent model / mode / reasoning effort already live
 * in `localStorage` (see `core/settings/local.ts`), which is what keeps two open
 * chats independent. But `localStorage` cannot answer the question the user
 * actually asks — *"what was this chat using?"* — because it only knows about
 * conversations **this browser** has touched, under **this origin**, since the
 * last time site data was cleared. Everywhere else the selection silently fell
 * back to the app default, so opening an old conversation showed whichever model
 * happened to be selected last rather than the one it had been talking to.
 *
 * So the selection is also written onto the thread's own metadata. That makes it
 * a property of the conversation rather than of the browser: it survives a
 * restart, follows the user to their phone, and is what a freshly-opened chat
 * reads before it decides which model to show.
 *
 * The local store stays the fast path — it is read synchronously during render,
 * while metadata arrives with a fetch — so this is a *seed*, not a replacement:
 * a thread with a local selection keeps it.
 */

import type { LocalSettings } from "@/core/settings/local";

/** Thread-metadata key holding the conversation's own workflow selection. */
export const THREAD_WORKFLOW_METADATA_KEY = "deerflow_workflow";

/**
 * The fields recorded. Deliberately the workflow ones only: what model answered,
 * which mode it answered in, how hard it was told to think, and — in Ultra mode
 * — which model its subagents used. Not the internet switch or the Democracy
 * roster, which are about how the *next* turn should run rather than what this
 * conversation is.
 */
export type ThreadWorkflow = {
  model_name?: string;
  subagent_model_name?: string;
  mode?: string;
  reasoning_effort?: string;
};

const WORKFLOW_FIELDS = [
  "model_name",
  "subagent_model_name",
  "mode",
  "reasoning_effort",
] as const;

type ThreadMetadata = Record<string, unknown> | null | undefined;

/**
 * Read the workflow off thread metadata.
 *
 * Metadata is a free-form bag that other writers share, and older threads have
 * no entry at all, so anything unrecognized degrades to `null` ("this
 * conversation has not recorded one") rather than to a partly-filled object
 * that would half-override the user's current selection.
 */
export function readThreadWorkflow(
  metadata: ThreadMetadata,
): ThreadWorkflow | null {
  const raw = metadata?.[THREAD_WORKFLOW_METADATA_KEY];
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return null;
  }
  const source = raw as Record<string, unknown>;
  const workflow: ThreadWorkflow = {};
  for (const field of WORKFLOW_FIELDS) {
    const value = source[field];
    if (typeof value === "string" && value.length > 0) {
      workflow[field] = value;
    }
  }
  return Object.keys(workflow).length > 0 ? workflow : null;
}

/** Narrow a live context down to the fields worth recording. */
export function workflowOfContext(
  context: Partial<LocalSettings["context"]>,
): ThreadWorkflow {
  const workflow: ThreadWorkflow = {};
  for (const field of WORKFLOW_FIELDS) {
    const value = context[field];
    if (typeof value === "string" && value.length > 0) {
      workflow[field] = value;
    }
  }
  return workflow;
}

/**
 * Whether `next` says something `stored` does not.
 *
 * The composer re-reports its context on every render pass that touches it, so
 * without this the chat would PATCH its own metadata continuously. Equality is
 * checked field by field rather than by serializing, because key order is not
 * meaningful and a reordered-but-identical object is not a change.
 */
export function workflowChanged(
  stored: ThreadWorkflow | null,
  next: ThreadWorkflow,
): boolean {
  if (Object.keys(next).length === 0) {
    return false;
  }
  if (stored === null) {
    return true;
  }
  return WORKFLOW_FIELDS.some((field) => stored[field] !== next[field]);
}

/**
 * The metadata patch that records `workflow`.
 *
 * A whole-object replace, not a merge: a conversation that leaves Ultra mode
 * must *lose* its subagent model, and a merge would leave the stale one behind
 * to be read back as this conversation's choice.
 */
export function buildThreadWorkflowPatch(
  workflow: ThreadWorkflow,
): Record<string, unknown> {
  return { [THREAD_WORKFLOW_METADATA_KEY]: workflow };
}
