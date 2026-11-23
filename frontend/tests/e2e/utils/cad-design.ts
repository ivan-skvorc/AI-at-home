import { readFile } from "node:fs/promises";
import path from "node:path";

import type { BrowserContext, Page, Route } from "@playwright/test";

export const cadDesignPackage = path.resolve(
  "../examples/deerflow-extension-cad-design/deerflow_extension_cad_design",
);

/** The actions the package registers (actions.py ACTIONS). */
const ACTIONS = [
  "list_designs",
  "create_design",
  "get_design",
  "get_version",
  "rename_design",
  "delete_design",
  "restore_design",
  "purge_design",
  "save_version",
  "report_render",
  "set_head",
  "prompt",
  "repair",
  "finalize",
  "messages",
  "run_status",
  "cancel",
];

/** The host binds the tool as ext_<namespace>_<name>_<12 hex>. */
export const BOUND_SCAD_DRAFT = "ext_cad_design_scad_draft_0123456789ab";

export type Render = {
  ok: boolean;
  partial?: boolean;
  error?: string;
  error_lines?: number[];
  bbox_mm?: number[];
  volume_mm3?: number;
  manifold?: boolean;
  triangles?: number;
};

export type Version = {
  id: string;
  design_id: string;
  parent_id: string | null;
  seq: number;
  source: string;
  scad: string;
  params: Record<string, unknown>;
  render: Render | null;
  final: null;
  run_id: string | null;
  repair_requested: boolean;
  created_at: string;
};

