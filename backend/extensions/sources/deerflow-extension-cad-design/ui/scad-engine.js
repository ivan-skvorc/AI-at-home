// The Worker's logic, kept apart from the Worker so node can run it with the
// shipped WebAssembly bytes. One fresh OpenSCAD instance per render, from one
// compiled module: OpenSCAD's main() keeps global state between runs.

const MAX_LINES = 200;
const MAX_LINE = 500;
const NOISE = /^Could not initialize localization/;
const LINE = /\bline (\d+)\b/;

/** Pick the first error, the warnings and the source lines they name out of OpenSCAD's output. */
export function parseLog(lines) {
  const log = [];
  const warnings = [];
  const errorLines = new Set();
  let error = null;
  for (const raw of lines) {
    const line = String(raw ?? "").slice(0, MAX_LINE);
    if (!line.trim() || NOISE.test(line)) continue;
    if (log.length < MAX_LINES) log.push(line);
    const kind = /^(ERROR|WARNING|TRACE):\s*/.exec(line);
    const named = LINE.exec(line);
    if (kind?.[1] === "ERROR") {
      error ??= line.slice(kind[0].length);
      if (named) errorLines.add(Number(named[1]));
    } else if (kind?.[1] === "WARNING") {
      if (warnings.length < 50) warnings.push(line.slice(kind[0].length));
      if (named) errorLines.add(Number(named[1]));
    } else if (/^Current top level object is empty/.test(line)) error ??= line;
  }
  return {
    log,
    warnings,
    error,
    errorLines: [...errorLines].sort((a, b) => a - b),
  };
}

/**
 * Render `code` to binary STL with a fresh instance of `factory` (the
 * Emscripten OpenSCAD factory) over `wasmModule` (a compiled
 * WebAssembly.Module). Never throws: a failure is `{ok: false, error}`.
 */
export async function renderScad(factory, wasmModule, code) {
  const started = Date.now();
  const lines = [];
  const push = (text) => {
    if (lines.length < MAX_LINES * 4) lines.push(text);
  };
  let stl = null;
  let exit = -1;
  try {
    const instance = await factory({
      noInitialRun: true,
      noExitRuntime: true,
      print: push,
      printErr: push,
      instantiateWasm(imports, receive) {
        WebAssembly.instantiate(wasmModule, imports).then((made) =>
          receive(made),
        );
        return {};
      },
    });
    instance.FS.writeFile("/input.scad", code);
    exit = instance.callMain([
      "/input.scad",
      "-o",
      "/output.stl",
      "--export-format=binstl",
      "--backend=manifold",
    ]);
    try {
      stl = instance.FS.readFile("/output.stl");
    } catch {
      stl = null;
    }
  } catch (caught) {
    push(
      `ERROR: OpenSCAD stopped (${String(caught?.message ?? caught).slice(0, 200)})`,
    );
  }
  const parsed = parseLog(lines);
  const ok = exit === 0 && stl instanceof Uint8Array && stl.length > 84;
  return {
    ok,
    stl: ok ? stl : null,
    error: ok ? null : (parsed.error ?? `OpenSCAD exited with ${exit}`),
    errorLines: parsed.errorLines,
    warnings: parsed.warnings,
    log: parsed.log,
    ms: Date.now() - started,
  };
}
