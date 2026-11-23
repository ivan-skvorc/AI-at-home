import assert from "node:assert/strict";
import test from "node:test";

import { StringStream } from "@codemirror/language";

import { openscadMode } from "../ui/scad-language.js";

function tokens(lines) {
  const state = openscadMode.startState();
  const out = [];
  for (const line of lines) {
    const stream = new StringStream(line, 2, 2);
    while (!stream.eol()) {
      const style = openscadMode.token(stream, state);
      const text = stream.current();
      if (style) out.push([text, style]);
      stream.start = stream.pos;
    }
  }
  return out;
}

test("keywords, builtins, numbers, strings, comments and special variables", () => {
  assert.deepEqual(
    tokens([
      "module tab(w = 2.5) { cube([w, 1e1, 3]); } // note",
      'echo("a\\"b"); $fn = 32;',
    ]),
    [
      ["module", "keyword"],
      ["tab", "def"],
      ["w", "variableName"],
      ["2.5", "number"],
      ["cube", "builtin"],
      ["w", "variableName"],
      ["1e1", "number"],
      ["3", "number"],
      ["// note", "comment"],
      ["echo", "builtin"],
      ['"a\\"b"', "string"],
      ["$fn", "atom"],
      ["32", "number"],
    ],
  );
});

test("a block comment carries across lines", () => {
  assert.deepEqual(tokens(["/* one", "two */ true"]), [
    ["/* one", "comment"],
    ["two */", "comment"],
    ["true", "atom"],
  ]);
});
