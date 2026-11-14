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

- **The interpreter is a security boundary.** `exec`, `eval`, `compile` and a
  second `getattr` do not belong in this package, and `ast.parse` has one call
  site. A change that lets a value from a script reach a lookup, a file path or
  a subprocess argument needs its own review.
- **A new method is a table row with typed arguments, an example that builds and
  a signature that matches the kernel.** Methods that take a path, a callable, a
  font or a raw kernel object stay off the list. A new string kind needs a
  closed pattern, because CadQuery parses selector strings itself.
- **Arguments are checked before the kernel starts.** CadQuery accepts wrong
  types silently and hangs on non-finite numbers, so the table decides, not the
  kernel.
- **The Gateway process never parses a script and never imports `cadquery`.**
  Both happen in `worker.py`, which talks through files because the kernel
  prints to stdout. Keep `__init__.py` and `tool.py` free of kernel imports.
- **Kernel calls hold the GIL.** Only the parent's wall clock and a kill of the
  process group stop a build; a timeout inside the child does nothing.
- **Pass or fail is decided on the re-imported STEP, by `decide()`.** STEP is
  written last and only for a part that passed every check, so its presence
  means a checked part.
- **The tool description is paid on every request.** The context-fit critical
  check has about ten tokens to spare with this tool installed: shorten
  elsewhere before adding a word, and keep parameter meaning in the names.
