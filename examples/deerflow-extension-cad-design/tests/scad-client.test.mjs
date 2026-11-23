import assert from "node:assert/strict";
import test from "node:test";

import { createScadRunner } from "../ui/scad-client.js";

/** A Worker double that answers renders with whatever `answer` returns. */
function fakeWorkers(answer) {
  const made = [];
  const factory = () => {
    const worker = {
      posted: [],
      terminated: false,
      onmessage: null,
      onerror: null,
      postMessage(message) {
        this.posted.push(message);
        queueMicrotask(() => {
          if (this.terminated) return;
          if (message.type === "init")
            this.onmessage?.({ data: { type: "ready" } });
          else {
            const reply = answer(message, this);
            if (reply)
              this.onmessage?.({
                data: { type: "result", id: message.id, ...reply },
              });
          }
        });
      },
      terminate() {
        this.terminated = true;
      },
    };
    made.push(worker);
    return worker;
  };
  return { made, factory };
}

const wasm = new Uint8Array([1, 2, 3]);

test("the first render sends a private copy of the bytes, then the code", async () => {
  const model = { positions: new Float32Array(9) };
  const { made, factory } = fakeWorkers(() => ({
    ok: true,
    stl: new ArrayBuffer(4),
    model,
    metrics: { triangles: 1 },
    errorLines: [],
    log: [],
  }));
  const runner = createScadRunner({
    getWasm: async () => wasm,
    workerFactory: factory,
  });
  const result = await runner.render("cube(1);", { mode: "final" });
  assert.equal(result.ok, true);
  assert.equal(result.model, model);
  assert.deepEqual(result.metrics, { triangles: 1 });
  assert.equal(made.length, 1);
  assert.equal(made[0].posted[0].type, "init");
  assert.notEqual(made[0].posted[0].wasm, wasm.buffer);
  assert.deepEqual(new Uint8Array(made[0].posted[0].wasm), wasm);
  assert.equal(made[0].posted[1].code, "cube(1);");
  await runner.render("cube(2);", { mode: "final" });
  assert.equal(made.length, 1, "the Worker is reused");
  runner.dispose();
  assert.equal(made[0].terminated, true);
});

test("a render past its limit terminates the Worker and the next render gets a new one", async () => {
  let hang = true;
  const { made, factory } = fakeWorkers(() =>
    hang ? null : { ok: true, stl: null, errorLines: [], log: [] },
  );
  const runner = createScadRunner({
    getWasm: async () => wasm,
    workerFactory: factory,
    limits: { live: 20, final: 40 },
  });
  const slow = await runner.render("for(i=[0:1e9]) cube(i);", { mode: "live" });
  assert.deepEqual([slow.ok, slow.error], [false, "timeout"]);
  assert.equal(made[0].terminated, true);
  hang = false;
  const next = await runner.render("cube(1);", { mode: "final" });
  assert.equal(next.ok, true);
  assert.equal(made.length, 2);
  assert.equal(made[1].posted[0].type, "init");
  runner.dispose();
});

test("a newer live render replaces one still waiting; final renders all run", async () => {
  const seen = [];
  const { factory } = fakeWorkers((message) => {
    seen.push(message.code);
    return { ok: true, stl: null, errorLines: [], log: [] };
  });
  const runner = createScadRunner({
    getWasm: async () => wasm,
    workerFactory: factory,
  });
  const first = runner.render("a", { mode: "live" });
  const second = runner.render("b", { mode: "live" });
  const third = runner.render("c", { mode: "live" });
  const fourth = runner.render("d", { mode: "final" });
  const results = await Promise.all([first, second, third, fourth]);
  assert.deepEqual(seen, ["a", "c", "d"]);
  assert.equal(results[1].superseded, true);
  runner.dispose();
});

test("bytes that fail to load answer every waiting render and are retried later", async () => {
  let attempts = 0;
  const { factory } = fakeWorkers(() => ({
    ok: true,
    stl: null,
    errorLines: [],
    log: [],
  }));
  const runner = createScadRunner({
    getWasm: async () => {
      attempts++;
      if (attempts === 1)
        throw Object.assign(new Error("x"), { code: "integrity" });
      return wasm;
    },
    workerFactory: factory,
  });
  const failed = await runner.render("a", { mode: "final" });
  assert.deepEqual([failed.ok, failed.error], [false, "load:integrity"]);
  assert.equal((await runner.render("a", { mode: "final" })).ok, true);
  runner.dispose();
});

test("after dispose a render answers at once", async () => {
  const { factory } = fakeWorkers(() => ({ ok: true }));
  const runner = createScadRunner({
    getWasm: async () => wasm,
    workerFactory: factory,
  });
  runner.dispose();
  assert.equal((await runner.render("a", { mode: "live" })).error, "disposed");
});
