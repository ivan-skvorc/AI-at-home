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
written only when every check passed. A STEP file listed in a `cad_build` answer
therefore means a part that passed.

**A part is built until it passes.** The agent runs the loop: build, read what
was measured, repair, build again. The tool keeps what a model loses over a
long one, the count of attempts and the numbers the part was first held to, and
every answer ends with what to do next. See
[Building until it passes](#building-until-it-passes).

It depends on the public `deerflow-extension-api` contract (0.2.13 or newer) and
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
`mounting-plate-1.*`, as a set. So a STEP file from an earlier build that
passed stays beside a later build that failed; the report of each build says
which is which.

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
outside of a cylinder are not holes, and neither is an opening whose walls are
all sloped (a tapered cut, a countersink deeper than the sheet). One drill pass
through two walls of an enclosure, with air between, is one hole, and the answer
says how many walls it crosses; two blind holes that face each other across a
cavity are two. Two limits are known and stated in `measure.py`: the inside of
a shelled cylinder or boss (a cup) reads as one blind hole, and a blind hole
with a domed floor reads as through.

Two things fail the build itself, with the line of the operation, before any
check runs. With only a bounding box to meet, both would otherwise pass as the
part before the operation:

- an operation that removes the whole part (a hole wider than the part, an
  intersection of parts that do not meet);
- a cut, a hole, an intersection or a shell that changes nothing (a pocket cut
  away from the part, a hole drilled beside it, a wall thicker than the part);
- an extrusion, a union or a primitive that adds nothing (posts drawn inside the
  floor, a boss extruded the wrong way).

Only operations the result is made of are held to this; a trial cut the part
never uses is not. A harmless repeat is refused with them, because nothing can
tell it from a miss: the same hole drilled again from the other side, a trim to
a build volume the part already fits. The message says to delete the line.

What the checks do not decide is said in the answer. `notes` names an outline
the script drew and never extruded or cut, a cavity sealed inside the part, a
hole that crosses more than one wall, and a mesh written coarser than usual.
`unchecked` gives the measured volume and hole diameters when the call did not
state them, under the names of the arguments that would check them. The hole
check compares diameters; holes that stop inside the part are listed with the
depth of their cylindrical wall (`blind_depths_mm`).

Three more notes come from loops, where a part can pass its bounding box with
most of its features missing. A script that builds bodies and never joins them
to its result is told how many and on which line they start: the usual slip is
a loop whose every pass builds a body, with the last one alone as the result.
A loop whose every pass starts from the same part keeps only the last pass's
work; the answer says how many passes did work that is not in the result. Not
counted, because nothing is missing: a tool made ready for a pass that never
came (a cutter moved on after its last cut), a part put together again in
every pass, and a trial cut outside a loop. A result made of several loose
bodies is said to be that, its holes are reported as not measured instead of
as none, and `next` gives both ways out: join the bodies, or tell the user
that the tool delivers one solid.

## Building until it passes

The agent runs the loop, and the tool's answers steer it. Nothing here runs a
loop inside the tool: one call is one build.

| The answer holds | Meaning |
| --- | --- |
| `attempt` | Which build of this part this was, within the run (one user message and the work that follows it) |
| `next` | What to do now. After a failed build: attempt *N* of 8, read what failed, change the script, build again under the same name. After a pass: go through what the user asked for that the numbers do not cover, and build again if something is missing |
| `expected_changed` | The expected numbers that differ from those of the part's first build, each with `first` and `now` |

- **The count ends in a report, not in a run limit.** From the eighth build of
  one part in one run, a failed answer says to stop, tell the user what still
  fails with the measured numbers, and build again only when asked. The tool
  still builds: the user may ask for more, and that is a new run with a new
  count. A pass on the eighth build is presented, not sent round again.
- **A part cannot pass by moving its numbers unsaid.** The expected numbers of
  a part's first build stand for what the user asked for. A later build with
  other numbers passes or fails on its own numbers, and its answer and report
  carry `expected_changed` with an instruction to tell the user which changed
  and why. A number stated for the first time on a later build is a check
  added, not a number moved: it is held from then on and not reported. The
  same holes in another order are the same numbers; anything else is compared
  exactly, because a volume range moved by a thousandth is a pocket's worth on
  a large part. The hold ends when the part passes and the user speaks again.
- **A change that did nothing is said to have done nothing.** When a build
  fails exactly as the one before it, the answer says the change did not reach
  the cause.
- **Only a build the script answers for is an attempt.** A busy server, a
  kernel that is still loading, a server without a kernel and arguments that
  were refused are not counted. Their answers say to call again with the same
  arguments, or to stop and tell the user.

Parts are counted by name, per conversation, in memory: case, spacing and
invisible characters aside, signs and punctuation kept, and not by the file
name, which is ASCII and cut at forty characters. A new name is a new part with a new count, which is why every
failed answer says to build again under the same name. A Gateway restart
starts the counts over, and the table holds a thousand parts: the one built
longest ago makes room. The procedure a model follows around these answers is
the `cad-modeling` skill (`skills/public/cad-modeling`).

## What a script may contain

- `import cadquery as cq` and `import math` (both optional: `cq` and `math` are
  the only modules a script is given).
- `name = value` lines, and several names at once: `w, d, t = 60, 40, 6`.
  Values are numbers, strings, `True`, `False`, `None`, tuples and lists of
  numbers, arithmetic on numbers (`+ - * / // % **`), and parts.
  `name += value` and its relatives are the arithmetic they stand for.
- Numbers from a closed table, computed by the reader itself: `math.pi`,
  `math.tau`, `math.sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`,
  `sqrt`, `hypot`, `radians`, `degrees`, `floor` and `ceil`; and `abs`, `min`,
  `max`, `round`, `int`, `float` and `len` on numbers and on lists the script
  states. An index by a whole number the reader knows (`p[0]`, `p[-1]`), and a
  list comprehension with one `for` and no `if`, read item by item like a loop:
  `[(10 * i, 0) for i in range(4)]`. None of these names can be assigned.
- `for` loops over `range(...)` or over a list of numbers or points that the
  script states, with one name or one name per number of a point
  (`for x, y in [(0, 0), (10, 0)]:`). Loops may be nested four deep. A count
  for `range` is a whole number however it was worked out: `50 // 3.5` is
  `14.0` and counts as 14.
- `cq.Workplane(...)` and the methods below, chained or held in variables, and
  `cq.Wire.makeHelix(pitch, height, radius)`, the path of a thread, which only
  `sweep` takes.
- Comments and a docstring. `show_object(name)` is accepted as a way to name the
  result.

The part is the variable `result`, else the object passed to `show_object`, else
the last part assigned. A script that uses the name `result` must leave a part
in it, and `result` and `show_object` may not name two different parts. Units
are millimetres.

A loop is read, not run. Its range or list is known when the script is read,
so the reader goes through the body once per pass, exactly as if the script had
written the statements out, and the program it hands to the kernel is the same
flat list of operations. A failure in a loop names the pass and the value of
the loop variable, exactly and in a few words however long the value, because
one line now stands for many operations. A loop that would not run once is
refused: it is a count that came out as zero. An exponent is capped at 64
unless its base is one or less, which cannot grow: `(-1) ** i` alternates a
sign over any number of passes.

Everything else is refused with the construct and its line: other imports and
`from math import`, attribute access, any other call, `def`, `lambda`,
`class`, `while`, `if`, `break`, `continue`, a loop's `else`, comprehensions
other than the one above, `with`, `try`, f-strings, slices, comparisons,
dunder names. The answer's `error.refused` names what was refused, as the
script wrote it where that is short (`loft`, `import os`, `math.system`). `range(...)` is what a loop runs over
and nothing else: it cannot be assigned or used as a value.
An export line such as `cq.exporters.export(result, "plate.step")` is refused
with its reason: the tool writes the files, after its checks.

Control characters, line separators and text-direction marks (form feed, lone
carriage return, direction overrides) are refused anywhere in the text, comments
included, so no character changes where a line starts or the order it is drawn
in. A script holds one statement per line, and padding that pushes code out of
sight is refused: more than 40 blanks in a row inside a line, more than 40 blank
lines in a row, a line indented more than 80 columns. A tab counts as the eight
columns a viewer draws. A loop's body is indented as one block under its
`for`: a statement beside the end of a header, or one a backslash carries into
a loop from the margin, is refused, because the reader would take it as part
of the loop and a person would not. These rules are what "the script kept
beside the part reads the way the tool read it" rests on; a line may still be
up to 1,000 characters long.
Characters of any language are fine in comments.

The allow-list (`allowlist.py`, 64 methods plus the constructor):

| Group | Methods |
| --- | --- |
| Primitives | `box`, `cylinder`, `sphere`, `wedge` |
| Outlines | `rect`, `circle`, `ellipse`, `polygon`, `slot2D`, `polyline`, `moveTo`, `move`, `lineTo`, `line`, `hLine`, `vLine`, `hLineTo`, `vLineTo`, `threePointArc`, `spline`, `radiusArc`, `sagittaArc`, `tangentArcPoint`, `polarLine`, `polarLineTo`, `close`, `center`, `offset2D` |
| Solids from outlines | `extrude`, `cutBlind`, `cutThruAll`, `revolve`, `loft`, `sweep`, `twistExtrude` |
| Holes | `hole`, `cboreHole`, `cskHole` |
| Edges and walls | `fillet`, `chamfer`, `shell` |
| Patterns | `pushPoints`, `rarray`, `polarArray` |
| Selecting | `faces`, `edges`, `vertices`, `workplane`, `transformed`, `tag`, `workplaneFromTagged`, `end`, `first`, `last` |
| Moving | `translate`, `rotate`, `mirror`, `mirrorX`, `mirrorY` |
| Combining | `union`, `cut`, `intersect` |
| Lettering and splitting | `text`, `split` |

Selector strings are CadQuery's own (`">Z"`, `"|Z and >Y"`, `"%CIRCLE"`). Every
argument is checked against the table before the kernel is loaded: a length must
be a positive number, a plane one of the named planes, a part a part.

A sweep's `path` is an outline the script drew earlier, ending with lines, arcs,
a spline or a circle (`path = cq.Workplane("XZ").polyline([(0, 0), (0, 20),
(20, 20)])`); a path that ends with a solid, a point or a moved copy is refused
before the kernel loads. `combine` takes `True` or `False` on every method: the
kernel's `"cut"` mode is `cut()`. Not exposed: `sweep`'s `normal` and
`auxSpine` (a kernel vector, a second rail), `spline`'s arguments past
`periodic`, `offset2D`'s `"tangent"` kind (`"intersection"` gives the same
sharp corners) and `parametricCurve` (a callable).

