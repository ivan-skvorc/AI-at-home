/**
 * Pure logic for resolving whether decorative animations should be reduced.
 *
 * The effective preference is the logical OR of:
 *  - the user's explicit "Reduce animations" setting (Settings → Appearance), and
 *  - the operating system `prefers-reduced-motion: reduce` accessibility signal.
 *
 * Kept free of React/DOM so it can be unit tested in isolation.
 */
export const PREFERS_REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

export function resolveReducedMotion(
  userPrefersReducedAnimations: boolean,
  systemPrefersReducedMotion: boolean,
): boolean {
  return userPrefersReducedAnimations || systemPrefersReducedMotion;
}
