import type { GenerationSource } from "./types";

/**
 * Selection helpers for the generate-an-agent wizard.
 *
 * Kept as pure functions rather than inline `setState` callbacks so the rules
 * that actually matter — a selection is a set, and it is capped by the server's
 * `max_sources` — are unit-testable and cannot drift between the two pickers
 * (conversations and scheduled tasks) that share them.
 */

export function sourceKey(source: GenerationSource): string {
  return `${source.kind}:${source.id}`;
}

export function isSelected(
  selection: GenerationSource[],
  source: GenerationSource,
): boolean {
  const key = sourceKey(source);
  return selection.some((item) => sourceKey(item) === key);
}

/**
 * Add or remove a source. Adding past `maxSources` is a no-op: the server
 * rejects an oversized selection with a 422, so the cap is enforced here where
 * the user can still see what happened, rather than at submit time.
 */
export function toggleSource(
  selection: GenerationSource[],
  source: GenerationSource,
  maxSources: number,
): GenerationSource[] {
  const key = sourceKey(source);
  if (selection.some((item) => sourceKey(item) === key)) {
    return selection.filter((item) => sourceKey(item) !== key);
  }
  if (maxSources > 0 && selection.length >= maxSources) {
    return selection;
  }
  return [...selection, source];
}

/** True when the user has picked something and is still within the cap. */
export function canAnalyze(
  selection: GenerationSource[],
  maxSources: number,
): boolean {
  if (selection.length === 0) {
    return false;
  }
  return maxSources <= 0 || selection.length <= maxSources;
}
