import assert from "node:assert/strict";
import test from "node:test";

import { parseLog } from "../ui/scad-engine.js";

test("a parser error names its line", () => {
  const result = parseLog([
    "Could not initialize localization (application path is '/').",
    "ERROR: Parser error: syntax error in file /input.scad, line 2",
    "Can't parse file '/input.scad'!",
  ]);
  assert.equal(
    result.error,
    "Parser error: syntax error in file /input.scad, line 2",
  );
  assert.deepEqual(result.errorLines, [2]);
  assert.deepEqual(result.log, [
    "ERROR: Parser error: syntax error in file /input.scad, line 2",
    "Can't parse file '/input.scad'!",
  ]);
});

test("warnings add their lines and an empty model is an error", () => {
  const result = parseLog([
    "WARNING: Ignoring unknown module 'foo' in file /input.scad, line 4",
    "WARNING: Ignoring unknown variable 'w' in file input.scad, line 4",
    "Current top level object is empty.",
  ]);
  assert.equal(result.error, "Current top level object is empty.");
  assert.deepEqual(result.errorLines, [4]);
  assert.deepEqual(result.warnings, [
    "Ignoring unknown module 'foo' in file /input.scad, line 4",
    "Ignoring unknown variable 'w' in file input.scad, line 4",
  ]);
});

test("the log is bounded", () => {
  const result = parseLog(
    Array.from({ length: 1000 }, (_, i) => `x${"y".repeat(2000)}${i}`),
  );
  assert.ok(result.log.length <= 200);
  assert.ok(result.log.every((line) => line.length <= 500));
});
