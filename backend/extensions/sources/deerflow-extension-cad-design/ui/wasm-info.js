// build.mjs defines __CAD_DESIGN_WASM__: the wasm asset paths, sizes and SHA-256s.
/* global __CAD_DESIGN_WASM__ */
export const WASM_INFO =
  typeof __CAD_DESIGN_WASM__ === "undefined" ? null : __CAD_DESIGN_WASM__;
