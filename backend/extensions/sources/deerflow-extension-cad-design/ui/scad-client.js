// Page side of the OpenSCAD Worker: one Worker, one render at a time, a hard
// time limit per render (live 8 s, final 30 s). On expiry the Worker is
// terminated; the next render starts a fresh one.

export const LIMITS_MS = Object.freeze({
  live: 8_000,
  final: 30_000,
  init: 30_000,
});

const defaultFactory = () =>
  new Worker(new URL("./scad-worker.mjs", import.meta.url), { type: "module" });

/**
 * `getWasm()` resolves the verified WebAssembly bytes (cached by the caller);
 * `render(code, {mode})` resolves `{ok, stl, model, metrics, error, errorLines,
 * warnings, log, ms}` (`model` is cad-preview's prepared mesh)
 * and never rejects. A live render still waiting is replaced by a newer live one
 * (`superseded: true`); final renders always run.
 */
export function createScadRunner({
  getWasm,
  workerFactory = defaultFactory,
  limits = LIMITS_MS,
} = {}) {
  const limit = { ...LIMITS_MS, ...limits };
  const queue = [];
  let worker = null;
  let ready = null;
  let busy = false;
  let disposed = false;
  let nextId = 1;
  let current = null;

  const drop = () => {
    if (worker) {
      worker.onmessage = worker.onerror = worker.onmessageerror = null;
      worker.terminate();
    }
    worker = null;
    ready = null;
  };

  const startWorker = async () => {
    const bytes = await getWasm();
    const made = workerFactory();
    worker = made;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error("init-timeout")),
        limit.init,
      );
      made.onmessage = ({ data }) => {
        if (data?.type === "ready") {
          clearTimeout(timer);
          made.onmessage = onResult;
          resolve();
        } else if (data?.type === "failed") {
          clearTimeout(timer);
          reject(new Error("wasm"));
        }
      };
      made.onerror = (event) => {
        event?.preventDefault?.();
        clearTimeout(timer);
        reject(new Error("worker"));
      };
      const copy = bytes.slice().buffer;
      made.postMessage({ type: "init", wasm: copy }, [copy]);
    });
  };

  const finish = (result) => {
    const job = current;
    if (!job) return;
    clearTimeout(job.timer);
    current = null;
    busy = false;
    job.resolve(result);
    pump();
  };

  function onResult({ data }) {
    if (data?.type !== "result" || !current || data.id !== current.id) return;
    const { type: _type, id: _id, ...result } = data;
    finish({
      ok: !!result.ok,
      stl: result.stl ?? null,
      model: result.model ?? null,
      metrics: result.metrics ?? null,
      error: result.error ?? null,
      errorLines: result.errorLines ?? [],
      warnings: result.warnings ?? [],
      log: result.log ?? [],
      ms: result.ms ?? 0,
    });
  }

  const failure = (error, extra = {}) => ({
    ok: false,
    stl: null,
    model: null,
    metrics: null,
    error,
    errorLines: [],
    warnings: [],
    log: [],
    ms: 0,
    ...extra,
  });

  async function pump() {
    if (busy || disposed || !queue.length) return;
    busy = true;
    const job = queue.shift();
    current = job;
    if (!ready) {
      ready = startWorker();
      ready.catch(() => {});
    }
    try {
      await ready;
    } catch (error) {
      drop();
      const code = error?.code
        ? `load:${error.code}`
        : error?.message === "wasm"
          ? "wasm"
          : "worker";
      finish(failure(code));
      return;
    }
    if (current !== job || disposed) return;
    worker.onerror = (event) => {
      event?.preventDefault?.();
      drop();
      finish(failure("worker"));
    };
    job.timer = setTimeout(() => {
      drop();
      finish(failure("timeout", { timedOut: true }));
    }, limit[job.mode] ?? limit.final);
    worker.postMessage({ type: "render", id: job.id, code: job.code });
  }

  return {
    render(code, { mode = "final" } = {}) {
      if (disposed) return Promise.resolve(failure("disposed"));
      return new Promise((resolve) => {
        if (mode === "live")
          for (let i = queue.length - 1; i >= 0; i--)
            if (queue[i].mode === "live")
              queue
                .splice(i, 1)[0]
                .resolve(failure("superseded", { superseded: true }));
        queue.push({ id: nextId++, code, mode, resolve, timer: 0 });
        pump();
      });
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      drop();
      if (current) {
        clearTimeout(current.timer);
        current.resolve(failure("disposed"));
        current = null;
      }
      for (const job of queue.splice(0)) job.resolve(failure("disposed"));
    },
  };
}
