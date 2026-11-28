/**
 * Reading a design's version folders, kept pure so `node --test` covers it.
 *
 * Every file under the folder is written by model-run code in the design's
 * container, so each value here is untrusted: names are matched before they
 * become paths, numbers must be finite, text is cut, and lists are capped. The
 * page renders the results with textContent only.
 */

/** The folder the backend names in get_design when it says nothing else. */
export const FOLDER = "/mnt/user-data/outputs/design";
/** cadkit.py's PALETTE: body N has the colour it has in assembly.glb and shaded.png. */
export const PALETTE = [
  "#4C78A8",
  "#F58518",
  "#54A24B",
  "#E45756",
  "#72B7B2",
  "#B279A2",
  "#EECA3B",
  "#9D755D",
  "#FF9DA6",
  "#BAB0AC",
];
/** report.json, check.json and print.json are read up to this size. */
export const MAX_JSON_BYTES = 1024 * 1024;
/** model.scad is shown up to this size; a larger file is a download. */
export const MAX_SOURCE_BYTES = 512 * 1024;
export const MAX_BODIES = 64;
export const MAX_LINES = 20;
const MAX_LINE_CHARS = 300;
const MAX_VERSION = 100_000;
const VERSION = /^v([1-9][0-9]{0,5})$/;
/** cadkit's body names: letters, digits, '-' or '_', at most 40. */
const BODY = /^[A-Za-z0-9_-]{1,40}$/;
/**
 * A file the Files tab may link: one plain name, no path, and none of the
 * characters the host's threadFiles refuses (services.ts checkThreadFile), so
 * every name kept here is one the host will build a URL for.
 */
const FILE = /^(?!\.\.?$)[^/\\\u0000-\u001f\u007f]{1,255}$/;

const record = (value) =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const finite = (value) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const triple = (value) =>
  Array.isArray(value) && value.length === 3 && value.every(Number.isFinite)
    ? value.slice()
    : null;
/** One bounded line of text, or "" for anything that is not a string. */
export const line = (value) =>
  typeof value === "string"
    ? value.replace(/\s+/g, " ").trim().slice(0, MAX_LINE_CHARS)
    : "";
const lines = (value, limit = MAX_LINES) =>
  (Array.isArray(value) ? value : []).map(line).filter(Boolean).slice(0, limit);

/** The folder a design renders into: the backend's when it is a plain outputs path. */
export function designFolder(value) {
  return typeof value === "string" &&
    /^\/mnt\/user-data\/outputs(\/[A-Za-z0-9_.-]+)+$/.test(value) &&
    !value.split("/").some((part) => part === "." || part === "..")
    ? value
    : FOLDER;
}

/** Version numbers among a design folder's entries, oldest first. */
export function versionNumbers(entries) {
  const numbers = new Set();
  for (const entry of Array.isArray(entries) ? entries : []) {
    if (entry?.kind !== "directory" || typeof entry.name !== "string") continue;
    const match = VERSION.exec(entry.name);
    if (match && Number(match[1]) <= MAX_VERSION) numbers.add(Number(match[1]));
  }
  return [...numbers].sort((a, b) => a - b);
}

/** Plain files of a listing by name, links and folders left out. */
export function filesByName(entries) {
  const files = new Map();
  for (const entry of Array.isArray(entries) ? entries : [])
    if (entry?.kind === "file" && FILE.test(entry.name ?? ""))
      files.set(entry.name, entry);
  return files;
}

/** Whether a listing has a subfolder of this name (views/, print/). */
export const hasFolder = (entries, name) =>
  (Array.isArray(entries) ? entries : []).some(
    (entry) => entry?.kind === "directory" && entry.name === name,
  );

/** A cache key that changes when the file is rewritten. */
export const fileKey = (entry) =>
  `${entry.path}\u0000${entry.size ?? ""}\u0000${entry.modified_at ?? ""}`;

/** Parse JSON bytes into an object, or null for anything else. */
export function parseJson(bytes) {
  try {
    const value = JSON.parse(new TextDecoder().decode(bytes));
    return record(value) ? value : null;
  } catch {
    return null;
  }
}

