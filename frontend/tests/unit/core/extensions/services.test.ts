import { beforeEach, expect, rs, test } from "@rstest/core";

import { loadFrontendExtensions } from "@/core/extensions/registry";
import {
  bindFrontendServices,
  conversationText,
  joinRunStream,
  latestVisibleAnswer,
  listThreadOutputs,
  openConversation,
  pluginModelSnapshot,
  readThreadOutput,
  requestExtensionRoute,
  threadOutputURL,
} from "@/core/extensions/services";
import type { AgentThread } from "@/core/threads/types";

const { request, getState, getThread } = rs.hoisted(() => ({
  request: rs.fn(),
  getState: rs.fn(),
  getThread: rs.fn(),
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: request }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
rs.mock("@/core/api", () => ({
  getAPIClient: () => ({ threads: { getState, get: getThread } }),
}));

beforeEach(() => {
  rs.clearAllMocks();
});

test("extension HTTP transport uses host auth and abort without replaying writes", async () => {
  const signal = new AbortController().signal;
  const response = { ok: false, status: 409 };
  request.mockResolvedValue(response);
  expect(
    await requestExtensionRoute(
      "/api/extensions/example/files?filename=a.txt",
      {
        method: "POST",
        body: "data",
        headers: { "x-deerflow-plugin-viewer": "forged" },
      },
      signal,
      "alice",
    ),
  ).toBe(response);
  expect(request).toHaveBeenCalledWith(
    "/api/extensions/example/files?filename=a.txt",
    expect.objectContaining({
      method: "POST",
      body: "data",
      signal,
      redirect: "error",
    }),
  );
  expect(request).toHaveBeenCalledTimes(1);
  expect(
    request.mock.calls[0]![1].headers.get("X-Deerflow-Plugin-Viewer"),
  ).toBe("alice");
});

test("extension transport rejects foreign URLs, traversal and late calls", async () => {
  const signal = new AbortController().signal;
  for (const path of [
    "https://evil.test/api/extensions/a",
    "//evil.test/api/extensions/a",
    "/api/plugins",
    "/api/extensions/../auth/me",
    "/api/extensions/a/%2e%2e/%2e%2e/auth/me",
    "/api/extensions/a\\b",
    "/api/extensions/a#fragment",
  ]) {
    await expect(
      requestExtensionRoute(path, {}, signal, "alice"),
    ).rejects.toThrow();
  }
  const aborted = AbortSignal.abort();
  await expect(
    requestExtensionRoute(
      "/api/extensions/example/spaces",
      {},
      aborted,
      "alice",
    ),
  ).rejects.toThrow();
  expect(request).not.toHaveBeenCalled();
  await expect(
    requestExtensionRoute("/api/extensions/example/spaces", {}, signal, ""),
  ).rejects.toThrow();
});

test("bookmark receives only the last visible assistant answer", async () => {
  const thread = {
    thread_id: "t",
    values: { title: "Example" },
  } as AgentThread;
  const answer = await latestVisibleAnswer({
    thread,
    messages: [
      { id: "a", type: "ai", content: "<think>SECRET</think>Visible answer" },
      {
        id: "h",
        type: "ai",
        content: "HIDDEN",
        additional_kwargs: { hide_from_ui: true },
      },
      { id: "u", type: "human", content: "Later question" },
    ],
  });
  expect(answer).toEqual({ id: "a", text: "Visible answer" });
});

const entry = {
  namespace: "community.stats",
  module: null,
  entry: null,
  title: "Stats",
  description: "",
  settings: { enabled: true },
  backend_actions: ["stats"],
};

test("backend-only entry stays visible without attempting a browser import", async () => {
  const importer = rs.fn();
  expect(await loadFrontendExtensions([entry], importer)).toEqual([entry]);
  expect(importer).not.toHaveBeenCalled();
});

test("backend bridge binds installed namespace and propagates administrator disable", async () => {
  const services = bindFrontendServices(
    {
      conversationText,
      showMessage: rs.fn(),
    },
    entry,
  );
  request.mockResolvedValue({
    ok: true,
    json: async () => ({ characters: 5 }),
  });
  expect(await services.callBackend("stats", { text: "hello" })).toEqual({
    characters: 5,
  });
  expect(request).toHaveBeenCalledWith(
    "/api/plugins/community.stats/actions/stats",
    expect.objectContaining({ method: "POST", body: '{"text":"hello"}' }),
  );
  await expect(services.callBackend("undeclared", {})).rejects.toThrow(
    "not declared",
  );
  expect(request).toHaveBeenCalledTimes(1);
  request.mockResolvedValue({ ok: false, status: 403 });
  await expect(services.callBackend("stats", {})).rejects.toThrow("403");
});

test("plugin transcript service shares visible-only sanitizer and authenticated sidebar read", async () => {
  const thread = {
    thread_id: "test",
    values: { title: "Synthetic" },
  } as AgentThread;
  const messages = [
    { id: "u", type: "human" as const, content: "hello" },
    {
      id: "a",
      type: "ai" as const,
      content: "<think>PRIVATE</think>world",
      additional_kwargs: { reasoning_content: "PRIVATE" },
    },
    {
      id: "hidden",
      type: "ai" as const,
      content: "HIDDEN",
      additional_kwargs: { hide_from_ui: true },
    },
  ];
  const text = await conversationText({ thread, messages });
  expect(text).toBe("hello\n\nworld");
  expect(getState).not.toHaveBeenCalled();
  getState.mockResolvedValue({ values: { messages } });
  expect(await conversationText({ thread })).toBe(text);
  expect(getState).toHaveBeenCalledWith("test");
  getState.mockRejectedValue(new Error("403"));
  await expect(conversationText({ thread })).rejects.toThrow("403");
});

for (const agent of [undefined, "researcher", "研究 / agent?#"]) {
  test(`plugin navigation resolves the current owner for ${agent ?? "default"} conversations`, async () => {
    getThread.mockResolvedValue({
      thread_id: "thread / 1",
      metadata: agent ? { agent_name: agent } : {},
    });
    const navigate = rs.fn();
    const signal = new AbortController().signal;
    await openConversation("thread / 1", navigate, signal);
    expect(getThread).toHaveBeenCalledWith("thread / 1", { signal });
    expect(navigate).toHaveBeenCalledWith(
      agent
        ? `/workspace/agents/${encodeURIComponent(agent)}/chats/thread%20%2F%201`
        : "/workspace/chats/thread%20%2F%201",
    );
  });
}

test("inaccessible conversations never fall back to the default agent route", async () => {
  const navigate = rs.fn();
  getThread.mockRejectedValue(new Error("403"));
  await expect(openConversation("thread", navigate)).rejects.toThrow("403");
  expect(navigate).not.toHaveBeenCalled();
});

test("unmounted or switched-account plugin pages cannot navigate after a late metadata read", async () => {
  const navigate = rs.fn();
  const abort = new AbortController();
  let finish!: (value: unknown) => void;
  getThread.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const pending = openConversation("thread", navigate, abort.signal);
  abort.abort();
  finish({ thread_id: "thread", metadata: { agent_name: "researcher" } });
  await expect(pending).rejects.toThrow();
  expect(navigate).not.toHaveBeenCalled();
  getThread.mockClear();
  await expect(
    openConversation("thread", navigate, abort.signal),
  ).rejects.toThrow();
  expect(getThread).not.toHaveBeenCalled();
});

function sseBody(chunks: string[]) {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(iterable: AsyncIterable<unknown>) {
  const events: unknown[] = [];
  for await (const event of iterable) events.push(event);
  return events;
}

test("run stream join reads the authenticated SSE route and parses split events", async () => {
  request.mockResolvedValue(
    new Response(
      sseBody([
        ': heartbeat\n\nevent: metadata\ndata: {"run_id":',
        '"r1"}\r',
        "\n\r\nevent: messages\ndata: [1,\ndata: 2]\n\n",
        "data: not json\n\nevent: end\ndata: null\n\n",
      ]),
      { headers: { "Content-Type": "text/event-stream" } },
    ),
  );
  const signal = new AbortController().signal;
  expect(await collect(joinRunStream("thread-1", "run_1", signal))).toEqual([
    { event: "metadata", data: { run_id: "r1" } },
    { event: "messages", data: [1, 2] },
    { event: "message", data: "not json" },
    { event: "end", data: null },
  ]);
  expect(request).toHaveBeenCalledTimes(1);
  const [url, init] = request.mock.calls[0]!;
  expect(url).toBe("/api/threads/thread-1/runs/run_1/join");
  expect(init.method).toBe("GET");
  expect(init.headers.Accept).toBe("text/event-stream");
  expect(init.signal).toBe(signal);
});

test("run stream join refuses malformed ids, failed responses and aborted pages", async () => {
  const signal = new AbortController().signal;
  for (const [threadId, runId] of [
    ["../auth", "run"],
    ["thread", "run/../../x"],
    ["thread", ""],
    ["thread", "a".repeat(129)],
    ["thread?x=1", "run"],
  ] as const) {
    await expect(
      collect(joinRunStream(threadId, runId, signal)),
    ).rejects.toThrow();
  }
  expect(request).not.toHaveBeenCalled();
  request.mockResolvedValue(new Response("nope", { status: 404 }));
  await expect(collect(joinRunStream("thread", "run", signal))).rejects.toThrow(
    "404",
  );
  await expect(
    collect(joinRunStream("thread", "run", AbortSignal.abort())),
  ).rejects.toThrow();
  expect(request).toHaveBeenCalledTimes(1);
});

test("aborting a joined run stream rejects the reader and cancels the body", async () => {
  const abort = new AbortController();
  const cancel = rs.fn();
  const encoder = new TextEncoder();
  request.mockResolvedValue(
    new Response(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode("event: values\ndata: 1\n\n"));
        },
        cancel,
      }),
    ),
  );
  const seen: unknown[] = [];
  await expect(
    (async () => {
      for await (const event of joinRunStream("t", "r", abort.signal)) {
        seen.push(event);
        abort.abort();
      }
    })(),
  ).rejects.toThrow();
  expect(seen).toEqual([{ event: "values", data: 1 }]);
  expect(cancel).toHaveBeenCalled();
});

