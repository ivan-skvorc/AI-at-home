import { useQuery } from "@tanstack/react-query";

import { fetchSpendReport } from "./api";

/** Windows offered by the spend page, in days. */
export const SPEND_WINDOWS = [7, 30, 90] as const;
export type SpendWindow = (typeof SPEND_WINDOWS)[number];

export function useSpendReport(days: number) {
  return useQuery({
    queryKey: ["spend-report", days],
    queryFn: () => fetchSpendReport(days),
    // Spend history only moves when a run finishes; a slow refresh keeps the
    // page live without polling a cross-thread aggregation every few seconds.
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
}
