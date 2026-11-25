# CAD design page

A full-stack plugin: the Designs page, its design store and a lead middleware
that adds the design brief to design runs. The model follows the cad-modeling
skill in the design thread's per-thread container and renders each version into
`/mnt/user-data/outputs/design/v<N>/`; the page shows those folders.
`README.md` states the limits.

```bash
cd examples/deerflow-extension-cad-design
npm ci --ignore-scripts --no-audit --no-fund && node build.mjs && node --test
../../backend/.venv/bin/python -m pytest tests -q
uv run --project ../../backend --no-sync python ../../scripts/check_extension.py .
cd ../../backend && uv run pytest tests/test_bundled_cad_design_extension.py tests/test_cad_design_end_to_end.py tests/test_context_fit_critical.py -q
cd ../frontend && pnpm exec playwright test cad-design
```

- **Model-written code runs only in the per-thread container, never in the
  Gateway.** The backend stores titles and starts runs; it renders, parses and
  serves no design file. A server-side render, check or file route breaks that
  boundary. `container` in `get_design` (`HostPolicySnapshot.sandbox_container`)
  tells the page whether the host runs such containers, and the page shows the
  setup commands when it does not.
- **The version folders are the versions.** The store keeps designs only. Files
  from the first release also hold a `versions` table and a `head_version_id`
  column; they must keep opening (`tests/test_store.py`), so never alter or drop
  that schema.
- **The page reads files only through `context.threadFiles`**, under
  `/mnt/user-data/outputs/`, and parses meshes only through cad-preview's capped
  parsers: every file in a version folder is model-written, untrusted input.
- **The built bundle is committed.** After any edit under `ui/`, run
  `node build.mjs` and commit `static/dist/` with `ui_manifest.json`, then copy
  the package over `backend/extensions/sources/deerflow-extension-cad-design`
  (without `node_modules`, `.venv` or `__pycache__`); a bundled-extension test
  fails on drift. `ui/` imports cad-preview's `ui/` by relative path, so both
  packages stay side by side in the snapshot.
- **The brief reaches only design runs** and adds 0 tokens anywhere else, a
  forged `cad-design` run option included;
  `backend/tests/test_context_fit_critical.py` measures both. The host forwards
  only appended system text and removed tools from `MODEL_LOGICAL`, so test the
  middleware through the host's wrapper (`tests/test_middleware.py`,
  `backend/tests/test_cad_design_end_to_end.py`), never bare.
- **`resolve_config` keeps accepting `max_source_bytes`** and ignores it. An
  install whose `config.yaml` has not run migration 79 still carries the key,
  and refusing an unknown key would stop the extension from loading.
- **One WebGL context per design view, released on dispose**, and meshes are
  updated in place: a context per render runs into the browser's cap.
