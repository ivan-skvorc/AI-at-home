/**
 * API functions for file uploads
 */

import { isRecord } from "@/lib/utils";

import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

export interface UploadedFileInfo {
  filename: string;
  size: number;
  path: string;
  virtual_path: string;
  artifact_url: string;
  extension?: string;
  modified?: number;
  markdown_file?: string;
  markdown_path?: string;
  markdown_virtual_path?: string;
  markdown_artifact_url?: string;
}

export interface UploadResponse {
  success: boolean;
  files: UploadedFileInfo[];
  message: string;
  skipped_files: string[];
}

export interface UploadLimits {
  max_files: number;
  max_file_size: number;
  max_total_size: number;
}

function formatValidationIssue(issue: unknown): string | null {
  if (
    !isRecord(issue) ||
    typeof issue.msg !== "string" ||
    !Array.isArray(issue.loc)
  ) {
    return null;
  }

  if (issue.msg.trim().length === 0) {
    return null;
  }

  const location = issue.loc
    .filter(
      (part): part is string | number =>
        typeof part === "string" || typeof part === "number",
    )
    .map(String)
    .filter((part) => part.length > 0)
    .join(".");

  return location.length > 0 ? `${location}: ${issue.msg}` : issue.msg;
}

function serializeStructuredDetail(
  detail: Record<string, unknown> | unknown[],
): string | null {
  if (
    (Array.isArray(detail) && detail.length === 0) ||
    (!Array.isArray(detail) && Object.keys(detail).length === 0)
  ) {
    return null;
  }

  try {
    return JSON.stringify(detail);
  } catch {
    return null;
  }
}

function formatErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail.trim().length > 0 ? detail : null;
  }

  if (Array.isArray(detail)) {
    if (detail.length === 0) {
      return null;
    }

    const validationIssues = detail.map(formatValidationIssue);
    if (validationIssues.every((issue) => issue !== null)) {
      return validationIssues.join("; ");
    }

    return serializeStructuredDetail(detail);
  }

  if (isRecord(detail)) {
    return formatValidationIssue(detail) ?? serializeStructuredDetail(detail);
  }

  return null;
}

async function readErrorDetail(
  response: Response,
  fallback: string,
): Promise<string> {
  const error = (await response.json().catch(() => null)) as unknown;
  if (!isRecord(error)) {
    return fallback;
  }

  return formatErrorDetail(error.detail) ?? fallback;
}

/**
 * Upload files to a thread
 */
export async function uploadFiles(
  threadId: string,
  files: File[],
  signal?: AbortSignal,
): Promise<UploadResponse> {
  const formData = new FormData();

  files.forEach((file) => {
    formData.append("files", file);
  });

  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads`,
    {
      method: "POST",
      body: formData,
      signal,
    },
  );

  if (!response.ok) {
    throw new Error(await readErrorDetail(response, "Upload failed"));
  }

  const result = (await response.json()) as UploadResponse;
  if (result.success === false) {
    // A gateway or proxy may omit `message`; treat it like an empty one
    // instead of throwing a TypeError while handling the failure.
    const message =
      typeof result.message === "string" ? result.message.trim() : "";
    throw new Error(
      message ? `Upload incomplete: ${message}` : "Upload failed",
    );
  }

  return result;
}

/**
 * Load the upload limits enforced by the gateway for a thread
 */
export async function getUploadLimits(threadId: string): Promise<UploadLimits> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/uploads/limits`,
  );

  if (!response.ok) {
    throw new Error(
      await readErrorDetail(response, "Failed to load upload limits"),
    );
  }

  return response.json();
}
