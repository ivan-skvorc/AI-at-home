/**
 * Hand-off for the message an edit has to replay in the thread it just created.
 *
 * The edited turn is sent by the chat instance that renders the *new* version
 * thread, not by the one the user clicked "edit" in — navigating remounts the
 * chat, so the text has to survive a route change. Session storage keyed by the
 * target thread id is the smallest thing that does: it is scoped to the tab,
 * it is dropped when the browser session ends, and reading it consumes it, so a
 * replay can never fire twice.
 */
const PENDING_EDIT_SEND_VERSION = 1;
const PENDING_EDIT_SEND_PREFIX = "deerflow:pending-edit-send:v1";

export type PendingEditSend = {
  text: string;
};

export type PendingEditSendStorage = Pick<
  Storage,
  "getItem" | "setItem" | "removeItem"
>;

export function getSessionPendingEditSendStorage(): PendingEditSendStorage | null {
  try {
    if (typeof window === "undefined") {
      return null;
    }
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function buildPendingEditSendKey(threadId: string) {
  return `${PENDING_EDIT_SEND_PREFIX}:${encodeURIComponent(threadId)}`;
}

export function writePendingEditSend(
  storage: PendingEditSendStorage | null | undefined,
  threadId: string,
  pending: PendingEditSend,
) {
  try {
    if (!storage || !pending.text) {
      return;
    }
    storage.setItem(
      buildPendingEditSendKey(threadId),
      JSON.stringify({
        version: PENDING_EDIT_SEND_VERSION,
        text: pending.text,
      }),
    );
  } catch {
    // Browser storage can be disabled or full. The version thread is already
    // created at this point, so the worst case is an empty version the user can
    // type into rather than a failed edit.
  }
}

/**
 * Read and remove the pending message for `threadId`.
 *
 * Removal happens before the caller sends, so a re-render, a Strict Mode double
 * effect, or a reload mid-send can never replay the same edit twice.
 */
export function takePendingEditSend(
  storage: PendingEditSendStorage | null | undefined,
  threadId: string,
): PendingEditSend | null {
  try {
    if (!storage) {
      return null;
    }
    const key = buildPendingEditSendKey(threadId);
    const raw = storage.getItem(key);
    if (!raw) {
      return null;
    }
    storage.removeItem(key);
    const parsed = JSON.parse(raw) as { version?: unknown; text?: unknown };
    if (
      parsed.version !== PENDING_EDIT_SEND_VERSION ||
      typeof parsed.text !== "string" ||
      !parsed.text
    ) {
      return null;
    }
    return { text: parsed.text };
  } catch {
    return null;
  }
}
