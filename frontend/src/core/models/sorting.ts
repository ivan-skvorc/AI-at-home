import type { Model } from "./types";

/**
 * Model-picker sort/group helpers (fork feature).
 *
 * Price and provider are NOT structured fields on the model API — they live
 * only inside `display_name` (the fork bakes them there, e.g.
 * `"Claude Opus 4.8 ($5/25) (Anthropic)"`,
 * `"GLM-5.2 ($1.15/3.6 → $0.28/0.87*) (OpenRouter) (p)"`, `"qwen3:32b (Ollama)"`).
 * So sorting by price and grouping by provider are done by parsing that string.
 * The parsers are deliberately defensive: an unrecognized name yields a null
 * price (sorted last) and the `Other` provider bucket rather than throwing.
 */

export type ModelSortKey = "default" | "name" | "price";
export type ModelSortDirection = "asc" | "desc";

/** Provider group derived from the `display_name` suffix. */
export type ModelProvider = "Anthropic" | "OpenRouter" | "Ollama" | "Other";

/** Stable render/heading order for provider groups. */
export const MODEL_PROVIDER_ORDER: readonly ModelProvider[] = [
  "Anthropic",
  "OpenRouter",
  "Ollama",
  "Other",
] as const;

/** Persisted per-browser model-picker preference. */
export interface ModelPickerPrefs {
  sortKey: ModelSortKey;
  sortDir: ModelSortDirection;
  groupByProvider: boolean;
}

export const DEFAULT_MODEL_PICKER_PREFS: ModelPickerPrefs = {
  // "default" keeps the config order, so out of the box nothing changes and the
  // user opts in to name/price sorting.
  sortKey: "default",
  sortDir: "asc",
  groupByProvider: false,
};

export interface ParsedModelPrice {
  /** Current input price per 1M tokens (promo-aware — see below). */
  input: number;
  /** Current output price per 1M tokens (promo-aware). */
  output: number;
  /**
   * True when the name carries a `$list → $promo*` discount pair, i.e. the
   * `input`/`output` above are the discounted "you pay now" figures.
   */
  discounted: boolean;
  /** The fork's bundled names are USD (`$`); kept explicit for callers. */
  currency: string;
}

