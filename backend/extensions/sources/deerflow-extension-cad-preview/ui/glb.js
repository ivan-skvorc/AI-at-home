import { LIMITS, fail } from "./limits.js";

const MAGIC = 0x46546c67; // "glTF"
const JSON_CHUNK = 0x4e4f534a;
const BIN_CHUNK = 0x004e4942;
const TRIANGLES = 4;
const FLOAT = 5126;
const INDEX_SIZES = { 5121: 1, 5123: 2, 5125: 4 };

/**
 * Read the strict glTF 2.0 subset the preview draws: one GLB with its data in
 * the BIN chunk, triangle primitives with float positions, unsigned indices,
 * and a node tree. Returns world positions in glTF units (metres, Y-up), one
 * index list for a single draw call, and the triangle range of each node so a
 * later caller can pick a body.
 *
 * Every declaration is checked and every count summed in `plan()` before an
 * output array exists; the read pass then only copies what the plan allowed.
 */
export function parseGlb(buffer, limits = LIMITS) {
  const plan = planGlb(buffer, limits);
  const positions = new Float32Array(plan.vertices * 3);
  const indices = new Uint32Array(plan.triangles * 3);
  const faces = new Int32Array(plan.triangles);
  const groups = [];
  let vertexBase = 0;
  let indexBase = 0;
  plan.instances.forEach(({ node, name, matrix, primitives }) => {
    const start = indexBase / 3;
    for (const primitive of primitives) {
      const { position, index } = primitive;
      readPositions(plan.bin, position, matrix, positions, vertexBase);
      const count = index ? index.count : position.count;
      if (index) readIndices(plan.bin, index, position.count, indices, indexBase, vertexBase);
      else for (let i = 0; i < count; i++) indices[indexBase + i] = vertexBase + i;
      faces.fill(primitive.face, indexBase / 3, (indexBase + count) / 3);
      vertexBase += position.count;
      indexBase += count;
    }
    if (indexBase / 3 > start) groups.push({ node, name, start, count: indexBase / 3 - start });
  });
  return { positions, indices, faces, groups, triangles: plan.triangles };
}

