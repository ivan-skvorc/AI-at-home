import { scanCode } from "./scad-text.js";

const NUMBER = "[+-]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][+-]?\\d+)?";
const ASSIGNMENT = new RegExp(
  `^([A-Za-z_][A-Za-z0-9_]*)[ \\t]*=[ \\t]*(${NUMBER}|true|false)[ \\t]*;[ \\t]*(?://[ \\t]*\\[([^\\]\\n]*)\\])?`,
);

/** Offsets of the lines that start at bracket depth 0, outside comments and strings. */
function topLevelLineStarts(source) {
  const depthAt = new Map();
  scanCode(source, (index, _char, depth) => {
    depthAt.set(index, depth);
  });
  const starts = [];
  let offset = 0;
  for (const line of source.split("\n")) {
    const lead = line.length - line.trimStart().length;
    if (depthAt.get(offset + lead) === 0) starts.push(offset + lead);
    offset += line.length + 1;
  }
  return starts;
}

const decimals = (value) => {
  const text = String(value);
  if (/e-/i.test(text)) return Math.min(6, Number(text.split(/e-/i)[1]));
  return Math.min(6, (text.split(".")[1] ?? "").length);
};

function customizerRange(spec) {
  if (spec === undefined) return null;
  const parts = spec.split(":").map((part) => part.trim());
  if (!parts.every((part) => new RegExp(`^${NUMBER}$`).test(part))) return null;
  const values = parts.map(Number);
  if (values.length === 1 && values[0] > 0)
    return { min: 0, step: null, max: values[0] };
  if (values.length === 2 && values[0] < values[1])
    return { min: values[0], step: null, max: values[1] };
  if (values.length === 3 && values[0] < values[2] && values[1] > 0)
    return { min: values[0], step: values[1], max: values[2] };
  return null;
}

function derivedRange(value) {
  const span = value === 0 ? 10 : Math.abs(value);
  const min = value >= 0 ? 0 : value - span;
  const max = value + span;
  return { min, max };
}

function stepFor(value, min, max) {
  const places = Math.max(decimals(value), decimals(min), decimals(max));
  if (places > 0) return 10 ** -places;
  return max - min > 2 ? 1 : 0.1;
}

/**
 * The file's top-level `name = number|true|false;` assignments, the last one
 * of each name (OpenSCAD's rule), with the Customizer range of an optional
 * `// [min:max]` or `// [min:step:max]` comment, or a derived range.
 */
export function parseParameters(source) {
  const found = new Map();
  for (const start of topLevelLineStarts(source)) {
    const match = ASSIGNMENT.exec(
      source.slice(
        start,
        source.indexOf("\n", start) < 0
          ? undefined
          : source.indexOf("\n", start),
      ),
    );
    if (!match) continue;
    const [, name, raw, spec] = match;
    const valueStart = start + match[0].indexOf(raw, name.length);
    const position = { start: valueStart, end: valueStart + raw.length };
    if (raw === "true" || raw === "false") {
      found.delete(name);
      found.set(name, {
        name,
        kind: "boolean",
        value: raw === "true",
        ...position,
      });
      continue;
    }
    const value = Number(raw);
    if (!Number.isFinite(value)) continue;
    const range = customizerRange(spec);
    const { min, max } = range ?? derivedRange(value);
    const step = range?.step ?? stepFor(value, min, max);
    found.delete(name);
    found.set(name, {
      name,
      kind: "number",
      value,
      min: Math.min(min, value),
      max: Math.max(max, value),
      step,
      derived: !range,
      ...position,
    });
  }
  return [...found.values()];
}

/** A value as OpenSCAD source: booleans as words, numbers with at most six places. */
export function formatValue(value) {
  if (typeof value === "boolean") return String(value);
  return String(Number(Number(value).toFixed(6)));
}

/** Replace one parameter's value in the source; an unknown name changes nothing. */
export function rewriteParameter(source, name, value) {
  const param = parseParameters(source).find((p) => p.name === name);
  if (
    !param ||
    typeof value !== (param.kind === "boolean" ? "boolean" : "number")
  )
    return source;
  if (param.kind === "number" && !Number.isFinite(value)) return source;
  // Six places at most: a slider value carries float noise such as 7.250000001.
  const text = formatValue(value);
  return source.slice(0, param.start) + text + source.slice(param.end);
}

/** Apply several `{name: value}` changes. */
export function withValues(source, values) {
  let next = source;
  for (const [name, value] of Object.entries(values))
    next = rewriteParameter(next, name, value);
  return next;
}
