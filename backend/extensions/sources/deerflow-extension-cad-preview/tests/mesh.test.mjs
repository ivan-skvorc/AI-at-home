import assert from "node:assert/strict";
import test from "node:test";

import { LIMITS } from "../ui/limits.js";
import { featureEdges, prepareModel } from "../ui/mesh.js";
import { binaryStl, cube, glb, meshDocument } from "./helpers.mjs";

const round = (values) => values.map((value) => Math.round(value * 1e4) / 1e4);

test("an STL in millimetres keeps its CAD size and stands Z-up", () => {
  const model = prepareModel("stl", binaryStl(cube([60, 40, 6])));
  assert.deepEqual(round(model.size), [60, 40, 6]);
  // The scene is Y-up: CAD Z (6 mm) becomes the scene's height.
  assert.deepEqual(round(model.box.max.map((v, i) => v - model.box.min[i])), [60, 6, 40]);
  assert.equal(model.triangles, 12);
  assert.equal(model.normals.length, model.positions.length);
});

test("a GLB in metres is shown in millimetres in the CAD frame", () => {
  // The CAD module's layout: millimetre vertices, a 0.001 root and a Z-up turn.
  const triangles = cube([60, 40, 6]);
  const { json, bin } = meshDocument({
    positions: triangles.flat(2),
    nodes: [
      { children: [1], scale: [0.001, 0.001, 0.001] },
      { mesh: 0, rotation: [-Math.SQRT1_2, 0, 0, Math.SQRT1_2] },
    ],
  });
  const model = prepareModel("glb", glb(json, bin));
  assert.deepEqual(round(model.size), [60, 40, 6]);
  assert.deepEqual(model.groups, [{ node: 1, name: "", start: 0, count: 12 }]);
});

test("a cube has 12 feature edges and no face diagonals", () => {
  const model = prepareModel("stl", binaryStl(cube([2, 2, 2])));
  assert.equal(model.edges.length / 6, 12);
});

test("faces of a GLB primitive draw their shared boundary", () => {
  // Two coplanar triangles in different primitives meet without an angle:
  // only a real fold or the outline of the part is an edge.
  const positions = new Float32Array([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0]);
  const indices = new Uint32Array([0, 1, 2, 0, 2, 3]);
  const sameFace = featureEdges(positions, indices, new Int32Array([0, 0]));
  assert.equal(sameFace.length / 6, 4);
  const folded = new Float32Array([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0.2]);
  assert.equal(featureEdges(folded, indices, new Int32Array([0, 1])).length / 6, 5);
  assert.equal(featureEdges(folded, indices, new Int32Array([0, 0])).length / 6, 4);
});

test("edges are skipped above the edge triangle limit", () => {
  const model = prepareModel("stl", binaryStl(cube()), { ...LIMITS, edgeTriangles: 11 });
  assert.equal(model.edges, null);
  assert.equal(model.edgesSkipped, true);
});
