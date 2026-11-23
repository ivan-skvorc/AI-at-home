# CAD design page

A full-stack plugin: the Designs page, its design store, the `scad_draft` tool
and a middleware that scopes it. The model writes OpenSCAD, the viewer's browser
renders it, and Finalize hands the draft to the CAD module's `cad_build`.
`README.md` states the limits.

```bash
cd examples/deerflow-extension-cad-design
npm ci --ignore-scripts --no-audit --no-fund && node build.mjs && node --test
../../backend/.venv/bin/python -m pytest tests -q
uv run --project ../../backend --no-sync python ../../scripts/check_extension.py .
cd ../../backend && uv run pytest tests/test_bundled_cad_design_extension.py tests/test_context_fit_critical.py -q
cd ../frontend && pnpm exec playwright test cad-design
```

- **The Gateway never runs model-written code.** `scad_draft` only stores the
  file; OpenSCAD runs in a browser Worker and CadQuery only inside `cad_build`.
  A server-side render or check of a draft breaks the design's trust boundary.
- **The built bundle is committed.** After any edit under `ui/`, run
  `node build.mjs` and commit `static/dist/` with `ui_manifest.json`, then copy
  the package over `backend/extensions/sources/deerflow-extension-cad-design`
  (without `node_modules`, `.venv` or `__pycache__`); a bundled-extension test
  fails on drift. `ui/` imports cad-preview's `ui/` by relative path, so both
  packages stay side by side in the snapshot.
- **The Workers are single modules that fetch nothing.** Plugin assets carry
  `Content-Security-Policy: sandbox`, so the page fetches the wasm, checks the
  SHA-256 baked into the bundle and posts the bytes to the Worker. The build
  fails if the OpenSCAD runtime keeps a network path.
- **The tool reaches only design runs.** The middleware removes `scad_draft`
  from every model call without the `cad-design` run option and adds 0 tokens
  there; `backend/tests/test_context_fit_critical.py` measures both phases.
  Keep the brief and the version note inside that budget. The host forwards only
  removed tools and appended system text from `MODEL_LOGICAL`, so test the
  middleware through the host's wrapper
  (`backend/tests/test_cad_design_end_to_end.py`), never bare.
- **One WebGL context per design view, released on dispose**, and the mesh is
  updated in place: a context per render runs into the browser's cap.
- **At most one automatic repair per model version**, stored with the version,
  so a draft that keeps failing cannot loop runs.
- **The OpenSCAD build has no fonts**, so `text()` does not render in the
  browser; the drafting brief tells the model to avoid it.
