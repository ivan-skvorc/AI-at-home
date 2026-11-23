import assert from "node:assert/strict";
import test from "node:test";

import { capFn, completePrefix, extractPartialCode } from "../ui/scad-text.js";

test("a partial JSON string yields the code decoded so far", () => {
  assert.deepEqual(extractPartialCode('{"code": "cube(1);\\nsphe'), {
    code: "cube(1);\nsphe",
    complete: false,
  });
  assert.deepEqual(extractPartialCode('{"note":"a \\"b\\"","code":"x=1;"}'), {
    code: "x=1;",
    complete: true,
  });
  // A key named code inside another value is not the argument.
  assert.equal(extractPartialCode('{"note":"{\\"code\\":1}", "co').code, null);
  assert.equal(
    extractPartialCode('{"note":{"code":"no"},"code":"yes"}').code,
    "yes",
  );
});

test("an escape cut in half is dropped, not decoded", () => {
  assert.equal(extractPartialCode('{"code":"a\\').code, "a");
  assert.equal(extractPartialCode('{"code":"a\\u00').code, "a");
  assert.equal(extractPartialCode('{"code":"\\u00e9\\t\\/"}').code, "é\t/");
});

test("nothing is extracted before the code value starts", () => {
  for (const text of ["", "{", '{"co', '{"code"', '{"code": ', "[1]", "null"])
    assert.equal(extractPartialCode(text).code, null, text);
});

test("the cut ends on the last complete top-level statement", () => {
  assert.equal(completePrefix("w = 2;\ncube(w);\nsphe"), "w = 2;\ncube(w);");
  assert.equal(
    completePrefix(
      "difference() {\n  cube(4);\n  translate([1,1,1]) cube(2);\n}\nunion() { cube(",
    ),
    "difference() {\n  cube(4);\n  translate([1,1,1]) cube(2);\n}",
  );
  // Semicolons inside a block, a string or a comment are not top level.
  assert.equal(completePrefix("union() { cube(1); sphere(2);"), "");
  assert.equal(
    completePrefix('echo("a;b"); // c;\n/* d; */ cube('),
    'echo("a;b");',
  );
  assert.equal(
    completePrefix("module m(a = [1, 2]) { cube(a); }\nm();"),
    "module m(a = [1, 2]) { cube(a); }\nm();",
  );
  assert.equal(completePrefix(""), "");
});

test("$fn literals are capped and expressions are left alone", () => {
  assert.equal(
    capFn("$fn = 128;\ncylinder(d=2, $fn=12);\nsphere(1, $fn = 96.5);", 24),
    "$fn = 24;\ncylinder(d=2, $fn=12);\nsphere(1, $fn = 24);",
  );
  assert.equal(capFn("cylinder($fn=res);", 24), "cylinder($fn=res);");
});
