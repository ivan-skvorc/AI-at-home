# DeerFlow CAD extension

For the shared edit → test → packaging check → install workflow, see the
[existing-example guide](../README.md).

This package adds one model tool, `cad_build`. A model writes a short
[CadQuery](https://cadquery.readthedocs.io/) script; the tool builds the part,
measures it, compares the measurements with the numbers the model said the part
must meet, and writes the files into the conversation's outputs.

**The script is never executed.** It is parsed into a syntax tree and read by an
interpreter that performs only an allow-list of CadQuery operations. That is why
the tool works on the default install, where `LocalSandboxProvider` gives the
agent no shell, and why installing it does not weaken that decision. It also
works with the conversation's internet switch off.

**The tool decides pass or fail, not the model.** STEP, STL and GLB files are
written only when every check passed. A STEP file in a conversation's outputs
therefore means a part that passed.

It depends on the public `deerflow-extension-api` contract (0.2.12 or newer) and
on `cadquery` 2.8.0, pinned. It never imports `deerflow.*` or `app.*`.

## What you get

Ask in any conversation, in any mode, on any model:

> Make a 60 × 40 × 6 mm mounting plate with two 4 mm through holes, 30 mm apart.

The model calls `cad_build` with a script and the expected numbers. A build that
passes writes five files, which open in the artifact panel and are listed in the
Files view:

| File | Content |
| --- | --- |
| `mounting-plate.py` | The script, as given |
| `mounting-plate.report.json` | Expected and measured numbers, each check, pass or fail |
| `mounting-plate.step` | The part for a CAD program |
| `mounting-plate.stl` | The mesh for a slicer |
| `mounting-plate.glb` | The mesh for a viewer |

A build that fails a check writes the script, the report and
`mounting-plate.failed.glb`, so the wrong shape can still be looked at. It
writes no STEP and no STL. A script that is refused, or that the kernel cannot
build, leaves the script and the report only.

A second build of the same name never replaces the first: its files are
`mounting-plate-1.*`, as a set.

## What the tool checks

The STEP file that was just written is imported again and measured. The model
does not get a vote.

| Check | Passes when |
| --- | --- |
| One closed solid | The file holds exactly one solid, it is valid, its shells are closed and its volume is positive |
| Bounding box | Each side is within 0.01 mm or 0.1 % of `bbox_xyz_mm`, whichever is larger |
| Volume | The volume is inside `volume_min_max_mm3` (only when given) |
| Holes | The drilled holes match `hole_diameters_mm`, one entry per hole, same tolerance (only when given) |

A hole is a full-circle, concave cylindrical wall with air inside that is open at
one end or both. A counterbore or countersink counts once, with its drill
diameter. Fillets, rounded pocket corners, the ends of a slot, a boss and the
outside of a cylinder are not holes. Two limits are known and stated in
`measure.py`: the inside of a shelled cylinder (a cup) reads as one blind hole,
and a blind hole with a domed floor reads as through.

## What a script may contain

- `import cadquery as cq` (optional: `cq` is the only name a script is given).
- `name = value` lines. Values are numbers, strings, `True`, `False`, `None`,
  tuples and lists of numbers, arithmetic on numbers (`+ - * / // % **`), and
  parts.
- `cq.Workplane(...)` and the methods below, chained or held in variables.
- Comments and a docstring. `show_object(name)` is accepted as a way to name the
  result.

The part is the variable `result`, else the object passed to `show_object`, else
the last part assigned. Units are millimetres.

Everything else is refused with the construct and its line: other imports,
attribute access, any other call, `def`, `lambda`, `class`, loops, `if`,
comprehensions, `with`, `try`, f-strings, subscripts, comparisons, dunder names.

Control characters and invisible Unicode (zero-width characters, direction
overrides, line separators) are refused anywhere in the text, comments included:
the script kept beside the part reads the way the tool read it. Visible
characters of any language are fine in comments.

The allow-list (`allowlist.py`, 46 methods plus the constructor):

| Group | Methods |
| --- | --- |
| Primitives | `box`, `cylinder`, `sphere` |
| Outlines | `rect`, `circle`, `ellipse`, `polygon`, `slot2D`, `polyline`, `moveTo`, `move`, `lineTo`, `line`, `hLine`, `vLine`, `hLineTo`, `vLineTo`, `threePointArc`, `close`, `center` |
| Solids from outlines | `extrude`, `cutBlind`, `cutThruAll` |
| Holes | `hole`, `cboreHole`, `cskHole` |
| Edges and walls | `fillet`, `chamfer`, `shell` |
| Patterns | `pushPoints`, `rarray`, `polarArray` |
| Selecting | `faces`, `edges`, `vertices`, `workplane`, `tag`, `workplaneFromTagged` |
| Moving | `translate`, `rotate`, `mirror`, `mirrorX`, `mirrorY` |
| Combining | `union`, `cut`, `intersect` |

Selector strings are CadQuery's own (`">Z"`, `"|Z and >Y"`, `"%CIRCLE"`). Every
argument is checked against the table before the kernel is loaded: a length must
be a positive number, a plane one of the named planes, a part a part.

Methods that take a file path, a callable, a font or a raw kernel object are not
on the list and will not be added: `export`, `exportSvg`, `text`, `each`,
`eachpoint`, `cutEach`, `invoke`, `apply`, `map`, `filter`, `sort`, `sketch`,
`add`, `val`, `vals`, `findSolid`. The list grows one method at a time, each
with an example that builds and a signature check against the kernel
(`tests/test_build.py`).

## Limits

| Limit | Value | Where |
| --- | --- | --- |
| Script size | 32 KiB, 2,000 syntax nodes, nesting 200, 300 operations | `interpreter.py` |
| Numbers | at most 1e12; sizes and coordinates from 0.0001 to 100,000 mm | `interpreter.py`, `allowlist.py` |
| Pattern points | 100 per call, 200 per script | `allowlist.py` |
| Build time | 20 seconds wall clock, then the process group is killed | `timeout_seconds` |
| Build memory | 4,096 MiB of address space, where the operating system enforces it (Linux) | `memory_mb` |
| Exported file | 16 MiB read back, then the host's `plugin_outputs` caps apply | `tool.py` |

Pattern cost grows faster than the count. `circle().cutThruAll()` on a pattern is
far slower than `hole()`: 100 circles take about 7 seconds on four cores.

The host's own plugin limits stay as they are: 256 KiB of input, 64 KiB of
result, 30 seconds. File bytes do not count against the result cap.

## The boundary, stated

The interpreter is a security boundary and is written to be audited:

- `ast.parse` is the only reader of script text. `exec`, `eval` and `compile`
  never touch it; a test searches the package for them, and another watches
  audit events while hostile scripts are read.
- The syntax tree is checked against a whitelist of node types before anything
  is evaluated, with an iterative walk and caps on size and depth.
- A script has no loops, branches or functions, so every number is known before
  the kernel starts. The outcome of reading is a flat list of operations with
  plain-data arguments (`interpreter.Program`).
- The only attribute lookup driven by a script is in `build.run_program`, for a
  method name that is a key of the allow-list.
- Reading and building both happen in a child process started with `python -I`,
  in an empty temporary directory, with an environment that carries nothing from
  the Gateway. The Gateway process never parses the script and never loads the
  kernel. The parent holds the wall clock and kills the process group, because a
  kernel operation cannot be interrupted from inside.

This is not a sandbox for the kernel itself. A crafted script that makes the
geometry kernel misbehave inside its allow-listed operations is bounded by the
child process, its limits and its clean environment, not by the interpreter.

## Install

The kernel is large: `cadquery` and its dependencies take about 1.7 GB on disk
(`vtk` 640 MB, `casadi` 270 MB, the OpenCascade bindings 260 MB). Only an install
that wants CAD pays for it.

```bash
make extension-install SOURCE="$PWD/examples/deerflow-extension-cad"
```

Restart DeerFlow afterwards. The manager adds this entry to `config.yaml`:

```yaml
plugins:
  - name: cad
    package: deerflow-extension-cad
    use: deerflow_extension_cad:install
    enabled: true
    required: false
    config: {}
```

`config` accepts three values, all optional:

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | `false` registers nothing |
| `timeout_seconds` | `20` | Wall clock for one build, 5 to 25 |
| `memory_mb` | `4096` | Address space for one build, 3,072 to 65,536 |

Then check it:

```bash
make doctor
```

With the extension installed, `make doctor` builds a one-millimetre cube through
the real tool. If the kernel cannot load because a system library is missing, it
names the library.

### System libraries

The kernel links three OpenGL dispatch libraries that its wheels do not carry:
`libGL.so.1`, `libGLX.so.0` and `libGLdispatch.so.0`. It never renders with them.

- **The Gateway image** (`make up`) unpacks them at build time, about 1.5 MB.
- **A desktop Linux** usually has them. On a minimal Debian or Ubuntu host:
  `apt-get install libgl1`.

Wheels of the kernel exist for Python 3.12 on x86-64 and arm64 Linux, macOS and
Windows. This package is tested on Linux only.

## Run the package tests

```bash
cd examples/deerflow-extension-cad
uv venv --python 3.12
uv pip install -e ../../backend/packages/extension-api
uv pip install -e ".[dev]"
uv run --no-project pytest -q
uv run --no-project ruff check .
uv run --no-project ruff format --check .
```

The interpreter and the child-process tests need no kernel. The tests that build
real parts are skipped when `cadquery` is not installed.

## Package layout

```text
deerflow_extension_cad/
├── __init__.py     # install(): registers the tool; imports no kernel
├── allowlist.py    # the operations a script may ask for, as data
├── interpreter.py  # text → allow-listed operations, or a refusal with its line
├── build.py        # operations → kernel calls; STEP, STL and GLB export
├── measure.py      # the re-imported STEP: solids, bounding box, volume, holes
├── worker.py       # the child process
├── tool.py         # the handler: child process, limits, pass or fail, file writes
└── selftest.py     # the one-millimetre cube `make doctor` builds
tests/
├── test_interpreter.py     # what is accepted and what is refused
├── test_worker_process.py  # the parent's hold on the child
├── test_build.py           # the whole tool against the real kernel
└── test_measure.py         # what counts as a hole
```
