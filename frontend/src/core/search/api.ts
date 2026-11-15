import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { pathOfThread } from "@/core/threads/utils";

export const OPEN_SEARCH_EVENT = "deerflow:open-search";

export type SearchSegment = { text: string; matched?: boolean };
export type WorkspaceSearchHit = {
  type: "thread" | "message";
  thread_id: string;
  title: string;
  agent_name: string | null;
  archived: boolean;
  updated_at: string;
  project_id: string | null;
  // Fork: the edit version a root thread hit opens (§18).
  open_thread_id?: string;
  message_id?: string;
  seq?: number;
  role?: "user" | "assistant";
  snippet: SearchSegment[];
};
export type WorkspaceSearchPage = {
  items: WorkspaceSearchHit[];
  cursor: string | null;
  indexing: boolean;
  messages_available: boolean;
};
export type SearchFilters = {
  type: "all" | "thread" | "message";
  includeArchived: boolean;
};

export async function searchWorkspace(
  query: string,
  filters: SearchFilters,
  cursor: string | null,
  signal: AbortSignal,
): Promise<WorkspaceSearchPage> {
  const response = await fetch(`${getBackendBaseURL()}/api/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      types: filters.type === "all" ? ["thread", "message"] : [filters.type],
      archived: filters.includeArchived ? null : false,
      limit: 20,
      cursor,
    }),
    signal,
  });
  if (!response.ok) throw new Error(`Search failed (${response.status})`);
  return (await response.json()) as WorkspaceSearchPage;
}

export function pathOfSearchHit(hit: WorkspaceSearchHit): string {
  // Fork: a conversation hit opens the edit version the user last switched to,
  // as its sidebar entry does; a message hit stays on the version that holds
  // the message (§18).
  const threadId =
    hit.type === "thread"
      ? (hit.open_thread_id ?? hit.thread_id)
      : hit.thread_id;
  const path = pathOfThread(threadId, {
    agent_name: hit.agent_name ?? undefined,
  });
  if (hit.type === "thread" || !hit.message_id) return path;
  const params = new URLSearchParams({ message: hit.message_id });
  if (hit.seq !== undefined) params.set("message_seq", String(hit.seq));
  return `${path}?${params}`;
}

export type MessageWindow = {
  messages: {
    message_id: string;
    seq: number;
    role: "user" | "assistant";
    text: string;
    created_at: string;
  }[];
  target_seq: number;
  has_before: boolean;
  has_after: boolean;
};

export async function fetchMessageWindow(
  threadId: string,
  messageId: string,
  seq: number | undefined,
  signal: AbortSignal,
): Promise<MessageWindow> {
  const params = new URLSearchParams({ message_id: messageId });
  if (seq !== undefined) params.set("seq", String(seq));
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/messages/around?${params}`,
    { signal },
  );
  if (!response.ok) throw new Error(`Message unavailable (${response.status})`);
  return (await response.json()) as MessageWindow;
}
