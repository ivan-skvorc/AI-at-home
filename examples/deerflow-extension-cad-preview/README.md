# CAD model preview

A browser contribution that turns `.glb` and `.stl` files into a rotatable
model in DeerFlow's artifact panel, the Files view and the standalone reader.
It is the viewer for the [CAD module](../deerflow-extension-cad/README.md)'s
output (`part.glb`, `part.stl`, and `part.failed.glb` for a build that failed a
check), and it reads any GLB or STL inside the limits below. Files are read
through the host's authenticated artifact route; nothing is fetched from
anywhere else. It uses the host's optional `artifactPreviews` browser contract.

In this fork the package ships installed and enabled, like the CAD module, from
a committed copy in `backend/extensions/sources/`. Turn it off with
`make extension-disable NAME=cad-preview` and a Gateway restart; GLB and STL
files then show the download fallback, as they did before.

## What you see

- The model, lit and drawn with its feature edges, over the panel's own
  background, in light and dark themes. A theme change recolours it in place.
- **Orbit**: drag to rotate, scroll or pinch to zoom, right-drag to pan. With
  the model focused, arrow keys pan and Shift with an arrow key rotates.
- **Fit**, **Reset**, **Top**, **Front** and **Iso**, and an **Edges** toggle.
  The camera and the edge setting are restored when you come back to an
  unchanged file in the same session.
- `Bounding box X × Y × Z mm (from the mesh)` under the model, along the CAD
  axes with Z up. It is measured on the triangles, so a curved face can read up
  to the mesh tolerance under the CAD module's report, which measures the solid.
- On `*.failed.glb`, a banner says the build failed a check and names the
  report file to read.
- No animation: the view is drawn only when something changes, and it never
  rotates by itself.

The original file always downloads unchanged, from the panel's download button.

### Units and axes

glTF is metres and Y-up by definition, so a GLB is read as metres. The CAD
module writes its GLB with a root scale of 0.001 over millimetre vertices, which
reads as the part's real size. A part of several bodies, which the CAD module
writes as one node per body, is drawn whole, each body where it was modelled;
the bounding box is their union. A GLB written by the CAD module before that
change has no root scale and reads 1000 times too large. An STL has no unit; it
is read as millimetres, Z-up, which is what the CAD module and slicers use.

## Limits

When a limit is reached the panel says which one and offers the original
bytes as a download instead of a preview.

- **25 MiB per file**, the host's read cap. The host shows this reason itself.
- **1,000,000 triangles**, **1,000,000 vertices**, and **20,000 primitives or
  nodes**. Every count is summed from the file's declarations before an output
  array is allocated, so a small file cannot ask for a large allocation (an
  index list that repeats three vertices a million times, or one mesh instanced
  from thousands of nodes).
- **GLB**: a strict glTF 2.0 subset. The header, chunk lengths and 4-byte
  alignment are checked; the JSON chunk is at most 4 MiB. Buffers with a `uri`
  (external or data URIs) and any `extensionsRequired` entry (Draco, meshopt,
  quantization) are refused. Only triangle primitives with float positions
  and unsigned indices are drawn; every accessor and buffer view is checked
  against its buffer, every index against its vertex count, and the node tree
  for cycles, shared nodes and a depth over 64.
- **STL**: binary when 84 + 50 n equals the file length, even when the header
  starts with `solid`; otherwise a strict ASCII reader. NaN and infinite
  coordinates are refused.
- Feature edges are skipped above 600,000 triangles.
- **15 seconds**: each file is parsed in its own Worker, which is terminated
  when it answers, when the deadline passes, and when the preview closes.
  Only fixed diagnostic codes come back from it.

Disposing a preview cancels any pending frame, disconnects its observers,
disposes the controls, geometries and materials, releases the WebGL context
(`forceContextLoss`), shrinks and removes the canvas, terminates the Worker and
revokes its Blob URLs, so switching between many models keeps one live context.
If the browser drops the context anyway, the viewer says *Display lost* and
offers *Reload*. A browser without WebGL gets the host's download fallback.

## Build

The package includes its built browser modules. After editing `ui/`, rebuild
and commit `deerflow_extension_cad_preview/static/dist/` and `ui_manifest.json`:

```sh
cd examples/deerflow-extension-cad-preview
npm ci --ignore-scripts
node build.mjs
node notices.mjs   # after a dependency change
node --test
```

`three` is pinned exactly in `package.json` and `package-lock.json`. The Worker
is bundled as one self-contained module: Gateway serves plugin assets with
`Content-Security-Policy: sandbox`, so the Worker runs in an opaque origin and
cannot import further chunks. `build.mjs` fails when an asset grows past 3 MiB,
under the host's 4 MiB per-asset cap.

## Validation

```sh
cd examples/deerflow-extension-cad-preview && node --test && uv run --no-project pytest -q && cd ../..
uv run --project backend --no-sync python scripts/check_extension.py examples/deerflow-extension-cad-preview
cd frontend && pnpm exec playwright test cad-preview
```

The browser test serves the packaged module graph with the Gateway's CSP, opens
real CAD-module output in the panel and the reader at 1440 and 390 px wide, and
checks the bounding box against the build report, the context count over twenty
file switches, idle frames, the theme switch and both download fallbacks. WebGL
there runs on SwiftShader (`--enable-unsafe-swiftshader`, set in the spec). Its
fixtures are regenerated with the CAD module:

```sh
cd examples/deerflow-extension-cad
uv run --no-project python ../../frontend/tests/e2e/fixtures/cad-preview/generate-fixtures.py
cd ../../frontend && pnpm exec prettier --write tests/e2e/fixtures/cad-preview/*.json
```

See [third-party notices](THIRD_PARTY_NOTICES.md) for three.js.