// A `$<in>/<out>` pair, e.g. `$5/25`, `$1.15/3.6`, `$0.28/0.87`. The leading
// `$` anchor is what keeps bare version numbers in the name (`4.8`, `3.6`,
// `GLM-5.2`) from being misread as a price.
const PRICE_PAIR = /\$\s*(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/g;

type NamedModel = Pick<Model, "display_name" | "name">;

/**
 * Extract the *current* price from a `display_name`.
 *
 * A discounted entry shows two pairs — the list price then the starred promo
 * (`($3/15 → $2/10*)`). The current price is the one you actually pay, i.e. the
 * **last** pair; the list price is the first. A single pair is both. Returns
 * `null` when the name carries no price (local Ollama, hand-added models).
 */
export function parseModelPrice(
  displayName: string | null | undefined,
): ParsedModelPrice | null {
  if (!displayName) {
    return null;
  }
  const matches = [...displayName.matchAll(PRICE_PAIR)];
  if (matches.length === 0) {
    return null;
  }
  const current = matches[matches.length - 1]!;
  const input = Number(current[1]);
  const output = Number(current[2]);
  if (!Number.isFinite(input) || !Number.isFinite(output)) {
    return null;
  }
  return {
    input,
    output,
    discounted: matches.length > 1,
    currency: "USD",
  };
}

/**
 * A piece of a `display_name` split out for colouring.
 *
 * `price` is an undiscounted model's only pair; a discounted name yields
 * `listPrice` (the standard rate you'd pay once the promo ends) and
 * `promoPrice` (what you pay now), so the picker can render them red and green
 * respectively instead of leaving two bare numbers for the eye to disambiguate.
 */
export type ModelNameSegmentKind =
  | "text"
  | "price"
  | "listPrice"
  | "promoPrice";

export interface ModelNameSegment {
  text: string;
  kind: ModelNameSegmentKind;
}

// Same anchored `$` pair as PRICE_PAIR, but non-global so `lastIndex` is not
// shared across calls, and capturing the surrounding punctuation is left to the
// caller by using match indices.
const PRICE_PAIR_ONCE = /\$\s*\d+(?:\.\d+)?\s*\/\s*\d+(?:\.\d+)?/g;

/**
 * Split a `display_name` into text and price runs for colour rendering.
 *
 * Purely presentational and deliberately total: a name with no recognizable
 * price comes back as one `text` segment, so an unparseable or hand-added model
 * still renders its full name verbatim. Only the first two pairs are classified
 * (list then promo, matching the `($list → $promo*)` convention); anything
 * further is left as text rather than guessed at.
 */
export function splitModelNamePriceSegments(
  displayName: string | null | undefined,
): ModelNameSegment[] {
  const name = displayName ?? "";
  if (!name) {
    return [];
  }
  const matches = [...name.matchAll(PRICE_PAIR_ONCE)].slice(0, 2);
  if (matches.length === 0) {
    return [{ text: name, kind: "text" }];
  }
  const discounted = matches.length > 1;
  const segments: ModelNameSegment[] = [];
  let cursor = 0;
  matches.forEach((match, index) => {
    const start = match.index ?? 0;
    if (start > cursor) {
      segments.push({ text: name.slice(cursor, start), kind: "text" });
    }
    segments.push({
      text: match[0],
      kind: !discounted ? "price" : index === 0 ? "listPrice" : "promoPrice",
    });
    cursor = start + match[0].length;
  });
  if (cursor < name.length) {
    segments.push({ text: name.slice(cursor), kind: "text" });
  }
  return segments;
}

/** Derive the provider group from the `display_name` suffix. */
export function parseModelProvider(
  displayName: string | null | undefined,
): ModelProvider {
  const name = displayName ?? "";
  if (/\(openrouter\)/i.test(name)) {
    return "OpenRouter";
  }
  if (/\(anthropic\)/i.test(name)) {
    return "Anthropic";
  }
  if (/\(ollama\)/i.test(name)) {
    return "Ollama";
  }
  return "Other";
}

/**
 * The scalar used when sorting by price: the current (promo-aware) **output**
 * price, the dominant cost driver. `null` for unpriced models, which are always
 * ordered last regardless of direction.
 */
export function modelPriceSortValue(model: NamedModel): number | null {
  const price = parseModelPrice(model.display_name);
  return price ? price.output : null;
}

function compareByName(a: NamedModel, b: NamedModel): number {
  return (a.display_name ?? a.name).localeCompare(b.display_name ?? b.name);
}

export interface ModelSortOptions<T extends NamedModel = NamedModel> {
  /**
   * Models matching this predicate are forced below every non-matching model
   * (within the whole list, or within each provider group when grouping), then
   * ordered among themselves by the same key. Used to keep tool-incapable
   * models at the bottom of the subagent picker (FORK.md §3) regardless of the
   * chosen sort. Relies on a stable sort to preserve incoming order within a
   * partition under the `default` key (guaranteed on Node and modern browsers).
   */
  demoteLast?: (model: T) => boolean;
}

/**
 * Return a new array of `models` ordered by the given preference. `default`
 * keeps the incoming (config) order and ignores direction. When sorting by
 * price, unpriced models sink to the bottom in both directions.
 */
export function sortModels<T extends NamedModel>(
  models: readonly T[],
  prefs: Pick<ModelPickerPrefs, "sortKey" | "sortDir">,
  options: ModelSortOptions<T> = {},
): T[] {
  const list = [...models];
  const demote = options.demoteLast;
  if (prefs.sortKey === "default" && !demote) {
    return list;
  }
  const factor = prefs.sortDir === "asc" ? 1 : -1;
  list.sort((a, b) => {
    if (demote) {
      const da = demote(a) ? 1 : 0;
      const db = demote(b) ? 1 : 0;
      if (da !== db) {
        return da - db;
      }
    }
    if (prefs.sortKey === "default") {
      // Stable sort keeps the incoming order within each partition.
      return 0;
    }
    if (prefs.sortKey === "price") {
      const pa = modelPriceSortValue(a);
      const pb = modelPriceSortValue(b);
      if (pa === null && pb === null) {
        return compareByName(a, b);
      }
      // Unpriced always last, independent of sort direction.
      if (pa === null) {
        return 1;
      }
      if (pb === null) {
        return -1;
      }
      if (pa !== pb) {
        return (pa - pb) * factor;
      }
      return compareByName(a, b);
    }
    return compareByName(a, b) * factor;
  });
  return list;
}

export interface ModelGroup<T extends NamedModel> {
  provider: ModelProvider;
  models: T[];
}

/**
 * Bucket `models` by provider (in `MODEL_PROVIDER_ORDER`) and sort within each
 * bucket by the same preference. Empty buckets are omitted.
 */
export function groupModelsByProvider<T extends NamedModel>(
  models: readonly T[],
  prefs: Pick<ModelPickerPrefs, "sortKey" | "sortDir">,
  options: ModelSortOptions<T> = {},
): ModelGroup<T>[] {
  const buckets = new Map<ModelProvider, T[]>();
  for (const model of models) {
    const provider = parseModelProvider(model.display_name);
    const bucket = buckets.get(provider);
    if (bucket) {
      bucket.push(model);
    } else {
      buckets.set(provider, [model]);
    }
  }
  const groups: ModelGroup<T>[] = [];
  for (const provider of MODEL_PROVIDER_ORDER) {
    const bucket = buckets.get(provider);
    if (bucket && bucket.length > 0) {
      groups.push({ provider, models: sortModels(bucket, prefs, options) });
    }
  }
  return groups;
}
