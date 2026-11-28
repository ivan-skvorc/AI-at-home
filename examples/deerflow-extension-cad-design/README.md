# deerflow-extension-cad-design

The CAD design page (`/workspace/extensions/cad-design/designs`). Each design is
a conversation with the assistant beside the versions it renders: the
assistant follows the `cad-modeling` skill in the conversation's per-thread CAD
container (multi-body OpenSCAD, one STL per body, clash and gap checks across
poses and sweeps, sections and a shaded render, print and strength checks,
STEP and 3MF export), and the page shows each version's bodies in 3D, its view
images, its checks and its files.

- **It needs the container sandbox with the CAD image.** Run
  `make sandbox-cad-image`, then `make sandbox-enable MODE=container IMAGE=cad`,
  and restart the Gateway. Until then the page shows those commands, and a
  design run is told to give the user the same commands and stop. That holds
  whenever the host runs no per-thread containers, even with a `bash` tool:
  host bash would run the CAD code beside the Gateway, and the AIO provider's
  external mode shares one container, and so one design folder, between every
  thread. Large STEP exports may need `DEER_FLOW_SANDBOX_MEMORY=4g` in the
  Gateway's environment (the container's cap is 2 GiB).
- **The Gateway runs no model-written code.** The backend actions store designs
  and start runs; cadkit runs in the design thread's own container.
- **Versions are folders.** A design's thread always works in
  `/mnt/user-data/outputs/design`: the model edits
  `/mnt/user-data/workspace/design/model.scad` in place, and every
  `cadkit.py render --design /mnt/user-data/outputs/design --print-layout` writes
  the next `v<N>/` (the `.scad`, one STL per body, `assembly.glb`,
  `report.json`, `views/`, `print/`, and after export the STEP files and
  `bodies.3mf`). The page lists and reads those folders through the host's
  thread file routes (`context.threadFiles`, outputs only, owner-checked,
  usable while a run streams), shows the newest by default, and lists them again
  on each tool result and when the run settles.
- **The tabs.** Preview draws every body of the selected version in its own
  colour, each with a show/hide switch; Views shows the PNGs; Checks summarises
  `report.json`, `check.json` and `print/print.json`; Code shows the version's
  `model.scad` read-only; Files links every file for download.
- **A message names an older version.** When the user writes while looking at
  an older version, the message tells the model which one
  (`prompt` with `viewing` and `newest`).
- **The chat's model picker, mode and effort.** The composer row holds the
  host's composer controls (`context.composerControls`): the same searchable,
  sorted model picker, mode menu (Flash to Double Plus Ultracode; Democracy
  starts from its own dialog) and reasoning-effort menu as the chat, with the
  choice kept per page in this browser. Each prompt sends their `runContext()`
  as `context`; `prompt` keeps only the keys the chat sends (model, mode,
  thinking, plan mode, subagents and their limits, effort, Democracy roster,
  other plugins' `plugin_options`), checks their types and bounds, drops the
  rest, and always sets the `cad-design` option itself. On a host without the
  controls the page shows no choice and the server's default model and mode
  apply. The Gateway still enforces model access and the mode rules.
- **The brief reaches only design runs.** A lead middleware at `MODEL_LOGICAL`
  appends a short design brief to the system message of a run whose
  `cad-design` option names a live design whose thread is the run's own;
  everything else, a forged option included, pays no tokens for it
  (`backend/tests/test_context_fit_critical.py`,
  `backend/tests/test_cad_design_end_to_end.py`).
- **Designs and the trash.** Designs are stored per user in SQLite under
  `DEER_FLOW_HOME` (`storage_path`, default `cad-design/designs.sqlite`);
  deleted designs go to a trash inside the page. "Delete forever" also deletes
  the design's conversation thread with every version folder (`delete_thread`),
  because that thread is hidden from the chat lists.

Backend actions: `list_designs`, `create_design`, `get_design` (the design, the
fixed `folder` and the host's `container` flag), `rename_design`,
`delete_design`, `restore_design`, `purge_design`, `prompt`, `messages` (each
tool call as its name and one bounded line of its arguments), `run_status` and
`cancel`. It needs extension API 0.2.15
(`HostPolicySnapshot.sandbox_container`).

Configuration (`plugins:` record `cad-design` in `config.yaml`):

```yaml
config:
  enabled: true
  storage_path: cad-design/designs.sqlite
```

`max_source_bytes`, which sized the retired `scad_draft` tool, is still
accepted and ignored; config migration 79 removes it.

Tests:

```bash
cd examples/deerflow-extension-cad-design
uv pip install --python ../../backend/.venv/bin/python -e '.[dev]'
../../backend/.venv/bin/python -m pytest tests -q
```
