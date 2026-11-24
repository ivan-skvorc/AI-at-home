// Fetch the OpenSCAD WebAssembly asset(s) from the page (host origin), check
// each against the SHA-256 recorded at build time, join and inflate them.
//
// The check must not depend on crypto.subtle: browsers expose it only in
// secure contexts, and this page is also opened over plain http on a LAN or
// tailnet address. There the hash is computed in JavaScript (sha256.js).

import { sha256Hex } from "./sha256.js";

export class WasmLoadError extends Error {
  constructor(code) {
    super(code);
    this.name = "WasmLoadError";
    this.code = code;
  }
}

async function sha256(bytes, subtle) {
  if (!subtle) return sha256Hex(bytes);
  const digest = new Uint8Array(await subtle.digest("SHA-256", bytes));
  return [...digest].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function inflate(bytes) {
  const stream = new Blob([bytes])
    .stream()
    .pipeThrough(new DecompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/**
 * `info` is the build's record: `{encoding: "gzip"|"raw", bytes, sha256,
 * files: [{path, bytes, sha256}]}`, paths relative to `base` (the URL of the
 * module that holds the record).
 */
export async function loadWasm(
  info,
  {
    base,
    fetchImpl = globalThis.fetch,
    signal,
    subtle = globalThis.crypto?.subtle,
  } = {},
) {
  if (!info || !Array.isArray(info.files) || !info.files.length)
    throw new WasmLoadError("unavailable");
  const parts = await Promise.all(
    info.files.map(async (file) => {
      let response;
      try {
        response = await fetchImpl(new URL(file.path, base), {
          signal,
          credentials: "same-origin",
        });
      } catch (error) {
        if (signal?.aborted) throw error;
        throw new WasmLoadError("unavailable");
      }
      if (!response.ok) throw new WasmLoadError("unavailable");
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (
        bytes.length !== file.bytes ||
        (await sha256(bytes, subtle)) !== file.sha256
      )
        throw new WasmLoadError("integrity");
      return bytes;
    }),
  );
  const joined = new Uint8Array(
    parts.reduce((sum, part) => sum + part.length, 0),
  );
  let offset = 0;
  for (const part of parts) {
    joined.set(part, offset);
    offset += part.length;
  }
  let raw;
  try {
    raw = info.encoding === "gzip" ? await inflate(joined) : joined;
  } catch {
    throw new WasmLoadError("integrity");
  }
  if (raw.length !== info.bytes || (await sha256(raw, subtle)) !== info.sha256)
    throw new WasmLoadError("integrity");
  return raw;
}
