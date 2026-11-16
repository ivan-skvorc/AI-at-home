/**
 * Keeps Settings → Conversation titles in step with the account (fork feature,
 * FORK.md §33).
 *
 * The Gateway's per-user value (`auto-title-api.ts`) is authoritative: it is
 * what IM channels, other devices and other origins get, because the Gateway
 * applies it to every run the user owns. The local `autoTitle` setting stays as
 * the copy the switch renders and the run context reads, so this module does
 * two things:
 *
 * - **hydrate**, once per workspace session: adopt the server value, so every
 *   device and origin converges on one setting. An unreachable server keeps the
 *   local value. A static demo has no Gateway and stays local-only.
 * - **write through**: every explicit change is saved to the account, in the
 *   order it was made. A failed save rolls the switch back to the last value
 *   the server confirmed, so the screen never claims a setting the account
 *   does not hold.
 *
 * One upgrade case is handled on purpose. Before the preference was stored
 * server-side it lived only here, so a browser can hold an opt-out the account
 * has never heard of, while the account reads as the never-set default. The
 * first hydration in such a browser uploads the local choice instead of
 * replacing it, or the upgrade itself would switch renaming back on for exactly
 * the people who had turned it off.
 */

import { isStaticWebsiteOnly } from "@/core/static-mode";

import {
  fetchAutoTitlePreference,
  saveAutoTitlePreference,
  type AutoTitlePreference,
} from "./auto-title-api";
import { safeLocalStorage } from "./local";
import { getBaseSettingsSnapshot, updateLocalSettings } from "./store";

/**
 * Set once this browser's preference has been reconciled with an account, from
 * then on the server value wins. Per browser, not per account: the pre-upgrade
 * value it guards belongs to whoever used the browser before, and uploading it
 * into every account that signs in later would hand one person's choice to
 * another.
 */
export const AUTO_TITLE_SYNCED_STORAGE_KEY =
  "deerflow.auto-title.server-synced";

/** How a hydration ended; for tests and diagnostics, never shown. */
export type AutoTitleHydration =
  | "static"
  | "unreachable"
  | "superseded"
  | "adopted"
  | "migrated"
  | "migration-failed";

/**
 * How a write-through ended. `failed` is the only outcome a caller reports:
 * `superseded` means a newer edit decides what the account holds, and `local`
 * means there is no account to save to (the static demo).
 */
export type AutoTitleSave = "saved" | "failed" | "superseded" | "local";

// A new workspace session or account starts a new epoch; an answer that
// belongs to an older one must not write into this one.
let epoch = 0;
// Counts explicit edits, so a read that started before an edit cannot
// overwrite it when it lands.
let userEdits = 0;
// The last value the server acknowledged in this epoch: the rollback target.
let confirmed: AutoTitlePreference | null = null;
// Writes run one at a time, in the order they were made. Two whole-value PUTs
// racing could land out of order and leave the account on the older choice.
let latestWrite = 0;
let writeQueue: Promise<unknown> = Promise.resolve();

function samePreference(a: AutoTitlePreference, b: AutoTitlePreference) {
  return a.enabled === b.enabled && a.modelName === b.modelName;
}

function isNeverSetDefault(preference: AutoTitlePreference) {
  return preference.enabled && preference.modelName === undefined;
}

function hasSyncedBefore(): boolean {
  return safeLocalStorage.getItem(AUTO_TITLE_SYNCED_STORAGE_KEY) !== null;
}

function markSynced() {
  safeLocalStorage.setItem(AUTO_TITLE_SYNCED_STORAGE_KEY, "1");
}

/** Copy a server value into the local setting, model key included. */
function applyToLocal(value: AutoTitlePreference) {
  if (samePreference(getBaseSettingsSnapshot().autoTitle, value)) {
    return;
  }
  // `modelName` is written even when undefined: the server's "follow the
  // operator" must clear a model this browser picked earlier.
  updateLocalSettings("autoTitle", {
    enabled: value.enabled,
    modelName: value.modelName,
  });
}

function enqueueWrite(
  value: AutoTitlePreference,
  session: number,
): Promise<AutoTitleSave> {
  const write = ++latestWrite;
  const result = writeQueue.then(async (): Promise<AutoTitleSave> => {
    const stored = await saveAutoTitlePreference(value);
    const isLatest = session === epoch && write === latestWrite;
    if (stored) {
      markSynced();
      if (session === epoch) {
        confirmed = stored;
      }
      // The normalized value is authoritative, but only the newest write may
      // show it: an older one describes a choice the user has since changed.
      if (isLatest) {
        applyToLocal(stored);
      }
      return "saved";
    }
    if (!isLatest) {
      return "superseded";
    }
    if (confirmed) {
      applyToLocal(confirmed);
    }
    return "failed";
  });
  writeQueue = result.catch(() => undefined);
  return result;
}

/**
 * Change the preference: locally at once (the switch moves, and the next run
 * carries it), then on the account. Resolves to `failed` when the account
 * did not take it; the switch is then back on the last confirmed value.
 */
export function setAutoTitlePreference(
  patch: Partial<AutoTitlePreference>,
): Promise<AutoTitleSave> {
  userEdits += 1;
  updateLocalSettings("autoTitle", patch);
  if (isStaticWebsiteOnly()) {
    return Promise.resolve("local");
  }
  return enqueueWrite({ ...getBaseSettingsSnapshot().autoTitle }, epoch);
}

/**
 * Adopt the account's preference. Called once per workspace session and again
 * for a new account; `signal` aborts a read the workspace no longer wants.
 */
export async function hydrateAutoTitlePreference(
  signal?: AbortSignal,
): Promise<AutoTitleHydration> {
  if (isStaticWebsiteOnly()) {
    return "static";
  }
  const session = ++epoch;
  confirmed = null;
  const editsAtStart = userEdits;
  const server = await fetchAutoTitlePreference(signal);
  if (session !== epoch || signal?.aborted) {
    return "superseded";
  }
  if (server === null) {
    // Unknown, not "on" and not "off": keep what this browser has.
    return "unreachable";
  }
  if (userEdits !== editsAtStart) {
    // The user changed the setting while the read was in flight. The read
    // predates that edit, and the edit's own write carries it to the server.
    return "superseded";
  }
  const local = getBaseSettingsSnapshot().autoTitle;
  if (
    !hasSyncedBefore() &&
    isNeverSetDefault(server) &&
    !isNeverSetDefault(local)
  ) {
    return (await enqueueWrite({ ...local }, session)) === "saved"
      ? "migrated"
      : "migration-failed";
  }
  confirmed = server;
  applyToLocal(server);
  markSynced();
  return "adopted";
}
