import { parseGlb } from "./glb.js";
import { LIMITS } from "./limits.js";
import { parseStl } from "./stl.js";

/** An edge between two faces of a part shows above this fold, in degrees. */
const FACE_FOLD = 1;
/** An edge inside one face, or anywhere in an STL, shows above this fold. */
const FEATURE_FOLD = 30;

/**
 * Parse a model and prepare what the viewer uploads: scene positions in
 * millimetres with Y up, normals, one index list (or none for an STL), the
 * feature edges, and the size along the CAD axes (X, Y, Z with Z up).
 *
 * glTF is metres and Y-up by definition. The CAD module's STL is millimetres
 * and Z-up, so it is turned -90 degrees about X: (x, y, z) -> (x, z, -y).
 */
export function prepareModel(kind, buffer, limits = LIMITS) {
  let positions, indices, faces, groups, triangles;
  if (kind === "glb") {
    ({ positions, indices, faces, groups, triangles } = parseGlb(buffer, limits));
    for (let i = 0; i < positions.length; i++) positions[i] *= 1000;
  } else {
    ({ positions, triangles } = parseStl(buffer, limits));
    for (let i = 0; i < positions.length; i += 3) {
      const y = positions[i + 1];
      positions[i + 1] = positions[i + 2];
      positions[i + 2] = -y;
    }
    indices = null;
    faces = null;
    groups = [];
  }
  const box = bounds(positions, indices);
  const normals = vertexNormals(positions, indices);
  const edgesSkipped = triangles > limits.edgeTriangles;
  const edges = edgesSkipped ? null : featureEdges(positions, indices, faces);
  const size = [
    box.max[0] - box.min[0],
    box.max[2] - box.min[2],
    box.max[1] - box.min[1],
  ];
  return { positions, normals, indices, edges, edgesSkipped, groups, box, size, triangles };
}

/** The box of the vertices the triangles use; an unused vertex does not count. */
function bounds(positions, indices) {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  const corners = indices ? indices.length : positions.length / 3;
  for (let i = 0; i < corners; i++) {
    const v = (indices ? indices[i] : i) * 3;
    for (let axis = 0; axis < 3; axis++) {
      const value = positions[v + axis];
      if (value < min[axis]) min[axis] = value;
      if (value > max[axis]) max[axis] = value;
    }
  }
  return { min, max };
}

/** Area-weighted vertex normals: smooth inside a face, sharp where vertices are not shared. */
function vertexNormals(positions, indices) {
  const normals = new Float32Array(positions.length);
  const corners = indices ? indices.length : positions.length / 3;
  for (let i = 0; i < corners; i += 3) {
    const a = (indices ? indices[i] : i) * 3;
    const b = (indices ? indices[i + 1] : i + 1) * 3;
    const c = (indices ? indices[i + 2] : i + 2) * 3;
    const [nx, ny, nz] = cross(positions, a, b, c);
    for (const v of [a, b, c]) {
      normals[v] += nx;
      normals[v + 1] += ny;
      normals[v + 2] += nz;
    }
  }
  for (let v = 0; v < normals.length; v += 3) {
    const length = Math.hypot(normals[v], normals[v + 1], normals[v + 2]);
    if (length > 0) {
      normals[v] /= length;
      normals[v + 1] /= length;
      normals[v + 2] /= length;
    }
  }
  return normals;
}

function cross(p, a, b, c) {
  const ux = p[b] - p[a];
  const uy = p[b + 1] - p[a + 1];
  const uz = p[b + 2] - p[a + 2];
  const vx = p[c] - p[a];
  const vy = p[c + 1] - p[a + 1];
  const vz = p[c + 2] - p[a + 2];
  return [uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx];
}

const nextPower = (n) => 2 ** Math.ceil(Math.log2(Math.max(2, n)));

/**
 * Line segments where the surface folds: an open boundary, an edge shared by
 * three or more triangles, a fold above FEATURE_FOLD, or (with `faces`, one id
 * per triangle) any fold above FACE_FOLD between two faces of the part. The
 * CAD module writes one primitive per face, so its faces' outlines are drawn
 * and a cylinder's facets are not.
 *
 * Vertices are welded by quantized position first, because a GLB gives each
 * face its own copy of the vertices on a shared edge.
 */
