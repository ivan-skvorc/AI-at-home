# CAD eval: parts graded on ground truth

`make cad-eval` scores one configured model on a fixed set of part requests. It
sends each request to the running agent as a user message, downloads the STEP
file the run delivered, measures it again, and compares it with numbers the
model never saw. It is a fork feature (roadmap item 48), opt-in and out of CI.

## Why a second grade

`cad_build` passes a part when the part meets the numbers the model passed in
with the script. Those numbers are the model's own reading of the request, so
a model that misreads "60 mm tall" as 40 gets a part that passes. That pass is
self-graded. The eval measures the delivered part against truth taken from a
reference part, and it reports how often a part the model presents as finished
is actually right (claim precision) beside how often `cad_build` said it
passed (self-pass).

## Run it

The stack must be up (`make dev`) with the CAD module on, and the model must be
configured in `config.yaml`.

```bash
make cad-eval MODEL=qwen3-32k                  # every part spec, three samples each
make cad-eval MODEL=qwen3-32k K=1 BAND=holes   # one band
make cad-eval MODEL=qwen3-32k SPEC=h01-mounting-plate,f02-open-box
make cad-eval MODEL=qwen3-32k QUANT=Q4_K_M     # record a local model's quantisation in the row
make cad-eval MODEL=gpt-big MAX_COST=2         # stop starting samples after 2 units of spend
```

From `backend/`, the same runner takes flags:
`PYTHONPATH=. uv run python -m scripts.benchmark.cad_eval run --model <name>`.
`... cad_eval list` prints the spec set and its hash without running anything.
If the Gateway requires authentication, set `DEER_FLOW_API_TOKEN` (or
`DEER_FLOW_CAD_EVAL_TOKEN`) in the environment; the token is never a flag.

Use `K=3` or more for a row you mean to compare. One sample of twenty specs has
a standard error of about 11 percentage points, which hides most changes.

### When it refuses to start

It exits without running anything, with status 3 and a message, when:

- no Gateway answers at `--base-url` (default `http://localhost:8001`);
- `/api/plugins` lists no `cad` namespace with `cad_build`, because the CAD
  module is not installed or not enabled;
- the model is not configured on the Gateway. The Gateway would otherwise
  run the request on its default model, and the row would carry the wrong name;
