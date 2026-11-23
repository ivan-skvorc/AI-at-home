const round = (value, places = 3) => Number(value.toFixed(places));

/**
 * Size, volume and closedness of a triangle soup in the CAD frame
 * (millimetres, Z up). Manifold here means every edge is shared by exactly two
 * triangles that run it in opposite directions, after welding equal corners.
 */
export function meshMetrics(positions, indices = null) {
  const corners = indices ? indices.length : positions.length / 3;
  const triangles = Math.floor(corners / 3);
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  let volume = 0;
  const ids = new Map();
  const weld = (v) => {
    const key = `${positions[v]},${positions[v + 1]},${positions[v + 2]}`;
    let id = ids.get(key);
    if (id === undefined) {
      id = ids.size;
      ids.set(key, id);
    }
    return id;
  };
  const directed = new Map();
  for (let t = 0; t < triangles; t++) {
    const v = [0, 1, 2].map(
      (k) => (indices ? indices[t * 3 + k] : t * 3 + k) * 3,
    );
    for (const offset of v)
      for (let axis = 0; axis < 3; axis++) {
        const value = positions[offset + axis];
        if (value < min[axis]) min[axis] = value;
        if (value > max[axis]) max[axis] = value;
      }
    const [a, b, c] = v;
    const p = positions;
    volume +=
      (p[a] * (p[b + 1] * p[c + 2] - p[b + 2] * p[c + 1]) -
        p[a + 1] * (p[b] * p[c + 2] - p[b + 2] * p[c]) +
        p[a + 2] * (p[b] * p[c + 1] - p[b + 1] * p[c])) /
      6;
    const w = v.map(weld);
    for (let k = 0; k < 3; k++) {
      const from = w[k];
      const to = w[(k + 1) % 3];
      if (from === to) continue;
      const key = `${from}>${to}`;
      directed.set(key, (directed.get(key) ?? 0) + 1);
    }
  }
  let manifold = triangles > 0;
  for (const [key, count] of directed) {
    const [from, to] = key.split(">");
    if (count !== 1 || directed.get(`${to}>${from}`) !== 1) {
      manifold = false;
      break;
    }
  }
  const empty = triangles === 0;
  return {
    bbox_mm: empty ? [0, 0, 0] : max.map((value, i) => round(value - min[i])),
    bbox_min_mm: empty ? [0, 0, 0] : min.map((value) => round(value)),
    bbox_max_mm: empty ? [0, 0, 0] : max.map((value) => round(value)),
    volume_mm3: round(Math.abs(volume), 2),
    manifold,
    triangles,
  };
}

/** The viewer keeps CAD (x, y, z) as scene (x, z, -y); this undoes it on a copy. */
export function sceneToCad(positions) {
  const out = new Float32Array(positions.length);
  for (let i = 0; i < positions.length; i += 3) {
    out[i] = positions[i];
    out[i + 1] = -positions[i + 2];
    out[i + 2] = positions[i + 1];
  }
  return out;
}