test("plugin model snapshots copy names and prefer the user's model", () => {
  const models = [
    { name: "fast", display_name: "Fast", price: { input: 1 } },
    { name: "smart", display_name: "" },
  ];
  expect(pluginModelSnapshot(models, "smart")).toEqual({
    list: [{ name: "fast", display_name: "Fast" }, { name: "smart" }],
    defaultName: "smart",
  });
  expect(pluginModelSnapshot(models, "gone").defaultName).toBe("fast");
  expect(pluginModelSnapshot([], "gone")).toEqual({ list: [] });
});

const OUT = "/mnt/user-data/outputs/design";

test("thread files list an outputs folder through the owner-checked listing route", async () => {
  request.mockResolvedValue(
    Response.json({
      path: OUT,
      exists: true,
      entries: [
        {
          name: "v1",
          path: `${OUT}/v1`,
          kind: "directory",
          size: null,
          modified_at: "2026-11-25T10:00:00Z",
        },
        // Not the listed folder plus its name: dropped by the host's parser.
        {
          name: "evil",
          path: "/mnt/user-data/uploads/evil",
          kind: "file",
          size: 1,
          modified_at: null,
        },
      ],
      truncated: false,
      total: 2,
    }),
  );
  const signal = new AbortController().signal;
  expect(await listThreadOutputs("thread-1", OUT, signal)).toEqual([
    {
      name: "v1",
      path: `${OUT}/v1`,
      kind: "directory",
      size: null,
      modified_at: "2026-11-25T10:00:00Z",
    },
  ]);
  const [url, init] = request.mock.calls[0]!;
  expect(url).toBe(
    `/api/threads/thread-1/files?path=${encodeURIComponent(OUT)}`,
  );
  expect(init.signal).toBe(signal);
  request.mockResolvedValue(
    Response.json({ detail: "Directory not found" }, { status: 404 }),
  );
  await expect(
    listThreadOutputs("thread-1", `${OUT}/v9`, signal),
  ).rejects.toMatchObject({ status: 404 });
});

