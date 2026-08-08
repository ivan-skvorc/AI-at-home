/**
 * Server-side persistence for the keep-alive chat tab strip (fork feature).
 *
 * `localStorage` is a first-paint cache, not the source of truth: it is scoped
 * to one browser *and* one origin, so a pinned set silently disappeared when the
 * browser cleared site data on exit, evicted storage for an insecure-origin
 * site (a plain-HTTP LAN deployment), or the app was reopened on a different
 * origin than the one that pinned the tabs (`localhost` vs a LAN/Tailscale
 * address both reach the same server). This module talks to the per-user store
 * that actually survives a machine restart.
 *
 * Every call degrades rather than throws: the strip must keep working from its
 * local cache when the gateway is still booting, which is exactly the moment a
 * post-restart page load happens.
 */

import { fetch, getCsrfHeaders } from "@/core/api/fetcher";

import { deserializeChatTabs, type ChatTab } from "./chat-tabs";

const ENDPOINT = "/api/settings/chat-tabs";

function readChatTabs(data: unknown): ChatTab[] | null {
  if (typeof data !== "object" || data === null) {
    return null;
  }
  const value = (data as { chat_tabs?: unknown }).chat_tabs;
  if (!Array.isArray(value)) {
    return null;
  }
  // Reuse the model's own defensive parser so the server and local caches are
  // validated, deduped and capped by exactly one implementation.
  return deserializeChatTabs(JSON.stringify(value));
}

/**
 * Fetch the persisted tab set.
 *
 * Returns `null` — meaning "unknown", distinct from "the user has no tabs" —
 * when the gateway is unreachable or answers unusably, so the caller keeps
 * showing its local cache instead of blanking the strip.
 */
export async function fetchChatTabs(): Promise<ChatTab[] | null> {
  try {
    const res = await fetch(ENDPOINT, { cache: "no-store" });
    if (!res.ok) {
      return null;
    }
    return readChatTabs(await res.json());
  } catch {
    return null;
  }
}

/**
 * Persist the tab set. Returns the server's normalized value, or `null` when
 * the write did not land (the local cache still holds it; the next successful
 * mutation or reload re-syncs).
 */
export async function saveChatTabs(tabs: ChatTab[]): Promise<ChatTab[] | null> {
  try {
    const res = await fetch(ENDPOINT, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        ...getCsrfHeaders(),
      },
      body: JSON.stringify({ chat_tabs: tabs }),
    });
    if (!res.ok) {
      return null;
    }
    return readChatTabs(await res.json());
  } catch {
    return null;
  }
}
