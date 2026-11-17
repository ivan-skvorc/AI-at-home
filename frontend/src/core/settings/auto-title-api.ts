/**
 * Server-side persistence for Settings → Conversation titles (fork feature,
 * FORK.md §33).
 *
 * The preference used to live only in this browser origin's localStorage, so
 * every run that did not come from that browser (another device, the PWA, the
 * tailnet hostname instead of localhost, an IM channel, an extension's child
 * thread) fell back to `config.yaml` and kept renaming conversations. The
 * Gateway now stores it per user and applies it when it admits a run; this
 * module is the client half of that contract:
 *
 * `GET /api/settings/auto-title` → `{"enabled": bool, "model_name"?: str}`;
 * `PUT` takes and returns the same shape. `model_name` has three states and the
 * wire keeps them apart, exactly like the run context: the key **absent**
 * follows `config.yaml -> title.model_name`, `""` renames without a model call,
 * and a name picks that model. The GET may also carry `"stored": bool`, whether
 * the account has saved a preference at all (see {@link AutoTitleAccountState}).
 *
 * Every call degrades rather than throws, and an unreachable or unusable answer
 * is `null` — "unknown" — never a default. Reading a failed request as
 * `{"enabled": true}` would switch renaming back on for a user who turned it
 * off, and reading it as "off" would do the opposite.
 */

import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { LocalSettings } from "./local";

/** The stored preference, in the client's own shape (`modelName`). */
export type AutoTitlePreference = LocalSettings["autoTitle"];

function endpoint(): string {
  return `${getBackendBaseURL()}/api/settings/auto-title`;
}

/**
 * Validate a Gateway answer. `null` when it is not a preference at all, so a
 * caller keeps what it has instead of adopting a made-up value.
 */
export function parseAutoTitlePreference(
  data: unknown,
): AutoTitlePreference | null {
  if (typeof data !== "object" || data === null) {
    return null;
  }
  const { enabled, model_name: modelName } = data as Record<string, unknown>;
  if (typeof enabled !== "boolean") {
    return null;
  }
  // The Gateway omits the key for "follow the operator"; `null` reads the same.
  if (modelName === undefined || modelName === null) {
    return { enabled, modelName: undefined };
  }
  if (typeof modelName !== "string") {
    return null;
  }
  return { enabled, modelName };
}

/**
 * A GET answer: the preference, and whether the account has ever saved one.
 *
 * The never-set default and an explicit "on, with the operator's model" read
 * alike on the wire (`{"enabled": true}`), and only the first may be replaced
 * by an opt-out this browser held before the account could store one; taking
 * the second for it would undo a choice made on another device. `stored`
 * tells them apart: `false` only for an account that never saved a
 * preference. It is `null` when the Gateway does not send the flag, and the
 * caller then has only the shape to go on.
 */
export type AutoTitleAccountState = {
  preference: AutoTitlePreference;
  stored: boolean | null;
};

/** Validate a GET answer; `null` when it is not a preference at all. */
export function parseAutoTitleAccountState(
  data: unknown,
): AutoTitleAccountState | null {
  const preference = parseAutoTitlePreference(data);
  if (!preference) {
    return null;
  }
  const { stored } = data as Record<string, unknown>;
  return { preference, stored: typeof stored === "boolean" ? stored : null };
}

/** The request body: an omitted `model_name` is how "server default" is stored. */
export function autoTitlePreferenceBody(preference: AutoTitlePreference): {
  enabled: boolean;
  model_name?: string;
} {
  return {
    enabled: preference.enabled,
    ...(preference.modelName === undefined
      ? {}
      : { model_name: preference.modelName }),
  };
}

/**
 * Read the caller's stored preference. `null` when the Gateway is unreachable,
 * answers with an error, or answers something that is not a preference.
 */
export async function fetchAutoTitleAccountState(
  signal?: AbortSignal,
): Promise<AutoTitleAccountState | null> {
  try {
    const res = await fetch(endpoint(), { cache: "no-store", signal });
    if (!res.ok) {
      return null;
    }
    return parseAutoTitleAccountState(await res.json());
  } catch {
    return null;
  }
}

/**
 * Replace the caller's stored preference. Returns the Gateway's normalized
 * value — the authoritative post-write state — or `null` when the write did
 * not land.
 */
export async function saveAutoTitlePreference(
  preference: AutoTitlePreference,
): Promise<AutoTitlePreference | null> {
  try {
    const res = await fetch(endpoint(), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(autoTitlePreferenceBody(preference)),
    });
    if (!res.ok) {
      return null;
    }
    return parseAutoTitlePreference(await res.json());
  } catch {
    return null;
  }
}
