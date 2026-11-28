// The built package against the host's asset rules (browser_assets.py):
// manifest-listed files only, each under 4 MiB, the package under 16 MiB.
import assert from "node:assert/strict";
import { readdir, readFile, stat } from "node:fs/promises";
import test from "node:test";

const root = new URL("../deerflow_extension_cad_design/", import.meta.url);
const manifest = JSON.parse(
  await readFile(new URL("ui_manifest.json", root), "utf8"),
);
const read = (file) => readFile(new URL(file, root));

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
    assert.match(file, /^static\/dist\/[A-Za-z0-9_./-]+\.mjs$/);
    const { size } = await stat(new URL(file, root));
    assert.ok(size < 4 * 1024 * 1024, `${file} is ${size} bytes`);
    total += size;
  }
  assert.ok(total < 16 * 1024 * 1024, `package is ${total} bytes`);
});

test("the model Worker is one module that fetches and imports nothing", async () => {
  const worker = (await read("static/dist/chunks/model-worker.mjs")).toString(
    "utf8",
  );
  assert.doesNotMatch(
    worker,
    /\bimport\s*[("'{*]|\bfetch\(|importScripts|XMLHttpRequest\(/,
  );
});

test("code that resolves the Worker URL sits next to it in chunks/", async () => {
  for (const file of manifest.files.filter((f) => f.endsWith(".mjs"))) {
    const code = (await read(file)).toString("utf8");
    if (
      /model-worker\.mjs/.test(code) &&
      file !== "static/dist/chunks/model-worker.mjs"
    )
      assert.match(file, /^static\/dist\/chunks\//, file);
  }
});

test("the bundle ships no WebAssembly or code editor (the package is MIT)", async () => {
  assert.ok(!manifest.files.some((file) => /wasm|scad/i.test(file)));
  const code = (
    await Promise.all(manifest.files.map((file) => read(file)))
  ).join("\n");
  assert.doesNotMatch(code, /WebAssembly\.instantiate|@codemirror/);
});
