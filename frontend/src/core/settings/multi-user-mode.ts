/**
 * Client for the server-side "multi-user mode" setting (fork feature).
 *
 * Multi-user mode is a server-wide setting, not a per-browser preference: when a
 * user turns it OFF the backend shows every conversation to every login/device
 * (one shared workspace), which is why it lives on the server and not in
 * localStorage. Default is ON (per-user isolation). The PUT is admin-gated
 * server-side; in passwordless mode the built-in `default` user is admin.
 */

import { fetch, getCsrfHeaders } from "@/core/api/fetcher";

const ENDPOINT = "/api/settings/multi-user-mode";

/**
 * Normalize the server payload to a boolean, defaulting to ON (isolated) for any
 * unexpected shape — the safe direction, never silently exposing all chats.
 */
function readMultiUserMode(data: unknown): boolean {
  if (typeof data === "object" && data !== null) {
    const value = (data as { multi_user_mode?: unknown }).multi_user_mode;
    if (typeof value === "boolean") {
      return value;
    }
  }
  return true;
}

/** Fetch whether multi-user mode (per-user thread isolation) is enabled. */
export async function getMultiUserMode(): Promise<boolean> {
  const res = await fetch(ENDPOINT, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Failed to load multi-user mode setting (${res.status})`);
  }
  return readMultiUserMode(await res.json());
}

/** Toggle multi-user mode. Returns the persisted value. Admin only. */
export async function setMultiUserMode(enabled: boolean): Promise<boolean> {
  const res = await fetch(ENDPOINT, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      ...getCsrfHeaders(),
    },
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) {
    throw new Error(`Failed to update multi-user mode setting (${res.status})`);
  }
  return readMultiUserMode(await res.json());
}
