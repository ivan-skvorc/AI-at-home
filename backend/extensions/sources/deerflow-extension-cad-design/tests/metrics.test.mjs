import assert from "node:assert/strict";
import test from "node:test";

import { meshMetrics, sceneToCad } from "../ui/metrics.js";
import { cube } from "../../deerflow-extension-cad-preview/tests/helpers.mjs";

const flat = (triangles) => new Float32Array(triangles.flat(2));

test("a closed box reports its size, volume and a manifold surface", () => {
  const metrics = meshMetrics(flat(cube([10, 20, 30])));
  assert.deepEqual(metrics.bbox_mm, [10, 20, 30]);
  assert.deepEqual(metrics.bbox_min_mm, [0, 0, 0]);
  assert.equal(metrics.volume_mm3, 6000);
  assert.equal(metrics.manifold, true);
  assert.equal(metrics.triangles, 12);
});

test("an open surface is not manifold", () => {
  const metrics = meshMetrics(flat(cube([1, 1, 1]).slice(0, 10)));
  assert.equal(metrics.manifold, false);
});

test("scene positions turn back into the CAD frame", () => {
  // The viewer stores CAD (x, y, z) as (x, z, -y).
  assert.deepEqual([...sceneToCad(new Float32Array([1, 3, -2]))], [1, 2, 3]);
});
