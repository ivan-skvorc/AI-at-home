# CAD design page

**Designs** in the sidebar opens a page of its own for designing a part with the
assistant. You describe the part on the left; the assistant writes it as
parametric OpenSCAD in this design's own sandbox container, renders every body,
checks the bodies against each other and against the printer, and each render
becomes a version you can open on the right: the bodies in 3D, the view images,
the check results, the code and the files. It is a bundled extension,
`examples/deerflow-extension-cad-design`, on by default; the maintainer's
reasoning is in [FORK.md §58](../../FORK.md).

The assistant follows the bundled `cad-modeling` skill, the same one an ordinary
chat on a container sandbox uses. The page gives that work a fixed place: one
design, one conversation, one folder of versions.

## Before you start: the CAD container

**The page needs the per-thread container sandbox running the CAD image.** The
model's OpenSCAD and Python run only inside that container, never in the
Gateway, so on the default sandbox (no shell for the agent) the page cannot
work. Set it up once, on the host whose Docker daemon runs the sandbox:

```bash
make sandbox-cad-image                        # builds deerflow-sandbox-cad:local
make sandbox-enable MODE=container IMAGE=cad  # points config.yaml's sandbox at it
```

Then restart the Gateway. If sandbox containers from before are still running,
remove them first (`make stop` does), because a restarted Gateway reuses a
running container whatever its image.

