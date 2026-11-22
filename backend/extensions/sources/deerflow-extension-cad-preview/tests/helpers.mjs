// Builders for hand-made STL and GLB bytes. Tests describe hostile files
// field by field, so a fixture states exactly which rule it breaks.

export function binaryStl(triangles, { header = "", count } = {}) {
  const bytes = new Uint8Array(84 + 50 * triangles.length);
  bytes.set(new TextEncoder().encode(header.slice(0, 80)));
  const view = new DataView(bytes.buffer);
  view.setUint32(80, count ?? triangles.length, true);
  triangles.forEach((corners, index) => {
    const offset = 84 + 50 * index + 12;
    corners.flat().forEach((value, k) => {
      view.setFloat32(offset + 4 * k, value, true);
    });
  });
  return bytes.buffer;
}

export function asciiStl(triangles, name = "part") {
  const facets = triangles
    .map(
      (corners) =>
        `  facet normal 0 0 1\n    outer loop\n${corners
          .map((point) => `      vertex ${point.join(" ")}\n`)
          .join("")}    endloop\n  endfacet\n`,
    )
    .join("");
  return new TextEncoder().encode(`solid ${name}\n${facets}endsolid ${name}\n`)
    .buffer;
}

const pad = (length) => (4 - (length % 4)) % 4;

/** A GLB container around `json` and an optional BIN chunk. */
export function glb(json, bin) {
  const text = new TextEncoder().encode(JSON.stringify(json));
  const jsonLength = text.length + pad(text.length);
  const binLength = bin ? bin.byteLength + pad(bin.byteLength) : 0;
  const total = 12 + 8 + jsonLength + (bin ? 8 + binLength : 0);
  const bytes = new Uint8Array(total);
  const view = new DataView(bytes.buffer);
  view.setUint32(0, 0x46546c67, true);
  view.setUint32(4, 2, true);
  view.setUint32(8, total, true);
  view.setUint32(12, jsonLength, true);
  view.setUint32(16, 0x4e4f534a, true);
  bytes.fill(0x20, 20, 20 + jsonLength);
  bytes.set(text, 20);
  if (bin) {
    const offset = 20 + jsonLength;
    view.setUint32(offset, binLength, true);
    view.setUint32(offset + 4, 0x004e4942, true);
    bytes.set(new Uint8Array(bin), offset + 8);
  }
  return bytes.buffer;
}

/**
 * One mesh of `positions` (flat xyz) and optional `indices`, placed by `nodes`.
 * Returns the JSON and BIN for `glb()`, so a test can corrupt either first.
 */
export function meshDocument({
  positions,
  indices,
  indexType = 5125,
  nodes = [{ mesh: 0 }],
  roots = [0],
}) {
  const positionBytes = new Float32Array(positions);
  const IndexArray = { 5121: Uint8Array, 5123: Uint16Array, 5125: Uint32Array }[
    indexType
  ];
  const indexBytes = indices ? new IndexArray(indices) : null;
  const positionLength = positionBytes.byteLength;
  const indexOffset = positionLength;
  const indexLength = indexBytes ? indexBytes.byteLength : 0;
  const bin = new Uint8Array(positionLength + indexLength + pad(indexLength));
  bin.set(new Uint8Array(positionBytes.buffer), 0);
  if (indexBytes) bin.set(new Uint8Array(indexBytes.buffer), indexOffset);
  const json = {
    asset: { version: "2.0" },
    scene: 0,
    scenes: [{ nodes: roots }],
    nodes,
    meshes: [
      {
        primitives: [
          {
            attributes: { POSITION: 0 },
            ...(indexBytes ? { indices: 1 } : {}),
            mode: 4,
          },
        ],
      },
    ],
    buffers: [{ byteLength: bin.byteLength }],
    bufferViews: [
      { buffer: 0, byteOffset: 0, byteLength: positionLength },
      ...(indexBytes
        ? [{ buffer: 0, byteOffset: indexOffset, byteLength: indexLength }]
        : []),
    ],
    accessors: [
      {
        bufferView: 0,
        componentType: 5126,
        count: positions.length / 3,
        type: "VEC3",
      },
      ...(indexBytes
        ? [
            {
              bufferView: 1,
              componentType: indexType,
              count: indices.length,
              type: "SCALAR",
            },
          ]
        : []),
    ],
  };
  return { json, bin: bin.buffer };
}

/** A unit cube of 12 triangles in millimetres, minimum corner at the origin. */
export function cube(size = [1, 1, 1]) {
  const [x, y, z] = size;
  const corners = [
    [0, 0, 0],
    [x, 0, 0],
    [x, y, 0],
    [0, y, 0],
    [0, 0, z],
    [x, 0, z],
    [x, y, z],
    [0, y, z],
  ];
  const quads = [
    [0, 3, 2, 1],
    [4, 5, 6, 7],
    [0, 1, 5, 4],
    [1, 2, 6, 5],
    [2, 3, 7, 6],
    [3, 0, 4, 7],
  ];
  return quads.flatMap(([a, b, c, d]) => [
    [corners[a], corners[b], corners[c]],
    [corners[a], corners[c], corners[d]],
  ]);
}

export async function rejectsWith(promiseOrFn, code) {
  try {
    await (typeof promiseOrFn === "function" ? promiseOrFn() : promiseOrFn);
  } catch (error) {
    if (error?.code === code) return error;
    throw new Error(`Expected ${code}, got ${error?.code ?? error}`);
  }
  throw new Error(`Expected ${code}, but it succeeded`);
}
