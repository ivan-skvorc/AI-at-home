import assert from "node:assert/strict";
import test from "node:test";

import {
  FOLDER,
  MAX_BODIES,
  MAX_LINES,
  PALETTE,
  bodiesOf,
  checkSummary,
  designFolder,
  fileKey,
  filesByName,
  hasFolder,
  parseJson,
  printSummary,
  renderSummary,
  versionNumbers,
  viewImages,
} from "../ui/files.js";

const entry = (name, kind = "file", extra = {}) => ({
  name,
  path: `${FOLDER}/v1/${name}`,
  kind,
  size: 10,
  modified_at: "2026-11-25T10:00:00Z",
  ...extra,
});
const files = (...names) => filesByName(names.map((name) => entry(name)));
const encode = (value) => new TextEncoder().encode(JSON.stringify(value));

// What cadkit.py render writes for a two-body model, as in cmd_render.
const REPORT = {
  version: "v1",
  model: "/mnt/user-data/workspace/design/model.scad",
  defines: [],
  bodies: {
    base: {
      file: "base.stl",
      size_mm: [60, 40, 6],
      min_mm: [-30, -20, 0],
      max_mm: [30, 20, 6],
      triangles: 1204,
      watertight: true,
      shells: 1,
      area_mm2: 6100.5,
      volume_mm3: 14249.2,
      solid_mass_g_pla: 17.7,
      center_of_mass_mm: [0, 0, 3],
    },
    lid: { error: "ERROR: Parser error in line 4", file: "lid.stl" },
  },
  warnings: ["base: WARNING: Ignoring unknown variable 'wal'"],
  echo: ['base: "wall" = 2'],
  seconds: 3.4,
  assembled: {
    clashes: [
      { pair: ["base", "lid"], overlap_mm3: 12.5, where: "x 0.0..1.0" },
    ],
    gaps: [],
  },
};

test("version folders are the v<N> directories, oldest first", () => {
  assert.deepEqual(
    versionNumbers([
      entry("v10", "directory"),
      entry("v2", "directory"),
      entry("v2", "directory"),
      entry("v1", "directory"),
      entry("v3", "file"),
      entry("v4", "symlink"),
      entry("v0", "directory"),
      entry("v01", "directory"),
      entry("v1000000", "directory"),
      entry("draft", "directory"),
      { kind: "directory" },
      null,
    ]),
    [1, 2, 10],
  );
  assert.deepEqual(versionNumbers("nope"), []);
});

test("the design folder is the backend's only when it is a plain outputs path", () => {
  assert.equal(designFolder("/mnt/user-data/outputs/design"), FOLDER);
  assert.equal(
    designFolder("/mnt/user-data/outputs/other/part"),
    "/mnt/user-data/outputs/other/part",
  );
  for (const value of [
    null,
    "/mnt/user-data/uploads/x",
    "/mnt/user-data/outputs",
    "/mnt/user-data/outputs/../workspace",
    "/mnt/user-data/outputs/a//b",
    "/mnt/user-data/outputs/a b",
  ])
    assert.equal(designFolder(value), FOLDER);
});

test("listings keep plain files by name and name their subfolders", () => {
  const listing = [
    entry("base.stl"),
    entry("views", "directory"),
    entry("link.stl", "symlink"),
    entry("a\\b"),
  ];
  assert.deepEqual([...filesByName(listing).keys()], ["base.stl"]);
  assert.equal(hasFolder(listing, "views"), true);
  assert.equal(hasFolder(listing, "print"), false);
  assert.notEqual(
    fileKey(entry("a.stl")),
    fileKey(entry("a.stl", "file", { size: 11 })),
  );
});

test("JSON is an object or nothing", () => {
  assert.deepEqual(parseJson(encode({ a: 1 })), { a: 1 });
  assert.equal(parseJson(encode([1])), null);
  assert.equal(parseJson(new TextEncoder().encode("{not json")), null);
});

test("bodies come from report.json in order, with their colour and STL", () => {
  const bodies = bodiesOf(REPORT, files("base.stl", "lid.stl", "report.json"));
  assert.deepEqual(
    bodies.map(({ name, color, file, error }) => ({
      name,
      color,
      file,
      error,
    })),
    [
      { name: "base", color: PALETTE[0], file: "base.stl", error: null },
      {
        name: "lid",
        color: PALETTE[1],
        file: null,
        error: "ERROR: Parser error in line 4",
      },
    ],
  );
  assert.deepEqual(bodies[0].size, [60, 40, 6]);
  assert.equal(bodies[0].volume, 14249.2);
  assert.equal(bodies[0].mass, 17.7);
  assert.equal(bodies[0].watertight, true);
  // A body whose STL is not in the folder has nothing to draw.
  assert.equal(bodiesOf(REPORT, files("report.json"))[0].file, null);
});

