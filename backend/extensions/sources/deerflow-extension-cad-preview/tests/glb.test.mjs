import assert from "node:assert/strict";
import test from "node:test";

import { parseGlb } from "../ui/glb.js";
import { LIMITS } from "../ui/limits.js";
import { glb, meshDocument, rejectsWith } from "./helpers.mjs";

const square = {
  positions: [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0],
  indices: [0, 1, 2, 0, 2, 3],
};

test("a valid GLB composes node transforms into world positions", () => {
  // The CAD module's layout: a root scaled from millimetres to metres, and a
  // child that turns Z-up into glTF's Y-up.
  const { json, bin } = meshDocument({
    ...square,
    nodes: [
      { children: [1], scale: [0.001, 0.001, 0.001] },
      { mesh: 0, name: "part", rotation: [-Math.SQRT1_2, 0, 0, Math.SQRT1_2] },
    ],
  });
  const result = parseGlb(glb(json, bin));
  assert.equal(result.triangles, 2);
  assert.deepEqual([...result.indices], square.indices);
  // (1, 1, 0) mm turns into (0.001, 0, -0.001) m.
  const corner = [...result.positions.slice(6, 9)].map((v) => Math.round(v * 1e6) / 1e6);
  assert.deepEqual(corner, [0.001, 0, -0.001]);
  assert.deepEqual(result.groups, [{ node: 1, name: "part", start: 0, count: 2 }]);
});

test("an unindexed primitive and a matrix transform are accepted", () => {
  const { json, bin } = meshDocument({
    positions: square.positions.slice(0, 9),
    nodes: [{ mesh: 0, matrix: [2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2, 0, 5, 0, 0, 1] }],
  });
  const result = parseGlb(glb(json, bin));
  assert.deepEqual([...result.positions.slice(3, 6)], [7, 0, 0]);
  assert.deepEqual([...result.indices], [0, 1, 2]);
});

test("a buffer with a uri is refused: the preview fetches nothing", async () => {
  const { json, bin } = meshDocument(square);
  json.buffers[0].uri = "https://example.invalid/part.bin";
  await rejectsWith(() => parseGlb(glb(json, bin)), "external-buffer");
  json.buffers[0].uri = "data:application/octet-stream;base64,AAAA";
  await rejectsWith(() => parseGlb(glb(json, bin)), "external-buffer");
});

test("a required extension such as Draco is refused", async () => {
  const { json, bin } = meshDocument(square);
  json.extensionsUsed = ["KHR_draco_mesh_compression"];
  json.extensionsRequired = ["KHR_draco_mesh_compression"];
  await rejectsWith(() => parseGlb(glb(json, bin)), "unsupported-extension");
});

test("an accessor past the end of its buffer view is refused", async () => {
  const { json, bin } = meshDocument(square);
  json.accessors[0].count = 5;
  await rejectsWith(() => parseGlb(glb(json, bin)), "out-of-bounds");
  const view = meshDocument(square);
  view.json.bufferViews[1].byteLength += 4;
  await rejectsWith(() => parseGlb(glb(view.json, view.bin)), "out-of-bounds");
});

test("an index at or above the vertex count is refused", async () => {
  for (const index of [4, 2 ** 32 - 1]) {
    const { json, bin } = meshDocument({ ...square, indices: [0, 1, 2, 0, 2, index] });
    await rejectsWith(() => parseGlb(glb(json, bin)), "index-out-of-range");
  }
});

test("cyclic and shared nodes are refused", async () => {
  const cyclic = meshDocument({
    ...square,
    nodes: [{ children: [1] }, { mesh: 0, children: [0] }],
  });
  await rejectsWith(() => parseGlb(glb(cyclic.json, cyclic.bin)), "node-cycle");
  const self = meshDocument({ ...square, nodes: [{ mesh: 0, children: [0] }] });
  await rejectsWith(() => parseGlb(glb(self.json, self.bin)), "node-cycle");
  const shared = meshDocument({
    ...square,
    nodes: [{ children: [2] }, { children: [2] }, { mesh: 0 }],
    roots: [0, 1],
  });
  await rejectsWith(() => parseGlb(glb(shared.json, shared.bin)), "node-cycle");
});

test("a node tree deeper than 64 levels is refused", async () => {
  const nodes = Array.from({ length: 70 }, (_, i) =>
    i === 69 ? { mesh: 0 } : { children: [i + 1] },
  );
  const { json, bin } = meshDocument({ ...square, nodes });
  await rejectsWith(() => parseGlb(glb(json, bin)), "too-deep");
});