/**
 * The bodies of a version: report.json's entries in order, each with its
 * colour and the STL the folder holds for it. Without a usable report (the
 * render is still running, or the file is malformed) the folder's STL files
 * stand in, so the preview still shows what exists.
 */
export function bodiesOf(report, files) {
  const bodies = [];
  const stl = (name) => (files.has(`${name}.stl`) ? `${name}.stl` : null);
  if (record(report?.bodies)) {
    for (const [name, info] of Object.entries(report.bodies)) {
      if (bodies.length === MAX_BODIES) break;
      if (!BODY.test(name) || !record(info)) continue;
      const error = line(info.error);
      bodies.push({
        name,
        color: PALETTE[bodies.length % PALETTE.length],
        file: error ? null : stl(name),
        error: error || null,
        size: triple(info.size_mm),
        volume: finite(info.volume_mm3),
        mass: finite(info.solid_mass_g_pla),
        triangles: finite(info.triangles),
        watertight: info.watertight === true,
        shells: finite(info.shells),
      });
    }
    return bodies;
  }
  for (const name of [...files.keys()].sort()) {
    if (bodies.length === MAX_BODIES) break;
    const match = /^([A-Za-z0-9_-]{1,40})\.stl$/.exec(name);
    if (!match) continue;
    bodies.push({
      name: match[1],
      color: PALETTE[bodies.length % PALETTE.length],
      file: name,
      error: null,
      size: null,
      volume: null,
      mass: null,
      triangles: null,
      watertight: null,
      shells: null,
    });
  }
  return bodies;
}

const pair = (value) =>
  Array.isArray(value) && value.length === 2
    ? value.map(line).join(" / ")
    : "?";

/** report.json as the Checks tab shows it. */
export function renderSummary(report) {
  if (!record(report)) return null;
  const clashes = record(report.assembled)
    ? (Array.isArray(report.assembled.clashes) ? report.assembled.clashes : [])
        .filter(record)
        .slice(0, MAX_LINES)
        .map((clash) => ({
          pair: pair(clash.pair),
          volume: finite(clash.overlap_mm3),
          where: line(clash.where),
        }))
    : [];
  return {
    seconds: finite(report.seconds),
    warnings: lines(report.warnings),
    echo: Array.isArray(report.echo) ? report.echo.length : 0,
    clashes,
  };
}

/** check.json: the overlaps per pose state, one line per finding, capped. */
export function checkSummary(check) {
  if (!record(check)) return null;
  const findings = [];
  let more = 0;
  for (const result of Array.isArray(check.results) ? check.results : []) {
    if (!record(result)) continue;
    for (const clash of Array.isArray(result.clashes) ? result.clashes : []) {
      if (!record(clash)) continue;
      if (findings.length === MAX_LINES) {
        more += 1;
        continue;
      }
      findings.push({
        pose: line(result.pose),
        state: line(result.state),
        pair: pair(clash.pair),
        volume: finite(clash.overlap_mm3),
        where: line(clash.where),
      });
    }
  }
  return {
    states: finite(check.states),
    clashes: finite(check.clashes),
    clearance: finite(check.clearance_mm),
    findings,
    more,
  };
}

/** print.json: the problems cadkit and the slicer found, and the slicer's numbers. */
export function printSummary(print) {
  if (!record(print)) return null;
  const problems = Array.isArray(print.problems) ? print.problems : [];
  const slicer = record(print.slicer) ? print.slicer : {};
  return {
    layout: triple(print.layout_mm),
    bed: triple(print.bed_mm),
    problems: lines(problems),
    more: Math.max(0, problems.length - MAX_LINES),
    slicer: {
      error: line(slicer.error) || null,
      skipped: line(slicer.skipped) || null,
      filament: line(slicer.filament_g) || null,
      time: line(slicer.time) || null,
      settings: line(slicer.settings) || null,
    },
  };
}

/** PNG images of a version's views/ folder: shaded first, then sections, by name. */
export function viewImages(files) {
  return [...files.keys()]
    .filter((name) => /\.png$/i.test(name))
    .sort((a, b) => {
      const rank = (name) => (name.startsWith("shaded") ? 0 : 1);
      return rank(a) - rank(b) || a.localeCompare(b);
    });
}
