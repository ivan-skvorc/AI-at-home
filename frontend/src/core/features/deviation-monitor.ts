import { selectDeviationMonitorFeature } from "./api";
import { useFeaturesQuery } from "./query";

/**
 * The deviation monitor's operator switch (config.yaml ->
 * deviation_monitor.enabled). Off while loading and on error, so the composer
 * never offers, even briefly, a monitor the server will not run.
 *
 * Its own module rather than `./hooks`, like `./query`: composer tests mock
 * `./hooks` with only the hooks they use, and the monitor's button renders in
 * that same composer.
 */
export function useDeviationMonitorFeature() {
  const { data, isPending } = useFeaturesQuery(selectDeviationMonitorFeature, {
    staleTime: 0,
    refetchOnMount: true,
  });
  return {
    enabled: data?.enabled ?? false,
    isLoading: isPending,
  };
}
