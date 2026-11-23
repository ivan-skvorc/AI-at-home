import assert from "node:assert/strict";
import test from "node:test";

import {
  extractWasm,
  readOpenscadModule,
  runtimeSource,
} from "../openscad-source.mjs";

const source = await readOpenscadModule();

test("the inlined binary is a WebAssembly module", () => {
  const wasm = extractWasm(source);
  assert.deepEqual([...wasm.subarray(0, 4)], [0, 0x61, 0x73, 0x6d]);
  assert.ok(wasm.length > 4 * 1024 * 1024, "the full OpenSCAD build");
  assert.equal(WebAssembly.validate(wasm), true);
});

test("the runtime keeps the factory and drops the literal and every network path", () => {
  const runtime = runtimeSource(source);
  assert.ok(runtime.length < 1024 * 1024);
  assert.match(runtime, /export \{ OpenSCAD \};/);
  assert.doesNotMatch(
    runtime,
    /\bfetch\(|XMLHttpRequest\(|importScripts|\bimport\s*\(/,
  );
});

test("an unexpected layout fails the build instead of shipping a broken runtime", () => {
  assert.throws(() => extractWasm("export {};"), /inlined wasm not found/);
  assert.throws(() => runtimeSource("export {};"), /unexpected module layout/);
});