test("thread files accept only paths under the outputs folder and a plain thread id", async () => {
  const signal = new AbortController().signal;
  for (const [threadId, path] of [
    ["../auth", OUT],
    ["thread?x=1", OUT],
    ["thread", "/mnt/user-data/uploads/a.stl"],
    ["thread", "/mnt/user-data/workspace/design/model.scad"],
    ["thread", "/mnt/user-data/outputs-evil/a"],
    ["thread", `${OUT}/../../uploads/a`],
    ["thread", `${OUT}/./v1`],
    ["thread", `${OUT}//v1`],
    ["thread", `${OUT}/v1/`],
    ["thread", `${OUT}\\v1`],
    ["thread", `${OUT}/v1\u0000`],
    ["thread", "mnt/user-data/outputs/a"],
  ] as const) {
    await expect(listThreadOutputs(threadId, path, signal)).rejects.toThrow();
    await expect(readThreadOutput(threadId, path, signal)).rejects.toThrow();
    expect(() => threadOutputURL(threadId, path)).toThrow();
  }
  expect(request).not.toHaveBeenCalled();
  await expect(
    listThreadOutputs("thread", OUT, AbortSignal.abort()),
  ).rejects.toThrow();
  expect(request).not.toHaveBeenCalled();
});

test("thread file URLs encode each path segment for the artifact route", () => {
  expect(threadOutputURL("t-1", `${OUT}/v1/a b#%.stl`)).toBe(
    "/api/threads/t-1/artifacts/mnt/user-data/outputs/design/v1/a%20b%23%25.stl",
  );
  expect(threadOutputURL("t-1", `${OUT}/v1/a.step`, true)).toBe(
    "/api/threads/t-1/artifacts/mnt/user-data/outputs/design/v1/a.step?download=true",
  );
});

