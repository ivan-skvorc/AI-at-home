# CAD extension

One model tool, `cad_build`: a CadQuery script is read by an allow-list
interpreter, built in a child process, measured and checked. The script is never
executed. `README.md` states the design; FORK.md §51 and `SECURITY.md` state the
boundary.

```bash
cd examples/deerflow-extension-cad
uv venv --python 3.12 && uv pip install -e ../../backend/packages/extension-api && uv pip install -e ".[dev]"
uv run --no-project pytest -q                        # the kernel tests skip without cadquery
cd ../../backend && python -m pytest tests/test_cad_extension.py tests/test_cad_runtime_deps.py -q   # the host half, no kernel
```

- **This directory is the source; `backend/extensions/sources/deerflow-extension-cad`
  is what every install runs.** After any edit here, copy the directory over the
  snapshot (without `__pycache__`); `test_bundled_cad_extension.py` fails until
  the two are identical.
- **The interpreter is a security boundary.** Calls to `exec`, `eval` and
  `compile` and a second script-driven `getattr` do not belong in this package,
  and `ast.parse` has one call site. A change that lets a value from a script reach a lookup, a file path or
  a subprocess argument needs its own review.
- **A new method is a table row with typed arguments, an example that builds and
  a signature that matches the kernel.** Methods that take a path, a callable, a
  font or a raw kernel object stay off the list. A new string kind needs a
  closed pattern, because CadQuery parses selector strings itself. After a
  change to the table, regenerate the skill's page, which a test compares:
  `python deerflow_extension_cad/allowlist.py > ../../skills/public/cad-modeling/references/operations.md`.
- **A loop is unrolled by the reader and never reaches the kernel as a loop.**
  What it runs over must be known when the script is read, so the program stays
  the flat list the written-out statements give. A construct whose outcome
  depends on a build (`if` on a measurement, `while`) does not fit that and
  stays refused; every construct added to the reader widens the boundary.
  Passes do not bound reading time, `MAX_WORK` does: count there whatever a
  new construct makes the reader walk.
- **The tool's answers are the loop's control.** A model repairs and rebuilds on
  what `next` says, and a host test pins each sentence to its state. Reword one
  only together with `skills/public/cad-modeling`, whose test quotes them.
- **Arguments are checked before the kernel starts.** CadQuery accepts wrong
  types silently and hangs on non-finite numbers, so the table decides, not the
  kernel.
- **The Gateway process never parses a script and never imports `cadquery`.**
  Both happen in `worker.py`, which talks through files because the kernel
  prints to stdout. Keep `__init__.py` and `tool.py` free of kernel imports.
- **Kernel calls hold the GIL.** Only the parent's wall clock and a kill of the
  process group stop a build; a timeout inside the child does nothing.
- **Pass or fail is decided on the re-imported STEP, by `decide()`.** STEP is
  written last and only for a part that passed every check, so a STEP listed in
  an answer means a checked part.
- **`findSolid()` walks back to the parent.** After an operation that empties
  the part it returns the part as it was before, which then passes. `build.py`
  fails an operation that leaves no solid, and a cut that changes no volume.
- **The kernel works on several cores and keeps a mesh on the shape.** The
  processor backstop is counted per core, builds take slots, and a coarser mesh
  needs the finer one cleared first.
- **The kernel's point classifier is the fallback, not the way.** On a grid of
  holes it takes 0.4 s a point; `measure.py` counts crossings on generic rays.
- **Clean-up must not depend on a task getting to run.** A task cancelled
  before its first step does nothing, and the host also runs tools on loops
  that end at once: the kill is direct and the release is a done callback.
- **The tool description is paid on every request.** The context-fit critical
  check has under forty tokens to spare with this tool on every request, nine
  with a workflows option on: shorten elsewhere before adding a word, and keep
  parameter meaning in the names. A small model gets the sentences before
  `Methods:` and nothing after, so what it cannot do without goes first.