Lettering and threads widen two rules of the boundary, each by one thing the
module owns (SECURITY.md):

- **`text` letters in the module's own font**, Liberation Sans, shipped in
  `deerflow_extension_cad/fonts/` with its licence (SIL OFL 1.1). `build.py`
  passes the file's path; a script cannot name a font or a path, since `font`
  and `fontPath` are not in the table. The slim Gateway image has no system
  fonts, and a missing font file fails the build instead of letting the kernel
  fall back to another. Lettering is at most 64 plain ASCII characters. It is
  cut into the part by default (a negative distance from a face); raised
  lettering takes `combine=True` and a positive distance. `halign` and
  `valign` are given by name; `kind` is not offered, since one font file
  letters bold and italic as regular.
- **`cq.Wire.makeHelix(pitch, height, radius)` is the one call on `cq` besides
  `cq.Workplane`.** The reader keeps its numbers as data (at most 200 turns),
  `build.py` makes the wire, and only `sweep`'s `path` takes it: a helix
  passed anywhere else, or given a method, is refused. An M8 x 1.25 and an
  M24 x 3 thread each build valid in under five seconds (`tests/test_build.py`
  holds that gate).

`split(keepTop=..., keepBottom=...)` cuts a part at the workplane, as for a
part too tall for a printer's bed; its arguments are given by name, because the
kernel takes them only as keywords and reads a positional part as a cutting
tool, which is `cut()`'s job.