- `deerflow_extension_cad.measure_cli` is not importable by the measuring
  Python (`--measure-python`, default the backend's own). The backend
  environment has it once the bundled CAD module ships item 57.

Without `MODEL` it prints its usage and exits with status 2. A completed run
exits 0 whatever its pass rate, because the eval measures and does not gate. A
run that stopped early or had samples that produced nothing to score exits 1.

### Without the CAD module

`make cad-eval MODEL=... NO_MODULE=1` runs one extra spec (`m01-no-module`)
against a Gateway whose CAD module is turned off (`make extension-disable
NAME=cad`, then restart). The model is asked for a STEP file, and the run passes
when it calls no CAD tool and its reply tells the user that `make doctor` on the
server says why. It refuses to start while the module is on.

## How one sample is scored

1. The request text, followed by a fixed sentence asking the model not to ask
   questions, goes to `POST /api/runs/wait` in a new thread. The model is named
   as an explicit selection, so an unknown name fails the run.
2. The transcript is read from the run's event store
   (`/api/threads/{id}/runs/{run_id}/messages`), which keeps every tool result.
   The thread state is not used, because compaction drops older tool results.
3. Every `cad_build` call is paired with its answer. The delivered part is the
   newest build that answered `passed: true`; its STEP file is downloaded
   through the artifact route.
4. `python -I -m deerflow_extension_cad.measure_cli <step>` re-imports and
   measures it, and `judge_truth` holds it to the spec's truth. `passed` is
   never the score.

A spec asks for one part. A kit, such as the box and lid, is one build of two
bodies. A run that builds the box and the lid as two parts delivers only the
newest one, and that part fails its truth.

## What the row reports

| Column | Meaning |
| --- | --- |
| Truth pass (95% CI) | Samples whose delivered STEP met the truth, with the Wilson 95% interval. Samples that produced nothing to score count as fails and are named in the run's output |
| Self-pass | Samples in which some `cad_build` call passed by its own checks |
| Claim precision | Of the samples presented as finished, the share that met the truth. A sample is presented as finished when the run's last `cad_build` call passed and the run ended with a reply |
| Single-shot | Samples whose first `cad_build` call passed and met the truth |
| Repair rounds | Average failed builds before the first passing one, over the samples that passed. Builds to pass is this plus one |
| Refusals | Builds the reader refused, by `error.refused` (the construct's name, such as `loft` or `import os`). A module from before item 55 has only `error.construct`, which is counted instead |
| view_image | Calls to `view_image` across all samples |
| Tokens / sample, Spend | From `/api/threads/{id}/token-usage`; spend is in the Gateway's pricing currency, and a Gateway spend cap (HTTP 402) stops the run |
| Module, CadQuery | `module_version` and `cadquery_version` from the delivered `report.json`, once the module writes them (item 57) |
| Skill | The first 12 hex digits of a hash over `skills/public/cad-modeling` |
| Specs | The spec-set hash and the scope (`all`, a band, or `specs`) |

Rows are comparable only when the spec-set hash matches. The hash covers every
request, truth and reference script and the fixed sentence added to each
request. The full record, with each sample's transcript and STEP files, goes
to `--out-dir` (default `/tmp/deer-flow-cad-eval`) and is never committed.

## The specs

The specs live in `backend/scripts/benchmark/cad_eval/specs/<id>/`. Each holds
`spec.json` (the request, its band, how the bounding box is compared, and the
truth) and `reference.py`, a script in the dialect `cad_build` reads. All
twenty requests and reference parts were written for this fork.

| Band | Specs |
| --- | --- |
| Prismatic | spacer block, L-bracket, three-step block, hexagonal prism, threshold ramp, U-channel |
| Holes, patterns and pockets | mounting plate (a 2 x 2 pattern), bolt flange (a polar pattern), pocketed plate, slotted plate, countersunk strip, counterbored block, name tag |
| Fillets, shells and two-part fits | rounded plate, open box, chamfered cube, control knob, V-groove pulley, captive pin, box and lid |

Four specs wait on other roadmap items, and their `spec.json` lists them under
`needs`:

- The name tag needs `text` (item 59), and the pulley needs `revolve` (item 56).
  Until those operations are on the allow-list, the CAD package's test skips
  their reference parts and names the item.
- The captive pin and the box and lid are two bodies. Their reference parts
  build today, but `cad_build` passes two bodies only with its `bodies`
  argument (item 51). Before that a run ends without a delivered part, which
  is the honest result.

### Truth and its tolerances

The truth is what the reference part measures through the CAD module's own
reader, kernel calls and STEP re-import: the number of solids, the bounding
box, the volume and, for a one-solid part, the drilled hole diameters. A part
meets it when:

- it has the same number of valid, closed solids;
- each bounding-box side is within 1 mm. With orientation `z`, the height must
  match and the two footprint sides may be swapped. With `free`, the three
  sides are compared in any order, for parts whose request fixes no direction;
- its volume is within 2%;
- for a one-solid part, it has the same hole diameters, each within 0.1 mm.
  The hole check is what fails a plate that forgot its holes, because those
  can be under 2% of the volume.

`derive_truth.py` writes the truth. It runs in the CAD package's environment,
because it needs the kernel:

```bash
cd examples/deerflow-extension-cad
uv run --no-project python ../../backend/scripts/benchmark/cad_eval/derive_truth.py [spec-id ...]
```

`examples/deerflow-extension-cad/tests/test_eval_specs.py` rebuilds every
reference part in CI's extension package job, judges it with the same
`judge_truth`, and fails when the stored truth no longer matches what the
reference builds. The backend's offline test, `test_bench_cad_eval.py`, drives
the runner against a fake Gateway with synthetic transcripts.

### Adding a spec

1. Create `specs/<band letter><nn>-<name>/spec.json` with `id`, `band`,
   `title`, `request` and `orientation`, plus `needs` if its reference calls an
   operation the allow-list does not have yet.
2. Write `reference.py` in the allow-listed dialect, with every dimension in a
   named variable, and run `derive_truth.py <id>`.
3. Run the CAD package's `tests/test_eval_specs.py` and the backend's
   `tests/test_bench_cad_eval.py`, whose spec count stays between 15 and 20.

A request the allow-list cannot express at all can carry `expected_refused:
<construct>` instead of a reference part. Its refusals are recorded, and they
count toward the case for item 50.

## Sources

The idea of grading a generated CAD part against a reference part by its
bounding box and volume comes from
[CadQueryEval](https://github.com/danwahl/cadqueryeval), whose code is MIT
licensed, and the CadEval benchmark before it. No task text, reference part or
ground truth was copied from either: the licence of their data is not
confirmed. Every request, reference script and truth here is this fork's own.

## Results

Each run prints one row in this format. Add rows here with the date of the run;
keep older rows, and compare only rows with the same spec-set hash.

| Date | Model | Quant | Window | Module | CadQuery | Skill | Specs | k | Truth pass (95% CI) | Self-pass | Claim precision | Single-shot | Repair rounds | Refusals | view_image | Tokens / sample | Spend |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

No live rows yet. The first rows, one local model with a 32K window and one
cloud model at `K=3` plus a baseline on main's module, need a model on the
owner's host.
