import { useQuery } from "@tanstack/react-query";

import { type FeaturesResponse, fetchFeatures } from "./api";

export const FEATURES_QUERY_KEY = ["features"] as const;

/**
 * One cached `/api/features` response shared by every feature hook. Each
 * caller keeps its own freshness (`staleTime`, `refetchOnMount`) and picks its
 * block with `select`, so mounting several hooks issues a single request.
 *
 * Kept apart from `./hooks` so tests that mock those hooks still get the real
 * shared query for the hooks in other modules.
 */
export function useFeaturesQuery<T>(
  select: (features: FeaturesResponse) => T,
  options: {
    enabled?: boolean;
    staleTime: number;
    refetchOnMount?: boolean;
  },
) {
  return useQuery({
    queryKey: FEATURES_QUERY_KEY,
    queryFn: fetchFeatures,
    select,
    retry: false,
    ...options,
  });
}
