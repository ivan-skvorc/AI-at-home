import { createHash } from "node:crypto";
import { mkdir, readdir, rm, stat, writeFile } from "node:fs/promises";
import { gzipSync } from "node:zlib";

import { build } from "esbuild";

import {
  extractWasm,
  readOpenscadModule,
  runtimeSource,
} from "./openscad-source.mjs";

const root = "deerflow_extension_cad_design";
const dist = `${root}/static/dist`;
// browser_assets.py: 4 MiB per file, 16 MiB per package.
const FILE_LIMIT = 4 * 1024 * 1024;
const PACKAGE_LIMIT = 16 * 1024 * 1024;
// The compressed wasm is split at this size when it outgrows one file.
const WASM_CHUNK = 3.5 * 1024 * 1024;
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

await rm(new URL(`./${dist}/`, import.meta.url), {
  recursive: true,
  force: true,
});
await mkdir(`${dist}/chunks`, { recursive: true });

// OpenSCAD ships as one 11 MB module with the wasm inlined as base64. The raw
// bytes become a gzip asset (served as .wasm, an allowed type) that the page
// verifies and inflates; the runtime without the literal goes into the Worker.
const openscad = await readOpenscadModule();
const wasm = extractWasm(openscad);
const packed = gzipSync(wasm, { level: 9 });
const pieces = [];
for (let offset = 0; offset < packed.length; offset += WASM_CHUNK)
  pieces.push(packed.subarray(offset, offset + WASM_CHUNK));
const wasmInfo = {
  encoding: "gzip",
  bytes: wasm.length,
  sha256: sha256(wasm),
  files: [],
};
for (const [index, piece] of pieces.entries()) {
  const name =
    pieces.length === 1 ? "openscad.gz.wasm" : `openscad.${index}.gz.wasm`;
  await writeFile(`${dist}/chunks/${name}`, piece);
  wasmInfo.files.push({
    path: `./${name}`,
    bytes: piece.length,
    sha256: sha256(piece),
  });
}

const common = {
  bundle: true,
  format: "esm",
  platform: "browser",
  target: "es2022",
  minify: true,
  legalComments: "eof",
  logLevel: "warning",
};
await build({
  ...common,
  entryPoints: { index: "ui/index.js" },
  splitting: true,
  outdir: dist,
  entryNames: "[dir]/[name]",
  chunkNames: "chunks/[name]-[hash]",
  outExtension: { ".js": ".mjs" },
  define: { __CAD_DESIGN_WASM__: JSON.stringify(wasmInfo) },
});
// Gateway assets carry CSP: sandbox. A Worker runs in an opaque origin and
// cannot fetch further chunks, so each is one self-contained module.
const runtime = {
  name: "openscad-runtime",
  setup(plugin) {
    plugin.onResolve({ filter: /^openscad-runtime$/ }, () => ({
      path: "openscad-runtime",
      namespace: "openscad",
    }));
    plugin.onLoad({ filter: /.*/, namespace: "openscad" }, () => ({
      contents: runtimeSource(openscad),
      loader: "js",
    }));
  },
};
await build({
  ...common,
  entryPoints: ["ui/scad-worker.js"],
  outfile: `${dist}/chunks/scad-worker.mjs`,
  plugins: [runtime],
});
// The GLB/STL parser Worker that cad-preview's worker-client.js expects next to it.
await build({
  ...common,
  entryPoints: ["../deerflow-extension-cad-preview/ui/model-worker.js"],
  outfile: `${dist}/chunks/model-worker.mjs`,
});

const files = (await readdir(dist, { recursive: true, withFileTypes: true }))
  .filter((entry) => entry.isFile())
  .map((entry) =>
    `${entry.parentPath}/${entry.name}`
      .replaceAll("\\", "/")
      .slice(root.length + 1),
  )
  .sort();
let total = 0;
for (const file of files) {
  const { size } = await stat(`${root}/${file}`);
  if (size > FILE_LIMIT)
    throw new Error(`${file} is ${size} bytes, over ${FILE_LIMIT}`);
  total += size;
}
if (total > PACKAGE_LIMIT)
  throw new Error(`the package is ${total} bytes, over ${PACKAGE_LIMIT}`);
await writeFile(
  `${root}/ui_manifest.json`,
  JSON.stringify(
    { schema_version: 1, entry: "static/dist/index.mjs", files },
    null,
    2,
  ) + "\n",
);
console.log(`${files.length} files, ${(total / 1024 / 1024).toFixed(2)} MiB`);
