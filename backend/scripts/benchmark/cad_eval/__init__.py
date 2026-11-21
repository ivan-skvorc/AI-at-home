"""CAD parts graded on ground truth (fork feature, roadmap item 48).

``cad_build`` decides pass or fail against the numbers the model itself stated,
so its ``passed`` is self-graded: a model that misreads the request and states
the wrong size gets a part that passes. This package scores a configured model
the other way round. Fixed requests (``specs/``) go to the running agent as user
messages; the STEP each run delivers is downloaded, measured again by the CAD
module's ``measure_cli``, and held to truth derived from a reference script the
model never saw.

1. ``specs`` loads the requests, their bands and their truth.
2. ``agent`` drives the Gateway over public HTTP and runs the measurer.
3. ``score`` reads a run's transcript and judges the part, purely.
4. ``derive_truth`` builds each reference once, offline, in the CAD package's
   environment, and stores what it measures.

Protocol and results: docs/guide/cad-eval.md.
"""
