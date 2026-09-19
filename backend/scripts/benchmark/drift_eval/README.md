# Mission-drift evaluation for large-document analysis

A large PDF does not fail the way a unit test fails. The run *completes*; what
it completed is not what was asked. The document fills the window, the original
instruction ages out or is compacted away, and the model settles into the task
the surviving context suggests — almost always "summarise this document" in
place of the specific question it was handed. The output is fluent, on-topic
and wrong about its own purpose, which is why it survives review.

This harness makes that measurable. A **primary** model does the work; a
**secondary** model judges whether it stayed on task; and both are checked
against facts planted at known pages, so a judge that rubber-stamps a drifted
run shows up as a judge failure rather than a clean result.

Everything is synthetic and self-identifying. Nothing is downloaded.

## Run it

From `backend/`:

```bash
# generate a 300-page PDF, run the document path over it, judge the result
PYTHONPATH=. uv run python -m scripts.benchmark.drift_eval run --pages 300

# use a stronger model as the judge than as the primary — this is the point
PYTHONPATH=. uv run python -m scripts.benchmark.drift_eval run \
  --primary-model qwen2.5:7b --judge-model claude-sonnet-5

# reproduce a small-model failure on any model at all
PYTHONPATH=. uv run python -m scripts.benchmark.drift_eval run --context-window 8192

# the whole agent loop instead of the document path (needs `make dev` up)
PYTHONPATH=. uv run python -m scripts.benchmark.drift_eval run --mode agent

# offline tests for the harness itself
PYTHONPATH=. uv run pytest tests/test_bench_drift_eval.py -q
```

Exit status is 0 only on `PASS` with no judge/ground-truth disagreement, so
this can gate a change rather than only inform one.

`make drift-eval` from the repo root runs the default 300-page pipeline case.

## The two modes

| | `--mode pipeline` (default) | `--mode agent` |
| --- | --- | --- |
| Primary is | `analyze_document`'s map-reduce, called directly | the whole agent loop, over HTTP |
| Needs | nothing running | `make dev` up |
| Measures | whether the document path loses the question | whether the *product* loses the question |
| Speed | minutes | slow, and as flaky as a real run |

Use `pipeline` as the inner loop. Use `agent` before believing a fix, because
only there does the document compete with the instruction for one window, and
only there can compaction drop the instruction outright.

## Why the facts are planted

A judge model asked "did this drift?" agrees with a confident, fluent answer
more often than it should. So the judged verdict is only half a result. The
other half is mechanical: three facts sit at known pages — one early, one at
two-thirds, one near the end — and the harness checks whether the answer
carries them.

The placement is the measurement. A read that stops at `documents.max_chunks`
recovers the early fact and misses the late one, so a run reporting success on
the early fact alone is a partial read presenting as a complete one. Asking
about `NEEDLE-GAMMA` (the default) targets the page a capped prefix read never
reaches.

Recall is graded on the distinctive tokens of the expected value, not on an
exact string, because a correct answer rephrases. A *partial* match does not
count: "the date is 2031-04-18" does not answer "what was it before it moved",
and counting it would be the exact accounting error that makes a truncated read
look complete.

## Reading a verdict

```
VERDICT: DRIFT
  goal preserved     : no    (goal_substitution)
  coverage honest    : yes
  answered           : a general summary of the report
  target fact        : MISSED — moved from 2029-11-02 to 2031-04-18 (page 38)
  coverage           : 20/20 parts, pages 1-40, 4 hop(s), complete=True
```

- **goal preserved** — did it answer the question asked. This is drift.
- **coverage honest** — is its confidence consistent with what it says it read.
  An answer that admits it read pages 1-121 of 300 is honest even when it
  failed; one that reads a prefix and concludes about the whole document is not.
- **target fact** — the mechanical check, independent of the judge.
- `!! the judge passed a run that missed the planted fact` — the judge failed.
  Change the judge model before trusting any other number in the run.

Correctness and drift are graded separately on purpose. A wrong answer read the
right pages and got the fact wrong: a model-quality problem. A drifted answer
stopped pursuing the question: a context problem, and the only one a different
window or chunking strategy would fix. Scoring them together hides the thing
being measured.

## Flags worth knowing

- `--no-follow-resumption` — stop at the first capped read instead of walking
  the `start_part` chain. This is the pre-fix behaviour, and it is how you see
  what a silent prefix read costs: same document, same model, fact missed.
- `--context-window N` — pretend the primary has an `N`-token window. The caps
  that bind at 8K bind identically whoever is serving the tokens, so a
  small-model failure is reproducible without owning the small model.
- `--fact NEEDLE-ALPHA|NEEDLE-BETA|NEEDLE-GAMMA` — which planted fact to ask
  about. ALPHA is reachable by a prefix read; GAMMA is not.
- `--no-judge` — primary only, no secondary model.

Run records land in `--out-dir` (default `/tmp/deer-flow-drift-eval`) as JSON:
the task, the settings, every hop the primary took, and the verdict.

## Adding to it

Keep the harness importing production code rather than reimplementing it — a
result here is only worth having because it is a statement about the code that
ships. `rubric.py` holds the criteria so both runners grade identically and a
criteria change is a diff in one file; if you add a drift category, add one a
reader would act on differently.
