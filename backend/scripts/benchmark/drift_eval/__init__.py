"""Mission-drift evaluation for long-document analysis (fork feature).

A large PDF fails in a way a unit test does not catch: the run *completes*, but
the thing it completed is not the thing that was asked. The document fills the
window, the original instruction ages out or is compacted away, and the model
settles into the task the context now suggests — usually "summarise this
document" in place of the specific question it was given. The answer that comes
back is fluent, on-topic and wrong about its own purpose.

This package makes that failure measurable:

1. ``corpus`` builds a synthetic PDF of known length with facts planted at known
   pages, so ground truth is exact rather than judged.
2. a **primary** model runs the real production path over it — either the
   ``analyze_document`` map-reduce (``pipeline``) or the whole agent loop
   (``agent``).
3. a **secondary** model judges the primary's output against the original task
   (``judge``), and its judgement is itself scored against the planted facts,
   so a judge that rubber-stamps drift is visible as a judge failure.

Everything here is synthetic and self-identifying. No dataset is downloaded.
"""
