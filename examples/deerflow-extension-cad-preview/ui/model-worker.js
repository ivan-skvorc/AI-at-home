// Bundled as one self-contained module: Gateway serves plugin assets with
// `Content-Security-Policy: sandbox`, so this Worker runs in an opaque origin
// and can neither import further chunks nor fetch anything.
import { prepareModel } from "./mesh.js";

self.onmessage = ({ data }) => {
  try {
    const kind = data?.kind === "stl" ? "stl" : "glb";
    const model = prepareModel(kind, data.bytes);
    const transfer = [model.positions.buffer, model.normals.buffer];
    if (model.indices) transfer.push(model.indices.buffer);
    if (model.edges) transfer.push(model.edges.buffer);
    self.postMessage({ result: model }, transfer);
  } catch (error) {
    // Only fixed codes cross back; parser messages never reach the page.
    self.postMessage({ error: error?.code ?? "invalid-file" });
  }
};
