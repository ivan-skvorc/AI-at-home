// A small OpenSCAD tokenizer for CodeMirror's StreamLanguage: highlighting
// only, no parsing. Pure, so node can test it with CodeMirror's StringStream.

const KEYWORDS = new Set([
  "module",
  "function",
  "if",
  "else",
  "for",
  "let",
  "each",
  "intersection_for",
  "assert",
  "include",
  "use",
]);
const ATOMS = new Set(["true", "false", "undef", "PI"]);
const BUILTINS = new Set(
  (
    "cube sphere cylinder polyhedron square circle polygon text import surface " +
    "translate rotate scale resize mirror multmatrix color offset hull minkowski " +
    "union difference intersection linear_extrude rotate_extrude projection render children " +
    "echo abs sign sin cos tan asin acos atan atan2 floor round ceil ln log pow sqrt exp " +
    "len min max norm cross concat lookup str chr ord search version version_num " +
    "is_undef is_bool is_num is_string is_list is_function rands"
  ).split(" "),
);

export const openscadMode = {
  name: "openscad",
  startState: () => ({ comment: false, afterDefinition: false }),
  token(stream, state) {
    if (state.comment) {
      if (stream.match(/^.*?\*\//)) state.comment = false;
      else stream.skipToEnd();
      return "comment";
    }
    if (stream.eatSpace()) return null;
    if (stream.match("//")) {
      stream.skipToEnd();
      return "comment";
    }
    if (stream.match("/*")) {
      state.comment = true;
      if (stream.match(/^.*?\*\//)) state.comment = false;
      else stream.skipToEnd();
      return "comment";
    }
    if (stream.peek() === '"') {
      stream.next();
      let escaped = false;
      for (let char = stream.next(); char !== undefined; char = stream.next()) {
        if (char === '"' && !escaped) break;
        escaped = !escaped && char === "\\";
      }
      return "string";
    }
    if (stream.match(/^(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/)) return "number";
    if (stream.match(/^\$[A-Za-z_]\w*/)) return "atom";
    const word = stream.match(/^[A-Za-z_]\w*/);
    if (word) {
      const text = word[0];
      if (state.afterDefinition) {
        state.afterDefinition = false;
        return "def";
      }
      if (KEYWORDS.has(text)) {
        state.afterDefinition = text === "module" || text === "function";
        return "keyword";
      }
      if (ATOMS.has(text)) return "atom";
      if (BUILTINS.has(text)) return "builtin";
      return "variableName";
    }
    stream.next();
    return null;
  },
  languageData: {
    commentTokens: { line: "//", block: { open: "/*", close: "*/" } },
  },
};
