/**
 * The pure model behind live chat slots: which chats stay mounted, and why.
 *
 * A background slot exists for exactly one reason — a chat the user left while
 * it was still answering — so the interesting properties are the ones that keep
 * that set honest: one slot per thread, a hard ceiling on how many instances can
 * be alive at once, and a stable key that survives the new→real thread-id
 * promotion (a key that changed there would remount the instance and drop the
 * stream it exists to keep).
 */
import { describe, expect, test } from "@rstest/core";

import {
  MAX_BACKGROUND_CHAT_SLOTS,
  findSlotByKey,
  findSlotByThreadId,
  isThreadBackgrounded,
  releaseSlot,
  releaseSlotByThreadId,
  retainSlot,
  updateSlotThreadId,
  type ChatSlot,
} from "@/core/threads/live-chat-slots";

function slot(key: string, threadId: string, isNew = false): ChatSlot {
  return { key, threadId, isNew };
}

describe("retainSlot", () => {
  test("adds a slot to the end", () => {
    const slots = retainSlot(
      retainSlot([], slot("k1", "t1")),
      slot("k2", "t2"),
    );
    expect(slots.map((entry) => entry.threadId)).toEqual(["t1", "t2"]);
  });

  test("is idempotent by thread id", () => {
    const first = retainSlot([], slot("k1", "t1"));
    // Leaving the same busy chat twice must not mount it twice: two instances
    // on one thread would race the same stream into two transcripts.
    const second = retainSlot(first, slot("k2", "t1"));
    expect(second).toBe(first);
  });

  test("declines past the ceiling, returning the same reference", () => {
    let slots: ChatSlot[] = [];
    for (let i = 0; i < MAX_BACKGROUND_CHAT_SLOTS; i++) {
      slots = retainSlot(slots, slot(`k${i}`, `t${i}`));
    }
    const full = slots;
    const rejected = retainSlot(full, slot("extra", "t-extra"));
    // Same reference is the caller's "nothing changed" signal — the run still
    // finishes server-side, it just finishes unobserved.
    expect(rejected).toBe(full);
    expect(rejected).toHaveLength(MAX_BACKGROUND_CHAT_SLOTS);
  });
});

describe("releaseSlot", () => {
  test("removes by key and leaves the rest in order", () => {
    const slots = [slot("k1", "t1"), slot("k2", "t2"), slot("k3", "t3")];
    expect(releaseSlot(slots, "k2").map((entry) => entry.key)).toEqual([
      "k1",
      "k3",
    ]);
  });

  test("returns the same reference when nothing matched", () => {
    const slots = [slot("k1", "t1")];
    expect(releaseSlot(slots, "nope")).toBe(slots);
  });

  test("removes by thread id, for a deleted conversation", () => {
    const slots = [slot("k1", "t1"), slot("k2", "t2")];
    expect(releaseSlotByThreadId(slots, "t1").map((e) => e.key)).toEqual([
      "k2",
    ]);
    expect(releaseSlotByThreadId(slots, "gone")).toBe(slots);
  });
});

describe("updateSlotThreadId", () => {
  test("promotes the thread id and keeps the key", () => {
    const slots = updateSlotThreadId([slot("k1", "client-uuid")], "k1", "real");
    // The key is the React key of the mounted instance: changing it here would
    // remount the chat mid-answer.
    expect(slots).toEqual([slot("k1", "real")]);
  });

  test("ignores an unknown key", () => {
    const slots = [slot("k1", "t1")];
    expect(updateSlotThreadId(slots, "k2", "real")).toBe(slots);
  });

  test("drops a duplicate that the promotion would create", () => {
    const slots = updateSlotThreadId(
      [slot("k1", "t1"), slot("k2", "pending")],
      "k2",
      "t1",
    );
    expect(slots).toEqual([slot("k2", "t1")]);
  });
});

describe("lookups", () => {
  test("find by thread id and by key", () => {
    const slots = [slot("k1", "t1"), slot("k2", "t2")];
    expect(findSlotByThreadId(slots, "t2")?.key).toBe("k2");
    expect(findSlotByKey(slots, "k1")?.threadId).toBe("t1");
    expect(findSlotByThreadId(slots, "t9")).toBeUndefined();
    expect(isThreadBackgrounded(slots, "t1")).toBe(true);
    expect(isThreadBackgrounded(slots, "t9")).toBe(false);
  });
});
