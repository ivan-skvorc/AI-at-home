/**
 * Preview budgets. Every count is summed from the file's own declarations and
 * checked here before an output array is allocated, so a small file cannot
 * ask for a large allocation (an index list that repeats three vertices, or one
 * mesh instanced from thousands of nodes).
 */
export const LIMITS = Object.freeze({
  triangles: 1_000_000,
  vertices: 1_000_000,
  // Mesh primitives drawn, counted once per instancing node, and declared nodes.
  primitives: 20_000,
  nodes: 20_000,
  jsonBytes: 4 * 1024 * 1024,
  depth: 64,
  // Feature edges need a vertex weld and an edge table; past this they are skipped.
  edgeTriangles: 600_000,
});

/** A Worker that has not answered by then is terminated. */
export const DEADLINE_MS = 15_000;

/** The fixed codes a Worker may answer with; anything else reads as a failure. */
export const CODES = Object.freeze([
  "invalid-file",
  "truncated",
  "non-finite",
  "external-buffer",
  "unsupported-extension",
  "unsupported-primitive",
  "out-of-bounds",
  "index-out-of-range",
  "node-cycle",
  "too-deep",
  "too-many-triangles",
  "too-many-vertices",
  "too-many-parts",
  "empty",
  "timeout",
  "worker-failed",
]);

export class ModelError extends Error {
  constructor(code) {
    super(code);
    this.name = "ModelError";
    this.code = CODES.includes(code) ? code : "worker-failed";
  }
}

export const fail = (code) => {
  throw new ModelError(code);
};
