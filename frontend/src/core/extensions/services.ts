import { getAPIClient } from "@/core/api";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { formatThreadAsJSON } from "@/core/threads/export";
import type { AgentThreadState } from "@/core/threads/types";
import { pathOfThread } from "@/core/threads/utils";

import type {
  ConversationActionContext,
  FrontendContribution,
  FrontendServices,
  ExtensionRequestOptions,
  RunStreamEvent,
  SurfaceModels,
} from "./contracts";

/** Same Gateway and CSRF transport as host calls; never replay an HTTP mutation. */
export async function requestExtensionRoute(
  path: string,
  options: ExtensionRequestOptions = {},
  signal: AbortSignal,
  viewerId: string,
): Promise<Response> {
  signal.throwIfAborted();
  if (!viewerId) throw new Error("Reload this extension to bind its viewer");
  // Decode once for validation only; forward the original encoded resource IDs.
  const decoded = decodeURIComponent(path.split("?")[0]!);
  if (
    !decoded.startsWith("/api/extensions/") ||
    /[\\\\#\u0000-\u0020]/.test(path) ||
    decoded.split("/").some((part) => part === "." || part === "..") ||
    decoded.includes("\\") ||
    decoded.includes("%")
  )
    throw new Error("Expected a contributed extension route");
  const headers = new Headers(options.headers);
  headers.set("X-Deerflow-Plugin-Viewer", viewerId);
  const response = await fetch(`${getBackendBaseURL()}${path}`, {
    ...options,
    headers,
    signal: options.signal ? AbortSignal.any([signal, options.signal]) : signal,
    redirect: "error",
  });
  signal.throwIfAborted();
  return response;
}

export type HostServices = Omit<FrontendServices, "callBackend">;

/** Namespace comes from the installed page snapshot, never from action input. */
export function bindFrontendServices(
  base: HostServices,
  entry: FrontendContribution,
  signal?: AbortSignal,
): FrontendServices {
  return {
    ...base,
    async callBackend(action, payload) {
      if (!entry.backend_actions?.includes(action))
        throw new Error("Backend action not declared by this plugin");
      const response = await fetch(
        `${getBackendBaseURL()}/api/plugins/${encodeURIComponent(entry.namespace)}/actions/${encodeURIComponent(action)}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(entry.viewer_id
              ? { "X-Deerflow-Plugin-Viewer": entry.viewer_id }
              : {}),
          },
          body: JSON.stringify(payload),
          ...(signal ? { signal } : {}),
        },
      );
      if (!response.ok)
        throw new Error(`Plugin action unavailable (${response.status})`);
      return response.json() as Promise<unknown>;
    },
  };
}

export async function conversationText(context: ConversationActionContext) {
  const data = await visibleConversation(context);
  return data.messages.map((message) => message.content).join("\n\n");
}

async function visibleConversation(context: ConversationActionContext) {
  const messages =
    context.messages ??
    (
      await getAPIClient().threads.getState<AgentThreadState>(
        context.thread.thread_id,
      )
    ).values?.messages ??
    [];
  // Reuse the export's visibility and internal-marker rules for both host slots.
  return JSON.parse(formatThreadAsJSON(context.thread, messages)) as {
    messages: { id?: string; type: string; content: string }[];
  };
}

export async function latestVisibleAnswer(context: ConversationActionContext) {
  const { messages } = await visibleConversation(context);
  const answer = [...messages]
    .reverse()
    .find((message) => message.type === "ai" && !!message.id);
  return answer ? { id: answer.id!, text: answer.content } : null;
}

/** Resolve live routing metadata through the authenticated host API, including legacy bookmarks. */
export async function openConversation(
  threadId: string,
  navigate: (path: string) => void,
  signal?: AbortSignal,
) {
  signal?.throwIfAborted();
  const thread = await getAPIClient().threads.get(threadId, { signal });
  signal?.throwIfAborted();
  navigate(pathOfThread(thread));
}

const RUN_REFERENCE = /^[A-Za-z0-9_-]{1,128}$/;
/** One event larger than this is not a run update; stop instead of buffering it. */
const MAX_SSE_EVENT_CHARS = 16 * 1024 * 1024;

/** Read-only join of a run's SSE stream; the Gateway checks thread ownership. */
export async function* joinRunStream(
  threadId: string,
  runId: string,
  signal: AbortSignal,
): AsyncGenerator<RunStreamEvent> {
  signal.throwIfAborted();
  if (!RUN_REFERENCE.test(threadId) || !RUN_REFERENCE.test(runId))
    throw new Error("Expected a thread and run identifier");
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/runs/${runId}/join`,
    {
      method: "GET",
      headers: { Accept: "text/event-stream" },
      cache: "no-store",
      redirect: "error",
      signal,
    },
  );
  signal.throwIfAborted();
  if (!response.ok || !response.body)
    throw new Error(`Run stream unavailable (${response.status})`);
  yield* parseServerSentEvents(response.body, signal);
}

async function* parseServerSentEvents(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
): AsyncGenerator<RunStreamEvent> {
  const reader = body.getReader();
  const stop = () => void reader.cancel().catch(() => undefined);
  signal.addEventListener("abort", stop, { once: true });
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "";
  let data: string[] = [];
  let size = 0;
  const dispatch = (): RunStreamEvent | undefined => {
    const text = data.join("\n");
    const name = event || "message";
    const seen = data.length > 0;
    event = "";
    data = [];
    size = 0;
    if (!seen) return undefined;
    try {
      return { event: name, data: JSON.parse(text) as unknown };
    } catch {
      return { event: name, data: text };
    }
  };
  try {
    while (true) {
      const { done, value } = await reader.read();
      signal.throwIfAborted();
      buffer += done
        ? decoder.decode()
        : decoder.decode(value, { stream: true });
      // A trailing CR may be the first half of a CRLF split across chunks.
      const hold = !done && buffer.endsWith("\r") ? "\r" : "";
      const lines = (hold ? buffer.slice(0, -1) : buffer).split(/\r\n|\r|\n/);
      buffer = (lines.pop() ?? "") + hold;
      for (const line of lines) {
        if (line === "") {
          const next = dispatch();
          if (next) yield next;
          signal.throwIfAborted();
          continue;
        }
        if (line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon === -1 ? line : line.slice(0, colon);
        let value = colon === -1 ? "" : line.slice(colon + 1);
        if (value.startsWith(" ")) value = value.slice(1);
        if (field === "event") event = value;
        else if (field === "data") {
          size += value.length;
          if (size > MAX_SSE_EVENT_CHARS)
            throw new Error("Run stream event too large");
          data.push(value);
        }
      }
      if (buffer.length > MAX_SSE_EVENT_CHARS)
        throw new Error("Run stream event too large");
      if (done) break;
    }
  } finally {
    signal.removeEventListener("abort", stop);
    stop();
  }
}

/** Plain copy of the host's model list for a plugin page; no prices or credentials. */
export function pluginModelSnapshot(
  models: readonly { name: string; display_name?: string | null }[],
  preferredName?: string,
): SurfaceModels {
  const list = models.map(({ name, display_name }) =>
    display_name ? { name, display_name } : { name },
  );
  const defaultName =
    list.find((model) => model.name === preferredName)?.name ?? list[0]?.name;
  return defaultName ? { list, defaultName } : { list };
}
