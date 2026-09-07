/**
 * Client for the on-demand Camoufox + SearXNG refresh (fork feature).
 *
 * The work takes minutes — a Docker image pull and a browser download — so the
 * POST only *starts* it and the outcome is polled. Holding one HTTP request
 * open for the duration would hit nginx's read timeout and show a 504 for a
 * refresh that actually succeeded.
 */

import { fetch, getCsrfHeaders } from "@/core/api/fetcher";

const ENDPOINT = "/api/settings/update-dependencies";

/** Per-component outcome words, as the updater script reports them. */
export type DependencyUpdateOutcome =
  | "ok"
  | "skipped"
  | "skipped-no-docker"
  | "would-update"
  | "failed"
  | "timeout";

export type DependencyUpdateStatus = {
  running: boolean;
  started_at?: number | null;
  finished_at?: number | null;
  /** Empty while a run is in flight, and before the first run. */
  results: Partial<Record<"camoufox" | "searxng", DependencyUpdateOutcome>>;
  error?: string | null;
};

function readStatus(data: unknown): DependencyUpdateStatus | null {
  if (typeof data !== "object" || data === null) {
    return null;
  }
  const value = data as Record<string, unknown>;
  if (typeof value.running !== "boolean") {
    return null;
  }
  return {
    running: value.running,
    started_at: typeof value.started_at === "number" ? value.started_at : null,
    finished_at:
      typeof value.finished_at === "number" ? value.finished_at : null,
    results:
      typeof value.results === "object" && value.results !== null
        ? (value.results as DependencyUpdateStatus["results"])
        : {},
    error: typeof value.error === "string" ? value.error : null,
  };
}

/** Current state, or `null` when the gateway could not be reached. */
export async function fetchDependencyUpdateStatus(): Promise<DependencyUpdateStatus | null> {
  try {
    const response = await fetch(ENDPOINT, { cache: "no-store" });
    if (!response.ok) {
      return null;
    }
    return readStatus(await response.json());
  } catch {
    return null;
  }
}

export class DependencyUpdateForbiddenError extends Error {}

/**
 * Start a refresh.
 *
 * Throws {@link DependencyUpdateForbiddenError} for a non-admin caller so the
 * page can say *why* rather than showing a generic failure — this runs commands
 * on the host and is admin-gated on purpose.
 */
export async function startDependencyUpdate(): Promise<DependencyUpdateStatus | null> {
  const response = await fetch(ENDPOINT, {
    method: "POST",
    headers: { ...getCsrfHeaders() },
  });
  if (response.status === 403) {
    throw new DependencyUpdateForbiddenError("Admin access required.");
  }
  if (!response.ok) {
    throw new Error("Could not start the update.");
  }
  return readStatus(await response.json());
}
