"""Derive each spec's ground truth from its reference script, once, offline.

The truth is what the reference part measures, through the CAD module's own
reader, kernel calls and STEP re-import: the same path a model's part takes. It
is written into ``spec.json`` and never shown to a model.

It needs the CAD kernel, so it runs in the CAD package's environment, not the
backend's:

    cd examples/deerflow-extension-cad
    uv run --no-project python ../../backend/scripts/benchmark/cad_eval/derive_truth.py [spec-id ...]

Each reference part is measured by ``measure_cli``, through the same measurer a
model's part is scored with. A spec whose reference calls an operation the
installed allow-list lacks is skipped with the item that adds it.
``tests/test_eval_specs.py`` in the CAD package rebuilds every reference and
fails when its stored truth has drifted.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

if __package__:
    from .measuring import MeasureCli
    from .score import truth_from
    from .specs import load_specs, write_truth
else:  # run as a script: this directory is on sys.path
    from measuring import MeasureCli
    from score import truth_from
    from specs import load_specs, write_truth

#: Exports of a reference part are small; this only keeps a runaway one from filling the disk.
MAX_EXPORT_BYTES = 64 * 1024 * 1024


def build_step(source: str, directory: Path) -> Path:
    """Read, build and export *source* the way the worker does; the STEP file's path."""
    import cadquery as cq
    from deerflow_extension_cad import build
    from deerflow_extension_cad.interpreter import compile_script

    program = compile_script(source)
    parts = build.build_parts(program, cq)
    names = build.export(build.solid_of(parts[program.result]), cq, directory, MAX_EXPORT_BYTES)[0]
    return directory / names["step"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive each eval spec's ground truth from its reference script.")
    parser.add_argument("ids", nargs="*", help="Spec ids to derive (default: every spec with a reference script).")
    args = parser.parse_args(argv)

    from deerflow_extension_cad.allowlist import METHODS

    measurer = MeasureCli()
    problem = measurer.problem()
    if problem:
        print(f"derive_truth: {problem}")
        return 2
    specs = [spec for spec in load_specs(ids=args.ids or None) if spec.has_reference]
    for spec in specs:
        missing = spec.missing_operations(METHODS)
        if missing:
            print(f"{spec.id}: skipped, needs " + "; ".join(f"item {item} ({', '.join(names)})" for item, names in missing.items()))
            continue
        with tempfile.TemporaryDirectory() as scratch:
            truth = truth_from(measurer.measure(build_step(spec.reference.read_text(encoding="utf-8"), Path(scratch))), positions=spec.hole_positions)
        write_truth(spec, truth)
        print(f"{spec.id}: {json.dumps(truth)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