test("hostile report entries are skipped, cut or capped", () => {
  const bodies = {};
  bodies["../evil"] = { file: "../evil.stl" };
  bodies["a b"] = {};
  bodies.ok = {
    file: "/etc/passwd",
    size_mm: [1, "2", 3],
    volume_mm3: Infinity,
    watertight: "yes",
    error: 7,
  };
  for (let i = 0; i < MAX_BODIES + 5; i++) bodies[`b${i}`] = {};
  const shown = bodiesOf({ bodies }, files("ok.stl"));
  assert.equal(shown.length, MAX_BODIES);
  assert.equal(shown[0].name, "ok");
  // The STL is always <name>.stl from the listing, never the report's path.
  assert.equal(shown[0].file, "ok.stl");
  assert.equal(shown[0].size, null);
  assert.equal(shown[0].volume, null);
  assert.equal(shown[0].watertight, false);
  assert.equal(shown[0].error, null);
  const long = bodiesOf(
    { bodies: { x: { error: "e".repeat(5000) } } },
    files(),
  );
  assert.equal(long[0].error.length, 300);
});

test("without a report the folder's STL files stand in", () => {
  const bodies = bodiesOf(
    undefined,
    files("lid.stl", "base.stl", "x y.stl", "a.glb"),
  );
  assert.deepEqual(
    bodies.map((b) => [b.name, b.file, b.color]),
    [
      ["base", "base.stl", PALETTE[0]],
      ["lid", "lid.stl", PALETTE[1]],
    ],
  );
  assert.deepEqual(bodiesOf(null, files()), []);
});

test("the render summary carries the time, warnings and overlaps as modelled", () => {
  assert.deepEqual(renderSummary(REPORT), {
    seconds: 3.4,
    warnings: ["base: WARNING: Ignoring unknown variable 'wal'"],
    echo: 1,
    clashes: [{ pair: "base / lid", volume: 12.5, where: "x 0.0..1.0" }],
  });
  assert.equal(renderSummary(null), null);
  const noisy = renderSummary({ warnings: Array(100).fill("w"), seconds: "3" });
  assert.equal(noisy.warnings.length, MAX_LINES);
  assert.equal(noisy.seconds, null);
});

test("the collision summary lists overlaps per pose state, capped", () => {
  const clash = { pair: ["arm", "base"], overlap_mm3: 3.2, where: "x 1..2" };
  const check = {
    version: "v1",
    clearance_mm: 0.3,
    states: 30,
    clashes: 30,
    results: Array.from({ length: 30 }, (_, i) => ({
      pose: "swing",
      state: `arm=${i}`,
      clashes: [clash],
      gaps: [],
    })),
  };
  const summary = checkSummary(check);
  assert.equal(summary.states, 30);
  assert.equal(summary.clearance, 0.3);
  assert.equal(summary.findings.length, MAX_LINES);
  assert.equal(summary.more, 10);
  assert.deepEqual(summary.findings[0], {
    pose: "swing",
    state: "arm=0",
    pair: "arm / base",
    volume: 3.2,
    where: "x 1..2",
  });
  assert.deepEqual(
    checkSummary({ states: 4, clashes: 0, results: "x" }).findings,
    [],
  );
  assert.equal(checkSummary("x"), null);
});

test("the print summary carries the problems and the slicer's numbers", () => {
  const print = {
    version: "v1/print",
    bed_mm: [220, 220, 250],
    layout_mm: [120, 60, 20],
    problems: ["lid: bridge spans 30 mm (> 10) at x 0..30", 5],
    slicer: {
      filament_g: "23.4",
      time: "1h 12m",
      settings: "0.4 mm nozzle, 0.2 mm layers",
      gcode: "print.gcode",
    },
  };
  assert.deepEqual(printSummary(print), {
    layout: [120, 60, 20],
    bed: [220, 220, 250],
    problems: ["lid: bridge spans 30 mm (> 10) at x 0..30"],
    more: 0,
    slicer: {
      error: null,
      skipped: null,
      filament: "23.4",
      time: "1h 12m",
      settings: "0.4 mm nozzle, 0.2 mm layers",
    },
  });
  assert.equal(
    printSummary({ slicer: { skipped: "run with --slice" } }).slicer.skipped,
    "run with --slice",
  );
  assert.equal(printSummary([]), null);
});

test("view images are the PNGs, shaded before sections", () => {
  assert.deepEqual(
    viewImages(files("sections.png", "shaded-open.png", "shaded.png", "a.txt")),
    ["shaded-open.png", "shaded.png", "sections.png"],
  );
});
