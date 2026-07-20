import { expect, test } from "@rstest/core";

import { resolveReducedMotion } from "@/core/appearance/reduced-motion";

test("reduces motion when the user opts in, regardless of the system", () => {
  expect(resolveReducedMotion(true, false)).toBe(true);
  expect(resolveReducedMotion(true, true)).toBe(true);
});

test("reduces motion when the system prefers reduced motion, even if the user did not opt in", () => {
  expect(resolveReducedMotion(false, true)).toBe(true);
});

test("keeps animations when neither the user nor the system requests reduced motion", () => {
  expect(resolveReducedMotion(false, false)).toBe(false);
});
