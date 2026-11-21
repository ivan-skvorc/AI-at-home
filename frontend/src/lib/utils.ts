import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * True for a non-null, non-array object, such as a parsed JSON object. Code
 * that also accepts arrays keeps its own check on purpose.
 */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Shared class for external links (underline by default). */
export const externalLinkClass =
  "text-primary underline underline-offset-2 hover:no-underline";
/** Link style without underline by default (e.g. for streaming/loading). */
export const externalLinkClassNoUnderline = "text-primary hover:underline";
