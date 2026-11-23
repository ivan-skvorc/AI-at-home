// Bundled as one self-contained module with the OpenSCAD runtime (its 11 MB
// base64 literal removed by build.mjs). Plugin assets carry
// `Content-Security-Policy: sandbox`, so this Worker has an opaque origin: the
// page fetches and verifies the WebAssembly bytes and posts them here. The
// mesh is prepared here too (cad-preview's mesh.js), so a render costs the page
// one message and no further Worker or request.
import { OpenSCAD } from "openscad-runtime";

import { prepareModel } from "../../deerflow-extension-cad-preview/ui/mesh.js";
import { meshMetrics, sceneToCad } from "./metrics.js";
import { renderScad } from "./scad-engine.js";

let compiled = null;

function prepare(stl) {
  const model = prepareModel("stl", stl.slice().buffer);
  return { model, metrics: meshMetrics(sceneToCad(model.positions)) };
}

self.onmessage = async ({ data }) => {
  if (data?.type === "init") {
    try {
      compiled = WebAssembly.compile(data.wasm);
      await compiled;
      self.postMessage({ type: "ready" });
    } catch {
      compiled = null;
      self.postMessage({ type: "failed", error: "wasm" });
    }
    return;
  }
  if (data?.type !== "render" || typeof data.code !== "string") return;
  let module;
  try {
    module = await compiled;
  } catch {
    module = null;
  }
  if (!module) {
    self.postMessage({
      type: "result",
      id: data.id,
      ok: false,
      error: "OpenSCAD is not loaded",
      errorLines: [],
      warnings: [],
      log: [],
    });
    return;
  }
  const { stl: bytes, ...result } = await renderScad(
    OpenSCAD,
    module,
    data.code,
  );
  let prepared = null;
  if (result.ok) {
    try {
      prepared = prepare(bytes);
    } catch (error) {
      // Only the parser's fixed code crosses back, as in cad-preview.
      Object.assign(result, {
        ok: false,
        error: `mesh: ${error?.code ?? "invalid-file"}`,
      });
    }
  }
  const stl = prepared ? bytes.slice().buffer : null;
  const transfer = stl ? [stl] : [];
  if (prepared) {
    const { model } = prepared;
    transfer.push(model.positions.buffer, model.normals.buffer);
    if (model.edges) transfer.push(model.edges.buffer);
  }
  self.postMessage(
    {
      type: "result",
      id: data.id,
      ...result,
      stl,
      model: prepared?.model ?? null,
      metrics: prepared?.metrics ?? null,
    },
    transfer,
  );
};
