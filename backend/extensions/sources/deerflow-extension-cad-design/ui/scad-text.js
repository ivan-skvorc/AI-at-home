// Text helpers for OpenSCAD source while it streams in: no parser, only a
// lexical scan that knows strings, comments and bracket depth.

/**
 * Read the `code` member of a tool call's arguments while their JSON is still
 * arriving. Returns the characters decoded so far, `complete` once the
 * string's closing quote has arrived, and `code: null` before the value starts.
 */
export function extractPartialCode(text) {
  const none = { code: null, complete: false };
  if (typeof text !== "string") return none;
  let i = skipSpace(text, 0);
  if (text[i] !== "{") return none;
  i++;
  for (;;) {
    i = skipSpace(text, i);
    if (text[i] === ",") i = skipSpace(text, i + 1);
    if (text[i] !== '"') return none;
    const key = readString(text, i);
    if (!key.complete) return none;
    i = skipSpace(text, key.end);
    if (text[i] !== ":") return none;
    i = skipSpace(text, i + 1);
    if (i >= text.length) return none;
    if (key.value === "code") {
      if (text[i] !== '"') return none;
      const value = readString(text, i);
      return { code: value.value, complete: value.complete };
    }
    i = skipValue(text, i);
    if (i < 0) return none;
  }
}

function skipSpace(text, i) {
  while (i < text.length && /\s/.test(text[i])) i++;
  return i;
}

const ESCAPES = {
  '"': '"',
  "\\": "\\",
  "/": "/",
  b: "\b",
  f: "\f",
  n: "\n",
  r: "\r",
  t: "\t",
};

/** Decode a JSON string starting at the quote at `start`, as far as it goes. */
function readString(text, start) {
  let value = "";
  let i = start + 1;
  while (i < text.length) {
    const char = text[i];
    if (char === '"') return { value, complete: true, end: i + 1 };
    if (char !== "\\") {
      value += char;
      i++;
      continue;
    }
    const kind = text[i + 1];
    if (kind === undefined) break;
    if (kind === "u") {
      const hex = text.slice(i + 2, i + 6);
      if (hex.length < 4) break;
      if (!/^[0-9a-fA-F]{4}$/.test(hex)) break;
      value += String.fromCharCode(parseInt(hex, 16));
      i += 6;
      continue;
    }
    if (!(kind in ESCAPES)) break;
    value += ESCAPES[kind];
    i += 2;
  }
  return { value, complete: false, end: text.length };
}

/** The index after one JSON value, or -1 when it has not fully arrived. */
function skipValue(text, i) {
  if (text[i] === '"') {
    const value = readString(text, i);
    return value.complete ? value.end : -1;
  }
  let depth = 0;
  for (; i < text.length; i++) {
    const char = text[i];
    if (char === '"') {
      const value = readString(text, i);
      if (!value.complete) return -1;
      i = value.end - 1;
    } else if (char === "{" || char === "[") depth++;
    else if (char === "}" || char === "]") {
      if (depth === 0) return i;
      depth--;
      if (depth === 0) return i + 1;
    } else if (char === "," && depth === 0) return i;
  }
  return -1;
}

/**
 * Walk OpenSCAD source and call `visit(index, char, depth)` for each character
 * of code (not inside a string or comment), with the bracket depth before it.
 */
export function scanCode(source, visit) {
  let depth = 0;
  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    const next = source[i + 1];
    if (char === "/" && next === "/") {
      const end = source.indexOf("\n", i);
      i = end < 0 ? source.length : end - 1;
      continue;
    }
    if (char === "/" && next === "*") {
      const end = source.indexOf("*/", i + 2);
      i = end < 0 ? source.length : end + 1;
      continue;
    }
    if (char === '"') {
      let j = i + 1;
      while (j < source.length && source[j] !== '"')
        j += source[j] === "\\" ? 2 : 1;
      i = j;
      continue;
    }
    if (visit(i, char, depth) === false) return;
    if (char === "(" || char === "[" || char === "{") depth++;
    else if (char === ")" || char === "]" || char === "}")
      depth = Math.max(0, depth - 1);
  }
}

/**
 * The longest prefix that ends on a complete top-level statement: a `;` or a
 * closing `}` at bracket depth 0. A half-streamed file renders up to there.
 */
export function completePrefix(source) {
  let end = 0;
  scanCode(source, (i, char, depth) => {
    if ((char === ";" && depth === 0) || (char === "}" && depth === 1))
      end = i + 1;
  });
  return source.slice(0, end);
}

/** Lower every literal `$fn = n` above `cap` to `cap`; expressions are left as they are. */
export function capFn(source, cap) {
  return source.replace(
    /(\$fn\s*=\s*)(\d+(?:\.\d*)?|\.\d+)/g,
    (match, head, value) => (Number(value) > cap ? `${head}${cap}` : match),
  );
}
