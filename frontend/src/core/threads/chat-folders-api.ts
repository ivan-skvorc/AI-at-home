/**
 * Server-side persistence for the sidebar's chat folders (fork feature).
 *
 * The folder list is per-user state that must follow the user across browsers
 * and devices — a conversation's `deerflow_folder` metadata is already durable
 * on the server, so keeping the folder *names* only in `localStorage` would
 * leave every filed chat pointing at a folder the next browser has never heard
 * of. Same store as the keep-alive tab strip: `ui_state.json`, per user.
 *
 * Every call degrades rather than throws: an unreachable gateway must leave the
 * sidebar rendering, not blank it.
 */

import { fetch, getCsrfHeaders } from "@/core/api/fetcher";

import { normalizeChatFolders, type ChatFolder } from "./chat-folders";

const ENDPOINT = "/api/settings/chat-folders";

function readChatFolders(data: unknown): ChatFolder[] | null {
  if (typeof data !== "object" || data === null) {
    return null;
  }
  const value = (data as { chat_folders?: unknown }).chat_folders;
  if (!Array.isArray(value)) {
    return null;
  }
  // Reuse the model's own defensive parser so the server response and any local
  // cache are validated, deduped and capped by exactly one implementation.
  return normalizeChatFolders(value);
}

/**
 * Fetch the persisted folder list.
 *
 * Returns `null` — "unknown", distinct from "the user has no folders" — when
 * the gateway is unreachable or answers unusably, so a caller can keep showing
 * what it already has instead of collapsing every folder into the root list.
 */
export async function fetchChatFolders(): Promise<ChatFolder[] | null> {
  try {
    const res = await fetch(ENDPOINT, { cache: "no-store" });
    if (!res.ok) {
      return null;
    }
    return readChatFolders(await res.json());
  } catch {
    return null;
  }
}

/**
 * Replace the folder list. Returns the server's normalized value — the
 * authoritative post-write state — or `null` when the write did not land.
 */
export async function saveChatFolders(
  folders: readonly ChatFolder[],
): Promise<ChatFolder[] | null> {
  try {
    const res = await fetch(ENDPOINT, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        ...getCsrfHeaders(),
      },
      body: JSON.stringify({ chat_folders: folders }),
    });
    if (!res.ok) {
      return null;
    }
    return readChatFolders(await res.json());
  } catch {
    return null;
  }
}
