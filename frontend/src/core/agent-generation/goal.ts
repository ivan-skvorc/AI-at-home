/**
 * Rules for the free-text goal / revision-guidance box.
 *
 * The server enforces `max_goal_chars` and answers 422 past it. These mirror
 * that bound in the UI so the user sees the limit while they are still typing,
 * rather than after paying for a round trip — and they are pure so the two
 * places that use them (the analyze button and the refine button) cannot drift.
 */

/** Length as the server measures it: trimmed. */
export function goalLength(goal: string): number {
  return goal.trim().length;
}

/** True when the trimmed goal fits the server's cap. A non-positive cap is unbounded. */
export function isGoalWithinCap(goal: string, maxGoalChars: number): boolean {
  return maxGoalChars <= 0 || goalLength(goal) <= maxGoalChars;
}

/**
 * The goal as the request should carry it: `null` when blank.
 *
 * Blank and absent mean the same thing to the server, and sending `""` would
 * make an empty box look like a stated intent.
 */
export function normalizeGoal(goal: string): string | null {
  return goal.trim() || null;
}

/**
 * Refining needs something to act on: "make it shorter" is only meaningful
 * relative to a draft, and an empty box has no instruction in it.
 */
export function canRefine(guidance: string, maxGoalChars: number): boolean {
  return goalLength(guidance) > 0 && isGoalWithinCap(guidance, maxGoalChars);
}
