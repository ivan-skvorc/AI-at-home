import { build } from "esbuild";
import { readdir, rm, stat, writeFile } from "node:fs/promises";

const root = "deerflow_extension_cad_preview";
// Gateway serves at most 4 MiB per asset; stay well under it.
const ASSET_LIMIT = 3 * 1024 * 1024;
await rm(new URL(`./${root}/static/dist/`, import.meta.url), {
  recursive: true,
  force: true,
});
await build({
  entryPoints: { index: "ui/index.js" },
  bundle: true,
  splitting: true,
  format: "esm",
  platform: "browser",
  target: "es2022",
  outdir: `${root}/static/dist`,
  entryNames: "[dir]/[name]",
  chunkNames: "chunks/[name]-[hash]",
  outExtension: { ".js": ".mjs" },
  minify: true,
  legalComments: "eof",
});
// Gateway assets carry CSP: sandbox. The Worker runs in an opaque origin and
// cannot fetch further chunks, so it is bundled as one self-contained module.
await build({
  entryPoints: ["ui/model-worker.js"],
  bundle: true,
  format: "esm",
  platform: "browser",
  target: "es2022",
  outfile: `${root}/static/dist/chunks/model-worker.mjs`,
  minify: true,
  legalComments: "eof",
});
const files = (await readdir(`${root}/static/dist`, { recursive: true }))
  .filter((p) => /\.mjs$/.test(p))
  .map((p) => `static/dist/${p.replaceAll("\\", "/")}`)
  .sort();
for (const file of files) {
  const { size } = await stat(`${root}/${file}`);
  if (size > ASSET_LIMIT) throw new Error(`${file} is ${size} bytes, over ${ASSET_LIMIT}`);
}
await writeFile(
  `${root}/ui_manifest.json`,
  JSON.stringify({ schema_version: 1, entry: "static/dist/index.mjs", files }, null, 2) + "\n",
);