function planGlb(buffer, limits) {
  const view = new DataView(buffer);
  const length = buffer.byteLength;
  if (length < 20) fail("invalid-file");
  if (view.getUint32(0, true) !== MAGIC || view.getUint32(4, true) !== 2) fail("invalid-file");
  if (view.getUint32(8, true) !== length) fail("invalid-file");
  const chunks = [];
  for (let offset = 12; offset < length; ) {
    if (offset + 8 > length) fail("invalid-file");
    const size = view.getUint32(offset, true);
    const type = view.getUint32(offset + 4, true);
    if (size % 4 !== 0 || offset + 8 + size > length) fail("invalid-file");
    chunks.push({ type, start: offset + 8, size });
    offset += 8 + size;
  }
  const [head, second] = chunks;
  if (head?.type !== JSON_CHUNK) fail("invalid-file");
  if (head.size > limits.jsonBytes) fail("invalid-file");
  if (chunks.some((chunk, i) => i > 0 && (chunk.type === JSON_CHUNK || (chunk.type === BIN_CHUNK && i !== 1))))
    fail("invalid-file");
  let doc;
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(
      new Uint8Array(buffer, head.start, head.size),
    );
    doc = JSON.parse(text);
  } catch {
    fail("invalid-file");
  }
  if (!isObject(doc) || !isObject(doc.asset) || !/^2\.\d+$/.test(String(doc.asset.version)))
    fail("invalid-file");
  if (doc.extensionsRequired !== undefined) {
    if (!Array.isArray(doc.extensionsRequired)) fail("invalid-file");
    if (doc.extensionsRequired.length) fail("unsupported-extension");
  }
  const bin = second?.type === BIN_CHUNK ? new DataView(buffer, second.start, second.size) : null;
  const buffers = list(doc.buffers);
  buffers.forEach((entry, i) => {
    if (!isObject(entry)) fail("invalid-file");
    if (entry.uri !== undefined) fail("external-buffer");
    // Only the first buffer may live in the BIN chunk; any other would need a uri.
    if (i > 0 || !bin || !count(entry.byteLength) || entry.byteLength > bin.byteLength)
      fail("invalid-file");
  });
  const nodes = list(doc.nodes);
  if (nodes.length > limits.nodes) fail("too-many-parts");
  const views = list(doc.bufferViews);
  const accessors = list(doc.accessors);
  const meshes = list(doc.meshes);
  const accessor = (index, role) => checkAccessor(index, role, accessors, views, buffers);
  const sceneIndex = doc.scene ?? 0;
  const scenes = list(doc.scenes);
  if (!scenes.length && doc.scene === undefined) fail("empty");
  const scene = at(scenes, sceneIndex);
  const roots = list(scene.nodes);

  const instances = [];
  const totals = { triangles: 0, vertices: 0, primitives: 0 };
  const visited = new Uint8Array(nodes.length);
  const stack = roots.map((root) => ({ index: root, depth: 1, parent: IDENTITY }));
  while (stack.length) {
    const { index, depth, parent } = stack.pop();
    const node = at(nodes, index);
    if (visited[index]) fail("node-cycle");
    visited[index] = 1;
    if (depth > limits.depth) fail("too-deep");
    const matrix = multiply(parent, localMatrix(node));
    if (node.mesh !== undefined) {
      const mesh = at(meshes, node.mesh);
      const primitives = list(mesh.primitives).map((primitive) => {
        if (!isObject(primitive) || !isObject(primitive.attributes)) fail("invalid-file");
        if ((primitive.mode ?? TRIANGLES) !== TRIANGLES) fail("unsupported-primitive");
        const position = accessor(primitive.attributes.POSITION, "position");
        const index = primitive.indices === undefined ? null : accessor(primitive.indices, "index");
        const corners = index ? index.count : position.count;
        if (corners % 3 !== 0) fail("invalid-file");
        totals.triangles += corners / 3;
        totals.vertices += position.count;
        totals.primitives += 1;
        if (totals.triangles > limits.triangles) fail("too-many-triangles");
        if (totals.vertices > limits.vertices) fail("too-many-vertices");
        if (totals.primitives > limits.primitives) fail("too-many-parts");
        return { position, index, face: totals.primitives - 1 };
      });
      const name = typeof node.name === "string" ? node.name : typeof mesh.name === "string" ? mesh.name : "";
      instances.push({ node: index, name: name.slice(0, 200), matrix, primitives });
    }
    const children = list(node.children);
    for (let i = children.length - 1; i >= 0; i--)
      stack.push({ index: children[i], depth: depth + 1, parent: matrix });
  }
  if (totals.triangles === 0) fail("empty");
  return { bin, instances, ...totals };
}

/** Bounds, alignment and type of one accessor, against its view and buffer. */
function checkAccessor(index, role, accessors, views, buffers) {
  const accessor = at(accessors, index);
  if (accessor.sparse !== undefined) fail("unsupported-primitive");
  const size = role === "position" ? 4 : INDEX_SIZES[accessor.componentType];
  if (role === "position") {
    if (accessor.componentType !== FLOAT || accessor.type !== "VEC3" || accessor.normalized)
      fail("unsupported-primitive");
  } else if (!size || accessor.type !== "SCALAR") fail("unsupported-primitive");
  if (!count(accessor.count) || accessor.count === 0) fail("invalid-file");
  const view = at(views, accessor.bufferView);
  const buffer = at(buffers, view.buffer);
  const viewOffset = view.byteOffset ?? 0;
  const offset = accessor.byteOffset ?? 0;
  if (!count(viewOffset) || !count(view.byteLength) || !count(offset)) fail("invalid-file");
  if (viewOffset + view.byteLength > buffer.byteLength) fail("out-of-bounds");
  const element = role === "position" ? 12 : size;
  let stride = element;
  if (view.byteStride !== undefined) {
    if (role !== "position") fail("invalid-file");
    stride = view.byteStride;
    if (!count(stride) || stride < element || stride > 252 || stride % 4 !== 0) fail("invalid-file");
  }
  if ((viewOffset + offset) % size !== 0) fail("invalid-file");
  if (offset + stride * (accessor.count - 1) + element > view.byteLength) fail("out-of-bounds");
  return { start: viewOffset + offset, stride, size, count: accessor.count };
}

