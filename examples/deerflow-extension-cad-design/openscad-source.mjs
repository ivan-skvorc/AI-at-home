// Split openscad-wasm-prebuilt's single module into the two things this
// package ships: the raw WebAssembly bytes (served as their own asset) and the
// Emscripten runtime without the 11 MB base64 literal (bundled into the Worker).
import { fileURLToPath } from "node:url";
import { readFile } from "node:fs/promises";

const INLINE = /_loadWasmModule\(0, null, '([A-Za-z0-9+/=]+)'/;
const EXPORT = /export\s*\{\s*createOpenSCAD\s*\};?\s*$/;

/** The path of the package's one module, resolved from this package. */
export function openscadModulePath() {
  return fileURLToPath(
    new URL(
      "./node_modules/openscad-wasm-prebuilt/dist/openscad.js",
      import.meta.url,
    ),
  );
}

export async function readOpenscadModule() {
  return readFile(openscadModulePath(), "utf8");
}

/** The inlined WebAssembly binary as bytes; fails unless it is one. */
export function extractWasm(source) {
  const match = INLINE.exec(source);
  if (!match) throw new Error("openscad-wasm-prebuilt: inlined wasm not found");
  const bytes = Buffer.from(match[1], "base64");
  if (bytes.readUInt32LE(0) !== 0x6d736100)
    throw new Error("openscad-wasm-prebuilt: not a wasm binary");
  return new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
}

const NO_NETWORK =
  'function __cadDesignNoNetwork() { throw new Error("The OpenSCAD worker has no network"); }\n';

/**
 * The Emscripten factory `OpenSCAD` as an ES module, with the base64 literal
 * removed: the Worker is handed the bytes and instantiates them itself. Its
 * fetch and XMLHttpRequest paths (file loading the Worker never uses) are
 * replaced by a function that throws, so the bundle holds no network call.
 */
export function runtimeSource(source) {
  if (!INLINE.test(source) || !EXPORT.test(source))
    throw new Error("openscad-wasm-prebuilt: unexpected module layout");
  if (!/\bvar OpenSCAD = \(\(\) =>/.test(source))
    throw new Error("openscad-wasm-prebuilt: factory not found");
  const stripped = source
    .replace(INLINE, "_loadWasmModule(0, null, ''")
    .replace(EXPORT, "export { OpenSCAD };\n")
    .replace(/\bfetch\(/g, "__cadDesignNoNetwork(")
    .replace(/\bnew XMLHttpRequest\(\)/g, "__cadDesignNoNetwork()");
  if (/\bfetch\(|XMLHttpRequest\(|importScripts|\bimport\s*\(/.test(stripped))
    throw new Error(
      "openscad-wasm-prebuilt: a network path is left in the runtime",
    );
  return NO_NETWORK + stripped;
}
