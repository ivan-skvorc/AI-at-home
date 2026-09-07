import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { AgentThread, ThreadTokenUsageResponse } from "./types";

export type ThreadCompactResponse = {
  thread_id: string;
  compacted: boolean;
  reason?: string | null;
  removed_message_count: number;
  preserved_message_count: number;
  summary_updated: boolean;
  checkpoint_id?: string | null;
  total_tokens: number;
};

export type CompactThreadContextOptions = {
  signal?: AbortSignal;
  agentName?: string | null;
  modelName?: string | null;
};

export type ThreadBranchResponse = {
  thread_id: string;
  parent_thread_id: string;
  parent_checkpoint_id: string;
  branched_from_message_id: string;
  workspace_clone_mode: string;
};

export type BranchThreadFromTurnInput = {
  messageId: string;
  messageIds?: string[];
  title?: string;
  /**
   * Gaslight-mode answer edit: rewrite this assistant message's words in the
   * branch. It must be one of `messageIds`, and the two fields travel together —
   * the Gateway refuses a half-specified pair rather than branching without the
   * edit the caller asked for.
   */
  replacementAssistantMessageId?: string;
  replacementAssistantText?: string;
};

export type ThreadMetadataPatch = Record<string, unknown>;

/**
 * The subset of thread fields the Gateway ``PATCH /api/threads/{id}`` handler
 * returns with meaningful values. The endpoint's ``ThreadResponse`` model also
 * serializes default ``values`` and ``interrupts``, but PATCH leaves those empty;
 * callers that need state should read it via a full thread fetch instead.
 */
export type ThreadMetadataPatchResponse = Pick<
  AgentThread,
  "thread_id" | "status" | "created_at" | "updated_at" | "metadata"
>;

async function readThreadAPIError(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) {
      return body.detail;
    }
  } catch {
    // Fall through to the caller-provided message.
  }
  return fallback;
}

export async function fetchThreadTokenUsage(
  threadId: string,
): Promise<ThreadTokenUsageResponse | null> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/token-usage`,
    {
      method: "GET",
    },
  );

  if (!response.ok) {
    if (response.status === 403 || response.status === 404) {
      return null;
    }
    throw new Error("Failed to load thread token usage.");
  }

  return (await response.json()) as ThreadTokenUsageResponse;
}

export async function branchThreadFromTurn(
  threadId: string,
  input: BranchThreadFromTurnInput,
): Promise<ThreadBranchResponse> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/branches`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message_id: input.messageId,
        message_ids: input.messageIds ?? [input.messageId],
        ...(input.title ? { title: input.title } : {}),
        ...(input.replacementAssistantMessageId !== undefined &&
        input.replacementAssistantText !== undefined
          ? {
              replacement_assistant_message_id:
                input.replacementAssistantMessageId,
              replacement_assistant_text: input.replacementAssistantText,
            }
          : {}),
      }),
    },
  );

  if (!response.ok) {
    throw new Error(
      await readThreadAPIError(response, "Failed to branch conversation."),
    );
  }

  return (await response.json()) as ThreadBranchResponse;
}

export type CreateThreadInput = {
  metadata?: Record<string, unknown>;
  assistantId?: string | null;
};

/**
 * Create an empty thread up front.
 *
 * Editing the *first* user message has no assistant turn to branch from, so the
 * version it produces starts from a genuinely empty conversation. Going through
 * the REST endpoint rather than the "new chat" route keeps the flow identical to
 * every other turn: the id exists before the edit navigates, so the version
 * metadata and the replayed message can both be addressed to it.
 */
export async function createThread(
  input: CreateThreadInput = {},
): Promise<{ thread_id: string }> {
  const response = await fetchWithAuth(`${getBackendBaseURL()}/api/threads`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ...(input.metadata ? { metadata: input.metadata } : {}),
      ...(input.assistantId ? { assistant_id: input.assistantId } : {}),
    }),
  });

  if (!response.ok) {
    throw new Error(
      await readThreadAPIError(response, "Failed to create conversation."),
    );
  }

  return (await response.json()) as { thread_id: string };
}

export async function patchThreadMetadata(
  threadId: string,
  metadata: ThreadMetadataPatch,
): Promise<ThreadMetadataPatchResponse> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ metadata }),
    },
  );

  if (!response.ok) {
    throw new Error(
      await readThreadAPIError(response, "Failed to update conversation."),
    );
  }

  return (await response.json()) as ThreadMetadataPatchResponse;
}

export async function compactThreadContext(
  threadId: string,
  options: CompactThreadContextOptions = {},
): Promise<ThreadCompactResponse> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/compact`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        force: true,
        ...(options.agentName ? { agent_name: options.agentName } : {}),
        ...(options.modelName ? { model_name: options.modelName } : {}),
      }),
      signal: options.signal,
    },
  );

  if (!response.ok) {
    throw new Error(
      await readThreadAPIError(response, "Failed to compact context."),
    );
  }

  return (await response.json()) as ThreadCompactResponse;
}

/** Gateway extension not forwarded by the LangGraph SDK's search method. */
export async function searchThreadsByArchive({
  archived,
  metadata,
  status,
  limit,
  offset,
}: {
  archived: boolean;
  metadata?: Record<string, unknown>;
  status?: string;
  limit: number;
  offset: number;
}): Promise<AgentThread[]> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/search`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ archived, metadata, status, limit, offset }),
    },
  );
  if (!response.ok) {
    throw new Error(
      await readThreadAPIError(response, "Failed to load conversations."),
    );
  }
  return (await response.json()) as AgentThread[];
}

export type SuggestThreadTitleResponse = {
  title: string;
  model_name?: string | null;
  exchange_count: number;
};

/**
 * Ask the Gateway to write a title for a conversation from its opening
 * exchanges (fork feature, FORK.md §38).
 *
 * Read-only on purpose: the suggestion comes back and the caller applies it
 * through the ordinary rename (`POST /{id}/state`). That keeps the "409 while
 * a run is in flight" rule in one place instead of two.
 *
 * `modelName` is omitted rather than sent as `null` when the user has not
 * picked one, so the Gateway falls back to `config.yaml -> title.model_name`.
 * A name the operator has not configured is refused with a 400 — unlike the
 * automatic rename, which drops it silently, because this one was chosen by a
 * person pressing a button.
 */
export async function suggestThreadTitle({
  threadId,
  modelName,
  exchanges,
  signal,
}: {
  threadId: string;
  modelName?: string | null;
  exchanges?: number;
  signal?: AbortSignal;
}): Promise<SuggestThreadTitleResponse> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/title/suggest`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...(modelName ? { model_name: modelName } : {}),
        ...(exchanges ? { exchanges } : {}),
      }),
      signal,
    },
  );

  if (!response.ok) {
    throw new Error(
      await readThreadAPIError(response, "Failed to generate a title."),
    );
  }

  return (await response.json()) as SuggestThreadTitleResponse;
}
