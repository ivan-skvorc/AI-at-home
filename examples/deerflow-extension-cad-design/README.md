# deerflow-extension-cad-design

The CAD design page (`/workspace/extensions/cad-design/designs`). Draft a part
with the assistant in OpenSCAD, see it rendered in your browser, edit the code
or drag parameter sliders, step through automatic versions, and finalize the
draft as a checked CadQuery part through the CAD module's `cad_build`.

- The model tool `scad_draft` only stores the file as a version. The page
  renders it with OpenSCAD compiled to WebAssembly in the viewer's browser; the
  Gateway never executes model-written OpenSCAD or Python.
- The tool and the design brief reach only design runs: a lead middleware at
  `MODEL_LOGICAL`, the one placement whose tool removals and appended system
  text the host hands on, removes the tool from every other model call, so
  ordinary conversations pay no tokens for it
  (`backend/tests/test_context_fit_critical.py`,
  `backend/tests/test_cad_design_end_to_end.py`). Delegated subagents never
  receive it.
- A prompt or repair turn that saves no draft says so in the conversation; the
  preview stays as it was.
- Designs and versions are stored per user in SQLite under `DEER_FLOW_HOME`
  (`storage_path`, default `cad-design/designs.sqlite`); deleted designs go to a
  trash inside the page. "Delete forever" also deletes the design's
  conversation thread with its drafts and build files (`delete_thread`, API
  0.2.14), because that thread is hidden from the chat lists.
- Finalize judges the CadQuery part's size against the draft's rendered size
  within 0.5 mm or 2 % per axis, whichever is larger: the draft is a faceted
  mesh, so `cad_build`'s own 0.1 % box check alone is not a wrong size. Because
  `cad_build` exports the part only when every check passes, such a build is
  rebuilt once against the measured size, and Finalize reports built only when
  a STEP, GLB, STL or 3MF was exported.
- Only the file's own errors are stored as a version's render. When the engine
  fails to load, crashes or times out, nothing is stored and no automatic repair
  starts; a later good render replaces a stored failure.

Configuration (`plugins:` record `cad-design` in `config.yaml`):

```yaml
config:
  enabled: true
  storage_path: cad-design/designs.sqlite
  max_source_bytes: 65536
```

Tests:

```bash
cd examples/deerflow-extension-cad-design
uv pip install --python ../../backend/.venv/bin/python -e '.[dev]'
../../backend/.venv/bin/python -m pytest tests -q
```

The browser bundle includes OpenSCAD (GPL-2.0-or-later); see
`THIRD_PARTY_NOTICES.md`.