test("thread file reads are bounded even when Content-Length is missing", async () => {
  const encoder = new TextEncoder();
  const body = (chunks: string[]) =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    });
  request.mockResolvedValue(new Response(body(['{"a":', "1}"])));
  const signal = new AbortController().signal;
  const bytes = await readThreadOutput(
    "t",
    `${OUT}/v1/report.json`,
    signal,
    64,
  );
  expect(new TextDecoder().decode(bytes)).toBe('{"a":1}');
  const [url, init] = request.mock.calls[0]!;
  expect(url).toBe(
    "/api/threads/t/artifacts/mnt/user-data/outputs/design/v1/report.json",
  );
  expect(init).toMatchObject({ cache: "no-store", redirect: "error", signal });

  request.mockResolvedValue(
    new Response(body(["x".repeat(40), "y".repeat(40)])),
  );
  await expect(
    readThreadOutput("t", `${OUT}/v1/report.json`, signal, 64),
  ).rejects.toMatchObject({ status: 413 });
  request.mockResolvedValue(
    new Response("x".repeat(10), { headers: { "Content-Length": "100" } }),
  );
  await expect(
    readThreadOutput("t", `${OUT}/v1/report.json`, signal, 64),
  ).rejects.toMatchObject({ status: 413 });
  request.mockResolvedValue(new Response("gone", { status: 404 }));
  await expect(
    readThreadOutput("t", `${OUT}/v1/report.json`, signal),
  ).rejects.toMatchObject({ status: 404 });
});