export type Design = {
  id: string;
  title: string;
  thread_id: string;
  head_version_id: string | null;
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
 * The package's backend actions over an in-memory store. A prompt plays the
 * part of the model: `scad_draft` stores `draft` as a version and the run's
 * joined stream carries the call as messages-tuple tool_call_chunks.
 */
export class DesignBackend {
  designs = new Map<string, Design>();
  versions: Version[] = [];
  calls: ActionCall[] = [];
  streams = new Map<string, string>();
  /** The design thread's history as the `messages` action simplifies it. */
  history: Record<string, unknown>[] = [];
  /** The file the mocked model writes on the next prompt. */
  draft = "";

  seed(title: string, scad: string, render: Render | null = null) {
    const design = this.newDesign(title);
    const version = this.addVersion(design, scad, "model");
    version.render = render;
    return { design, version };
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
      head_version_id: null,
      run_id: null,
      created_at: now(),
      updated_at: now(),
      deleted_at: null,
    };
    this.designs.set(id, design);
    return design;
  }

  private addVersion(
    design: Design,
    scad: string,
    source: string,
    parent: string | null = design.head_version_id,
  ) {
    const version: Version = {
      id: hexId(),
      design_id: design.id,
      parent_id: parent,
      seq: this.versionsOf(design.id).length + 1,
      source,
      scad,
      params: {},
      render: null,
      final: null,
      run_id: null,
      repair_requested: false,
      created_at: now(),
    };
    this.versions.push(version);
    design.head_version_id = version.id;
    design.updated_at = now();
    return version;
  }

  private versionsOf(designId: string) {
    return this.versions.filter((v) => v.design_id === designId);
  }

  private design(payload: Record<string, unknown>) {
    const design = this.designs.get(String(payload.design_id));
    if (!design) throw new Error("design unavailable");
    return design;
  }

  private version(payload: Record<string, unknown>) {
    const version = this.versions.find((v) => v.id === payload.version_id);
    if (!version) throw new Error("version unavailable");
    return version;
  }

  handle(action: string, payload: Record<string, unknown>): unknown {
    switch (action) {
      case "list_designs":
        return {
          designs: [...this.designs.values()]
            .filter((d) => !!d.deleted_at === !!payload.trash)
            .map((d) => ({
              id: d.id,
              title: d.title,
              updated_at: d.updated_at,
              versions: this.versionsOf(d.id).length,
              thumbnail: null,
              deleted_at: d.deleted_at,
            })),
        };
      case "create_design":
        return { design: this.newDesign("Untitled design") };
      case "get_design": {
        const design = this.design(payload);
        return { design, versions: this.versionsOf(design.id) };
      }
      case "get_version":
        return { version: this.version(payload) };
      case "save_version": {
        const design = this.design(payload);
        return {
          version: this.addVersion(
            design,
            String(payload.scad),
            String(payload.source),
            (payload.parent_id as string | null) ?? null,
          ),
        };
      }
      case "report_render": {
        const version = this.version(payload);
        version.render = payload.render as Render;
        return { version };
      }
      case "set_head": {
        const design = this.design(payload);
        design.head_version_id = this.version(payload).id;
        return { design };
      }
      case "prompt": {
        const design = this.design(payload);
        const runId = `run-${hexId().slice(-8)}`;
        // The tool's part: store the whole file as the new head.
        const version = this.addVersion(design, this.draft, "model");
        version.run_id = runId;
        design.run_id = runId;
        this.streams.set(runId, draftStream(this.draft, version));
        this.history.push(
          { id: `human-${runId}`, role: "user", text: payload.text },
          {
            id: "ai-draft",
            role: "assistant",
            text: "Here is a first draft.",
            tool_calls: [{ name: BOUND_SCAD_DRAFT, args: {} }],
          },
        );
        return { run_id: runId, thread_id: design.thread_id };
      }
      case "run_status": {
        const design = this.design(payload);
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
}

const sse = (events: { event: string; data: unknown }[]) =>
  events
    .map(
      ({ event, data }) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
    )
    .join("");

/**
 * One joined run as the Gateway streams it for stream_mode
 * ["values", "messages-tuple"]: an AI message chunk of text, the scad_draft
 * call's arguments in pieces, the tool's answer, then `end`.
 */
function draftStream(code: string, version: Version) {
  const args = JSON.stringify({ code, note: "A cube to start" });
  const cut = [0, 9, Math.floor(args.length / 2), args.length];
  const meta = { langgraph_node: "model" };
  const chunk = (index: number) => ({
    event: "messages",
    data: [
      {
        type: "AIMessageChunk",
        id: "ai-draft",
        content: index === 0 ? "Here is a first draft." : "",
        tool_call_chunks: [
          {
            type: "tool_call_chunk",
            index: 0,
            id: index === 0 ? "call-draft" : null,
            name: index === 0 ? BOUND_SCAD_DRAFT : null,
            args: args.slice(cut[index], cut[index + 1]),
          },
        ],
      },
      meta,
    ],
  });
  return sse([
    { event: "metadata", data: { run_id: version.run_id } },
    chunk(0),
    chunk(1),
    chunk(2),
    {
      event: "messages",
      data: [
        {
          type: "tool",
          id: "tool-draft",
          tool_call_id: "call-draft",
          name: BOUND_SCAD_DRAFT,
          content: JSON.stringify({
            version_id: version.id,
            seq: version.seq,
            next: "The page renders it in the browser; the result reaches you on your next turn.",
          }),
        },
        { langgraph_node: "tools" },
      ],
    },
    { event: "end", data: null },
  ]);
}

/**
 * Serve the cad-design package's built module graph with the Gateway's asset
 * policy (`Content-Security-Policy: sandbox`, so the OpenSCAD Worker runs in an
 * opaque origin), and answer its actions and run joins from `backend`.
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
          model_tools: ["scad_draft"],
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
        contentType: filename.endsWith(".wasm")
          ? "application/wasm"
          : "text/javascript",
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
        await route.fulfill({ json: backend.handle(action, payload) });
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
}

/** Count the requests to the Gateway (`/api/...`) from the page and its Workers. */
export function gatewayRequests(context: BrowserContext) {
  const seen: string[] = [];
  context.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) seen.push(url.pathname);
  });
  return seen;
}
