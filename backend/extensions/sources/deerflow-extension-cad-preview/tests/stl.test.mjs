import assert from "node:assert/strict";
import test from "node:test";

import { LIMITS } from "../ui/limits.js";
import { parseStl } from "../ui/stl.js";
import { asciiStl, binaryStl, cube, rejectsWith } from "./helpers.mjs";

const triangle = [
  [0, 0, 0],
  [10, 0, 0],
  [0, 20, 5],
];

test("a binary STL whose header starts with 'solid' is read as binary", () => {
  // Exporters routinely write "solid <name>" into the 80-byte binary header.
  const result = parseStl(binaryStl(cube([60, 40, 6]), { header: "solid part" }));
  assert.equal(result.triangles, 12);
  assert.equal(result.positions.length, 12 * 9);
  assert.deepEqual(
    [Math.max(...result.positions.filter((_, i) => i % 3 === 0))],
    [60],
  );
});

test("an ASCII STL is read facet by facet", () => {
  const result = parseStl(asciiStl([triangle, triangle]));
  assert.equal(result.triangles, 2);
  assert.deepEqual([...result.positions.slice(0, 9)], triangle.flat());
});

test("a truncated binary STL is refused", async () => {
  const whole = new Uint8Array(binaryStl(cube()));
  await rejectsWith(() => parseStl(whole.slice(0, whole.length - 7).buffer), "truncated");
  // A header that claims more triangles than the file holds.
  await rejectsWith(() => parseStl(binaryStl([triangle], { count: 2 })), "truncated");
  // The same with a 'solid' header: the ASCII reader cannot rescue it.
  await rejectsWith(
    () => parseStl(binaryStl([triangle], { header: "solid x", count: 3 })),
    "truncated",
  );
});

test("NaN and infinite coordinates are refused", async () => {
  await rejectsWith(
    () => parseStl(binaryStl([[[0, 0, 0], [1, NaN, 0], [0, 1, 0]]])),
    "non-finite",
  );
  await rejectsWith(
    () => parseStl(binaryStl([[[0, 0, 0], [1, 0, Infinity], [0, 1, 0]]])),
    "non-finite",
  );
  const text = new TextDecoder()
    .decode(asciiStl([triangle]))
    .replace("vertex 10 0 0", "vertex nan 0 0");
  await rejectsWith(() => parseStl(new TextEncoder().encode(text).buffer), "non-finite");
  const overflow = new TextDecoder()
    .decode(asciiStl([triangle]))
    .replace("vertex 10 0 0", "vertex 1e999 0 0");
  await rejectsWith(
    () => parseStl(new TextEncoder().encode(overflow).buffer),
    "non-finite",
  );
});

test("malformed ASCII is refused, not guessed at", async () => {
  for (const [from, to] of [
    ["endloop", "endloops"],
    ["vertex 10 0 0", "vertex 10 0"],
    ["vertex 10 0 0", "vertex 0x10 0 0"],
    ["outer loop", "outer"],
  ]) {
    const text = new TextDecoder().decode(asciiStl([triangle])).replace(from, to);
    await rejectsWith(() => parseStl(new TextEncoder().encode(text).buffer), "invalid-file");
  }
});

test("a file with no triangles is reported as empty", async () => {
  await rejectsWith(() => parseStl(binaryStl([])), "empty");
  await rejectsWith(() => parseStl(asciiStl([])), "empty");
});

test("the triangle cap is checked before the vertex array is allocated", async () => {
  const limits = { ...LIMITS, triangles: 11 };
  const allocated = [];
  const Native = globalThis.Float32Array;
  globalThis.Float32Array = new Proxy(Native, {
    construct(target, args) {
      allocated.push(args[0]);
      return new target(...args);
    },
  });
  try {
    await rejectsWith(() => parseStl(binaryStl(cube()), limits), "too-many-triangles");
    await rejectsWith(() => parseStl(asciiStl(cube()), limits), "too-many-triangles");
  } finally {
    globalThis.Float32Array = Native;
  }
  assert.deepEqual(allocated, []);
  assert.equal(parseStl(binaryStl(cube()), { ...limits, triangles: 12 }).triangles, 12);
});