function readPositions(bin, position, matrix, out, base) {
  const m = matrix;
  for (let i = 0; i < position.count; i++) {
    const offset = position.start + i * position.stride;
    const x = bin.getFloat32(offset, true);
    const y = bin.getFloat32(offset + 4, true);
    const z = bin.getFloat32(offset + 8, true);
    const target = (base + i) * 3;
    out[target] = m[0] * x + m[4] * y + m[8] * z + m[12];
    out[target + 1] = m[1] * x + m[5] * y + m[9] * z + m[13];
    out[target + 2] = m[2] * x + m[6] * y + m[10] * z + m[14];
    if (
      !Number.isFinite(out[target]) ||
      !Number.isFinite(out[target + 1]) ||
      !Number.isFinite(out[target + 2])
    )
      fail("non-finite");
  }
}

function readIndices(bin, index, vertices, out, outBase, vertexBase) {
  const read =
    index.size === 1
      ? (offset) => bin.getUint8(offset)
      : index.size === 2
        ? (offset) => bin.getUint16(offset, true)
        : (offset) => bin.getUint32(offset, true);
  for (let i = 0; i < index.count; i++) {
    const value = read(index.start + i * index.size);
    if (value >= vertices) fail("index-out-of-range");
    out[outBase + i] = vertexBase + value;
  }
}

const IDENTITY = Object.freeze([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);

function localMatrix(node) {
  const numbers = (value, length, fallback) => {
    if (value === undefined) return fallback;
    if (!Array.isArray(value) || value.length !== length) fail("invalid-file");
    for (const item of value) {
      if (typeof item !== "number") fail("invalid-file");
      if (!Number.isFinite(item)) fail("non-finite");
    }
    return value;
  };
  if (node.matrix !== undefined) return numbers(node.matrix, 16);
  const [tx, ty, tz] = numbers(node.translation, 3, [0, 0, 0]);
  let [qx, qy, qz, qw] = numbers(node.rotation, 4, [0, 0, 0, 1]);
  const [sx, sy, sz] = numbers(node.scale, 3, [1, 1, 1]);
  const norm = Math.hypot(qx, qy, qz, qw);
  if (norm === 0) fail("invalid-file");
  qx /= norm;
  qy /= norm;
  qz /= norm;
  qw /= norm;
  // Column-major, as glTF stores matrices: T * R * S.
  return [
    (1 - 2 * (qy * qy + qz * qz)) * sx,
    2 * (qx * qy + qz * qw) * sx,
    2 * (qx * qz - qy * qw) * sx,
    0,
    2 * (qx * qy - qz * qw) * sy,
    (1 - 2 * (qx * qx + qz * qz)) * sy,
    2 * (qy * qz + qx * qw) * sy,
    0,
    2 * (qx * qz + qy * qw) * sz,
    2 * (qy * qz - qx * qw) * sz,
    (1 - 2 * (qx * qx + qy * qy)) * sz,
    0,
    tx,
    ty,
    tz,
    1,
  ];
}

function multiply(a, b) {
  const out = Array(16);
  for (let column = 0; column < 4; column++)
    for (let row = 0; row < 4; row++) {
      let sum = 0;
      for (let k = 0; k < 4; k++) sum += a[k * 4 + row] * b[column * 4 + k];
      out[column * 4 + row] = sum;
    }
  if (!out.every(Number.isFinite)) fail("non-finite");
  return out;
}

function isObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function count(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function list(value) {
  if (value === undefined) return [];
  if (!Array.isArray(value)) fail("invalid-file");
  return value;
}

/** An entry by index, refusing a missing index, a hole or a non-object. */
function at(items, index) {
  if (!count(index) || index >= items.length || !isObject(items[index])) fail("invalid-file");
  return items[index];
}
