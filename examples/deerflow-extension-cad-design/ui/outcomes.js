/** Decisions about runs and versions, kept pure so `node --test` covers them. */

/**
 * Whether a prompt turn ended without a new version folder, so the preview did
 * not change: the model answered in text, asked a question, or its render
 * failed before cadkit made the folder. A stopped or failed run says so
 * already, and a resumed run may have rendered before the page listed.
 */
export function endedWithoutVersion(run, newest) {
  if (run?.kind !== "prompt") return false;
  if (run.stopped || run.state?.error) return false;
  return (newest ?? 0) <= (run.newestBefore ?? 0);
}

/**
 * The version to show after a listing: the newest while the user follows it
 * (the default, and after picking the newest), else the one they picked while
 * it still exists. Null when the design has no version yet.
 */
export function pickVersion(numbers, { selected = null, follow = true } = {}) {
  if (!numbers.length) return null;
  const newest = numbers[numbers.length - 1];
  if (follow || selected === null || !numbers.includes(selected)) return newest;
  return selected;
}

/**
 * The messages to append when `messages` extends what is shown (`shownIds`),
 * else null (rebuild). Appending keeps a live region from re-reading history.
 */
export function appendOnly(shownIds, messages) {
  if (messages.length < shownIds.length) return null;
  for (let i = 0; i < messages.length; i++) {
    const id = messages[i]?.id;
    if (typeof id !== "string" || !id) return null;
    if (i < shownIds.length && shownIds[i] !== id) return null;
  }
  return messages.slice(shownIds.length);
}
