import { readFile } from "node:fs/promises";
import path from "node:path";

import type { Page, Route } from "@playwright/test";

export const cadDesignPackage = path.resolve(
  "../examples/deerflow-extension-cad-design/deerflow_extension_cad_design",
);
const cadFixtures = path.resolve("tests/e2e/fixtures/cad-preview");

/** The actions the package registers (actions.py ACTIONS). */
const ACTIONS = [
  "list_designs",
  "create_design",
  "get_design",
  "rename_design",
  "delete_design",
  "restore_design",
  "purge_design",
  "prompt",
  "messages",
  "run_status",
  "cancel",
];

export const FOLDER = "/mnt/user-data/outputs/design";
export const RENDER_COMMAND = `python3 /mnt/skills/public/cad-modeling/scripts/cadkit.py render /mnt/user-data/workspace/design/model.scad --design ${FOLDER} --print-layout`;
/** What the mocked model says when it answers without rendering. */
export const TEXT_ANSWER = "Which bolt size should the holes take?";
export const SCAD = `BODIES = ["plate", "peg"];
part = "plate";
if (part == "plate") cube([60, 40, 6], center = true);
if (part == "peg") translate([0, 0, 3]) cube([10, 10, 20]);
`;

/** A 1x1 PNG: the stand-in for cadkit's shaded and section views. */
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

/** A closed binary STL box from `min` to `max`, in millimetres. */
export function boxStl(min: number[], max: number[]) {
  const [x0, y0, z0] = min as [number, number, number];
  const [x1, y1, z1] = max as [number, number, number];
  const p = (x: number, y: number, z: number) => [x, y, z];
  const quads = [
    [p(x0, y0, z0), p(x0, y1, z0), p(x1, y1, z0), p(x1, y0, z0)],
    [p(x0, y0, z1), p(x1, y0, z1), p(x1, y1, z1), p(x0, y1, z1)],
    [p(x0, y0, z0), p(x1, y0, z0), p(x1, y0, z1), p(x0, y0, z1)],
    [p(x0, y1, z0), p(x0, y1, z1), p(x1, y1, z1), p(x1, y1, z0)],
    [p(x0, y0, z0), p(x0, y0, z1), p(x0, y1, z1), p(x0, y1, z0)],
    [p(x1, y0, z0), p(x1, y1, z0), p(x1, y1, z1), p(x1, y0, z1)],
  ];
  const triangles = quads.flatMap(([a, b, c, d]) => [
    [a, b, c],
    [a, c, d],
  ]);
  const bytes = Buffer.alloc(84 + 50 * triangles.length);
  bytes.writeUInt32LE(triangles.length, 80);
  triangles.forEach((corners, index) =>
    corners.flat().forEach((value, k) => {
      bytes.writeFloatLE(value!, 84 + 50 * index + 12 + 4 * k);
    }),
  );
  return bytes;
}

/** report.json as cadkit.py render writes it for the plate and the peg. */
function report(version: number, seconds = 2.5) {
  return {
    version: `v${version}`,
    model: "/mnt/user-data/workspace/design/model.scad",
    defines: [],
    bodies: {
      plate: {
        file: "plate.stl",
        size_mm: [60, 40, 6],
        min_mm: [-30, -20, -3],
        max_mm: [30, 20, 3],
        triangles: 340,
        watertight: true,
        shells: 1,
        area_mm2: 6100.5,
        volume_mm3: 14249.2,
        solid_mass_g_pla: 17.7,
      },
      peg: {
        file: "peg.stl",
        size_mm: [10, 10, 20 + version],
        min_mm: [0, 0, 3],
        max_mm: [10, 10, 23 + version],
        triangles: 12,
        watertight: true,
        shells: 1,
        area_mm2: 1000,
        volume_mm3: 2000,
        solid_mass_g_pla: 2.5,
      },
    },
    warnings: ["peg: WARNING: Ignoring unknown variable 'wal'"],
    echo: [],
    seconds,
    assembled: { clashes: [], gaps: [] },
  };
}

type Tree = Map<string, { body: Buffer; modified: string }>;

export type Design = {
  id: string;
  title: string;
  thread_id: string;
  run_id: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};

export type ActionCall = { action: string; payload: Record<string, unknown> };

let counter = 0;
/** The store's ids: 32 lowercase hex. */
const hexId = () => (++counter).toString(16).padStart(32, "0");
const now = () => new Date().toISOString();