- **The cost is Docker and a large image.** The image is the pinned AIO sandbox
  (`ghcr.io/agent-infra/sandbox:1.11.0`, over 13 GB unpacked) plus OpenSCAD
  2021.01, PrusaSlicer 2.4, the DejaVu and Liberation fonts, and trimesh,
  manifold3d, shapely, rtree and CadQuery 2.7.0 in the image's own Python.
  Nothing publishes the tag: build it locally, and again when the pinned base
  tag moves. The image details are in
  [the CAD image](../../backend/docs/CONFIGURATION.md#the-shipped-example-the-cad-image).
- **Each design's conversation gets its own container**, with the usual
  container-mode limits: 2 GiB of memory by default, an idle timeout, and the
  shell's own network. A STEP export of a large body can need more memory; set
  `DEER_FLOW_SANDBOX_MEMORY=4g` in the Gateway's environment.
- **Without it, the page says so.** When this DeerFlow does not run sandbox
  containers, the page shows a banner with the commands above. A design run that
  has no shell is told to give you the same commands and stop, so it never
  pretends to have rendered anything.

## Using it

1. **Designs → New design.** Describe the part with its sizes in millimetres,
   what moves and what it must fit. Under the prompt are the chat's own
   controls: the model picker (search, sorting, prices), the mode (Flash,
   Reasoning, Pro, Ultra, and Plus and Double Plus Ultracode when Script
   workflows is on) and the reasoning effort. They apply to this design's turns
   and are remembered for the Designs page in this browser, apart from any
   chat's choice. For a mechanism the assistant may first offer two or three
   ways to build it and ask you to pick.
2. **Watch it work.** The conversation follows the run live, with each tool call
   as one line. Every time the assistant renders, a new version appears on the
   right; the page lists the versions again after each tool result and when the
   run ends.
3. **Look at a version.** The newest is selected by default. The tabs:
   - **Preview**: every body of the version in 3D, each in its own colour and
     with its own show and hide switch, with Fit, Top, Front and Iso views and
     the size in millimetres.
   - **Views**: the shaded render and the cross-sections the assistant drew.
   - **Checks**: short summaries of the render, the clash check and the print
     check (below).
   - **Code**: the version's `model.scad`, read-only.
   - **Files**: every file of the version, as download links.
4. **Talk about an older version.** Pick it in the version list and write; your
   message tells the assistant which version you are looking at. The next render
   is still the next number: versions are a history, not branches.
5. **Get the files.** Ask for them, or say you are happy: the assistant writes
   `guide.pdf` (a print and assembly guide), exports STEP and 3MF into the
   version, reads every file back against its body, and packs them into
   `design-v<N>.zip` with a manifest. The print-layout STLs are there from the
   first render.

At 768 px and narrower the page becomes tabs, with the conversation as one of
them.

## What a version holds

The design's conversation always works in `/mnt/user-data/outputs/design`. The
assistant edits one working file, `/mnt/user-data/workspace/design/model.scad`,
in place, and every render writes the next folder, `design/v<N>/`:

| File | What it is |
| --- | --- |
| `model.scad` | The OpenSCAD the version was rendered from |
| `<body>.stl` | One mesh per body, in millimetres, where the body sits in use |
| `assembly.glb` | All bodies in one file for viewers (metres, Y up, one node per body) |
| `report.json` | The render: each body's size, volume, whether it is a closed solid, overlaps as modelled |
| `check.json` | The clash and gap check across poses and sweeps |
| `views/shaded*.png`, `views/sections*.png` | The shaded render and the cross-sections |
| `print/` | Every body laid flat for printing: its STLs, `report.json`, `print.json` and the slicer's `print.gcode` |
| `<body>.step`, `bodies.3mf` | Written on export and read back: one STEP per body and a 3MF of the bodies |
| `export.json` | What export read back: each STL, STEP and the 3MF against the body it came from |
| `guide.pdf` | The print and assembly guide: parts, a page per body, the assembly steps, the checks |
| `design-v<N>.zip` | The delivery: print-layout STLs, 3MF, STEP, `model.scad`, the guide, the views, the results and `manifest.json` with each file's size and sha256 |
| `test/` | Test pieces: the bodies cut by a box around one joint, to print first, with `test.json` |
| `<body>-cq.step` | An editable STEP rebuilt in CadQuery, with `<body>-cq.compare.json` proving it matches the body |

Dimension studies go to `design/studies/<name>/<value>/`, outside the versions,
so the version list stays one entry per render.

The page reads these files through the host's thread file routes, which serve
only the design owner's own outputs and work while a run is still going.

## What the checks mean

Every check runs on the model in the container; none of them is a print.

- **Render**: every body renders, is a closed solid and is one piece unless meant
  otherwise; two bodies that overlap where they sit are a clash as modelled.
- **Clashes and gaps**: the bodies are moved through every pose and swing the
  assistant wrote down, and any overlap in any step is a clash; gaps under the
  clearance you asked for are marked tight, and the smallest gap is reported.
- **Views**: the sections and the shaded render are for the assistant to look at
  (when its model reads images) and for you to check by eye.
- **Print**: the print layout sits on the bed with a flat face; overhangs,
  bridges, one-sided ledges, thin walls and bodies close enough to fuse are
  named, the layout must fit the bed, and PrusaSlicer slices it without supports
  for grams and time. The slicer's own warnings count as problems.
- **Strength**: worked out by hand in the reply, from the loads you gave, with
  the arithmetic and a safety factor; it is not a file and not a simulation.
- **Export**: every STEP, the 3MF and every STL are read back and compared with
  the body they came from (volume within 0.5%, bounding box within 0.05 mm); a
  mismatch fails the export and no zip is written.

## Limits

- **Every result is a check on the model.** Real strength, the fit to a real
  object and how your printer handles a bridge are not checked. Tell the
  assistant how a print came out; it changes the clearance or the feature.
- **The STEP is faceted** unless the assistant rebuilt the body in CadQuery.
  The export STEP is written from the mesh through CadQuery's kernel, each
  triangle a face: good for checking a fit in a CAD program, not for editing
  features. A body over 60,000 triangles is refused for STEP until it is
  rendered with a lower `$fn`. Ask for an editable STEP and the assistant
  rebuilds the body in CadQuery as `<body>-cq.step` and proves it against the
  OpenSCAD body with `cadkit.py compare` (symmetric difference under 1% of the
  volume); round features differ by about 0.3% at `$fn = 48`, because
  OpenSCAD's circles are polygons.
- **OpenSCAD 2021.01 is slow on curves.** The version in the image's Ubuntu
  release renders booleans with CGAL, without the newer Manifold backend, so a
  body with many curved cuts, `minkowski` or a large `hull` can take minutes. A
  body gets 600 seconds per render.
- **2 GiB of memory by default** for the whole container, as above.
- **Two font families.** `text()` can draw with DejaVu and Liberation only.
- **Designs made before this version** keep their conversation, but their
  browser-rendered drafts are no longer shown; ask the assistant to render the
  design again in the container.
- **Designs are yours.** They are stored per user and kept out of the chat list.
  **Delete** moves a design to the Trash, where you can restore it; **Delete
  forever** also deletes its conversation and every version folder.

The design instructions reach design runs only; ordinary chats and subagents
never see them and pay no tokens for them.

## Configuration

The record is in `config.example.yaml` and was added to existing installs by
config migration 78:

```yaml
plugins:
  - name: cad-design
    package: deerflow-extension-cad-design
    use: deerflow_extension_cad_design:install
    enabled: true
    required: false
    config:
      enabled: true
      storage_path: cad-design/designs.sqlite  # relative = under DEER_FLOW_HOME
```

The design store lives under `DEER_FLOW_HOME`, so `make backup` includes it; the
version folders are the conversation's outputs. Config migration 79 removes a
`max_source_bytes` key that sized the old drafts; until it runs, the key is
accepted and ignored. Turn the page off with
`make extension-disable NAME=cad-design` and restart the Gateway; the record
stays, and `make extension-enable NAME=cad-design` turns it back on.
