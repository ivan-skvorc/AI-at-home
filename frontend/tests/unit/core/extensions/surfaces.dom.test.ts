import { expect, rs, test } from "@rstest/core";

import { mountSurface } from "@/core/extensions/surfaces";

test("surface cleanup aborts outstanding work and rejects late backend calls", async () => {
  const container = document.createElement("div");
  const dispose = rs.fn();
  const backend = rs.fn(async () => ({}));
  let callLater: (
    name: string,
    payload: Record<string, unknown>,
  ) => Promise<unknown> = rs.fn();
  let signal: AbortSignal | undefined;
  const cleanup = mountSurface(
    container,
    {
      id: "picker",
      slot: "page",
      title: "Picker",
      mount(root, context) {
        signal = context.signal;
        callLater = context.callBackend;
        root.textContent = "PLUGIN UI";
        return { dispose };
      },
    },
    {
      namespace: "community.example",
      locale: "en",
      settings: {},
      threadId: "a",
      callBackend: backend,
    },
    rs.fn(),
  );
  expect(container.shadowRoot?.textContent).toBe("PLUGIN UI");
  await callLater("search", {});
  cleanup();
  cleanup();
  await expect(callLater("search", {})).rejects.toThrow();
  expect(backend).toHaveBeenCalledTimes(1);
  expect(signal?.aborted).toBe(true);
  expect(dispose).toHaveBeenCalledTimes(1);
  expect(container.shadowRoot?.textContent).toBe("");
});

test("a failed mount is isolated and cannot leave its partial UI behind", () => {
  const error = rs.fn();
  const container = document.createElement("div");
  mountSurface(
    container,
    {
      id: "bad",
      slot: "page",
      title: "Broken",
      mount(root) {
        root.textContent = "partial";
        throw new Error("broken");
      },
    },
    {
      namespace: "community.example",
      locale: "en",
      settings: {},
      callBackend: rs.fn(),
    },
    error,
  );
  expect(error).toHaveBeenCalledTimes(1);
  expect(container.shadowRoot?.textContent).toBe("");
});

for (const failMount of [false, true]) {
  test(`surface ${failMount ? "mount failure" : "cleanup"} aborts navigation and rejects stale callbacks`, async () => {
    let openLater!: (id: string) => Promise<void>;
    let pending!: Promise<void>;
    let finish!: () => void;
    const navigate = rs.fn();
    const open = rs.fn(async (_id: string, signal: AbortSignal) => {
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
      signal.throwIfAborted();
      navigate();
    });
    const cleanup = mountSurface(
      document.createElement("div"),
      {
        id: "library",
        slot: "page",
        title: "Library",
        mount(_root, context) {
          openLater = context.openConversation!;
          pending = openLater("thread");
          if (failMount) throw new Error("mount failed");
          return { dispose: rs.fn() };
        },
      },
      {
        namespace: "bookmarks",
        locale: "en",
        settings: {},
        callBackend: rs.fn(),
        openConversation: open,
      },
      rs.fn(),
    );
    if (!failMount) cleanup();
    finish();
    await expect(pending).rejects.toThrow();
    await expect(openLater("thread")).rejects.toThrow();
    expect(open).toHaveBeenCalledTimes(1);
    expect(navigate).not.toHaveBeenCalled();
  });
}

test("joined run streams carry the page signal and stop with the page", async () => {
  const seenSignals: AbortSignal[] = [];
  const join = rs.fn(async function* (
    _threadId: string,
    _runId: string,
    signal: AbortSignal,
  ) {
    seenSignals.push(signal);
    yield { event: "values", data: 1 };
    signal.throwIfAborted();
  });
  let joinLater!: NonNullable<
    Parameters<Parameters<typeof mountSurface>[1]["mount"]>[1]["joinRunStream"]
  >;
  const own = new AbortController();
  const cleanup = mountSurface(
    document.createElement("div"),
    {
      id: "designs",
      slot: "page",
      title: "Designs",
      mount(_root, context) {
        joinLater = context.joinRunStream!;
        return { dispose: rs.fn() };
      },
    },
    {
      namespace: "cad-design",
      locale: "en",
      settings: {},
      callBackend: rs.fn(),
      joinRunStream: join,
    },
    rs.fn(),
  );
  const events: unknown[] = [];
  for await (const event of joinLater("t", "r", { signal: own.signal }))
    events.push(event);
  expect(events).toEqual([{ event: "values", data: 1 }]);
  expect(join).toHaveBeenCalledWith("t", "r", expect.any(AbortSignal));
  own.abort();
  expect(seenSignals[0]?.aborted).toBe(true);
  cleanup();
  const late = joinLater("t", "r");
  await expect(late[Symbol.asyncIterator]().next()).rejects.toThrow();
  expect(join).toHaveBeenCalledTimes(1);
});

test("a full-layout surface root fills its host and models pass through", () => {
  const container = document.createElement("div");
  let models: unknown;
  let root!: HTMLElement;
  mountSurface(
    container,
    {
      id: "designs",
      slot: "page",
      title: "Designs",
      layout: "full",
      mount(element, context) {
        root = element;
        models = context.models?.list;
        return { dispose: rs.fn() };
      },
    },
    {
      namespace: "cad-design",
      locale: "en",
      settings: {},
      callBackend: rs.fn(),
      models: { list: [{ name: "a", display_name: "A" }], defaultName: "a" },
    },
    rs.fn(),
  );
  expect(models).toEqual([{ name: "a", display_name: "A" }]);
  expect(root.style.height).toBe("100%");
});
