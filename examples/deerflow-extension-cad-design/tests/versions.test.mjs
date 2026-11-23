import assert from "node:assert/strict";
import test from "node:test";

import { timeline } from "../ui/versions.js";

const v = (id, seq, parent, extra = {}) => ({
  id,
  seq,
  parent_id: parent,
  source: "model",
  created_at: `2026-11-23T10:0${seq}:00Z`,
  ...extra,
});

test("the timeline is newest first and marks the head", () => {
  const rows = timeline([v("a", 1, null), v("c", 3, "b"), v("b", 2, "a")], "b");
  assert.deepEqual(
    rows.map((r) => r.seq),
    [3, 2, 1],
  );
  assert.deepEqual(
    rows.map((r) => r.isHead),
    [false, true, false],
  );
});

test("a version whose parent is not the one before it starts a branch", () => {
  const rows = timeline(
    [v("a", 1, null), v("b", 2, "a"), v("c", 3, "a"), v("d", 4, "c")],
    "d",
  );
  const bySeq = Object.fromEntries(rows.map((r) => [r.seq, r]));
  assert.equal(bySeq[3].branchFrom, 1);
  assert.equal(bySeq[2].branchFrom, null);
  assert.equal(bySeq[4].branchFrom, null);
});

test("render state reads ok, failed or not yet rendered", () => {
  const rows = timeline([
    v("a", 1, null, { render: { ok: true } }),
    v("b", 2, "a", { render: { ok: false, error: "syntax" } }),
    v("c", 3, "b"),
  ]);
  assert.deepEqual(
    rows.map((r) => r.status),
    ["pending", "error", "ok"],
  );
  assert.equal(rows[1].error, "syntax");
});

test("malformed rows are dropped", () => {
  assert.deepEqual(
    timeline([null, { id: 3 }, v("a", 1, null)]).map((r) => r.id),
    ["a"],
  );
});
