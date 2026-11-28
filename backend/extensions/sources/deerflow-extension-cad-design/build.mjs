import { mkdir, readdir, rm, stat, writeFile } from "node:fs/promises";

import { build } from "esbuild";

const root = "deerflow_extension_cad_design";
const dist = `${root}/static/dist`;
// browser_assets.py: 4 MiB per file, 16 MiB per package.
const FILE_LIMIT = 4 * 1024 * 1024;
const PACKAGE_LIMIT = 16 * 1024 * 1024;

await rm(new URL(`./${dist}/`, import.meta.url), {
  recursive: true,
  force: true,
});
await mkdir(`${dist}/chunks`, { recursive: true });

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
});
// The STL parser Worker that cad-preview's worker-client.js expects next to it.
// Gateway assets carry CSP: sandbox, so the Worker runs in an opaque origin and
// cannot fetch further chunks: it is one self-contained module.
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
