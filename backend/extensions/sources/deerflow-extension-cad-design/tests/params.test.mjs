import assert from "node:assert/strict";
import test from "node:test";

import { parseParameters, rewriteParameter, withValues } from "../ui/params.js";

const SOURCE = `// Bracket
width = 40; // [10:5:120]
height = 12.5; // [2:30]
holes = true;
depth = 0;
$fn = 48;
module tab(t = 3) { inner = 9; cube(t); }
offset = -4;
label = "x";
width = 50; // [10:5:120]
`;

test("top-level numbers and booleans become parameters, the last assignment wins", () => {
  const params = parseParameters(SOURCE);
  assert.deepEqual(
    params.map(({ name, value, kind }) => [name, value, kind]),
    [
      ["height", 12.5, "number"],
      ["holes", true, "boolean"],
      ["depth", 0, "number"],
      ["offset", -4, "number"],
      ["width", 50, "number"],
    ],
  );
});

test("customizer comments set the range and the step", () => {
  const byName = Object.fromEntries(
    parseParameters(SOURCE).map((p) => [p.name, p]),
  );
  assert.deepEqual(
    [
      byName.width.min,
      byName.width.step,
      byName.width.max,
      byName.width.derived,
    ],
    [10, 5, 120, false],
  );
  assert.deepEqual(
    [byName.height.min, byName.height.max, byName.height.derived],
    [2, 30, false],
  );
  assert.ok(byName.height.step > 0 && byName.height.step <= 0.5);
});

test("a parameter without a range gets a derived one that contains its value", () => {
  for (const p of parseParameters(SOURCE).filter(
    (p) => p.kind === "number" && p.derived,
  )) {
    assert.ok(p.min <= p.value && p.value <= p.max, p.name);
    assert.ok(p.max > p.min, p.name);
    assert.ok(p.step > 0, p.name);
  }
});

test("rewriting changes only that value and keeps the comment", () => {
  const next = rewriteParameter(SOURCE, "width", 65);
  assert.match(next, /^width = 65; \/\/ \[10:5:120\]$/m);
  assert.match(next, /^width = 40; \/\/ \[10:5:120\]$/m);
  assert.equal(
    rewriteParameter(next, "holes", false).includes("holes = false;"),
    true,
  );
  assert.equal(
    rewriteParameter(SOURCE, "height", 7.25000001).includes("height = 7.25;"),
    true,
  );
  assert.equal(rewriteParameter(SOURCE, "missing", 1), SOURCE);
  assert.equal(rewriteParameter(SOURCE, "inner", 1), SOURCE);
});

test("several values apply at once", () => {
  const next = withValues(SOURCE, { width: 70, depth: 3 });
  assert.match(next, /^width = 70;/m);
  assert.match(next, /^depth = 3;/m);
});