/**
 * The package's backend actions over an in-memory store, and each design
 * thread's output tree as the host's file routes serve it. A prompt plays the
 * part of the model: with `render` on, it writes the next version folder the
 * way cadkit.py does and the joined stream carries the bash call and its result.
 */
export class DesignBackend {
  designs = new Map<string, Design>();
  trees = new Map<string, Tree>();
  calls: ActionCall[] = [];
  fileRequests: string[] = [];
  streams = new Map<string, string>();
  /** The design thread's history as the `messages` action simplifies it. */
  history: Record<string, unknown>[] = [];
  /** Whether the host runs sandbox containers (HostPolicySnapshot.sandbox_container). */
  container = true;
  /** False: the next prompt answers in text and makes no version. */
  render = true;
  /**
   * True: run_status keeps answering "running" after the joined stream has
   * ended, so the page is still following the run until the test sets it back.
   */
  holdRun = false;

  /** A design with `versions` rendered folders already in its thread. */
  async seed(title: string, versions = 1) {
    const design = this.newDesign(title);
    for (let i = 0; i < versions; i++) await this.writeVersion(design);
    return design;
  }

  calledWith(action: string) {
    return this.calls.filter((call) => call.action === action);
  }

  private newDesign(title: string) {
    const id = hexId();
    const design: Design = {
      id,
      title,
      thread_id: `thread-${id.slice(-8)}`,
      run_id: null,
      created_at: now(),
      updated_at: now(),
      deleted_at: null,
    };
    this.designs.set(id, design);
    this.trees.set(design.thread_id, new Map());
    return design;
  }