export function featureEdges(positions, indices, faces = null) {
  const vertexCount = positions.length / 3;
  const triangles = (indices ? indices.length : vertexCount) / 3;
  const corner = (t, k) => (indices ? indices[t * 3 + k] : t * 3 + k);
  const weld = weldVertices(positions);
  const normals = new Float32Array(triangles * 3);
  for (let t = 0; t < triangles; t++) {
    const [x, y, z] = cross(positions, corner(t, 0) * 3, corner(t, 1) * 3, corner(t, 2) * 3);
    const length = Math.hypot(x, y, z);
    if (length > 0) normals.set([x / length, y / length, z / length], t * 3);
  }
  const fold = (degrees) => Math.cos((degrees * Math.PI) / 180);
  const featureCos = fold(FEATURE_FOLD);
  const faceCos = fold(FACE_FOLD);
  const size = nextPower(triangles * 6);
  const keys = new Float64Array(size).fill(-1);
  const first = new Int32Array(size);
  // 1 one triangle, 2 a fold to draw, 3 smooth.
  const state = new Uint8Array(size);
  const mask = size - 1;
  for (let t = 0; t < triangles; t++) {
    for (let k = 0; k < 3; k++) {
      const a = weld[corner(t, k)];
      const b = weld[corner(t, (k + 1) % 3)];
      if (a === b) continue;
      const lo = Math.min(a, b);
      const hi = Math.max(a, b);
      const key = lo * vertexCount + hi;
      let slot = (Math.imul(lo, 0x9e3779b1) ^ Math.imul(hi, 0x85ebca6b)) & mask;
      while (keys[slot] !== -1 && keys[slot] !== key) slot = (slot + 1) & mask;
      if (keys[slot] === -1) {
        keys[slot] = key;
        first[slot] = t;
        state[slot] = 1;
      } else if (state[slot] === 1) {
        const other = first[slot];
        const cosine =
          normals[t * 3] * normals[other * 3] +
          normals[t * 3 + 1] * normals[other * 3 + 1] +
          normals[t * 3 + 2] * normals[other * 3 + 2];
        const limit = faces && faces[t] !== faces[other] ? faceCos : featureCos;
        state[slot] = cosine < limit ? 2 : 3;
      } else {
        state[slot] = 2;
      }
    }
  }
  let count = 0;
  for (let slot = 0; slot < size; slot++) if (state[slot] === 1 || state[slot] === 2) count++;
  const out = new Float32Array(count * 6);
  let o = 0;
  for (let slot = 0; slot < size; slot++) {
    if (state[slot] !== 1 && state[slot] !== 2) continue;
    const lo = Math.floor(keys[slot] / vertexCount);
    const hi = keys[slot] - lo * vertexCount;
    out.set(positions.subarray(lo * 3, lo * 3 + 3), o);
    out.set(positions.subarray(hi * 3, hi * 3 + 3), o + 3);
    o += 6;
  }
  return out;
}

/** The first vertex at each quantized position stands for all of them. */
function weldVertices(positions) {
  const vertexCount = positions.length / 3;
  const { min, max } = bounds(positions, null);
  const span = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2]) || 1;
  const step = span * 1e-6;
  const quantized = new Int32Array(positions.length);
  for (let i = 0; i < positions.length; i++)
    quantized[i] = Math.round((positions[i] - min[i % 3]) / step);
  const size = nextPower(vertexCount * 2);
  const mask = size - 1;
  const table = new Int32Array(size).fill(-1);
  const weld = new Int32Array(vertexCount);
  for (let v = 0; v < vertexCount; v++) {
    const x = quantized[v * 3];
    const y = quantized[v * 3 + 1];
    const z = quantized[v * 3 + 2];
    let slot = (Math.imul(x, 73856093) ^ Math.imul(y, 19349663) ^ Math.imul(z, 83492791)) & mask;
    for (;;) {
      const found = table[slot];
      if (found === -1) {
        table[slot] = v;
        weld[v] = v;
        break;
      }
      if (
        quantized[found * 3] === x &&
        quantized[found * 3 + 1] === y &&
        quantized[found * 3 + 2] === z
      ) {
        weld[v] = found;
        break;
      }
      slot = (slot + 1) & mask;
    }
  }
  return weld;
}
