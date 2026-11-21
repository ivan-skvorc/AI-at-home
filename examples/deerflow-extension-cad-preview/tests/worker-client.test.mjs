import assert from "node:assert/strict";
import test from "node:test";

import { prepareInWorker } from "../ui/worker-client.js";
import { rejectsWith } from "./helpers.mjs";

class FakeWorker {
  constructor(reply) {
    this.reply = reply;
    this.terminated = 0;
    this.posted = [];
  }
  postMessage(message, transfer) {
    this.posted.push({ message, transfer });
    if (this.reply) queueMicrotask(() => this.onmessage?.({ data: this.reply }));
  }
  terminate() {
    this.terminated++;
  }
}

test("the worker gets its own copy of the bytes and is terminated after it answers", async () => {
  const worker = new FakeWorker({ result: { triangles: 1 } });
  const bytes = new Uint8Array([1, 2, 3]).buffer;
  const result = await prepareInWorker(bytes, "stl", new AbortController().signal, {
    workerFactory: () => worker,
  });
  assert.deepEqual(result, { triangles: 1 });
  assert.equal(worker.terminated, 1);
  const { message, transfer } = worker.posted[0];
  assert.notEqual(message.bytes, bytes);
  assert.deepEqual(transfer, [message.bytes]);
  assert.equal(bytes.byteLength, 3);
});

test("a fixed diagnostic code from the worker is passed through", async () => {
  const worker = new FakeWorker({ error: "too-many-triangles" });
  await rejectsWith(
    prepareInWorker(new ArrayBuffer(4), "glb", new AbortController().signal, {
      workerFactory: () => worker,
    }),
    "too-many-triangles",
  );
  assert.equal(worker.terminated, 1);
});

test("an unknown message from the worker is not shown as a reason", async () => {
  const worker = new FakeWorker({ error: "<img src=x onerror=alert(1)>" });
  await rejectsWith(
    prepareInWorker(new ArrayBuffer(4), "glb", new AbortController().signal, {
      workerFactory: () => worker,
    }),
    "worker-failed",
  );
});

test("the deadline terminates a worker that never answers", async () => {
  const worker = new FakeWorker(null);
  await rejectsWith(
    prepareInWorker(new ArrayBuffer(4), "glb", new AbortController().signal, {
      workerFactory: () => worker,
      timeoutMs: 10,
    }),
    "timeout",
  );
  assert.equal(worker.terminated, 1);
});

test("aborting terminates the worker, and an aborted signal starts none", async () => {
  const worker = new FakeWorker(null);
  const controller = new AbortController();
  const pending = prepareInWorker(new ArrayBuffer(4), "glb", controller.signal, {
    workerFactory: () => worker,
  });
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(worker.terminated, 1);
  let created = 0;
  await assert.rejects(
    prepareInWorker(new ArrayBuffer(4), "glb", controller.signal, {
      workerFactory: () => {
        created++;
        return new FakeWorker(null);
      },
    }),
    { name: "AbortError" },
  );
  assert.equal(created, 0);
});