Parameters that take a file path, a callable, a font or a raw kernel object are
not on the list and will not be added, nor are the methods made of them:
`export`, `exportSvg`, `each`, `eachpoint`, `cutEach`, `invoke`, `apply`, `map`,
`filter`, `sort`, `sketch`, `add`, `val`, `vals`, `findSolid`. The list grows
one method at a time, each with an example that builds and a signature check
against the kernel (`tests/test_build.py`).

## Limits

| Limit | Value | Where |
| --- | --- | --- |
| Script size | 32 KiB, 2,000 syntax nodes, nesting 200 (about 97 chained calls), 300 operations | `interpreter.py` |
| Loops | 1,000 passes in a script, all loops together; nested four deep. The 300 operations are counted after unrolling | `interpreter.py` |
| Reading | 200,000 statements and values read and list items walked, loops unrolled: a script is read in under a second | `interpreter.py` |
| Attempts | 8 builds of one part in one run, then the answer says to stop and report | `tool.py` |
| Lines | one statement per line, at most 1,000 characters, at most 40 blanks or blank lines in a row | `interpreter.py` |
| Numbers | at most 1e12; sizes from 0.0001 to 100,000 mm; coordinates within ±100,000 mm | `interpreter.py`, `allowlist.py` |
| Pattern points | `pushPoints`, `rarray`, `polarArray`: 100 per call, 200 per script; a polygon has at most 100 sides | `allowlist.py` |
| Build time | 20 seconds wall clock, then the process group is killed | `timeout_seconds` |
| Build memory | 4,096 MiB of address space, where the operating system enforces it (Linux) | `memory_mb` |
| Builds at once | half the processor cores, at least one; a call waits 3 seconds for a slot, then is told to call again | `parallel_builds` |
| Mesh | STL: 0.1 mm off the surface and 0.3 rad between facets, in proportion to the size for a part over a metre; coarser (twice, then four times) until it is under 6 MiB. GLB: a mesh for viewing, bounded by the same angle | `build.py` |
| Exported file | 16 MiB read back, then the host's `plugin_outputs` caps apply (8 MiB per file by default) | `tool.py` |

