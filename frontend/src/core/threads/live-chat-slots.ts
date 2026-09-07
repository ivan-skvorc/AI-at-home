/**
 * Pure model for the live chat slots the workspace keeps mounted.
 *
 * A "slot" is one mounted `<ChatInstance>`: its own stream, artifact panel and
 * subtasks. Exactly one slot is the chat on screen; the rest are **background**
 * slots — chats the user navigated away from *while they were still answering*.
 * Keeping those mounted is what makes concurrent chats work: the run survives
 * server-side either way (`onDisconnect: "continue"`), but a torn-down instance
 * stops receiving the stream, so the answer only reappears on a later visit.
 *
 * There is no user-managed strip here and nothing is persisted: a background
 * slot is created by leaving a busy chat and released the moment its run
 * finishes. This module owns only the ordered set and its transitions —
 * nothing React, nothing route-aware — so it is exhaustively unit-testable.
 */

/**
 * One mounted chat.
 *
 * `key` is a stable identity assigned when the slot is created and never
 * changed afterwards — it backs the React key of the mounted instance, so it
 * must survive a "new chat becomes real" promotion where only `threadId`
 * changes.
 */
export type ChatSlot = {
  key: string;
  threadId: string;
  isNew: boolean;
};

/**
 * Cap on simultaneously-mounted background chats. Each one holds a live chat
 * instance, so the ceiling is a resource guard: past it, leaving another busy
 * chat lets its instance go and the run finishes server-side unobserved,
 * rather than growing the mounted set without limit.
 */
export const MAX_BACKGROUND_CHAT_SLOTS = 8;

/** Whether a thread is currently held as a background slot. */
export function isThreadBackgrounded(
  slots: ChatSlot[],
  threadId: string,
): boolean {
  return slots.some((slot) => slot.threadId === threadId);
}

export function findSlotByThreadId(
  slots: ChatSlot[],
  threadId: string,
): ChatSlot | undefined {
  return slots.find((slot) => slot.threadId === threadId);
}

export function findSlotByKey(
  slots: ChatSlot[],
  key: string,
): ChatSlot | undefined {
  return slots.find((slot) => slot.key === key);
}

/**
 * Retain a slot in the background. Idempotent by thread id and capped at
 * {@link MAX_BACKGROUND_CHAT_SLOTS}; a full set rejects the addition and
 * returns the same array reference so callers can detect "nothing changed".
 */
export function retainSlot(
  slots: ChatSlot[],
  slot: ChatSlot,
  max: number = MAX_BACKGROUND_CHAT_SLOTS,
): ChatSlot[] {
  if (isThreadBackgrounded(slots, slot.threadId)) {
    return slots;
  }
  if (slots.length >= max) {
    return slots;
  }
  return [...slots, slot];
}

/** Release a background slot by its stable key. */
export function releaseSlot(slots: ChatSlot[], key: string): ChatSlot[] {
  const next = slots.filter((slot) => slot.key !== key);
  return next.length === slots.length ? slots : next;
}

/** Release a background slot by its (possibly promoted) thread id. */
export function releaseSlotByThreadId(
  slots: ChatSlot[],
  threadId: string,
): ChatSlot[] {
  const next = slots.filter((slot) => slot.threadId !== threadId);
  return next.length === slots.length ? slots : next;
}

/**
 * Promote a slot's thread id in place (a brand-new chat gains its real backend
 * id on its first send). The stable `key` is unchanged, so the mounted
 * instance is never remounted. If the promoted id is already held by another
 * slot, the duplicate is dropped to keep thread ids unique.
 */
export function updateSlotThreadId(
  slots: ChatSlot[],
  key: string,
  threadId: string,
): ChatSlot[] {
  if (!slots.some((slot) => slot.key === key)) {
    return slots;
  }
  return slots
    .filter((slot) => slot.threadId !== threadId || slot.key === key)
    .map((slot) => (slot.key === key ? { ...slot, threadId } : slot));
}
