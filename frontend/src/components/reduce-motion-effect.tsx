"use client";

import { useEffect } from "react";

import { useReducedMotion } from "@/core/appearance";

/**
 * Reflects the effective reduced-motion preference onto the document root as a
 * `data-reduce-motion` attribute so global CSS can neutralize decorative
 * animations (aurora shimmer, subagent ambilight, wave, etc.) that live in
 * generated components we do not edit directly.
 *
 * Renders nothing; it only manages the attribute side effect.
 */
export function ReduceMotionEffect() {
  const reduceMotion = useReducedMotion();
  useEffect(() => {
    const root = document.documentElement;
    if (reduceMotion) {
      root.setAttribute("data-reduce-motion", "true");
    } else {
      root.removeAttribute("data-reduce-motion");
    }
  }, [reduceMotion]);
  return null;
}