test("3 vertices with more than 1M index triplets are refused before allocation", async () => {
  const triplets = LIMITS.triangles + 1;
  const { json, bin } = meshDocument({
    positions: [0, 0, 0, 1, 0, 0, 0, 1, 0],
    indices: new Uint8Array(triplets * 3).map((_, i) => i % 3),
    indexType: 5121,
  });
  const allocated = [];
  const natives = {};
  for (const name of ["Float32Array", "Uint32Array", "Int32Array", "Float64Array"]) {
    natives[name] = globalThis[name];
    globalThis[name] = new Proxy(natives[name], {
      construct(target, args) {
        if (typeof args[0] === "number" && args[0] > 1024) allocated.push([name, args[0]]);
        return new target(...args);
      },
    });
  }
  const bytes = glb(json, bin);
  try {
    await rejectsWith(() => parseGlb(bytes), "too-many-triangles");
  } finally {
    Object.assign(globalThis, natives);
  }
  assert.deepEqual(allocated, []);
});

test("instancing one mesh from many nodes counts every instance", async () => {
  const nodes = [
    { children: Array.from({ length: 50 }, (_, i) => i + 1) },
    ...Array.from({ length: 50 }, () => ({ mesh: 0 })),
  ];
  const { json, bin } = meshDocument({ ...square, nodes });
  assert.equal(parseGlb(glb(json, bin)).triangles, 100);
  await rejectsWith(
    () => parseGlb(glb(json, bin), { ...LIMITS, triangles: 99 }),
    "too-many-triangles",
  );
  await rejectsWith(
    () => parseGlb(glb(json, bin), { ...LIMITS, vertices: 199 }),
    "too-many-vertices",
  );
  await rejectsWith(
    () => parseGlb(glb(json, bin), { ...LIMITS, primitives: 49 }),
    "too-many-parts",
  );
  await rejectsWith(() => parseGlb(glb(json, bin), { ...LIMITS, nodes: 50 }), "too-many-parts");
});

test("points and lines are refused", async () => {
  const { json, bin } = meshDocument(square);
  json.meshes[0].primitives[0].mode = 1;
  await rejectsWith(() => parseGlb(glb(json, bin)), "unsupported-primitive");
  json.meshes[0].primitives[0].mode = 4;
  json.accessors[0].sparse = { count: 1 };
  await rejectsWith(() => parseGlb(glb(json, bin)), "unsupported-primitive");
});

test("NaN positions and infinite transforms are refused", async () => {
  const nan = meshDocument({ ...square, positions: [0, 0, 0, NaN, 0, 0, 1, 1, 0, 0, 1, 0] });
  await rejectsWith(() => parseGlb(glb(nan.json, nan.bin)), "non-finite");
  const huge = meshDocument({ ...square, nodes: [{ mesh: 0, scale: [1e39, 1, 1] }] });
  await rejectsWith(() => parseGlb(glb(huge.json, huge.bin)), "non-finite");
});

test("container damage is refused", async () => {
  const { json, bin } = meshDocument(square);
  const good = new Uint8Array(glb(json, bin));
  const corrupt = (edit) => {
    const bytes = good.slice();
    edit(new DataView(bytes.buffer), bytes);
    return bytes.buffer;
  };
  await rejectsWith(() => parseGlb(corrupt((v) => v.setUint32(0, 0, true))), "invalid-file");
  await rejectsWith(() => parseGlb(corrupt((v) => v.setUint32(4, 1, true))), "invalid-file");
  await rejectsWith(() => parseGlb(corrupt((v) => v.setUint32(8, 9, true))), "invalid-file");
  // A JSON chunk length that breaks 4-byte alignment.
  await rejectsWith(
    () => parseGlb(corrupt((v) => v.setUint32(12, v.getUint32(12, true) - 1, true))),
    "invalid-file",
  );
  await rejectsWith(() => parseGlb(good.slice(0, good.length - 4).buffer), "invalid-file");
  await rejectsWith(() => parseGlb(glb({ asset: { version: "1.0" } })), "invalid-file");
});

test("a JSON chunk over 4 MiB is refused before it is decoded", async () => {
  const { json, bin } = meshDocument(square);
  json.extras = { padding: "x".repeat(LIMITS.jsonBytes) };
  await rejectsWith(() => parseGlb(glb(json, bin)), "invalid-file");
});

test("a scene without triangles is reported as empty", async () => {
  const { json, bin } = meshDocument({ ...square, nodes: [{}] });
  await rejectsWith(() => parseGlb(glb(json, bin)), "empty");
});
