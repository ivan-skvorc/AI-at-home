// Runs the shipped Worker bundle in node with the shipped WebAssembly asset:
// the same bytes and code a browser gets, minus the Worker wrapper.
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { gunzipSync } from "node:zlib";

import { parseStl } from "../../deerflow-extension-cad-preview/ui/stl.js";
import { meshMetrics } from "../ui/metrics.js";

const root = new URL("../deerflow_extension_cad_design/", import.meta.url);
const manifest = JSON.parse(
  await readFile(new URL("ui_manifest.json", root), "utf8"),
);
const wasmFiles = manifest.files
  .filter((file) => file.endsWith(".wasm"))
  .sort();
const packed = Buffer.concat(
  await Promise.all(wasmFiles.map((file) => readFile(new URL(file, root)))),
);
const wasm = gunzipSync(packed);

const replies = [];
let waiting = null;
globalThis.self = {
  postMessage(message) {
    replies.push(message);
    waiting?.();
  },
};
await import(new URL("static/dist/chunks/scad-worker.mjs", root));

async function send(data) {
  const before = replies.length;
  const arrived = new Promise((resolve) => (waiting = resolve));
  await self.onmessage({ data });
  if (replies.length === before) await arrived;
  return replies.at(-1);
}

test("the worker compiles the shipped bytes", async () => {
  const buffer = wasm.buffer.slice(
    wasm.byteOffset,
    wasm.byteOffset + wasm.byteLength,
  );
  assert.deepEqual(await send({ type: "init", wasm: buffer }), {
    type: "ready",
  });
});

test("a cube renders to a binary STL of its size", async () => {
  const reply = await send({
    type: "render",
    id: 1,
    code: "w = 10;\ncube([w, 20, 30]);\n",
  });
  assert.equal(reply.ok, true, reply.error);
  assert.equal(reply.id, 1);
  const { positions, triangles } = parseStl(reply.stl);
  assert.equal(triangles, 12);
  assert.deepEqual(meshMetrics(positions).bbox_mm, [10, 20, 30]);
  // The worker also sends the prepared mesh (Y up) and its CAD-frame metrics.
  assert.equal(reply.model.triangles, 12);
  assert.deepEqual(reply.model.size, [10, 20, 30]);
  assert.ok(reply.model.normals instanceof Float32Array);
  assert.deepEqual(reply.metrics.bbox_mm, [10, 20, 30]);
  assert.equal(reply.metrics.volume_mm3, 6000);
  assert.equal(reply.metrics.manifold, true);
});

test("a boolean difference renders a closed part", async () => {
  const reply = await send({
    type: "render",
    id: 2,
    code: "difference() { cube([20, 10, 5]); translate([5, 5, -1]) cylinder(d = 3, h = 10, $fn = 24); }",
  });
  assert.equal(reply.ok, true, reply.error);
  assert.equal(reply.metrics.manifold, true);
});

test("a syntax error answers with its line and no mesh", async () => {
  const reply = await send({
    type: "render",
    id: 3,
    code: "cube(1);\ncube([1, 2, 3] 5);\ncube(2);\n",
  });
  assert.equal(reply.ok, false);
  assert.equal(reply.stl, null);
  assert.equal(reply.model, null);
  assert.match(reply.error, /syntax error/);
  assert.deepEqual(reply.errorLines, [2]);
});

test("files outside the source cannot be read", async (t) => {
  // Real, readable host files that would render if the Worker could see them: a
  // valid STL tetrahedron and an OpenSCAD file with a 50 mm cube in it.
  const dir = await mkdtemp(join(tmpdir(), "scad-worker-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const facet = (a, b, c) =>
    `facet normal 0 0 0\nouter loop\nvertex ${a}\nvertex ${b}\nvertex ${c}\nendloop\nendfacet\n`;
  const o = "0 0 0",
    x = "1 0 0",
    y = "0 1 0",
    z = "0 0 1";
  const stl = join(dir, "part.stl");
  await writeFile(
    stl,
    `solid t\n${facet(o, y, x)}${facet(o, x, z)}${facet(o, z, y)}${facet(x, y, z)}endsolid t\n`,
  );
  const scad = join(dir, "big.scad");
  await writeFile(scad, "cube(50);\n");

  const imported = await send({
    type: "render",
    id: 4,
    code: `import("${stl}");`,
  });
  assert.equal(imported.ok, false);
  assert.match(imported.warnings.join("\n"), /Can't open import file/);

  const included = await send({
    type: "render",
    id: 5,
    code: `include <${scad}>\ncube(1);\n`,
  });
  assert.match(included.warnings.join("\n"), /Can't open include file/);
  assert.deepEqual(included.metrics?.bbox_mm, [1, 1, 1]);
});
