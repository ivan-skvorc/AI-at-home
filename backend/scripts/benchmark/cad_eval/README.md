# CAD eval

Scores a configured model's CAD parts against ground truth it never saw:
fixed requests go to the running agent, and the STEP each run delivers is
measured again by the CAD module's `measure_cli`. The protocol, the columns of
a result row and the dated results are in
[docs/guide/cad-eval.md](../../../../docs/guide/cad-eval.md).

```bash
# from the repository root, with `make dev` up
make cad-eval MODEL=<name from config.yaml> [K=3] [BAND=prismatic|holes|fits] [SPEC=<id,...>]

# from backend/
PYTHONPATH=. uv run python -m scripts.benchmark.cad_eval list
PYTHONPATH=. uv run python -m scripts.benchmark.cad_eval run --model <name> --k 3
PYTHONPATH=. uv run pytest tests/test_bench_cad_eval.py -q

# the truth, in the CAD package's environment (it needs the kernel)
cd ../examples/deerflow-extension-cad
uv run --no-project python ../../backend/scripts/benchmark/cad_eval/derive_truth.py
uv run --no-project pytest -q tests/test_eval_specs.py
```

| File | Role |
| --- | --- |
| `specs.py` | Loads `specs/<id>/spec.json`, the bands and the spec-set hash |
| `score.py` | Pure scoring: the transcript, the truth judgement, the Wilson interval, the row |
| `agent.py` | The Gateway over public HTTP |
| `measuring.py` | The measurer: `measure_cli` as a child process, for scored parts and reference parts alike |
| `derive_truth.py` | Builds each `reference.py` and stores what `measure_cli` measures as the truth |
| `__main__.py` | The CLI: preconditions, the sample loop, the report and the run record |

`specs.py`, `score.py` and `measuring.py` import only the standard library,
because the CAD package's test loads them by path in an environment without
DeerFlow and scores every reference part through them. Keep them that way.