Pattern cost grows faster than the count. `circle().cutThruAll()` on a pattern is
far slower than `hole()`: 100 circles take about 7 seconds on four cores. The
pattern caps keep the ordinary idioms inside the build time; they do not bound
every script. `vertices()` on construction geometry multiplies the points on
the stack, and what stops such a build is the wall clock: it is killed and the
model is told to simplify.

The host's own plugin limits stay as they are: 256 KiB of input, 64 KiB of
result, 30 seconds. File bytes do not count against the result cap.

## The boundary, stated

The interpreter is a security boundary and is written to be audited:

- No code object is ever made from script text. `ast.parse` is its one reader
  (CPython's `compile()` with the flag that stops at the syntax tree), and
  `exec` and `eval` never receive it. A test searches the package for calls to
  `exec`, `eval` and `compile`, and another watches audit events while hostile
  scripts are read.
- The syntax tree is checked against a whitelist of node types before anything
  is evaluated, with an iterative walk and caps on size and depth.
- A script has no branches, functions or `while`, and a `for` loop runs over a
  range or a list the script states, so every number is known before the
  kernel starts. The reader unrolls a loop itself, with Python's own `range` on
  whole numbers it has already checked. The outcome of reading is a flat list
  of operations with plain-data arguments (`interpreter.Program`), the same
  list the statements written out would give; a test compares the two.
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

**In this fork the module ships installed and on**, on Linux (x86-64 and arm64,
glibc 2.31 or newer) and Apple-silicon Macs. A new install gets it with
`make install` or `make up`; an existing one gets it on its next update, when
the config upgrade adds the record below once. The backend installs it from a
committed copy of this directory,
`backend/extensions/sources/deerflow-extension-cad`, which a test keeps
identical to it. The kernel has no wheels for Windows, Intel Macs or a Linux
with an older C library: those hosts install everything else, the record stays,
and `make doctor` says to turn it off.

The kernel is large: `cadquery` and its dependencies take about 1.7 GB on disk
(`vtk` 640 MB, `casadi` 270 MB, the OpenCascade bindings 260 MB). It is loaded
only in a child process while a part is being built, never into the Gateway.

```yaml
plugins:
  - name: cad
    package: deerflow-extension-cad
    use: deerflow_extension_cad:install
    enabled: true
    required: false
    config:
      enabled: true
```

Turn it off and keep the record, then restart:

```bash
make extension-disable NAME=cad
```

That stops the tool; the kernel stays on disk. Do not use
`make extension-remove` on it: the module is part of the repository's own
dependency files, so removing it leaves them modified and the next `git pull`
stops on them.

**The first build after an install or a restart can be slow.** Loading the
kernel reads about 1.2 GB of libraries from disk; warm that takes two seconds,
on a slow or busy disk it can take longer than a build may. The tool then
answers that the kernel was still loading and to call again, and the next call
is quick. After three such answers in a row in one conversation it says to stop
and run `make doctor`, which loads the kernel once and names what is wrong.

In upstream DeerFlow, or any tree without the bundled copy, install it by hand
and restart:

```bash
make extension-install SOURCE="$PWD/examples/deerflow-extension-cad"
```

`config` accepts four values, all optional:

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | `false` registers nothing |
| `timeout_seconds` | `20` | Wall clock for one build, 5 to 25 |
| `memory_mb` | `4096` | Address space for one build, 3,072 to 65,536 |
| `parallel_builds` | half the cores | Builds at once, 1 to 16; each holds several hundred MiB |

Then check it:

```bash
make doctor
```

`make doctor` loads the kernel and then builds a one-millimetre cube through the
real tool. If the kernel cannot load because a system library is missing, it
names the library.

### System libraries

The kernel links three OpenGL dispatch libraries that its wheels do not carry:
`libGL.so.1`, `libGLX.so.0` and `libGLdispatch.so.0`. It never renders with them.
It also loads the system's `libX11.so.6`, which a desktop and the Gateway image
already have.

- **The Gateway image** (`make up`) unpacks them at build time, about 1.5 MB,
  and the dev image (`make docker-start`) does the same with `libX11`.
- **A desktop Linux** usually has them. On a minimal Debian or Ubuntu host:
  `apt-get install libgl1`.

Wheels of the kernel exist for Python 3.12 to 3.14 on Linux x86-64 and arm64
(glibc 2.31 or newer) and Apple-silicon macOS; there are none for Intel macOS.
Windows wheels exist, but the worker is POSIX-only. This package is tested on
Linux only.

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
├── selftest.py     # the one-millimetre cube `make doctor` builds
└── fonts/          # the lettering font, its licence and where it comes from
tests/
├── test_interpreter.py     # what is accepted and what is refused
├── test_worker_process.py  # the parent's hold on the child
├── test_build.py           # the whole tool against the real kernel
└── test_measure.py         # what counts as a hole
```
