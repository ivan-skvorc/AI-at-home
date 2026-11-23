/**
 * Decisions about renders, runs and saves, kept pure so `node --test` covers them.
 *
 * A render outcome is what page.js's renderSource resolves: `{ok, error?, engine?}`
 * or `{superseded: true}`. `engine` marks a failure of the engine itself (the
 * wasm did not load, the Worker crashed, the time limit ran out), which says
 * nothing about the OpenSCAD file.
 */

const ENGINE_CODES = new Set(["worker", "wasm", "timeout", "disposed"]);

/** True for an engine or infrastructure failure code from scad-client.js. */
export function isEngineFailure(code) {
  return (
    typeof code === "string" &&
    (ENGINE_CODES.has(code) || code.startsWith("load:"))
  );
}

/**
 * Whether to store this outcome as the version's render. Engine failures never
 * are (they would spend the automatic repair and block Finalize for a correct
 * file); a good render replaces a stored failure.
 */
export function shouldReport(version, outcome) {
  if (!outcome || outcome.ok === undefined || outcome.superseded) return false;
  if (outcome.error === "closed" || outcome.engine) return false;
  const stored = version?.render;
  if (!stored) return true;
  return stored.ok === false && outcome.ok === true;
}

/** One automatic repair, only after a prompt run the user did not stop and that did not fail. */
export function shouldRepair(run) {
  return (
    run?.kind === "prompt" &&
    !!run.failedVersion &&
    !run.stopped &&
    !run.state?.error
  );
}

/** Versions the model wrote: its drafts and its repairs. */
export const isDraftSource = (source) =>
  source === "model" || source === "repair";

/** After a save: try again only for edits made since the attempt, never the same failed text. */
export function shouldRetrySave({ now, attempted, running }) {
  return !running && now !== attempted;
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
