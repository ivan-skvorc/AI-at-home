import { LIMITS, fail } from "./limits.js";

const NUMBER = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;
const NOT_FINITE = /^[+-]?(?:nan|inf(?:inity)?)$/i;

/**
 * Read a binary or ASCII STL into a flat list of triangle corners, in the
 * file's own units (millimetres for the CAD module) and frame (Z-up).
 *
 * A file is binary when 84 + 50 n equals its length, n being the header's
 * triangle count. That holds even when the 80-byte header starts with
 * "solid", which many binary exporters write. Text never holds a NUL byte, so
 * a "solid" file with one is a binary file of the wrong length.
 */
export function parseStl(buffer, limits = LIMITS) {
  const bytes = new Uint8Array(buffer);
  const view = new DataView(buffer);
  const declared = bytes.length >= 84 ? view.getUint32(80, true) : -1;
  if (declared >= 0 && 84 + 50 * declared === bytes.length)
    return readBinary(view, declared, limits);
  if (startsWithSolid(bytes) && !bytes.includes(0))
    return readAscii(new TextDecoder().decode(bytes), limits);
  if (declared < 0 || 84 + 50 * declared > bytes.length) fail("truncated");
  fail("invalid-file");
}

function startsWithSolid(bytes) {
  let start = 0;
  while (start < bytes.length && start < 256 && bytes[start] <= 0x20) start++;
  const word = String.fromCharCode(...bytes.subarray(start, start + 5));
  return word.toLowerCase() === "solid";
}

function readBinary(view, triangles, limits) {
  if (triangles === 0) fail("empty");
  if (triangles > limits.triangles) fail("too-many-triangles");
  const positions = new Float32Array(triangles * 9);
  for (let t = 0; t < triangles; t++) {
    const offset = 84 + 50 * t + 12;
    for (let k = 0; k < 9; k++) {
      const value = view.getFloat32(offset + 4 * k, true);
      if (!Number.isFinite(value)) fail("non-finite");
      positions[t * 9 + k] = value;
    }
  }
  return { positions, triangles };
}

/**
 * A strict reader of the ASCII grammar: a "solid" line, facets of exactly
 * three vertices, an "endsolid" line; several solids may follow one another.
 * The first pass checks and counts, the second fills an array of that size.
 */
function readAscii(text, limits) {
  const triangles = walk(text, limits, null);
  if (triangles === 0) fail("empty");
  const positions = new Float32Array(triangles * 9);
  walk(text, limits, positions);
  return { positions, triangles };
}

function walk(text, limits, out) {
  const tokens = /\S+/g;
  const next = () => tokens.exec(text)?.[0].toLowerCase() ?? null;
  // A name runs to the end of its line.
  const skipLine = () => {
    const end = text.indexOf("\n", tokens.lastIndex);
    tokens.lastIndex = end < 0 ? text.length : end;
  };
  const expect = (word) => {
    if (next() !== word) fail("invalid-file");
  };
  const number = () => {
    const token = next();
    if (token === null) fail("invalid-file");
    if (NOT_FINITE.test(token)) fail("non-finite");
    if (!NUMBER.test(token)) fail("invalid-file");
    const value = Number(token);
    // A literal past the float range reads as Infinity once stored.
    if (!Number.isFinite(Math.fround(value))) fail("non-finite");
    return value;
  };
  let triangles = 0;
  let token = next();
  while (token !== null) {
    if (token !== "solid") fail("invalid-file");
    skipLine();
    for (token = next(); token === "facet"; token = next()) {
      expect("normal");
      number(), number(), number();
      expect("outer");
      expect("loop");
      for (let corner = 0; corner < 3; corner++) {
        expect("vertex");
        for (let axis = 0; axis < 3; axis++) {
          const value = number();
          if (out) out[triangles * 9 + corner * 3 + axis] = value;
        }
      }
      expect("endloop");
      expect("endfacet");
      if (++triangles > limits.triangles) fail("too-many-triangles");
    }
    if (token !== "endsolid") fail("invalid-file");
    skipLine();
    token = next();
  }
  return triangles;
}
