import assert from "node:assert/strict";
import test from "node:test";

import {
  appendOnly,
  isDraftSource,
  isEngineFailure,
  shouldRepair,
  shouldReport,
  shouldRetrySave,
} from "../ui/outcomes.js";

test("engine and infrastructure failures are told apart from the file's own errors", () => {
  for (const code of [
    "load:integrity",
    "load:network",
    "worker",
    "wasm",
    "timeout",
    "disposed",
  ])
    assert.equal(isEngineFailure(code), true, code);
  for (const code of [
    "Parser error in line 3",
    "No top-level geometry",
    null,
    undefined,
  ])
    assert.equal(isEngineFailure(code), false, String(code));
});

test("only a render that says something about the source is reported", () => {
  const ok = { ok: true };
  const bad = { ok: false, error: "Parser error" };
  assert.equal(shouldReport({ render: null }, ok), true);
  assert.equal(shouldReport({ render: null }, bad), true);
  assert.equal(shouldReport({ render: { ok: true } }, ok), false);
  assert.equal(shouldReport({ render: { ok: true } }, bad), false);
  // A later good render replaces a stored failure, so Finalize is not blocked for good.
  assert.equal(shouldReport({ render: { ok: false } }, ok), true);
  assert.equal(shouldReport({ render: { ok: false } }, bad), false);
  // The engine failing to load, crashing or running out of time says nothing about the file.
  assert.equal(
    shouldReport({ render: null }, { ok: false, engine: true }),
    false,
  );
  assert.equal(shouldReport({ render: null }, { superseded: true }), false);
  assert.equal(
    shouldReport({ render: null }, { ok: false, error: "closed" }),
    false,
  );
  assert.equal(shouldReport(null, ok), true);
});

test("the automatic repair follows only a prompt run that ended on its own", () => {
  const run = (extra = {}) => ({
    kind: "prompt",
    failedVersion: "v4",
    stopped: false,
    state: { error: null },
    ...extra,
  });
  assert.equal(shouldRepair(run()), true);
  assert.equal(shouldRepair(run({ stopped: true })), false);
  assert.equal(shouldRepair(run({ state: { error: "interrupted" } })), false);
  assert.equal(shouldRepair(run({ failedVersion: null })), false);
  assert.equal(shouldRepair(run({ kind: "repair" })), false);
  assert.equal(shouldRepair(run({ kind: "finalize" })), false);
});

test("model and repair drafts are both the model's", () => {
  assert.equal(isDraftSource("model"), true);
  assert.equal(isDraftSource("repair"), true);
  assert.equal(isDraftSource("hand"), false);
  assert.equal(isDraftSource("slider"), false);
});

test("a failed save is not retried until the source changes", () => {
  assert.equal(
    shouldRetrySave({ now: "a", attempted: "a", running: false }),
    false,
  );
  assert.equal(
    shouldRetrySave({ now: "ab", attempted: "a", running: false }),
    true,
  );
  assert.equal(
    shouldRetrySave({ now: "ab", attempted: "a", running: true }),
    false,
  );
});

test("new messages are appended to the ones already shown", () => {
  assert.deepEqual(
    appendOnly(["a", "b"], [{ id: "a" }, { id: "b" }, { id: "c" }]),
    [{ id: "c" }],
  );
  assert.deepEqual(appendOnly([], [{ id: "a" }]), [{ id: "a" }]);
  assert.deepEqual(appendOnly(["a", "b"], [{ id: "a" }, { id: "b" }]), []);
  // Anything else is a different history: rebuild.
  assert.equal(appendOnly(["a", "b"], [{ id: "a" }]), null);
  assert.equal(appendOnly(["a", "x"], [{ id: "a" }, { id: "b" }]), null);
  assert.equal(appendOnly(["a"], [{ id: "" }, { id: "b" }]), null);
});
