import assert from "node:assert/strict";
import test from "node:test";

import {
  appendOnly,
  endedWithoutVersion,
  pickVersion,
} from "../ui/outcomes.js";

const run = (fields = {}) => ({
  kind: "prompt",
  stopped: false,
  state: { error: null },
  newestBefore: 2,
  ...fields,
});

test("a prompt turn that made no new version folder says so", () => {
  assert.equal(endedWithoutVersion(run(), 2), true);
  assert.equal(endedWithoutVersion(run({ newestBefore: 0 }), 0), true);
  assert.equal(endedWithoutVersion(run(), 3), false);
});

test("stopped, failed and resumed runs say nothing about versions", () => {
  assert.equal(endedWithoutVersion(run({ stopped: true }), 2), false);
  assert.equal(
    endedWithoutVersion(run({ state: { error: "The run failed." } }), 2),
    false,
  );
  assert.equal(endedWithoutVersion(run({ kind: "resume" }), 2), false);
  assert.equal(endedWithoutVersion(null, 2), false);
});

test("the newest version shows unless the user picked an older one that still exists", () => {
  assert.equal(pickVersion([]), null);
  assert.equal(pickVersion([1, 2, 3]), 3);
  assert.equal(pickVersion([1, 2, 3], { selected: 1, follow: true }), 3);
  assert.equal(pickVersion([1, 2, 3], { selected: 1, follow: false }), 1);
  assert.equal(pickVersion([2, 3], { selected: 1, follow: false }), 3);
  assert.equal(pickVersion([1, 2], { selected: null, follow: false }), 2);
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
