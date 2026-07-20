"use client";

import { useSyncExternalStore } from "react";

import { useLocalSettings } from "@/core/settings";

import {
  PREFERS_REDUCED_MOTION_QUERY,
  resolveReducedMotion,
} from "./reduced-motion";

function hasMatchMedia(): boolean {
  return (
    typeof window !== "undefined" && typeof window.matchMedia === "function"
  );
}

function subscribeToSystemPreference(callback: () => void): () => void {
  if (!hasMatchMedia()) {
    return () => undefined;
  }
  const query = window.matchMedia(PREFERS_REDUCED_MOTION_QUERY);
  query.addEventListener("change", callback);
  return () => query.removeEventListener("change", callback);
}

function getSystemPreferenceSnapshot(): boolean {
  if (!hasMatchMedia()) {
    return false;
  }
  return window.matchMedia(PREFERS_REDUCED_MOTION_QUERY).matches;
}

function getServerSnapshot(): boolean {
  return false;
}

/**
 * Tracks the OS-level `prefers-reduced-motion: reduce` accessibility setting.
 */
export function useSystemPrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeToSystemPreference,
    getSystemPreferenceSnapshot,
    getServerSnapshot,
  );
}

/**
 * Returns whether decorative animations should be reduced, combining the user's
 * "Reduce animations" appearance setting with the OS accessibility preference.
 */
export function useReducedMotion(): boolean {
  const [settings] = useLocalSettings();
  const systemPrefersReducedMotion = useSystemPrefersReducedMotion();
  return resolveReducedMotion(
    settings.appearance.reduceAnimations,
    systemPrefersReducedMotion,
  );
}
