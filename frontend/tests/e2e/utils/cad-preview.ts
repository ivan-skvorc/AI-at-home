import { readFile } from "node:fs/promises";
import path from "node:path";
import { inflateSync } from "node:zlib";

import type { Page } from "@playwright/test";

/** Frozen files made by the retired CAD module; see the cad-preview README. */
export const cadFixtures = path.resolve("tests/e2e/fixtures/cad-preview");
export const cadPackage = path.resolve(
  "../examples/deerflow-extension-cad-preview/deerflow_extension_cad_preview",
);

/**
 * Serve the packaged module graph with the Gateway's asset policy, so the
 * model Worker runs in the same opaque origin it gets in production.
 */
export async function mockCadPreview(
  page: Page,
  { plugins = "enabled" }: { plugins?: "enabled" | "disabled" | "none" } = {},
) {
  const manifest = JSON.parse(
    await readFile(path.join(cadPackage, "ui_manifest.json"), "utf8"),
  ) as { entry: string; files: string[] };
  const prefix = `/api/plugins/cad-preview/assets/${"c".repeat(64)}/`;
  await page.route("**/api/plugins", (route) =>
    route.fulfill({
      json:
        plugins === "none"
          ? []
          : [
              {
                viewer_id: "default",
                namespace: "cad-preview",
                module: "cad-preview",
                entry: `${prefix}${manifest.entry}`,
                transport: "assets-v1",
                title: "CAD model preview",
                description: "",
                settings: { enabled: plugins === "enabled" },
              },
            ],
    }),
  );
  // Worker requests belong to the context, not to the page.
  await page
    .context()
    .route("**/api/plugins/cad-preview/assets/**", async (route) => {
      const filename = new URL(route.request().url()).pathname.slice(
        prefix.length,
      );
      if (!manifest.files.includes(filename))
        return route.fulfill({ status: 404 });
      return route.fulfill({
        contentType: "text/javascript",
        headers: { "Content-Security-Policy": "sandbox" },
        body: await readFile(path.join(cadPackage, filename)),
      });
    });
}

/**
 * Three vertices and 1,000,001 triangles of one-byte indices: about 3 MB that
 * would ask for 12 MB of indices and more for edges if counts were not checked
 * before allocation.
 */
export function amplifyingGlb() {
  const corners = 3 * 1_000_001;
  const positions = Buffer.alloc(36);
  [0, 0, 0, 1, 0, 0, 0, 1, 0].forEach((value, i) =>
    positions.writeFloatLE(value, i * 4),
  );
  const indices = Buffer.alloc(corners + ((4 - (corners % 4)) % 4));
  for (let i = 0; i < corners; i++) indices[i] = i % 3;
  const bin = Buffer.concat([positions, indices]);
  const json = Buffer.from(
    JSON.stringify({
      asset: { version: "2.0" },
      scene: 0,
      scenes: [{ nodes: [0] }],
      nodes: [{ mesh: 0 }],
      meshes: [{ primitives: [{ attributes: { POSITION: 0 }, indices: 1 }] }],
      buffers: [{ byteLength: bin.length }],
      bufferViews: [
        { buffer: 0, byteOffset: 0, byteLength: 36 },
        { buffer: 0, byteOffset: 36, byteLength: corners },
      ],
      accessors: [
        { bufferView: 0, componentType: 5126, count: 3, type: "VEC3" },
        { bufferView: 1, componentType: 5121, count: corners, type: "SCALAR" },
      ],
    }),
  );
  const text = Buffer.concat([
    json,
    Buffer.alloc((4 - (json.length % 4)) % 4, 0x20),
  ]);
  const header = Buffer.alloc(12);
  const total = 12 + 8 + text.length + 8 + bin.length;
  header.writeUInt32LE(0x46546c67, 0);
  header.writeUInt32LE(2, 4);
  header.writeUInt32LE(total, 8);
  const chunk = (type: number, body: Buffer) => {
    const head = Buffer.alloc(8);
    head.writeUInt32LE(body.length, 0);
    head.writeUInt32LE(type, 4);
    return Buffer.concat([head, body]);
  };
  return Buffer.concat([
    header,
    chunk(0x4e4f534a, text),
    chunk(0x004e4942, bin),
  ]);
}

/** One RGB pixel of an 8-bit, non-interlaced PNG such as a Playwright screenshot. */
export function pngPixel(png: Buffer, x: number, y: number) {
  return pngRow(png, y)[x]!;
}

/** The RGB pixels of row `y` of an 8-bit, non-interlaced PNG, left to right. */
export function pngRow(png: Buffer, y: number) {
  const width = png.readUInt32BE(16);
  const colorType = png[25]!;
  const channels = colorType === 6 ? 4 : colorType === 2 ? 3 : 0;
  if (png[24] !== 8 || !channels || png[28] !== 0)
    throw new Error("Unsupported PNG layout");
  const parts: Buffer[] = [];
  for (let offset = 8; offset < png.length; ) {
    const length = png.readUInt32BE(offset);
    if (png.toString("ascii", offset + 4, offset + 8) === "IDAT")
      parts.push(png.subarray(offset + 8, offset + 8 + length));
    offset += 12 + length;
  }
  const raw = inflateSync(Buffer.concat(parts));
  const stride = width * channels;
  let previous = Buffer.alloc(stride);
  let row = previous;
  for (let line = 0; line <= y; line++) {
    const start = line * (stride + 1);
    const filter = raw[start]!;
    row = Buffer.alloc(stride);
    for (let i = 0; i < stride; i++) {
      const value = raw[start + 1 + i]!;
      const left = i >= channels ? row[i - channels]! : 0;
      const up = previous[i]!;
      const corner = i >= channels ? previous[i - channels]! : 0;
      const p = left + up - corner;
      const [pa, pb, pc] = [p - left, p - up, p - corner].map(Math.abs);
      const paeth = pa! <= pb! && pa! <= pc! ? left : pb! <= pc! ? up : corner;
      row[i] = (value + [0, left, up, (left + up) >> 1, paeth][filter]!) & 0xff;
    }
    previous = row;
  }
  return Array.from({ length: width }, (_, x) => [
    ...row.subarray(x * channels, x * channels + 3),
  ]);
}
