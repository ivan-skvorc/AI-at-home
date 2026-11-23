// The built package against the host's asset rules (browser_assets.py):
// manifest-listed files only, each under 4 MiB, the package under 16 MiB.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readdir, readFile, stat } from "node:fs/promises";
import test from "node:test";
import { gunzipSync } from "node:zlib";

import { extractWasm, readOpenscadModule } from "../openscad-source.mjs";

const root = new URL("../deerflow_extension_cad_design/", import.meta.url);
const manifest = JSON.parse(
  await readFile(new URL("ui_manifest.json", root), "utf8"),
);
const read = (file) => readFile(new URL(file, root));
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");

test("the manifest lists exactly the built files", async () => {
  const listed = (
    await readdir(new URL("static/", root), {
      recursive: true,
      withFileTypes: true,
    })
  )
    .filter((entry) => entry.isFile())
    .map(
      (entry) =>
        `${entry.parentPath ?? entry.path}/${entry.name}`.split(
          "/deerflow_extension_cad_design/",
        )[1],
    )
    .sort();
  assert.deepEqual(listed, [...manifest.files].sort());
  assert.ok(manifest.files.includes(manifest.entry));
  assert.equal(manifest.schema_version, 1);
});

test("every asset fits the host limits", async () => {
  let total = 0;
  for (const file of manifest.files) {
    assert.match(file, /^static\/dist\/[A-Za-z0-9_./-]+\.(mjs|wasm)$/);
    const { size } = await stat(new URL(file, root));
    assert.ok(size < 4 * 1024 * 1024, `${file} is ${size} bytes`);
    total += size;
  }
  assert.ok(total < 16 * 1024 * 1024, `package is ${total} bytes`);
});

test("the shipped wasm is the npm package's binary and its hashes are baked in", async () => {
  const parts = manifest.files.filter((file) => file.endsWith(".wasm")).sort();
  const packed = Buffer.concat(await Promise.all(parts.map(read)));
  const raw = gunzipSync(packed);
  assert.deepEqual(
    new Uint8Array(raw),
    extractWasm(await readOpenscadModule()),
  );
  const code = (
    await Promise.all(
      manifest.files.filter((f) => f.endsWith(".mjs")).map(read),
    )
  ).join("\n");
  assert.ok(code.includes(sha(raw)), "raw SHA-256 baked into the bundle");
  for (const part of parts)
    assert.ok(code.includes(sha(await read(part))), `${part} SHA-256 baked in`);
});

test("Workers are single modules that fetch and import nothing", async () => {
  for (const name of ["scad-worker.mjs", "model-worker.mjs"]) {
    const worker = (await read(`static/dist/chunks/${name}`)).toString("utf8");
    assert.doesNotMatch(
      worker,
      /\bimport\s*[("'{*]|\bfetch\(|importScripts|XMLHttpRequest\(/,
      name,
    );
  }
});

test("code that resolves Worker and wasm URLs sits next to them in chunks/", async () => {
  for (const file of manifest.files.filter((f) => f.endsWith(".mjs"))) {
    const code = (await read(file)).toString("utf8");
    if (
      /scad-worker\.mjs|model-worker\.mjs|\.gz\.wasm/.test(code) &&
      !/^static\/dist\/chunks\/(scad|model)-worker\.mjs$/.test(file)
    )
      assert.match(file, /^static\/dist\/chunks\//, file);
  }
});
