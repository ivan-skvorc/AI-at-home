# CAD model preview

A browser-only `artifactPreviews` package that draws `.glb` and `.stl` files
with three.js. `README.md` states the limits and the units.

```bash
cd examples/deerflow-extension-cad-preview
npm ci --ignore-scripts --no-audit --no-fund && node build.mjs && node --test
uv run --project ../../backend --no-sync python ../../scripts/check_extension.py .
cd ../../frontend && pnpm exec playwright test cad-preview
```

- **The built bundles are committed.** After any edit under `ui/`, run
  `node build.mjs` and commit `static/dist/` with `ui_manifest.json`; the
  Gateway serves those files, never `ui/`. Once this package is bundled, copy
  it over `backend/extensions/sources/deerflow-extension-cad-preview` too
  (without `node_modules`, `.venv` or `__pycache__`).
- **The parsers are the boundary.** A file is hostile input to `glb.js` and
  `stl.js`. Sum every count from the file's declarations and check it against
  `LIMITS` before allocating; a test proves no large typed array exists when a
  cap is hit. A new glTF feature is a new check and a hostile-fixture test.
- **The Worker is one self-contained module.** Plugin assets carry
  `Content-Security-Policy: sandbox`, so the Worker's origin is opaque: no
  imports, no fetch. Keep `three` out of it; it posts back fixed codes only.
- **One WebGL context per mount, released in `dispose()`** in the order the
  README gives. Browsers cap live contexts at about sixteen; a leak shows up
  only after many file switches, which the e2e spec does.
- **Render on demand.** No animation loop, no damping, no auto-rotation: the
  idle-frame check fails on any of them.
- **GLB is metres and Y-up; STL is millimetres and Z-up.** The bounding box is
  reported in the CAD frame (Z up) and compared with the CAD report in e2e.
