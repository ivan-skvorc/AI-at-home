import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { gzipSync } from "node:zlib";

import { loadWasm } from "../ui/wasm-loader.js";

const RAW = new Uint8Array([
  0,
  0x61,
  0x73,
  0x6d,
  1,
  0,
  0,
  0,
  ...new Array(5000).fill(7),
]);
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");

function served(parts) {
  const requests = [];
  const fetchImpl = async (url) => {
    requests.push(String(url));
    const name = String(url).split("/").pop();
    if (!(name in parts)) return new Response("missing", { status: 404 });
    return new Response(parts[name]);
  };
  return { fetchImpl, requests };
}

test("gzip chunks are fetched relative to the base, verified, joined and inflated", async () => {
  const packed = gzipSync(RAW);
  const a = packed.subarray(0, 100);
  const b = packed.subarray(100);
  const info = {
    encoding: "gzip",
    bytes: RAW.length,
    sha256: sha(RAW),
    files: [
      { path: "./w.0.wasm", bytes: a.length, sha256: sha(a) },
      { path: "./w.1.wasm", bytes: b.length, sha256: sha(b) },
    ],
  };
  const { fetchImpl, requests } = served({ "w.0.wasm": a, "w.1.wasm": b });
  const bytes = await loadWasm(info, {
    base: "https://host/api/assets/chunks/x.mjs",
    fetchImpl,
  });
  assert.deepEqual(bytes, RAW);
  assert.deepEqual(requests, [
    "https://host/api/assets/chunks/w.0.wasm",
    "https://host/api/assets/chunks/w.1.wasm",
  ]);
});

test("a changed byte fails the check before anything is inflated", async () => {
  const packed = gzipSync(RAW);
  const info = {
    encoding: "gzip",
    bytes: RAW.length,
    sha256: sha(RAW),
    files: [{ path: "./w.wasm", bytes: packed.length, sha256: sha(packed) }],
  };
  const tampered = Uint8Array.from(packed);
  tampered[20] ^= 1;
  const { fetchImpl } = served({ "w.wasm": tampered });
  await assert.rejects(
    loadWasm(info, { base: "https://host/a/b.mjs", fetchImpl }),
    { code: "integrity" },
  );
});

test("a missing asset and a missing build-time record both fail clearly", async () => {
  const { fetchImpl } = served({});
  const info = {
    encoding: "raw",
    bytes: RAW.length,
    sha256: sha(RAW),
    files: [{ path: "./w.wasm", bytes: RAW.length, sha256: sha(RAW) }],
  };
  await assert.rejects(
    loadWasm(info, { base: "https://host/a/b.mjs", fetchImpl }),
    { code: "unavailable" },
  );
  await assert.rejects(
    loadWasm(null, { base: "https://host/a/b.mjs", fetchImpl }),
    { code: "unavailable" },
  );
});
