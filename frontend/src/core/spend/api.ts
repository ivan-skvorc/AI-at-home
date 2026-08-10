import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { SpendReport } from "./types";

export async function fetchSpendReport(days: number): Promise<SpendReport> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/console/spend?days=${encodeURIComponent(String(days))}`,
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      `Failed to load spend report: ${response.statusText}`,
    );
  }
  return response.json();
}
