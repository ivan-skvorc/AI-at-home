import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  SystemPrompt,
  SystemPromptPreview,
  SystemPromptPreviewOptions,
} from "./types";

/**
 * Raised when the backend rejects a request against the system-prompt routes.
 *
 * `status` lets the UI separate the two failures a user can actually act on —
 * 403 (not an admin) and 422 (the template is invalid) — from everything else,
 * and `detail` carries the backend's own message, which for 422 names the
 * offending placeholder.
 */
export class SystemPromptError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly detail: string | null = null,
  ) {
    super(message);
    this.name = "SystemPromptError";
  }
}

async function readResponse(
  res: Response,
  fallbackMessage: string,
): Promise<SystemPrompt> {
  if (!res.ok) {
    throw await buildError(res, fallbackMessage);
  }
  return (await res.json()) as SystemPrompt;
}

async function buildError(
  res: Response,
  fallbackMessage: string,
): Promise<SystemPromptError> {
  const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
  const detail = typeof body.detail === "string" ? body.detail : null;
  return new SystemPromptError(
    detail ?? `${fallbackMessage}: ${res.statusText}`,
    res.status,
    detail,
  );
}

export async function loadSystemPrompt(): Promise<SystemPrompt> {
  const res = await fetch(`${getBackendBaseURL()}/api/system-prompt`);
  return readResponse(res, "Failed to load the system prompt");
}

export async function saveSystemPrompt(content: string): Promise<SystemPrompt> {
  const res = await fetch(`${getBackendBaseURL()}/api/system-prompt`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return readResponse(res, "Failed to save the system prompt");
}

export async function resetSystemPrompt(): Promise<SystemPrompt> {
  const res = await fetch(`${getBackendBaseURL()}/api/system-prompt`, {
    method: "DELETE",
  });
  return readResponse(res, "Failed to reset the system prompt");
}

export async function loadSystemPromptPreview(
  options: SystemPromptPreviewOptions = {},
): Promise<SystemPromptPreview> {
  const params = new URLSearchParams({
    subagent_enabled: String(options.subagentEnabled ?? true),
  });
  const res = await fetch(
    `${getBackendBaseURL()}/api/system-prompt/preview?${params.toString()}`,
  );
  if (!res.ok) {
    throw await buildError(res, "Failed to render the system prompt");
  }
  return (await res.json()) as SystemPromptPreview;
}