  /** The next v<N> folder, as cadkit render, check, views and print leave it. */
  async writeVersion(design: Design) {
    const tree = this.trees.get(design.thread_id)!;
    const numbers = [...tree.keys()]
      .map((key) => /^\/mnt\/user-data\/outputs\/design\/v(\d+)\//.exec(key))
      .filter((match) => match)
      .map((match) => Number(match![1]));
    const n = Math.max(0, ...numbers) + 1;
    const base = `${FOLDER}/v${n}`;
    const plate = await readFile(path.join(cadFixtures, "mounting-plate.stl"));
    const put = (name: string, body: Buffer | string) =>
      tree.set(`${base}/${name}`, {
        body: typeof body === "string" ? Buffer.from(body) : body,
        modified: now(),
      });
    const json = (value: unknown) => JSON.stringify(value, null, 2);
    put("model.scad", SCAD);
    put("plate.stl", plate);
    put("peg.stl", boxStl([0, 0, 3], [10, 10, 23 + n]));
    put("assembly.glb", Buffer.alloc(16));
    put("report.json", json(report(n)));
    put(
      "check.json",
      json({
        version: `v${n}`,
        clearance_mm: 0.3,
        states: 13,
        clashes: 1,
        results: [
          {
            pose: "swing",
            state: "peg=30",
            clashes: [
              { pair: ["peg", "plate"], overlap_mm3: 1.25, where: "x 0..1" },
            ],
            gaps: [],
          },
        ],
      }),
    );
    put("views/shaded.png", PNG);
    put("views/sections.png", PNG);
    put("print/plate.stl", plate);
    put("print/report.json", json({ ...report(n), version: `v${n}/print` }));
    put(
      "print/print.json",
      json({
        version: `v${n}/print`,
        bed_mm: [220, 220, 250],
        layout_mm: [80, 40, 6],
        problems: ["peg: bridge spans 14 mm (> 10) at x 0..14"],
        slicer: {
          filament_g: "21.3",
          time: "1h 2m",
          settings: "0.4 mm nozzle, 0.2 mm layers, 2 perimeters",
          gcode: "print.gcode",
        },
      }),
    );
    put("print/print.gcode", "; gcode\n");
    design.updated_at = now();
    return n;
  }

  private design(payload: Record<string, unknown>) {
    const design = this.designs.get(String(payload.design_id));
    if (!design) throw new Error("design unavailable");
    return design;
  }

  async handle(
    action: string,
    payload: Record<string, unknown>,
  ): Promise<unknown> {
    switch (action) {
      case "list_designs":
        return {
          designs: [...this.designs.values()]
            .filter((d) => !!d.deleted_at === !!payload.trash)
            .map(({ id, title, updated_at, deleted_at }) => ({
              id,
              title,
              updated_at,
              deleted_at,
            })),
          container: this.container,
        };
      case "create_design":
        return { design: this.newDesign("Untitled design") };
      case "get_design":
        return {
          design: this.design(payload),
          folder: FOLDER,
          container: this.container,
        };
      case "prompt": {
        const design = this.design(payload);
        const runId = `run-${hexId().slice(-8)}`;
        design.run_id = runId;
        this.history.push({
          id: `human-${runId}`,
          role: "user",
          text: payload.text,
        });
        if (!this.render) {
          this.streams.set(runId, answerStream(runId));
          this.history.push({
            id: `ai-${runId}`,
            role: "assistant",
            text: TEXT_ANSWER,
          });
          return { run_id: runId, thread_id: design.thread_id };
        }
        // The model's part: render the next version in the container.
        const n = await this.writeVersion(design);
        this.streams.set(runId, renderStream(runId, n));
        this.history.push(
          {
            id: `ai-${runId}`,
            role: "assistant",
            text: "Rendering the plate and the peg.",
            tool_calls: [{ name: "bash", summary: RENDER_COMMAND }],
          },
          {
            id: `tool-${runId}`,
            role: "tool",
            tool_name: "bash",
            text: `v${n}: 2/2 bodies rendered in 2.5 s`,
          },
          {
            id: `ai-${runId}-end`,
            role: "assistant",
            text: `v${n} is ready.`,
          },
        );
        return { run_id: runId, thread_id: design.thread_id };
      }
      case "run_status": {
        const design = this.design(payload);
        if (this.holdRun) return { status: "running" };
        if (design.run_id === payload.run_id) design.run_id = null;
        return { status: "success" };
      }
      case "messages":
        return { messages: this.history };
      case "rename_design": {
        const design = this.design(payload);
        design.title = String(payload.title);
        return { design };
      }
      default:
        throw new Error(`unexpected action ${action}`);
    }
  }

  /** GET /api/threads/{tid}/files?path=: one directory of the thread's tree. */
  list(threadId: string, folder: string) {
    const tree = this.trees.get(threadId);
    if (!tree) return null;
    const children = new Map<string, Record<string, unknown>>();
    for (const [key, file] of tree) {
      if (!key.startsWith(`${folder}/`)) continue;
      const [name, ...rest] = key.slice(folder.length + 1).split("/");
      const child = `${folder}/${name}`;
      children.set(
        name!,
        rest.length
          ? {
              name,
              path: child,
              kind: "directory",
              size: null,
              modified_at: null,
            }
          : {
              name,
              path: child,
              kind: "file",
              size: file.body.length,
              modified_at: file.modified,
            },
      );
    }
    if (!children.size) return null;
    return {
      path: folder,
      exists: true,
      entries: [...children.values()],
      truncated: false,
      total: children.size,
    };
  }
}

const sse = (events: { event: string; data: unknown }[]) =>
  events
    .map(
      ({ event, data }) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
    )
    .join("");

/** A joined run whose model only answers in text. */
function answerStream(runId: string) {
  return sse([
    { event: "metadata", data: { run_id: runId } },
    {
      event: "messages",
      data: [
        { type: "AIMessageChunk", id: `ai-${runId}`, content: TEXT_ANSWER },
        { langgraph_node: "model" },
      ],
    },
    { event: "end", data: null },
  ]);
}

/**
 * One joined run as the Gateway streams it for stream_mode
 * ["values", "messages-tuple"]: text, the bash call's arguments in pieces,
 * the tool's answer, the closing text, then `end`.
 */
function renderStream(runId: string, n: number) {
  const args = JSON.stringify({
    description: "Render the next version",
    command: RENDER_COMMAND,
  });
  const half = Math.floor(args.length / 2);
  const meta = { langgraph_node: "model" };
  const chunk = (fields: Record<string, unknown>, id = `ai-${runId}`) => ({
    event: "messages",
    data: [{ type: "AIMessageChunk", id, content: "", ...fields }, meta],
  });
  return sse([
    { event: "metadata", data: { run_id: runId } },
    chunk({ content: "Rendering the plate and the peg." }),
    chunk({
      tool_call_chunks: [
        {
          index: 0,
          id: "call-render",
          name: "bash",
          args: args.slice(0, half),
        },
      ],
    }),
    chunk({
      tool_call_chunks: [
        { index: 0, id: null, name: null, args: args.slice(half) },
      ],
    }),
    {
      event: "messages",
      data: [
        {
          type: "tool",
          id: `tool-${runId}`,
          tool_call_id: "call-render",
          name: "bash",
          content: `v${n}: 2/2 bodies rendered in 2.5 s`,
        },
        { langgraph_node: "tools" },
      ],
    },
    chunk({ content: `v${n} is ready.` }, `ai-${runId}-end`),
    { event: "end", data: null },
  ]);
}

const CONTENT_TYPES: Record<string, string> = {
  ".json": "application/json",
  ".png": "image/png",
  ".stl": "model/stl",
  ".scad": "text/plain",
};

/**
 * Serve the cad-design package's built module graph with the Gateway's asset
 * policy (`Content-Security-Policy: sandbox`, so the STL Worker runs in an
 * opaque origin), and answer its actions, run joins and thread file routes
 * from `backend`.
 */
export async function mockCadDesign(page: Page, backend: DesignBackend) {
  const manifest = JSON.parse(
    await readFile(path.join(cadDesignPackage, "ui_manifest.json"), "utf8"),
  ) as { entry: string; files: string[] };
  const prefix = `/api/plugins/cad-design/assets/${"d".repeat(64)}/`;
  await page.route("**/api/plugins", (route) =>
    route.fulfill({
      json: [
        {
          viewer_id: "default",
          namespace: "cad-design",
          module: "cad-design",
          entry: `${prefix}${manifest.entry}`,
          transport: "assets-v1",
          title: "CAD designs / CAD 设计",
          description: "",
          settings: { enabled: true },
          backend_actions: ACTIONS,
          model_tools: [],
        },
      ],
    }),
  );
  // Worker requests belong to the context, not to the page.
  await page
    .context()
    .route("**/api/plugins/cad-design/assets/**", async (route) => {
      const filename = new URL(route.request().url()).pathname.slice(
        prefix.length,
      );
      if (!manifest.files.includes(filename))
        return route.fulfill({ status: 404 });
      return route.fulfill({
        contentType: "text/javascript",
        headers: { "Content-Security-Policy": "sandbox" },
        body: await readFile(path.join(cadDesignPackage, filename)),
      });
    });
  await page.route(
    "**/api/plugins/cad-design/actions/*",
    async (route: Route) => {
      const action = new URL(route.request().url()).pathname.split("/").pop()!;
      const payload = (route.request().postDataJSON() ?? {}) as Record<
        string,
        unknown
      >;
      backend.calls.push({ action, payload });
      try {
        await route.fulfill({ json: await backend.handle(action, payload) });
      } catch (error) {
        await route.fulfill({
          status: 404,
          json: { detail: String((error as Error).message) },
        });
      }
    },
  );
  await page.route("**/api/threads/*/runs/*/join", (route) => {
    const runId = new URL(route.request().url()).pathname.split("/")[5]!;
    const body = backend.streams.get(runId);
    if (body === undefined) return route.fulfill({ status: 404 });
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body,
    });
  });
  await page.route(/\/api\/threads\/[^/]+\/files(?:\?|$)/, (route) => {
    const url = new URL(route.request().url());
    const threadId = decodeURIComponent(url.pathname.split("/")[3]!);
    const folder = url.searchParams.get("path") ?? "";
    backend.fileRequests.push(`list ${folder}`);
    const listing = backend.list(threadId, folder);
    return listing
      ? route.fulfill({ json: listing })
      : route.fulfill({
          status: 404,
          json: { detail: `Directory not found: ${folder}` },
        });
  });
  await page.route(/\/api\/threads\/[^/]+\/artifacts\//, (route) => {
    const url = new URL(route.request().url());
    const [, , , threadId, , ...rest] = url.pathname.split("/");
    const file = `/${rest.map(decodeURIComponent).join("/")}`;
    backend.fileRequests.push(
      `read ${file}${url.searchParams.get("download") ? " (download)" : ""}`,
    );
    const found = backend.trees.get(decodeURIComponent(threadId!))?.get(file);
    if (!found) return route.fulfill({ status: 404 });
    return route.fulfill({
      contentType:
        CONTENT_TYPES[path.extname(file)] ?? "application/octet-stream",
      body: found.body,
    });
  });
}
