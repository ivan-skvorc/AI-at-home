"""Names shared by the actions, the middleware and the store."""

from __future__ import annotations

import re

NAMESPACE = "cad-design"
#: The one folder a design's thread renders into. Each design has its own thread, so
#: the path is fixed; cadkit writes every render as the next ``v<N>/`` under it, and
#: those folders are the design's versions.
FOLDER = "/mnt/user-data/outputs/design"
#: The working file the model edits in place; every render copies it into its version.
WORKING_FILE = "/mnt/user-data/workspace/design/model.scad"
#: The tool a run needs to drive cadkit; without it the run has no container shell.
BASH_TOOL = "bash"
ID = re.compile(r"[0-9a-f]{32}")
RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
